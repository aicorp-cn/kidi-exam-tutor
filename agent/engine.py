"""Pipeline engine — orchestrates OCR → Stage 1 → Stage 2 → Store → SSE.

Uses DeepSeek Tool Calling with Strict Schema (Beta endpoint).
Falls back to response_format + lightweight validation if Beta is unavailable.
"""

import asyncio
import json
import time
from pathlib import Path

from openai import AsyncOpenAI, APIError, APITimeoutError, RateLimitError

from config import config
from ocr import ocr_images, OCRError
from prompts import (
    STAGE1_SYSTEM_PROMPT, STAGE2_SYSTEM_PROMPT,
    build_stage1_user_prompt, build_stage2_user_prompt,
)
from tools import (
    STAGE1_TOOLS, STAGE2_TOOL_NAME, VARIANT_TOOL_NAME, STAGE2_TOOL_DEFS,
    get_tool_definition, strip_strict, format_questions_block,
)
from pipeline_log import (
    log_ocr_start, log_ocr_result,
    log_stage1_entry, log_stage1_result,
    log_llm_start, log_llm_result,
    log_trace, log_variant_detect, log_stage_retry,
)
from vocab import process_vocabulary

# ── Client init: cache two clients (strict + fallback) per session ──

_STRICT_CLIENT: AsyncOpenAI | None = None
_FALLBACK_CLIENT: AsyncOpenAI | None = None
# Per-session strict mode — session_id → bool. Prevents cross-session pollution.
_strict_mode: dict[str, bool] = {}


def _get_strict_client() -> AsyncOpenAI:
    """Return cached strict-mode client (beta endpoint)."""
    global _STRICT_CLIENT
    if _STRICT_CLIENT is None:
        _STRICT_CLIENT = _build_client(use_strict=True)
    return _STRICT_CLIENT


def _get_fallback_client() -> AsyncOpenAI:
    """Return cached fallback client (non-strict endpoint)."""
    global _FALLBACK_CLIENT
    if _FALLBACK_CLIENT is None:
        _FALLBACK_CLIENT = _build_client(use_strict=False)
    return _FALLBACK_CLIENT


def _client_for_session(session_id: str) -> AsyncOpenAI:
    """Return the right client for a given session's strict mode."""
    return _get_strict_client() if _strict_mode.get(session_id, True) else _get_fallback_client()


def _build_client(use_strict: bool) -> AsyncOpenAI:
    """Build AsyncOpenAI client. If use_strict, use beta endpoint."""
    api_key = config.llm_api_key()
    s1 = config.llm_for("stage1")
    if not api_key:
        raise RuntimeError("DeepSeek API key not configured.")
    url = s1["base_url"] if use_strict else s1["fallback_url"]
    return AsyncOpenAI(
        api_key=api_key,
        base_url=url,
        timeout=s1["timeout"],
        max_retries=s1["max_retries"],
    )


def _maybe_fallback(session_id: str = "", status_code: int = 0):
    """If Strict Mode is active and we hit a transient/compatibility error, fall back.

    Updates ONLY this session's strict mode — never affects other concurrent sessions.
    """
    if not _strict_mode.get(session_id, True):
        return  # already in fallback mode for this session

    if status_code and 400 <= status_code < 500 and status_code != 429:
        _strict_mode[session_id] = False
        if session_id:
            log_trace(session_id, f"strict_disabled:http_{status_code}")
        return

    # 5xx / timeout / rate-limit → try fallback URL
    s1 = config.llm_for("stage1")
    if s1["base_url"] == s1["fallback_url"]:
        _strict_mode[session_id] = False
        return
    _strict_mode[session_id] = False
    if session_id:
        log_trace(session_id, "strict_mode_fallback")


def _using_strict(session_id: str) -> bool:
    """Check if a session is in strict mode."""
    return _strict_mode.get(session_id, True)


# ── JSON parsing with LLM output resilience ──

_CHINESE_QUOTE_RE = __import__('re').compile(
    r'[\u3000-\u303f\u3040-\u30ff\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]'
    r'"'
    r'[\u3000-\u303f\u3040-\u30ff\u4e00-\u9fff\uf900-\ufaff\uff00-\uffef]'
)


def _parse_json(raw: str) -> dict | None:
    """Parse JSON from LLM tool call arguments. Returns dict or None.

    Chinese-quote fast-fail: if raw contains ASCII " between CJK characters,
    return None immediately — this JSON is structurally broken by the LLM
    using ASCII quotes inside Chinese text values.
    """
    if not raw or not raw.strip():
        return None

    if _CHINESE_QUOTE_RE.search(raw):
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    try:
        decoder = json.JSONDecoder()
        return decoder.raw_decode(raw)[0]
    except json.JSONDecodeError:
        pass

    return None


def _validate_structure(data: dict, schema: dict) -> list[str]:
    """Check required fields exist. Only used when Strict Mode is unavailable."""
    errors = []
    for field in schema.get("required", []):
        if field not in data:
            errors.append(f"Missing required field: {field}")
    return errors


# ── Config helper ──

def _get_stage_params(stage: str) -> dict:
    """Return merged LLM params for a stage."""
    return config.llm_for(stage)


# ── Error detail extraction (logs only, never user-facing) ──

def _api_error_detail(e: APIError) -> str:
    """Extract error detail for pipeline.log — NOT for user-facing messages."""
    try:
        if e.body and isinstance(e.body, dict):
            err = e.body.get("error", {})
            return err.get("message", err.get("type", str(e.status_code)))
    except Exception:
        pass
    return str(e.status_code)


# ── SSE broadcast ──

async def _broadcast(queues: dict, session_id: str, stage: str,
                     status: str, data: dict = None):
    """Send SSE event to all queues for a session."""
    qs = list(queues.get(session_id, []))  # snapshot to avoid mutation race
    event = {"stage": stage, "status": status, **(data or {})}
    for q in qs:
        await q.put(event)


# ── Heartbeat during long Stage 2 calls ──

async def _heartbeat_loop(queues: dict, session_id: str, interval: float = 5.0):
    """Send periodic heartbeat events during long-running Stage 2."""
    while True:
        await asyncio.sleep(interval)
        await _broadcast(queues, session_id, "stage2", "progress",
                         {"status": "generating"})


# ═══════════════════════════════════════════════════════════════
# Stage 1 Call
# ═══════════════════════════════════════════════════════════════

async def _stage1_call(ocr_text: str, page_count: int,
                      session_id: str = "") -> dict:
    """Call DeepSeek to parse OCR text into structured JSON.

    Returns dict with exam_type, passage, questions.
    Retries once on tool_call failure or structure errors (non-strict mode).
    """
    client = _client_for_session(session_id)
    params = _get_stage_params("stage1")
    tools = STAGE1_TOOLS if _using_strict(session_id) else strip_strict(STAGE1_TOOLS)

    chinese_quote_context = None

    for attempt in range(params["retry_attempts"]):
        try:
            messages = [
                {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
                {"role": "user", "content": build_stage1_user_prompt(ocr_text, page_count)},
            ]
            if chinese_quote_context:
                messages.append({
                    "role": "user",
                    "content": (
                        "上一次生成失败：JSON 字段值中检测到 ASCII 英文双引号 \"。\n\n"
                        f"违规位置（周围文本）：{chinese_quote_context}\n\n"
                        "请回顾工具描述中的【JSON 字段值符号约定】，"
                        "根据你的具体情景选择正确的符号，重新生成。"
                    ),
                })
            response = await client.chat.completions.create(
                model=params["model"],
                messages=messages,
                tools=tools,
                tool_choice={"type": "function", "function": {"name": "parse_exam"}},
                temperature=params.get("temperature", 0.0),
                extra_body=params.get("extra_body"),
            )

            if not response.choices[0].message.tool_calls:
                if attempt == 0:
                    log_stage_retry(session_id, "stage1", 1, "no_tool_calls")
                    continue
                raise RuntimeError("Stage 1: LLM did not call parse_exam after retry")

            data = _parse_json(
                raw_args := response.choices[0].message.tool_calls[0].function.arguments
            )
            if data is None:
                if attempt == 0:
                    m = _CHINESE_QUOTE_RE.search(raw_args)
                    if m:
                        pos = m.start()
                        chinese_quote_context = raw_args[max(0, pos - 30):pos + 40]
                        log_stage_retry(session_id, "stage1", attempt+1,
                                        "json_parse_fail:chinese_quote")
                    else:
                        log_stage_retry(session_id, "stage1", attempt+1,
                                        "json_parse_fail")
                    continue
                raise RuntimeError("Stage 1: LLM returned unparseable JSON after retry")

            # Non-strict mode: validate structure
            if not _using_strict(session_id):
                errors = _validate_structure(
                    data, STAGE1_TOOLS[0]["function"]["parameters"]
                )
                if errors and attempt == 0:
                    continue
                elif errors:
                    raise RuntimeError(f"Stage 1 structure errors after retry: {errors}")

            return data

        except (APITimeoutError, RateLimitError):
            if attempt == 0:
                log_stage_retry(session_id, "stage1", attempt+1, "api_timeout_or_ratelimit")
                await asyncio.sleep(params["retry_delay_s"])
                continue
            raise
        except APIError as e:
            if _using_strict(session_id) and attempt == 0:
                _maybe_fallback(session_id, status_code=e.status_code or 0)
                continue
            if e.status_code and e.status_code >= 500 and attempt == 0:
                log_stage_retry(session_id, "stage1", attempt+1, f"api_{e.status_code}")
                await asyncio.sleep(params["retry_delay_s"])
                continue
            raise


# ═══════════════════════════════════════════════════════════════
# Stage 2 Call
# ═══════════════════════════════════════════════════════════════

async def _stage2_call(s1_data: dict, exam_type: str = "",
                      variant: str = "multiple_choice",
                      session_id: str = "",
                      cancel_evt: asyncio.Event = None) -> dict:
    """Call DeepSeek to generate tutorials. Model picks the right tool.

    All 5 Stage 2 tools are offered. Model chooses based on the data.
    This allows correction if Stage 1 misclassified exam_type.
    Returns dict with questions array of {number, answer, modules}.
    """
    client = _client_for_session(session_id)
    params = _get_stage_params("stage2")

    all_tools = list(STAGE2_TOOL_DEFS.values())
    tools = all_tools if _using_strict(session_id) else [strip_strict(t) for t in all_tools]

    chinese_quote_context = None

    for attempt in range(params["retry_attempts"]):
        try:
            messages = [
                {"role": "system", "content": STAGE2_SYSTEM_PROMPT},
                {"role": "user", "content": build_stage2_user_prompt(
                    s1_data, exam_type, format_questions_block,
                    variant=variant
                )},
            ]
            if chinese_quote_context:
                messages.append({
                    "role": "user",
                    "content": (
                        "上一次生成失败：JSON 字段值中检测到 ASCII 英文双引号 \"。\n\n"
                        f"违规位置（周围文本）：{chinese_quote_context}\n\n"
                        "请回顾工具描述中的【JSON 字段值符号约定】，"
                        "根据你的具体情景选择正确的符号，重新生成。"
                    ),
                })
            response = await client.chat.completions.create(
                model=params["model"],
                messages=messages,
                tools=tools,
                tool_choice="required",
                temperature=params.get("temperature", 0.3),
                max_tokens=params.get("max_tokens", 16384),
                extra_body=params.get("extra_body"),
            )

            if not response.choices[0].message.tool_calls:
                if attempt == 0:
                    log_stage_retry(session_id, "stage2", 1, "no_tool_calls")
                    continue
                raise RuntimeError("Stage 2: LLM did not call function after retry")

            chosen_tool = response.choices[0].message.tool_calls[0].function.name
            if session_id:
                log_trace(session_id,
                          f"stage2_tool chosen={chosen_tool} hinted={exam_type}")

            # Detect output truncation — split into smaller batches and retry
            if response.choices[0].finish_reason == "length":
                log_stage_retry(session_id, "stage2", attempt + 1, "output_truncated")
                batch_size = params.get("truncation_batch_size", 2)
                questions = s1_data["questions"]
                if len(questions) <= batch_size:
                    if attempt == 0:
                        continue
                    raise RuntimeError(
                        f"Stage 2 output truncated even at batch_size={batch_size}. "
                        "Consider increasing max_tokens or reducing question count."
                    )
                all_results = []
                failed = []
                for batch_start in range(0, len(questions), batch_size):
                    batch_end = min(batch_start + batch_size, len(questions))
                    batch_data = {"passage": s1_data["passage"],
                                  "questions": questions[batch_start:batch_end]}
                    # Check cancellation before each sub-batch
                    if cancel_evt and cancel_evt.is_set():
                        raise asyncio.CancelledError("Stage 2 batch cancelled")
                    try:
                        batch_result = await _stage2_call(
                            batch_data, exam_type=exam_type,
                            variant=variant, session_id=session_id,
                            cancel_evt=cancel_evt)
                        all_results.extend(batch_result["questions"])
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        failed.append(f"Q{batch_start+1}-Q{batch_end}: {e}")
                if failed:
                    raise RuntimeError(
                        f"Stage 2 batch partial failure: {len(failed)}/{len(all_results) + len(failed)} "
                        f"batches failed ({'; '.join(failed[:3])}). "
                        f"Partial results ({len(all_results)} questions) preserved in log."
                    )
                return {"questions": all_results}

            data = _parse_json(
                raw_args := response.choices[0].message.tool_calls[0].function.arguments
            )
            if data is None:
                if attempt == 0:
                    m = _CHINESE_QUOTE_RE.search(raw_args)
                    if m:
                        pos = m.start()
                        chinese_quote_context = raw_args[max(0, pos - 30):pos + 40]
                        log_stage_retry(session_id, "stage2", attempt+1,
                                        "json_parse_fail:chinese_quote")
                    else:
                        try:
                            json.loads(raw_args)
                        except json.JSONDecodeError as je:
                            ctx = raw_args[max(0,je.pos-30):je.pos+30]
                            log_stage_retry(session_id, "stage2", attempt+1,
                                            f"json_parse_fail pos={je.pos} "
                                            f"ctx={ctx!r} msg={str(je)[:80]}")
                        else:
                            log_stage_retry(session_id, "stage2", attempt+1,
                                            "json_parse_fail")
                    continue
                raise RuntimeError(
                    f"Stage 2: LLM returned unparseable JSON after retry "
                    f"(raw_len={len(raw_args)}, starts={raw_args[:100]!r})"
                )

            if not _using_strict(session_id):
                tool_schema = STAGE2_TOOL_DEFS.get(chosen_tool, {})
                errors = _validate_structure(
                    data, tool_schema.get("function", {}).get("parameters", {})
                )
                if errors and attempt == 0:
                    continue
                elif errors:
                    raise RuntimeError(f"Stage 2 structure errors after retry: {errors}")

            return data

        except (APITimeoutError, RateLimitError):
            if attempt == 0:
                log_stage_retry(session_id, "stage2", attempt+1, "api_timeout_or_ratelimit")
                await asyncio.sleep(params["retry_delay_s"])
                continue
            raise
        except APIError as e:
            if _using_strict(session_id) and attempt == 0:
                _maybe_fallback(session_id, status_code=e.status_code or 0)
                continue
            if e.status_code and e.status_code >= 500 and attempt == 0:
                log_stage_retry(session_id, "stage2", attempt+1, f"api_{e.status_code}")
                await asyncio.sleep(params["retry_delay_s"])
                continue
            raise


# ═══════════════════════════════════════════════════════════════
# Variant detection
# ═══════════════════════════════════════════════════════════════

def detect_variant(s1_data: dict) -> str:
    """Determine the question variant from Stage 1 output.

    Returns:
        "multiple_choice" — standard exam with A/B/C/D options
        "open_ended"      — questions with blanks but no preset options
        "empty"           — no questions found in OCR text
        "passage_only"    — passage found but no questions extracted

    Pure function — no LLM call, no I/O.
    """
    questions = s1_data.get("questions", [])
    passage = s1_data.get("passage", "").strip()

    if not questions:
        if not passage:
            return "empty"
        return "passage_only"

    # Check if ALL questions have completely empty options
    all_options_empty = all(
        all(v == "" for v in q.get("options", {}).values())
        for q in questions
    )

    if all_options_empty:
        return "open_ended"

    return "multiple_choice"


# ═══════════════════════════════════════════════════════════════
# Semantic Validation
# ═══════════════════════════════════════════════════════════════

def _validate_semantic(s1_data: dict, s2_data: dict) -> list[str]:
    """Cross-check Stage 1 questions against Stage 2 tutorial text.

    For each question, extract the longest English word sequence (3-5 words)
    from the Stage 1 stem/sentence, and check it appears in the Stage 2 content.
    Returns list of warning strings for mismatches.
    """
    import re
    warnings = []
    s1_qs = s1_data.get("questions", [])
    s2_qs = s2_data.get("questions", [])

    for s1q in s1_qs:
        qid = s1q.get("id")
        # Get the key text from Stage 1
        key_text = (s1q.get("sentence_with_blank", "") or
                    s1q.get("stem", "") or
                    s1q.get("statement", ""))
        if not key_text:
            continue

        # Extract longest English word sequences (3-5 words)
        words = re.findall(r'[a-zA-Z]{2,}', key_text)
        if len(words) < 3:
            continue
        phrases = []
        for n in range(min(5, len(words)), 2, -1):
            for i in range(len(words) - n + 1):
                phrases.append(" ".join(words[i:i+n]))

        # Find matching Stage 2 question
        s2q = next((q for q in s2_qs if q.get("number") == qid), None)
        if not s2q:
            warnings.append(f"第{qid}题：Stage 2 未生成（可能被遗漏）")
            continue

        # Search in all module text — concatenate raw values, not JSON
        modules = s2q.get("modules", {})
        s2_text = " ".join(str(v) for v in modules.values()).lower()
        found = any(p.lower() in s2_text for p in phrases)
        if not found:
            best = phrases[0] if phrases else key_text[:40]
            warnings.append(f"第{qid}题精讲未基于正确题干（'{best}'未在输出中找到）")

    return warnings


# ═══════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════

# Track active tasks for concurrency control and cancellation
_active_tasks: dict[str, asyncio.Task] = {}
_cancel_events: dict[str, asyncio.Event] = {}


def cancel_session(session_id: str) -> bool:
    """Cancel an active processing session. Returns True if found and cancelled."""
    evt = _cancel_events.pop(session_id, None)
    task = _active_tasks.pop(session_id, None)
    if evt:
        evt.set()
    if task and not task.done():
        task.cancel()
        return True
    return False


async def process_exam(session_id: str, image_paths: list[str],
                       ui_queues: dict, store, user_id: str = "") -> None:
    """Full pipeline: OCR → Stage 1 → Stage 2 → Store → SSE.

    Args:
        session_id: Unique session identifier
        image_paths: List of uploaded image file paths
        ui_queues: Dict[session_id, list[asyncio.Queue]] for SSE broadcasting
        store: ExamStore instance for persistence
    """
    # Register for cancellation
    cancel_evt = asyncio.Event()
    _cancel_events[session_id] = cancel_evt
    _active_tasks[session_id] = asyncio.current_task()

    try:
        await asyncio.wait_for(
            _run_pipeline(session_id, image_paths, ui_queues, store, user_id, cancel_evt),
            timeout=300,
        )
    except asyncio.TimeoutError:
        log_trace(session_id, "pipeline_timeout:300s")
        await _broadcast(ui_queues, session_id, "error", "ocr_failed", {
            "message": "处理超时，请稍后重试或减少图片数量。",
            "recoverable": True,
        })
    except OCRError as e:
        log_trace(session_id, f"ocr_error: {e}")
        await _broadcast(ui_queues, session_id, "error", "ocr_failed",
                         {"message": str(e), "recoverable": True})
    except (APITimeoutError, RateLimitError):
        log_trace(session_id, "api_timeout_or_ratelimit")
        await _broadcast(ui_queues, session_id, "error", "api_error", {
            "message": "AI 服务暂时不可用，请稍后重试",
            "recoverable": True,
        })
    except APIError as e:
        detail = _api_error_detail(e)
        log_trace(session_id, f"api_error:{e.status_code}:{detail}")
        if e.status_code and e.status_code >= 500:
            user_msg = "AI 服务暂时不可用，请稍后重试。"
            recoverable = True
        elif e.status_code == 429:
            user_msg = "请求过于频繁，请稍后重试。"
            recoverable = True
        else:
            user_msg = "服务配置异常，请联系管理员。"
            recoverable = False
        await _broadcast(ui_queues, session_id, "error", "api_error", {
            "message": user_msg,
            "recoverable": recoverable,
        })
    except RuntimeError as e:
        msg = str(e)
        if msg.startswith(("EMPTY_EXAM:", "PASSAGE_ONLY:", "OPEN_ENDED_UNSUPPORTED:")):
            user_msg = msg.split(":", 1)[1]
            recoverable = True
        elif msg.startswith("BAD_EXAM_TYPE:"):
            user_msg = "系统配置异常，请联系管理员。"
            recoverable = False
        else:
            user_msg = "处理异常，请稍后重试。"
            recoverable = True
        log_trace(session_id, f"runtime_error: {msg}")
        await _broadcast(ui_queues, session_id, "error", "unknown", {
            "message": user_msg,
            "recoverable": recoverable,
        })
    except asyncio.CancelledError:
        log_trace(session_id, "cancelled_by_user")
        await _broadcast(ui_queues, session_id, "error", "cancelled", {
            "message": "已取消",
            "recoverable": True,
        })
    except Exception as e:
        log_trace(session_id, f"unknown_error: {e}")
        await _broadcast(ui_queues, session_id, "error", "unknown", {
            "message": f"系统错误: {str(e)}",
            "recoverable": False,
        })
    finally:
        # Cleanup uploaded images
        if config.upload_image_cleanup:
            for p in image_paths:
                Path(p).unlink(missing_ok=True)
        _cancel_events.pop(session_id, None)
        _active_tasks.pop(session_id, None)
        _strict_mode.pop(session_id, None)  # per-session strict mode cleanup


async def _run_pipeline(session_id: str, image_paths: list[str],
                        ui_queues: dict, store, user_id: str,
                        cancel_evt: asyncio.Event) -> None:
    """Pipeline body: OCR → Stage 1 → Stage 2 → Store → SSE."""
    # ── 1. OCR ──
    await _broadcast(ui_queues, session_id, "ocr", "start",
                     {"files": len(image_paths)})
    t0_ocr = time.time()
    total_bytes = sum(Path(p).stat().st_size for p in image_paths)
    log_ocr_start(session_id, "tesseract", image_paths[0], total_bytes)
    log_trace(session_id, "ocr_start")
    ocr_text = await ocr_images(image_paths, cancel_evt=cancel_evt)
    log_ocr_result(session_id, "tesseract",
                   (time.time() - t0_ocr) * 1000,
                   len(ocr_text), ocr_text[:200], True)
    await _broadcast(ui_queues, session_id, "ocr", "done",
                     {"method": "tesseract", "chars": len(ocr_text)})
    log_trace(session_id, f"ocr_done chars={len(ocr_text)}")

    # ── 2. Stage 1 ──
    await _broadcast(ui_queues, session_id, "stage1", "start", {})
    log_stage1_entry(session_id)
    s1_data = await _stage1_call(ocr_text, len(image_paths),
                                  session_id=session_id)
    exam_type = s1_data["exam_type"]
    q_count = len(s1_data["questions"])
    variant = detect_variant(s1_data)
    log_variant_detect(session_id, variant, exam_type)
    await _broadcast(ui_queues, session_id, "stage1", "done", {
        "exam_type": exam_type,
        "question_count": q_count,
        "variant": variant,
    })
    log_stage1_result(session_id, q_count=q_count, exam_type=exam_type,
                      success=True)

    # ── 2.5 Variant check ──
    if variant == "empty":
        raise RuntimeError("EMPTY_EXAM:未在图片中识别到题目，请确认试卷图片清晰且包含题目。")
    if variant == "passage_only":
        raise RuntimeError("PASSAGE_ONLY:只识别到文章，未找到题目。请上传包含题目的页面。")
    if variant == "open_ended":
        if exam_type in ("reading_comp", "true_false"):
            type_label = {"reading_comp": "阅读理解", "true_false": "正误判断"}.get(exam_type, exam_type)
            raise RuntimeError(
                f"OPEN_ENDED_UNSUPPORTED:识别到{type_label}题但未提取到选项——"
                f"这通常是文字识别问题，请重新拍摄清晰图片。"
            )
    if exam_type not in STAGE2_TOOL_NAME:
        raise RuntimeError(f"BAD_EXAM_TYPE:Unknown exam_type: {exam_type}")

    # ── 3. Stage 2 (with heartbeat) ──
    await _broadcast(ui_queues, session_id, "stage2", "start",
                     {"question_count": q_count})
    s2_params = _get_stage_params("stage2")
    log_llm_start(session_id, len(ocr_text), s2_params["model"])

    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(ui_queues, session_id,
                       interval=s2_params.get("heartbeat_interval_s", 5.0))
    )
    t0 = time.time()
    try:
        s2_data = await _stage2_call(s1_data,
                                      exam_type=exam_type,
                                      variant=variant,
                                      session_id=session_id,
                                      cancel_evt=cancel_evt)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass

    log_llm_result(session_id,
                   duration_ms=(time.time() - t0) * 1000,
                   output_length=len(json.dumps(s2_data)),
                   question_marker_count=len(s2_data.get("questions", [])),
                   success=True)

    # ── 4. Soft validation ──
    warnings = []
    if len(s2_data["questions"]) != q_count:
        warnings.append(
            f"题数不一致：Stage 1 识别 {q_count} 题，"
            f"Stage 2 生成 {len(s2_data['questions'])} 题"
        )
    sem_warnings = _validate_semantic(s1_data, s2_data)
    warnings.extend(sem_warnings)

    # ── 5. Store + Vocabulary + SSE ──
    exam_id = store.save(
        session_id=session_id,
        user_id=user_id,
        exam_type=exam_type,
        variant=variant,
        passage=s1_data.get("passage", ""),
        s1_questions=json.dumps(s1_data.get("questions", []), ensure_ascii=False),
        question_count=q_count,
        ocr_text=ocr_text,
        tutorial=json.dumps(s2_data["questions"], ensure_ascii=False),
        warnings=warnings,
    )

    vocab_text = s1_data.get("passage", "") + " "
    for q in s1_data.get("questions", []):
        vocab_text += (q.get("stem", "") or q.get("sentence_with_blank", "") or q.get("statement", "")) + " "
        for opt_text in q.get("options", {}).values():
            vocab_text += opt_text + " "
    vocab_insight = process_vocabulary(vocab_text, exam_id, store, user_id=user_id)

    await _broadcast(ui_queues, session_id, "stage2", "done", {
        "questions": s2_data["questions"],
        "exam_id": exam_id,
        "exam_type": exam_type,
        "variant": variant,
        "passage": s1_data.get("passage", ""),
        "s1_questions": s1_data.get("questions", []),
        "warnings": warnings,
        "vocabulary": vocab_insight,
    })

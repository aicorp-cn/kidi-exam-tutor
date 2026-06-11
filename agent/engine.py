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

# ── Client initialization with Strict Mode detection ──
_USE_STRICT = True
_client = None


def _get_client() -> AsyncOpenAI:
    """Return the DeepSeek API client. Lazy-init on first call."""
    global _client
    if _client is not None:
        return _client
    return _build_client(use_strict=True)


def _build_client(use_strict: bool) -> AsyncOpenAI:
    """Build AsyncOpenAI client. If use_strict, use beta endpoint."""
    global _client, _USE_STRICT
    api_key = config.llm_api_key()
    s1 = config.llm_for("stage1")
    if not api_key:
        raise RuntimeError("DeepSeek API key not configured.")
    url = s1["base_url"] if use_strict else s1["fallback_url"]
    _USE_STRICT = use_strict
    _client = AsyncOpenAI(
        api_key=api_key,
        base_url=url,
        timeout=s1["timeout"],
        max_retries=s1["max_retries"],
    )
    return _client


def _maybe_fallback(session_id: str = "", status_code: int = 0):
    """If Strict Mode is active and we hit a transient/compatibility error, fall back.

    4xx client errors (except 429 rate-limit) = model/config issue, NOT strict mode.
    Only 5xx / timeout / rate-limit warrant endpoint switch.
    """
    global _USE_STRICT
    if not _USE_STRICT:
        return  # already in fallback mode

    if status_code and 400 <= status_code < 500 and status_code != 429:
        # Client error — disable strict for retry, keep same URL
        _USE_STRICT = False
        if session_id:
            log_trace(session_id, f"strict_disabled:http_{status_code}")
        return

    # 5xx / timeout / rate-limit → possible endpoint issue → try fallback URL
    s1 = config.llm_for("stage1")
    if s1["base_url"] == s1["fallback_url"]:
        _USE_STRICT = False
        return
    _build_client(use_strict=False)
    if session_id:
        log_trace(session_id, "strict_mode_fallback")


# ── JSON parsing with LLM output resilience ──

def _parse_json(raw: str) -> tuple[dict | None, bool]:
    """Parse JSON from LLM tool call arguments. Returns (data, _) tuple.
    
    Tries json.loads first, then raw_decode for extra-data tolerance.
    Returns (None, False) if unparseable — caller retries LLM.
    """
    if not raw or not raw.strip():
        return None, False

    # Try strict parse first
    try:
        return json.loads(raw), False
    except json.JSONDecodeError:
        pass

    # Extra data after valid JSON
    try:
        decoder = json.JSONDecoder()
        obj, _ = decoder.raw_decode(raw)
        return obj, False
    except json.JSONDecodeError:
        pass

    return None, False  # Unrecoverable — caller retries LLM


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
    qs = queues.get(session_id, [])
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
    client = _get_client()
    params = _get_stage_params("stage1")
    tools = STAGE1_TOOLS if _USE_STRICT else strip_strict(STAGE1_TOOLS)

    for attempt in range(params["retry_attempts"]):
        try:
            response = await client.chat.completions.create(
                model=params["model"],
                messages=[
                    {"role": "system", "content": STAGE1_SYSTEM_PROMPT},
                    {"role": "user", "content": build_stage1_user_prompt(ocr_text, page_count)},
                ],
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

            data, _ = _parse_json(
                response.choices[0].message.tool_calls[0].function.arguments
            )
            if data is None:
                if attempt == 0:
                    log_stage_retry(session_id, "stage1", attempt+1, "json_parse_fail")
                    continue
                raise RuntimeError("Stage 1: LLM returned unparseable JSON after retry")

            # Non-strict mode: validate structure
            if not _USE_STRICT:
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
            if _USE_STRICT and attempt == 0:
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
                      session_id: str = "") -> dict:
    """Call DeepSeek to generate tutorials. Model picks the right tool.

    All 5 Stage 2 tools are offered. Model chooses based on the data.
    This allows correction if Stage 1 misclassified exam_type.
    Returns dict with questions array of {number, answer, modules}.
    """
    client = _get_client()
    params = _get_stage_params("stage2")

    all_tools = list(STAGE2_TOOL_DEFS.values())
    tools = all_tools if _USE_STRICT else [strip_strict(t) for t in all_tools]

    for attempt in range(params["retry_attempts"]):
        try:
            response = await client.chat.completions.create(
                model=params["model"],
                messages=[
                    {"role": "system", "content": STAGE2_SYSTEM_PROMPT},
                    {"role": "user", "content": build_stage2_user_prompt(
                        s1_data, exam_type, format_questions_block,
                        variant=variant
                    )},
                ],
                tools=tools,
                tool_choice="required",
                temperature=params.get("temperature", 0.3),
                max_tokens=params.get("max_tokens", 16384),
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
            if response.choices[0].finish_reason == "length" and attempt == 0:
                log_stage_retry(session_id, "stage2", 1, "output_truncated")
                batch_size = params.get("truncation_batch_size", 2)
                questions = s1_data["questions"]
                if len(questions) <= batch_size:
                    continue
                all_results = []
                for batch_start in range(0, len(questions), batch_size):
                    batch_end = min(batch_start + batch_size, len(questions))
                    batch_data = {"passage": s1_data["passage"],
                                  "questions": questions[batch_start:batch_end]}
                    batch_result = await _stage2_call(
                        batch_data, exam_type=exam_type,
                        variant=variant, session_id=session_id)
                    all_results.extend(batch_result["questions"])
                return {"questions": all_results}

            data, _ = _parse_json(
                raw_args := response.choices[0].message.tool_calls[0].function.arguments
            )
            if data is None:
                if attempt == 0:
                    # Log JSON error position for diagnosis
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

            if not _USE_STRICT:
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
            if _USE_STRICT and attempt == 0:
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

        # Search in all module text
        s2_text = json.dumps(s2q.get("modules", {}), ensure_ascii=False).lower()
        found = any(p.lower() in s2_text for p in phrases)
        if not found:
            best = phrases[0] if phrases else key_text[:40]
            warnings.append(f"第{qid}题精讲未基于正确题干（'{best}'未在输出中找到）")

    return warnings


# ═══════════════════════════════════════════════════════════════
# Main Pipeline
# ═══════════════════════════════════════════════════════════════

# Track active tasks for concurrency control
_active_tasks: dict[str, asyncio.Task] = {}


async def process_exam(session_id: str, image_paths: list[str],
                       ui_queues: dict, store) -> None:
    """Full pipeline: OCR → Stage 1 → Stage 2 → Store → SSE.

    Args:
        session_id: Unique session identifier
        image_paths: List of uploaded image file paths
        ui_queues: Dict[session_id, list[asyncio.Queue]] for SSE broadcasting
        store: ExamStore instance for persistence
    """
    try:
        # ── 1. OCR ──
        await _broadcast(ui_queues, session_id, "ocr", "start",
                         {"files": len(image_paths)})
        t0_ocr = time.time()
        total_bytes = sum(Path(p).stat().st_size for p in image_paths)
        log_ocr_start(session_id, "tesseract", image_paths[0], total_bytes)
        log_trace(session_id, "ocr_start")
        ocr_text = await ocr_images(image_paths)
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
        # Model picks the right tool from all 5 — auto-corrects exam_type if needed
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
                                          session_id=session_id)
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
        # Semantic cross-check: Stage 1 stems vs Stage 2 tutorial text
        sem_warnings = _validate_semantic(s1_data, s2_data)
        warnings.extend(sem_warnings)

        # ── 5. Store + SSE ──
        exam_id = store.save(
            session_id=session_id,
            exam_type=exam_type,
            variant=variant,
            passage=s1_data.get("passage", ""),
            s1_questions=json.dumps(s1_data.get("questions", []), ensure_ascii=False),
            question_count=q_count,
            ocr_text=ocr_text,
            tutorial=json.dumps(s2_data["questions"], ensure_ascii=False),
            warnings=warnings,
        )
        await _broadcast(ui_queues, session_id, "stage2", "done", {
            "questions": s2_data["questions"],
            "exam_id": exam_id,
            "exam_type": exam_type,
            "variant": variant,
            "passage": s1_data.get("passage", ""),
            "s1_questions": s1_data.get("questions", []),
            "warnings": warnings,
        })

    except OCRError as e:
        log_ocr_result(session_id, "tesseract",
                       (time.time() - t0_ocr) * 1000,
                       0, str(e)[:200], False)
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
        # User-facing: generic, actionable, no technical detail leaked
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
        # Prefixed errors → user-actionable, show the message
        if msg.startswith(("EMPTY_EXAM:", "PASSAGE_ONLY:", "OPEN_ENDED_UNSUPPORTED:")):
            user_msg = msg.split(":", 1)[1]
            recoverable = True
        elif msg.startswith("BAD_EXAM_TYPE:"):
            user_msg = "系统配置异常，请联系管理员。"
            recoverable = False
        else:
            user_msg = "系统错误，请稍后重试。"
            recoverable = False
        log_trace(session_id, f"runtime_error: {msg}")
        await _broadcast(ui_queues, session_id, "error", "unknown", {
            "message": user_msg,
            "recoverable": recoverable,
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
        _active_tasks.pop(session_id, None)

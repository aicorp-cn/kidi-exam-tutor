"""Pipeline observability logger.

Writes JSON Lines to data/pipeline.log. Each line is a self-contained event.
Query by session_id to reconstruct the full trace of one exam processing.

Event types:
  upload       — image received by API
  ocr_start    — OCR attempt begins
  ocr_result   — OCR attempt ends
  stage1_entry — Stage 1 structural parse begins
  stage1_result — Stage 1 result (ok/error/field_errors/recovered)
  llm_start    — Stage 2 LLM call begins
  llm_result   — Stage 2 LLM call ends
  trace        — lightweight debug marker
  retry        — LLM call retry with reason
"""

import json
import time
from pathlib import Path

LOG_PATH = None  # initialized by init_log_path()


def init_log_path(path: str):
    """Set the pipeline log path. Called once at startup from main.py."""
    global LOG_PATH
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH = p


def _write(event: dict):
    event["ts"] = time.time()
    # Rotate if log exceeds 5 MB
    if LOG_PATH.exists() and LOG_PATH.stat().st_size > 5 * 1024 * 1024:
        bak = LOG_PATH.with_suffix(".log.1")
        if bak.exists():
            bak.unlink()
        LOG_PATH.rename(bak)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def log_upload(session_id: str, file_count: int, total_bytes: int):
    _write({"step": "upload", "session_id": session_id,
            "file_count": file_count, "total_bytes": total_bytes})


def log_ocr_start(session_id: str, method: str, image_path: str, image_bytes: int):
    _write({"step": "ocr_start", "session_id": session_id,
            "method": method, "image_path": image_path, "image_bytes": image_bytes})


def log_ocr_result(session_id: str, method: str, duration_ms: float,
                   text_length: int, text_preview: str, success: bool):
    _write({"step": "ocr_result", "session_id": session_id,
            "method": method, "duration_ms": round(duration_ms, 1),
            "text_length": text_length, "text_preview": text_preview[:200],
            "success": success})


def log_llm_start(session_id: str, ocr_text_length: int, model: str):
    _write({"step": "llm_start", "session_id": session_id,
            "ocr_text_length": ocr_text_length, "model": model})


def log_llm_result(session_id: str, duration_ms: float,
                   output_length: int, question_marker_count: int, success: bool):
    _write({"step": "llm_result", "session_id": session_id,
            "duration_ms": round(duration_ms, 1),
            "output_length": output_length,
            "question_marker_count": question_marker_count,
            "success": success})


def log_stage1_entry(session_id: str):
    """Stage 1 structural parse begins."""
    _write({"step": "stage1_entry", "session_id": session_id})


def log_stage1_result(session_id: str, q_count: int = 0,
                       exam_type: str = "", success: bool = False,
                       field_errors: list[str] = None,
                       error: str = None,
                       attempt: int = 1,
                       recovered: bool = False):
    """Stage 1 structural parse result."""
    evt = {"step": "stage1_result", "session_id": session_id,
           "attempt": attempt}
    if success:
        evt["status"] = "ok"
        evt["exam_type"] = exam_type
        evt["question_count"] = q_count
    elif recovered:
        evt["status"] = "recovered"
        evt["exam_type"] = exam_type
        evt["question_count"] = q_count
        evt["field_errors"] = field_errors or []
    elif error:
        evt["status"] = "error"
        evt["error"] = error
    elif field_errors:
        evt["status"] = "field_errors"
        evt["exam_type"] = exam_type
        evt["question_count"] = q_count
        evt["field_errors"] = field_errors
    _write(evt)


def log_trace(session_id: str, message: str):
    """Lightweight trace point for debugging pipeline hangs."""
    _write({"step": "trace", "session_id": session_id, "msg": message})


def log_variant_detect(session_id: str, variant: str, exam_type: str):
    """Record variant detection decision for pipeline audit."""
    _write({"step": "variant_detect", "session_id": session_id,
            "variant": variant, "exam_type": exam_type})


def log_stage_retry(session_id: str, stage: str, attempt: int, reason: str):
    """Record LLM call retry for troubleshooting."""
    _write({"step": "retry", "session_id": session_id,
            "stage": stage, "attempt": attempt, "reason": reason})


def query_logs(session_id: str, limit: int = 50) -> list[dict]:
    """Return all log entries for a session, most recent first."""
    if not LOG_PATH or not LOG_PATH.exists():
        return []
    results = []
    with open(LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("session_id") == session_id:
                results.append(evt)
    # Sort by timestamp ascending for trace readability
    results.sort(key=lambda e: e.get("ts", 0))
    return results[-limit:]


def recent_logs(limit: int = 20) -> list[dict]:
    """Return most recent log entries across all sessions."""
    if not LOG_PATH or not LOG_PATH.exists():
        return []
    results = []
    with open(LOG_PATH) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                results.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    results.sort(key=lambda e: e.get("ts", 0))
    return results[-limit:]

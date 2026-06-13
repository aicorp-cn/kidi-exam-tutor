"""Exam Tutor Agent — FastAPI SSE Server.

Single process. Serves:
  - POST /exams           Upload images → start pipeline
  - GET  /sse/ui?session=X  SSE event stream
  - GET  /exams            History list
  - GET  /exams/{id}       Single exam detail
  - GET  /health           Health check + config validity
  - GET  /api/config       Frontend configuration (page_size, allowed_types, etc.)
  - Static files from webui/
"""

import asyncio
import json
import uuid
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Query, Request
from fastapi.responses import StreamingResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import config  # validates at first access
from engine import process_exam, cancel_session
from store import ExamStore
from pipeline_log import log_upload, init_log_path


class CORSStaticFiles(StaticFiles):
    """StaticFiles that adds CORS headers for module script compatibility."""

    async def __call__(self, scope, receive, send):
        async def cors_send(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                if b"access-control-allow-origin" not in headers:
                    headers[b"access-control-allow-origin"] = b"*"
                message["headers"] = list(headers.items())
            await send(message)
        await super().__call__(scope, receive, cors_send)

# ── Init paths ──

init_log_path(str(config.data_dir / "pipeline.log"))

# ── Server config ──

app = FastAPI(title="Exam Tutor Agent", version="5.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = ExamStore(str(config.data_dir / "exams.db"))

# session_id → list[asyncio.Queue]
ui_queues: dict[str, list[asyncio.Queue]] = {}


# ═══════════════════════════════════════════════════════════════
# Health / Config endpoints
# ═══════════════════════════════════════════════════════════════

@app.get("/health")
async def health(deep: bool = False):
    """System health check.

    Without deep: config validity, API key status, writability.
    With deep=true: also pings each configured model via 1-token inference.
    Only binary result exposed — no model names, no error details.
    """
    result = config.health()
    if deep:
        ok, detail = await _deep_health_ping()
        result["checks"]["llm_reachable"] = ok
        if not ok:
            result["status"] = "error"
    return result


async def _deep_health_ping() -> tuple[bool, str]:
    """Ping each configured model. Returns (all_ok, log_detail)."""
    from engine import _get_client, _get_stage_params, _api_error_detail
    from pipeline_log import _write
    import time as _time

    try:
        client = _get_client()
    except Exception as e:
        _write({"step": "health_check", "ok": False,
                "detail": str(e), "ts": _time.time()})
        return False, str(e)

    s1 = _get_stage_params("stage1")
    s2 = _get_stage_params("stage2")
    models = {s1["model"], s2["model"]}
    all_ok = True

    for model in models:
        try:
            resp = await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0.0,
            )
            _write({"step": "health_check", "model": model, "ok": True,
                    "detail": f"finish={resp.choices[0].finish_reason}", "ts": _time.time()})
        except Exception as e:
            detail = str(e)[:200]
            _write({"step": "health_check", "model": model, "ok": False,
                    "detail": detail, "ts": _time.time()})
            all_ok = False

    return all_ok, ""


@app.get("/api/config")
async def api_config():
    """Frontend configuration endpoint. Called once on page load."""
    return config.frontend_config()


# ═══════════════════════════════════════════════════════════════
# REST Endpoints
# ═══════════════════════════════════════════════════════════════

@app.post("/exams")
async def create_exam(images: list[UploadFile] = File(...)):
    """Upload exam images. Starts async pipeline, returns session_id immediately."""
    session_id = str(uuid.uuid4())[:8]

    image_paths = []
    total_bytes = 0
    for img in images:
        if img.content_type and img.content_type not in config.upload_allowed_types:
            return JSONResponse(
                {"error": f"不支持的文件类型: {img.content_type}"}, 400
            )
        data = await img.read()
        if len(data) > config.upload_max_file_size:
            return JSONResponse(
                {"error": f"图片过大: {len(data)} bytes (max {config.upload_max_file_size})"}, 400
            )

        fpath = config.data_dir / "images" / f"{session_id}_{img.filename}"
        fpath.write_bytes(data)
        total_bytes += len(data)
        image_paths.append(str(fpath))

    # Fire and forget — SSE endpoint picks up events
    log_upload(session_id, len(image_paths), total_bytes)
    asyncio.create_task(process_exam(session_id, image_paths, ui_queues, store))

    return {"session_id": session_id}


@app.get("/exams")
async def list_exams(page: int = 1, search: str = "", type: str = ""):
    """List recent exam records. Supports search (passage/ocr/tutorial) and type filter."""
    limit = config.history_page_size
    items, total, type_counts = store.list_exams(page, limit, search=search, exam_type=type)
    return {"items": items, "total": total, "page": page, "types": type_counts}


@app.get("/exams/{exam_id}")
async def get_exam(exam_id: str):
    """Get a single exam record by ID."""
    exam = store.get_exam(exam_id)
    if not exam:
        return JSONResponse({"error": "not found"}, 404)
    return exam


@app.get("/review/{exam_id}")
async def get_review(exam_id: str):
    """Get full review data for an exam — including questions, warnings, and vocabulary insight.

    This is the unified endpoint for history replay. Returns the same shape
    as the SSE 'stage2 done' event, ensuring one code path for review data.
    """
    data = store.get_review(exam_id)
    if not data:
        return JSONResponse({"error": "not found"}, 404)
    return data


@app.post("/exams/{exam_id}/star")
async def toggle_star(exam_id: str):
    """Toggle starred status on an exam. Returns {exam_id, starred: bool}."""
    new_state = store.toggle_star(exam_id)
    return {"exam_id": exam_id, "starred": new_state}


@app.delete("/exams/{exam_id}")
async def delete_exam(exam_id: str):
    """Delete a single exam record."""
    if store.delete_exam(exam_id):
        return {"deleted": True, "exam_id": exam_id}
    return JSONResponse({"error": "not found"}, 404)


@app.post("/exams/batch-delete")
async def batch_delete_exams(request: Request):
    """Delete multiple exam records. Body: {ids: [...]}."""
    body = await request.json()
    ids = body.get("ids", [])
    if not ids:
        return JSONResponse({"error": "ids required"}, 400)
    count = store.delete_exams(ids)
    return {"deleted": count, "ids": ids}


# ═══════════════════════════════════════════════════════════════
# SSE Endpoint
# ═══════════════════════════════════════════════════════════════

@app.get("/sse/ui")
async def sse_ui(session: str = Query(...)):
    """SSE event stream for a session. Web UI connects here."""
    q = asyncio.Queue()
    ui_queues.setdefault(session, []).append(q)

    async def stream():
        try:
            # Immediate connection confirm
            yield f"data: {json.dumps({'stage': 'connected', 'session': session}, ensure_ascii=False)}\n\n"

            while True:
                # Race between next event and heartbeat timeout
                get_task = asyncio.create_task(q.get())
                try:
                    data = await asyncio.wait_for(get_task, timeout=config.sse_heartbeat_timeout)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    if data.get("stage") in ("stage2", "error") and data.get("status") in ("done", "ocr_failed", "api_error", "unknown"):
                        break
                except asyncio.TimeoutError:
                    get_task.cancel()
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            # Connection dropped — try to flush any pending error event
            try:
                data = q.get_nowait()
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.QueueEmpty:
                pass
        finally:
            queues = ui_queues.get(session, [])
            if q in queues:
                queues.remove(q)
            # Cancel backend processing if no listeners remain
            if not queues:
                ui_queues.pop(session, None)
                cancel_session(session)

    return StreamingResponse(stream(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════
# Debug Endpoints
# ═══════════════════════════════════════════════════════════════

@app.post("/debug/client-error")
async def debug_client_error(request: Request):
    """Receive browser-side JS error reports."""
    import sys
    body = await request.json()
    print(
        f"[CLIENT_ERROR] {body.get('message','?')} | "
        f"{body.get('filename','?')}:{body.get('lineno','?')} | "
        f"{body.get('userAgent','?')[:80]}",
        file=sys.stderr, flush=True,
    )
    if body.get('stack'):
        print(f"  STACK: {body['stack'][:300]}", file=sys.stderr, flush=True)
    return {"status": "logged"}


# ═══════════════════════════════════════════════════════════════
# Static (Web UI)
# ═══════════════════════════════════════════════════════════════

if config.webui_dir.exists():
    app.mount("/", CORSStaticFiles(directory=str(config.webui_dir), html=True), name="webui")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    proto = "https" if getattr(config, 'ssl_enabled', False) else "http"
    print(f"Exam Tutor Agent starting on {proto}://{config.server_host}:{config.server_port}")

    uvicorn_kwargs = dict(
        host=config.server_host, port=config.server_port, log_level="info"
    )
    if getattr(config, 'ssl_enabled', False):
        uvicorn_kwargs["ssl_keyfile"] = str(config.ssl_key_file)
        uvicorn_kwargs["ssl_certfile"] = str(config.ssl_cert_file)

    uvicorn.run(app, **uvicorn_kwargs)

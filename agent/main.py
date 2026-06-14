"""Exam Tutor Agent — FastAPI SSE Server."""
import asyncio
import json
import secrets
from pathlib import Path

from fastapi import FastAPI, UploadFile, File, Query, Request, Depends, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

from config import config
from engine import process_exam, cancel_session
from store import ExamStore
from pipeline_log import log_upload, init_log_path

from user import (
    Student, StudentCreate, StudentRead,
    init_student_db, get_user_manager, get_user_db,
    create_fastapi_users, auth_backend, get_jwt_strategy,
)
from geoip import lookup as geoip_lookup
from pinyin import surname_initial


class CORSStaticFiles(StaticFiles):
    async def __call__(self, scope, receive, send):
        async def cors_send(message):
            if message["type"] == "http.response.start":
                headers = dict(message.get("headers", []))
                if b"access-control-allow-origin" not in headers:
                    headers[b"access-control-allow-origin"] = b"*"
                message["headers"] = list(headers.items())
            await send(message)
        await super().__call__(scope, receive, cors_send)


# ── Init ──

init_log_path(str(config.data_dir / "pipeline.log"))

app = FastAPI(title="Exam Tutor Agent", version="6.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=config.cors_origins,
    allow_methods=["*"], allow_headers=["*"],
)

store = ExamStore(str(config.data_dir / "exams.db"))
ui_queues: dict[str, list[asyncio.Queue]] = {}
_pipeline_semaphore = asyncio.Semaphore(2)

# ── User system ──

_student_db = init_student_db(str(config.data_dir / "users.db"))
_fastapi_users = create_fastapi_users(get_user_manager, [auth_backend])
current_user = _fastapi_users.current_user(active=True)

app.include_router(
    _fastapi_users.get_register_router(StudentRead, StudentCreate),
    prefix="/auth", tags=["auth"],
)
app.include_router(
    _fastapi_users.get_auth_router(auth_backend),
    prefix="/auth/jwt", tags=["auth"],
)

# ── Custom /auth endpoint — student-friendly register/login ──

@app.post("/auth", tags=["auth"])
async def auth(request: Request, body: dict):
    """Register or login. Body: {province, city, gender, input_id, name, password?}"""
    import bcrypt
    province = body.get("province", "")
    city = body.get("city", "")
    gender = body.get("gender", "保密")
    input_id = body.get("input_id", "").strip()
    name = body.get("name", "").strip()
    password = body.get("password", "")

    if not input_id or not name:
        raise HTTPException(400, "学号和姓名不能为空")

    name_init = surname_initial(name)
    gender_code = {"男": "M", "女": "F"}.get(gender, "X")

    student_id = f"{province}-{city}-{gender_code}-{name_init}-{input_id}"
    email = f"{student_id}@aikidi.com"

    # Try existing user
    existing = await _student_db.get_by_email(email)
    if existing:
        if not existing.hashed_password or bcrypt.checkpw(
            password.encode(), existing.hashed_password.encode()
        ):
            token = await get_jwt_strategy().write_token(existing)
            return {"access_token": token, "token_type": "bearer",
                    "student_id": existing.student_id, "name": existing.name}
        raise HTTPException(401, "密码错误")

    # New user
    hp = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode() if password else ""
    import uuid as _uuid
    uid = str(_uuid.uuid4())
    new_user = await _student_db.create({
        "id": uid, "email": email, "hashed_password": hp,
        "student_id": student_id, "name": name,
    })
    token = await get_jwt_strategy().write_token(new_user)
    return {"access_token": token, "token_type": "bearer",
            "student_id": student_id, "name": name}

# ── /api/location — IP → province/city ──

@app.get("/api/location")
async def api_location(request: Request):
    ip = request.client.host if request.client else "127.0.0.1"
    province, city = await geoip_lookup(ip)
    return {"province": province, "city": city}


# ── Health / Config ──

@app.get("/health")
async def health(deep: bool = False):
    result = config.health()
    if deep:
        ok, detail = await _deep_health_ping()
        result["checks"]["llm_reachable"] = ok
        if not ok:
            result["status"] = "error"
    return result


async def _deep_health_ping() -> tuple[bool, str]:
    from engine import _get_strict_client, _get_stage_params, _api_error_detail
    from pipeline_log import _write
    import time as _time
    try:
        client = _get_strict_client()
    except Exception as e:
        _write({"step": "health_check", "ok": False, "detail": str(e), "ts": _time.time()})
        return False, str(e)
    s1 = _get_stage_params("stage1")
    s2 = _get_stage_params("stage2")
    models_set = {s1["model"], s2["model"]}
    all_ok = True
    for model in models_set:
        try:
            resp = await client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": "ping"}],
                max_tokens=1, temperature=0.0)
            _write({"step": "health_check", "model": model, "ok": True,
                    "detail": f"finish={resp.choices[0].finish_reason}", "ts": _time.time()})
        except Exception as e:
            _write({"step": "health_check", "model": model, "ok": False,
                    "detail": str(e)[:200], "ts": _time.time()})
            all_ok = False
    return all_ok, ""


@app.get("/api/config")
async def api_config():
    return config.frontend_config()


# ═══════════════════════════════════════════════════════════════
# Exam endpoints — user-scoped
# ═══════════════════════════════════════════════════════════════

@app.get("/auth/me", tags=["auth"])
async def auth_me(user: Student = Depends(current_user)):
    return {"id": str(user.id), "email": user.email,
            "student_id": user.student_id, "name": user.name}


@app.patch("/auth/me", tags=["auth"])
async def auth_me_update(body: dict, user: Student = Depends(current_user)):
    """Update name and/or password. Body: {name?, password?, new_password?}"""
    import bcrypt
    user_db = _student_db
    updates = {}

    # Name update
    new_name = body.get("name", "").strip()
    if new_name and new_name != user.name:
        updates["name"] = new_name

    # Password update
    new_password = body.get("new_password", "")
    if new_password:
        if len(new_password) < 6:
            raise HTTPException(400, "密码至少6位")
        current_pw = body.get("password", "")
        if user.hashed_password and not bcrypt.checkpw(
            current_pw.encode(), user.hashed_password.encode()
        ):
            raise HTTPException(401, "当前密码错误")
        updates["hashed_password"] = bcrypt.hashpw(
            new_password.encode(), bcrypt.gensalt()
        ).decode()

    if updates:
        await user_db.update(user, updates)

    return {"id": str(user.id), "email": user.email,
            "student_id": user.student_id, "name": user.name}


@app.post("/exams")
async def create_exam(
    images: list[UploadFile] = File(...),
    user: Student = Depends(current_user),
):
    session_id = secrets.token_hex(8)  # pipeline isolation
    image_paths = []
    total_bytes = 0
    for img in images:
        if img.content_type and img.content_type not in config.upload_allowed_types:
            return JSONResponse({"error": f"不支持的文件类型: {img.content_type}"}, 400)
        data = await img.read()
        if len(data) > config.upload_max_file_size:
            size_mb = round(len(data) / 1048576, 1)
            limit_mb = round(config.upload_max_file_size / 1048576, 1)
            return JSONResponse({"error": f"图片过大（{size_mb}MB），上限为 {limit_mb}MB"}, 400)
        fpath = config.data_dir / "images" / f"{session_id}_{Path(img.filename).name}"
        fpath.write_bytes(data)
        total_bytes += len(data)
        image_paths.append(str(fpath))
    log_upload(session_id, len(image_paths), total_bytes)
    asyncio.create_task(_pipeline_with_semaphore(session_id, image_paths, str(user.id))).add_done_callback(
        lambda t: t.exception() and log_upload(session_id, 0, 0) or None  # log if task failed silently
    )
    return {"session_id": session_id}


async def _pipeline_with_semaphore(session_id: str, image_paths: list[str], user_id: str):
    async with _pipeline_semaphore:
        await process_exam(session_id, image_paths, ui_queues, store, user_id=user_id)


@app.get("/exams")
async def list_exams(
    page: int = 1, search: str = "", type: str = "",
    user: Student = Depends(current_user),
):
    limit = config.history_page_size
    items, total, type_counts = store.list_exams(
        page, limit, search=search, exam_type=type, user_id=str(user.id))
    return {"items": items, "total": total, "page": page, "types": type_counts}


@app.get("/exams/{exam_id}")
async def get_exam(exam_id: str, user: Student = Depends(current_user)):
    exam = store.get_exam(exam_id, user_id=str(user.id))
    return exam if exam else JSONResponse({"error": "not found"}, 404)


@app.get("/review/{exam_id}")
async def get_review(exam_id: str, user: Student = Depends(current_user)):
    data = store.get_review(exam_id, user_id=str(user.id))
    return data if data else JSONResponse({"error": "not found"}, 404)


@app.post("/exams/{exam_id}/star")
async def toggle_star(exam_id: str, user: Student = Depends(current_user)):
    new_state = store.toggle_star(exam_id, user_id=str(user.id))
    if new_state is False and not store.get_exam(exam_id, user_id=str(user.id)):
        return JSONResponse({"error": "not found"}, 404)
    return {"exam_id": exam_id, "starred": new_state}


@app.delete("/exams/{exam_id}")
async def delete_exam(exam_id: str, user: Student = Depends(current_user)):
    if store.delete_exam(exam_id, user_id=str(user.id)):
        return {"deleted": True, "exam_id": exam_id}
    return JSONResponse({"error": "not found"}, 404)


@app.post("/exams/batch-delete")
async def batch_delete_exams(request: Request, user: Student = Depends(current_user)):
    body = await request.json()
    ids = body.get("ids", [])
    if not ids:
        return JSONResponse({"error": "ids required"}, 400)
    count = store.delete_exams(ids, user_id=str(user.id))
    return {"deleted": count, "ids": ids}


# ═══════════════════════════════════════════════════════════════
# SSE
# ═══════════════════════════════════════════════════════════════

@app.get("/sse/ui")
async def sse_ui(session: str = Query(...)):
    from engine import _strict_mode as engine_strict_mode
    if session not in ui_queues and session not in engine_strict_mode:
        await asyncio.sleep(0)
        if session not in ui_queues:
            return JSONResponse({"error": "session not found"}, 404)
    q = asyncio.Queue()
    ui_queues.setdefault(session, []).append(q)

    async def stream():
        try:
            yield f"data: {json.dumps({'stage': 'connected', 'session': session}, ensure_ascii=False)}\n\n"
            while True:
                get_task = asyncio.create_task(q.get())
                try:
                    data = await asyncio.wait_for(get_task, timeout=config.sse_heartbeat_timeout)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                    if data.get("stage") in ("stage2", "error") and data.get("status") in (
                        "done", "ocr_failed", "api_error", "unknown"):
                        break
                except asyncio.TimeoutError:
                    get_task.cancel()
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            try:
                data = q.get_nowait()
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
            except asyncio.QueueEmpty:
                pass
        finally:
            queues = ui_queues.get(session, [])
            if q in queues:
                queues.remove(q)
            if not queues:
                ui_queues.pop(session, None)
                cancel_session(session)
                from engine import _strict_mode
                _strict_mode.pop(session, None)
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/debug/client-error")
async def debug_client_error(request: Request):
    import sys
    body = await request.json()
    print(
        f"[CLIENT_ERROR] {body.get('message','?')} | "
        f"{body.get('filename','?')}:{body.get('lineno','?')} | "
        f"{body.get('userAgent','?')[:80]}",
        file=sys.stderr, flush=True)
    if body.get('stack'):
        print(f"  STACK: {body['stack'][:300]}", file=sys.stderr, flush=True)
    return {"status": "logged"}


if config.webui_dir.exists():
    app.mount("/", CORSStaticFiles(directory=str(config.webui_dir), html=True), name="webui")

if __name__ == "__main__":
    proto = "https" if getattr(config, 'ssl_enabled', False) else "http"
    print(f"Exam Tutor Agent starting on {proto}://{config.server_host}:{config.server_port}")
    uvicorn_kwargs = dict(host=config.server_host, port=config.server_port, log_level="info")
    if getattr(config, 'ssl_enabled', False):
        uvicorn_kwargs["ssl_keyfile"] = str(config.ssl_key_file)
        uvicorn_kwargs["ssl_certfile"] = str(config.ssl_cert_file)
    uvicorn.run(app, **uvicorn_kwargs)

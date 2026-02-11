from __future__ import annotations

from pathlib import Path
from typing import Optional
import os
import datetime
import base64
import binascii
import time
import json
from collections import deque
from threading import Lock

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel

from core import db
from core import settings as app_settings
from core.ocr_pipeline import prepare_debug_artifacts, run_face_match_scan, run_security_scan
from core import face_match
from core import media
from core import queue as rq_queue
from core import tasks as background_tasks_runner

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") == "1"
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "20"))
SSE_POLL_INTERVAL_SEC = float(os.getenv("SSE_POLL_INTERVAL_SEC", "2"))
REPROCESS_BATCH_MAX = int(os.getenv("REPROCESS_BATCH_MAX", "50"))
TRUST_PROXY = os.getenv("TRUST_PROXY", "1") == "1"
_rate_lock = Lock()
_rate_buckets: dict[str, deque[float]] = {}
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
DEBUG_PIN = os.getenv("DEBUG_PIN", "1150445")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-session-secret")
PRODUCTION = os.getenv("PRODUCTION", "0") == "1"

BASE_DIR = media.BASE_DIR
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
DATA_DIR = media.DATA_DIR
DEBUG_DIR = media.DEBUG_DIR
PHOTO_DIR = media.PHOTO_DIR
CARD_DIR = media.CARD_DIR

media.ensure_dirs()

app = FastAPI(title="بوابة التحقق من بطاقة الرقم القومي", version="1.0.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    same_site="lax",
    https_only=PRODUCTION,
)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/debug-images", StaticFiles(directory=str(DEBUG_DIR)), name="debug-images")
app.mount("/person-photos", StaticFiles(directory=str(PHOTO_DIR)), name="person-photos")
app.mount("/card-images", StaticFiles(directory=str(CARD_DIR)), name="card-images")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class BlockRequest(BaseModel):
    national_id: str
    reason: Optional[str] = None


class UnblockRequest(BaseModel):
    national_id: str


class SettingsRequest(BaseModel):
    docai_grayscale: bool
    face_match_enabled: Optional[bool] = None
    face_match_threshold: Optional[float] = None
    docai_max_dim: Optional[int] = None
    docai_jpeg_quality: Optional[int] = None


class UpdatePersonRequest(BaseModel):
    national_id: str
    full_name: Optional[str] = None
    new_national_id: Optional[str] = None


class Base64ScanRequest(BaseModel):
    image_base64: str
    gate_number: Optional[int] = None


class DebugPinRequest(BaseModel):
    pin: str


class BatchRotateRequest(BaseModel):
    national_ids: list[str]
    direction: str


@app.on_event("startup")
def on_startup() -> None:
    media.ensure_dirs()
    db.init_db()
    try:
        face_match.warm_up()
    except Exception as exc:
        print(f"[FACE] Warm-up failed: {exc}")


def _require_api_key(request: Request) -> None:
    expected = os.getenv("SECURITY_API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="SECURITY_API_KEY غير مضبوط")
    provided = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="مفتاح API غير صحيح")




def _decode_base64_image(value: str) -> bytes:
    if not value:
        raise HTTPException(status_code=400, detail="بيانات الصورة فارغة")
    payload = value.strip()
    if payload.startswith("data:"):
        comma_index = payload.find(",")
        if comma_index != -1:
            payload = payload[comma_index + 1 :]
    try:
        return base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail="Base64 غير صالح")


def _cleanup_raw_file(raw_path: Optional[str]) -> None:
    if not raw_path:
        return
    try:
        Path(raw_path).unlink()
    except Exception:
        pass


def _cleanup_card_file(card_filename: Optional[str]) -> None:
    if not card_filename:
        return
    try:
        (CARD_DIR / card_filename).unlink()
    except Exception:
        pass


def _client_ip(request: Request) -> str:
    if TRUST_PROXY:
        forwarded = request.headers.get("X-Forwarded-For") or request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _enforce_rate_limit(request: Request) -> None:
    if not RATE_LIMIT_ENABLED:
        return
    ip = _client_ip(request)
    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets.setdefault(ip, deque())
        cutoff = now - RATE_LIMIT_WINDOW_SEC
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX:
            raise HTTPException(status_code=429, detail="معدل الطلبات عالي، حاول لاحقاً")
        bucket.append(now)


def _is_authenticated(request: Request) -> bool:
    return bool(request.session.get("admin_auth"))


def _require_admin(request: Request) -> None:
    if not _is_authenticated(request):
        raise HTTPException(status_code=401, detail="غير مصرح")


def _require_debug_access(request: Request) -> None:
    _require_admin(request)
    if not request.session.get("debug_unlocked"):
        raise HTTPException(status_code=403, detail="الرمز غير صحيح أو غير مفعل")


def _process_scan(image_bytes: bytes) -> dict:
    original_card_filename = media.save_original_card_image(image_bytes)
    scan = run_security_scan(image_bytes)
    if scan.error:
        return {
            "status": "error",
            "message": scan.error,
            "ocr": {"full_name": "", "national_id": ""},
            "timings": scan.timings,
        }
    ocr = scan.ocr
    national_id = (ocr.national_id or "").strip()
    full_name = (ocr.full_name or "").strip()
    face_match_info = scan.face_match
    ocr_source = "docai" if scan.docai else "tesseract"
    photo_available = scan.photo_image is not None

    if not photo_available:
        return {
            "status": "error",
            "message": "لم يتم استخراج صورة واضحة من البطاقة",
            "ocr": {"full_name": full_name, "national_id": national_id},
            "timings": scan.timings,
        }

    if face_match_info and face_match_info.get("matched"):
        matched_person = face_match_info.get("person") or {}
        nid = matched_person.get("national_id") or national_id
        if not nid:
            return {
                "status": "error",
                "message": "تعذر تحديد الرقم القومي",
                "ocr": {"full_name": full_name, "national_id": national_id},
                "match": face_match_info,
            }

        photo_filename = None
        card_filename = original_card_filename
        if scan.photo_image is not None:
            photo_filename = media.save_person_photo(scan.photo_image, nid)
        if card_filename is None and scan.card_image is not None:
            card_filename = media.save_card_image(scan.card_image, nid)
        embedding_blob = media.serialize_embedding(scan.face_embedding)

        db.increment_visit(nid)
        if photo_filename or card_filename or embedding_blob:
            db.update_media(
                nid,
                photo_path=photo_filename,
                card_path=card_filename,
                face_embedding=embedding_blob,
            )
            if embedding_blob:
                face_match.mark_index_dirty()
        person = db.get_person_by_nid(nid) or matched_person

        if person.get("blocked"):
            return {
                "status": "blocked",
                "message": "هذا الشخص محظور من الدخول",
                "reason": person.get("block_reason") or "غير محدد",
                "person": person,
                "ocr": {"full_name": person.get("full_name") or full_name, "national_id": nid},
                "match": face_match_info,
                "source": "face_match",
            }

        return {
            "status": "allowed",
            "message": "مسموح بالدخول",
            "person": person,
            "ocr": {"full_name": person.get("full_name") or full_name, "national_id": nid},
            "match": face_match_info,
            "source": "face_match",
        }

    if not national_id:
        if not full_name:
            return {
                "status": "error",
                "message": "لم يتم استخراج اسم أو رقم قومي",
                "ocr": {"full_name": full_name, "national_id": national_id},
                "source": "ocr",
            }
        national_id = media.generate_temp_nid()

    person = db.get_person_by_nid(national_id)
    photo_filename = None
    card_filename = original_card_filename
    if scan.photo_image is not None:
        photo_filename = media.save_person_photo(scan.photo_image, national_id)
    if card_filename is None and scan.card_image is not None:
        card_filename = media.save_card_image(scan.card_image, national_id)
    embedding_blob = media.serialize_embedding(scan.face_embedding)

    if person:
        if person["blocked"]:
            if photo_filename or card_filename or embedding_blob:
                db.update_media(
                    national_id,
                    photo_path=photo_filename,
                    card_path=card_filename,
                    face_embedding=embedding_blob,
                )
                if embedding_blob:
                    face_match.mark_index_dirty()
            return {
                "status": "blocked",
                "message": "هذا الشخص محظور من الدخول",
                "reason": person.get("block_reason") or "غير محدد",
                "person": person,
                "ocr": {"full_name": full_name, "national_id": national_id},
                "source": ocr_source,
            }

        db.increment_visit(national_id)
        db.update_name_if_missing(national_id, full_name)
        if photo_filename or card_filename or embedding_blob:
            db.update_media(
                national_id,
                photo_path=photo_filename,
                card_path=card_filename,
                face_embedding=embedding_blob,
            )
            if embedding_blob:
                face_match.mark_index_dirty()
        person = db.get_person_by_nid(national_id)

        return {
            "status": "allowed",
            "message": "مسموح بالدخول",
            "person": person,
            "ocr": {"full_name": full_name, "national_id": national_id},
            "source": ocr_source,
        }

    person = db.add_person(
        national_id,
        full_name,
        photo_filename,
        card_filename,
        embedding_blob,
    )
    if embedding_blob:
        face_match.mark_index_dirty()
    return {
        "status": "new",
        "message": "أول مرة - تم السماح بالدخول",
        "person": person,
        "ocr": {"full_name": full_name, "national_id": national_id},
        "source": ocr_source,
    }


def _process_scan_external(
    image_bytes: bytes,
    background_tasks: Optional[BackgroundTasks],
    gate_number: Optional[int] = None,
) -> dict:
    raw_path = media.save_raw_upload(image_bytes)
    original_card_filename = media.save_original_card_image(image_bytes)
    scan = run_face_match_scan(image_bytes)
    if scan.error:
        _cleanup_raw_file(raw_path)
        _cleanup_card_file(original_card_filename)
        return {
            "status": "error",
            "message": scan.error,
            "timings": scan.timings,
        }
    if scan.photo_image is None:
        _cleanup_raw_file(raw_path)
        _cleanup_card_file(original_card_filename)
        return {
            "status": "error",
            "message": "لم يتم استخراج صورة واضحة من البطاقة",
        }

    match_info = scan.face_match
    if match_info and match_info.get("matched"):
        person = match_info.get("person") or {}
        nid = person.get("national_id") or ""
        if not nid:
            _cleanup_raw_file(raw_path)
            _cleanup_card_file(original_card_filename)
            return {
                "status": "error",
                "message": "تعذر تحديد الرقم القومي",
            }

        photo_filename = media.save_person_photo(scan.photo_image, nid)
        card_filename = original_card_filename
        if card_filename is None and scan.card_image is not None:
            card_filename = media.save_card_image(scan.card_image, nid)
        embedding_blob = media.serialize_embedding(scan.face_embedding)
        db.increment_visit(nid)
        if photo_filename or card_filename or embedding_blob:
            db.update_media(
                nid,
                photo_path=photo_filename,
                card_path=card_filename,
                face_embedding=embedding_blob,
            )
            if embedding_blob:
                face_match.mark_index_dirty()
        if gate_number is not None:
            db.update_gate_number_if_missing(nid, gate_number)
        person = db.get_person_by_nid(nid) or person

        if person.get("blocked"):
            _cleanup_raw_file(raw_path)
            return {
                "status": "blocked",
                "message": "هذا الشخص محظور من الدخول",
                "reason": person.get("block_reason") or "غير محدد",
                "is_new": False,
            }

        _cleanup_raw_file(raw_path)
        return {
            "status": "allowed",
            "message": "مسموح بالدخول",
            "is_new": False,
        }

    placeholder_nid = media.generate_temp_nid()
    photo_filename = media.save_person_photo(scan.photo_image, placeholder_nid)
    card_filename = original_card_filename
    if card_filename is None and scan.card_image is not None:
        card_filename = media.save_card_image(scan.card_image, placeholder_nid)
    embedding_blob = media.serialize_embedding(scan.face_embedding)
    db.add_person(
        placeholder_nid,
        "",
        photo_filename,
        card_filename,
        embedding_blob,
        gate_number=gate_number,
    )
    if embedding_blob:
        face_match.mark_index_dirty()

    job_id = rq_queue.enqueue_registration(raw_path, original_card_filename, placeholder_nid, gate_number)
    if job_id is None:
        if background_tasks is not None:
            background_tasks.add_task(
                background_tasks_runner.register_person_job,
                raw_path,
                original_card_filename,
                placeholder_nid,
                gate_number,
            )
        else:
            background_tasks_runner.register_person_job(raw_path, original_card_filename, placeholder_nid, gate_number)

    return {
        "status": "allowed",
        "message": "مسموح بالدخول",
        "is_new": True,
    }


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    if _is_authenticated(request):
        return RedirectResponse("/admin", status_code=303)
    return RedirectResponse("/login", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    if _is_authenticated(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "is_authenticated": False, "error": None},
    )


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
        request.session["admin_auth"] = True
        request.session.pop("debug_unlocked", None)
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "is_authenticated": False, "error": "بيانات الدخول غير صحيحة"},
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/security", response_class=HTMLResponse)
def security(request: Request):
    raise HTTPException(status_code=404, detail="Not Found")


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    if not _is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "is_authenticated": True,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    raise HTTPException(status_code=404, detail="Not Found")


@app.get("/debug", response_class=HTMLResponse)
def debug(request: Request):
    if not _is_authenticated(request):
        return RedirectResponse("/login", status_code=303)
    if not request.session.get("debug_unlocked"):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(
        "debug.html",
        {
            "request": request,
            "is_authenticated": True,
        },
    )


@app.post("/api/debug/unlock")
def unlock_debug(request: Request, payload: DebugPinRequest):
    _require_admin(request)
    if payload.pin == DEBUG_PIN:
        request.session["debug_unlocked"] = True
        return {"status": "ok"}
    raise HTTPException(status_code=403, detail="الرمز غير صحيح")


@app.post("/api/v1/security/scan-base64")
def security_scan_base64(request: Request, payload: Base64ScanRequest, background_tasks: BackgroundTasks):
    _require_api_key(request)
    _enforce_rate_limit(request)
    image_bytes = _decode_base64_image(payload.image_base64)
    result = _process_scan_external(image_bytes, background_tasks, payload.gate_number)
    if result["status"] == "error":
        return JSONResponse(result, status_code=422)
    return result


@app.post("/api/debug")
async def debug_scan(request: Request, image: UploadFile = File(...)):
    _require_debug_access(request)
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="الملف لازم يكون صورة")

    image_bytes = await image.read()
    artifacts = prepare_debug_artifacts(image_bytes)
    if artifacts.get("status") == "error":
        return artifacts
    debug_image_url = f"/debug-images/debug_{artifacts['file_id']}.jpg"

    return {
        "status": "ok",
        "debug_image_url": debug_image_url,
        "docai_image_url": artifacts.get("docai_image_url"),
        "face_image_url": artifacts.get("face_image_url"),
        "fields": artifacts["fields"],
        "tesseract": artifacts["tesseract"],
        "docai": artifacts["docai"],
        "docai_entities": artifacts["docai_entities"],
        "timings": artifacts.get("timings", {}),
        "final": artifacts["final"],
    }


@app.get("/api/settings")
def get_settings(request: Request):
    _require_debug_access(request)
    return {
        "docai_grayscale": app_settings.get_docai_grayscale(),
        "face_match_enabled": app_settings.get_face_match_enabled(),
        "face_match_threshold": app_settings.get_face_match_threshold(),
        "docai_max_dim": app_settings.get_docai_max_dim(),
        "docai_jpeg_quality": app_settings.get_docai_jpeg_quality(),
    }


@app.post("/api/settings")
def update_settings(request: Request, payload: SettingsRequest):
    _require_debug_access(request)
    app_settings.set_docai_grayscale(payload.docai_grayscale)
    if payload.face_match_enabled is not None:
        app_settings.set_face_match_enabled(payload.face_match_enabled)
    if payload.face_match_threshold is not None:
        app_settings.set_face_match_threshold(payload.face_match_threshold)
    if payload.docai_max_dim is not None:
        app_settings.set_docai_max_dim(payload.docai_max_dim)
    if payload.docai_jpeg_quality is not None:
        app_settings.set_docai_jpeg_quality(payload.docai_jpeg_quality)
    return {
        "status": "ok",
        "docai_grayscale": app_settings.get_docai_grayscale(),
        "face_match_enabled": app_settings.get_face_match_enabled(),
        "face_match_threshold": app_settings.get_face_match_threshold(),
        "docai_max_dim": app_settings.get_docai_max_dim(),
        "docai_jpeg_quality": app_settings.get_docai_jpeg_quality(),
    }


@app.get("/api/admin/people")
def list_people(
    request: Request,
    q: Optional[str] = None,
    page: Optional[int] = None,
    page_size: Optional[int] = None,
):
    _require_admin(request)
    try:
        page_value = int(page or 1)
    except Exception:
        page_value = 1
    try:
        size_value = int(page_size or 25)
    except Exception:
        size_value = 50
    if page_value < 1:
        page_value = 1
    if size_value < 10:
        size_value = 10
    if size_value > 200:
        size_value = 200
    offset = (page_value - 1) * size_value
    people = db.search_people(q, limit=size_value, offset=offset)
    total = db.count_people(q)
    return {"items": people, "total": total, "page": page_value, "page_size": size_value}


@app.get("/api/admin/stream")
def admin_stream(request: Request, cursor_ts: Optional[str] = None, cursor_id: Optional[int] = None):
    _require_admin(request)
    try:
        cursor_id_value = int(cursor_id or 0)
    except Exception:
        cursor_id_value = 0
    cursor_ts_value = (cursor_ts or "").strip() or "1970-01-01T00:00:00"

    def _event(name: str, payload: dict) -> str:
        data = json.dumps(payload, ensure_ascii=False)
        return f"event: {name}\ndata: {data}\n\n"

    def _stream():
        nonlocal cursor_ts_value, cursor_id_value
        while True:
            try:
                changes = db.get_people_updated_since(cursor_ts_value, cursor_id_value, limit=500)
                if changes:
                    last = changes[-1]
                    cursor_ts_value = last.get("updated_at") or cursor_ts_value
                    cursor_id_value = last.get("id") or cursor_id_value
                    yield _event(
                        "changed",
                        {
                            "count": len(changes),
                            "cursor_ts": cursor_ts_value,
                            "cursor_id": cursor_id_value,
                        },
                    )
                else:
                    yield _event(
                        "heartbeat",
                        {"time": datetime.datetime.utcnow().isoformat() + "Z"},
                    )
                time.sleep(SSE_POLL_INTERVAL_SEC)
            except GeneratorExit:
                break
            except Exception as exc:
                print(f"[SSE] Stream error: {exc}")
                yield _event(
                    "heartbeat",
                    {"time": datetime.datetime.utcnow().isoformat() + "Z"},
                )
                time.sleep(SSE_POLL_INTERVAL_SEC)

    headers = {
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    }
    return StreamingResponse(_stream(), media_type="text/event-stream", headers=headers)


@app.get("/api/health")
def health_check():
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat() + "Z"}


@app.post("/api/admin/block")
def block_person(request: Request, payload: BlockRequest):
    _require_admin(request)
    person = db.set_block_status(payload.national_id, True, payload.reason)
    if not person:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    return {"status": "ok", "person": person}


@app.post("/api/admin/unblock")
def unblock_person(request: Request, payload: UnblockRequest):
    _require_admin(request)
    person = db.set_block_status(payload.national_id, False, None)
    if not person:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    return {"status": "ok", "person": person}


@app.post("/api/admin/update")
def update_person(request: Request, payload: UpdatePersonRequest):
    _require_admin(request)
    try:
        person = db.update_person(
            payload.national_id,
            full_name=payload.full_name,
            new_national_id=payload.new_national_id,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="الرقم القومي الجديد مستخدم بالفعل")
    if not person:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    face_match.mark_index_dirty()
    return {"status": "ok", "person": person}


@app.post("/api/admin/reprocess")
def reprocess_people(request: Request, payload: BatchRotateRequest, background_tasks: BackgroundTasks):
    _require_admin(request)
    if payload.direction not in {"cw", "ccw"}:
        raise HTTPException(status_code=400, detail="اتجاه التدوير غير صالح")
    raw_ids = [item.strip() for item in (payload.national_ids or []) if item and item.strip()]
    if not raw_ids:
        raise HTTPException(status_code=400, detail="لا توجد سجلات محددة")
    if len(raw_ids) > REPROCESS_BATCH_MAX:
        raise HTTPException(status_code=400, detail="عدد السجلات أكبر من الحد المسموح")

    job_ids: list[str] = []
    for nid in raw_ids:
        job_id = rq_queue.enqueue_reprocess(nid, payload.direction)
        if job_id is None:
            background_tasks.add_task(background_tasks_runner.reprocess_person_job, nid, payload.direction)
        else:
            job_ids.append(job_id)
    return {"status": "ok", "count": len(raw_ids), "jobs": job_ids}


@app.delete("/api/admin/people/{national_id}")
def delete_person(request: Request, national_id: str):
    _require_admin(request)
    deleted = db.delete_person(national_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    face_match.mark_index_dirty()
    return {"status": "ok"}

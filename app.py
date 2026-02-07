from __future__ import annotations

from pathlib import Path
from typing import Optional
import uuid
import os
import datetime
import base64
import binascii
import time
from collections import deque
from threading import Lock

import cv2
import numpy as np

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
import sqlite3

from core import db
from core import settings as app_settings
from core.ocr_pipeline import prepare_debug_artifacts, run_face_match_scan, run_security_scan
from core import face_match

RATE_LIMIT_ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1") == "1"
RATE_LIMIT_WINDOW_SEC = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "20"))
TRUST_PROXY = os.getenv("TRUST_PROXY", "1") == "1"
_rate_lock = Lock()
_rate_buckets: dict[str, deque[float]] = {}
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")
DEBUG_PIN = os.getenv("DEBUG_PIN", "1150445")
SESSION_SECRET = os.getenv("SESSION_SECRET", "change-this-session-secret")
PRODUCTION = os.getenv("PRODUCTION", "0") == "1"

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
DATA_DIR = BASE_DIR / "data"
DEBUG_DIR = DATA_DIR / "debug"
PHOTO_DIR = DATA_DIR / "photos"
CARD_DIR = DATA_DIR / "cards"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
PHOTO_DIR.mkdir(parents=True, exist_ok=True)
CARD_DIR.mkdir(parents=True, exist_ok=True)

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


class DebugPinRequest(BaseModel):
    pin: str


@app.on_event("startup")
def on_startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()


def _save_person_photo(photo_image, national_id: str) -> str:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch for ch in national_id if ch.isdigit())
    filename = f"{safe_id}_{uuid.uuid4().hex[:8]}.jpg"
    output_path = PHOTO_DIR / filename
    cv2.imwrite(str(output_path), photo_image)
    return filename


def _save_card_image(card_image, national_id: str) -> str:
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch for ch in national_id if ch.isdigit()) or "unknown"
    filename = f"{safe_id}_{uuid.uuid4().hex[:8]}.jpg"
    output_path = CARD_DIR / filename
    cv2.imwrite(str(output_path), card_image)
    return filename


def _save_original_card_image(image_bytes: bytes) -> Optional[str]:
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    data = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        return None
    filename = f"orig_{uuid.uuid4().hex[:10]}.jpg"
    output_path = CARD_DIR / filename
    cv2.imwrite(str(output_path), image)
    return filename


def _generate_temp_nid() -> str:
    return f"TEMP-{uuid.uuid4().hex[:12]}"


def _require_api_key(request: Request) -> None:
    expected = os.getenv("SECURITY_API_KEY")
    if not expected:
        raise HTTPException(status_code=500, detail="SECURITY_API_KEY غير مضبوط")
    provided = request.headers.get("X-API-Key") or request.headers.get("x-api-key")
    if not provided or provided != expected:
        raise HTTPException(status_code=401, detail="مفتاح API غير صحيح")


def _serialize_embedding(embedding) -> Optional[bytes]:
    if embedding is None:
        return None
    return face_match.serialize_embedding(embedding)


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
    original_card_filename = _save_original_card_image(image_bytes)
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
            photo_filename = _save_person_photo(scan.photo_image, nid)
        if card_filename is None and scan.card_image is not None:
            card_filename = _save_card_image(scan.card_image, nid)
        embedding_blob = _serialize_embedding(scan.face_embedding)

        db.increment_visit(nid)
        if photo_filename or card_filename or embedding_blob:
            db.update_media(
                nid,
                photo_path=photo_filename,
                card_path=card_filename,
                face_embedding=embedding_blob,
            )
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
        national_id = _generate_temp_nid()

    person = db.get_person_by_nid(national_id)
    photo_filename = None
    card_filename = original_card_filename
    if scan.photo_image is not None:
        photo_filename = _save_person_photo(scan.photo_image, national_id)
    if card_filename is None and scan.card_image is not None:
        card_filename = _save_card_image(scan.card_image, national_id)
    embedding_blob = _serialize_embedding(scan.face_embedding)

    if person:
        if person["blocked"]:
            if photo_filename or card_filename or embedding_blob:
                db.update_media(
                    national_id,
                    photo_path=photo_filename,
                    card_path=card_filename,
                    face_embedding=embedding_blob,
                )
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
    return {
        "status": "new",
        "message": "أول مرة - تم السماح بالدخول",
        "person": person,
        "ocr": {"full_name": full_name, "national_id": national_id},
        "source": ocr_source,
    }


def _register_person_async(image_bytes: bytes, original_card_filename: Optional[str]) -> None:
    scan = run_security_scan(image_bytes)
    if scan.error:
        print(f"[ASYNC] OCR failed: {scan.error}")
        return
    if scan.photo_image is None:
        print("[ASYNC] No face photo extracted, skipping registration.")
        return

    full_name = (scan.ocr.full_name or "").strip()
    national_id = (scan.ocr.national_id or "").strip()
    if len(national_id) != 14:
        national_id = ""
    if not national_id:
        national_id = _generate_temp_nid()

    photo_filename = _save_person_photo(scan.photo_image, national_id)
    card_filename = original_card_filename
    if card_filename is None and scan.card_image is not None:
        card_filename = _save_card_image(scan.card_image, national_id)
    embedding_blob = _serialize_embedding(scan.face_embedding)

    person = db.get_person_by_nid(national_id)
    if person:
        db.increment_visit(national_id)
        db.update_name_if_missing(national_id, full_name)
        if photo_filename or card_filename or embedding_blob:
            db.update_media(
                national_id,
                photo_path=photo_filename,
                card_path=card_filename,
                face_embedding=embedding_blob,
            )
        return

    db.add_person(
        national_id,
        full_name,
        photo_filename,
        card_filename,
        embedding_blob,
    )


def _process_scan_external(image_bytes: bytes, background_tasks: Optional[BackgroundTasks]) -> dict:
    original_card_filename = _save_original_card_image(image_bytes)
    scan = run_face_match_scan(image_bytes)
    if scan.error:
        return {
            "status": "error",
            "message": scan.error,
            "timings": scan.timings,
        }
    if scan.photo_image is None:
        return {
            "status": "error",
            "message": "لم يتم استخراج صورة واضحة من البطاقة",
        }

    match_info = scan.face_match
    if match_info and match_info.get("matched"):
        person = match_info.get("person") or {}
        nid = person.get("national_id") or ""
        if not nid:
            return {
                "status": "error",
                "message": "تعذر تحديد الرقم القومي",
            }

        photo_filename = _save_person_photo(scan.photo_image, nid)
        card_filename = original_card_filename
        if card_filename is None and scan.card_image is not None:
            card_filename = _save_card_image(scan.card_image, nid)
        embedding_blob = _serialize_embedding(scan.face_embedding)
        db.increment_visit(nid)
        if photo_filename or card_filename or embedding_blob:
            db.update_media(
                nid,
                photo_path=photo_filename,
                card_path=card_filename,
                face_embedding=embedding_blob,
            )
        person = db.get_person_by_nid(nid) or person

        if person.get("blocked"):
            return {
                "status": "blocked",
                "message": "هذا الشخص محظور من الدخول",
                "reason": person.get("block_reason") or "غير محدد",
                "is_new": False,
            }

        return {
            "status": "allowed",
            "message": "مسموح بالدخول",
            "is_new": False,
        }

    if background_tasks is not None:
        background_tasks.add_task(_register_person_async, image_bytes, original_card_filename)
    else:
        _register_person_async(image_bytes, original_card_filename)

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
    result = _process_scan_external(image_bytes, background_tasks)
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
def list_people(request: Request, q: Optional[str] = None):
    _require_admin(request)
    people = db.search_people(q)
    return {"items": people}


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
    return {"status": "ok", "person": person}


@app.delete("/api/admin/people/{national_id}")
def delete_person(request: Request, national_id: str):
    _require_admin(request)
    deleted = db.delete_person(national_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    return {"status": "ok"}

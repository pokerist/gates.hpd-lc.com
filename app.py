from __future__ import annotations

from pathlib import Path
from typing import Optional
import uuid
import os
import datetime
import base64
import binascii

import cv2
import numpy as np

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import sqlite3

from core import db
from core import settings as app_settings
from core.ocr_pipeline import prepare_debug_artifacts, run_security_scan
from core import face_match

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


def _process_scan(image_bytes: bytes) -> dict:
    original_card_filename = _save_original_card_image(image_bytes)
    scan = run_security_scan(image_bytes)
    ocr = scan.ocr
    national_id = (ocr.national_id or "").strip()
    full_name = (ocr.full_name or "").strip()
    face_match_info = scan.face_match
    ocr_source = "docai" if scan.docai else "tesseract"

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
        return {
            "status": "error",
            "message": "لم يتم استخراج رقم قومي",
            "ocr": {"full_name": full_name, "national_id": national_id},
            "source": "ocr",
        }

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


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
        },
    )


@app.get("/security", response_class=HTMLResponse)
def security(request: Request):
    return templates.TemplateResponse(
        "security.html",
        {
            "request": request,
        },
    )


@app.get("/admin", response_class=HTMLResponse)
def admin(request: Request):
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
        },
    )


@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
        },
    )


@app.get("/debug", response_class=HTMLResponse)
def debug(request: Request):
    return templates.TemplateResponse(
        "debug.html",
        {
            "request": request,
        },
    )


@app.post("/api/scan")
async def scan_card(image: UploadFile = File(...)):
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="الملف لازم يكون صورة")

    image_bytes = await image.read()
    payload = _process_scan(image_bytes)
    if payload["status"] == "error":
        return JSONResponse(payload, status_code=422)
    return payload


@app.post("/api/v1/security/scan")
async def security_scan_api(request: Request, image: UploadFile = File(...)):
    _require_api_key(request)
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="الملف لازم يكون صورة")
    image_bytes = await image.read()
    payload = _process_scan(image_bytes)
    if payload["status"] == "error":
        return JSONResponse(payload, status_code=422)
    return payload


@app.post("/api/v1/security/scan-base64")
def security_scan_base64(request: Request, payload: Base64ScanRequest):
    _require_api_key(request)
    image_bytes = _decode_base64_image(payload.image_base64)
    result = _process_scan(image_bytes)
    if result["status"] == "error":
        return JSONResponse(result, status_code=422)
    return result


@app.post("/api/debug")
async def debug_scan(image: UploadFile = File(...)):
    if image.content_type and not image.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="الملف لازم يكون صورة")

    image_bytes = await image.read()
    artifacts = prepare_debug_artifacts(image_bytes)
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
def get_settings():
    return {
        "docai_grayscale": app_settings.get_docai_grayscale(),
        "face_match_enabled": app_settings.get_face_match_enabled(),
        "face_match_threshold": app_settings.get_face_match_threshold(),
        "docai_max_dim": app_settings.get_docai_max_dim(),
        "docai_jpeg_quality": app_settings.get_docai_jpeg_quality(),
    }


@app.post("/api/settings")
def update_settings(payload: SettingsRequest):
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
def list_people(q: Optional[str] = None):
    people = db.search_people(q)
    return {"items": people}


@app.get("/api/health")
def health_check():
    return {"status": "ok", "time": datetime.datetime.utcnow().isoformat() + "Z"}


@app.post("/api/admin/block")
def block_person(payload: BlockRequest):
    person = db.set_block_status(payload.national_id, True, payload.reason)
    if not person:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    return {"status": "ok", "person": person}


@app.post("/api/admin/unblock")
def unblock_person(payload: UnblockRequest):
    person = db.set_block_status(payload.national_id, False, None)
    if not person:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    return {"status": "ok", "person": person}


@app.post("/api/admin/update")
def update_person(payload: UpdatePersonRequest):
    try:
        person = db.update_person(
            payload.national_id,
            full_name=payload.full_name,
            new_national_id=payload.new_national_id,
        )
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="الرقم القومي الجديد مستخدم بالفعل")
    if not person:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    return {"status": "ok", "person": person}


@app.delete("/api/admin/people/{national_id}")
def delete_person(national_id: str):
    deleted = db.delete_person(national_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    return {"status": "ok"}

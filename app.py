from __future__ import annotations

from pathlib import Path
from typing import Optional
import uuid

import cv2

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from core import db
from core.ocr_pipeline import prepare_debug_artifacts, run_ocr_with_photo

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
DATA_DIR = BASE_DIR / "data"
DEBUG_DIR = DATA_DIR / "debug"
PHOTO_DIR = DATA_DIR / "photos"

DATA_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_DIR.mkdir(parents=True, exist_ok=True)
PHOTO_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="بوابة التحقق من بطاقة الرقم القومي", version="1.0.0")

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/debug-images", StaticFiles(directory=str(DEBUG_DIR)), name="debug-images")
app.mount("/person-photos", StaticFiles(directory=str(PHOTO_DIR)), name="person-photos")

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class BlockRequest(BaseModel):
    national_id: str
    reason: Optional[str] = None


class UnblockRequest(BaseModel):
    national_id: str


@app.on_event("startup")
def on_startup() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    db.init_db()


def _save_person_photo(photo_image, national_id: str) -> str:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = "".join(ch for ch in national_id if ch.isdigit())
    filename = f"{safe_id}_{uuid.uuid4().hex[:8]}.jpg"
    output_path = PHOTO_DIR / filename
    cv2.imwrite(str(output_path), photo_image)
    return filename


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
    result, photo_image = run_ocr_with_photo(image_bytes)

    national_id = result.national_id
    full_name = result.full_name

    if len(national_id) != 14:
        return JSONResponse(
            {
                "status": "error",
                "message": "لم يتم استخراج رقم قومي صحيح (14 رقم)",
                "ocr": {
                    "full_name": full_name,
                    "national_id": national_id,
                },
            },
            status_code=422,
        )

    person = db.get_person_by_nid(national_id)
    photo_filename = None
    if photo_image is not None and (person is None or not person.get("photo_path")):
        photo_filename = _save_person_photo(photo_image, national_id)
    if person:
        if person["blocked"]:
            if photo_filename:
                db.update_photo_if_missing(national_id, photo_filename)
            return {
                "status": "blocked",
                "message": "هذا الشخص محظور من الدخول",
                "reason": person.get("block_reason") or "غير محدد",
                "person": person,
                "ocr": {
                    "full_name": full_name,
                    "national_id": national_id,
                },
            }

        db.increment_visit(national_id)
        db.update_name_if_missing(national_id, full_name)
        if photo_filename:
            db.update_photo_if_missing(national_id, photo_filename)
        person = db.get_person_by_nid(national_id)

        return {
            "status": "allowed",
            "message": "مسموح بالدخول",
            "person": person,
            "ocr": {
                "full_name": full_name,
                "national_id": national_id,
            },
        }

    person = db.add_person(national_id, full_name, photo_filename)
    return {
        "status": "new",
        "message": "أول مرة - تم السماح بالدخول",
        "person": person,
        "ocr": {
            "full_name": full_name,
            "national_id": national_id,
        },
    }


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
        "fields": artifacts["fields"],
        "easyocr": artifacts["easyocr"],
        "tesseract": artifacts["tesseract"],
        "final": artifacts["final"],
    }


@app.get("/api/admin/people")
def list_people(q: Optional[str] = None):
    people = db.search_people(q)
    return {"items": people}


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


@app.delete("/api/admin/people/{national_id}")
def delete_person(national_id: str):
    deleted = db.delete_person(national_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="الشخص غير موجود")
    return {"status": "ok"}

from __future__ import annotations

from pathlib import Path
from typing import Optional
import uuid

import cv2
import numpy as np

from core import face_match

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DEBUG_DIR = DATA_DIR / "debug"
PHOTO_DIR = DATA_DIR / "photos"
CARD_DIR = DATA_DIR / "cards"
RAW_DIR = DATA_DIR / "raw"


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    CARD_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)


def _safe_id(value: str) -> str:
    return "".join(ch for ch in value if ch.isdigit())


def save_person_photo(photo_image, national_id: str) -> str:
    ensure_dirs()
    safe_id = _safe_id(national_id)
    filename = f"{safe_id}_{uuid.uuid4().hex[:8]}.jpg"
    output_path = PHOTO_DIR / filename
    cv2.imwrite(str(output_path), photo_image)
    return filename


def save_card_image(card_image, national_id: str) -> str:
    ensure_dirs()
    safe_id = _safe_id(national_id) or "unknown"
    filename = f"{safe_id}_{uuid.uuid4().hex[:8]}.jpg"
    output_path = CARD_DIR / filename
    cv2.imwrite(str(output_path), card_image)
    return filename


def save_original_card_image(image_bytes: bytes) -> Optional[str]:
    ensure_dirs()
    data = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        return None
    filename = f"orig_{uuid.uuid4().hex[:10]}.jpg"
    output_path = CARD_DIR / filename
    cv2.imwrite(str(output_path), image)
    return filename


def save_raw_upload(image_bytes: bytes) -> str:
    ensure_dirs()
    filename = f"raw_{uuid.uuid4().hex}.bin"
    output_path = RAW_DIR / filename
    output_path.write_bytes(image_bytes)
    return str(output_path)


def generate_temp_nid() -> str:
    return f"TEMP-{uuid.uuid4().hex[:12]}"


def serialize_embedding(embedding) -> Optional[bytes]:
    if embedding is None:
        return None
    return face_match.serialize_embedding(embedding)

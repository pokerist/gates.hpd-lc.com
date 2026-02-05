from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import pytesseract
from ultralytics import YOLO
import easyocr

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "models"
DEBUG_DIR = BASE_DIR / "data" / "debug"
TESSDATA_DIR = BASE_DIR / "tessdata"

ID_CARD_MODEL_PATH = MODEL_DIR / "detect_id_card.pt"
FIELD_MODEL_PATH = MODEL_DIR / "detect_odjects.pt"
DIGITS_MODEL_PATH = MODEL_DIR / "detect_id.pt"

_id_card_model: Optional[YOLO] = None
_fields_model: Optional[YOLO] = None
_digits_model: Optional[YOLO] = None
_reader: Optional[easyocr.Reader] = None


@dataclass
class OcrResult:
    full_name: str
    national_id: str
    easyocr_raw: Dict[str, Any]
    tesseract_raw: Dict[str, Any]
    debug: Dict[str, Any]


def _ensure_models() -> None:
    global _id_card_model, _fields_model, _digits_model, _reader

    if _reader is None:
        _reader = easyocr.Reader(["ar"], gpu=False)

    if _id_card_model is None:
        _id_card_model = YOLO(str(ID_CARD_MODEL_PATH))

    if _fields_model is None:
        _fields_model = YOLO(str(FIELD_MODEL_PATH))

    if _digits_model is None:
        _digits_model = YOLO(str(DIGITS_MODEL_PATH))

    if TESSDATA_DIR.exists():
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)


def _tessdata_exists(lang: str) -> bool:
    return (TESSDATA_DIR / f"{lang}.traineddata").exists()


def _tess_lang(lang: str) -> str:
    return lang if _tessdata_exists(lang) else "ara"


def _tess_config(base_config: str = "") -> str:
    if TESSDATA_DIR.exists():
        extra = f"--tessdata-dir {TESSDATA_DIR}"
        return f"{base_config} {extra}".strip()
    return base_config


def _decode_image(image_bytes: bytes) -> np.ndarray:
    data = np.frombuffer(image_bytes, np.uint8)
    image = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("تعذر قراءة الصورة")
    return image


def _normalize_digits(text: str) -> str:
    if not text:
        return ""
    arabic_to_ascii = str.maketrans(
        "٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹",
        "01234567890123456789",
    )
    cleaned = text.translate(arabic_to_ascii)
    cleaned = re.sub(r"\D", "", cleaned)
    return cleaned


def _crop(image: np.ndarray, bbox: Tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = bbox
    x1 = max(0, x1)
    y1 = max(0, y1)
    x2 = min(image.shape[1], x2)
    y2 = min(image.shape[0], y2)
    return image[y1:y2, x1:x2]


def _best_box(boxes: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not boxes:
        return None
    return sorted(boxes, key=lambda b: b.get("conf", 0), reverse=True)[0]


def _easyocr_text(image: np.ndarray) -> str:
    if _reader is None:
        return ""
    try:
        results = _reader.readtext(image, detail=0, paragraph=True)
        return " ".join(results).strip()
    except Exception:
        return ""


def _tesseract_text(image: np.ndarray, lang: str, config: str = "") -> str:
    try:
        return pytesseract.image_to_string(image, lang=lang, config=_tess_config(config)).strip()
    except Exception:
        return ""


def _prep_for_tesseract(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binary


def _detect_card_bbox(image: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
    if _id_card_model is None:
        return None
    results = _id_card_model(image, verbose=False)[0]
    if results.boxes is None or len(results.boxes) == 0:
        return None
    best = None
    best_conf = -1.0
    for box in results.boxes:
        conf = float(box.conf[0]) if box.conf is not None else 0.0
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        if conf > best_conf:
            best_conf = conf
            best = (x1, y1, x2, y2)
    return best


def _detect_fields(card_image: np.ndarray) -> List[Dict[str, Any]]:
    if _fields_model is None:
        return []
    results = _fields_model(card_image, verbose=False)[0]
    boxes: List[Dict[str, Any]] = []
    if results.boxes is None:
        return boxes
    for box in results.boxes:
        cls_id = int(box.cls[0]) if hasattr(box.cls, "__len__") else int(box.cls)
        label = results.names.get(cls_id, str(cls_id))
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        conf = float(box.conf[0]) if box.conf is not None else 0.0
        boxes.append({
            "label": label,
            "bbox": (x1, y1, x2, y2),
            "conf": conf,
        })
    return boxes


def _detect_digits(nid_image: np.ndarray) -> str:
    if _digits_model is None:
        return ""
    results = _digits_model(nid_image, verbose=False)[0]
    digits: List[Tuple[int, str]] = []
    if results.boxes is None:
        return ""
    for box in results.boxes:
        cls_id = int(box.cls[0]) if hasattr(box.cls, "__len__") else int(box.cls)
        x1 = int(box.xyxy[0][0])
        digits.append((x1, str(cls_id)))
    digits.sort(key=lambda item: item[0])
    return "".join(d for _, d in digits)


def annotate_image(image: np.ndarray, fields: List[Dict[str, Any]]) -> np.ndarray:
    annotated = image.copy()
    for field in fields:
        x1, y1, x2, y2 = field["bbox"]
        label = field.get("label", "field")
        color = (0, 200, 255)
        if label.lower().startswith("nid"):
            color = (0, 140, 255)
        elif "name" in label.lower():
            color = (0, 255, 160)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        cv2.putText(
            annotated,
            label,
            (x1, max(0, y1 - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            2,
            cv2.LINE_AA,
        )
    return annotated


def _process(image_bytes: bytes) -> Tuple[OcrResult, np.ndarray, List[Dict[str, Any]]]:
    _ensure_models()

    image = _decode_image(image_bytes)
    card_bbox = _detect_card_bbox(image)
    if card_bbox:
        card_image = _crop(image, card_bbox)
    else:
        card_image = image
        card_bbox = (0, 0, image.shape[1], image.shape[0])

    fields = _detect_fields(card_image)

    name_labels = {
        "firstname",
        "lastname",
        "middlename",
        "fullname",
        "name",
        "firstName",
        "lastName",
    }
    name_lookup = {label.lower() for label in name_labels}

    name_parts: List[Tuple[int, str]] = []
    nid_candidates = [f for f in fields if f["label"].lower() in {"nid", "id", "nationalid", "national_id"}]

    for field in fields:
        label = field["label"]
        if label.lower() in name_lookup:
            crop = _crop(card_image, field["bbox"])
            text = _easyocr_text(crop)
            if text:
                name_parts.append((field["bbox"][0], text))

    name_parts.sort(key=lambda item: item[0])
    easyocr_name_raw = " ".join([part for _, part in name_parts]).strip()

    nid_field = _best_box(nid_candidates)
    nid_text = ""
    tesseract_nid_text = ""

    if nid_field:
        nid_crop = _crop(card_image, nid_field["bbox"])
        nid_text = _detect_digits(nid_crop)
        tess_nid_lang = _tess_lang("ara_number")
        tesseract_nid_text = _tesseract_text(
            _prep_for_tesseract(nid_crop),
            lang=tess_nid_lang,
            config="--psm 7 -c tessedit_char_whitelist=0123456789٠١٢٣٤٥٦٧٨٩",
        )
    else:
        tess_nid_lang = _tess_lang("ara_number")
        tesseract_nid_text = _tesseract_text(
            _prep_for_tesseract(card_image),
            lang=tess_nid_lang,
            config="--psm 6 -c tessedit_char_whitelist=0123456789٠١٢٣٤٥٦٧٨٩",
        )

    nid_text = _normalize_digits(nid_text)
    tesseract_nid_text = _normalize_digits(tesseract_nid_text)

    easyocr_nid_raw = nid_text

    if len(nid_text) != 14 and len(tesseract_nid_text) == 14:
        nid_text = tesseract_nid_text

    tess_name_lang = _tess_lang("ara_combined")
    tesseract_full_name = _tesseract_text(_prep_for_tesseract(card_image), lang=tess_name_lang, config="--psm 6")
    full_name = easyocr_name_raw
    if not full_name:
        full_name = tesseract_full_name.strip()

    easyocr_payload = {
        "full_name_raw": easyocr_name_raw,
        "national_id_raw": easyocr_nid_raw,
    }

    tesseract_payload = {
        "full_name_raw": tesseract_full_name,
        "national_id_raw": tesseract_nid_text,
    }

    debug_payload = {
        "card_bbox": card_bbox,
        "fields": fields,
    }

    print("[OCR][easyocr]", easyocr_payload)
    print("[OCR][tesseract]", tesseract_payload)

    return (
        OcrResult(
            full_name=full_name,
            national_id=nid_text,
            easyocr_raw=easyocr_payload,
            tesseract_raw=tesseract_payload,
            debug=debug_payload,
        ),
        card_image,
        fields,
    )


def run_ocr(image_bytes: bytes) -> OcrResult:
    result, _, _ = _process(image_bytes)
    return result


def save_debug_image(card_image: np.ndarray, fields: List[Dict[str, Any]]) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    annotated = annotate_image(card_image, fields)
    file_id = uuid.uuid4().hex
    output_path = DEBUG_DIR / f"debug_{file_id}.jpg"
    cv2.imwrite(str(output_path), annotated)
    return file_id


def prepare_debug_artifacts(image_bytes: bytes) -> Dict[str, Any]:
    result, card_image, fields = _process(image_bytes)
    file_id = save_debug_image(card_image, fields)

    return {
        "file_id": file_id,
        "card_bbox": result.debug["card_bbox"],
        "fields": fields,
        "easyocr": result.easyocr_raw,
        "tesseract": result.tesseract_raw,
        "final": {
            "full_name": result.full_name,
            "national_id": result.national_id,
        },
    }

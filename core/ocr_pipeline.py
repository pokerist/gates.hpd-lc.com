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
PHOTO_DIR = BASE_DIR / "data" / "photos"
TESSDATA_DIR = BASE_DIR / "tessdata"

ID_CARD_MODEL_PATH = MODEL_DIR / "detect_id_card.pt"
FIELD_MODEL_PATH = MODEL_DIR / "detect_odjects.pt"

_id_card_model: Optional[YOLO] = None
_fields_model: Optional[YOLO] = None
_reader: Optional[easyocr.Reader] = None
_tess_warned: set[str] = set()
_docai_warned: bool = False


@dataclass
class OcrResult:
    full_name: str
    national_id: str
    easyocr_raw: Dict[str, Any]
    tesseract_raw: Dict[str, Any]
    debug: Dict[str, Any]


def _ensure_models() -> None:
    global _id_card_model, _fields_model, _reader

    if _reader is None:
        _reader = easyocr.Reader(["ar"], gpu=False)

    if _id_card_model is None:
        _id_card_model = YOLO(str(ID_CARD_MODEL_PATH))

    if _fields_model is None:
        _fields_model = YOLO(str(FIELD_MODEL_PATH))

    if TESSDATA_DIR.exists():
        os.environ["TESSDATA_PREFIX"] = str(TESSDATA_DIR)


def _tessdata_exists(lang: str) -> bool:
    return (TESSDATA_DIR / f"{lang}.traineddata").exists()


def _tess_lang(lang: str) -> str:
    if _tessdata_exists(lang):
        return lang
    if lang not in _tess_warned:
        print(f"[TESSERACT] Missing traineddata for '{lang}'. Falling back to 'ara'.")
        _tess_warned.add(lang)
    return "ara"


def _tess_config(base_config: str = "") -> str:
    if TESSDATA_DIR.exists():
        extra = f"--tessdata-dir {TESSDATA_DIR}"
        return f"{base_config} {extra}".strip()
    return base_config


def _docai_settings() -> Optional[Dict[str, str]]:
    global _docai_warned
    processor_id = os.getenv("DOC_AI_PROCESSOR_ID")
    project_id = os.getenv("DOC_AI_PROJECT_NUMBER") or os.getenv("DOC_AI_PROJECT_ID")
    location = os.getenv("DOC_AI_LOCATION", "us")
    if not processor_id or not project_id:
        if not _docai_warned:
            print("[DOC-AI] Disabled: missing DOC_AI_PROJECT_* or DOC_AI_PROCESSOR_ID.")
            _docai_warned = True
        return None

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
    if creds_path and not Path(creds_path).exists():
        if not _docai_warned:
            print(f"[DOC-AI] Credentials file not found: {creds_path}")
            _docai_warned = True
        return None

    if not _docai_warned:
        short_processor = processor_id[:6] + "..." + processor_id[-4:]
        print(f"[DOC-AI] Enabled: project={project_id}, location={location}, processor={short_processor}")
        _docai_warned = True
    return {
        "processor_id": processor_id,
        "project_id": project_id,
        "location": location,
    }


def _docai_candidates(env_name: str, defaults: List[str]) -> List[str]:
    raw = os.getenv(env_name, "")
    if raw.strip():
        return [item.strip() for item in raw.split(",") if item.strip()]
    return defaults


def _match_entity_type(entity_type: str, candidates: List[str]) -> bool:
    normalized = entity_type.lower()
    for cand in candidates:
        cand_norm = cand.lower()
        if not cand_norm:
            continue
        if normalized == cand_norm or cand_norm in normalized:
            return True
    return False


def _entity_text(entity: Any, doc_text: str) -> str:
    if hasattr(entity, "mention_text") and entity.mention_text:
        return entity.mention_text
    normalized_value = getattr(entity, "normalized_value", None)
    if normalized_value is not None:
        text = getattr(normalized_value, "text", "")
        if text:
            return text
    text_anchor = getattr(entity, "text_anchor", None)
    if text_anchor is not None:
        segments = getattr(text_anchor, "text_segments", []) or []
        if doc_text and segments:
            parts = []
            for seg in segments:
                try:
                    start = int(getattr(seg, "start_index", 0) or 0)
                    end = int(getattr(seg, "end_index", 0) or 0)
                except (TypeError, ValueError):
                    continue
                if end > start:
                    parts.append(doc_text[start:end])
            return "".join(parts).strip()
    return ""


def _pick_best_entity(entities: List[Any], candidates: List[str], doc_text: str) -> str:
    best_text = ""
    best_conf = -1.0
    for entity in entities:
        entity_type = getattr(entity, "type_", "") or ""
        if not _match_entity_type(entity_type, candidates):
            continue
        confidence = float(getattr(entity, "confidence", 0.0) or 0.0)
        text = _entity_text(entity, doc_text).strip()
        if text and confidence >= best_conf:
            best_conf = confidence
            best_text = text
    return best_text


def _encode_jpeg(image: np.ndarray, quality: int = 95) -> bytes:
    success, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not success:
        raise ValueError("تعذر تحويل الصورة")
    return buffer.tobytes()


def _serialize_docai_entity(entity: Any, doc_text: str) -> Dict[str, Any]:
    return {
        "type": getattr(entity, "type_", "") or "",
        "text": _entity_text(entity, doc_text),
        "confidence": float(getattr(entity, "confidence", 0.0) or 0.0),
    }


def _docai_extract_fields(card_image: np.ndarray) -> Optional[Dict[str, Any]]:
    settings = _docai_settings()
    if settings is None:
        return None

    try:
        from google.cloud import documentai
    except Exception as exc:
        print(f"[DOC-AI] Library not available: {exc}")
        return None

    try:
        project_id = settings["project_id"]
        location = settings["location"]
        processor_id = settings["processor_id"]

        client_options = {"api_endpoint": f"{location}-documentai.googleapis.com"}
        client = documentai.DocumentProcessorServiceClient(client_options=client_options)
        name = client.processor_path(project_id, location, processor_id)

        raw_doc = documentai.RawDocument(
            content=_encode_jpeg(card_image, quality=95),
            mime_type="image/jpeg",
        )

        request = documentai.ProcessRequest(
            name=name,
            raw_document=raw_doc,
            skip_human_review=True,
        )

        result = client.process_document(request=request)
        doc_text = getattr(result.document, "text", "") or ""
        entities = list(getattr(result.document, "entities", []) or [])
        entity_items = [_serialize_docai_entity(entity, doc_text) for entity in entities]

        name_candidates = _docai_candidates(
            "DOC_AI_NAME_TYPES",
            ["full_name", "fullname", "fullName", "name", "arabic_name", "person_name"],
        )
        nid_candidates = _docai_candidates(
            "DOC_AI_NID_TYPES",
            ["national_id", "nationalid", "nationalID", "nid", "id_number", "identity_number"],
        )

        full_name = _pick_best_entity(entities, name_candidates, doc_text)
        national_id = _normalize_digits(_pick_best_entity(entities, nid_candidates, doc_text))

        if not full_name and not national_id:
            entity_types = [getattr(e, "type_", "") for e in entities if getattr(e, "type_", "")]
            preview = []
            for e in entities:
                etype = getattr(e, "type_", "")
                if not etype:
                    continue
                text = _entity_text(e, doc_text)
                preview.append(f\"{etype}:{text[:40]}\")
            print(f\"[DOC-AI] No matching entities. Types seen: {entity_types} | Samples: {preview}\")
            return None

        payload = {
            "full_name": full_name,
            "national_id": national_id,
            "entities": entity_items,
        }
        print("[OCR][docai]", payload)
        return payload
    except Exception as exc:
        print(f"[DOC-AI] Failed to process document: {exc}")
        return None


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


def _prepare_card(image_bytes: bytes) -> Tuple[np.ndarray, List[Dict[str, Any]], Tuple[int, int, int, int]]:
    _ensure_models()
    image = _decode_image(image_bytes)
    card_bbox = _detect_card_bbox(image)
    if card_bbox:
        card_image = _crop(image, card_bbox)
    else:
        card_image = image
        card_bbox = (0, 0, image.shape[1], image.shape[0])
    fields = _detect_fields(card_image)
    return card_image, fields, card_bbox


def _normalize_name_parts(parts: List[Dict[str, Any]]) -> str:
    if not parts:
        return ""
    parts.sort(key=lambda item: (item["priority"], -item["x"]))
    return " ".join([item["text"] for item in parts if item["text"]]).strip()


def _name_priority(label: str) -> int:
    label_lower = label.lower()
    if label_lower in {"firstname", "first_name", "givenname", "fname", "name_first", "first"}:
        return 0
    if label_lower in {"middlename", "middle_name", "secondname", "second_name", "second", "name2"}:
        return 1
    if label_lower in {"lastname", "last_name", "familyname", "surname", "lname", "last"}:
        return 2
    if label_lower in {"fullname", "name"}:
        return 3
    return 4


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


def _extract_photo_region(card_image: np.ndarray, fields: List[Dict[str, Any]]) -> Optional[np.ndarray]:
    candidates = []
    for field in fields:
        label = field.get("label", "").lower()
        if any(key in label for key in ["photo", "image", "img", "face", "portrait", "picture"]):
            candidates.append(field)

    if candidates:
        best = _best_box(candidates)
        if best:
            return _crop(card_image, best["bbox"])

    h, w = card_image.shape[:2]
    x1 = int(w * 0.05)
    x2 = int(w * 0.28)
    y1 = int(h * 0.08)
    y2 = int(h * 0.56)
    if x2 > x1 and y2 > y1:
        return card_image[y1:y2, x1:x2]
    return None


def _process(image_bytes: bytes, include_tess_name: bool = False) -> Tuple[OcrResult, np.ndarray, List[Dict[str, Any]]]:
    card_image, fields, card_bbox = _prepare_card(image_bytes)

    name_labels = {
        "firstname",
        "lastname",
        "middlename",
        "fullname",
        "name",
        "firstName",
        "lastName",
        "secondName",
    }
    name_lookup = {label.lower() for label in name_labels}

    name_parts: List[Dict[str, Any]] = []
    name_fields: List[Dict[str, Any]] = []
    nid_candidates = [f for f in fields if f["label"].lower() in {"nid", "id", "nationalid", "national_id"}]

    for field in fields:
        label = field["label"]
        if label.lower() in name_lookup:
            name_fields.append({
                "priority": _name_priority(label),
                "x": field["bbox"][0],
                "bbox": field["bbox"],
            })
            crop = _crop(card_image, field["bbox"])
            text = _easyocr_text(crop)
            if text:
                name_parts.append({
                    "priority": _name_priority(label),
                    "x": field["bbox"][0],
                    "text": text,
                })

    easyocr_name_raw = _normalize_name_parts(name_parts)

    nid_field = _best_box(nid_candidates)
    nid_text = ""
    tesseract_nid_text = ""

    if nid_field:
        nid_crop = _crop(card_image, nid_field["bbox"])
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

    tesseract_nid_text = _normalize_digits(tesseract_nid_text)
    nid_text = tesseract_nid_text

    tesseract_full_name = ""
    if include_tess_name and name_fields:
        tess_name_lang = _tess_lang("ara_combined")
        tess_parts: List[Dict[str, Any]] = []
        for field in name_fields:
            crop = _crop(card_image, field["bbox"])
            text = _tesseract_text(
                _prep_for_tesseract(crop),
                lang=tess_name_lang,
                config="--psm 7",
            )
            if text:
                tess_parts.append({
                    "priority": field["priority"],
                    "x": field["x"],
                    "text": text,
                })
        tesseract_full_name = _normalize_name_parts(tess_parts)
    full_name = easyocr_name_raw

    easyocr_payload = {
        "full_name_raw": easyocr_name_raw,
        "national_id_raw": "",
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
    result, _, _ = _process(image_bytes, include_tess_name=False)
    return result


def run_ocr_with_photo(image_bytes: bytes) -> Tuple[OcrResult, Optional[np.ndarray]]:
    card_image, fields, card_bbox = _prepare_card(image_bytes)
    photo = _extract_photo_region(card_image, fields)

    docai_payload = _docai_extract_fields(card_image)
    if docai_payload:
        local_result, _, _ = _process(image_bytes, include_tess_name=False)
        full_name = docai_payload.get("full_name") or local_result.full_name
        national_id = docai_payload.get("national_id") or local_result.national_id
        result = OcrResult(
            full_name=full_name,
            national_id=national_id,
            easyocr_raw=local_result.easyocr_raw,
            tesseract_raw=local_result.tesseract_raw,
            debug={"card_bbox": card_bbox, "fields": fields},
        )
        return result, photo

    result, _, _ = _process(image_bytes, include_tess_name=False)
    return result, photo


def save_debug_image(card_image: np.ndarray, fields: List[Dict[str, Any]]) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    annotated = annotate_image(card_image, fields)
    file_id = uuid.uuid4().hex
    output_path = DEBUG_DIR / f"debug_{file_id}.jpg"
    cv2.imwrite(str(output_path), annotated)
    return file_id


def prepare_debug_artifacts(image_bytes: bytes) -> Dict[str, Any]:
    card_image, fields, card_bbox = _prepare_card(image_bytes)
    result, _, _ = _process(image_bytes, include_tess_name=True)
    docai_payload = _docai_extract_fields(card_image)
    file_id = save_debug_image(card_image, fields)

    return {
        "file_id": file_id,
        "card_bbox": card_bbox,
        "fields": fields,
        "easyocr": result.easyocr_raw,
        "tesseract": result.tesseract_raw,
        "docai": docai_payload or {},
        "docai_entities": (docai_payload or {}).get("entities", []),
        "final": {
            "full_name": (docai_payload or {}).get("full_name", result.full_name),
            "national_id": (docai_payload or {}).get("national_id", result.national_id),
        },
    }

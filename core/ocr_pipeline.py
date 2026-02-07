from __future__ import annotations

import os
import re
import uuid
from time import perf_counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import pytesseract
from ultralytics import YOLO
from core import settings as app_settings
from core import face_match

BASE_DIR = Path(__file__).resolve().parent.parent
MODEL_DIR = BASE_DIR / "models"
DEBUG_DIR = BASE_DIR / "data" / "debug"
PHOTO_DIR = BASE_DIR / "data" / "photos"
TESSDATA_DIR = BASE_DIR / "tessdata"

ID_CARD_MODEL_PATH = MODEL_DIR / "detect_id_card.pt"
FIELD_MODEL_PATH = MODEL_DIR / "detect_odjects.pt"

_id_card_model: Optional[YOLO] = None
_fields_model: Optional[YOLO] = None
_tess_warned: set[str] = set()
_docai_warned: bool = False


@dataclass
class OcrResult:
    full_name: str
    national_id: str
    tesseract_raw: Dict[str, Any]
    debug: Dict[str, Any]


@dataclass
class ScanResult:
    ocr: OcrResult
    photo_image: Optional[np.ndarray]
    card_image: Optional[np.ndarray]
    fields: List[Dict[str, Any]]
    card_bbox: Optional[Tuple[int, int, int, int]]
    docai: Dict[str, Any]
    face_match: Optional[Dict[str, Any]]
    face_embedding: Optional[np.ndarray]
    timings: Dict[str, float]
    error: Optional[str] = None


class CardNotFoundError(Exception):
    pass


def _ensure_models() -> None:
    global _id_card_model, _fields_model

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


def _entity_properties(entity: Any) -> List[Any]:
    props = getattr(entity, "properties", None)
    if props is None:
        return []
    return list(props)

def _docai_property_priority(entity_type: str) -> int:
    label = entity_type.lower()
    if label in {"firstname", "first_name", "givenname", "fname"}:
        return 0
    if label in {"restname", "lastname", "last_name", "familyname", "surname", "lname", "secondname", "middlename"}:
        return 1
    return 2


def _entity_text_with_properties(entity: Any, doc_text: str) -> str:
    direct = _entity_text(entity, doc_text)
    if direct:
        return direct
    props = _entity_properties(entity)
    if not props:
        return ""
    ordered_props = sorted(
        props,
        key=lambda p: _docai_property_priority(getattr(p, "type_", "") or ""),
    )
    parts = []
    for prop in ordered_props:
        text = _entity_text(prop, doc_text)
        if text:
            parts.append(text)
    return " ".join(parts).strip()


def _pick_best_entity(entities: List[Any], candidates: List[str], doc_text: str) -> str:
    best_text = ""
    best_conf = -1.0
    for entity in entities:
        entity_type = getattr(entity, "type_", "") or ""
        if not _match_entity_type(entity_type, candidates):
            continue
        confidence = float(getattr(entity, "confidence", 0.0) or 0.0)
        text = _entity_text_with_properties(entity, doc_text).strip()
        if text and confidence >= best_conf:
            best_conf = confidence
            best_text = text
    return best_text


def _encode_jpeg(image: np.ndarray, quality: int = 95) -> bytes:
    success, buffer = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    if not success:
        raise ValueError("تعذر تحويل الصورة")
    return buffer.tobytes()


def _docai_max_dim() -> int:
    return app_settings.get_docai_max_dim()


def _docai_jpeg_quality() -> int:
    return app_settings.get_docai_jpeg_quality()


def _resize_for_docai(image: np.ndarray) -> np.ndarray:
    max_dim = _docai_max_dim()
    h, w = image.shape[:2]
    longest = max(h, w)
    if longest <= max_dim:
        return image
    scale = max_dim / float(longest)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _prepare_docai_image(card_image: np.ndarray) -> np.ndarray:
    docai_image = _resize_for_docai(card_image)
    if app_settings.get_docai_grayscale():
        docai_image = cv2.cvtColor(docai_image, cv2.COLOR_BGR2GRAY)
    return docai_image


def _serialize_docai_entity(entity: Any, doc_text: str) -> Dict[str, Any]:
    item = {
        "type": getattr(entity, "type_", "") or "",
        "text": _entity_text_with_properties(entity, doc_text),
        "confidence": float(getattr(entity, "confidence", 0.0) or 0.0),
    }
    props = _entity_properties(entity)
    if props:
        item["properties"] = [
            _serialize_docai_entity(prop, doc_text) for prop in props
        ]
    return item


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

        docai_image = _prepare_docai_image(card_image)
        raw_doc = documentai.RawDocument(
            content=_encode_jpeg(docai_image, quality=_docai_jpeg_quality()),
            mime_type="image/jpeg",
        )

        request = documentai.ProcessRequest(
            name=name,
            raw_document=raw_doc,
            skip_human_review=True,
        )

        result = client.process_document(request=request)
        doc_text = getattr(result.document, "text", "") or ""
        if not doc_text:
            print("[DOC-AI] Warning: document text is empty.")
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
                text = _entity_text_with_properties(e, doc_text)
                preview.append(f"{etype}:{text[:40]}")
            print(f"[DOC-AI] No matching entities. Types seen: {entity_types} | Samples: {preview}")
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


def _collect_name_fields(fields: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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
    name_fields: List[Dict[str, Any]] = []
    for field in fields:
        label = field["label"]
        if label.lower() in name_lookup:
            name_fields.append({
                "priority": _name_priority(label),
                "x": field["bbox"][0],
                "bbox": field["bbox"],
            })
    return name_fields


def _tesseract_nid_from_fields(card_image: np.ndarray, fields: List[Dict[str, Any]]) -> str:
    nid_candidates = [f for f in fields if f["label"].lower() in {"nid", "id", "nationalid", "national_id"}]
    nid_field = _best_box(nid_candidates)
    if nid_field:
        nid_crop = _crop(card_image, nid_field["bbox"])
        tess_nid_lang = _tess_lang("ara_number")
        nid_text = _tesseract_text(
            _prep_for_tesseract(nid_crop),
            lang=tess_nid_lang,
            config="--psm 7 -c tessedit_char_whitelist=0123456789٠١٢٣٤٥٦٧٨٩",
        )
    else:
        tess_nid_lang = _tess_lang("ara_number")
        nid_text = _tesseract_text(
            _prep_for_tesseract(card_image),
            lang=tess_nid_lang,
            config="--psm 6 -c tessedit_char_whitelist=0123456789٠١٢٣٤٥٦٧٨٩",
        )
    return _normalize_digits(nid_text)


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


def _prepare_assets_timed(
    image_bytes: bytes,
    timings: Dict[str, float],
) -> Tuple[np.ndarray, np.ndarray, List[Dict[str, Any]], Tuple[int, int, int, int], Optional[np.ndarray]]:
    t0 = perf_counter()
    _ensure_models()
    timings["model_load_ms"] = (perf_counter() - t0) * 1000

    t0 = perf_counter()
    image = _decode_image(image_bytes)
    timings["decode_ms"] = (perf_counter() - t0) * 1000

    t0 = perf_counter()
    card_bbox = _detect_card_bbox(image)
    timings["detect_card_ms"] = (perf_counter() - t0) * 1000
    if not card_bbox:
        raise CardNotFoundError("فشل إيجاد بطاقة شخصية في الصورة. برجاء التأكد من التصوير بشكل صحيح")

    if card_bbox:
        card_image = _crop(image, card_bbox)
    else:
        card_image = image
        card_bbox = (0, 0, image.shape[1], image.shape[0])

    t0 = perf_counter()
    fields = _detect_fields(card_image)
    timings["detect_fields_ms"] = (perf_counter() - t0) * 1000

    t0 = perf_counter()
    photo = _extract_photo_region(card_image, fields)
    timings["extract_photo_ms"] = (perf_counter() - t0) * 1000

    return image, card_image, fields, card_bbox, photo


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


def prepare_assets(image_bytes: bytes) -> Tuple[np.ndarray, List[Dict[str, Any]], Tuple[int, int, int, int], Optional[np.ndarray]]:
    card_image, fields, card_bbox = _prepare_card(image_bytes)
    photo = _extract_photo_region(card_image, fields)
    return card_image, fields, card_bbox, photo


def _process(image_bytes: bytes, include_tess_name: bool = False) -> Tuple[OcrResult, np.ndarray, List[Dict[str, Any]]]:
    card_image, fields, card_bbox = _prepare_card(image_bytes)
    name_fields = _collect_name_fields(fields)
    tesseract_nid_text = _tesseract_nid_from_fields(card_image, fields)
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
    full_name = tesseract_full_name

    tesseract_payload = {
        "full_name_raw": tesseract_full_name,
        "national_id_raw": tesseract_nid_text,
    }

    debug_payload = {
        "card_bbox": card_bbox,
        "fields": fields,
    }

    print("[OCR][tesseract]", tesseract_payload)

    return (
        OcrResult(
            full_name=full_name,
            national_id=nid_text,
            tesseract_raw=tesseract_payload,
            debug=debug_payload,
        ),
        card_image,
        fields,
    )


def run_ocr(image_bytes: bytes) -> OcrResult:
    result, _, _ = _process(image_bytes, include_tess_name=False)
    return result


def _tesseract_name_from_fields(card_image: np.ndarray, fields: List[Dict[str, Any]]) -> str:
    name_fields = _collect_name_fields(fields)
    if not name_fields:
        return ""
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
    return _normalize_name_parts(tess_parts)


def run_security_scan(image_bytes: bytes) -> ScanResult:
    timings: Dict[str, float] = {}
    total_start = perf_counter()
    try:
        _, card_image, fields, card_bbox, photo = _prepare_assets_timed(image_bytes, timings)
    except CardNotFoundError as exc:
        timings["total_ms"] = (perf_counter() - total_start) * 1000
        if timings:
            log_payload = {key: round(value, 2) for key, value in timings.items()}
            print("[TIMING]", log_payload)
        ocr = OcrResult(
            full_name="",
            national_id="",
            tesseract_raw={},
            debug={},
        )
        return ScanResult(
            ocr=ocr,
            photo_image=None,
            card_image=None,
            fields=[],
            card_bbox=None,
            docai={},
            face_match=None,
            face_embedding=None,
            timings=timings,
            error=str(exc),
        )
    face_match_info = None
    face_embedding = None

    if app_settings.get_face_match_enabled() and photo is not None:
        t0 = perf_counter()
        face_embedding = face_match.extract_face_embedding(photo)
        timings["face_embedding_ms"] = (perf_counter() - t0) * 1000
        if face_embedding is not None:
            threshold = app_settings.get_face_match_threshold()
            t0 = perf_counter()
            match = face_match.find_best_match(face_embedding, threshold)
            timings["face_match_ms"] = (perf_counter() - t0) * 1000
            if match:
                person, score = match
                print(f"[FACE] Match score={score:.3f} nid={person.get('national_id')}")
                person_payload = {
                    "national_id": person.get("national_id"),
                    "full_name": person.get("full_name"),
                    "blocked": person.get("blocked"),
                    "block_reason": person.get("block_reason"),
                    "visits": person.get("visits"),
                    "created_at": person.get("created_at"),
                    "last_seen_at": person.get("last_seen_at"),
                    "photo_path": person.get("photo_path"),
                    "card_path": person.get("card_path"),
                }
                face_match_info = {
                    "matched": True,
                    "score": score,
                    "person": person_payload,
                }
                ocr = OcrResult(
                    full_name=person_payload.get("full_name") or "",
                    national_id=person_payload.get("national_id") or "",
                    tesseract_raw={},
                    debug={"card_bbox": card_bbox, "fields": fields},
                )
                timings["total_ms"] = (perf_counter() - total_start) * 1000
                if timings:
                    log_payload = {key: round(value, 2) for key, value in timings.items()}
                    print("[TIMING]", log_payload)
                return ScanResult(
                    ocr=ocr,
                    photo_image=photo,
                    card_image=card_image,
                    fields=fields,
                    card_bbox=card_bbox,
                    docai={},
                    face_match=face_match_info,
                    face_embedding=face_embedding,
                    timings=timings,
                )

    t0 = perf_counter()
    docai_payload = _docai_extract_fields(card_image) or {}
    timings["docai_ms"] = (perf_counter() - t0) * 1000
    full_name = (docai_payload.get("full_name") or "").strip()
    docai_nid = _normalize_digits(docai_payload.get("national_id") or "")

    tesseract_payload = {
        "full_name_raw": "",
        "national_id_raw": "",
    }

    if docai_payload:
        if len(docai_nid) < 14:
            t0 = perf_counter()
            tess_nid = _tesseract_nid_from_fields(card_image, fields)
            timings["tesseract_nid_ms"] = (perf_counter() - t0) * 1000
            tesseract_payload["national_id_raw"] = tess_nid
            if len(tess_nid) > len(docai_nid):
                docai_nid = tess_nid
        national_id = docai_nid
    else:
        t0 = perf_counter()
        tesseract_full_name = _tesseract_name_from_fields(card_image, fields)
        timings["tesseract_name_ms"] = (perf_counter() - t0) * 1000
        t0 = perf_counter()
        tesseract_nid_text = _tesseract_nid_from_fields(card_image, fields)
        timings["tesseract_nid_ms"] = (perf_counter() - t0) * 1000
        tesseract_payload = {
            "full_name_raw": tesseract_full_name,
            "national_id_raw": tesseract_nid_text,
        }
        full_name = tesseract_full_name
        national_id = tesseract_nid_text

    if tesseract_payload["national_id_raw"] or tesseract_payload["full_name_raw"]:
        print("[OCR][tesseract]", tesseract_payload)

    ocr = OcrResult(
        full_name=full_name,
        national_id=national_id,
        tesseract_raw=tesseract_payload,
        debug={"card_bbox": card_bbox, "fields": fields},
    )

    timings["total_ms"] = (perf_counter() - total_start) * 1000
    if timings:
        log_payload = {key: round(value, 2) for key, value in timings.items()}
        print("[TIMING]", log_payload)

    return ScanResult(
        ocr=ocr,
        photo_image=photo,
        card_image=card_image,
        fields=fields,
        card_bbox=card_bbox,
        docai=docai_payload,
        face_match=face_match_info,
        face_embedding=face_embedding,
        timings=timings,
        error=None,
    )


def run_ocr_with_photo(image_bytes: bytes) -> Tuple[OcrResult, Optional[np.ndarray]]:
    scan = run_security_scan(image_bytes)
    return scan.ocr, scan.photo_image


def save_debug_image(card_image: np.ndarray, fields: List[Dict[str, Any]]) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    file_id = uuid.uuid4().hex
    output_path = DEBUG_DIR / f"debug_{file_id}.jpg"
    cv2.imwrite(str(output_path), card_image)
    return file_id


def _save_debug_variant(image: np.ndarray, name: str, file_id: str) -> str:
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    output_path = DEBUG_DIR / f"{name}_{file_id}.jpg"
    cv2.imwrite(str(output_path), image)
    return str(output_path)


def prepare_debug_artifacts(image_bytes: bytes) -> Dict[str, Any]:
    scan = run_security_scan(image_bytes)
    if scan.error:
        return {
            "status": "error",
            "message": scan.error,
            "timings": scan.timings,
        }
    card_image = scan.card_image
    fields = scan.fields
    card_bbox = scan.card_bbox
    file_id = save_debug_image(card_image, fields)

    docai_url = ""
    try:
        docai_image = _prepare_docai_image(card_image)
        encoded = _encode_jpeg(docai_image, quality=_docai_jpeg_quality())
        decoded = cv2.imdecode(np.frombuffer(encoded, np.uint8), cv2.IMREAD_UNCHANGED)
        if decoded is None:
            decoded = docai_image
        _save_debug_variant(decoded, "docai", file_id)
        docai_url = f"/debug-images/docai_{file_id}.jpg"
    except Exception:
        docai_url = ""

    face_url = ""
    if scan.photo_image is not None:
        _save_debug_variant(scan.photo_image, "face", file_id)
        face_url = f"/debug-images/face_{file_id}.jpg"

    tesseract_payload = {
        "full_name_raw": _tesseract_name_from_fields(card_image, fields),
        "national_id_raw": _tesseract_nid_from_fields(card_image, fields),
    }
    docai_payload = scan.docai or {}

    return {
        "file_id": file_id,
        "card_bbox": card_bbox,
        "fields": fields,
        "tesseract": tesseract_payload,
        "docai": docai_payload or {},
        "docai_entities": (docai_payload or {}).get("entities", []),
        "docai_image_url": docai_url,
        "face_image_url": face_url,
        "timings": scan.timings,
        "final": {
            "full_name": scan.ocr.full_name,
            "national_id": scan.ocr.national_id,
        },
    }

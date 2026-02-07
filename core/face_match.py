from __future__ import annotations

from typing import Any, Dict, Optional, Tuple, List
import os
from threading import Lock

import numpy as np
import cv2
from insightface.app import FaceAnalysis

from core import db

_face_app: Optional[FaceAnalysis] = None
_index_lock = Lock()
_annoy_index = None
_annoy_items: List[Tuple[Dict[str, Any], np.ndarray]] = []
_index_dirty = True

try:
    from annoy import AnnoyIndex
except Exception:  # pragma: no cover - optional
    AnnoyIndex = None

EMBEDDING_DIM = 512
FACE_MAX_DIM = int(os.getenv("FACE_MAX_DIM", "640"))
FACE_DET_SIZE_RAW = os.getenv("FACE_DET_SIZE", "320")
ANNOY_TREES = int(os.getenv("ANNOY_TREES", "10"))


def _ensure_face_app() -> FaceAnalysis:
    global _face_app
    if _face_app is None:
        det_size = _parse_det_size(FACE_DET_SIZE_RAW)
        _face_app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        _face_app.prepare(ctx_id=-1, det_size=det_size)
    return _face_app


def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image is None:
        return image
    if len(image.shape) == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def _parse_det_size(value: str) -> Tuple[int, int]:
    try:
        if "," in value:
            parts = [int(p.strip()) for p in value.split(",") if p.strip()]
            if len(parts) >= 2:
                return (parts[0], parts[1])
        size = int(value)
        return (size, size)
    except Exception:
        return (320, 320)


def _resize_for_face(image: np.ndarray) -> np.ndarray:
    if image is None:
        return image
    h, w = image.shape[:2]
    max_dim = max(h, w)
    if max_dim <= FACE_MAX_DIM:
        return image
    scale = FACE_MAX_DIM / float(max_dim)
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    return cv2.resize(image, (new_w, new_h), interpolation=cv2.INTER_AREA)


def _normalize_embedding(emb: np.ndarray) -> Optional[np.ndarray]:
    if emb is None:
        return None
    emb = np.asarray(emb, dtype=np.float32)
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb


def extract_face_embedding(image: np.ndarray) -> Optional[np.ndarray]:
    if image is None:
        return None
    app = _ensure_face_app()
    bgr = _to_bgr(image)
    bgr = _resize_for_face(bgr)
    faces = app.get(bgr)
    if not faces:
        return None
    best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    emb = getattr(best, "embedding", None)
    if emb is None:
        return None
    return _normalize_embedding(emb)


def serialize_embedding(embedding: np.ndarray) -> bytes:
    return embedding.astype(np.float32).tobytes()


def deserialize_embedding(blob: bytes) -> Optional[np.ndarray]:
    if blob is None:
        return None
    arr = np.frombuffer(blob, dtype=np.float32)
    if arr.size == 0:
        return None
    return _normalize_embedding(arr)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None:
        return -1.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return -1.0
    return float(np.dot(a, b) / denom)


def mark_index_dirty() -> None:
    global _index_dirty
    _index_dirty = True


def _build_annoy_index() -> None:
    global _annoy_index, _annoy_items, _index_dirty
    _annoy_items = []
    _annoy_index = None
    candidates = db.get_people_with_embeddings()
    if not candidates:
        _index_dirty = False
        return
    items: List[Tuple[Dict[str, Any], np.ndarray]] = []
    for person in candidates:
        blob = person.get("face_embedding")
        if not blob:
            continue
        emb = deserialize_embedding(blob)
        if emb is None:
            continue
        items.append((person, emb))
    if not items:
        _index_dirty = False
        return
    if AnnoyIndex is None:
        _annoy_items = items
        _index_dirty = False
        return
    index = AnnoyIndex(EMBEDDING_DIM, "angular")
    for idx, (_, emb) in enumerate(items):
        index.add_item(idx, emb.tolist())
    index.build(ANNOY_TREES)
    _annoy_items = items
    _annoy_index = index
    _index_dirty = False


def warm_up() -> None:
    _ensure_face_app()
    with _index_lock:
        if _index_dirty:
            _build_annoy_index()


def find_best_match(embedding: np.ndarray, threshold: float) -> Optional[Tuple[Dict[str, Any], float]]:
    if embedding is None:
        return None
    embedding = _normalize_embedding(embedding)
    if embedding is None:
        return None
    with _index_lock:
        if _index_dirty:
            _build_annoy_index()
        items = list(_annoy_items)
        index = _annoy_index

    if not items:
        return None

    best_person = None
    best_score = -1.0
    if index is None:
        for person, stored in items:
            score = cosine_similarity(embedding, stored)
            if score > best_score:
                best_score = score
                best_person = person
    else:
        idxs = index.get_nns_by_vector(embedding.tolist(), min(10, len(items)))
        for idx in idxs:
            person, stored = items[idx]
            score = cosine_similarity(embedding, stored)
            if score > best_score:
                best_score = score
                best_person = person

    if best_person is None:
        return None
    if best_score >= threshold:
        return best_person, best_score
    return None

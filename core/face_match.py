from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np
import cv2
from insightface.app import FaceAnalysis

from core import db

_face_app: Optional[FaceAnalysis] = None


def _ensure_face_app() -> FaceAnalysis:
    global _face_app
    if _face_app is None:
        _face_app = FaceAnalysis(
            name="buffalo_l",
            providers=["CPUExecutionProvider"],
        )
        _face_app.prepare(ctx_id=-1, det_size=(640, 640))
    return _face_app


def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image is None:
        return image
    if len(image.shape) == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


def extract_face_embedding(image: np.ndarray) -> Optional[np.ndarray]:
    if image is None:
        return None
    app = _ensure_face_app()
    bgr = _to_bgr(image)
    faces = app.get(bgr)
    if not faces:
        return None
    best = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
    emb = getattr(best, "embedding", None)
    if emb is None:
        return None
    emb = np.asarray(emb, dtype=np.float32)
    norm = np.linalg.norm(emb)
    if norm > 0:
        emb = emb / norm
    return emb


def serialize_embedding(embedding: np.ndarray) -> bytes:
    return embedding.astype(np.float32).tobytes()


def deserialize_embedding(blob: bytes) -> Optional[np.ndarray]:
    if blob is None:
        return None
    arr = np.frombuffer(blob, dtype=np.float32)
    if arr.size == 0:
        return None
    return arr


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    if a is None or b is None:
        return -1.0
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    if denom == 0:
        return -1.0
    return float(np.dot(a, b) / denom)


def find_best_match(embedding: np.ndarray, threshold: float) -> Optional[Tuple[Dict[str, Any], float]]:
    candidates = db.get_people_with_embeddings()
    best_person = None
    best_score = -1.0
    for person in candidates:
        blob = person.get("face_embedding")
        if not blob:
            continue
        stored = deserialize_embedding(blob)
        if stored is None:
            continue
        score = cosine_similarity(embedding, stored)
        if score > best_score:
            best_score = score
            best_person = person
    if best_person is None:
        return None
    if best_score >= threshold:
        return best_person, best_score
    return None

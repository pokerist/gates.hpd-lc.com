from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple
import os

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from core import db

EMBEDDING_DIM = 512
BASE_DIR = Path(__file__).resolve().parent.parent
INDEX_VERSION_FILE = BASE_DIR / "data" / "face_index.version"

FACE_MAX_DIM = int(os.getenv("FACE_MAX_DIM", "640"))
FACE_DET_SIZE_RAW = os.getenv("FACE_DET_SIZE", "640")
FACE_MIN_SCORE = float(os.getenv("FACE_MIN_SCORE", "0.5"))
FACE_MAX_CANDIDATES = int(os.getenv("FACE_MAX_CANDIDATES", "50"))

_cache_lock = Lock()
_embedding_matrix: Optional[np.ndarray] = None
_embedding_people: List[Dict[str, Any]] = []
_index_dirty = True
_index_version_mtime = 0.0


def _parse_det_size(value: str) -> Tuple[int, int]:
    try:
        if "," in value:
            parts = [int(p.strip()) for p in value.split(",") if p.strip()]
            if len(parts) >= 2:
                return (parts[0], parts[1])
        size = int(value)
        return (size, size)
    except Exception:
        return (640, 640)


@lru_cache(maxsize=1)
def _get_face_app() -> FaceAnalysis:
    det_size = _parse_det_size(FACE_DET_SIZE_RAW)
    app = FaceAnalysis(
        name="buffalo_l",
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=det_size)
    return app


def _to_bgr(image: np.ndarray) -> np.ndarray:
    if image is None:
        return image
    if len(image.shape) == 2:
        return cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    if image.shape[2] == 4:
        return cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
    return image


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


def _normalize_embedding(emb: Optional[np.ndarray]) -> Optional[np.ndarray]:
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
    app = _get_face_app()
    bgr = _resize_for_face(_to_bgr(image))
    faces = app.get(bgr)
    if not faces:
        return None
    if len(faces) != 1:
        return None
    face = faces[0]
    det_score = getattr(face, "det_score", None)
    if det_score is None:
        det_score = getattr(face, "score", None)
    if det_score is not None and det_score < FACE_MIN_SCORE:
        return None
    emb = getattr(face, "embedding", None)
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
    global _index_dirty, _index_version_mtime
    _index_dirty = True
    try:
        INDEX_VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        INDEX_VERSION_FILE.touch()
        _index_version_mtime = INDEX_VERSION_FILE.stat().st_mtime
    except Exception:
        pass


def _get_index_version_mtime() -> float:
    try:
        return INDEX_VERSION_FILE.stat().st_mtime
    except Exception:
        return 0.0


def _refresh_index_state() -> None:
    global _index_dirty, _index_version_mtime
    current = _get_index_version_mtime()
    if current > _index_version_mtime:
        _index_dirty = True
        _index_version_mtime = current


def _build_embedding_cache() -> None:
    global _embedding_matrix, _embedding_people, _index_dirty, _index_version_mtime
    people = db.get_people_with_embeddings()
    embeddings: List[np.ndarray] = []
    people_list: List[Dict[str, Any]] = []
    for person in people:
        blob = person.get("face_embedding")
        if not blob:
            continue
        emb = deserialize_embedding(blob)
        if emb is None:
            continue
        embeddings.append(emb)
        people_list.append(person)
    if embeddings:
        _embedding_matrix = np.vstack(embeddings).astype(np.float32)
        _embedding_people = people_list
    else:
        _embedding_matrix = None
        _embedding_people = []
    _index_dirty = False
    _index_version_mtime = _get_index_version_mtime()


def warm_up() -> None:
    _get_face_app()
    with _cache_lock:
        _refresh_index_state()
        if _index_dirty:
            _build_embedding_cache()


def find_best_match(embedding: np.ndarray, threshold: float) -> Optional[Tuple[Dict[str, Any], float]]:
    embedding = _normalize_embedding(embedding)
    if embedding is None:
        return None
    with _cache_lock:
        _refresh_index_state()
        if _index_dirty:
            _build_embedding_cache()
        matrix = _embedding_matrix
        people = list(_embedding_people)
    if matrix is None or not people:
        return None

    scores = np.dot(matrix, embedding)
    total = scores.shape[0]
    max_candidates = max(1, min(FACE_MAX_CANDIDATES, total))
    if total > max_candidates:
        top_idx = np.argpartition(scores, -max_candidates)[-max_candidates:]
        best_idx = int(top_idx[np.argmax(scores[top_idx])])
    else:
        best_idx = int(np.argmax(scores))

    best_score = float(scores[best_idx])
    if best_score >= threshold:
        return people[best_idx], best_score
    return None

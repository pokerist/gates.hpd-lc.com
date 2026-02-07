from __future__ import annotations

import os

from core import db


def _to_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def get_docai_grayscale() -> bool:
    raw = db.get_setting("docai_grayscale", "0")
    return _to_bool(raw, default=False)


def set_docai_grayscale(enabled: bool) -> None:
    db.set_setting("docai_grayscale", "1" if enabled else "0")


def get_face_match_enabled() -> bool:
    raw = db.get_setting("face_match_enabled", "1")
    return _to_bool(raw, default=True)


def set_face_match_enabled(enabled: bool) -> None:
    db.set_setting("face_match_enabled", "1" if enabled else "0")


def get_face_match_threshold() -> float:
    raw = db.get_setting("face_match_threshold", "0.35")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.35
    return max(0.2, min(value, 0.9))


def set_face_match_threshold(value: float) -> None:
    safe = max(0.2, min(float(value), 0.9))
    db.set_setting("face_match_threshold", f"{safe:.3f}")


def get_docai_max_dim() -> int:
    raw = db.get_setting("docai_max_dim")
    if raw is None:
        raw = os.getenv("DOC_AI_MAX_DIM", "1600")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 1600
    return max(640, min(value, 3000))


def set_docai_max_dim(value: int) -> None:
    safe = max(640, min(int(value), 3000))
    db.set_setting("docai_max_dim", str(safe))


def get_docai_jpeg_quality() -> int:
    raw = db.get_setting("docai_jpeg_quality")
    if raw is None:
        raw = os.getenv("DOC_AI_JPEG_QUALITY", "85")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 85
    return max(50, min(value, 95))


def set_docai_jpeg_quality(value: int) -> None:
    safe = max(50, min(int(value), 95))
    db.set_setting("docai_jpeg_quality", str(safe))

from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
APP_ENV = os.getenv("APP_ENV", "development").lower()
DEFAULT_DB_NAME = "gate_prod.db" if APP_ENV in {"prod", "production"} else "gate_dev.db"
DB_PATH = Path(os.getenv("DB_PATH", str(BASE_DIR / "data" / DEFAULT_DB_NAME)))


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "national_id": row["national_id"],
        "full_name": row["full_name"],
        "blocked": bool(row["blocked"]),
        "block_reason": row["block_reason"],
        "visits": row["visits"],
        "created_at": row["created_at"],
        "last_seen_at": row["last_seen_at"],
        "photo_path": row["photo_path"],
        "card_path": row["card_path"],
    }


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                national_id TEXT UNIQUE NOT NULL,
                full_name TEXT,
                blocked INTEGER NOT NULL DEFAULT 0,
                block_reason TEXT,
                visits INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                last_seen_at TEXT,
                photo_path TEXT,
                card_path TEXT,
                face_embedding BLOB
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_people_name ON people(full_name);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_people_nid ON people(national_id);")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("docai_grayscale", "0"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("face_match_enabled", "1"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("face_match_threshold", "0.35"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("docai_max_dim", "1600"),
        )
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            ("docai_jpeg_quality", "85"),
        )


def get_person_by_nid(national_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM people WHERE national_id = ?",
            (national_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def add_person(
    national_id: str,
    full_name: str,
    photo_path: Optional[str] = None,
    card_path: Optional[str] = None,
    face_embedding: Optional[bytes] = None,
) -> Dict[str, Any]:
    now = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO people (
                national_id,
                full_name,
                blocked,
                block_reason,
                visits,
                created_at,
                last_seen_at,
                photo_path,
                card_path,
                face_embedding
            )
            VALUES (?, ?, 0, NULL, 1, ?, ?, ?, ?, ?)
            """,
            (national_id, full_name, now, now, photo_path, card_path, face_embedding),
        )
    return get_person_by_nid(national_id)  # type: ignore[return-value]


def increment_visit(national_id: str) -> Optional[Dict[str, Any]]:
    now = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            "UPDATE people SET visits = visits + 1, last_seen_at = ? WHERE national_id = ?",
            (now, national_id),
        )
    return get_person_by_nid(national_id)


def update_name_if_missing(national_id: str, full_name: str) -> Optional[Dict[str, Any]]:
    if not full_name:
        return get_person_by_nid(national_id)
    with get_connection() as conn:
        conn.execute(
            "UPDATE people SET full_name = COALESCE(NULLIF(full_name, ''), ?) WHERE national_id = ?",
            (full_name, national_id),
        )
    return get_person_by_nid(national_id)


def update_photo_if_missing(national_id: str, photo_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not photo_path:
        return get_person_by_nid(national_id)
    with get_connection() as conn:
        conn.execute(
            "UPDATE people SET photo_path = COALESCE(NULLIF(photo_path, ''), ?) WHERE national_id = ?",
            (photo_path, national_id),
        )
    return get_person_by_nid(national_id)


def update_card_if_missing(national_id: str, card_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not card_path:
        return get_person_by_nid(national_id)
    with get_connection() as conn:
        conn.execute(
            "UPDATE people SET card_path = COALESCE(NULLIF(card_path, ''), ?) WHERE national_id = ?",
            (card_path, national_id),
        )
    return get_person_by_nid(national_id)


def update_media(
    national_id: str,
    photo_path: Optional[str] = None,
    card_path: Optional[str] = None,
    face_embedding: Optional[bytes] = None,
) -> Optional[Dict[str, Any]]:
    updates = []
    params: List[Any] = []
    if photo_path:
        updates.append("photo_path = ?")
        params.append(photo_path)
    if card_path:
        updates.append("card_path = ?")
        params.append(card_path)
    if face_embedding is not None:
        updates.append("face_embedding = ?")
        params.append(face_embedding)
    if not updates:
        return get_person_by_nid(national_id)
    params.append(national_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE people SET {', '.join(updates)} WHERE national_id = ?",
            params,
        )
    return get_person_by_nid(national_id)


def set_block_status(national_id: str, blocked: bool, reason: Optional[str]) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        conn.execute(
            "UPDATE people SET blocked = ?, block_reason = ? WHERE national_id = ?",
            (1 if blocked else 0, reason, national_id),
        )
    return get_person_by_nid(national_id)


def delete_person(national_id: str) -> bool:
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM people WHERE national_id = ?", (national_id,))
        return cur.rowcount > 0


def search_people(query: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        if query:
            q = f"%{query.strip()}%"
            rows = conn.execute(
                """
                SELECT * FROM people
                WHERE national_id LIKE ? OR full_name LIKE ?
                ORDER BY last_seen_at DESC, created_at DESC
                LIMIT ?
                """,
                (q, q, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM people
                ORDER BY last_seen_at DESC, created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    return [_row_to_dict(row) for row in rows]


def update_person(
    national_id: str,
    full_name: Optional[str] = None,
    new_national_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    updates = []
    params: List[Any] = []
    if full_name is not None:
        updates.append("full_name = ?")
        params.append(full_name)
    if new_national_id is not None and new_national_id.strip():
        updates.append("national_id = ?")
        params.append(new_national_id.strip())
    if not updates:
        return get_person_by_nid(national_id)
    params.append(national_id)
    with get_connection() as conn:
        conn.execute(
            f"UPDATE people SET {', '.join(updates)} WHERE national_id = ?",
            params,
        )
    return get_person_by_nid(new_national_id or national_id)


def get_people_with_embeddings(limit: int = 10000) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM people
            WHERE face_embedding IS NOT NULL
            ORDER BY last_seen_at DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    results = []
    for row in rows:
        results.append({
            **_row_to_dict(row),
            "face_embedding": row["face_embedding"],
        })
    return results


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?",
            (key,),
        ).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )

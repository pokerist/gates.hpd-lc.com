from __future__ import annotations

import datetime
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "gate.db"


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
                photo_path TEXT
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_people_name ON people(full_name);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_people_nid ON people(national_id);")
        try:
            conn.execute("ALTER TABLE people ADD COLUMN photo_path TEXT;")
        except sqlite3.OperationalError:
            pass


def get_person_by_nid(national_id: str) -> Optional[Dict[str, Any]]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM people WHERE national_id = ?",
            (national_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def add_person(national_id: str, full_name: str, photo_path: Optional[str] = None) -> Dict[str, Any]:
    now = datetime.datetime.utcnow().isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO people (national_id, full_name, blocked, block_reason, visits, created_at, last_seen_at, photo_path)
            VALUES (?, ?, 0, NULL, 1, ?, ?, ?)
            """,
            (national_id, full_name, now, now, photo_path),
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

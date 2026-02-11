from __future__ import annotations

import datetime
import os
import re
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

try:
    import psycopg2
    import psycopg2.extras
except Exception:  # pragma: no cover - optional in dev
    psycopg2 = None

BASE_DIR = Path(__file__).resolve().parent.parent
PG_SCHEMA_ENV = os.getenv("PG_SCHEMA", "gates")


def _detect_backend() -> str:
    forced = os.getenv("DB_BACKEND", "").strip().lower()
    if forced in {"sqlite", "postgres", "postgresql"}:
        return "postgres" if forced.startswith("post") else "sqlite"
    app_env = os.getenv("APP_ENV", "development").lower()
    if app_env in {"prod", "production"}:
        return "postgres"
    return "sqlite"


DB_BACKEND = _detect_backend()


def _utcnow() -> str:
    return datetime.datetime.utcnow().isoformat()


def _sqlite_path() -> Path:
    app_env = os.getenv("APP_ENV", "development").lower()
    default_name = "gate_prod.db" if app_env in {"prod", "production"} else "gate_dev.db"
    env_path = os.getenv("DB_PATH")
    if env_path and env_path.strip():
        return Path(env_path)
    return Path(str(BASE_DIR / "data" / default_name))


def _pg_dsn() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
    if url:
        return url
    host = os.getenv("PGHOST") or os.getenv("POSTGRES_HOST")
    dbname = os.getenv("PGDATABASE") or os.getenv("POSTGRES_DB")
    user = os.getenv("PGUSER") or os.getenv("POSTGRES_USER")
    password = os.getenv("PGPASSWORD") or os.getenv("POSTGRES_PASSWORD")
    port = os.getenv("PGPORT") or os.getenv("POSTGRES_PORT") or "5432"
    if host and dbname and user:
        pwd = f":{password}" if password else ""
        return f"postgresql://{user}{pwd}@{host}:{port}/{dbname}"
    raise RuntimeError("DATABASE_URL غير مضبوط للـ PostgreSQL")


def _pg_schema() -> str:
    raw = (PG_SCHEMA_ENV or "public").strip()
    if not raw:
        return "gates"
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", raw):
        return "gates"
    return raw


def _ensure_pg_schema(conn) -> None:
    schema = _pg_schema()
    try:
        with conn.cursor() as cur:
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
            cur.execute(f"SET search_path TO {schema}")
    except Exception:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO public")
        except Exception:
            pass


DB_PATH = _sqlite_path()


def _sql(query: str) -> str:
    if DB_BACKEND == "sqlite":
        return query.replace("%s", "?")
    return query


def get_connection():
    if DB_BACKEND == "postgres":
        if psycopg2 is None:
            raise RuntimeError("psycopg2 غير مثبت")
        conn = psycopg2.connect(_pg_dsn(), cursor_factory=psycopg2.extras.RealDictCursor)
        _ensure_pg_schema(conn)
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _execute(query: str, params: Sequence[Any] = ()) -> int:
    with get_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(_sql(query), params)
        except Exception as exc:
            if DB_BACKEND == "postgres":
                pgcode = getattr(exc, "pgcode", "")
                if pgcode in {"23505", "42710", "42P07"}:
                    return 0
            raise
        return getattr(cur, "rowcount", 0) or 0


def _fetchone(query: str, params: Sequence[Any] = ()) -> Optional[Any]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_sql(query), params)
        return cur.fetchone()


def _fetchall(query: str, params: Sequence[Any] = ()) -> List[Any]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(_sql(query), params)
        return list(cur.fetchall())


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, sqlite3.Row):
        keys = row.keys()
        return row[key] if key in keys else default
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def _row_to_dict(row: Any) -> Dict[str, Any]:
    return {
        "id": _row_value(row, "id"),
        "national_id": _row_value(row, "national_id"),
        "full_name": _row_value(row, "full_name"),
        "blocked": bool(_row_value(row, "blocked", 0)),
        "block_reason": _row_value(row, "block_reason"),
        "visits": _row_value(row, "visits", 0),
        "created_at": _row_value(row, "created_at"),
        "last_seen_at": _row_value(row, "last_seen_at"),
        "updated_at": _row_value(row, "updated_at"),
        "gate_number": _row_value(row, "gate_number"),
        "photo_path": _row_value(row, "photo_path"),
        "card_path": _row_value(row, "card_path"),
    }


def init_db() -> None:
    if DB_BACKEND == "postgres":
        _init_db_postgres()
    else:
        _init_db_sqlite()


def _init_db_sqlite() -> None:
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
                updated_at TEXT,
                gate_number INTEGER,
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
        _ensure_updated_at_sqlite(conn)
        _ensure_gate_number_sqlite(conn)


def _init_db_postgres() -> None:
    _execute(
        """
        CREATE TABLE IF NOT EXISTS people (
            id SERIAL PRIMARY KEY,
            national_id TEXT UNIQUE NOT NULL,
            full_name TEXT,
            blocked BOOLEAN NOT NULL DEFAULT FALSE,
            block_reason TEXT,
            visits INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL,
            last_seen_at TIMESTAMP,
            updated_at TIMESTAMP,
            gate_number INTEGER,
            photo_path TEXT,
            card_path TEXT,
            face_embedding BYTEA
        );
        """
    )
    _execute("CREATE INDEX IF NOT EXISTS idx_people_name ON people(full_name);")
    _execute("CREATE INDEX IF NOT EXISTS idx_people_nid ON people(national_id);")
    _execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    _execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
        ("docai_grayscale", "0"),
    )
    _execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
        ("face_match_enabled", "1"),
    )
    _execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
        ("face_match_threshold", "0.35"),
    )
    _execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
        ("docai_max_dim", "1600"),
    )
    _execute(
        "INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO NOTHING",
        ("docai_jpeg_quality", "85"),
    )
    _ensure_updated_at_postgres()
    _ensure_gate_number_postgres()


def _ensure_updated_at_sqlite(conn) -> None:
    try:
        columns = conn.execute("PRAGMA table_info(people);").fetchall()
    except Exception:
        return
    has_updated = False
    for col in columns:
        name = col[1] if len(col) > 1 else None
        if name == "updated_at":
            has_updated = True
            break
    if not has_updated:
        conn.execute("ALTER TABLE people ADD COLUMN updated_at TEXT")
    conn.execute(
        "UPDATE people SET updated_at = created_at WHERE updated_at IS NULL OR updated_at = ''"
    )


def _ensure_updated_at_postgres() -> None:
    _execute("ALTER TABLE people ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP")
    _execute("UPDATE people SET updated_at = created_at WHERE updated_at IS NULL")


def _ensure_gate_number_sqlite(conn) -> None:
    try:
        columns = conn.execute("PRAGMA table_info(people);").fetchall()
    except Exception:
        return
    has_gate = False
    for col in columns:
        name = col[1] if len(col) > 1 else None
        if name == "gate_number":
            has_gate = True
            break
    if not has_gate:
        conn.execute("ALTER TABLE people ADD COLUMN gate_number INTEGER")


def _ensure_gate_number_postgres() -> None:
    _execute("ALTER TABLE people ADD COLUMN IF NOT EXISTS gate_number INTEGER")


def get_person_by_nid(national_id: str) -> Optional[Dict[str, Any]]:
    row = _fetchone("SELECT * FROM people WHERE national_id = %s", (national_id,))
    return _row_to_dict(row) if row else None


def get_face_embedding(national_id: str) -> Optional[bytes]:
    row = _fetchone("SELECT face_embedding FROM people WHERE national_id = %s", (national_id,))
    return _row_value(row, "face_embedding")


def add_person(
    national_id: str,
    full_name: str,
    photo_path: Optional[str] = None,
    card_path: Optional[str] = None,
    face_embedding: Optional[bytes] = None,
    gate_number: Optional[int] = None,
) -> Dict[str, Any]:
    now = _utcnow()
    _execute(
        """
        INSERT INTO people (
            national_id,
            full_name,
            blocked,
            block_reason,
            visits,
            created_at,
            last_seen_at,
            updated_at,
            gate_number,
            photo_path,
            card_path,
            face_embedding
        )
        VALUES (%s, %s, %s, NULL, 1, %s, %s, %s, %s, %s, %s, %s)
        """,
        (national_id, full_name, False, now, now, now, gate_number, photo_path, card_path, face_embedding),
    )
    return get_person_by_nid(national_id)  # type: ignore[return-value]


def increment_visit(national_id: str) -> Optional[Dict[str, Any]]:
    now = _utcnow()
    _execute(
        "UPDATE people SET visits = visits + 1, last_seen_at = %s, updated_at = %s WHERE national_id = %s",
        (now, now, national_id),
    )
    return get_person_by_nid(national_id)


def update_name_if_missing(national_id: str, full_name: str) -> Optional[Dict[str, Any]]:
    if not full_name:
        return get_person_by_nid(national_id)
    now = _utcnow()
    _execute(
        "UPDATE people SET full_name = COALESCE(NULLIF(full_name, ''), %s), updated_at = %s WHERE national_id = %s",
        (full_name, now, national_id),
    )
    return get_person_by_nid(national_id)


def update_photo_if_missing(national_id: str, photo_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not photo_path:
        return get_person_by_nid(national_id)
    now = _utcnow()
    _execute(
        "UPDATE people SET photo_path = COALESCE(NULLIF(photo_path, ''), %s), updated_at = %s WHERE national_id = %s",
        (photo_path, now, national_id),
    )
    return get_person_by_nid(national_id)


def update_card_if_missing(national_id: str, card_path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not card_path:
        return get_person_by_nid(national_id)
    now = _utcnow()
    _execute(
        "UPDATE people SET card_path = COALESCE(NULLIF(card_path, ''), %s), updated_at = %s WHERE national_id = %s",
        (card_path, now, national_id),
    )
    return get_person_by_nid(national_id)


def update_gate_number_if_missing(national_id: str, gate_number: Optional[int]) -> Optional[Dict[str, Any]]:
    if gate_number is None:
        return get_person_by_nid(national_id)
    now = _utcnow()
    _execute(
        "UPDATE people SET gate_number = %s, updated_at = %s WHERE national_id = %s AND gate_number IS NULL",
        (gate_number, now, national_id),
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
        updates.append("photo_path = %s")
        params.append(photo_path)
    if card_path:
        updates.append("card_path = %s")
        params.append(card_path)
    if face_embedding is not None:
        updates.append("face_embedding = %s")
        params.append(face_embedding)
    if not updates:
        return get_person_by_nid(national_id)
    updates.append("updated_at = %s")
    params.append(_utcnow())
    params.append(national_id)
    _execute(
        f"UPDATE people SET {', '.join(updates)} WHERE national_id = %s",
        params,
    )
    return get_person_by_nid(national_id)


def set_block_status(national_id: str, blocked: bool, reason: Optional[str]) -> Optional[Dict[str, Any]]:
    now = _utcnow()
    _execute(
        "UPDATE people SET blocked = %s, block_reason = %s, updated_at = %s WHERE national_id = %s",
        (bool(blocked), reason, now, national_id),
    )
    return get_person_by_nid(national_id)


def delete_person(national_id: str) -> bool:
    return _execute("DELETE FROM people WHERE national_id = %s", (national_id,)) > 0


def search_people(query: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
    if query:
        q = f"%{query.strip()}%"
        rows = _fetchall(
            """
            SELECT * FROM people
            WHERE national_id LIKE %s OR full_name LIKE %s
            ORDER BY last_seen_at DESC, created_at DESC
            LIMIT %s
            """,
            (q, q, limit),
        )
    else:
        rows = _fetchall(
            """
            SELECT * FROM people
            ORDER BY last_seen_at DESC, created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
    return [_row_to_dict(row) for row in rows]


def get_people_updated_since(
    cursor_ts: Optional[str],
    cursor_id: int = 0,
    limit: int = 200,
) -> List[Dict[str, Any]]:
    effective_ts = (cursor_ts or "").strip() or "1970-01-01T00:00:00"
    if DB_BACKEND == "postgres":
        rows = _fetchall(
            """
            SELECT *
            FROM people
            WHERE updated_at IS NOT NULL
              AND (updated_at, id) > (%s, %s)
            ORDER BY updated_at ASC, id ASC
            LIMIT %s
            """,
            (effective_ts, int(cursor_id), limit),
        )
    else:
        rows = _fetchall(
            """
            SELECT *
            FROM people
            WHERE updated_at IS NOT NULL
              AND (updated_at > %s OR (updated_at = %s AND id > %s))
            ORDER BY updated_at ASC, id ASC
            LIMIT %s
            """,
            (effective_ts, effective_ts, int(cursor_id), limit),
        )
    return [_row_to_dict(row) for row in rows]


def update_person(
    national_id: str,
    full_name: Optional[str] = None,
    new_national_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    updates = []
    params: List[Any] = []
    if full_name is not None:
        updates.append("full_name = %s")
        params.append(full_name)
    if new_national_id is not None and new_national_id.strip():
        updates.append("national_id = %s")
        params.append(new_national_id.strip())
    if not updates:
        return get_person_by_nid(national_id)
    updates.append("updated_at = %s")
    params.append(_utcnow())
    params.append(national_id)
    try:
        _execute(
            f"UPDATE people SET {', '.join(updates)} WHERE national_id = %s",
            params,
        )
    except Exception as exc:
        if DB_BACKEND == "postgres" and getattr(exc, "pgcode", "") == "23505":
            raise ValueError("duplicate_nid") from exc
        if isinstance(exc, sqlite3.IntegrityError):
            raise ValueError("duplicate_nid") from exc
        raise
    return get_person_by_nid(new_national_id or national_id)


def get_people_with_embeddings(limit: int = 10000) -> List[Dict[str, Any]]:
    rows = _fetchall(
        """
        SELECT *
        FROM people
        WHERE face_embedding IS NOT NULL
        ORDER BY last_seen_at DESC, created_at DESC
        LIMIT %s
        """,
        (limit,),
    )
    results = []
    for row in rows:
        item = _row_to_dict(row)
        item["face_embedding"] = _row_value(row, "face_embedding")
        results.append(item)
    return results


def get_setting(key: str, default: Optional[str] = None) -> Optional[str]:
    row = _fetchone("SELECT value FROM settings WHERE key = %s", (key,))
    return _row_value(row, "value", default)


def set_setting(key: str, value: str) -> None:
    _execute(
        """
        INSERT INTO settings (key, value)
        VALUES (%s, %s)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )

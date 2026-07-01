from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


SCHEMA = """
CREATE TABLE IF NOT EXISTS admin_user (
    open_id TEXT PRIMARY KEY,
    name TEXT,
    email TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS api_keys (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    key_prefix TEXT NOT NULL,
    key_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    open_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    next TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_oauth_states_expires ON oauth_states(expires_at);
"""

API_KEY_PREFIX = "auc_"
API_KEY_PREFIX_LEN = 12
OAUTH_STATE_TTL_SECONDS = 600


@dataclass(frozen=True)
class AdminUser:
    open_id: str
    name: str | None
    email: str | None
    created_at: str


@dataclass(frozen=True)
class ApiKey:
    id: str
    name: str
    key_prefix: str
    key_hash: str
    created_at: str
    last_used_at: str | None = None
    revoked_at: str | None = None

    @property
    def revoked(self) -> bool:
        return self.revoked_at is not None


@dataclass(frozen=True)
class Session:
    id: str
    open_id: str
    created_at: str
    expires_at: str


class AdminSeatTakenError(Exception):
    pass


class AuthService:
    def __init__(self, db_path: Path, session_ttl_hours: float = 24):
        self.db_path = Path(db_path)
        self.session_ttl = timedelta(hours=session_ttl_hours)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_schema(self) -> None:
        last_error = None
        for attempt in range(10):
            try:
                with closing(self.connect()) as conn:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.executescript(SCHEMA)
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower():
                    raise
                last_error = exc
                time.sleep(0.1 * (attempt + 1))
        if last_error:
            raise last_error

    def get_admin(self) -> AdminUser | None:
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM admin_user LIMIT 1").fetchone()
        return self._row_to_admin(row) if row else None

    def register_or_check_admin(self, open_id: str, name: str | None, email: str | None) -> AdminUser:
        now = self._now_iso()
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM admin_user LIMIT 1").fetchone()
                if row is None:
                    conn.execute(
                        "INSERT INTO admin_user (open_id, name, email, created_at) VALUES (?, ?, ?, ?)",
                        (open_id, name, email, now),
                    )
                    conn.execute("COMMIT")
                    return AdminUser(open_id, name, email, now)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        if row["open_id"] != open_id:
            raise AdminSeatTakenError
        return self._row_to_admin(row)

    def create_api_key(self, name: str) -> tuple[ApiKey, str]:
        raw = API_KEY_PREFIX + secrets.token_urlsafe(32)
        record = ApiKey(uuid4().hex, name, raw[:API_KEY_PREFIX_LEN], self.hash_key(raw), self._now_iso())
        with closing(self.connect()) as conn:
            conn.execute(
                "INSERT INTO api_keys (id, name, key_prefix, key_hash, created_at) VALUES (?, ?, ?, ?, ?)",
                (record.id, record.name, record.key_prefix, record.key_hash, record.created_at),
            )
        return record, raw

    def verify_api_key(self, raw: str | None) -> ApiKey | None:
        if not raw:
            return None
        now = self._now_iso()
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
                (self.hash_key(raw),),
            ).fetchone()
            if row is None:
                return None
            conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
        return self._row_to_key(row, last_used_at=now)

    def list_api_keys(self) -> list[ApiKey]:
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
        return [self._row_to_key(row) for row in rows]

    def revoke_api_key(self, key_id: str) -> bool:
        with closing(self.connect()) as conn:
            result = conn.execute(
                "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (self._now_iso(), key_id),
            )
        return result.rowcount > 0

    def create_session(self, open_id: str) -> Session:
        now = self._now()
        session = Session(secrets.token_urlsafe(32), open_id, now.isoformat(), (now + self.session_ttl).isoformat())
        with closing(self.connect()) as conn:
            self._purge_expired(conn, now)
            conn.execute(
                "INSERT INTO sessions (id, open_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (session.id, session.open_id, session.created_at, session.expires_at),
            )
        return session

    def get_session(self, session_id: str | None) -> Session | None:
        if not session_id:
            return None
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM sessions WHERE id = ? AND expires_at > ?",
                (session_id, self._now_iso()),
            ).fetchone()
        return Session(row["id"], row["open_id"], row["created_at"], row["expires_at"]) if row else None

    def delete_session(self, session_id: str) -> None:
        with closing(self.connect()) as conn:
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def create_oauth_state(self, next_url: str | None) -> str:
        now = self._now()
        state = secrets.token_hex(16)
        with closing(self.connect()) as conn:
            self._purge_expired(conn, now)
            conn.execute(
                "INSERT INTO oauth_states (state, created_at, expires_at, next) VALUES (?, ?, ?, ?)",
                (state, now.isoformat(), (now + timedelta(seconds=OAUTH_STATE_TTL_SECONDS)).isoformat(), next_url),
            )
        return state

    def consume_oauth_state(self, state: str | None) -> tuple[bool, str | None]:
        if not state:
            return False, None
        with closing(self.connect()) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM oauth_states WHERE state = ?", (state,)).fetchone()
                conn.execute("DELETE FROM oauth_states WHERE state = ?", (state,))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
        if row is None or row["expires_at"] <= self._now_iso():
            return False, None
        return True, row["next"]

    @staticmethod
    def hash_key(raw: str) -> str:
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    @classmethod
    def _now_iso(cls) -> str:
        return cls._now().isoformat()

    @staticmethod
    def _purge_expired(conn: sqlite3.Connection, now: datetime) -> None:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now.isoformat(),))
        conn.execute("DELETE FROM oauth_states WHERE expires_at <= ?", (now.isoformat(),))

    @staticmethod
    def _row_to_admin(row: sqlite3.Row) -> AdminUser:
        return AdminUser(row["open_id"], row["name"], row["email"], row["created_at"])

    @staticmethod
    def _row_to_key(row: sqlite3.Row, last_used_at: str | None = None) -> ApiKey:
        return ApiKey(
            row["id"],
            row["name"],
            row["key_prefix"],
            row["key_hash"],
            row["created_at"],
            last_used_at if last_used_at is not None else row["last_used_at"],
            row["revoked_at"],
        )

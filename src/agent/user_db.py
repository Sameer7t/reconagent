import os
import uuid
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import psycopg2
from psycopg2.extras import RealDictCursor

logger = logging.getLogger("UserDatabase")

DEFAULT_PG_URL = os.getenv("DATABASE_URL")
DEFAULT_SQLITE_USER_PATH = Path("data") / "users.db"


class UserDatabase:
    """
    Enterprise user repository supporting PostgreSQL with seamless SQLite fallback.
    Ensures zero-downtime execution in standalone containers (e.g. Render, Railway)
    when external PostgreSQL is not provisioned or during development.
    """
    def __init__(self, db_url: Optional[str] = None, db_path: Optional[str] = None):
        self.db_url = db_url or os.getenv("DATABASE_URL") or DEFAULT_PG_URL
        self.db_path = Path(db_path) if db_path else DEFAULT_SQLITE_USER_PATH
        self.is_postgres = False
        self._conn = None

        if not self.db_url or str(db_path) == ":memory:" or (str(db_path).endswith(".db")):
            self._init_sqlite(str(self.db_path))
        else:
            try:
                self._init_postgres(self.db_url)
            except Exception as e:
                logger.warning(
                    f"PostgreSQL connection to {self.db_url} failed ({e}). "
                    f"Falling back to local SQLite at {self.db_path}."
                )
                self._init_sqlite(str(self.db_path))

    def _init_postgres(self, url: str):
        conn = psycopg2.connect(url, cursor_factory=RealDictCursor, connect_timeout=5)
        self._conn = conn
        self.is_postgres = True
        self.init_db()
        logger.info(f"UserDatabase: Connected to PostgreSQL ({url.split('@')[-1] if '@' in url else 'postgres'}).")

    def _init_sqlite(self, path: str):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self.is_postgres = False
        self.init_db()
        logger.info(f"UserDatabase: Connected to SQLite ({path}).")

    def _get_connection(self):
        if self.is_postgres:
            if self._conn is None or self._conn.closed:
                self._conn = psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)
        return self._conn

    def close(self):
        if self._conn is not None:
            try:
                if self.is_postgres and not self._conn.closed:
                    self._conn.close()
                elif not self.is_postgres:
                    self._conn.close()
            except Exception:
                pass

    def init_db(self):
        """Initializes the users table."""
        conn = self._get_connection()
        cur = conn.cursor()
        if self.is_postgres:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id UUID PRIMARY KEY,
                    email VARCHAR(255) UNIQUE NOT NULL,
                    password_hash VARCHAR(255) NOT NULL,
                    role VARCHAR(50) NOT NULL,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    is_active BOOLEAN DEFAULT TRUE
                );
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    is_active INTEGER DEFAULT 1
                );
            """)
        conn.commit()

    def _normalize_user(self, user: Optional[Any]) -> Optional[Dict[str, Any]]:
        if not user:
            return None
        user_dict = dict(user)
        if "id" in user_dict and user_dict["id"] is not None:
            user_dict["id"] = str(user_dict["id"])
        if "created_at" in user_dict and user_dict["created_at"] is not None:
            if hasattr(user_dict["created_at"], "isoformat"):
                user_dict["created_at"] = user_dict["created_at"].isoformat()
            else:
                user_dict["created_at"] = str(user_dict["created_at"])
        if "is_active" in user_dict:
            user_dict["is_active"] = bool(user_dict["is_active"])
        return user_dict

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        placeholder = "%s" if self.is_postgres else "?"
        cur.execute(f"SELECT * FROM users WHERE email = {placeholder}", (email,))
        return self._normalize_user(cur.fetchone())

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        placeholder = "%s" if self.is_postgres else "?"
        cur.execute(f"SELECT * FROM users WHERE id = {placeholder}", (user_id,))
        return self._normalize_user(cur.fetchone())

    def create_user(self, email: str, password_hash: str, role: str) -> Dict[str, Any]:
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        conn = self._get_connection()
        cur = conn.cursor()
        if self.is_postgres:
            cur.execute(
                """
                INSERT INTO users (id, email, password_hash, role, created_at, is_active)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id, email, role, created_at, is_active
                """,
                (user_id, email, password_hash, role, now, True)
            )
            user = cur.fetchone()
        else:
            cur.execute(
                """
                INSERT INTO users (id, email, password_hash, role, created_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, email, password_hash, role, now.isoformat(), 1)
            )
            cur.execute("SELECT id, email, role, created_at, is_active FROM users WHERE id = ?", (user_id,))
            user = cur.fetchone()
        conn.commit()
        return self._normalize_user(user)

    def list_users(self) -> List[Dict[str, Any]]:
        conn = self._get_connection()
        cur = conn.cursor()
        cur.execute("SELECT id, email, role, created_at, is_active FROM users ORDER BY created_at DESC")
        return [self._normalize_user(r) for r in cur.fetchall()]

    def delete_user(self, user_id: str) -> bool:
        conn = self._get_connection()
        cur = conn.cursor()
        if self.is_postgres:
            cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
            deleted = cur.fetchone()
        else:
            cur.execute("SELECT id FROM users WHERE id = ?", (user_id,))
            exists = cur.fetchone()
            if exists:
                cur.execute("DELETE FROM users WHERE id = ?", (user_id,))
                deleted = True
            else:
                deleted = False
        conn.commit()
        return bool(deleted)

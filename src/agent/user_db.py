import os
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

# Default to a local postgres if not provided
DEFAULT_PG_URL = os.getenv("DATABASE_URL", "postgresql://postgres:root@localhost:5432/reconagent")

class UserDatabase:
    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or DEFAULT_PG_URL
        self._conn = None
        self.init_db()

    def _get_connection(self):
        if self._conn is None or self._conn.closed:
            self._conn = psycopg2.connect(self.db_url, cursor_factory=RealDictCursor)
        return self._conn

    def close(self):
        if self._conn is not None and not self._conn.closed:
            self._conn.close()

    def init_db(self):
        """Initializes the PostgreSQL users table."""
        with self._get_connection() as conn:
            with conn.cursor() as cur:
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
            conn.commit()

    def _normalize_user(self, user: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
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
        return user_dict

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE email = %s", (email,))
                return self._normalize_user(cur.fetchone())

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                return self._normalize_user(cur.fetchone())

    def create_user(self, email: str, password_hash: str, role: str) -> Dict[str, Any]:
        user_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, email, password_hash, role, created_at, is_active)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id, email, role, created_at, is_active
                    """,
                    (user_id, email, password_hash, role, now, True)
                )
                user = cur.fetchone()
            conn.commit()
            return self._normalize_user(user)

    def list_users(self) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, email, role, created_at, is_active FROM users ORDER BY created_at DESC")
                return [self._normalize_user(r) for r in cur.fetchall()]

    def delete_user(self, user_id: str) -> bool:
        with self._get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s RETURNING id", (user_id,))
                deleted = cur.fetchone()
            conn.commit()
            return bool(deleted)

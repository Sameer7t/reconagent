"""
Enterprise Persistence Layer for ReconAgent.

Supports production-grade PostgreSQL with Threaded Connection Pooling,
while maintaining SQLite compatibility for isolated in-memory unit testing.
"""
import os
import json
import logging
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

import psycopg2
from psycopg2 import pool
from psycopg2.extras import Json

from agent.models import InvestigationResult

logger = logging.getLogger("InvestigationDatabase")

DEFAULT_DB_PATH = Path("data") / "investigations.db"
DEFAULT_PG_URL = os.getenv("DATABASE_URL", "postgresql://postgres:root@localhost:5432/reconagent")


class DictRow(dict):
    """
    Row wrapper that supports both key-based mapping (row['col'])
    and zero-based index access (row[0]), plus dict(row).
    Ensures 100% interoperability across SQLite and PostgreSQL query code.
    """
    def __init__(self, mapping: dict, tuple_vals: tuple):
        super().__init__(mapping)
        self._tuple = tuple_vals

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._tuple[key]
        return super().__getitem__(key)


class PGCursorWrapper:
    """Wraps a psycopg2 cursor to return DictRow instances."""
    def __init__(self, cur):
        self._cur = cur

    def _wrap_row(self, row):
        if row is None:
            return None
        cols = [d[0] for d in self._cur.description]
        normalized_row = []
        mapping = {}
        for col_name, val in zip(cols, row):
            if isinstance(val, datetime):
                val_normalized = val.isoformat()
            else:
                val_normalized = val
            mapping[col_name] = val_normalized
            normalized_row.append(val_normalized)
        return DictRow(mapping, tuple(normalized_row))

    def fetchone(self):
        row = self._cur.fetchone()
        return self._wrap_row(row)

    def fetchall(self):
        rows = self._cur.fetchall()
        return [self._wrap_row(r) for r in rows]

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size)
        return [self._wrap_row(r) for r in rows]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def description(self):
        return self._cur.description

    def __iter__(self):
        for row in self._cur:
            yield self._wrap_row(row)


class PGConnectionWrapper:
    """Wraps a psycopg2 pooled connection with execute() and parameter translation."""
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql: str, params=None):
        cur = self._conn.cursor()
        prepared_sql = _translate_query_to_postgres(sql)
        cur.execute(prepared_sql, params or ())
        return PGCursorWrapper(cur)

    def cursor(self):
        return PGCursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def _translate_query_to_postgres(sql: str) -> str:
    """Translates SQLite-style queries (e.g. '?' placeholders) to PostgreSQL ('%s')."""
    # Replace ? with %s when not part of text
    # Avoid replacing ? inside quotes by splitting or simple regex
    if "?" in sql:
        sql = re.sub(r'\?', '%s', sql)
    # Translate SQLite functions if present
    # e.g. substr(col, 12, 5) -> SUBSTR(col::text, 12, 5) if needed
    return sql


class InvestigationDatabase:
    """
    Enterprise-grade repository supporting PostgreSQL connection pooling
    and SQLite fallback for local test environments.
    """
    def __init__(self, db_path: Optional[str] = None, db_url: Optional[str] = None):
        self.is_postgres = False
        self._pool = None
        self._shared_conn = None
        self.db_path = str(db_path) if db_path is not None else None
        self.db_url = db_url or os.getenv("DATABASE_URL", DEFAULT_PG_URL)

        # Decide whether to use SQLite or PostgreSQL
        # If db_path is explicitly ':memory:' or ends with '.db' (and no explicit postgres URL), use SQLite
        if self.db_path == ":memory:" or (self.db_path and self.db_path.endswith(".db") and not db_url):
            self._init_sqlite(self.db_path)
        else:
            try:
                self._init_postgres(self.db_url)
            except Exception as e:
                logger.warning(
                    f"PostgreSQL connection to {self.db_url} failed ({e}). "
                    f"Falling back to local SQLite at {DEFAULT_DB_PATH}."
                )
                self._init_sqlite(str(DEFAULT_DB_PATH))

        self.init_db()

    def _init_postgres(self, url: str):
        """Initializes PostgreSQL threaded connection pool."""
        minconn = int(os.getenv("DB_MIN_CONNECTIONS", "2"))
        maxconn = int(os.getenv("DB_MAX_CONNECTIONS", "20"))
        self._pool = pool.ThreadedConnectionPool(minconn, maxconn, url)
        self.is_postgres = True
        logger.info(f"Connected to PostgreSQL ({url.split('@')[-1] if '@' in url else 'postgres'}). Pool active (min={minconn}, max={maxconn}).")

    def _init_sqlite(self, path: str):
        """Initializes SQLite connection."""
        self.db_path = path
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._shared_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._shared_conn.row_factory = sqlite3.Row
        self._shared_conn.execute("PRAGMA foreign_keys = ON")
        self.is_postgres = False
        logger.info(f"Connected to SQLite ({self.db_path}).")

    @contextmanager
    def _get_connection(self):
        """Yields a database connection with auto-commit / rollback."""
        if self.is_postgres:
            conn = self._pool.getconn()
            try:
                wrapper = PGConnectionWrapper(conn)
                yield wrapper
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self._pool.putconn(conn)
        else:
            if self._shared_conn is None:
                self._shared_conn = sqlite3.connect(self.db_path, check_same_thread=False)
                self._shared_conn.row_factory = sqlite3.Row
                self._shared_conn.execute("PRAGMA foreign_keys = ON")
            with self._shared_conn as conn:
                yield conn

    def close(self):
        """Closes active database connections and drains the pool."""
        if self.is_postgres and self._pool is not None:
            try:
                self._pool.closeall()
            except Exception:
                pass
            self._pool = None
        elif self._shared_conn is not None:
            try:
                self._shared_conn.close()
            except Exception:
                pass
            self._shared_conn = None

    def init_db(self):
        """Initializes relational tables and performance indices in PostgreSQL or SQLite."""
        if self.is_postgres:
            with self._get_connection() as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS investigations (
                        id VARCHAR(64) PRIMARY KEY,
                        case_id VARCHAR(128) NOT NULL,
                        status VARCHAR(64) NOT NULL,
                        started_at TIMESTAMPTZ,
                        completed_at TIMESTAMPTZ,
                        recommendation VARCHAR(64),
                        confidence VARCHAR(32),
                        requires_human_review BOOLEAN NOT NULL DEFAULT FALSE,
                        final_summary TEXT,
                        po_file VARCHAR(512),
                        invoice_file VARCHAR(512),
                        receipt_files JSONB,
                        source_files JSONB,
                        vendor_name VARCHAR(255),
                        po_number VARCHAR(128),
                        invoice_number VARCHAR(128),
                        receipt_numbers JSONB,
                        reconciliation_result JSONB,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS investigation_events (
                        id VARCHAR(64) PRIMARY KEY,
                        investigation_id VARCHAR(64) NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                        event_type VARCHAR(64),
                        tool_name VARCHAR(128),
                        arguments JSONB,
                        result JSONB,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS investigation_evidence (
                        id VARCHAR(128) PRIMARY KEY,
                        investigation_id VARCHAR(64) NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                        source_type VARCHAR(64) NOT NULL,
                        source_id VARCHAR(128) NOT NULL,
                        field VARCHAR(128),
                        value TEXT,
                        description TEXT,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS investigation_findings (
                        id VARCHAR(128) PRIMARY KEY,
                        investigation_id VARCHAR(64) NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
                        discrepancy_type VARCHAR(64) NOT NULL,
                        explanation TEXT NOT NULL,
                        confidence VARCHAR(32) NOT NULL,
                        created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE TABLE IF NOT EXISTS review_decisions (
                        case_id VARCHAR(128) PRIMARY KEY,
                        decision VARCHAR(64) NOT NULL,
                        status VARCHAR(64) NOT NULL,
                        reviewer_id VARCHAR(128) NOT NULL,
                        notes TEXT,
                        reviewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );

                    CREATE INDEX IF NOT EXISTS idx_inv_case_id ON investigations(case_id);
                    CREATE INDEX IF NOT EXISTS idx_inv_status ON investigations(status);
                    CREATE INDEX IF NOT EXISTS idx_inv_completed_at ON investigations(completed_at DESC);
                    CREATE INDEX IF NOT EXISTS idx_inv_requires_review ON investigations(requires_human_review);
                    CREATE INDEX IF NOT EXISTS idx_events_inv_id ON investigation_events(investigation_id);
                    CREATE INDEX IF NOT EXISTS idx_evid_inv_id ON investigation_evidence(investigation_id);
                    CREATE INDEX IF NOT EXISTS idx_find_inv_id ON investigation_findings(investigation_id);
                    CREATE INDEX IF NOT EXISTS idx_rev_case_id ON review_decisions(case_id);
                """)
        else:
            with self._get_connection() as conn:
                conn.executescript("""
                    CREATE TABLE IF NOT EXISTS investigations (
                        id TEXT PRIMARY KEY,
                        case_id TEXT NOT NULL,
                        status TEXT NOT NULL,
                        started_at TEXT,
                        completed_at TEXT,
                        recommendation TEXT,
                        confidence TEXT,
                        requires_human_review INTEGER NOT NULL DEFAULT 0,
                        final_summary TEXT
                    );

                    CREATE TABLE IF NOT EXISTS investigation_events (
                        id TEXT PRIMARY KEY,
                        investigation_id TEXT NOT NULL,
                        event_type TEXT,
                        tool_name TEXT,
                        arguments TEXT,
                        result TEXT,
                        created_at TEXT,
                        FOREIGN KEY (investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS investigation_evidence (
                        id TEXT PRIMARY KEY,
                        investigation_id TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        source_id TEXT NOT NULL,
                        field TEXT,
                        value TEXT,
                        description TEXT,
                        created_at TEXT,
                        FOREIGN KEY (investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS investigation_findings (
                        id TEXT PRIMARY KEY,
                        investigation_id TEXT NOT NULL,
                        discrepancy_type TEXT NOT NULL,
                        explanation TEXT NOT NULL,
                        confidence TEXT NOT NULL,
                        created_at TEXT,
                        FOREIGN KEY (investigation_id) REFERENCES investigations(id) ON DELETE CASCADE
                    );

                    CREATE TABLE IF NOT EXISTS review_decisions (
                        case_id TEXT PRIMARY KEY,
                        decision TEXT NOT NULL,
                        status TEXT NOT NULL,
                        reviewer_id TEXT NOT NULL,
                        notes TEXT,
                        reviewed_at TEXT NOT NULL
                    );

                    CREATE INDEX IF NOT EXISTS idx_inv_case_id ON investigations(case_id);
                    CREATE INDEX IF NOT EXISTS idx_events_inv_id ON investigation_events(investigation_id);
                    CREATE INDEX IF NOT EXISTS idx_evid_inv_id ON investigation_evidence(investigation_id);
                    CREATE INDEX IF NOT EXISTS idx_find_inv_id ON investigation_findings(investigation_id);
                    CREATE INDEX IF NOT EXISTS idx_rev_case_id ON review_decisions(case_id);
                """)

                extra_cols = [
                    ("po_file", "TEXT"),
                    ("invoice_file", "TEXT"),
                    ("receipt_files", "TEXT"),
                    ("source_files", "TEXT"),
                    ("vendor_name", "TEXT"),
                    ("po_number", "TEXT"),
                    ("invoice_number", "TEXT"),
                    ("receipt_numbers", "TEXT"),
                    ("reconciliation_result", "TEXT"),
                ]
                for col_name, col_type in extra_cols:
                    try:
                        conn.execute(f"ALTER TABLE investigations ADD COLUMN {col_name} {col_type}")
                    except Exception:
                        pass

    def save_investigation(
        self,
        state: Dict[str, Any],
        result: InvestigationResult,
        investigation_id: Optional[str] = None,
        po_file: Optional[str] = None,
        invoice_file: Optional[str] = None,
        receipt_files: Optional[Union[List[str], str]] = None,
        source_files: Optional[Union[List[str], str]] = None,
        vendor_name: Optional[str] = None,
        po_number: Optional[str] = None,
        invoice_number: Optional[str] = None,
        receipt_numbers: Optional[Union[List[str], str]] = None,
        reconciliation_result: Optional[Union[Dict[str, Any], str]] = None,
    ) -> str:
        """
        Persists a completed investigation along with all its tool events,
        evidence items, and synthesized findings within a single atomic transaction.
        """
        inv_id = investigation_id or f"INV-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now(timezone.utc).isoformat()
        started_at = state.get("started_at", now)
        completed_at = now

        resolved_po_file = po_file or state.get("po_file") or getattr(result, "po_file", None)
        resolved_inv_file = invoice_file or state.get("invoice_file") or getattr(result, "invoice_file", None)
        resolved_rcpt_files = receipt_files or state.get("receipt_files") or getattr(result, "receipt_files", None)
        resolved_src_files = source_files or state.get("source_files") or getattr(result, "source_files", None)
        resolved_vendor = vendor_name or state.get("vendor_name") or getattr(result, "vendor_name", None)
        resolved_po_num = po_number or state.get("po_number") or getattr(result, "po_number", None)
        resolved_inv_num = invoice_number or state.get("invoice_number") or getattr(result, "invoice_number", None)
        resolved_rcpt_nums = receipt_numbers or state.get("receipt_numbers") or getattr(result, "receipt_numbers", None)
        resolved_recon_res = reconciliation_result or state.get("reconciliation_result") or getattr(result, "reconciliation_result", None)

        def _json_val(v):
            if v is None:
                return None
            if self.is_postgres:
                if isinstance(v, (dict, list)):
                    return Json(v)
                if isinstance(v, str):
                    s = v.strip()
                    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                        try:
                            return Json(json.loads(s))
                        except Exception:
                            pass
                    return Json(s)
                return Json(v)
            else:
                if isinstance(v, (dict, list)):
                    return json.dumps(v, default=str)
                return v

        summary_text = getattr(result, "final_summary", None) or (
            result.to_executive_summary() if hasattr(result, "to_executive_summary") else ""
        )

        with self._get_connection() as conn:
            if self.is_postgres:
                conn.execute(
                    """
                    INSERT INTO investigations (
                        id, case_id, status, started_at, completed_at,
                        recommendation, confidence, requires_human_review, final_summary,
                        po_file, invoice_file, receipt_files, source_files,
                        vendor_name, po_number, invoice_number, receipt_numbers,
                        reconciliation_result
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        case_id = EXCLUDED.case_id,
                        status = EXCLUDED.status,
                        started_at = EXCLUDED.started_at,
                        completed_at = EXCLUDED.completed_at,
                        recommendation = EXCLUDED.recommendation,
                        confidence = EXCLUDED.confidence,
                        requires_human_review = EXCLUDED.requires_human_review,
                        final_summary = EXCLUDED.final_summary,
                        po_file = EXCLUDED.po_file,
                        invoice_file = EXCLUDED.invoice_file,
                        receipt_files = EXCLUDED.receipt_files,
                        source_files = EXCLUDED.source_files,
                        vendor_name = EXCLUDED.vendor_name,
                        po_number = EXCLUDED.po_number,
                        invoice_number = EXCLUDED.invoice_number,
                        receipt_numbers = EXCLUDED.receipt_numbers,
                        reconciliation_result = EXCLUDED.reconciliation_result
                    """,
                    (
                        inv_id,
                        result.case_id,
                        state.get("status", "COMPLETED"),
                        started_at,
                        completed_at,
                        result.recommendation,
                        result.confidence,
                        bool(result.requires_human_review),
                        summary_text,
                        resolved_po_file,
                        resolved_inv_file,
                        _json_val(resolved_rcpt_files),
                        _json_val(resolved_src_files),
                        resolved_vendor,
                        resolved_po_num,
                        resolved_inv_num,
                        _json_val(resolved_rcpt_nums),
                        _json_val(resolved_recon_res),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO investigations (
                        id, case_id, status, started_at, completed_at,
                        recommendation, confidence, requires_human_review, final_summary,
                        po_file, invoice_file, receipt_files, source_files,
                        vendor_name, po_number, invoice_number, receipt_numbers,
                        reconciliation_result
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        inv_id,
                        result.case_id,
                        state.get("status", "COMPLETED"),
                        started_at,
                        completed_at,
                        result.recommendation,
                        result.confidence,
                        1 if result.requires_human_review else 0,
                        summary_text,
                        resolved_po_file,
                        resolved_inv_file,
                        json.dumps(resolved_rcpt_files) if isinstance(resolved_rcpt_files, list) else resolved_rcpt_files,
                        json.dumps(resolved_src_files) if isinstance(resolved_src_files, list) else resolved_src_files,
                        resolved_vendor,
                        resolved_po_num,
                        resolved_inv_num,
                        json.dumps(resolved_rcpt_nums) if isinstance(resolved_rcpt_nums, list) else resolved_rcpt_nums,
                        json.dumps(resolved_recon_res, default=str) if resolved_recon_res else None,
                    ),
                )

            # 2. Insert Tool Events
            for tc in state.get("tool_calls", []):
                ev_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
                sql = (
                    "INSERT INTO investigation_events (id, investigation_id, event_type, tool_name, arguments, result, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING"
                    if self.is_postgres
                    else "INSERT INTO investigation_events (id, investigation_id, event_type, tool_name, arguments, result, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
                )
                conn.execute(
                    sql,
                    (
                        ev_id,
                        inv_id,
                        "TOOL_CALL",
                        tc.get("tool", ""),
                        _json_val(tc.get("arguments", {})),
                        _json_val(tc.get("result", {})),
                        tc.get("timestamp", now),
                    ),
                )

            # 3. Insert Evidence records
            for ev in result.evidence:
                ev_pk = f"{inv_id}_{ev.evidence_id}"
                sql = (
                    "INSERT INTO investigation_evidence (id, investigation_id, source_type, source_id, field, value, description, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING"
                    if self.is_postgres
                    else "INSERT INTO investigation_evidence (id, investigation_id, source_type, source_id, field, value, description, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                )
                conn.execute(
                    sql,
                    (
                        ev_pk,
                        inv_id,
                        ev.source_type,
                        ev.source_id,
                        ev.field or "",
                        ev.value or "",
                        ev.description,
                        now,
                    ),
                )

            # 4. Insert Findings
            for f in result.findings:
                finding_pk = f"{inv_id}_{f.finding_id}"
                sql = (
                    "INSERT INTO investigation_findings (id, investigation_id, discrepancy_type, explanation, confidence, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (id) DO NOTHING"
                    if self.is_postgres
                    else "INSERT INTO investigation_findings (id, investigation_id, discrepancy_type, explanation, confidence, created_at) VALUES (?, ?, ?, ?, ?, ?)"
                )
                conn.execute(
                    sql,
                    (
                        finding_pk,
                        inv_id,
                        f.discrepancy_type,
                        f.explanation,
                        f.confidence,
                        now,
                    ),
                )

        return inv_id

    def get_investigation(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an investigation record by case ID."""
        sql = "SELECT * FROM investigations WHERE case_id = %s ORDER BY completed_at DESC LIMIT 1" if self.is_postgres else "SELECT * FROM investigations WHERE case_id = ? ORDER BY completed_at DESC LIMIT 1"
        with self._get_connection() as conn:
            cur = conn.execute(sql, (case_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_investigations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists investigations with optional status filter."""
        with self._get_connection() as conn:
            if status:
                sql = "SELECT * FROM investigations WHERE status = %s ORDER BY completed_at DESC" if self.is_postgres else "SELECT * FROM investigations WHERE status = ? ORDER BY completed_at DESC"
                cur = conn.execute(sql, (status,))
            else:
                sql = "SELECT * FROM investigations ORDER BY completed_at DESC"
                cur = conn.execute(sql)
            return [dict(r) for r in cur.fetchall()]

    def get_investigation_events(self, investigation_id: str) -> List[Dict[str, Any]]:
        """Retrieves all tool execution events for an investigation."""
        sql = "SELECT * FROM investigation_events WHERE investigation_id = %s ORDER BY created_at ASC" if self.is_postgres else "SELECT * FROM investigation_events WHERE investigation_id = ? ORDER BY created_at ASC"
        with self._get_connection() as conn:
            cur = conn.execute(sql, (investigation_id,))
            return [dict(r) for r in cur.fetchall()]

    def get_investigation_evidence(self, investigation_id: str) -> List[Dict[str, Any]]:
        """Retrieves all evidence records stored for an investigation."""
        sql = "SELECT * FROM investigation_evidence WHERE investigation_id = %s ORDER BY id ASC" if self.is_postgres else "SELECT * FROM investigation_evidence WHERE investigation_id = ? ORDER BY id ASC"
        with self._get_connection() as conn:
            cur = conn.execute(sql, (investigation_id,))
            return [dict(r) for r in cur.fetchall()]

    def get_investigation_findings(self, investigation_id: str) -> List[Dict[str, Any]]:
        """Retrieves all findings stored for an investigation."""
        sql = "SELECT * FROM investigation_findings WHERE investigation_id = %s ORDER BY id ASC" if self.is_postgres else "SELECT * FROM investigation_findings WHERE investigation_id = ? ORDER BY id ASC"
        with self._get_connection() as conn:
            cur = conn.execute(sql, (investigation_id,))
            return [dict(r) for r in cur.fetchall()]

    def save_review_decision(
        self,
        case_id: str,
        decision: str,
        status: str,
        reviewer_id: str,
        notes: str,
        reviewed_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persists a human reviewer decision and audit trail to database."""
        ts = reviewed_at or datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            if self.is_postgres:
                conn.execute(
                    """
                    INSERT INTO review_decisions (
                        case_id, decision, status, reviewer_id, notes, reviewed_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (case_id) DO UPDATE SET
                        decision = EXCLUDED.decision,
                        status = EXCLUDED.status,
                        reviewer_id = EXCLUDED.reviewer_id,
                        notes = EXCLUDED.notes,
                        reviewed_at = EXCLUDED.reviewed_at
                    """,
                    (case_id, decision, status, reviewer_id, notes, ts),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO review_decisions (
                        case_id, decision, status, reviewer_id, notes, reviewed_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (case_id, decision, status, reviewer_id, notes, ts),
                )
        return {
            "case_id": case_id,
            "decision": decision,
            "status": status,
            "reviewer_id": reviewer_id,
            "notes": notes,
            "reviewed_at": ts,
        }

    def get_review_decision(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves durable review decision for a case if one exists."""
        sql = "SELECT * FROM review_decisions WHERE case_id = %s LIMIT 1" if self.is_postgres else "SELECT * FROM review_decisions WHERE case_id = ? LIMIT 1"
        with self._get_connection() as conn:
            cur = conn.execute(sql, (case_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    def list_review_decisions(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves recorded human review decisions, optionally filtered by status."""
        if status:
            sql = "SELECT * FROM review_decisions WHERE status = %s ORDER BY reviewed_at DESC" if self.is_postgres else "SELECT * FROM review_decisions WHERE status = ? ORDER BY reviewed_at DESC"
            params = (status,)
        else:
            sql = "SELECT * FROM review_decisions ORDER BY reviewed_at DESC"
            params = ()
        with self._get_connection() as conn:
            cur = conn.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

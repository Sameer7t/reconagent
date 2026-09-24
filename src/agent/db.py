"""
AI Investigation Agent Relational Persistence Layer (SQLite).

Step 30: Implements durable relational persistence across four tables:
1. investigations
2. investigation_events
3. investigation_evidence
4. investigation_findings

Transforms ephemeral agent runs into enterprise-grade audit records.
"""
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from agent.models import InvestigationResult


DEFAULT_DB_PATH = Path("data") / "investigations.db"


class InvestigationDatabase:
    """
    Production-grade SQLite repository backing durable agent investigation state.
    """
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = str(db_path) if db_path is not None else str(DEFAULT_DB_PATH)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._shared_conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._shared_conn.row_factory = sqlite3.Row
        self._shared_conn.execute("PRAGMA foreign_keys = ON")
        self.init_db()

    def _get_connection(self) -> sqlite3.Connection:
        if self._shared_conn is None:
            self._shared_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._shared_conn.row_factory = sqlite3.Row
            self._shared_conn.execute("PRAGMA foreign_keys = ON")
        return self._shared_conn

    def close(self):
        """Closes active database connection and releases file handles."""
        if self._shared_conn is not None:
            try:
                self._shared_conn.close()
            except Exception:
                pass
            self._shared_conn = None

    def init_db(self):
        """Initializes relational tables and performance indices."""
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

            # Non-destructive schema migration: Add file provenance & document metadata columns if missing
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

        with self._get_connection() as conn:
            # 1. Insert Investigation record
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
                    getattr(result, "final_summary", None) or result.to_executive_summary(),
                    resolved_po_file,
                    resolved_inv_file,
                    json.dumps(resolved_rcpt_files) if isinstance(resolved_rcpt_files, list) else resolved_rcpt_files,
                    json.dumps(resolved_src_files) if isinstance(resolved_src_files, list) else resolved_src_files,
                    resolved_vendor,
                    resolved_po_num,
                    resolved_inv_num,
                    json.dumps(resolved_rcpt_nums) if isinstance(resolved_rcpt_nums, list) else resolved_rcpt_nums,
                    json.dumps(resolved_recon_res, default=str) if resolved_recon_res else None,
                )
            )

            # 2. Insert Tool Events
            for tc in state.get("tool_calls", []):
                ev_id = f"EVT-{uuid.uuid4().hex[:8].upper()}"
                conn.execute(
                    """
                    INSERT INTO investigation_events (
                        id, investigation_id, event_type, tool_name, arguments, result, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_id,
                        inv_id,
                        "TOOL_CALL",
                        tc.get("tool", ""),
                        json.dumps(tc.get("arguments", {}), default=str),
                        json.dumps(tc.get("result", {}), default=str),
                        tc.get("timestamp", now),
                    )
                )

            # 3. Insert Evidence records
            for ev in result.evidence:
                ev_pk = f"{inv_id}_{ev.evidence_id}"
                conn.execute(
                    """
                    INSERT INTO investigation_evidence (
                        id, investigation_id, source_type, source_id, field, value, description, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_pk,
                        inv_id,
                        ev.source_type,
                        ev.source_id,
                        ev.field or "",
                        ev.value or "",
                        ev.description,
                        now,
                    )
                )

            # 4. Insert Findings
            for f in result.findings:
                finding_pk = f"{inv_id}_{f.finding_id}"
                conn.execute(
                    """
                    INSERT INTO investigation_findings (
                        id, investigation_id, discrepancy_type, explanation, confidence, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        finding_pk,
                        inv_id,
                        f.discrepancy_type,
                        f.explanation,
                        f.confidence,
                        now,
                    )
                )

        return inv_id

    def get_investigation(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves an investigation record by case ID."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM investigations WHERE case_id = ? ORDER BY completed_at DESC LIMIT 1",
                (case_id,)
            )
            row = cur.fetchone()
            if not row:
                return None
            return dict(row)

    def list_investigations(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists investigations with optional status filter."""
        with self._get_connection() as conn:
            if status:
                cur = conn.execute(
                    "SELECT * FROM investigations WHERE status = ? ORDER BY completed_at DESC",
                    (status,)
                )
            else:
                cur = conn.execute("SELECT * FROM investigations ORDER BY completed_at DESC")
            return [dict(r) for r in cur.fetchall()]

    def get_investigation_events(self, investigation_id: str) -> List[Dict[str, Any]]:
        """Retrieves all tool execution events for an investigation."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM investigation_events WHERE investigation_id = ? ORDER BY created_at ASC",
                (investigation_id,)
            )
            return [dict(r) for r in cur.fetchall()]

    def get_investigation_evidence(self, investigation_id: str) -> List[Dict[str, Any]]:
        """Retrieves all evidence records stored for an investigation."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM investigation_evidence WHERE investigation_id = ? ORDER BY id ASC",
                (investigation_id,)
            )
            return [dict(r) for r in cur.fetchall()]

    def get_investigation_findings(self, investigation_id: str) -> List[Dict[str, Any]]:
        """Retrieves all findings stored for an investigation."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM investigation_findings WHERE investigation_id = ? ORDER BY id ASC",
                (investigation_id,)
            )
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
        """Persists a human reviewer decision and audit trail to SQLite."""
        ts = reviewed_at or datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
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
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM review_decisions WHERE case_id = ? LIMIT 1",
                (case_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def list_review_decisions(self) -> List[Dict[str, Any]]:
        """Retrieves all recorded human review decisions."""
        with self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM review_decisions ORDER BY reviewed_at DESC"
            )
            return [dict(r) for r in cur.fetchall()]

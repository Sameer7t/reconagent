"""
One-Time Automated Migration Script: SQLite to Production PostgreSQL.

Migrates all case records, tool events, evidence, findings, and reviewer decisions
from data/investigations.db into PostgreSQL (reconagent).
"""
import os
import json
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from pathlib import Path

SQLITE_PATH = Path("data") / "investigations.db"
PG_URL = os.getenv("DATABASE_URL", "postgresql://postgres:root@localhost:5432/reconagent")

CREATE_PG_TABLES = """
-- 1. Investigations Table
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

-- 2. Investigation Events Table
CREATE TABLE IF NOT EXISTS investigation_events (
    id VARCHAR(64) PRIMARY KEY,
    investigation_id VARCHAR(64) NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    event_type VARCHAR(64),
    tool_name VARCHAR(128),
    arguments JSONB,
    result JSONB,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 3. Investigation Evidence Table
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

-- 4. Investigation Findings Table
CREATE TABLE IF NOT EXISTS investigation_findings (
    id VARCHAR(128) PRIMARY KEY,
    investigation_id VARCHAR(64) NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    discrepancy_type VARCHAR(64) NOT NULL,
    explanation TEXT NOT NULL,
    confidence VARCHAR(32) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

-- 5. Review Decisions Table (Specialist Governance)
CREATE TABLE IF NOT EXISTS review_decisions (
    case_id VARCHAR(128) PRIMARY KEY,
    decision VARCHAR(64) NOT NULL,
    status VARCHAR(64) NOT NULL,
    reviewer_id VARCHAR(128) NOT NULL,
    notes TEXT,
    reviewed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for Fast Case Queries & Pagination
CREATE INDEX IF NOT EXISTS idx_inv_case_id ON investigations(case_id);
CREATE INDEX IF NOT EXISTS idx_inv_status ON investigations(status);
CREATE INDEX IF NOT EXISTS idx_inv_completed_at ON investigations(completed_at DESC);
CREATE INDEX IF NOT EXISTS idx_inv_requires_review ON investigations(requires_human_review);
CREATE INDEX IF NOT EXISTS idx_events_inv_id ON investigation_events(investigation_id);
CREATE INDEX IF NOT EXISTS idx_evid_inv_id ON investigation_evidence(investigation_id);
CREATE INDEX IF NOT EXISTS idx_find_inv_id ON investigation_findings(investigation_id);
CREATE INDEX IF NOT EXISTS idx_rev_case_id ON review_decisions(case_id);
"""


def _to_jsonb(val):
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return Json(val)
    if isinstance(val, str):
        val_s = val.strip()
        if (val_s.startswith("{") and val_s.endswith("}")) or (val_s.startswith("[") and val_s.endswith("]")):
            try:
                parsed = json.loads(val_s)
                return Json(parsed)
            except Exception:
                pass
        return Json(val_s)
    return Json(val)


def migrate():
    print(f"Connecting to SQLite: {SQLITE_PATH}")
    if not SQLITE_PATH.is_file():
        print(f"SQLite database {SQLITE_PATH} not found. Nothing to migrate.")
        return

    s_conn = sqlite3.connect(SQLITE_PATH)
    s_conn.row_factory = sqlite3.Row

    print(f"Connecting to PostgreSQL: {PG_URL}")
    pg_conn = psycopg2.connect(PG_URL)

    with pg_conn.cursor() as cur:
        print("Creating PostgreSQL tables and indexes...")
        cur.execute(CREATE_PG_TABLES)
    pg_conn.commit()

    # 1. Migrate investigations
    s_cur = s_conn.cursor()
    s_cur.execute("SELECT * FROM investigations")
    inv_rows = s_cur.fetchall()
    print(f"Migrating {len(inv_rows)} rows from 'investigations'...")

    with pg_conn.cursor() as cur:
        for r in inv_rows:
            d = dict(r)
            cur.execute(
                """
                INSERT INTO investigations (
                    id, case_id, status, started_at, completed_at,
                    recommendation, confidence, requires_human_review, final_summary,
                    po_file, invoice_file, receipt_files, source_files,
                    vendor_name, po_number, invoice_number, receipt_numbers,
                    reconciliation_result
                ) VALUES (
                    %(id)s, %(case_id)s, %(status)s, %(started_at)s, %(completed_at)s,
                    %(recommendation)s, %(confidence)s, %(requires_human_review)s, %(final_summary)s,
                    %(po_file)s, %(invoice_file)s, %(receipt_files)s, %(source_files)s,
                    %(vendor_name)s, %(po_number)s, %(invoice_number)s, %(receipt_numbers)s,
                    %(reconciliation_result)s
                ) ON CONFLICT (id) DO UPDATE SET
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
                    reconciliation_result = EXCLUDED.reconciliation_result;
                """,
                {
                    "id": d["id"],
                    "case_id": d["case_id"],
                    "status": d["status"],
                    "started_at": d.get("started_at"),
                    "completed_at": d.get("completed_at"),
                    "recommendation": d.get("recommendation"),
                    "confidence": d.get("confidence"),
                    "requires_human_review": bool(d.get("requires_human_review")),
                    "final_summary": d.get("final_summary"),
                    "po_file": d.get("po_file"),
                    "invoice_file": d.get("invoice_file"),
                    "receipt_files": _to_jsonb(d.get("receipt_files")),
                    "source_files": _to_jsonb(d.get("source_files")),
                    "vendor_name": d.get("vendor_name"),
                    "po_number": d.get("po_number"),
                    "invoice_number": d.get("invoice_number"),
                    "receipt_numbers": _to_jsonb(d.get("receipt_numbers")),
                    "reconciliation_result": _to_jsonb(d.get("reconciliation_result")),
                },
            )
    pg_conn.commit()

    # 2. Migrate investigation_events
    s_cur.execute("SELECT * FROM investigation_events")
    event_rows = s_cur.fetchall()
    print(f"Migrating {len(event_rows)} rows from 'investigation_events'...")

    with pg_conn.cursor() as cur:
        for r in event_rows:
            d = dict(r)
            cur.execute(
                """
                INSERT INTO investigation_events (
                    id, investigation_id, event_type, tool_name, arguments, result, created_at
                ) VALUES (
                    %(id)s, %(investigation_id)s, %(event_type)s, %(tool_name)s,
                    %(arguments)s, %(result)s, %(created_at)s
                ) ON CONFLICT (id) DO UPDATE SET
                    investigation_id = EXCLUDED.investigation_id,
                    event_type = EXCLUDED.event_type,
                    tool_name = EXCLUDED.tool_name,
                    arguments = EXCLUDED.arguments,
                    result = EXCLUDED.result,
                    created_at = EXCLUDED.created_at;
                """,
                {
                    "id": d["id"],
                    "investigation_id": d["investigation_id"],
                    "event_type": d.get("event_type"),
                    "tool_name": d.get("tool_name"),
                    "arguments": _to_jsonb(d.get("arguments")),
                    "result": _to_jsonb(d.get("result")),
                    "created_at": d.get("created_at"),
                },
            )
    pg_conn.commit()

    # 3. Migrate investigation_evidence
    s_cur.execute("SELECT * FROM investigation_evidence")
    evid_rows = s_cur.fetchall()
    print(f"Migrating {len(evid_rows)} rows from 'investigation_evidence'...")

    with pg_conn.cursor() as cur:
        for r in evid_rows:
            d = dict(r)
            cur.execute(
                """
                INSERT INTO investigation_evidence (
                    id, investigation_id, source_type, source_id, field, value, description, created_at
                ) VALUES (
                    %(id)s, %(investigation_id)s, %(source_type)s, %(source_id)s,
                    %(field)s, %(value)s, %(description)s, %(created_at)s
                ) ON CONFLICT (id) DO UPDATE SET
                    investigation_id = EXCLUDED.investigation_id,
                    source_type = EXCLUDED.source_type,
                    source_id = EXCLUDED.source_id,
                    field = EXCLUDED.field,
                    value = EXCLUDED.value,
                    description = EXCLUDED.description,
                    created_at = EXCLUDED.created_at;
                """,
                {
                    "id": d["id"],
                    "investigation_id": d["investigation_id"],
                    "source_type": d["source_type"],
                    "source_id": d["source_id"],
                    "field": d.get("field"),
                    "value": d.get("value"),
                    "description": d.get("description"),
                    "created_at": d.get("created_at"),
                },
            )
    pg_conn.commit()

    # 4. Migrate investigation_findings
    s_cur.execute("SELECT * FROM investigation_findings")
    find_rows = s_cur.fetchall()
    print(f"Migrating {len(find_rows)} rows from 'investigation_findings'...")

    with pg_conn.cursor() as cur:
        for r in find_rows:
            d = dict(r)
            cur.execute(
                """
                INSERT INTO investigation_findings (
                    id, investigation_id, discrepancy_type, explanation, confidence, created_at
                ) VALUES (
                    %(id)s, %(investigation_id)s, %(discrepancy_type)s, %(explanation)s,
                    %(confidence)s, %(created_at)s
                ) ON CONFLICT (id) DO UPDATE SET
                    investigation_id = EXCLUDED.investigation_id,
                    discrepancy_type = EXCLUDED.discrepancy_type,
                    explanation = EXCLUDED.explanation,
                    confidence = EXCLUDED.confidence,
                    created_at = EXCLUDED.created_at;
                """,
                {
                    "id": d["id"],
                    "investigation_id": d["investigation_id"],
                    "discrepancy_type": d["discrepancy_type"],
                    "explanation": d["explanation"],
                    "confidence": d["confidence"],
                    "created_at": d.get("created_at"),
                },
            )
    pg_conn.commit()

    # 5. Migrate review_decisions
    s_cur.execute("SELECT * FROM review_decisions")
    rev_rows = s_cur.fetchall()
    print(f"Migrating {len(rev_rows)} rows from 'review_decisions'...")

    with pg_conn.cursor() as cur:
        for r in rev_rows:
            d = dict(r)
            cur.execute(
                """
                INSERT INTO review_decisions (
                    case_id, decision, status, reviewer_id, notes, reviewed_at
                ) VALUES (
                    %(case_id)s, %(decision)s, %(status)s, %(reviewer_id)s,
                    %(notes)s, %(reviewed_at)s
                ) ON CONFLICT (case_id) DO UPDATE SET
                    decision = EXCLUDED.decision,
                    status = EXCLUDED.status,
                    reviewer_id = EXCLUDED.reviewer_id,
                    notes = EXCLUDED.notes,
                    reviewed_at = EXCLUDED.reviewed_at;
                """,
                {
                    "case_id": d["case_id"],
                    "decision": d["decision"],
                    "status": d["status"],
                    "reviewer_id": d["reviewer_id"],
                    "notes": d.get("notes"),
                    "reviewed_at": d.get("reviewed_at"),
                },
            )
    pg_conn.commit()

    # Verification
    print("\n--- Verifying Row Counts in PostgreSQL ---")
    with pg_conn.cursor() as cur:
        for t in ["investigations", "investigation_events", "investigation_evidence", "investigation_findings", "review_decisions"]:
            cur.execute(f"SELECT COUNT(*) FROM {t}")
            count = cur.fetchone()[0]
            print(f"PostgreSQL table '{t}': {count} rows")

    s_conn.close()
    pg_conn.close()
    print("\nMigration completed successfully!")


if __name__ == "__main__":
    migrate()

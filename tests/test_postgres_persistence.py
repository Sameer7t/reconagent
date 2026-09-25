"""
Unit & Integration Tests for PostgreSQL Enterprise Persistence Layer in ReconAgent.

Verifies:
1. Dual-mode instantiation: PostgreSQL when connection URL provided, SQLite fallback for :memory:.
2. Threaded connection pool acquisition and release.
3. CRUD operations on investigations, events, evidence, findings, and review decisions.
4. DictRow behavior: supports both row['column'] and row[0] indexing.
5. Auto-normalization of TIMESTAMPTZ datetimes into ISO 8601 strings.
6. JSONB serialization and deserialization for native lists and dicts.
"""
import uuid
import pytest
from datetime import datetime, timezone

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent.db import InvestigationDatabase, DictRow, DEFAULT_PG_URL
from agent.models import (
    InvestigationResult,
    Finding,
    Evidence,
)


@pytest.fixture
def memory_db():
    """Provides an isolated in-memory SQLite database."""
    db = InvestigationDatabase(":memory:")
    yield db
    db.close()


@pytest.fixture
def pg_db():
    """Provides a PostgreSQL database connected to the test database."""
    db = InvestigationDatabase(db_url=DEFAULT_PG_URL)
    yield db
    db.close()


def test_dict_row_dual_access():
    """DictRow must allow both dict-like key access and tuple-like integer index access."""
    row = DictRow({"case_id": "CASE-123", "status": "COMPLETED"}, ("CASE-123", "COMPLETED"))
    assert row["case_id"] == "CASE-123"
    assert row["status"] == "COMPLETED"
    assert row[0] == "CASE-123"
    assert row[1] == "COMPLETED"
    assert dict(row) == {"case_id": "CASE-123", "status": "COMPLETED"}


def test_sqlite_memory_fallback(memory_db):
    """Verifies in-memory SQLite operation when :memory: is specified."""
    assert not memory_db.is_postgres
    test_case_id = f"CASE-SQLITE-{uuid.uuid4().hex[:6]}"

    result = InvestigationResult(
        case_id=test_case_id,
        status="COMPLETED",
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        findings=[
            Finding(
                finding_id="F1",
                discrepancy_type="PRICE_MISMATCH",
                explanation="Unit price discrepancy.",
                confidence="HIGH",
            )
        ],
        evidence=[
            Evidence(
                evidence_id="E1",
                source_type="invoice",
                source_id="INV-001",
                field="unit_price",
                value="100.00",
                description="Billed price",
            )
        ],
        recommendation="REQUEST_CREDIT_MEMO",
        confidence="HIGH",
        requires_human_review=True,
        final_summary="Investigated price mismatch.",
    )

    inv_id = memory_db.save_investigation(state={}, result=result)
    assert inv_id is not None

    inv = memory_db.get_investigation(test_case_id)
    assert inv is not None
    assert inv["case_id"] == test_case_id
    assert inv["recommendation"] == "REQUEST_CREDIT_MEMO"

    findings = memory_db.get_investigation_findings(inv_id)
    assert len(findings) == 1
    assert findings[0]["discrepancy_type"] == "PRICE_MISMATCH"

    evidence = memory_db.get_investigation_evidence(inv_id)
    assert len(evidence) == 1
    assert evidence[0]["source_id"] == "INV-001"


def test_postgres_connection_and_pool(pg_db):
    """Verifies PostgreSQL connection pooling and CRUD operations."""
    assert pg_db.is_postgres
    assert pg_db._pool is not None

    test_case_id = f"CASE-PG-TEST-{uuid.uuid4().hex[:6]}"

    result = InvestigationResult(
        case_id=test_case_id,
        status="COMPLETED",
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
        findings=[
            Finding(
                finding_id="FIND-999",
                discrepancy_type="QUANTITY_SHORTAGE",
                explanation="Physical delivery shortage confirmed by receiving records.",
                confidence="HIGH",
            )
        ],
        evidence=[
            Evidence(
                evidence_id="EVID-999",
                source_type="receipt",
                source_id="DR-999",
                field="quantity_delivered",
                value="8",
                description="Dock verified delivery quantity.",
            )
        ],
        recommendation="REQUEST_CREDIT_MEMO",
        confidence="HIGH",
        requires_human_review=True,
        final_summary="Shortage confirmed by receiving logs.",
    )

    metadata = {
        "po_file": "PO-TEST.txt",
        "invoice_file": "INV-TEST.txt",
        "receipt_files": ["DR-TEST.txt"],
        "source_files": ["PO-TEST.txt", "INV-TEST.txt", "DR-TEST.txt"],
        "vendor_name": "Test Global Logistics",
        "po_number": "PO-999",
        "invoice_number": "INV-999",
        "receipt_numbers": ["DR-999"],
        "reconciliation_result": {
            "status": "DISCREPANCY_FOUND",
            "discrepancies": [{"type": "QUANTITY_SHORTAGE", "expected": 10, "actual": 8}],
        },
    }

    try:
        inv_id = pg_db.save_investigation(state={}, result=result, **metadata)
        assert inv_id is not None

        # Fetch investigation
        inv = pg_db.get_investigation(test_case_id)
        assert inv is not None
        assert inv["case_id"] == test_case_id
        assert inv["status"] == "COMPLETED"
        assert inv["vendor_name"] == "Test Global Logistics"
        assert isinstance(inv["completed_at"], str)  # Auto-normalized to ISO string
        assert isinstance(inv["receipt_files"], list)  # Native JSONB list

        # Findings & Evidence
        findings = pg_db.get_investigation_findings(inv_id)
        assert len(findings) == 1
        assert findings[0]["discrepancy_type"] == "QUANTITY_SHORTAGE"

        evidence = pg_db.get_investigation_evidence(inv_id)
        assert len(evidence) == 1
        assert evidence[0]["source_id"] == "DR-999"

        # Review Decisions
        pg_db.save_review_decision(
            case_id=test_case_id,
            decision="APPROVE_PAYMENT",
            reviewer_id="reviewer_alex",
            notes="Variance approved by management.",
            status="APPROVED",
        )
        dec = pg_db.get_review_decision(test_case_id)
        assert dec is not None
        assert dec["decision"] == "APPROVE_PAYMENT"
        assert dec["reviewer_id"] == "reviewer_alex"
        assert dec["status"] == "APPROVED"
        assert isinstance(dec["reviewed_at"], str)

        # List review decisions
        decisions = pg_db.list_review_decisions(status="APPROVED")
        assert any(d["case_id"] == test_case_id for d in decisions)

    finally:
        # Clean up test row
        with pg_db._get_connection() as conn:
            conn.execute("DELETE FROM review_decisions WHERE case_id = %s", (test_case_id,))
            conn.execute("DELETE FROM investigations WHERE case_id = %s", (test_case_id,))

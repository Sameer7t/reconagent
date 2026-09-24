"""
Unit and Integration Tests for ReconAgent FastAPI Backend (Phase 7.1).

Tests all endpoints:
- System health and info (/api/health, /api/info)
- Document upload and ingestion (/api/documents/upload, /api/documents/supported-types)
  - Mixed upload mode
  - Individual upload mode with type override
- Cases & Reconciliation (/api/cases, /api/cases/{case_id}, /api/cases/reconcile)
  - Reconcile clean match (auto-approve)
  - Reconcile discrepancy (agent investigation)
  - Individual triplet upload mode (/api/cases/reconcile-triplet)
  - Mixed batch upload mode (/api/cases/reconcile-mixed)
- Investigations (/api/investigations, /api/investigations/{case_id})
- Review Queue & Human Governance (/api/review/metrics, /api/review/queue, /api/review/{case_id}/decision)
"""
import io
import sys
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Ensure src/ and project root are in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from api.main import app
from agent.db import InvestigationDatabase
from agent.review_queue import get_review_queue
from api.dependencies import get_db, get_review_queue_dep


@pytest.fixture(scope="module")
def client():
    """Provides FastAPI TestClient and cleans up test records on completion."""
    with TestClient(app) as c:
        yield c

    # Cleanup test cases from DB so they never leak into the application
    db = get_db()
    test_cases = ["CASE-TEST-CLEAN-01", "CASE-TEST-DISC-01", "CASE-TRIPLET-TEST", "CASE-USER-SPEC-01"]
    with db._get_connection() as conn:
        for cid in test_cases:
            inv_rows = conn.execute("SELECT id FROM investigations WHERE case_id = ?", (cid,)).fetchall()
            for inv_row in inv_rows:
                inv_id = inv_row[0]
                conn.execute("DELETE FROM investigation_events WHERE investigation_id = ?", (inv_id,))
                conn.execute("DELETE FROM investigation_evidence WHERE investigation_id = ?", (inv_id,))
                conn.execute("DELETE FROM investigation_findings WHERE investigation_id = ?", (inv_id,))
            conn.execute("DELETE FROM review_decisions WHERE case_id = ?", (cid,))
            conn.execute("DELETE FROM investigations WHERE case_id = ?", (cid,))




# =============================================================================
# 1. SYSTEM & HEALTH ENDPOINTS
# =============================================================================
def test_root_endpoint(client):
    res = client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["service"] == "ReconAgent API"
    assert data["status"] == "OPERATIONAL"


def test_health_check(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["database_connected"] is True
    assert "version" in data


def test_system_info(client):
    res = client.get("/api/info")
    assert res.status_code == 200
    data = res.json()
    assert "INVOICE" in data["supported_document_types"]
    assert "PURCHASE_ORDER" in data["supported_document_types"]
    assert "RECEIPT" in data["supported_document_types"]
    assert ".pdf" in data["supported_file_extensions"]


# =============================================================================
# 2. DOCUMENT INGESTION & EXTRACTION ENDPOINTS
# =============================================================================
def test_supported_types_endpoint(client):
    res = client.get("/api/documents/supported-types")
    assert res.status_code == 200
    data = res.json()
    assert "INVOICE" in data["supported_types"]


def test_upload_mixed_documents(client):
    """Verifies uploading arbitrary mixed documents with auto-classification."""
    invoice_content = (
        "INVOICE\n"
        "Invoice Number: INV-9901\n"
        "Date: 2026-03-01\n"
        "Vendor: Apex Supplies\n"
        "PO Reference: PO-8801\n"
        "Items:\n"
        "- Widget A: 10 @ $50.00 = $500.00\n"
        "Total: $500.00\n"
    )
    po_content = (
        "PURCHASE ORDER\n"
        "PO Number: PO-8801\n"
        "Date: 2026-02-28\n"
        "Vendor: Apex Supplies\n"
        "Items:\n"
        "- Widget A: 10 @ $50.00 = $500.00\n"
        "Total: $500.00\n"
    )

    files = [
        ("files", ("test_inv.txt", io.BytesIO(invoice_content.encode("utf-8")), "text/plain")),
        ("files", ("test_po.txt", io.BytesIO(po_content.encode("utf-8")), "text/plain")),
    ]

    res = client.post("/api/documents/upload", files=files)
    assert res.status_code == 200
    data = res.json()
    assert data["total_uploaded"] == 2
    doc_types = [doc["document_type"] for doc in data["documents"]]
    assert "INVOICE" in doc_types
    assert "PURCHASE_ORDER" in doc_types


def test_upload_individual_document_with_override(client):
    """Verifies individual document upload with explicit document_type override."""
    doc_content = "Raw text content for an invoice"
    files = [
        ("files", ("invoice_manual.txt", io.BytesIO(doc_content.encode("utf-8")), "text/plain")),
    ]
    data = {"document_type": "INVOICE"}

    res = client.post("/api/documents/upload", files=files, data=data)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["total_uploaded"] == 1
    assert res_data["documents"][0]["document_type"] == "INVOICE"


# =============================================================================
# 3. CASES & RECONCILIATION ENDPOINTS
# =============================================================================
def test_list_cases(client):
    res = client.get("/api/cases?limit=5")
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "cases" in data
    assert isinstance(data["cases"], list)


def test_reconcile_clean_match(client):
    """Reconciles matching PO, Invoice, and Receipt returning AUTO_APPROVE."""
    po = {
        "purchase_order_number": "PO-CLEAN-01",
        "vendor_name": "Acme Industrial",
        "currency": "USD",
        "total": 1000.0,
        "items": [{"description": "Turbine Blade", "product_code": "TB-1", "quantity": 10, "unit_price": 100.0, "line_total": 1000.0}],
    }
    inv = {
        "invoice_number": "INV-CLEAN-01",
        "purchase_order_number": "PO-CLEAN-01",
        "vendor_name": "Acme Industrial",
        "currency": "USD",
        "total": 1000.0,
        "items": [{"description": "Turbine Blade", "product_code": "TB-1", "quantity": 10, "unit_price": 100.0, "line_total": 1000.0}],
    }
    receipt = {
        "receipt_number": "REC-CLEAN-01",
        "purchase_order_number": "PO-CLEAN-01",
        "vendor_name": "Acme Industrial",
        "items": [{"description": "Turbine Blade", "item_code": "TB-1", "quantity": 10, "unit_price": 100.0, "total": 1000.0}],
    }

    payload = {
        "case_id": "CASE-TEST-CLEAN-01",
        "po_data": po,
        "invoice_data": inv,
        "receipt_data_list": [receipt],
    }

    res = client.post("/api/cases/reconcile", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["case_id"] == "CASE-TEST-CLEAN-01"
    assert data["status"] in ("MATCHED", "MATCHED_WITH_TOLERANCE")
    assert data["recommendation"] == "APPROVE_PAYMENT"
    assert data["discrepancy_count"] == 0
    assert data["requires_human_review"] is False


def test_reconcile_with_discrepancy_dispatches_agent(client):
    """Reconciles with price mismatch triggering AI investigation and review gate."""
    po = {
        "purchase_order_number": "PO-DISC-01",
        "vendor_name": "Apex Supplies",
        "currency": "USD",
        "total": 500.0,
        "items": [{"description": "Hydraulic Pump", "product_code": "HP-1", "quantity": 5, "unit_price": 100.0, "line_total": 500.0}],
    }
    inv = {
        "invoice_number": "INV-DISC-01",
        "purchase_order_number": "PO-DISC-01",
        "vendor_name": "Apex Supplies",
        "currency": "USD",
        "total": 750.0,  # Overbilled!
        "items": [{"description": "Hydraulic Pump", "product_code": "HP-1", "quantity": 5, "unit_price": 150.0, "line_total": 750.0}],
    }
    receipt = {
        "receipt_number": "REC-DISC-01",
        "purchase_order_number": "PO-DISC-01",
        "vendor_name": "Apex Supplies",
        "items": [{"description": "Hydraulic Pump", "quantity_received": 5}],
    }

    payload = {
        "case_id": "CASE-TEST-DISC-01",
        "po_data": po,
        "invoice_data": inv,
        "receipt_data_list": [receipt],
    }

    res = client.post("/api/cases/reconcile", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["case_id"] == "CASE-TEST-DISC-01"
    assert data["discrepancy_count"] > 0
    assert data["requires_human_review"] is True
    assert data["investigation_result"] is not None


def test_reconcile_individual_triplet_upload(client):
    """Tests the explicit Individual Triplet Upload mode with dedicated file slots."""
    po_text = "PURCHASE ORDER\nPO Number: PO-TRIPLET-01\nVendor: SupplyCo\nTotal: $300.00\nItems:\n- Bolt: 30 @ $10.00 = $300.00"
    inv_text = "INVOICE\nInvoice Number: INV-TRIPLET-01\nPO: PO-TRIPLET-01\nVendor: SupplyCo\nTotal: $300.00\nItems:\n- Bolt: 30 @ $10.00 = $300.00"
    rcpt_text = "DELIVERY RECEIPT\nReceipt Number: REC-TRIPLET-01\nPO: PO-TRIPLET-01\nVendor: SupplyCo\nItems:\n- Bolt: 30"

    files = [
        ("purchase_order_file", ("po.txt", io.BytesIO(po_text.encode("utf-8")), "text/plain")),
        ("invoice_file", ("inv.txt", io.BytesIO(inv_text.encode("utf-8")), "text/plain")),
        ("receipt_files", ("rcpt.txt", io.BytesIO(rcpt_text.encode("utf-8")), "text/plain")),
    ]
    data = {"case_id": "CASE-TRIPLET-TEST"}

    res = client.post("/api/cases/reconcile-triplet", files=files, data=data)
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["case_id"] == "CASE-TRIPLET-TEST"
    assert "status" in res_data
    assert res_data["status"] in ("MATCHED", "MATCHED_WITH_TOLERANCE", "DISCREPANCY_DETECTED", "FLAGGED", "REVIEW_REQUIRED", "UNMATCHED")


def test_reconcile_triplet_unrelated_file_rejected(client):
    """Verifies that uploading an unrelated document in triplet mode is rejected with HTTP 400 'Invalid file'."""
    unrelated_text = "Grandma's Chocolate Chip Cookies: 2 cups flour, 1 cup butter, bake at 350F for 10 minutes."
    inv_text = "INVOICE\nInvoice Number: INV-TRIPLET-02\nPO: PO-TRIPLET-02\nVendor: SupplyCo\nTotal: $100.00\nItems:\n- Bolt: 10 @ $10.00 = $100.00"

    files = [
        ("purchase_order_file", ("cookie_recipe.txt", io.BytesIO(unrelated_text.encode("utf-8")), "text/plain")),
        ("invoice_file", ("inv.txt", io.BytesIO(inv_text.encode("utf-8")), "text/plain")),
    ]
    res = client.post("/api/cases/reconcile-triplet", files=files)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "Invalid file" in detail
    assert "cookie_recipe.txt" in detail


def test_reconcile_triplet_mismatched_file_rejected(client):
    """Verifies that uploading an invoice into the Purchase Order slot is rejected with HTTP 400."""
    inv_text = "INVOICE\nInvoice Number: INV-MISMATCH-01\nVendor: SupplyCo\nTotal: $100.00\nItems:\n- Bolt: 10 @ $10.00 = $100.00"

    files = [
        ("purchase_order_file", ("actual_invoice.txt", io.BytesIO(inv_text.encode("utf-8")), "text/plain")),
        ("invoice_file", ("inv.txt", io.BytesIO(inv_text.encode("utf-8")), "text/plain")),
    ]
    res = client.post("/api/cases/reconcile-triplet", files=files)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "Invalid file" in detail
    assert "actual_invoice.txt" in detail
    assert "not a Purchase Order" in detail


def test_reconcile_mixed_unrelated_file_rejected(client):
    """Verifies that uploading unrelated documents in mixed batch mode is rejected with HTTP 400 'Invalid file'."""
    unrelated_text = "Random essay about space travel and astronomy. Mars has two moons: Phobos and Deimos."
    files = [
        ("files", ("space_essay.txt", io.BytesIO(unrelated_text.encode("utf-8")), "text/plain")),
    ]
    res = client.post("/api/cases/reconcile-mixed", files=files)
    assert res.status_code == 400
    detail = res.json()["detail"]
    assert "Invalid file" in detail
    assert "space_essay.txt" in detail


# =============================================================================
# 4. INVESTIGATIONS ENDPOINTS
# =============================================================================
def test_list_investigations(client):
    res = client.get("/api/investigations?limit=5")
    assert res.status_code == 200
    data = res.json()
    assert "total" in data
    assert "investigations" in data
    assert isinstance(data["investigations"], list)


def test_get_investigation_detail(client):
    # First get any existing case from list
    list_res = client.get("/api/investigations?limit=1")
    assert list_res.status_code == 200
    invs = list_res.json()["investigations"]
    if invs:
        target_case_id = invs[0]["case_id"]
        detail_res = client.get(f"/api/investigations/{target_case_id}")
        assert detail_res.status_code == 200
        detail_data = detail_res.json()
        assert detail_data["case_id"] == target_case_id
        assert "findings" in detail_data
        assert "evidence" in detail_data
        assert "events" in detail_data


# =============================================================================
# 5. REVIEW QUEUE & HUMAN GOVERNANCE ENDPOINTS
# =============================================================================
def test_review_queue_metrics(client):
    res = client.get("/api/review/metrics")
    assert res.status_code == 200
    data = res.json()
    assert "total_count" in data
    assert "pending_count" in data
    assert "approved_count" in data
    assert "overridden_count" in data


def test_review_queue_list_and_briefing(client):
    res = client.get("/api/review/queue?status=ALL")
    assert res.status_code == 200
    data = res.json()
    assert "metrics" in data
    assert "items" in data
    if data["items"]:
        first_item = data["items"][0]
        assert "case_id" in first_item
        assert "rendered_briefing" in first_item
        assert "agent_recommendation" in first_item


def test_submit_specialist_decision(client):
    # Ensure a case is in the queue
    case_id = "CASE-TEST-DISC-01"
    queue = get_review_queue_dep()
    queue.enqueue(
        case_id=case_id,
        discrepancy_count=1,
        recommendation="REQUEST_CREDIT_MEMO",
        confidence="HIGH",
        requires_human_review=True,
    )

    decision_payload = {
        "decision": "APPROVE_PAYMENT",
        "reviewer_id": "specialist_sarah",
        "notes": "Vendor negotiated bulk discount applied on next cycle. Exception authorized by procurement director.",
    }

    res = client.post(f"/api/review/{case_id}/decision", json=decision_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["item"]["human_decision"] == "APPROVE_PAYMENT"
    assert data["item"]["reviewed_by"] == "specialist_sarah"
    assert data["item"]["human_status"] == "OVERRIDDEN"

    # Verify durable persistence in SQLite
    db = get_db()
    saved_dec = db.get_review_decision(case_id)
    assert saved_dec is not None
    assert saved_dec["decision"] == "APPROVE_PAYMENT"
    assert saved_dec["reviewer_id"] == "specialist_sarah"


# =============================================================================
# 6. EXACT USER-SPECIFIED ENDPOINT PATHS
# =============================================================================
def test_user_specified_exact_endpoints(client):
    """
    Explicitly tests all 8 endpoints requested by the user:
    1. POST /documents/upload
    2. POST /transactions/process
    3. GET /cases
    4. GET /cases/{case_id}
    5. GET /cases/{case_id}/investigation
    6. GET /review-queue
    7. POST /review-queue/{case_id}/approve
    8. POST /review-queue/{case_id}/reject
    """
    # 1. POST /documents/upload
    doc_content = "INVOICE\nInvoice: INV-USER-01\nVendor: Acme\nTotal: $100.00"
    files = [("files", ("inv_user.txt", io.BytesIO(doc_content.encode("utf-8")), "text/plain"))]
    res1 = client.post("/documents/upload", files=files)
    assert res1.status_code == 200
    assert res1.json()["total_uploaded"] == 1

    # 2. POST /transactions/process
    tx_payload = {
        "case_id": "CASE-USER-SPEC-01",
        "po_data": {
            "purchase_order_number": "PO-USER-01",
            "vendor_name": "Acme",
            "currency": "USD",
            "total": 100.0,
            "items": [{"description": "Filter", "product_code": "F-1", "quantity": 1, "unit_price": 100.0, "line_total": 100.0}],
        },
        "invoice_data": {
            "invoice_number": "INV-USER-01",
            "purchase_order_number": "PO-USER-01",
            "vendor_name": "Acme",
            "currency": "USD",
            "total": 100.0,
            "items": [{"description": "Filter", "product_code": "F-1", "quantity": 1, "unit_price": 100.0, "line_total": 100.0}],
        },
        "receipt_data_list": [
            {
                "receipt_number": "REC-USER-01",
                "purchase_order_number": "PO-USER-01",
                "vendor_name": "Acme",
                "items": [{"description": "Filter", "item_code": "F-1", "quantity": 1, "unit_price": 100.0, "total": 100.0}],
            }
        ],
    }
    res2 = client.post("/transactions/process", json=tx_payload)
    assert res2.status_code == 200
    assert res2.json()["case_id"] == "CASE-USER-SPEC-01"

    # 3. GET /cases
    res3 = client.get("/cases?limit=5")
    assert res3.status_code == 200
    cases_list = res3.json()["cases"]
    assert len(cases_list) > 0

    target_case_id = cases_list[0]["case_id"]

    # 4. GET /cases/{case_id}
    res4 = client.get(f"/cases/{target_case_id}")
    assert res4.status_code == 200
    assert res4.json()["case_id"] == target_case_id

    # 5. GET /cases/{case_id}/investigation
    res5 = client.get(f"/cases/{target_case_id}/investigation")
    assert res5.status_code == 200
    assert res5.json()["case_id"] == target_case_id

    # 6. GET /review-queue
    res6 = client.get("/review-queue")
    assert res6.status_code == 200
    assert "items" in res6.json()

    # Setup review item for approval/rejection tests
    test_case_id = "CASE-ACTION-TEST-01"
    queue = get_review_queue_dep()
    queue.enqueue(
        case_id=test_case_id,
        discrepancy_count=1,
        recommendation="REQUEST_CREDIT_MEMO",
        confidence="HIGH",
        requires_human_review=True,
    )

    # 7. POST /review-queue/{case_id}/approve
    res7 = client.post(f"/review-queue/{test_case_id}/approve", json={"reviewer_id": "auditor_bob", "notes": "Approved variance"})
    assert res7.status_code == 200
    assert res7.json()["success"] is True
    assert res7.json()["item"]["human_decision"] == "APPROVE"

    # 8. POST /review-queue/{case_id}/reject
    test_case_id_2 = "CASE-ACTION-TEST-02"
    queue.enqueue(
        case_id=test_case_id_2,
        discrepancy_count=1,
        recommendation="REQUEST_CREDIT_MEMO",
        confidence="HIGH",
        requires_human_review=True,
    )
    res8 = client.post(f"/review-queue/{test_case_id_2}/reject", json={"reviewer_id": "auditor_alice", "notes": "Fraud suspected"})
    assert res8.status_code == 200
    assert res8.json()["success"] is True
    assert res8.json()["item"]["human_decision"] == "REJECT_INVOICE"


def test_get_document_raw_pdf_and_text(client):
    """Verifies that GET /api/documents/raw streams binary PDFs and text files inline for in-browser inspection."""
    # Test streaming an existing uploaded PDF
    res = client.get("/api/documents/raw?file_name=purchase_orders_10251.pdf")
    if res.status_code == 200:
        assert "application/pdf" in res.headers.get("content-type", "")
        assert len(res.content) > 0
        assert "inline" in res.headers.get("content-disposition", "")

    # Test streaming a text file
    res_txt = client.get("/api/documents/raw?file_name=po.txt")
    if res_txt.status_code == 200:
        assert "text/plain" in res_txt.headers.get("content-type", "")

    # Test non-existent file returns 404
    res_404 = client.get("/api/documents/raw?file_name=non_existent_file_99999.pdf")
    assert res_404.status_code == 404



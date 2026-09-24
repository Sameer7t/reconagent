import sys
from pathlib import Path
SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import pytest
from decimal import Decimal
from schemas.reconciliation import DiscrepancyType, Severity
from reconciliation.pipeline import reconcile_transaction


def test_clean_documents_pass_stage_0():
    po = {
        "purchase_order_number": "PO-100",
        "vendor_name": "Acme Corp",
        "subtotal": "500.00",
        "total": "500.00",
        "items": [
            {"item_code": "ITEM-1", "quantity": "5", "unit_price": "100.00", "line_total": "500.00"}
        ],
    }
    inv = {
        "invoice_number": "INV-100",
        "purchase_order_number": "PO-100",
        "vendor_name": "Acme Corp",
        "subtotal": "500.00",
        "total": "500.00",
        "items": [
            {"item_code": "ITEM-1", "quantity": "5", "unit_price": "100.00", "line_total": "500.00"}
        ],
    }
    rcpt = {
        "receipt_number": "REC-100",
        "purchase_order_number": "PO-100",
        "items": [
            {"item_code": "ITEM-1", "quantity": "5", "unit_price": "100.00", "total": "500.00"}
        ],
        "total": "500.00",
    }

    res = reconcile_transaction(po_data=po, invoice_data=inv, receipt_data_list=[rcpt], check_duplicates=False)
    assert len(res.document_validation_checks) == 3
    assert all(c.passed for c in res.document_validation_checks)
    calc_errors = [d for d in res.discrepancies if d.type == DiscrepancyType.CALCULATION_ERROR]
    assert len(calc_errors) == 0


def test_invoice_math_error_caught_in_stage_0():
    bad_inv = {
        "invoice_number": "INV-ERR-01",
        "purchase_order_number": "PO-100",
        "vendor_name": "Acme Corp",
        "subtotal": "300.00",
        "total": "300.00",
        "items": [
            # 2 * 100 is 200, reported 300 -> calculation error
            {"item_code": "ITEM-1", "quantity": "2", "unit_price": "100.00", "line_total": "300.00"}
        ],
    }

    res = reconcile_transaction(invoice_data=bad_inv, check_duplicates=False)
    calc_errors = [d for d in res.discrepancies if d.type == DiscrepancyType.CALCULATION_ERROR]
    assert len(calc_errors) > 0
    assert any(d.severity == Severity.HIGH for d in calc_errors)
    inv_check = next(c for c in res.document_validation_checks if c.check_name == "invoice_internal_validation")
    assert inv_check.passed is False


def test_po_math_error_caught_in_stage_0():
    bad_po = {
        "purchase_order_number": "PO-ERR-01",
        "vendor_name": "Acme Corp",
        "subtotal": "500.00",
        "total": "1000.00",  # Reported total 1000 vs subtotal 500
        "items": [
            {"item_code": "ITEM-1", "quantity": "5", "unit_price": "100.00", "line_total": "500.00"}
        ],
    }

    res = reconcile_transaction(po_data=bad_po, check_duplicates=False)
    calc_errors = [d for d in res.discrepancies if d.type == DiscrepancyType.CALCULATION_ERROR]
    assert len(calc_errors) > 0
    po_check = next(c for c in res.document_validation_checks if c.check_name == "po_internal_validation")
    assert po_check.passed is False


def test_orchestrator_bypasses_agent_investigation_on_math_error(monkeypatch):
    from pipeline.orchestrator import MasterOrchestrator
    import pipeline.orchestrator as orch_module

    agent_called = False

    def fake_run_investigation(*args, **kwargs):
        nonlocal agent_called
        agent_called = True
        raise RuntimeError("Agent should not have been called!")

    monkeypatch.setattr(orch_module, "run_investigation", fake_run_investigation)

    orchestrator = MasterOrchestrator(db_path=False)

    bad_inv = {
        "invoice_number": "INV-ERR-99",
        "purchase_order_number": "PO-100",
        "vendor_name": "Acme Corp",
        "subtotal": "300.00",
        "total": "300.00",
        "items": [
            {"item_code": "ITEM-1", "quantity": "2", "unit_price": "100.00", "line_total": "300.00"}
        ],
    }

    res = orchestrator.process_transaction(invoice_data=bad_inv)

    assert agent_called is False, "Investigation agent should be bypassed when document has internal math errors"
    assert res.recommendation == "REJECT_INVOICE"
    assert res.confidence == "HIGH"
    assert res.requires_human_review is True
    assert res.investigation_result is not None
    assert res.investigation_result["recommendation"] == "REJECT_INVOICE"
    assert "internal arithmetic validation" in res.investigation_result["final_summary"].lower()
    assert any(f["discrepancy_type"] == "CALCULATION_ERROR" for f in res.investigation_result["findings"])


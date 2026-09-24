import sys
from decimal import Decimal
from pathlib import Path
import pytest

SRC_ROOT = Path(__file__).resolve().parent.parent / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    DiscrepancyType,
    LineItemMatch,
    MatchMethod,
    ReconciliationPolicy,
    ReconciliationStatus,
)
from reconciliation.line_item_matcher import match_line_items, match_receipt_items_to_matches
from reconciliation.receipt_reconciler import build_receipt_comparison_table, reconcile_receipts
from reconciliation.financial_reconciler import reconcile_financials
from reconciliation.pipeline import reconcile_transaction


def test_flexible_receipt_no_amounts():
    """Delivery receipts without monetary amounts should remain valid and not trigger price errors."""
    po_items = [{"description": "Medical Glove", "product_code": "GLV-01", "quantity": Decimal("10"), "unit_price": Decimal("15.00"), "line_total": Decimal("150.00")}]
    inv_items = [{"description": "Medical Glove", "product_code": "GLV-01", "quantity": Decimal("10"), "unit_price": Decimal("15.00"), "line_total": Decimal("150.00")}]
    matches, _ = match_line_items(po_items, inv_items, "PO-01", "INV-01")

    # Receipt without unit_price or total
    receipt_items = [{"description": "Medical Glove", "item_code": "GLV-01", "quantity": Decimal("10")}]
    matches = match_receipt_items_to_matches(matches, receipt_items, "REC-01")

    checks, discrepancies, table = reconcile_receipts(matches)
    assert len(discrepancies) == 0
    assert table[0].price_status == "NOT_APPLICABLE"
    assert table[0].received_unit_price is None


def test_flexible_receipt_matching_amounts():
    """Receipt with explicit unit price matching PO and Invoice should reconcile cleanly."""
    po_items = [{"description": "Diagnostic Kit", "product_code": "KIT-99", "quantity": Decimal("5"), "unit_price": Decimal("250.00"), "line_total": Decimal("1250.00")}]
    inv_items = [{"description": "Diagnostic Kit", "product_code": "KIT-99", "quantity": Decimal("5"), "unit_price": Decimal("250.00"), "line_total": Decimal("1250.00")}]
    matches, _ = match_line_items(po_items, inv_items, "PO-02", "INV-02")

    # Receipt with explicit unit_price and total
    receipt_items = [{"description": "Diagnostic Kit", "item_code": "KIT-99", "quantity": Decimal("5"), "unit_price": Decimal("250.00"), "total": Decimal("1250.00")}]
    matches = match_receipt_items_to_matches(matches, receipt_items, "REC-02")

    checks, discrepancies, table = reconcile_receipts(matches)
    assert len(discrepancies) == 0
    assert table[0].price_status == "MATCHED"
    assert table[0].received_unit_price == Decimal("250.00")
    assert any(c.check_name == "receipt_price_reconciliation" and c.passed for c in checks)


def test_flexible_receipt_price_mismatch():
    """Receipt with explicit unit price differing from PO authorized rate should flag RECEIPT_PRICE_MISMATCH."""
    po_items = [{"description": "Centrifuge Rotor", "product_code": "ROT-10", "quantity": Decimal("2"), "unit_price": Decimal("500.00"), "line_total": Decimal("1000.00")}]
    inv_items = [{"description": "Centrifuge Rotor", "product_code": "ROT-10", "quantity": Decimal("2"), "unit_price": Decimal("500.00"), "line_total": Decimal("1000.00")}]
    matches, _ = match_line_items(po_items, inv_items, "PO-03", "INV-03")

    # Receipt dock billed with $580.00 rate instead of authorized $500.00
    receipt_items = [{"description": "Centrifuge Rotor", "item_code": "ROT-10", "quantity": Decimal("2"), "unit_price": Decimal("580.00"), "total": Decimal("1160.00")}]
    matches = match_receipt_items_to_matches(matches, receipt_items, "REC-03")

    checks, discrepancies, table = reconcile_receipts(matches)
    assert table[0].price_status == "PRICE_MISMATCH"
    assert len(discrepancies) == 1
    assert discrepancies[0].type == DiscrepancyType.RECEIPT_PRICE_MISMATCH
    assert discrepancies[0].difference == Decimal("80.00")
    assert "receipt document specifies $580.00" in discrepancies[0].explanation


def test_flexible_receipt_grand_total_mismatch():
    """Receipt document with grand total exceeding PO total triggers RECEIPT_TOTAL_MISMATCH in financial reconciliation."""
    po_data = {"purchase_order_number": "PO-04", "subtotal": Decimal("1000.00"), "total": Decimal("1000.00"), "items": []}
    inv_data = {"invoice_number": "INV-04", "subtotal": Decimal("1000.00"), "total": Decimal("1000.00"), "items": []}
    receipt_data = [{"receipt_number": "REC-04", "subtotal": Decimal("1250.00"), "total": Decimal("1250.00")}]

    checks, discrepancies, breakdown = reconcile_financials(po_data, inv_data, receipt_data_list=receipt_data)
    assert breakdown.receipt_total == Decimal("1250.00")
    assert any(d.type == DiscrepancyType.RECEIPT_TOTAL_MISMATCH for d in discrepancies)
    assert any(c.check_name == "receipt_total_reconciliation" and not c.passed for c in checks)


def test_full_pipeline_with_receipt_price_discrepancy():
    """Full pipeline execution on transaction with receipt price mismatch flags case for review."""
    po_data = {
        "purchase_order_number": "PO-2024-TEST",
        "vendor_name": "BioMed Test Labs",
        "subtotal": Decimal("100.00"),
        "total": Decimal("100.00"),
        "currency": "USD",
        "items": [{"description": "Test Flask", "product_code": "FLK-1", "quantity": Decimal("1"), "unit_price": Decimal("100.00"), "line_total": Decimal("100.00")}],
    }
    inv_data = {
        "invoice_number": "INV-2024-TEST",
        "purchase_order_number": "PO-2024-TEST",
        "vendor_name": "BioMed Test Labs",
        "subtotal": Decimal("100.00"),
        "total": Decimal("100.00"),
        "currency": "USD",
        "items": [{"description": "Test Flask", "product_code": "FLK-1", "quantity": Decimal("1"), "unit_price": Decimal("100.00"), "line_total": Decimal("100.00")}],
    }
    # Delivery receipt with price markup
    receipt_data = [{
        "receipt_number": "REC-2024-TEST",
        "purchase_order_number": "PO-2024-TEST",
        "vendor_name": "BioMed Test Labs",
        "total": Decimal("130.00"),
        "items": [{"description": "Test Flask", "item_code": "FLK-1", "quantity": Decimal("1"), "unit_price": Decimal("130.00"), "total": Decimal("130.00")}],
    }]

    result = reconcile_transaction(po_data, inv_data, receipt_data, case_id="CASE-RCPT-TEST", check_duplicates=False)
    assert result.status == ReconciliationStatus.REVIEW_REQUIRED
    assert any(d.type == DiscrepancyType.RECEIPT_PRICE_MISMATCH for d in result.discrepancies)


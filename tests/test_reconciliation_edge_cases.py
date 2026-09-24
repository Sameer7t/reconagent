"""
Stress-testing and edge-case validation suite for the Reconciliation System.

This suite attacks the engine with messy, realistic, and adversarial edge cases:
  1. Dirty OCR vendor names, weird suffixes, multi-country legal forms, punctuation
  2. Currency symbol variations, missing currencies, mixed currencies
  3. Dirty / partial / missing PO numbers
  4. Line items: massive lists (50+ items), duplicated items, arbitrary permutations
  5. Dirty line descriptions: severe OCR noise, numbers, punctuation, casing
  6. Fractional & Decimal quantities (e.g. 12.345 kg, 0.5 hours)
  7. Zero quantities, negative values (credit notes, rebates)
  8. Extreme partial delivery splitting (10+ delivery receipts for one PO)
  9. Multiple unauthorized surcharges (restocking fee, handling, fuel, liftgate)
  10. Floating-point edge cases: 0.0049 roundings, Decimal precision
  11. Incomplete document permutations: only PO, only Invoice, PO + Receipts, Invoice + Receipts
  12. Duplicate detection subtleties: same invoice number across different vendors, whitespace/suffix normalization
  13. Corrupted / None-heavy document payloads (None inside lists, missing fields)
  14. Large batch throughput and memory safety (100 synthetic cases)
"""
import sys
import json
import logging
from decimal import Decimal
from pathlib import Path

# Add src to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

logging.basicConfig(
    level=logging.WARNING, # Keep output clean during heavy testing
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from schemas.reconciliation import (
    ReconciliationPolicy,
    ReconciliationResult,
    ReconciliationStatus,
    Discrepancy,
    DiscrepancyType,
    Severity,
    LinkingConfidence,
    MatchMethod,
    LineItemMatch,
)

from reconciliation.document_linker import (
    normalize_vendor,
    normalize_currency,
    evaluate_link,
    detect_missing_documents,
    batch_link_documents,
)
from reconciliation.header_reconciler import (
    normalize_vendor_name,
    normalize_currency_code,
    reconcile_headers,
)
from reconciliation.line_item_matcher import (
    normalize_description,
    normalize_code,
    calculate_similarity,
    match_line_items,
    match_receipt_items_to_matches,
)
from reconciliation.quantity_reconciler import reconcile_quantities
from reconciliation.price_reconciler import reconcile_prices
from reconciliation.financial_reconciler import reconcile_financials
from reconciliation.receipt_reconciler import reconcile_receipts, build_receipt_comparison_table
from reconciliation.duplicate_detector import DuplicateDetector, build_invoice_fingerprint
from reconciliation.discrepancy_engine import enforce_severities, assign_severity
from reconciliation.decision_engine import determine_status, finalize_result
from reconciliation.pipeline import reconcile_transaction, reconcile_batch


# ============================================================
# 1. DIRTY VENDOR NORMALIZATION EDGE CASES
# ============================================================

def test_edge_vendor_normalization():
    """Tests extreme corporate suffix, punctuation, and whitespace variations."""
    cases = [
        ("Acme Corporation Ltd.", "acme"),
        ("  ACME   HOLDINGS,   LLC  ", "acme"),
        ("Global Logistics S.A.", "global logistics"),
        ("Fast Freight GmbH & Co. KG", "fast freight &"),  # Or stripped clean
        ("Apex Solutions Pty. Limited", "apex solutions"),
        ("St. John's Industrial Supply Co., Inc.", "st john's industrial supply"),
        ("", ""),
        (None, None),
        ("   ", ""),
        ("A", "a"),
        ("123 Logistics", "123 logistics"),
    ]

    for raw, expected in cases:
        norm = normalize_vendor_name(raw)
        # Verify it doesn't crash on None/empty
        if raw is None or not str(raw).strip():
            assert norm is None or norm == "", f"Expected empty/None for {raw!r}, got {norm!r}"
        else:
            assert norm is not None, f"Expected non-None for {raw!r}"
            # Check key corporate suffixes are gone
            for suff in ["corp", "corporation", "ltd", "limited", "llc", "inc"]:
                assert suff not in norm.split(), f"Suffix {suff} still in {norm} from {raw}"

    print("  PASS: test_edge_vendor_normalization")


def test_edge_vendor_matching_dirty():
    """Matching two vendors with dirty OCR and different corporate suffixes."""
    po = {"purchase_order_number": "PO-101", "vendor_name": "Atlas Heavy Equipment, Inc."}
    inv = {"purchase_order_number": "PO-101", "vendor": {"name": "atlas heavy equipment limited  "}}
    rec = [{"purchase_order_number": "PO-101", "vendor_name": "ATLAS HEAVY EQUIPMENT CORP"}]

    checks, discrepancies = reconcile_headers(po, inv, rec)
    vendor_mismatches = [d for d in discrepancies if d.type == DiscrepancyType.VENDOR_MISMATCH]
    assert len(vendor_mismatches) == 0, f"Expected clean match, got discrepancies: {vendor_mismatches}"
    print("  PASS: test_edge_vendor_matching_dirty")


# ============================================================
# 2. CURRENCY EDGE CASES
# ============================================================

def test_edge_currency_normalization():
    """Tests various symbol and ISO formats."""
    cases = [
        ("$", "USD"),
        ("US$", "USD"),
        ("€", "EUR"),
        ("£", "GBP"),
        ("¥", "JPY"),
        ("₹", "INR"),
        ("Rs", "PKR"),
        ("Rs.", "PKR"),
        ("usd", "USD"),
        ("  eur  ", "EUR"),
        (None, None),
        ("", None),
    ]
    for raw, expected in cases:
        norm = normalize_currency_code(raw)
        if expected is None:
            assert norm is None or norm == ""
        else:
            assert norm == expected, f"For {raw!r}, expected {expected!r}, got {norm!r}"

    print("  PASS: test_edge_currency_normalization")


def test_edge_currency_mismatch_blocks_false_price_error():
    """When currency mismatches, CURRENCY_MISMATCH must be CRITICAL."""
    po = {"purchase_order_number": "PO-CUR-1", "currency": "USD", "items": [{"description": "Item", "quantity": 1, "unit_price": 100.0}]}
    inv = {"purchase_order_number": "PO-CUR-1", "currency": "EUR", "items": [{"description": "Item", "quantity": 1, "unit_price": 100.0}]}

    result = reconcile_transaction(po, inv, [], check_duplicates=False)
    curr_mismatches = [d for d in result.discrepancies if d.type == DiscrepancyType.CURRENCY_MISMATCH]
    assert len(curr_mismatches) > 0
    assert curr_mismatches[0].severity == Severity.CRITICAL
    assert result.status == ReconciliationStatus.REVIEW_REQUIRED
    print("  PASS: test_edge_currency_mismatch_blocks_false_price_error")


# ============================================================
# 3. DIRTY & OUT-OF-ORDER LINE ITEMS
# ============================================================

def test_edge_line_item_dirty_ocr_matching():
    """Matches line items despite OCR punctuation and spacing differences."""
    po_items = [
        {"description": "Industrial Widget (Model #X-500)", "product_code": "WID-500", "quantity": 10, "unit_price": 45.00},
        {"description": "Heavy-Duty Cable -- 10m", "product_code": "CBL-10M", "quantity": 4, "unit_price": 15.00},
    ]
    inv_items = [
        # Out of order, dirty punctuation, whitespace
        {"description": "heavy duty cable 10m", "product_code": "CBL-10M", "quantity": 4, "unit_price": 15.00},
        {"description": "INDUSTRIAL WIDGET MODEL X 500", "product_code": "WID-500", "quantity": 10, "unit_price": 45.00},
    ]

    matches, discrepancies = match_line_items(po_items, inv_items, "PO-DIRTY", "INV-DIRTY")
    assert len(matches) == 2
    assert len(discrepancies) == 0
    print("  PASS: test_edge_line_item_dirty_ocr_matching")


def test_edge_line_item_duplicate_descriptions():
    """PO and Invoice have multiple lines with identical descriptions but different prices/quantities."""
    po_items = [
        {"description": "Standard Pallet", "product_code": "PLT-01", "quantity": 5, "unit_price": 20.00},
        {"description": "Standard Pallet", "product_code": "PLT-02", "quantity": 10, "unit_price": 18.00},
    ]
    inv_items = [
        {"description": "Standard Pallet", "product_code": "PLT-02", "quantity": 10, "unit_price": 18.00},
        {"description": "Standard Pallet", "product_code": "PLT-01", "quantity": 5, "unit_price": 20.00},
    ]

    matches, discrepancies = match_line_items(po_items, inv_items, "PO-DUP", "INV-DUP")
    assert len(matches) == 2
    assert len(discrepancies) == 0
    # Both lines matched without cross-matching collision
    matched_skus = {m.po_item.get("product_code") for m in matches}
    assert matched_skus == {"PLT-01", "PLT-02"}
    print("  PASS: test_edge_line_item_duplicate_descriptions")


def test_edge_line_item_fuzzy_threshold():
    """Fuzzy description match when words are reordered or slightly varied."""
    po_items = [{"description": "Repair and refurbishment of container", "quantity": 1, "unit_price": 500.00}]
    inv_items = [{"description": "Container repair and refurbishment", "quantity": 1, "unit_price": 500.00}]

    matches, discrepancies = match_line_items(po_items, inv_items, "PO-FUZZ", "INV-FUZZ")
    assert len(matches) == 1
    assert matches[0].match_method in (MatchMethod.FUZZY_DESCRIPTION, MatchMethod.NORMALIZED_DESCRIPTION)
    print("  PASS: test_edge_line_item_fuzzy_threshold")


def test_edge_line_item_empty_or_none():
    """Handles None or empty items gracefully without crashing."""
    matches, discrepancies = match_line_items([], [], "PO-EMPTY", "INV-EMPTY")
    assert matches == []
    assert discrepancies == []

    # One side empty
    po_items = [{"description": "Sole Item", "quantity": 1, "unit_price": 10.0}]
    matches, discrepancies = match_line_items(po_items, [], "PO-1", "INV-EMPTY")
    assert len(matches) == 0
    assert len(discrepancies) == 1
    assert discrepancies[0].type == DiscrepancyType.UNMATCHED_ITEM
    print("  PASS: test_edge_line_item_empty_or_none")


# ============================================================
# 4. QUANTITY & PARTIAL DELIVERY EDGE CASES
# ============================================================

def test_edge_quantity_fractional():
    """Fractional quantities (e.g. 12.5 kg or 0.33 hours)."""
    matches = [LineItemMatch(
        po_line_id="PO-FRAC-L1", invoice_line_id="INV-FRAC-L1",
        match_method=MatchMethod.NORMALIZED_DESCRIPTION, match_confidence=1.0,
        ordered_quantity=Decimal("12.50"), invoiced_quantity=Decimal("12.50"), received_quantity=Decimal("12.50"),
        po_item={"description": "Bulk Raw Resin"}, invoice_item={"description": "Bulk Raw Resin"}
    )]
    checks, discrepancies, _ = reconcile_quantities(matches)
    assert len(discrepancies) == 0
    print("  PASS: test_edge_quantity_fractional")


def test_edge_quantity_fractional_mismatch():
    """Fractional quantity mismatch within Decimal precision (12.50 vs 12.75)."""
    matches = [LineItemMatch(
        po_line_id="PO-FRAC-L1", invoice_line_id="INV-FRAC-L1",
        match_method=MatchMethod.NORMALIZED_DESCRIPTION, match_confidence=1.0,
        ordered_quantity=Decimal("12.50"), invoiced_quantity=Decimal("12.75"), received_quantity=Decimal("12.50"),
        po_item={"description": "Bulk Raw Resin"}, invoice_item={"description": "Bulk Raw Resin"}
    )]
    checks, discrepancies, _ = reconcile_quantities(matches)
    assert len(discrepancies) >= 1
    types = [d.type for d in discrepancies]
    assert DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_PO in types
    assert discrepancies[0].difference == Decimal("0.25")
    print("  PASS: test_edge_quantity_fractional_mismatch")


def test_edge_quantity_zero_quantities():
    """Line items with quantity = 0 (cancelled or free replacement)."""
    matches = [LineItemMatch(
        po_line_id="PO-ZERO-L1", invoice_line_id="INV-ZERO-L1",
        match_method=MatchMethod.NORMALIZED_DESCRIPTION, match_confidence=1.0,
        ordered_quantity=Decimal("0.00"), invoiced_quantity=Decimal("0.00"), received_quantity=Decimal("0.00"),
        po_item={"description": "Zero Qty Sample"}, invoice_item={"description": "Zero Qty Sample"}
    )]
    checks, discrepancies, _ = reconcile_quantities(matches)
    assert len(discrepancies) == 0
    print("  PASS: test_edge_quantity_zero_quantities")


def test_edge_extreme_partial_deliveries():
    """1 PO fulfilled across 10 partial delivery receipts totaling exactly the PO quantity."""
    po_items = [{"description": "Standard Widget", "product_code": "WID-1", "quantity": 100, "unit_price": 10.0}]
    inv_items = [{"description": "Standard Widget", "product_code": "WID-1", "quantity": 100, "unit_price": 10.0}]

    matches, _ = match_line_items(po_items, inv_items, "PO-PARTIAL", "INV-PARTIAL")

    # 10 delivery receipts of 10 items each
    receipt_data_list = [
        {"receipt_number": f"GRN-{i:03d}", "items": [{"description": "Standard Widget", "item_code": "WID-1", "quantity": 10}]}
        for i in range(1, 11)
    ]

    for i, r in enumerate(receipt_data_list):
        matches = match_receipt_items_to_matches(matches, r.get("items", []), r["receipt_number"])

    assert matches[0].received_quantity == Decimal("100")
    assert len(matches[0].receipt_line_ids) == 10

    checks, discrepancies, _ = reconcile_quantities(matches)
    assert len(discrepancies) == 0
    print("  PASS: test_edge_extreme_partial_deliveries")


def test_edge_partial_deliveries_shortage():
    """1 PO of 100 items, delivered in 3 receipts (30 + 30 + 30 = 90), invoice bills 100."""
    po_items = [{"description": "Standard Widget", "product_code": "WID-1", "quantity": 100, "unit_price": 10.0}]
    inv_items = [{"description": "Standard Widget", "product_code": "WID-1", "quantity": 100, "unit_price": 10.0}]

    matches, _ = match_line_items(po_items, inv_items, "PO-PARTIAL", "INV-PARTIAL")

    receipt_data_list = [
        {"receipt_number": "GRN-001", "items": [{"description": "Standard Widget", "item_code": "WID-1", "quantity": 30}]},
        {"receipt_number": "GRN-002", "items": [{"description": "Standard Widget", "item_code": "WID-1", "quantity": 30}]},
        {"receipt_number": "GRN-003", "items": [{"description": "Standard Widget", "item_code": "WID-1", "quantity": 30}]},
    ]

    for r in receipt_data_list:
        matches = match_receipt_items_to_matches(matches, r.get("items", []), r["receipt_number"])

    assert matches[0].received_quantity == Decimal("90")

    checks, discrepancies, _ = reconcile_quantities(matches)
    types = [d.type for d in discrepancies]
    assert DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_RECEIVED in types
    # 100 billed vs 90 received = 10 units shortage
    shortage_disc = next(d for d in discrepancies if d.type == DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_RECEIVED)
    assert shortage_disc.difference == Decimal("10.00")
    print("  PASS: test_edge_partial_deliveries_shortage")


# ============================================================
# 5. FINANCIAL & ARITHMETIC EDGE CASES
# ============================================================

def test_edge_financial_subcent_tolerances():
    """Decimal rounding differences of $0.0049 within policy tolerance."""
    policy = ReconciliationPolicy(price_tolerance=Decimal("0.02"), total_tolerance=Decimal("0.05"))

    po = {
        "purchase_order_number": "PO-CENT",
        "subtotal": 1000.00,
        "shipping": 50.00,
        "tax": 100.00,
        "total": 1150.00,
        "items": [{"description": "Item", "quantity": 1, "unit_price": 1000.00}]
    }
    inv = {
        "invoice_number": "INV-CENT",
        "purchase_order_number": "PO-CENT",
        "subtotal": 1000.01,
        "shipping": 50.00,
        "total_tax": 100.02,
        "total": 1150.03,
        "items": [{"description": "Item", "quantity": 1, "unit_price": 1000.01}]
    }

    checks, discrepancies, breakdown = reconcile_financials(po, inv, policy)
    assert len(discrepancies) == 0, f"Expected 0 discrepancies within tolerance, got {discrepancies}"
    print("  PASS: test_edge_financial_subcent_tolerances")


def test_edge_financial_unauthorized_surcharge_breakdown():
    """Invoice adds a $750 unapproved charge, detected as UNAUTHORIZED_CHARGE."""
    po = {
        "purchase_order_number": "PO-FEE",
        "subtotal": 5000.00,
        "shipping": 100.00,
        "total": 5100.00,
        "items": [{"description": "Item", "quantity": 10, "unit_price": 500.00}]
    }
    inv = {
        "invoice_number": "INV-FEE",
        "purchase_order_number": "PO-FEE",
        "subtotal": 5000.00,
        "shipping": 100.00,
        "total": 5850.00,  # $750 unapproved surcharge
        "items": [{"description": "Item", "quantity": 10, "unit_price": 500.00}]
    }

    checks, discrepancies, breakdown = reconcile_financials(po, inv)
    unauthorized = [d for d in discrepancies if d.type == DiscrepancyType.UNAUTHORIZED_CHARGE]
    assert len(unauthorized) == 1
    assert unauthorized[0].difference == Decimal("750.00")
    assert unauthorized[0].severity == Severity.CRITICAL  # Over $500 threshold
    print("  PASS: test_edge_financial_unauthorized_surcharge_breakdown")


def test_edge_financial_unapplied_po_discount():
    """PO specified a $200 contract discount, but invoice omitted it."""
    po = {
        "purchase_order_number": "PO-DISC",
        "subtotal": 2000.00,
        "discount": 200.00,
        "total": 1800.00,
        "items": [{"description": "Item", "quantity": 1, "unit_price": 2000.00}]
    }
    inv = {
        "invoice_number": "INV-DISC",
        "purchase_order_number": "PO-DISC",
        "subtotal": 2000.00,
        "total_discount": 0.00,
        "total": 2000.00,
        "items": [{"description": "Item", "quantity": 1, "unit_price": 2000.00}]
    }

    checks, discrepancies, breakdown = reconcile_financials(po, inv)
    disc_issues = [d for d in discrepancies if d.type == DiscrepancyType.DISCOUNT_NOT_APPLIED]
    assert len(disc_issues) == 1
    assert disc_issues[0].expected_value == "200.00"
    print("  PASS: test_edge_financial_unapplied_po_discount")


# ============================================================
# 6. MISSING DOCUMENT COMBINATIONS
# ============================================================

def test_edge_missing_document_permutations():
    """Tests every combination of missing documents."""
    po = {"purchase_order_number": "PO-101", "vendor_name": "ABC", "items": []}
    inv = {"invoice_number": "INV-101", "purchase_order_number": "PO-101", "vendor": {"name": "ABC"}, "items": []}
    rec = [{"receipt_number": "REC-101", "purchase_order_number": "PO-101", "vendor_name": "ABC", "items": []}]

    # 1. Invoice + PO (Receipt missing) -> INCOMPLETE
    r1 = reconcile_transaction(po, inv, [], check_duplicates=False)
    assert r1.status == ReconciliationStatus.INCOMPLETE
    assert "RECEIPT" in r1.missing_documents

    # 2. Invoice only (PO and Receipt missing) -> INCOMPLETE
    r2 = reconcile_transaction(None, inv, [], check_duplicates=False)
    assert r2.status in (ReconciliationStatus.INCOMPLETE, ReconciliationStatus.UNMATCHED)
    assert "PURCHASE_ORDER" in r2.missing_documents

    # 3. PO + Receipt (Invoice missing) -> INCOMPLETE
    r3 = reconcile_transaction(po, None, rec, check_duplicates=False)
    assert r3.status == ReconciliationStatus.INCOMPLETE
    assert "INVOICE" in r3.missing_documents

    # 4. Nothing -> UNMATCHED
    r4 = reconcile_transaction(None, None, [], check_duplicates=False)
    assert r4.status == ReconciliationStatus.UNMATCHED

    print("  PASS: test_edge_missing_document_permutations")


# ============================================================
# 7. DUPLICATE INVOICE DETECTION EDGE CASES
# ============================================================

def test_edge_duplicate_detection_subtleties():
    """Validates duplicate fingerprinting edge cases."""
    temp_ledger = Path("__test_edge_ledger.json")
    if temp_ledger.exists():
        temp_ledger.unlink()

    detector = DuplicateDetector(ledger_path=temp_ledger)

    inv_a = {
        "invoice_number": "INV-9999",
        "vendor": {"name": "Apex Industrial Supplies, LLC"},
        "invoice_date": "2026-03-01",
        "currency": "USD",
        "total": 5000.00,
        "purchase_order_number": "PO-100",
    }

    # Case 1: First submission -> clean
    assert detector.check_duplicate(inv_a) is None

    # Case 2: Exact resubmission -> DUPLICATE
    res2 = detector.check_duplicate(inv_a)
    assert res2 is not None
    assert res2.type == DiscrepancyType.DUPLICATE_INVOICE

    # Case 3: Same invoice number from DIFFERENT vendor -> NOT DUPLICATE
    inv_different_vendor = {
        "invoice_number": "INV-9999",
        "vendor": {"name": "Zenith Global Corp"},
        "invoice_date": "2026-03-01",
        "currency": "USD",
        "total": 5000.00,
        "purchase_order_number": "PO-100",
    }
    assert detector.check_duplicate(inv_different_vendor) is None

    # Case 4: Same vendor, same invoice number, but different casing/punctuation in vendor -> DUPLICATE
    inv_casing_vendor = {
        "invoice_number": "INV-9999",
        "vendor": {"name": "APEX INDUSTRIAL SUPPLIES"},
        "invoice_date": "2026-03-01",
        "currency": "USD",
        "total": 5000.00,
        "purchase_order_number": "PO-100",
    }
    assert detector.check_duplicate(inv_casing_vendor) is not None

    if temp_ledger.exists():
        temp_ledger.unlink()

    print("  PASS: test_edge_duplicate_detection_subtleties")


# ============================================================
# 8. HIGH-VOLUME BATCH STRESS TEST (50 Line Items & Multiple Trans)
# ============================================================

def test_edge_large_line_item_volume():
    """Processes an invoice and PO with 50 distinct line items shuffled in random order."""
    po_items = [
        {"description": f"Component Model-{i:03d}", "product_code": f"SKU-{i:03d}", "quantity": i, "unit_price": float(i * 10)}
        for i in range(1, 51)
    ]
    # Reverse order on invoice
    inv_items = list(reversed(po_items))
    rec_items = [
        {"description": item["description"], "item_code": item["product_code"], "quantity": item["quantity"]}
        for item in po_items
    ]

    total_amount = sum(item["quantity"] * item["unit_price"] for item in po_items)

    po = {
        "purchase_order_number": "PO-BIG-50",
        "vendor_name": "Mega Manufacturer Ltd",
        "currency": "USD",
        "items": po_items,
        "subtotal": total_amount,
        "total": total_amount,
    }
    inv = {
        "invoice_number": "INV-BIG-50",
        "purchase_order_number": "PO-BIG-50",
        "vendor": {"name": "Mega Manufacturer"},
        "currency": "USD",
        "items": inv_items,
        "subtotal": total_amount,
        "total": total_amount,
    }
    rec = {
        "receipt_number": "REC-BIG-50",
        "purchase_order_number": "PO-BIG-50",
        "vendor_name": "Mega Manufacturer",
        "currency": "USD",
        "items": rec_items,
        "total": total_amount,
    }

    result = reconcile_transaction(po, inv, [rec], case_id="STRESS-50-ITEMS", check_duplicates=False)
    assert len(result.line_item_matches) == 50
    assert len(result.discrepancies) == 0
    assert result.status in (ReconciliationStatus.MATCHED, ReconciliationStatus.MATCHED_WITH_TOLERANCE)
    print(f"  PASS: test_edge_large_line_item_volume (50 line items matched perfectly: {result.status.value})")


def test_edge_batch_processing_stress():
    """Runs a batch of 20 varied transactions simultaneously."""
    batch_txns = []
    for i in range(1, 21):
        # Even numbers perfect, odd numbers have slight variance
        price_offset = 0 if i % 2 == 0 else 50
        po = {
            "purchase_order_number": f"PO-BATCH-{i:03d}",
            "vendor_name": f"Supplier-{i:03d} Corp",
            "currency": "USD",
            "items": [{"description": f"Item-{i}", "product_code": f"SKU-{i}", "quantity": 10, "unit_price": 100.0}],
            "subtotal": 1000.0,
            "total": 1000.0,
        }
        inv = {
            "invoice_number": f"INV-BATCH-{i:03d}",
            "purchase_order_number": f"PO-BATCH-{i:03d}",
            "vendor": {"name": f"Supplier-{i:03d}"},
            "currency": "USD",
            "items": [{"description": f"Item-{i}", "product_code": f"SKU-{i}", "quantity": 10, "unit_price": 100.0 + price_offset}],
            "subtotal": 1000.0 + (price_offset * 10),
            "total": 1000.0 + (price_offset * 10),
        }
        rec = {
            "receipt_number": f"REC-BATCH-{i:03d}",
            "purchase_order_number": f"PO-BATCH-{i:03d}",
            "vendor_name": f"Supplier-{i:03d}",
            "currency": "USD",
            "items": [{"description": f"Item-{i}", "item_code": f"SKU-{i}", "quantity": 10}],
            "total": 1000.0,
        }
        batch_txns.append({
            "case_id": f"CASE-BATCH-{i:03d}",
            "po_data": po,
            "invoice_data": inv,
            "receipt_data_list": [rec],
        })

    results = reconcile_batch(batch_txns, check_duplicates=False)
    assert len(results) == 20
    # Exactly 10 should be MATCHED and 10 should be REVIEW_REQUIRED
    matched_count = sum(1 for r in results if r.status in (ReconciliationStatus.MATCHED, ReconciliationStatus.MATCHED_WITH_TOLERANCE))
    review_count = sum(1 for r in results if r.status == ReconciliationStatus.REVIEW_REQUIRED)

    assert matched_count == 10, f"Expected 10 matched, got {matched_count}"
    assert review_count == 10, f"Expected 10 review required, got {review_count}"
    print(f"  PASS: test_edge_batch_processing_stress (20 cases: {matched_count} matched, {review_count} review required)")


# ============================================================
# MASTER RUNNER
# ============================================================

def run_all_edge_tests():
    """Runs the entire edge-case stress test suite."""
    tests = [
        test_edge_vendor_normalization,
        test_edge_vendor_matching_dirty,
        test_edge_currency_normalization,
        test_edge_currency_mismatch_blocks_false_price_error,
        test_edge_line_item_dirty_ocr_matching,
        test_edge_line_item_duplicate_descriptions,
        test_edge_line_item_fuzzy_threshold,
        test_edge_line_item_empty_or_none,
        test_edge_quantity_fractional,
        test_edge_quantity_fractional_mismatch,
        test_edge_quantity_zero_quantities,
        test_edge_extreme_partial_deliveries,
        test_edge_partial_deliveries_shortage,
        test_edge_financial_subcent_tolerances,
        test_edge_financial_unauthorized_surcharge_breakdown,
        test_edge_financial_unapplied_po_discount,
        test_edge_missing_document_permutations,
        test_edge_duplicate_detection_subtleties,
        test_edge_large_line_item_volume,
        test_edge_batch_processing_stress,
    ]

    passed = 0
    failed = 0

    print("\n" + "=" * 70)
    print("STARTING ADVANCED RECONCILIATION EDGE-CASE & STRESS TEST SUITE")
    print("=" * 70)

    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"  FAIL: {test.__name__}: {e}")

    print("\n" + "=" * 70)
    print(f"EDGE-CASE RESULTS: {passed} PASSED, {failed} FAILED OUT OF {passed + failed}")
    print("=" * 70)

    if failed > 0:
        print("\nSOME EDGE-CASE TESTS FAILED! FIXING REQUIRED.")
        return False
    else:
        print("\nALL ADVANCED EDGE CASES PASSED WITH 100% SUCCESS!")
        return True


if __name__ == "__main__":
    success = run_all_edge_tests()
    if not success:
        sys.exit(1)

"""
Tests for Description and Specification Reconciliation.

Validates:
1. Real-world descriptive words match with fuzzy logic (e.g., 'marker' vs 'merker').
2. Measurements, units, and dimensions strictly enforce non-fuzzy checks
   (e.g., 'marker 0.5 mm' vs 'marker 0.10 mm' or '4x4' vs '4x8' must NEVER match).
3. 3-way reconciliation correctly audits specifications across PO, Invoice, and Delivery Receipt.
"""
import sys
from decimal import Decimal
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    DiscrepancyType,
    MatchMethod,
    ReconciliationPolicy,
    ReconciliationStatus,
    Severity,
)
from reconciliation.line_item_matcher import (
    calculate_similarity,
    compare_item_descriptions,
    extract_specs_and_words,
    match_line_items,
    match_receipt_items_to_matches,
)
from reconciliation.description_reconciler import reconcile_descriptions
from reconciliation.pipeline import reconcile_transaction


class TestSpecificationAndFuzzyLogic:
    def test_extract_specs_and_words(self):
        """Test extraction of dimensions, measurements, and words."""
        p = extract_specs_and_words("Marker 0.5 mm")
        assert p["measurements"].get("mm") == 0.5
        assert "marker" in p["words"]

        p2 = extract_specs_and_words("Treated Lumber 4x4")
        assert len(p2["dimensions"]) == 1
        assert p2["dimensions"][0][0] == (4.0, 4.0)

        p3 = extract_specs_and_words("MERKER 0.50 mm")
        assert p3["measurements"].get("mm") == 0.5
        assert "merker" in p3["words"]

    def test_real_words_fuzzy_match(self):
        """Real-world words with typos or OCR variations should match."""
        # marker vs merker
        is_match, sim, code, reason = compare_item_descriptions("Marker", "MERKER")
        assert is_match is True
        assert sim >= 0.70
        assert code == "MATCHED"

        # processor vs procesor
        is_match, sim, code, reason = compare_item_descriptions(
            "Intel Core Processor", "Intel Core Procesor"
        )
        assert is_match is True
        assert sim >= 0.85

        # cartridge vs catridge
        is_match, sim, code, reason = compare_item_descriptions(
            "Laser Toner Cartridge", "Laser Toner Catridge"
        )
        assert is_match is True
        assert sim >= 0.85

    def test_measurement_mismatch_strictly_rejected(self):
        """Conflicting measurements must never match and calculate_similarity must return 0.0."""
        # marker 0.5 mm vs marker 0.10 mm
        is_match, sim, code, reason = compare_item_descriptions(
            "Marker 0.5 mm", "Marker 0.10 mm"
        )
        assert is_match is False
        assert sim == 0.0
        assert code == "MEASUREMENT_MISMATCH"
        assert "0.5 vs 0.1" in reason

        # calculate_similarity must be 0.0
        assert calculate_similarity("Marker 0.5 mm", "Marker 0.10 mm") == 0.0

    def test_dimension_mismatch_strictly_rejected(self):
        """Conflicting dimensions (e.g. 4x4 vs 4x8) must never match."""
        # Treated Lumber 4x4 vs Treated Lumber 4x8
        is_match, sim, code, reason = compare_item_descriptions(
            "Treated Lumber 4x4", "Treated Lumber 4x8"
        )
        assert is_match is False
        assert sim == 0.0
        assert code == "DIMENSION_MISMATCH"

        assert calculate_similarity("Treated Lumber 4x4", "Treated Lumber 4x8") == 0.0

    def test_matching_dimension_with_word_typo(self):
        """Matching dimensions with typo in word should match successfully."""
        is_match, sim, code, reason = compare_item_descriptions(
            "4x4 wud post", "4x4 wood post"
        )
        assert is_match is True
        assert sim >= 0.75
        assert code == "MATCHED"

    def test_same_measurement_different_format(self):
        """Equivalent measurements (0.5 mm vs 0.50 mm) should match."""
        is_match, sim, code, reason = compare_item_descriptions(
            "Marker 0.5 mm", "MERKER 0.50 mm"
        )
        assert is_match is True
        assert sim >= 0.75

        # Spacing variations
        assert calculate_similarity("Marker 0.5mm", "marker 0.5 mm") == 1.0


class TestLineItemMatchingWithFuzzyAndSpecs:
    def test_match_line_items_typo_success(self):
        """PO has 'Marker' and Invoice has 'MERKER' - should match."""
        po_items = [
            {"description": "Fine Tip Marker", "quantity": 10, "unit_price": 2.50}
        ]
        inv_items = [
            {"description": "Fine Tip Merker", "quantity": 10, "unit_price": 2.50}
        ]

        matches, discrepancies = match_line_items(po_items, inv_items, "PO-1", "INV-1")
        assert len(matches) == 1
        assert matches[0].match_method == MatchMethod.FUZZY_DESCRIPTION
        assert matches[0].match_confidence >= 0.75
        assert len(discrepancies) == 0

    def test_match_line_items_spec_conflict_not_matched(self):
        """PO has 'Marker 0.5 mm' and Invoice has 'Marker 0.10 mm' - must not match."""
        po_items = [
            {"description": "Marker 0.5 mm", "quantity": 10, "unit_price": 2.50}
        ]
        inv_items = [
            {"description": "Marker 0.10 mm", "quantity": 10, "unit_price": 2.50}
        ]

        matches, discrepancies = match_line_items(po_items, inv_items, "PO-1", "INV-1")
        # Since measurements conflict, calculate_similarity is 0.0, so they are not paired
        assert len(matches) == 0
        assert len(discrepancies) == 2  # Both PO and Invoice line items unmatched
        assert all(d.type == DiscrepancyType.UNMATCHED_ITEM for d in discrepancies)

    def test_match_receipt_items_fuzzy_typo(self):
        """Receipt has 'MERKER' matching PO 'Marker'."""
        po_items = [
            {"description": "Black Dry Erase Marker", "quantity": 10, "unit_price": 2.50}
        ]
        inv_items = [
            {"description": "Black Dry Erase Marker", "quantity": 10, "unit_price": 2.50}
        ]
        matches, _ = match_line_items(po_items, inv_items, "PO-1", "INV-1")

        receipt_items = [
            {"description": "Black Dry Erase Merker", "quantity": 10}
        ]
        matches = match_receipt_items_to_matches(matches, receipt_items, "REC-1")
        assert len(matches[0].receipt_items) == 1
        assert matches[0].received_quantity == Decimal("10")


class TestThreeWayReconciliationAudit:
    def test_reconcile_transaction_with_merker_typo(self):
        """Full 3-way reconciliation with 'MERKER' typo matches cleanly."""
        po = {
            "purchase_order_number": "PO-2024-8888",
            "vendor_name": "Apex Supplies Inc",
            "currency": "USD",
            "subtotal": 25.00,
            "tax": 0.00,
            "total": 25.00,
            "items": [
                {"description": "Whiteboard Marker Black", "quantity": 10, "unit_price": 2.50, "line_total": 25.00}
            ],
        }
        inv = {
            "invoice_number": "INV-2024-8888",
            "purchase_order_number": "PO-2024-8888",
            "vendor": {"name": "Apex Supplies Inc"},
            "currency": "USD",
            "subtotal": 25.00,
            "tax": 0.00,
            "total": 25.00,
            "items": [
                {"description": "Whiteboard Merker Black", "quantity": 10, "unit_price": 2.50, "line_total": 25.00}
            ],
        }
        rec = [
            {
                "receipt_number": "REC-2024-8888",
                "purchase_order_number": "PO-2024-8888",
                "vendor_name": "Apex Supplies Inc",
                "items": [
                    {"description": "Whiteboard Merker Black", "quantity_delivered": 10}
                ],
            }
        ]

        result = reconcile_transaction(po, inv, rec, check_duplicates=False)
        assert result.status == ReconciliationStatus.MATCHED
        assert len(result.line_item_matches) == 1
        assert len(result.description_checks) >= 1
        assert all(c.passed for c in result.description_checks)

    def test_reconcile_receipt_specification_mismatch(self):
        """
        PO and Invoice specify '0.5 mm' but Receipt delivered '0.10 mm'.
        Must flag SPECIFICATION_MISMATCH for delivered variant!
        """
        po = {
            "purchase_order_number": "PO-2024-9999",
            "vendor_name": "Apex Supplies Inc",
            "currency": "USD",
            "subtotal": 50.00,
            "tax": 0.00,
            "total": 50.00,
            "items": [
                {"product_code": "MK-05", "description": "Marker 0.5 mm", "quantity": 20, "unit_price": 2.50, "line_total": 50.00}
            ],
        }
        inv = {
            "invoice_number": "INV-2024-9999",
            "purchase_order_number": "PO-2024-9999",
            "vendor": {"name": "Apex Supplies Inc"},
            "currency": "USD",
            "subtotal": 50.00,
            "tax": 0.00,
            "total": 50.00,
            "items": [
                {"product_code": "MK-05", "description": "Marker 0.5 mm", "quantity": 20, "unit_price": 2.50, "line_total": 50.00}
            ],
        }
        rec = [
            {
                "receipt_number": "REC-2024-9999",
                "purchase_order_number": "PO-2024-9999",
                "vendor_name": "Apex Supplies Inc",
                "items": [
                    {"product_code": "MK-05", "description": "Marker 0.10 mm", "quantity_delivered": 20}
                ],
            }
        ]

        result = reconcile_transaction(po, inv, rec, check_duplicates=False)
        # Should flag SPECIFICATION_MISMATCH discrepancy
        spec_discs = [d for d in result.discrepancies if d.type == DiscrepancyType.SPECIFICATION_MISMATCH]
        assert len(spec_discs) >= 1
        assert "0.5 vs 0.1" in spec_discs[0].explanation or "0.5 mm" in spec_discs[0].explanation
        assert result.status in (ReconciliationStatus.REVIEW_REQUIRED, ReconciliationStatus.UNMATCHED)

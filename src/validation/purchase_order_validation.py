import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# CONFIGURATION & GLOBAL CONSTANTS
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("POVerifier")

TOLERANCE = Decimal("0.02")

# ============================================================
# UTILITIES & CONVERSIONS
# ============================================================
def to_decimal(val: Any) -> Optional[Decimal]:
    """Safely converts numerical or string inputs to Decimal without crashing."""
    if val is None:
        return None
    try:
        clean_val = str(val).replace(",", "").strip()
        if not clean_val or clean_val.lower() in ("none", "null", ""):
            return None
        return Decimal(clean_val).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return None


def is_close(val1: Optional[Decimal], val2: Optional[Decimal], tolerance: Decimal = TOLERANCE) -> bool:
    """Evaluates whether two decimal values match within acceptable variance."""
    if val1 is None or val2 is None:
        return False
    return abs(val1 - val2) <= tolerance


# ============================================================
# VERIFICATION ENGINE
# ============================================================
def verify_po_line_items(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Decimal, Decimal, int, int]:
    """
    Validates (quantity * unit_price) - discount + tax == line_total for each purchase order item.
    Returns:
        - audited_items: List with audit notes and discrepancy flags
        - sum_line_totals: Sum of all valid line totals
        - sum_quantities: Sum of all item quantities
        - checks_passed: Number of successful item-level math checks
        - total_checks: Total eligible item checks attempted
    """
    audited_items = []
    sum_line_totals = Decimal("0.00")
    sum_quantities = Decimal("0.00")
    checks_passed = 0
    total_checks = 0

    for idx, item in enumerate(items, start=1):
        qty = to_decimal(item.get("quantity"))
        unit_price = to_decimal(item.get("unit_price"))
        # Support both PO schema naming (discount/tax) and aliases (unit_discount/unit_tax)
        line_discount = to_decimal(item.get("discount") or item.get("unit_discount")) or Decimal("0.00")
        line_tax = to_decimal(item.get("tax") or item.get("unit_tax")) or Decimal("0.00")
        line_total = to_decimal(item.get("line_total") or item.get("total_price") or item.get("total"))

        item_audit = {
            "index": idx,
            "product_code": item.get("product_code") or item.get("sku") or item.get("item_code"),
            "description": item.get("description"),
            "quantity": qty,
            "unit": item.get("unit"),
            "unit_price": unit_price,
            "discount": line_discount,
            "tax": line_tax,
            "reported_line_total": line_total,
            "calculated_line_total": None,
            "is_valid": None,
            "error_note": None
        }

        # Track total quantity if quantity exists
        if qty is not None:
            sum_quantities += qty

        if qty is not None and unit_price is not None:
            total_checks += 1
            calculated_total = ((qty * unit_price) - line_discount + line_tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            item_audit["calculated_line_total"] = calculated_total

            if line_total is not None:
                if is_close(calculated_total, line_total):
                    checks_passed += 1
                    item_audit["is_valid"] = True
                    sum_line_totals += line_total
                else:
                    item_audit["is_valid"] = False
                    item_audit["error_note"] = (
                        f"Line total discrepancy: calculated {calculated_total} vs reported {line_total}"
                    )
                    sum_line_totals += line_total  # Carry reported value for upstream checking
            else:
                # Inferred Line Check
                checks_passed += 1
                item_audit["is_valid"] = True
                item_audit["error_note"] = f"Line total inferred: {calculated_total}"
                sum_line_totals += calculated_total
        elif line_total is not None:
            sum_line_totals += line_total
            item_audit["error_note"] = "Incomplete quantity or unit_price; line item math untestable"
        else:
            item_audit["error_note"] = "Missing pricing components on line item"

        audited_items.append(item_audit)

    return audited_items, sum_line_totals, sum_quantities, checks_passed, total_checks


def verify_purchase_order_math(po_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes end-to-end deterministic verification on purchase order data.
    Computes a transparent confidence score (0-100) based on arithmetic integrity.
    """
    if hasattr(po_data, "model_dump"):
        po_data = po_data.model_dump(mode="json")
    elif not isinstance(po_data, dict):
        po_data = {}

    report = {
        "is_valid": False,
        "confidence_score": 0.0,
        "discrepancies": [],
        "line_item_audit": [],
        "checks": {
            "total_quantity_verified": False,
            "line_items_verified": False,
            "subtotal_verified": False,
            "grand_total_verified": False
        },
        "resolved_totals": {}
    }

    try:
        items = po_data.get("items") or po_data.get("lines") or []
        reported_total_qty = to_decimal(po_data.get("total_quantity"))
        subtotal = to_decimal(po_data.get("subtotal"))
        doc_discount = to_decimal(po_data.get("discount") or po_data.get("total_discount")) or Decimal("0.00")
        doc_tax = to_decimal(po_data.get("tax") or po_data.get("total_tax")) or Decimal("0.00")
        shipping = to_decimal(po_data.get("shipping")) or Decimal("0.00")
        round_adj = to_decimal(po_data.get("rounding_adjustment") or po_data.get("round_adjustment")) or Decimal("0.00")
        grand_total = to_decimal(po_data.get("total") or po_data.get("total_amount") or po_data.get("grand_total"))

        # Score Weight Components (Max: 100)
        score = Decimal("0.0")

        sum_line_totals = Decimal("0.00")
        sum_quantities = Decimal("0.00")

        # 1. Line Item Verification (Up to 30 points)
        if items:
            audited_items, sum_line_totals, sum_quantities, items_passed, total_checks = verify_po_line_items(items)
            report["line_item_audit"] = audited_items

            if total_checks > 0:
                pass_rate = Decimal(items_passed) / Decimal(total_checks)
                score += pass_rate * Decimal("30.0")
                if items_passed == total_checks:
                    report["checks"]["line_items_verified"] = True
                else:
                    report["discrepancies"].append(f"Failed {total_checks - items_passed}/{total_checks} line item math checks.")
            else:
                score += Decimal("10.0")
                report["discrepancies"].append("Line item variables insufficient to calculate item totals.")
        else:
            report["discrepancies"].append("No line items found in purchase order payload.")

        # 2. Total Quantity Verification (Up to 10 points)
        if reported_total_qty is not None:
            if is_close(sum_quantities, reported_total_qty):
                score += Decimal("10.0")
                report["checks"]["total_quantity_verified"] = True
            else:
                report["discrepancies"].append(
                    f"Total quantity mismatch: sum of items ({sum_quantities}) != reported total_quantity ({reported_total_qty})."
                )
        else:
            # Grant structural points if not required/reported to avoid penalizing standard POs
            score += Decimal("10.0")

        # 3. Subtotal & Grand Total Pre-computation
        effective_subtotal = subtotal if subtotal is not None else sum_line_totals
        calculated_grand_total = effective_subtotal - doc_discount + doc_tax + shipping + round_adj
        grand_total_matches = grand_total is not None and is_close(calculated_grand_total, grand_total)

        # 3. Subtotal Verification (Up to 30 points)
        if subtotal is not None:
            if is_close(sum_line_totals, subtotal):
                score += Decimal("30.0")
                report["checks"]["subtotal_verified"] = True
            else:
                report["discrepancies"].append(
                    f"Subtotal discrepancy: sum of lines ({sum_line_totals}) != reported subtotal ({subtotal})."
                )
        else:
            # Subtotal is not explicitly printed
            if grand_total is not None:
                # Reconcile through reported grand total
                if grand_total_matches:
                    score += Decimal("30.0")
                    report["checks"]["subtotal_verified"] = True
                elif sum_line_totals > Decimal("0.00"):
                    score += Decimal("15.0")
                    report["discrepancies"].append(
                        "Reported subtotal absent and inferred total does not reconcile with grand total."
                    )
                else:
                    report["discrepancies"].append("Reported subtotal absent and no line items available.")
            else:
                # No grand total and no subtotal on PO: infer cleanly from line items without flagging
                if items and (total_checks == 0 or items_passed == total_checks):
                    score += Decimal("30.0")
                    report["checks"]["subtotal_verified"] = True
                elif sum_line_totals > Decimal("0.00"):
                    score += Decimal("15.0")
                else:
                    report["discrepancies"].append("No line items or pricing available to determine subtotal.")

        # 4. Grand Total Verification (Up to 30 points)
        # Formula: Subtotal - Discount + Tax + Shipping + RoundingAdjustment
        if grand_total is not None:
            if grand_total_matches:
                score += Decimal("30.0")
                report["checks"]["grand_total_verified"] = True
            else:
                report["discrepancies"].append(
                    f"Grand total discrepancy: calculated {calculated_grand_total} "
                    f"!= reported {grand_total} (Diff: {abs(calculated_grand_total - grand_total)})."
                )
        else:
            # Purchase Order has no explicitly stated grand total: grant full points without flagging
            score += Decimal("30.0")
            report["checks"]["grand_total_verified"] = True

        # Record clean financial summary
        report["resolved_totals"] = {
            "sum_line_totals": float(sum_line_totals),
            "sum_quantities": float(sum_quantities),
            "reported_total_quantity": float(reported_total_qty) if reported_total_qty is not None else None,
            "reported_subtotal": float(subtotal) if subtotal is not None else None,
            "document_discount": float(doc_discount),
            "document_tax": float(doc_tax),
            "shipping": float(shipping),
            "round_adjustment": float(round_adj),
            "calculated_grand_total": float(calculated_grand_total),
            "reported_grand_total": float(grand_total) if grand_total is not None else None,
        }

        # Final Evaluation
        final_confidence = float(score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        report["confidence_score"] = final_confidence
        report["is_valid"] = final_confidence >= 70.0

        if not report["is_valid"]:
            logger.warning(
                f"PO math verification flagged issues (Score: {final_confidence}%). Discrepancies: {report['discrepancies']}"
            )
        else:
            logger.info(f"PO deterministic math verified cleanly (Score: {final_confidence}%).")

    except Exception as e:
        logger.error(f"Unexpected error during purchase order deterministic verification: {e}", exc_info=True)
        report["discrepancies"].append(f"Verification runtime crash prevented: {str(e)}")
        report["confidence_score"] = 0.0
        report["is_valid"] = False

    return report


def verify_purchase_order_batch(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Validates a list of extracted purchase order records in batch.
    Each record should contain 'extracted_data' (or be the PO data dictionary itself).
    Adds or updates 'validation_report' on each record.
    """
    audited_records = []
    for record in records:
        rec_copy = dict(record)
        payload = rec_copy.get("extracted_data", rec_copy)
        val_report = verify_purchase_order_math(payload)
        rec_copy["validation_report"] = val_report
        audited_records.append(rec_copy)
    return audited_records


def print_po_batch_validation_summary(audited_records: List[Dict[str, Any]]) -> None:
    """
    Prints a formatted summary table of batch verification results for purchase orders.
    """
    total = len(audited_records)
    valid_count = sum(1 for r in audited_records if r.get("validation_report", {}).get("is_valid", False))
    flagged_count = total - valid_count

    separator = "=" * 80
    print(f"\n{separator}")
    print(f"PO BATCH VALIDATION SUMMARY: {valid_count}/{total} Valid ({flagged_count} Flagged)")
    print(separator)
    for idx, r in enumerate(audited_records, start=1):
        name = r.get("file_name", f"Record_{idx}")
        vr = r.get("validation_report", {})
        score = vr.get("confidence_score", 0.0)
        status = "VALID" if vr.get("is_valid") else "FLAGGED"
        discrepancies = ", ".join(vr.get("discrepancies", [])) or "None"
        print(f"[{idx:>3}] {name:<35} | Status: {status:<7} | Score: {score:>5.1f}% | Issues: {discrepancies}")
    print(f"{separator}\n")


# ============================================================
# SELF-TEST HARNESS
# ============================================================
if __name__ == "__main__":
    # Test Payload with item discounts, taxes, and shipping
    mock_po_payload = {
        "purchase_order_number": "PO-99101",
        "vendor_name": "Acme Industrial Corp",
        "buyer_name": "Global Manufacturing Ltd",
        "items": [
            {
                "product_code": "WID-100",
                "description": "Precision Bearing Kit",
                "quantity": 10,
                "unit_price": 25.00,
                "discount": 10.00,  # (10 * 25.00) - 10.00 = 240.00
                "tax": 0.00,
                "line_total": 240.00
            },
            {
                "product_code": "OIL-500",
                "description": "Synthetic Lubricant 5L",
                "quantity": 4,
                "unit_price": 15.00,
                "discount": 0.00,
                "tax": 3.00,       # (4 * 15.00) + 3.00 = 63.00
                "line_total": 63.00
            }
        ],
        "subtotal": 303.00,
        "discount": 15.00,  # Document level discount
        "tax": 24.24,       # Document level tax
        "shipping": 20.00,
        "rounding_adjustment": -0.04,
        "total": 332.20
    }

    print("\n--- RUNNING SELF-TEST: VALID PURCHASE ORDER ---")
    result = verify_purchase_order_math(mock_po_payload)
    print(f"Verified: {result['is_valid']}")
    print(f"Confidence Score: {result['confidence_score']}%")
    if result['discrepancies']:
        print(f"Discrepancies: {result['discrepancies']}")

    # Test Payload without explicit subtotal row (reconciled through grand total)
    mock_po_no_subtotal = {
        "purchase_order_number": "PO-NO-SUBTOTAL",
        "items": [
            {"description": "Item 1", "quantity": 2, "unit_price": 50.00, "line_total": 100.00},
            {"description": "Item 2", "quantity": 1, "unit_price": 40.00, "line_total": 40.00}
        ],
        "subtotal": None,
        "shipping": 10.00,
        "total": 150.00  # 140 + 10 = 150
    }

    print("\n--- RUNNING SELF-TEST: OMITTED SUBTOTAL RECONCILED ---")
    no_sub_result = verify_purchase_order_math(mock_po_no_subtotal)
    print(f"Verified: {no_sub_result['is_valid']}")
    print(f"Confidence Score: {no_sub_result['confidence_score']}%")
    print(f"Subtotal Verified: {no_sub_result['checks']['subtotal_verified']}")

    # Edge Case: Math Mismatch on Line 1 & Grand Total Mismatch
    mock_bad_po = {
        "purchase_order_number": "PO-ERR-001",
        "items": [
            {
                "description": "Defective Widget",
                "quantity": 10,
                "unit_price": 10.00,
                "discount": 5.00,
                "line_total": 100.00  # Should be 95.00
            }
        ],
        "subtotal": 100.00,
        "total": 120.00  # Calculated is 100.00, mismatch!
    }

    print("\n--- RUNNING SELF-TEST: MATH ERROR ---")
    bad_result = verify_purchase_order_math(mock_bad_po)
    print(f"Verified: {bad_result['is_valid']}")
    print(f"Confidence Score: {bad_result['confidence_score']}%")
    print(f"Discrepancies: {bad_result['discrepancies']}")

    # Test Payload without explicit subtotal AND without grand total (Full Points & No Flagging)
    mock_po_no_totals = {
        "purchase_order_number": "PO-NO-TOTALS",
        "items": [
            {"description": "Industrial Widget", "quantity": 10, "unit_price": 25.00, "line_total": None},
            {"description": "Metric Bolt Pack", "quantity": 5, "unit_price": 4.00, "line_total": None}
        ],
        "subtotal": None,
        "total": None
    }

    print("\n--- RUNNING SELF-TEST: NO TOTALS (FULL POINTS & NO FLAGGING) ---")
    no_totals_result = verify_purchase_order_math(mock_po_no_totals)
    print(f"Verified: {no_totals_result['is_valid']}")
    print(f"Confidence Score: {no_totals_result['confidence_score']}%")
    print(f"Discrepancies: {no_totals_result['discrepancies']}")

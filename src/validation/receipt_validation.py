import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# CONFIGURATION & GLOBAL CONSTANTS
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ReceiptVerifier")

TOLERANCE = Decimal("0.05")


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
def verify_receipt_line_items(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], Decimal, Decimal, int, int]:
    """
    Validates (quantity * unit_price) - discount == total for each receipt item.
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
        qty = to_decimal(item.get("quantity") or item.get("quantity_delivered"))
        unit_price = to_decimal(item.get("unit_price"))
        raw_discount = to_decimal(item.get("discount"))
        line_discount = abs(raw_discount) if raw_discount is not None else Decimal("0.00")
        line_total = to_decimal(item.get("total") or item.get("line_total") or item.get("total_price"))

        item_audit = {
            "index": idx,
            "item_code": item.get("item_code"),
            "description": item.get("description"),
            "quantity": qty,
            "unit_price": unit_price,
            "discount": line_discount,
            "reported_line_total": line_total,
            "calculated_line_total": None,
            "is_valid": None,
            "error_note": None,
            "discount_deducted": False
        }

        # Track total quantity if quantity exists
        if qty is not None:
            sum_quantities += qty

        if qty is not None and unit_price is not None:
            total_checks += 1
            gross_total = (qty * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            calculated_total = (gross_total - line_discount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            item_audit["calculated_line_total"] = calculated_total

            if line_total is not None:
                if is_close(calculated_total, line_total):
                    # Line total was already reported net of discount
                    checks_passed += 1
                    item_audit["is_valid"] = True
                    sum_line_totals += line_total
                    if line_discount > Decimal("0.00"):
                        item_audit["discount_deducted"] = True
                elif line_discount > Decimal("0.00") and is_close(gross_total, line_total):
                    # Line total was reported pre-discount; deduct discount to get net line total
                    checks_passed += 1
                    item_audit["is_valid"] = True
                    item_audit["error_note"] = f"Line discount applied: {line_total} - {line_discount} = {calculated_total}"
                    item_audit["discount_deducted"] = True
                    sum_line_totals += calculated_total
                elif line_discount > Decimal("0.00") and is_close(gross_total, line_total - line_discount):
                    # unit_price was reported as net unit price after discount: qty * unit_price == line_total - line_discount
                    checks_passed += 1
                    item_audit["is_valid"] = True
                    item_audit["calculated_line_total"] = gross_total
                    item_audit["error_note"] = f"Net unit price verified: {line_total} - {line_discount} = {gross_total}"
                    item_audit["discount_deducted"] = True
                    sum_line_totals += gross_total
                else:
                    item_audit["is_valid"] = False
                    item_audit["error_note"] = (
                        f"Line total discrepancy: calculated {calculated_total} vs reported {line_total}"
                    )
                    if line_discount > Decimal("0.00") and line_total >= gross_total:
                        effective_total = line_total - line_discount
                        item_audit["discount_deducted"] = True
                    else:
                        effective_total = line_total
                    sum_line_totals += effective_total
            else:
                # Inferred Line Check
                checks_passed += 1
                item_audit["is_valid"] = True
                item_audit["error_note"] = f"Line total inferred: {calculated_total}"
                sum_line_totals += calculated_total
                if line_discount > Decimal("0.00"):
                    item_audit["discount_deducted"] = True
        elif line_total is not None:
            if line_discount > Decimal("0.00"):
                effective_total = line_total - line_discount
                item_audit["discount_deducted"] = True
            else:
                effective_total = line_total
            sum_line_totals += effective_total
            item_audit["error_note"] = "Incomplete quantity or unit_price; line item math untestable"
        else:
            item_audit["error_note"] = "Missing pricing components on line item"

        audited_items.append(item_audit)

    return audited_items, sum_line_totals, sum_quantities, checks_passed, total_checks


def verify_receipt_math(receipt_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes end-to-end deterministic verification on receipt data.
    Computes a transparent confidence score (0-100) based on arithmetic integrity.
    """
    if hasattr(receipt_data, "model_dump"):
        receipt_data = receipt_data.model_dump(mode="json")
    elif not isinstance(receipt_data, dict):
        receipt_data = {}

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
        items = receipt_data.get("items") or receipt_data.get("lines") or []
        reported_total_qty = to_decimal(receipt_data.get("total_quantity"))
        subtotal = to_decimal(receipt_data.get("subtotal"))
        raw_doc_discount = to_decimal(receipt_data.get("discount_amount") or receipt_data.get("discount") or receipt_data.get("total_discount"))
        doc_discount = abs(raw_doc_discount) if raw_doc_discount is not None else Decimal("0.00")
        doc_tax = to_decimal(receipt_data.get("tax") or receipt_data.get("total_tax")) or Decimal("0.00")
        doc_shipping = to_decimal(receipt_data.get("shipping") or receipt_data.get("shipping_amount")) or Decimal("0.00")
        doc_service_charge = to_decimal(receipt_data.get("service_charge")) or Decimal("0.00")
        round_adj = to_decimal(receipt_data.get("rounding_adjustment") or receipt_data.get("round_adjustment")) or Decimal("0.00")
        grand_total = to_decimal(receipt_data.get("total") or receipt_data.get("total_amount") or receipt_data.get("grand_total"))

        # Score Weight Components (Max: 100)
        score = Decimal("0.0")

        sum_line_totals = Decimal("0.00")
        sum_quantities = Decimal("0.00")
        sum_item_discounts = Decimal("0.00")

        # 1. Line Item Verification (Up to 30 points)
        if items:
            audited_items, sum_line_totals, sum_quantities, items_passed, total_checks = verify_receipt_line_items(items)
            report["line_item_audit"] = audited_items
            sum_item_discounts = sum(
                (it.get("discount") or Decimal("0.00"))
                for it in audited_items
                if it.get("discount_deducted")
            )

            if total_checks > 0:
                pass_rate = Decimal(items_passed) / Decimal(total_checks)
                score += pass_rate * Decimal("30.0")
                if items_passed == total_checks:
                    report["checks"]["line_items_verified"] = True
                else:
                    report["discrepancies"].append(f"Failed {total_checks - items_passed}/{total_checks} line item math checks.")
            else:
                # Receipt has line items with quantities but no unit prices (standard delivery receipt / packing slip)
                score += Decimal("30.0")
                report["checks"]["line_items_verified"] = True
        else:
            if subtotal is not None and grand_total is not None and is_close(subtotal, grand_total):
                # Flat payment slip without itemized products (e.g. telecom/utility payment)
                score += Decimal("20.0")
                report["checks"]["line_items_verified"] = True
            else:
                report["discrepancies"].append("No line items found in receipt payload.")

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
            # Grant structural points if not required/reported
            score += Decimal("10.0")

        # 3. Subtotal & Grand Total Pre-computation with Dual-Tax Support
        effective_subtotal = subtotal if subtotal is not None else sum_line_totals

        # Discount Deduplication: If document discount summarizes line item discounts, don't deduct twice
        if sum_item_discounts > Decimal("0.00") and doc_discount > Decimal("0.00"):
            if is_close(doc_discount, sum_item_discounts) or doc_discount <= sum_item_discounts:
                effective_doc_discount = Decimal("0.00")
            else:
                effective_doc_discount = doc_discount - sum_item_discounts
        else:
            effective_doc_discount = doc_discount

        # Convention A: Tax-Exclusive (Additive Tax, e.g. US/Canada)
        calc_additive = (effective_subtotal - effective_doc_discount + doc_service_charge + doc_shipping + doc_tax + round_adj).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Convention B: Tax-Inclusive (Embedded Tax / Gross Pricing, e.g. Malaysia/Singapore/UK/EU)
        calc_inclusive = (effective_subtotal - effective_doc_discount + doc_service_charge + doc_shipping + round_adj).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Convention C: Pre-discount subtotal with global discount
        calc_pre_disc = (effective_subtotal - doc_discount + doc_service_charge + doc_shipping + doc_tax + round_adj).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Convention D: Tax Adjustment / Credit Note (e.g. returns where GST is credited)
        calc_tax_credit = (effective_subtotal - effective_doc_discount + doc_service_charge + doc_shipping - doc_tax + round_adj).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        grand_total_matches = False
        calculated_grand_total = calc_additive
        pricing_model = "tax_exclusive"

        if grand_total is not None:
            if is_close(calc_additive, grand_total):
                grand_total_matches = True
                calculated_grand_total = calc_additive
                pricing_model = "tax_exclusive"
            elif doc_tax > Decimal("0.00") and is_close(calc_inclusive, grand_total):
                grand_total_matches = True
                calculated_grand_total = calc_inclusive
                pricing_model = "tax_inclusive"
            elif doc_tax > Decimal("0.00") and is_close(calc_tax_credit, grand_total):
                grand_total_matches = True
                calculated_grand_total = calc_tax_credit
                pricing_model = "tax_adjustment"
            elif is_close(calc_pre_disc, grand_total):
                grand_total_matches = True
                calculated_grand_total = calc_pre_disc
                pricing_model = "tax_exclusive"
            else:
                # Direct sum of lines + service charge + round
                calc_direct = (sum_line_totals + doc_service_charge + round_adj).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if is_close(calc_direct, grand_total):
                    grand_total_matches = True
                    calculated_grand_total = calc_direct
                    pricing_model = "tax_inclusive"

        # 3. Subtotal Verification (Up to 30 points)
        if subtotal is not None:
            if is_close(sum_line_totals, subtotal):
                score += Decimal("30.0")
                report["checks"]["subtotal_verified"] = True
            elif doc_tax > Decimal("0.00") and is_close(sum_line_totals - doc_tax, subtotal):
                # Lines are tax-inclusive, while subtotal is pre-tax net
                score += Decimal("30.0")
                report["checks"]["subtotal_verified"] = True
            elif doc_discount > Decimal("0.00") and is_close(sum_line_totals - doc_discount, subtotal):
                # Subtotal already reflects document discount
                score += Decimal("30.0")
                report["checks"]["subtotal_verified"] = True
            elif len(items) == 0 and grand_total is not None and is_close(subtotal, grand_total):
                # Flat payment slip: subtotal matches grand total
                score += Decimal("30.0")
                report["checks"]["subtotal_verified"] = True
            elif grand_total is None and is_close(sum_line_totals + doc_service_charge + doc_tax + round_adj, subtotal):
                # Receipt used 'SUBTOTAL' label for the final grand total (e.g. Old Asia)
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
                # No grand total and no subtotal on receipt: infer cleanly from line items without flagging
                if items and (total_checks == 0 or items_passed == total_checks):
                    score += Decimal("30.0")
                    report["checks"]["subtotal_verified"] = True
                elif sum_line_totals > Decimal("0.00"):
                    score += Decimal("15.0")
                else:
                    report["discrepancies"].append("No line items or pricing available to determine subtotal.")

        # 4. Grand Total Verification (Up to 30 points)
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
            if subtotal is not None and is_close(sum_line_totals + doc_service_charge + doc_tax + round_adj, subtotal):
                # Subtotal was the final total
                score += Decimal("30.0")
                report["checks"]["grand_total_verified"] = True
                calculated_grand_total = subtotal
            else:
                # Receipt has no explicitly stated grand total: grant full points without flagging
                score += Decimal("30.0")
                report["checks"]["grand_total_verified"] = True

        # Record clean financial summary
        report["resolved_totals"] = {
            "sum_line_totals": float(sum_line_totals),
            "sum_quantities": float(sum_quantities),
            "reported_total_quantity": float(reported_total_qty) if reported_total_qty is not None else None,
            "reported_subtotal": float(subtotal) if subtotal is not None else None,
            "document_discount": float(doc_discount),
            "document_service_charge": float(doc_service_charge),
            "document_tax": float(doc_tax),
            "round_adjustment": float(round_adj),
            "calculated_grand_total": float(calculated_grand_total),
            "reported_grand_total": float(grand_total) if grand_total is not None else None,
            "pricing_model": pricing_model,
        }

        # Final Evaluation
        final_confidence = float(score.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
        report["confidence_score"] = final_confidence
        report["is_valid"] = final_confidence >= 70.0

        if not report["is_valid"]:
            logger.warning(
                f"Receipt math verification flagged issues (Score: {final_confidence}%). Discrepancies: {report['discrepancies']}"
            )
        else:
            logger.info(f"Receipt deterministic math verified cleanly (Score: {final_confidence}%).")

    except Exception as e:
        logger.error(f"Unexpected error during receipt deterministic verification: {e}", exc_info=True)
        report["discrepancies"].append(f"Verification runtime crash prevented: {str(e)}")
        report["confidence_score"] = 0.0
        report["is_valid"] = False

    return report


def verify_receipt_batch(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Validates a list of extracted receipt records in batch.
    Each record should contain 'extracted_data' (or be the receipt data dictionary itself).
    Adds or updates 'validation_report' on each record.
    """
    audited_records = []
    for record in records:
        rec_copy = dict(record)
        payload = rec_copy.get("extracted_data", rec_copy)
        val_report = verify_receipt_math(payload)
        rec_copy["validation_report"] = val_report
        audited_records.append(rec_copy)
    return audited_records


def print_receipt_batch_validation_summary(audited_records: List[Dict[str, Any]]) -> None:
    """
    Prints a formatted summary table of batch verification results for receipts.
    """
    total = len(audited_records)
    valid_count = sum(1 for r in audited_records if r.get("validation_report", {}).get("is_valid", False))
    flagged_count = total - valid_count

    separator = "=" * 80
    print(f"\n{separator}")
    print(f"RECEIPT BATCH VALIDATION SUMMARY: {valid_count}/{total} Valid ({flagged_count} Flagged)")
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
    # Test Payload with item discounts and tax
    mock_receipt_payload = {
        "vendor_name": "Metro Supermarket",
        "receipt_number": "REC-20260915-001",
        "items": [
            {
                "description": "Organic Milk 1L",
                "quantity": 2,
                "unit_price": 3.50,
                "discount": 0.50,
                "total": 6.50
            },
            {
                "description": "Whole Wheat Bread",
                "quantity": 1,
                "unit_price": 2.99,
                "discount": 0.00,
                "total": 2.99
            }
        ],
        "subtotal": 9.49,
        "discount_amount": 1.00,
        "tax": 0.68,
        "rounding_adjustment": -0.02,
        "total": 9.15
    }

    print("\n--- RUNNING SELF-TEST: VALID RECEIPT ---")
    result = verify_receipt_math(mock_receipt_payload)
    print(f"Verified: {result['is_valid']}")
    print(f"Confidence Score: {result['confidence_score']}%")
    if result['discrepancies']:
        print(f"Discrepancies: {result['discrepancies']}")

    # Test Payload without explicit subtotal row (reconciled through grand total)
    mock_receipt_no_subtotal = {
        "vendor_name": "Corner Cafe",
        "items": [
            {"description": "Latte", "quantity": 1, "unit_price": 4.50, "total": 4.50},
            {"description": "Croissant", "quantity": 2, "unit_price": 3.00, "total": 6.00}
        ],
        "subtotal": None,
        "tax": 0.84,
        "total": 11.34  # 10.50 + 0.84 = 11.34
    }

    print("\n--- RUNNING SELF-TEST: OMITTED SUBTOTAL RECONCILED ---")
    no_sub_result = verify_receipt_math(mock_receipt_no_subtotal)
    print(f"Verified: {no_sub_result['is_valid']}")
    print(f"Confidence Score: {no_sub_result['confidence_score']}%")
    print(f"Subtotal Verified: {no_sub_result['checks']['subtotal_verified']}")

    # Edge Case: Math Mismatch on Line 1 & Grand Total Mismatch
    mock_bad_receipt = {
        "vendor_name": "Quick Mart",
        "items": [
            {
                "description": "Energy Drink",
                "quantity": 3,
                "unit_price": 2.50,
                "total": 10.00  # Should be 7.50
            }
        ],
        "subtotal": 10.00,
        "total": 12.00  # Calculated is 10.00, mismatch!
    }

    print("\n--- RUNNING SELF-TEST: MATH ERROR ---")
    bad_result = verify_receipt_math(mock_bad_receipt)
    print(f"Verified: {bad_result['is_valid']}")
    print(f"Confidence Score: {bad_result['confidence_score']}%")
    print(f"Discrepancies: {bad_result['discrepancies']}")

    # Test Payload without explicit subtotal AND without grand total (Full Points & No Flagging)
    mock_receipt_no_totals = {
        "vendor_name": "Street Vendor",
        "items": [
            {"description": "Samosa", "quantity": 5, "unit_price": 0.50, "total": None},
            {"description": "Chai", "quantity": 2, "unit_price": 1.00, "total": None}
        ],
        "subtotal": None,
        "total": None
    }

    print("\n--- RUNNING SELF-TEST: NO TOTALS (FULL POINTS & NO FLAGGING) ---")
    no_totals_result = verify_receipt_math(mock_receipt_no_totals)
    print(f"Verified: {no_totals_result['is_valid']}")
    print(f"Confidence Score: {no_totals_result['confidence_score']}%")
    print(f"Discrepancies: {no_totals_result['discrepancies']}")


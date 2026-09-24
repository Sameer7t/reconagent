"""
Stage 5 — Financial Reconciliation.

Performs two levels of financial checks:
  Level 1 — Line Level:
    Sums validated line totals without duplicating internal arithmetic validation.
  Level 2 — Document Level (Semantic financial checks):
    Compares PO authorized subtotal vs Invoice subtotal (SUBTOTAL_MISMATCH),
    shipping charges (SHIPPING_EXCEEDS_PO), taxes (TAX_VARIANCE), discounts
    (DISCOUNT_NOT_APPLIED), and detects uncontracted surcharges (UNAUTHORIZED_CHARGE)
    rather than treating all monetary differences as simple TOTAL_MISMATCH.
"""
import logging
import sys
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    FinancialBreakdown,
    ReconciliationCheck,
    ReconciliationPolicy,
    Severity,
)

logger = logging.getLogger("FinancialReconciler")


def _to_decimal(val: Any) -> Optional[Decimal]:
    """Safely convert a value to Decimal, quantized to 0.01."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _zero(val: Optional[Decimal]) -> Decimal:
    """Return the given value if it is a Decimal, else Decimal('0.00')."""
    if val is not None and isinstance(val, Decimal):
        return val
    return Decimal("0.00")


def reconcile_financials(
    po_data: Dict[str, Any],
    invoice_data: Dict[str, Any],
    policy: Optional[ReconciliationPolicy] = None,
    receipt_data_list: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[ReconciliationCheck], List[Discrepancy], FinancialBreakdown]:
    """
    Perform financial reconciliation comparing a Purchase Order, Invoice, and optional Receipts.

    Returns:
        checks: List of ReconciliationCheck records for each financial category.
        discrepancies: List of Discrepancy objects detected.
        breakdown: Structured FinancialBreakdown object.
    """
    if policy is None:
        policy = ReconciliationPolicy()

    checks: List[ReconciliationCheck] = []
    discrepancies: List[Discrepancy] = []

    po_id = po_data.get("purchase_order_number") or po_data.get("id", "PO")
    inv_id = invoice_data.get("invoice_number") or invoice_data.get("id", "INV")
    doc_ids = [po_id, inv_id]

    # Level 1: Line sums
    po_items = po_data.get("items", [])
    po_line_total_sum = Decimal("0.00")
    for item in po_items:
        line_total = _to_decimal(item.get("line_total") or item.get("total"))
        po_line_total_sum += _zero(line_total)

    invoice_items = invoice_data.get("items", [])
    invoice_line_total_sum = Decimal("0.00")
    for item in invoice_items:
        line_total = _to_decimal(item.get("line_total") or item.get("total"))
        invoice_line_total_sum += _zero(line_total)

    # Document Level Values
    po_subtotal = _to_decimal(po_data.get("subtotal"))
    po_shipping = _to_decimal(po_data.get("shipping"))
    po_tax = _to_decimal(po_data.get("tax"))
    po_discount = _to_decimal(po_data.get("discount"))
    po_total = _to_decimal(po_data.get("total"))

    inv_subtotal = _to_decimal(invoice_data.get("subtotal"))
    inv_shipping = _to_decimal(invoice_data.get("shipping"))
    inv_tax = _to_decimal(invoice_data.get("total_tax") or invoice_data.get("tax"))
    inv_discount = _to_decimal(invoice_data.get("total_discount") or invoice_data.get("discount"))
    inv_total = _to_decimal(invoice_data.get("total"))

    # Effective values for comparison
    effective_po_sub = po_subtotal if po_subtotal is not None else po_line_total_sum
    effective_inv_sub = inv_subtotal if inv_subtotal is not None else invoice_line_total_sum

    # A. Subtotal Check
    subtotal_passed = True
    if effective_po_sub is not None and effective_inv_sub is not None:
        subtotal_diff = abs(effective_po_sub - effective_inv_sub)
        if subtotal_diff > policy.subtotal_tolerance:
            subtotal_passed = False
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.SUBTOTAL_MISMATCH,
                severity=Severity.HIGH,
                document_ids=doc_ids,
                expected_value=str(effective_po_sub),
                actual_value=str(effective_inv_sub),
                difference=subtotal_diff,
                explanation=f"Subtotal mismatch: PO authorized ${effective_po_sub}, Invoice billed ${effective_inv_sub} (diff: ${subtotal_diff}).",
            ))
        checks.append(ReconciliationCheck(
            check_name="subtotal_reconciliation",
            stage="financial",
            passed=subtotal_passed,
            details={
                "po_subtotal": float(effective_po_sub),
                "invoice_subtotal": float(effective_inv_sub),
                "difference": float(subtotal_diff),
            },
            message=f"Subtotal check {'PASSED' if subtotal_passed else 'FAILED'}: diff ${subtotal_diff}.",
        ))

    # B. Shipping Check
    po_ship_val = _zero(po_shipping)
    inv_ship_val = _zero(inv_shipping)
    shipping_passed = True
    if inv_ship_val > po_ship_val + policy.shipping_tolerance:
        shipping_passed = False
        ship_diff = inv_ship_val - po_ship_val
        discrepancies.append(Discrepancy(
            type=DiscrepancyType.SHIPPING_EXCEEDS_PO,
            severity=Severity.HIGH,
            document_ids=doc_ids,
            expected_value=str(po_ship_val),
            actual_value=str(inv_ship_val),
            difference=ship_diff,
            explanation=f"Invoice shipping (${inv_ship_val}) exceeds authorized PO shipping (${po_ship_val}) by ${ship_diff}.",
        ))
    checks.append(ReconciliationCheck(
        check_name="shipping_reconciliation",
        stage="financial",
        passed=shipping_passed,
        details={
            "po_shipping": float(po_ship_val),
            "invoice_shipping": float(inv_ship_val),
        },
        message=f"Shipping check {'PASSED' if shipping_passed else 'FAILED'}: PO ${po_ship_val} vs Invoice ${inv_ship_val}.",
    ))

    # C. Tax Check
    po_tax_val = _zero(po_tax)
    inv_tax_val = _zero(inv_tax)
    tax_diff = abs(po_tax_val - inv_tax_val)
    # Tax on invoice without PO tax is often normal in supply chains if PO excludes tax,
    # but if PO explicitly states tax and invoice differs beyond tolerance:
    tax_passed = True
    if po_tax is not None and tax_diff > policy.tax_tolerance:
        tax_passed = False
        discrepancies.append(Discrepancy(
            type=DiscrepancyType.TAX_VARIANCE,
            severity=Severity.MEDIUM,
            document_ids=doc_ids,
            expected_value=str(po_tax_val),
            actual_value=str(inv_tax_val),
            difference=tax_diff,
            explanation=f"Tax variance: PO specifies ${po_tax_val}, Invoice specifies ${inv_tax_val} (diff: ${tax_diff}).",
        ))
    checks.append(ReconciliationCheck(
        check_name="tax_reconciliation",
        stage="financial",
        passed=tax_passed,
        details={
            "po_tax": float(po_tax_val),
            "invoice_tax": float(inv_tax_val),
            "difference": float(tax_diff),
        },
        message=f"Tax check {'PASSED' if tax_passed else 'FAILED'}.",
    ))

    # D. Discount Check
    po_disc_val = _zero(po_discount)
    inv_disc_val = _zero(inv_discount)
    discount_passed = True
    if po_disc_val > Decimal("0.00") and inv_disc_val == Decimal("0.00"):
        discount_passed = False
        discrepancies.append(Discrepancy(
            type=DiscrepancyType.DISCOUNT_NOT_APPLIED,
            severity=Severity.MEDIUM,
            document_ids=doc_ids,
            expected_value=str(po_disc_val),
            actual_value=str(inv_disc_val),
            difference=po_disc_val,
            explanation=f"PO agreed discount of ${po_disc_val} was not applied on the invoice.",
        ))
    checks.append(ReconciliationCheck(
        check_name="discount_reconciliation",
        stage="financial",
        passed=discount_passed,
        details={
            "po_discount": float(po_disc_val),
            "invoice_discount": float(inv_disc_val),
        },
        message=f"Discount check {'PASSED' if discount_passed else 'FAILED'}.",
    ))

    # E. Unauthorized Charges Detection
    po_authorized = effective_po_sub - po_disc_val + po_ship_val + po_tax_val
    inv_authorized_components = effective_inv_sub - inv_disc_val + inv_ship_val + inv_tax_val
    unauthorized_charges_list = []

    # If invoice total exceeds the sum of its standard items/tax/shipping or exceeds PO authorized:
    effective_inv_total = inv_total if inv_total is not None else inv_authorized_components
    unauth_diff = effective_inv_total - po_authorized

    if unauth_diff > policy.total_tolerance and not policy.allow_unauthorized_charges:
        # Check whether the difference is specifically an unauthorized fee/surcharge
        severity = Severity.CRITICAL if unauth_diff > policy.critical_unauthorized_charge_threshold else Severity.HIGH
        unauthorized_charges_list.append({
            "charge_name": "Unapproved Surcharge / Total Variance",
            "amount": float(unauth_diff),
        })
        discrepancies.append(Discrepancy(
            type=DiscrepancyType.UNAUTHORIZED_CHARGE,
            severity=severity,
            document_ids=doc_ids,
            expected_value=str(po_authorized),
            actual_value=str(effective_inv_total),
            difference=unauth_diff,
            details={
                "charge_name": "Unapproved Surcharge",
                "amount": float(unauth_diff),
            },
            explanation=f"Invoice total (${effective_inv_total}) exceeds PO authorized total (${po_authorized}) by unauthorized charge of ${unauth_diff}.",
        ))
        checks.append(ReconciliationCheck(
            check_name="unauthorized_charges",
            stage="financial",
            passed=False,
            details={"authorized": float(po_authorized), "billed": float(effective_inv_total), "unauthorized": float(unauth_diff)},
            message=f"Unauthorized charges detected: ${unauth_diff} above authorized amount.",
        ))
    else:
        checks.append(ReconciliationCheck(
            check_name="unauthorized_charges",
            stage="financial",
            passed=True,
            details={"authorized": float(po_authorized), "billed": float(effective_inv_total)},
            message="No unauthorized charges detected.",
        ))

    # F. Grand Total Check
    grand_total_passed = True
    if po_total is not None and inv_total is not None:
        total_diff = abs(po_total - inv_total)
        # If PO total differs from invoice total, but already captured as unauthorized charge,
        # we still record the check
        if total_diff > policy.total_tolerance and not unauthorized_charges_list:
            grand_total_passed = False
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.TOTAL_MISMATCH,
                severity=Severity.HIGH,
                document_ids=doc_ids,
                expected_value=str(po_total),
                actual_value=str(inv_total),
                difference=total_diff,
                explanation=f"Grand total mismatch: PO total ${po_total} vs Invoice total ${inv_total} (diff: ${total_diff}).",
            ))
        checks.append(ReconciliationCheck(
            check_name="grand_total_reconciliation",
            stage="financial",
            passed=grand_total_passed and (len(unauthorized_charges_list) == 0),
            details={"po_total": float(po_total), "invoice_total": float(inv_total), "difference": float(total_diff)},
            message=f"Grand total comparison: PO ${po_total} vs Invoice ${inv_total}.",
        ))

    # Flexible Receipt Total Check: ONLY evaluated if receipt explicitly prints a monetary total
    receipt_subtotal: Optional[Decimal] = None
    receipt_total: Optional[Decimal] = None

    if receipt_data_list:
        for r in receipt_data_list:
            if not isinstance(r, dict):
                continue
            r_sub = _to_decimal(r.get("subtotal"))
            r_tot = _to_decimal(r.get("total") or r.get("grand_total") or r.get("amount_due") or r.get("total_sales"))
            if r_sub is not None:
                receipt_subtotal = (receipt_subtotal or Decimal("0.00")) + r_sub
            if r_tot is not None:
                receipt_total = (receipt_total or Decimal("0.00")) + r_tot

    if receipt_total is not None:
        # Flexible reconciliation: in commercial trade, a delivery receipt total may represent
        # either the merchandise subtotal (goods delivered) or the grand total (with freight/tax).
        candidate_expected_totals = [
            val for val in [po_total, inv_total, effective_po_sub, effective_inv_sub]
            if val is not None
        ]
        if candidate_expected_totals:
            diffs = [(abs(receipt_total - cand), cand) for cand in candidate_expected_totals]
            diffs.sort(key=lambda x: x[0])
            best_diff, best_cand = diffs[0]

            tol = max(policy.total_tolerance, policy.subtotal_tolerance)
            rcpt_total_passed = best_diff <= tol
            checks.append(ReconciliationCheck(
                check_name="receipt_total_reconciliation",
                stage="financial",
                passed=rcpt_total_passed,
                details={
                    "receipt_total": float(receipt_total),
                    "expected_target": float(best_cand),
                    "difference": float(best_diff),
                },
                message=(
                    f"Receipt total (${receipt_total}) reconciles with document amount (${best_cand})."
                    if rcpt_total_passed
                    else f"Receipt total (${receipt_total}) differs from expected document amounts (closest: ${best_cand}, diff: ${best_diff})."
                ),
            ))
            if not rcpt_total_passed:
                rcpt_ids = [str(r.get("receipt_number")) for r in (receipt_data_list or []) if isinstance(r, dict) and r.get("receipt_number")]
                discrepancies.append(Discrepancy(
                    type=DiscrepancyType.RECEIPT_TOTAL_MISMATCH,
                    severity=Severity.HIGH if best_diff > policy.high_price_difference_threshold else Severity.MEDIUM,
                    document_ids=rcpt_ids or ["RECEIPT"],
                    expected_value=str(best_cand),
                    actual_value=str(receipt_total),
                    difference=best_diff,
                    explanation=f"Receipt total amount (${receipt_total}) does not reconcile with document authorized total (${best_cand}, variance: ${best_diff}).",
                ))

    breakdown = FinancialBreakdown(
        po_subtotal=effective_po_sub,
        invoice_subtotal=effective_inv_sub,
        receipt_subtotal=receipt_subtotal,
        po_shipping=po_shipping,
        invoice_shipping=inv_shipping,
        po_tax=po_tax,
        invoice_tax=inv_tax,
        po_discount=po_discount,
        invoice_discount=inv_discount,
        po_total=po_total,
        invoice_total=inv_total,
        receipt_total=receipt_total,
        unauthorized_charges=unauthorized_charges_list,
    )

    return checks, discrepancies, breakdown

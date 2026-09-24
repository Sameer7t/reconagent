"""
Stage 3 — Quantity Reconciliation.

Compares ordered (PO), invoiced (Invoice), and received (Receipt) quantities
for each matched line item. Supports partial deliveries by aggregating
quantities across multiple receipts.

Emits directional discrepancies rather than generic QUANTITY_MISMATCH:
  - INVOICE_QUANTITY_EXCEEDS_PO
  - INVOICE_QUANTITY_EXCEEDS_RECEIPT / INVOICE_QUANTITY_EXCEEDS_RECEIVED
  - PO_QUANTITY_EXCEEDS_INVOICE
  - RECEIVED_QUANTITY_EXCEEDS_PO
"""
import logging
import sys
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    LineItemMatch,
    ReconciliationCheck,
    ReconciliationPolicy,
    Severity,
)

logger = logging.getLogger("QuantityReconciler")


# ============================================================
# UTILITIES
# ============================================================

def _to_decimal(val: Any) -> Optional[Decimal]:
    """Safely convert a value to Decimal, returning None on failure."""
    if val is None:
        return None
    try:
        return Decimal(str(val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        return None


def _pct(difference: Decimal, base: Decimal) -> Optional[Decimal]:
    """Calculate percentage difference relative to base."""
    if base is None or base == Decimal("0"):
        return None
    return (abs(difference) / abs(base) * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


# ============================================================
# QUANTITY RECONCILIATION
# ============================================================

def reconcile_quantities(
    matches: List[LineItemMatch],
    policy: Optional[ReconciliationPolicy] = None,
) -> Tuple[List[ReconciliationCheck], List[Discrepancy], List[LineItemMatch]]:
    """
    Perform 3-way quantity reconciliation on matched line items.

    For each LineItemMatch, compares:
        ordered_quantity (PO) vs invoiced_quantity (Invoice) vs received_quantity (Receipts)

    Returns:
        checks: List of per-item ReconciliationCheck results.
        discrepancies: List of quantity Discrepancy objects.
        updated_matches: The input matches with quantity fields populated.
    """
    if policy is None:
        policy = ReconciliationPolicy()

    checks: List[ReconciliationCheck] = []
    discrepancies: List[Discrepancy] = []
    tolerance = policy.quantity_tolerance

    for match in matches:
        # Skip unmatched items (they already have their own discrepancy)
        if match.match_method.value == "UNMATCHED":
            continue

        ordered = _to_decimal(match.ordered_quantity)
        invoiced = _to_decimal(match.invoiced_quantity)
        received = _to_decimal(match.received_quantity)

        item_desc = ""
        if match.po_item:
            item_desc = match.po_item.get("description", "")
        elif match.invoice_item:
            item_desc = match.invoice_item.get("description", "")

        po_line = match.po_line_id or "unknown"
        inv_line = match.invoice_line_id or "unknown"

        doc_ids = []
        if match.po_line_id:
            po_doc = match.po_line_id.rsplit("-L", 1)[0] if "-L" in (match.po_line_id or "") else match.po_line_id
            doc_ids.append(po_doc)
        if match.invoice_line_id:
            inv_doc = match.invoice_line_id.rsplit("-L", 1)[0] if "-L" in (match.invoice_line_id or "") else match.invoice_line_id
            doc_ids.append(inv_doc)

        item_passed = True
        item_details: Dict[str, Any] = {
            "item": item_desc,
            "ordered": float(ordered) if ordered else None,
            "invoiced": float(invoiced) if invoiced else None,
            "received": float(received) if received else None,
        }

        # --- Check 1: Invoice vs PO ---
        if ordered is not None and invoiced is not None:
            diff = invoiced - ordered
            if abs(diff) > tolerance:
                item_passed = False
                if diff > Decimal("0"):
                    # Invoice bills MORE than PO authorized
                    discrepancies.append(Discrepancy(
                        type=DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_PO,
                        severity=Severity.HIGH,
                        document_ids=doc_ids,
                        po_line_id=po_line,
                        invoice_line_id=inv_line,
                        expected_value=str(ordered),
                        actual_value=str(invoiced),
                        difference=diff,
                        difference_percent=_pct(diff, ordered),
                        explanation=(
                            f"Invoice quantity ({invoiced}) exceeds PO quantity "
                            f"({ordered}) for '{item_desc}' by {diff} units."
                        ),
                    ))
                else:
                    # PO ordered more than invoice bills (partial billing)
                    discrepancies.append(Discrepancy(
                        type=DiscrepancyType.PO_QUANTITY_EXCEEDS_INVOICE,
                        severity=Severity.LOW,
                        document_ids=doc_ids,
                        po_line_id=po_line,
                        invoice_line_id=inv_line,
                        expected_value=str(ordered),
                        actual_value=str(invoiced),
                        difference=abs(diff),
                        difference_percent=_pct(diff, ordered),
                        explanation=(
                            f"PO quantity ({ordered}) exceeds invoice quantity "
                            f"({invoiced}) for '{item_desc}'. Possible partial billing."
                        ),
                    ))

        # --- Check 2: Invoice vs Received ---
        if invoiced is not None and received is not None:
            diff = invoiced - received
            if abs(diff) > tolerance:
                item_passed = False
                if diff > Decimal("0"):
                    # Billing for more than received
                    discrepancies.append(Discrepancy(
                        type=DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_RECEIVED,
                        severity=Severity.MEDIUM,
                        document_ids=doc_ids,
                        po_line_id=po_line,
                        invoice_line_id=inv_line,
                        expected_value=str(received),
                        actual_value=str(invoiced),
                        difference=diff,
                        difference_percent=_pct(diff, received),
                        explanation=(
                            f"Invoice quantity ({invoiced}) exceeds received "
                            f"quantity ({received}) for '{item_desc}'. "
                            f"Billing for {diff} undelivered units."
                        ),
                    ))

        # --- Check 3: Received vs PO ---
        if ordered is not None and received is not None:
            diff = received - ordered
            if abs(diff) > tolerance and diff > Decimal("0"):
                # Over-delivery
                discrepancies.append(Discrepancy(
                    type=DiscrepancyType.RECEIVED_QUANTITY_EXCEEDS_PO,
                    severity=Severity.MEDIUM,
                    document_ids=doc_ids,
                    po_line_id=po_line,
                    expected_value=str(ordered),
                    actual_value=str(received),
                    difference=diff,
                    difference_percent=_pct(diff, ordered),
                    explanation=(
                        f"Received quantity ({received}) exceeds PO quantity "
                        f"({ordered}) for '{item_desc}'. Over-delivery of {diff} units."
                    ),
                ))

        checks.append(ReconciliationCheck(
            check_name=f"quantity_{po_line}",
            stage="quantity",
            passed=item_passed,
            details=item_details,
            message=(
                f"Quantity check {'PASSED' if item_passed else 'FAILED'} "
                f"for '{item_desc}'."
            ),
        ))

    logger.info(
        f"Quantity reconciliation: {sum(1 for c in checks if c.passed)}/{len(checks)} "
        f"items passed, {len(discrepancies)} discrepancies found."
    )
    return checks, discrepancies, matches


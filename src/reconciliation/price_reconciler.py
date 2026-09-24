"""
Stage 4 — Price Reconciliation.

Validates unit price adherence for each matched line item by comparing
the contracted PO unit price against the invoiced unit price.

Uses configurable ReconciliationPolicy tolerances (both absolute and
percentage-based) with strict Decimal arithmetic. Emits UNIT_PRICE_MISMATCH
discrepancies with full expected/actual/difference/percentage payloads.
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

logger = logging.getLogger("PriceReconciler")


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


def _pct_diff(difference: Decimal, base: Decimal) -> Optional[Decimal]:
    """Calculate percentage difference relative to base value."""
    if base is None or base == Decimal("0"):
        return None
    return (abs(difference) / abs(base) * Decimal("100")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def _assign_price_severity(
    abs_diff: Decimal,
    pct_diff: Optional[Decimal],
    policy: ReconciliationPolicy,
) -> Severity:
    """
    Assign severity to a price discrepancy using deterministic rules.

    Rules (Step 27):
      - abs_diff > policy.high_price_difference_threshold OR
        pct_diff > policy.high_price_percentage_threshold -> HIGH
      - Otherwise -> MEDIUM
      - Very small differences -> LOW
    """
    if abs_diff > policy.high_price_difference_threshold:
        return Severity.HIGH
    if pct_diff is not None and pct_diff > policy.high_price_percentage_threshold:
        return Severity.HIGH
    if abs_diff <= Decimal("1.00"):
        return Severity.LOW
    return Severity.MEDIUM


# ============================================================
# PRICE RECONCILIATION
# ============================================================

def reconcile_prices(
    matches: List[LineItemMatch],
    policy: Optional[ReconciliationPolicy] = None,
) -> Tuple[List[ReconciliationCheck], List[Discrepancy], List[LineItemMatch]]:
    """
    Validate unit prices for each matched line item.

    Compares PO unit price (expected/contracted) against Invoice unit price
    (actual/billed). Uses policy tolerances to determine if the variance is
    acceptable.

    Returns:
        checks: List of per-item ReconciliationCheck results.
        discrepancies: List of price Discrepancy objects.
        updated_matches: Input matches with price_difference fields populated.
    """
    if policy is None:
        policy = ReconciliationPolicy()

    checks: List[ReconciliationCheck] = []
    discrepancies: List[Discrepancy] = []

    abs_tolerance = policy.price_tolerance
    pct_tolerance = policy.price_percentage_tolerance

    for match in matches:
        # Skip unmatched items
        if match.match_method.value == "UNMATCHED":
            continue

        po_price = _to_decimal(match.ordered_unit_price)
        inv_price = _to_decimal(match.invoiced_unit_price)

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

        # If either price is missing, we cannot compare
        if po_price is None or inv_price is None:
            checks.append(ReconciliationCheck(
                check_name=f"price_{po_line}",
                stage="price",
                passed=True,
                details={
                    "item": item_desc,
                    "po_unit_price": float(po_price) if po_price else None,
                    "invoice_unit_price": float(inv_price) if inv_price else None,
                    "skipped": True,
                },
                message=(
                    f"Price check skipped for '{item_desc}': "
                    f"missing PO or Invoice unit price."
                ),
            ))
            continue

        # Calculate variance
        abs_diff = abs(inv_price - po_price)
        pct_diff = _pct_diff(inv_price - po_price, po_price)

        # Populate match fields
        match.price_difference = inv_price - po_price
        match.price_difference_percent = pct_diff

        # Determine if within tolerance
        within_abs = abs_diff <= abs_tolerance
        if pct_tolerance > Decimal("0") and pct_diff is not None:
            within_pct = pct_diff <= pct_tolerance
            item_passed = within_abs or within_pct
        else:
            item_passed = within_abs

        check_details: Dict[str, Any] = {
            "item": item_desc,
            "po_unit_price": float(po_price),
            "invoice_unit_price": float(inv_price),
            "difference": float(abs_diff),
            "difference_percent": float(pct_diff) if pct_diff else None,
            "within_tolerance": item_passed,
        }

        if not item_passed:
            severity = _assign_price_severity(abs_diff, pct_diff, policy)
            discrepancies.append(Discrepancy(
                type=DiscrepancyType.UNIT_PRICE_MISMATCH,
                severity=severity,
                document_ids=doc_ids,
                po_line_id=po_line,
                invoice_line_id=inv_line,
                expected_value=str(po_price),
                actual_value=str(inv_price),
                difference=abs_diff,
                difference_percent=pct_diff,
                details={
                    "expected": float(po_price),
                    "actual": float(inv_price),
                    "difference": float(abs_diff),
                    "difference_percent": float(pct_diff) if pct_diff else None,
                },
                explanation=(
                    f"Unit price mismatch for '{item_desc}': PO price "
                    f"${po_price} vs Invoice price ${inv_price} "
                    f"(difference: ${abs_diff}, {pct_diff}%)."
                ),
            ))

        checks.append(ReconciliationCheck(
            check_name=f"price_{po_line}",
            stage="price",
            passed=item_passed,
            details=check_details,
            message=(
                f"Price check {'PASSED' if item_passed else 'FAILED'} "
                f"for '{item_desc}': PO ${po_price} vs Invoice ${inv_price}."
            ),
        ))

    logger.info(
        f"Price reconciliation: {sum(1 for c in checks if c.passed)}/{len(checks)} "
        f"items passed, {len(discrepancies)} discrepancies found."
    )
    return checks, discrepancies, matches


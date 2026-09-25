"""
Rule-Based Discrepancy Engine.

Assigns severity to discrepancies using deterministic business rules
rather than LLM inference. The exact thresholds are configured via
ReconciliationPolicy.

Rules (from Step 27):
  - DUPLICATE_INVOICE, VENDOR_MISMATCH, DOCUMENT_LINK_MISMATCH,
    CURRENCY_MISMATCH -> CRITICAL
  - UNAUTHORIZED_CHARGE (> threshold) -> CRITICAL, else HIGH
  - UNIT_PRICE_MISMATCH (> 10% or > $100) -> HIGH, else MEDIUM/LOW
  - INVOICE_QUANTITY_EXCEEDS_RECEIVED -> MEDIUM (review, not fraud)
  - MISSING_DOCUMENT -> MEDIUM
"""
import logging
import sys
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    ReconciliationPolicy,
    Severity,
)

logger = logging.getLogger("DiscrepancyEngine")

# Discrepancy types that are always CRITICAL regardless of amount
ALWAYS_CRITICAL = frozenset({
    DiscrepancyType.DUPLICATE_INVOICE,
    DiscrepancyType.VENDOR_MISMATCH,
    DiscrepancyType.DOCUMENT_LINK_MISMATCH,
    DiscrepancyType.CURRENCY_MISMATCH,
})


def assign_severity(
    discrepancy: Discrepancy,
    policy: Optional[ReconciliationPolicy] = None,
) -> Discrepancy:
    """
    Assign or reassign severity to a discrepancy using deterministic rules.

    This function enforces consistent severity assignment across the entire
    reconciliation engine. It is the single source of truth for severity.
    """
    if policy is None:
        policy = ReconciliationPolicy()

    dtype = discrepancy.type

    # --- Always CRITICAL ---
    if dtype in ALWAYS_CRITICAL:
        discrepancy.severity = Severity.CRITICAL
        return discrepancy

    # --- UNAUTHORIZED_CHARGE ---
    if dtype == DiscrepancyType.UNAUTHORIZED_CHARGE:
        amount = discrepancy.difference or Decimal("0")
        if amount > policy.critical_unauthorized_charge_threshold:
            discrepancy.severity = Severity.CRITICAL
        else:
            discrepancy.severity = Severity.HIGH
        return discrepancy

    # --- UNIT_PRICE_MISMATCH ---
    if dtype == DiscrepancyType.UNIT_PRICE_MISMATCH:
        abs_diff = discrepancy.difference or Decimal("0")
        pct_diff = discrepancy.difference_percent or Decimal("0")
        if abs_diff > policy.high_price_difference_threshold:
            discrepancy.severity = Severity.HIGH
        elif pct_diff > policy.high_price_percentage_threshold:
            discrepancy.severity = Severity.HIGH
        elif abs_diff <= Decimal("1.00"):
            discrepancy.severity = Severity.LOW
        else:
            discrepancy.severity = Severity.MEDIUM
        return discrepancy

    # --- Quantity discrepancies ---
    if dtype == DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_PO:
        discrepancy.severity = Severity.HIGH
        return discrepancy

    if dtype in (
        DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_RECEIPT,
        DiscrepancyType.INVOICE_QUANTITY_EXCEEDS_RECEIVED,
    ):
        discrepancy.severity = Severity.MEDIUM
        return discrepancy

    if dtype == DiscrepancyType.PO_QUANTITY_EXCEEDS_INVOICE:
        discrepancy.severity = Severity.LOW
        return discrepancy

    if dtype == DiscrepancyType.RECEIVED_QUANTITY_EXCEEDS_PO:
        discrepancy.severity = Severity.MEDIUM
        return discrepancy

    # --- Financial discrepancies ---
    if dtype == DiscrepancyType.SHIPPING_EXCEEDS_PO:
        discrepancy.severity = Severity.HIGH
        return discrepancy

    if dtype == DiscrepancyType.SUBTOTAL_MISMATCH:
        discrepancy.severity = Severity.HIGH
        return discrepancy

    if dtype == DiscrepancyType.TAX_VARIANCE:
        discrepancy.severity = Severity.MEDIUM
        return discrepancy

    if dtype == DiscrepancyType.DISCOUNT_NOT_APPLIED:
        discrepancy.severity = Severity.MEDIUM
        return discrepancy

    if dtype == DiscrepancyType.TOTAL_MISMATCH:
        discrepancy.severity = Severity.HIGH
        return discrepancy

    # --- Receipt ---
    if dtype == DiscrepancyType.RECEIPT_SHORTAGE:
        discrepancy.severity = Severity.MEDIUM
        return discrepancy

    if dtype == DiscrepancyType.RECEIPT_PRICE_MISMATCH:
        abs_diff = discrepancy.difference or Decimal("0")
        pct_diff = discrepancy.difference_percent or Decimal("0")
        if abs_diff > policy.high_price_difference_threshold or pct_diff > policy.high_price_percentage_threshold:
            discrepancy.severity = Severity.HIGH
        elif abs_diff <= Decimal("1.00"):
            discrepancy.severity = Severity.LOW
        else:
            discrepancy.severity = Severity.HIGH
        return discrepancy

    if dtype == DiscrepancyType.RECEIPT_TOTAL_MISMATCH:
        discrepancy.severity = Severity.HIGH
        return discrepancy

    # --- Internal Document Validation Errors ---
    if dtype in (DiscrepancyType.CALCULATION_ERROR, DiscrepancyType.INTERNAL_MATH_ERROR):
        discrepancy.severity = Severity.HIGH
        return discrepancy

    # --- Missing document ---
    if dtype == DiscrepancyType.MISSING_DOCUMENT:
        discrepancy.severity = Severity.MEDIUM
        return discrepancy

    # --- Unmatched item & Description / Specification Mismatches ---
    if dtype in (
        DiscrepancyType.UNMATCHED_ITEM,
        DiscrepancyType.SPECIFICATION_MISMATCH,
        DiscrepancyType.DESCRIPTION_MISMATCH,
    ):
        discrepancy.severity = Severity.HIGH
        return discrepancy

    # --- Default ---
    discrepancy.severity = Severity.MEDIUM
    return discrepancy


def enforce_severities(
    discrepancies: List[Discrepancy],
    policy: Optional[ReconciliationPolicy] = None,
) -> List[Discrepancy]:
    """
    Apply deterministic severity rules to a list of discrepancies.

    This is the final pass that ensures all discrepancies have
    consistently assigned severities based on business rules.
    """
    if policy is None:
        policy = ReconciliationPolicy()

    for d in discrepancies:
        assign_severity(d, policy)

    severity_counts = {}
    for d in discrepancies:
        severity_counts[d.severity.value] = severity_counts.get(d.severity.value, 0) + 1

    logger.info(
        f"Discrepancy engine processed {len(discrepancies)} discrepancies. "
        f"Severity distribution: {severity_counts}"
    )
    return discrepancies


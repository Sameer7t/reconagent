"""
Final Decision Engine.

After all reconciliation stages have run and discrepancies have been
severity-assigned, determines the overall ReconciliationStatus:

    MATCHED                  -> Zero discrepancies, all documents present
    MATCHED_WITH_TOLERANCE   -> Only tolerance-level variances (LOW severity)
    REVIEW_REQUIRED          -> HIGH or CRITICAL discrepancies detected
    INCOMPLETE               -> Required documents missing
    UNMATCHED                -> Documents could not be linked with confidence
    ERROR                    -> Runtime/extraction failure
"""
import logging
import sys
from pathlib import Path
from typing import List, Optional

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    Discrepancy,
    ReconciliationResult,
    ReconciliationStatus,
    Severity,
)

logger = logging.getLogger("DecisionEngine")


def determine_status(
    discrepancies: List[Discrepancy],
    missing_documents: List[str],
    linked: bool = True,
    error_occurred: bool = False,
) -> ReconciliationStatus:
    """
    Apply deterministic rules to determine the final reconciliation status.

    Priority order (highest to lowest):
      1. ERROR           -> extraction/runtime failure
      2. UNMATCHED       -> documents couldn't be linked
      3. INCOMPLETE      -> required documents missing
      4. REVIEW_REQUIRED -> CRITICAL or HIGH severity discrepancies
      5. MATCHED_WITH_TOLERANCE -> only LOW/MEDIUM discrepancies
      6. MATCHED         -> clean reconciliation
    """
    if error_occurred:
        return ReconciliationStatus.ERROR

    if not linked:
        return ReconciliationStatus.UNMATCHED

    has_critical = any(d.severity == Severity.CRITICAL for d in discrepancies)
    has_high = any(d.severity == Severity.HIGH for d in discrepancies)

    if has_critical or has_high:
        return ReconciliationStatus.REVIEW_REQUIRED

    if missing_documents:
        return ReconciliationStatus.INCOMPLETE

    has_medium = any(d.severity == Severity.MEDIUM for d in discrepancies)
    has_low = any(d.severity == Severity.LOW for d in discrepancies)

    if has_medium or has_low:
        return ReconciliationStatus.MATCHED_WITH_TOLERANCE

    return ReconciliationStatus.MATCHED


def finalize_result(result: ReconciliationResult) -> ReconciliationResult:
    """
    Apply the decision engine to a ReconciliationResult and set its final status.

    Also generates a human-readable summary.
    """
    linked = True
    if result.document_linking:
        linked = result.document_linking.linked

    status = determine_status(
        discrepancies=result.discrepancies,
        missing_documents=result.missing_documents,
        linked=linked,
        error_occurred=(result.status == ReconciliationStatus.ERROR),
    )
    result.status = status

    # Generate summary
    result.summary = _build_summary(result)

    logger.info(f"Case {result.case_id}: Final status = {status.value}")
    return result


def _build_summary(result: ReconciliationResult) -> str:
    """Build a human-readable summary of the reconciliation outcome."""
    lines = [f"Reconciliation Case {result.case_id}"]
    lines.append(f"Status: {result.status.value}")

    if result.purchase_order_id:
        lines.append(f"PO: {result.purchase_order_id}")
    if result.invoice_id:
        lines.append(f"Invoice: {result.invoice_id}")
    if result.receipt_ids:
        lines.append(f"Receipts: {', '.join(result.receipt_ids)}")

    if result.missing_documents:
        lines.append(f"Missing Documents: {', '.join(result.missing_documents)}")

    if result.discrepancies:
        severity_counts = result.discrepancy_count_by_severity()
        lines.append(f"\nDiscrepancies: {len(result.discrepancies)}")
        for sev, count in sorted(severity_counts.items()):
            lines.append(f"  {sev}: {count}")

        lines.append("\nDetails:")
        for i, d in enumerate(result.discrepancies, 1):
            lines.append(
                f"  {i}. [{d.severity.value}] {d.type.value}: "
                f"{d.explanation or 'No explanation'}"
            )
    else:
        lines.append("\nAll checks passed. No discrepancies found.")

    # Stage summary
    stage_counts = {
        "Header": len(result.header_checks),
        "Line-Item": len(result.line_item_matches),
        "Quantity": len(result.quantity_checks),
        "Price": len(result.price_checks),
        "Financial": len(result.financial_checks),
        "Receipt": len(result.receipt_checks),
    }
    active_stages = {k: v for k, v in stage_counts.items() if v > 0}
    if active_stages:
        lines.append(f"\nStages Executed: {', '.join(active_stages.keys())}")

    return "\n".join(lines)


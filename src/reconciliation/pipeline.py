"""
Reconciliation Pipeline Orchestrator.

Coordinates all reconciliation stages in sequence on a set of
validated documents, producing a complete ReconciliationResult.

Stage execution order:
  1. Document Linking
  2. Header Reconciliation (Vendor, PO Ref, Currency)
  3. Line-Item Matching
  4. Quantity Reconciliation
  5. Price Reconciliation
  6. Financial Reconciliation
  7. Receipt Reconciliation
  8. Duplicate Detection
  9. Discrepancy Engine (severity enforcement)
  10. Decision Engine (final status)
"""
import logging
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional

SRC_ROOT = Path(__file__).resolve().parent.parent
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from schemas.reconciliation import (
    Discrepancy,
    DiscrepancyType,
    ReconciliationCheck,
    ReconciliationPolicy,
    ReconciliationResult,
    ReconciliationStatus,
    DocumentLinkResult,
    Severity,
)
from validation import (
    verify_invoice_math,
    verify_purchase_order_math,
    verify_receipt_math,
)

from reconciliation.document_linker import (
    evaluate_link,
    detect_missing_documents,
)
from reconciliation.header_reconciler import reconcile_headers
from reconciliation.line_item_matcher import (
    match_line_items,
    match_receipt_items_to_matches,
)
from reconciliation.quantity_reconciler import reconcile_quantities
from reconciliation.price_reconciler import reconcile_prices
from reconciliation.financial_reconciler import reconcile_financials
from reconciliation.receipt_reconciler import reconcile_receipts
from reconciliation.duplicate_detector import DuplicateDetector
from reconciliation.discrepancy_engine import enforce_severities
from reconciliation.decision_engine import finalize_result

logger = logging.getLogger("ReconciliationPipeline")

# Global duplicate detector instance
_duplicate_detector: Optional[DuplicateDetector] = None


def _get_duplicate_detector() -> DuplicateDetector:
    """Get or create the global duplicate detector instance."""
    global _duplicate_detector
    if _duplicate_detector is None:
        _duplicate_detector = DuplicateDetector()
    return _duplicate_detector


def _generate_case_id(counter: int = 0) -> str:
    """Generate a unique case ID."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"REC-{timestamp}-{counter:04d}"


def reconcile_transaction(
    po_data: Optional[Dict[str, Any]] = None,
    invoice_data: Optional[Dict[str, Any]] = None,
    receipt_data_list: Optional[List[Dict[str, Any]]] = None,
    case_id: Optional[str] = None,
    policy: Optional[ReconciliationPolicy] = None,
    check_duplicates: bool = True,
) -> ReconciliationResult:
    """
    Run the full reconciliation pipeline on a set of validated documents.

    Args:
        po_data: Validated PurchaseOrder data as a dictionary.
        invoice_data: Validated Invoice data as a dictionary.
        receipt_data_list: List of validated Receipt data dictionaries.
        case_id: Optional case ID. Auto-generated if not provided.
        policy: Reconciliation policy with tolerances. Uses defaults if not provided.
        check_duplicates: Whether to check for duplicate invoices.

    Returns:
        ReconciliationResult with all stage results, discrepancies, and final status.
    """
    if policy is None:
        policy = ReconciliationPolicy()
    if receipt_data_list is None:
        receipt_data_list = []
    if case_id is None:
        case_id = _generate_case_id()

    logger.info(f"=== Starting Reconciliation: {case_id} ===")

    # Initialize result
    result = ReconciliationResult(
        case_id=case_id,
        status=ReconciliationStatus.MATCHED,  # Will be overridden by decision engine
        invoice_id=_extract_id(invoice_data, "invoice_number"),
        purchase_order_id=_extract_id(po_data, "purchase_order_number"),
        receipt_ids=[
            _extract_id(r, "receipt_number") or f"RECEIPT-{i+1}"
            for i, r in enumerate(receipt_data_list)
        ],
    )

    all_discrepancies = []

    try:
        # ── Stage 0: Internal Document Validation ──────────────────
        logger.info(f"[{case_id}] Stage 0: Internal Document Validation")
        val_checks: List[ReconciliationCheck] = []

        # 0.1 Purchase Order Internal Validation
        if po_data:
            po_id = result.purchase_order_id or "PO"
            po_val = verify_purchase_order_math(po_data)
            po_discs = po_val.get("discrepancies", [])
            po_passed = po_val.get("is_valid", True) and len(po_discs) == 0
            val_checks.append(
                ReconciliationCheck(
                    stage="DOCUMENT_VALIDATION",
                    check_name="po_internal_validation",
                    passed=po_passed,
                    details=po_val,
                    message="PO internal math and integrity verified." if po_passed else f"PO math issues: {'; '.join(po_discs)}",
                )
            )
            for d_msg in po_discs:
                all_discrepancies.append(
                    Discrepancy(
                        type=DiscrepancyType.CALCULATION_ERROR,
                        severity=Severity.HIGH,
                        document_ids=[po_id],
                        explanation=f"Purchase Order {po_id} internal math discrepancy: {d_msg}",
                        details=po_val,
                    )
                )

        # 0.2 Invoice Internal Validation
        if invoice_data:
            inv_id = result.invoice_id or "INV"
            inv_val = verify_invoice_math(invoice_data)
            inv_discs = inv_val.get("discrepancies", [])
            inv_passed = inv_val.get("is_valid", True) and len(inv_discs) == 0
            val_checks.append(
                ReconciliationCheck(
                    stage="DOCUMENT_VALIDATION",
                    check_name="invoice_internal_validation",
                    passed=inv_passed,
                    details=inv_val,
                    message="Invoice internal math and integrity verified." if inv_passed else f"Invoice math issues: {'; '.join(inv_discs)}",
                )
            )
            for d_msg in inv_discs:
                all_discrepancies.append(
                    Discrepancy(
                        type=DiscrepancyType.CALCULATION_ERROR,
                        severity=Severity.HIGH,
                        document_ids=[inv_id],
                        explanation=f"Invoice {inv_id} internal math discrepancy: {d_msg}",
                        details=inv_val,
                    )
                )

        # 0.3 Receipt Internal Validation
        if receipt_data_list:
            for idx, r_data in enumerate(receipt_data_list):
                r_id = result.receipt_ids[idx] if idx < len(result.receipt_ids) else f"RECEIPT-{idx+1}"
                rcpt_val = verify_receipt_math(r_data)
                rcpt_discs = rcpt_val.get("discrepancies", [])
                # For delivery receipts with only quantities, ignore insufficient price variables note
                filtered_rcpt_discs = [
                    d for d in rcpt_discs
                    if not ("Line item variables insufficient" in d and r_data.get("items"))
                ]
                rcpt_passed = rcpt_val.get("is_valid", True) and len(filtered_rcpt_discs) == 0
                val_checks.append(
                    ReconciliationCheck(
                        stage="DOCUMENT_VALIDATION",
                        check_name=f"receipt_{idx+1}_internal_validation",
                        passed=rcpt_passed,
                        details=rcpt_val,
                        message=f"Receipt {r_id} internal integrity verified." if rcpt_passed else f"Receipt {r_id} issues: {'; '.join(filtered_rcpt_discs)}",
                    )
                )
                for d_msg in filtered_rcpt_discs:
                    all_discrepancies.append(
                        Discrepancy(
                            type=DiscrepancyType.CALCULATION_ERROR,
                            severity=Severity.HIGH,
                            document_ids=[r_id],
                            explanation=f"Receipt {r_id} internal integrity discrepancy: {d_msg}",
                            details=rcpt_val,
                        )
                    )

        result.document_validation_checks = val_checks

        # ── Stage 1: Document Linking ──────────────────────────────
        logger.info(f"[{case_id}] Stage 1: Document Linking")
        missing_docs = detect_missing_documents(po_data, invoice_data, receipt_data_list)
        result.missing_documents = missing_docs

        if po_data and (invoice_data or receipt_data_list):
            link_evidence = evaluate_link(
                po_data, invoice_data, receipt_data_list, policy
            )
            result.document_linking = DocumentLinkResult(
                linked=link_evidence.confidence.value != "LOW",
                evidence=link_evidence,
                missing_documents=missing_docs,
            )

            if link_evidence.confidence.value == "LOW":
                logger.warning(f"[{case_id}] Document linking LOW confidence. Marking UNMATCHED.")
                result.status = ReconciliationStatus.UNMATCHED
                result = finalize_result(result)
                return result
        else:
            result.document_linking = DocumentLinkResult(
                linked=False,
                missing_documents=missing_docs,
            )

        # ── Stage 2: Header Reconciliation ─────────────────────────
        if po_data:
            logger.info(f"[{case_id}] Stage 2: Header Reconciliation")
            header_checks, header_discrepancies = reconcile_headers(
                po_data, invoice_data, receipt_data_list, policy
            )
            result.header_checks = header_checks
            all_discrepancies.extend(header_discrepancies)

        # ── Stage 3: Line-Item Matching ────────────────────────────
        if po_data and invoice_data:
            logger.info(f"[{case_id}] Stage 3: Line-Item Matching")
            po_items = po_data.get("items", [])
            inv_items = invoice_data.get("items", [])

            po_id = result.purchase_order_id or "PO"
            inv_id = result.invoice_id or "INV"

            matches, match_discrepancies = match_line_items(
                po_items, inv_items, po_id, inv_id
            )
            all_discrepancies.extend(match_discrepancies)

            # Match receipt items if available
            if receipt_data_list:
                for i, receipt_data in enumerate(receipt_data_list):
                    receipt_items = receipt_data.get("items", [])
                    receipt_id = result.receipt_ids[i] if i < len(result.receipt_ids) else f"REC-{i+1}"
                    matches = match_receipt_items_to_matches(
                        matches, receipt_items, receipt_id
                    )

            result.line_item_matches = matches

            # ── Stage 4: Quantity Reconciliation ───────────────────
            logger.info(f"[{case_id}] Stage 4: Quantity Reconciliation")
            qty_checks, qty_discrepancies, matches = reconcile_quantities(
                matches, policy
            )
            result.quantity_checks = qty_checks
            all_discrepancies.extend(qty_discrepancies)

            # ── Stage 5: Price Reconciliation ──────────────────────
            logger.info(f"[{case_id}] Stage 5: Price Reconciliation")
            price_checks, price_discrepancies, matches = reconcile_prices(
                matches, policy
            )
            result.price_checks = price_checks
            all_discrepancies.extend(price_discrepancies)

            result.line_item_matches = matches

        # ── Stage 6: Financial Reconciliation ──────────────────────
        if po_data and invoice_data:
            logger.info(f"[{case_id}] Stage 6: Financial Reconciliation")
            fin_checks, fin_discrepancies, fin_breakdown = reconcile_financials(
                po_data, invoice_data, policy, receipt_data_list=receipt_data_list
            )
            result.financial_checks = fin_checks
            result.financial_breakdown = fin_breakdown
            all_discrepancies.extend(fin_discrepancies)

        # ── Stage 7: Receipt Reconciliation ────────────────────────
        if result.line_item_matches:
            logger.info(f"[{case_id}] Stage 7: Receipt Reconciliation")
            receipt_checks, receipt_discrepancies, comparison_table = reconcile_receipts(
                result.line_item_matches, policy
            )
            result.receipt_checks = receipt_checks
            result.receipt_comparison_table = comparison_table
            all_discrepancies.extend(receipt_discrepancies)

        # ── Stage 8: Duplicate Detection ───────────────────────────
        if check_duplicates and invoice_data:
            logger.info(f"[{case_id}] Stage 8: Duplicate Detection")
            detector = _get_duplicate_detector()
            dup_discrepancy = detector.check_duplicate(invoice_data)
            if dup_discrepancy:
                all_discrepancies.append(dup_discrepancy)

        # ── Stage 9: Discrepancy Engine (Severity Enforcement) ─────
        logger.info(f"[{case_id}] Stage 9: Severity Enforcement")
        all_discrepancies = enforce_severities(all_discrepancies, policy)
        result.discrepancies = all_discrepancies

        # ── Stage 10: Decision Engine ──────────────────────────────
        logger.info(f"[{case_id}] Stage 10: Final Decision")
        result.reconciled_at = datetime.now(timezone.utc).isoformat()
        result = finalize_result(result)

    except Exception as e:
        logger.error(f"[{case_id}] Pipeline error: {e}", exc_info=True)
        result.status = ReconciliationStatus.ERROR
        result.summary = f"Reconciliation failed: {str(e)}"
        result.reconciled_at = datetime.now(timezone.utc).isoformat()

    logger.info(
        f"=== Reconciliation Complete: {case_id} -> {result.status.value} "
        f"({len(result.discrepancies)} discrepancies) ==="
    )
    return result


def reconcile_batch(
    transactions: List[Dict[str, Any]],
    policy: Optional[ReconciliationPolicy] = None,
    check_duplicates: bool = True,
) -> List[ReconciliationResult]:
    """
    Run reconciliation on a batch of transactions.

    Each transaction dict should contain:
        - 'po_data': PurchaseOrder dict (optional)
        - 'invoice_data': Invoice dict (optional)
        - 'receipt_data_list': List of Receipt dicts (optional)
        - 'case_id': Optional case ID
    """
    results = []
    for i, txn in enumerate(transactions):
        case_id = txn.get("case_id", _generate_case_id(i))
        result = reconcile_transaction(
            po_data=txn.get("po_data"),
            invoice_data=txn.get("invoice_data"),
            receipt_data_list=txn.get("receipt_data_list", []),
            case_id=case_id,
            policy=policy,
            check_duplicates=check_duplicates,
        )
        results.append(result)
    return results


def _extract_id(data: Optional[Dict[str, Any]], key: str) -> Optional[str]:
    """Safely extract an identifier from a data dict."""
    if data is None:
        return None
    return data.get(key)


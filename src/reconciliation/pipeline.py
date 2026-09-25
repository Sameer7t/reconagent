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

        def _generate_granular_discrepancies(val_report: Dict[str, Any], doc_id: str, doc_name: str, id_field: str) -> List[Discrepancy]:
            discs = []
            
            # 1. Line item math errors
            for item in val_report.get("line_item_audit", []):
                if item.get("is_valid") is False and item.get("error_note"):
                    # Extract values safely
                    calc_val = item.get("calculated_line_total")
                    rep_val = item.get("reported_line_total")
                    diff = None
                    diff_pct = None
                    if calc_val is not None and rep_val is not None:
                        diff = abs(calc_val - rep_val)
                        if calc_val > Decimal("0"):
                            diff_pct = (diff / calc_val) * 100

                    line_id = str(item.get("index")) if item.get("index") else ""
                    if item.get("sku"):
                        line_id += f"-{item.get('sku')}"

                    kwargs = {
                        "type": DiscrepancyType.CALCULATION_ERROR,
                        "severity": Severity.HIGH,
                        "document_ids": [doc_id],
                        "expected_value": str(calc_val) if calc_val is not None else None,
                        "actual_value": str(rep_val) if rep_val is not None else None,
                        "difference": diff,
                        "difference_percent": diff_pct,
                        "explanation": f"{doc_name} {doc_id} line item '{item.get('description') or item.get('sku') or 'Item'}' math failed: {item.get('error_note')}",
                        "details": {"item_audit": item},
                    }
                    kwargs[id_field] = f"{doc_id}-L{line_id}"
                    discs.append(Discrepancy(**kwargs))

            # 2. Extract Document-Level Discrepancies (Subtotal, Grand Total, Missing Items)
            for d_msg in val_report.get("discrepancies", []):
                # Skip the generic line item failure message since we already added granular line-by-line discs above
                if "line item math checks" in d_msg.lower() or "Failed" in d_msg and "/" in d_msg and "line" in d_msg.lower():
                    continue
                
                # Check if it's subtotal or grand total related to map to a specific difference if possible
                exp_val = None
                act_val = None
                
                # Example: "Subtotal discrepancy: sum of lines (500.00) != reported subtotal (600.00)."
                if "sum of lines" in d_msg and "reported subtotal" in d_msg:
                    import re
                    m = re.search(r"sum of lines \(([^)]+)\) != reported subtotal \(([^)]+)\)", d_msg)
                    if m:
                        exp_val = m.group(1)
                        act_val = m.group(2)
                # Example: "Grand total discrepancy: calculated 650.00 != reported 750.00 (Diff: 100.00)."
                elif "Grand total discrepancy: calculated" in d_msg and "!= reported" in d_msg:
                    import re
                    m = re.search(r"calculated ([0-9.]+) != reported ([0-9.]+)", d_msg)
                    if m:
                        exp_val = m.group(1)
                        act_val = m.group(2)

                discs.append(Discrepancy(
                    type=DiscrepancyType.CALCULATION_ERROR,
                    severity=Severity.HIGH,
                    document_ids=[doc_id],
                    expected_value=exp_val,
                    actual_value=act_val,
                    difference=abs(Decimal(exp_val) - Decimal(act_val)) if exp_val and act_val else None,
                    explanation=f"{doc_name} {doc_id} internal integrity discrepancy: {d_msg}",
                    details=val_report.get("resolved_totals", {})
                ))

            return discs

        # 0.1 Purchase Order Internal Validation
        if po_data:
            po_id = result.purchase_order_id or "PO"
            po_val = verify_purchase_order_math(po_data)
            po_discs_msgs = po_val.get("discrepancies", [])
            po_passed = po_val.get("is_valid", True) and len(po_discs_msgs) == 0
            val_checks.append(
                ReconciliationCheck(
                    stage="DOCUMENT_VALIDATION",
                    check_name="po_internal_validation",
                    passed=po_passed,
                    details=po_val,
                    message="PO internal math and integrity verified." if po_passed else f"PO math issues: {'; '.join(po_discs_msgs)}",
                )
            )
            all_discrepancies.extend(_generate_granular_discrepancies(po_val, po_id, "Purchase Order", "po_line_id"))

        # 0.2 Invoice Internal Validation
        if invoice_data:
            inv_id = result.invoice_id or "INV"
            inv_val = verify_invoice_math(invoice_data)
            inv_discs_msgs = inv_val.get("discrepancies", [])
            inv_passed = inv_val.get("is_valid", True) and len(inv_discs_msgs) == 0
            val_checks.append(
                ReconciliationCheck(
                    stage="DOCUMENT_VALIDATION",
                    check_name="invoice_internal_validation",
                    passed=inv_passed,
                    details=inv_val,
                    message="Invoice internal math and integrity verified." if inv_passed else f"Invoice math issues: {'; '.join(inv_discs_msgs)}",
                )
            )
            all_discrepancies.extend(_generate_granular_discrepancies(inv_val, inv_id, "Invoice", "invoice_line_id"))

        # 0.3 Receipt Internal Validation
        if receipt_data_list:
            for idx, r_data in enumerate(receipt_data_list):
                r_id = result.receipt_ids[idx] if idx < len(result.receipt_ids) else f"RECEIPT-{idx+1}"
                rcpt_val = verify_receipt_math(r_data)
                rcpt_discs_msgs = rcpt_val.get("discrepancies", [])
                # For delivery receipts with only quantities, ignore insufficient price variables note
                filtered_rcpt_discs = [
                    d for d in rcpt_discs_msgs
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
                
                # Use a slightly modified fallback logic for receipt since we filtered its generic messages
                granular = _generate_granular_discrepancies(rcpt_val, r_id, "Receipt", "receipt_line_id")
                # Remove fallbacks that might be just the generic message if we filtered it
                if not any(d.details and "item_audit" in d.details for d in granular) and not rcpt_val.get("checks", {}).get("subtotal_verified", True) and len(filtered_rcpt_discs) > 0:
                     pass # keep it
                
                if granular:
                    # Replace the fallback generic messages with filtered ones if needed
                    final_granular = []
                    for d in granular:
                        if not d.details or "item_audit" not in d.details:
                            # It's a fallback or total error. Use filtered messages if it's a fallback
                            if d.explanation.startswith(f"Receipt {r_id} internal integrity discrepancy:"):
                                msg = d.explanation.split(": ", 1)[-1]
                                if msg in filtered_rcpt_discs:
                                    final_granular.append(d)
                            else:
                                final_granular.append(d)
                        else:
                            final_granular.append(d)
                    all_discrepancies.extend(final_granular)

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


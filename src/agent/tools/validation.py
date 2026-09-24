"""
Document Arithmetic & Integrity Validation Tool for ReconAgent.

Provides deterministic, case-isolated verification of line item math,
subtotals, discounts, taxes, and grand totals across Purchase Orders,
Invoices, and Receipts by connecting to the verification layer.
"""
import logging
from typing import Dict, Any, Optional

from validation.purchase_order_validation import verify_purchase_order_math
from validation.invoice_validation import verify_invoice_math
from validation.receipt_validation import verify_receipt_math

logger = logging.getLogger("ValidationTool")


def verify_document_arithmetic(
    document_type: str,
    document_id: str,
    store: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Tool: Deterministically audits the arithmetic of a case document
    (Purchase Order, Vendor Invoice, or Goods Receipt).

    Args:
        document_type: 'purchase_order', 'invoice', or 'receipt'
        document_id: The document identifier (e.g. 'PO-2024-0001', 'INV-30001', 'DR-70001')
        store: Optional AgentDataStore instance

    Returns:
        Structured audit report containing:
        - status: 'VALID' | 'INVALID' | 'NOT_FOUND'
        - is_valid: bool
        - document_type: str
        - document_id: str
        - discrepancies: List[str]
        - line_item_audit: List[dict]
        - resolved_totals: dict
        - error_detail: Optional[str]
        - summary: str
    """
    from agent.tools.registry import AgentDataStore

    datastore = store or AgentDataStore.get_default()
    doc_type_clean = (document_type or "").lower().strip()

    # Normalize aliases
    if doc_type_clean in ("po", "purchase_order", "purchaseorder"):
        doc_type_key = "purchase_order"
        raw_doc = datastore.purchase_orders.get(document_id)
        verifier_fn = verify_purchase_order_math
        label = "Purchase Order"
    elif doc_type_clean in ("inv", "invoice", "vendor_invoice"):
        doc_type_key = "invoice"
        raw_doc = datastore.invoices.get(document_id)
        verifier_fn = verify_invoice_math
        label = "Invoice"
    elif doc_type_clean in ("rcpt", "receipt", "goods_receipt", "delivery_receipt"):
        doc_type_key = "receipt"
        raw_doc = datastore.receipts.get(document_id)
        verifier_fn = verify_receipt_math
        label = "Receipt"
    else:
        return {
            "status": "ERROR",
            "found": False,
            "document_type": document_type,
            "document_id": document_id,
            "error": f"Unsupported document_type '{document_type}'. Permitted: 'purchase_order', 'invoice', 'receipt'.",
            "is_valid": False,
        }

    if not raw_doc:
        return {
            "status": "NOT_FOUND",
            "found": False,
            "document_type": doc_type_key,
            "document_id": document_id,
            "error": f"{label} '{document_id}' not found in case repository.",
            "is_valid": False,
            "summary": f"{label} '{document_id}' was not found on file.",
        }

    # Execute deterministic verification
    try:
        raw_report = verifier_fn(raw_doc)
    except Exception as err:
        logger.error(f"Error validating {doc_type_key} {document_id}: {err}", exc_info=True)
        return {
            "status": "ERROR",
            "found": True,
            "document_type": doc_type_key,
            "document_id": document_id,
            "error": f"Arithmetic verification crashed: {str(err)}",
            "is_valid": False,
        }

    discrepancies = raw_report.get("discrepancies", [])
    line_audits = raw_report.get("line_item_audit", [])
    failed_lines = [la for la in line_audits if not la.get("is_valid")]
    resolved_totals = raw_report.get("resolved_totals", {})

    # A document is only valid if underlying math passed AND no failed lines or discrepancies exist
    is_valid = bool(raw_report.get("is_valid", False)) and len(failed_lines) == 0 and len(discrepancies) == 0
    confidence_score = raw_report.get("confidence_score", 100.0 if is_valid else 0.0)

    # Format human-readable details
    error_detail = None
    formatted_math = None

    if failed_lines:
        first_fail = failed_lines[0]
        desc = first_fail.get("description") or first_fail.get("product_code") or "Item"
        rep_val = first_fail.get("reported_line_total")
        calc_val = first_fail.get("calculated_line_total")
        error_note = first_fail.get("error_note") or ""

        # Safe formatting with fallback
        try:
            rep_str = f"${float(rep_val):.2f}" if rep_val is not None else "N/A"
        except (ValueError, TypeError):
            rep_str = str(rep_val or "N/A")

        try:
            calc_str = f"${float(calc_val):.2f}" if calc_val is not None else "N/A"
        except (ValueError, TypeError):
            calc_str = str(calc_val or "N/A")

        formatted_math = f"Printed {rep_str} vs Calculated {calc_str}"
        error_detail = f"Line item '{desc}' arithmetic mismatch: {formatted_math}. {error_note}"
    elif not is_valid and discrepancies:
        error_detail = "; ".join(discrepancies)

    if is_valid:
        summary = f"{label} {document_id} arithmetic verified: item lines, subtotal, and grand total match perfectly."
    else:
        summary = (
            f"{label} {document_id} failed arithmetic verification. "
            f"{error_detail or 'Item calculations do not equal reported totals.'}"
        )

    return {
        "status": "VALID" if is_valid else "INVALID",
        "found": True,
        "is_valid": is_valid,
        "document_type": doc_type_key,
        "document_id": document_id,
        "confidence_score": confidence_score,
        "discrepancies": discrepancies,
        "line_item_audit": line_audits,
        "failed_lines": failed_lines,
        "resolved_totals": resolved_totals,
        "formatted_math": formatted_math,
        "error_detail": error_detail,
        "summary": summary,
    }

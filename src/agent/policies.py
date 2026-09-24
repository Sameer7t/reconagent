"""
AI Investigation Agent Policies Layer.

Defines deterministic policy rules that restrict which tools are permissible
for each discrepancy category, enforcing hybrid agent governance rather than
uncontrolled autonomy.
"""
from typing import Dict, List, Set, Any


INVESTIGATION_POLICY: Dict[str, List[str]] = {
    "PRICE_MISMATCH": [
        "get_purchase_order",
        "get_invoice",
        "check_authorization",
        "get_vendor_history",
        "find_similar_invoices",
    ],
    "UNIT_PRICE_MISMATCH": [
        "get_purchase_order",
        "get_invoice",
        "check_authorization",
        "get_vendor_history",
        "find_similar_invoices",
    ],
    "QUANTITY_MISMATCH": [
        "get_purchase_order",
        "get_invoice",
        "get_receipt",
    ],
    "QUANTITY_SHORTAGE": [
        "get_purchase_order",
        "get_invoice",
        "get_receipt",
    ],
    "RECEIPT_SHORTAGE": [
        "get_purchase_order",
        "get_invoice",
        "get_receipt",
    ],
    "INVOICE_QUANTITY_EXCEEDS_PO": [
        "get_purchase_order",
        "get_invoice",
        "get_receipt",
    ],
    "INVOICE_QUANTITY_EXCEEDS_RECEIVED": [
        "get_purchase_order",
        "get_invoice",
        "get_receipt",
    ],
    "UNAUTHORIZED_CHARGE": [
        "get_purchase_order",
        "get_invoice",
        "check_authorization",
    ],
    "SHIPPING_EXCEEDS_PO": [
        "get_purchase_order",
        "get_invoice",
        "check_authorization",
    ],
    "SUBTOTAL_MISMATCH": [
        "get_purchase_order",
        "get_invoice",
        "check_authorization",
    ],
    "DUPLICATE_INVOICE": [
        "get_invoice",
        "find_similar_invoices",
        "get_vendor_history",
    ],
    "VENDOR_MISMATCH": [
        "get_purchase_order",
        "get_invoice",
    ],
    "CURRENCY_MISMATCH": [
        "get_purchase_order",
        "get_invoice",
    ],
    "DOCUMENT_LINK_MISMATCH": [
        "get_purchase_order",
        "get_invoice",
        "get_receipt",
    ],
    "UNMATCHED_ITEM": [
        "get_purchase_order",
        "get_invoice",
        "check_authorization",
    ],
    "CALCULATION_ERROR": [
        "verify_document_arithmetic",
        "get_purchase_order",
        "get_invoice",
        "get_receipt",
    ],
    "INTERNAL_MATH_ERROR": [
        "verify_document_arithmetic",
        "get_purchase_order",
        "get_invoice",
        "get_receipt",
    ],
    "MATH_DISCREPANCY": [
        "verify_document_arithmetic",
        "get_purchase_order",
        "get_invoice",
        "get_receipt",
    ],
}

# Baseline fallback if discrepancy type is not specifically mapped
DEFAULT_BASELINE_TOOLS = ["verify_document_arithmetic", "get_purchase_order", "get_invoice", "get_receipt"]


def get_allowed_tools_for_discrepancies(discrepancies: List[Dict[str, Any]]) -> Set[str]:
    """
    Returns the union of allowed tool names permitted for the given case discrepancies.
    """
    if not discrepancies:
        return set(DEFAULT_BASELINE_TOOLS)

    allowed: Set[str] = set()
    for disc in discrepancies:
        disc_type = str(disc.get("type", "")).upper()
        # Direct policy lookup
        matched_tools = INVESTIGATION_POLICY.get(disc_type)
        if matched_tools:
            allowed.update(matched_tools)
        else:
            # Substring heuristic
            found = False
            for policy_key, policy_tools in INVESTIGATION_POLICY.items():
                if policy_key in disc_type or disc_type in policy_key:
                    allowed.update(policy_tools)
                    found = True
            if not found:
                allowed.update(DEFAULT_BASELINE_TOOLS)

    return allowed


def is_tool_allowed_for_case(tool_name: str, state: Dict[str, Any]) -> bool:
    """
    Evaluates whether tool_name is permitted by policy for the discrepancies in state.
    """
    discrepancies = state.get("discrepancies", [])
    allowed = get_allowed_tools_for_discrepancies(discrepancies)
    return tool_name in allowed

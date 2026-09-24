"""
Invoice Investigation Tool.

Retrieves structured Invoice records from enterprise storage
and returns header and line item details for investigation.
"""
from typing import Dict, Any, Optional


def get_invoice(invoice_id: str, store: Optional[Any] = None) -> Dict[str, Any]:
    """
    Tool #2: Retrieves structured Invoice from the database.
    Returns invoice number, vendor, PO reference, currency, lines, quantities, prices, tax, shipping, total.
    """
    from agent.tools.registry import AgentDataStore
    datastore = store or AgentDataStore.get_default()
    inv = datastore.invoices.get(invoice_id)
    if not inv:
        return {
            "status": "NOT_FOUND",
            "invoice_id": invoice_id,
            "error": f"Invoice '{invoice_id}' not found.",
            "message": f"Invoice '{invoice_id}' was not found on file.",
        }

    lines = []
    for idx, item in enumerate(inv.get("items", []), start=1):
        lines.append({
            "line_id": f"INV-L{idx}",
            "description": item.get("description", ""),
            "quantity": str(item.get("quantity", "0")),
            "unit_price": str(item.get("unit_price", "0.00")),
            "line_total": str(item.get("line_total", "0.00")),
        })

    vendor_name = inv.get("vendor_name") or (inv.get("vendor", {}) or {}).get("name", "")
    return {
        "status": "FOUND",
        "invoice_id": invoice_id,
        "vendor": vendor_name,
        "po_reference": inv.get("purchase_order_number"),
        "currency": inv.get("currency", "USD"),
        "lines": lines,
        "tax": str(inv.get("total_tax", inv.get("tax", "0.00"))),
        "shipping": str(inv.get("shipping", "0.00")),
        "subtotal": str(inv.get("subtotal", "0.00")),
        "total": str(inv.get("total", "0.00")),
    }


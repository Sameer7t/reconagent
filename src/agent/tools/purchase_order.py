"""
Purchase Order Investigation Tool.

Retrieves structured Purchase Order records from enterprise storage
and returns relevant high-signal fields for investigation.
"""
from typing import Dict, Any, Optional


def get_purchase_order(po_id: str, store: Optional[Any] = None) -> Dict[str, Any]:
    """
    Tool #1: Retrieves structured Purchase Order from the database.
    Returns only the relevant high-signal fields.
    """
    from agent.tools.registry import AgentDataStore
    datastore = store or AgentDataStore.get_default()
    po = datastore.purchase_orders.get(po_id)
    if not po:
        return {
            "found": False,
            "status": "NOT_FOUND",
            "po_id": po_id,
            "error": f"Purchase Order '{po_id}' not found.",
            "message": f"Purchase Order '{po_id}' was not found on file.",
        }

    lines = []
    for idx, item in enumerate(po.get("items", []), start=1):
        lines.append({
            "item_id": item.get("product_code") or item.get("item_id") or f"PO-L{idx}",
            "line_id": f"PO-L{idx}",
            "description": item.get("description", ""),
            "quantity": str(item.get("quantity", "0")),
            "unit_price": str(item.get("unit_price", "0.00")),
        })

    vendor_name = po.get("vendor_name") or (po.get("vendor", {}) or {}).get("name", "")
    return {
        "found": True,
        "status": "FOUND",
        "po_id": po_id,
        "vendor_id": vendor_name,
        "currency": po.get("currency", "USD"),
        "lines": lines,
        "payment_terms": po.get("payment_terms", "Net 30"),
    }


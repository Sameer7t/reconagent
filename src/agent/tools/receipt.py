"""
Delivery Receipt Investigation Tool.

Retrieves structured Delivery Receipt records from receiving dock systems
and returns received quantities and fulfillment status.
"""
from typing import Dict, Any, Optional


def get_receipt(receipt_id: str, store: Optional[Any] = None) -> Dict[str, Any]:
    """
    Tool #3: Retrieves structured Delivery Receipt from the database.
    Returns receipt ID, PO, received lines, received quantities, dates.
    """
    from agent.tools.registry import AgentDataStore
    datastore = store or AgentDataStore.get_default()
    rcpt = datastore.receipts.get(receipt_id)
    if not rcpt:
        return {
            "status": "NOT_FOUND",
            "receipt_id": receipt_id,
            "error": f"Receipt '{receipt_id}' not found.",
            "message": f"Receipt '{receipt_id}' was not found on file.",
        }

    received_lines = []
    for idx, item in enumerate(rcpt.get("items", []), start=1):
        line_data = {
            "line_id": f"REC-L{idx}",
            "description": item.get("description", ""),
            "quantity_ordered": str(item.get("quantity_ordered", item.get("quantity", "0"))),
            "quantity_delivered": str(item.get("quantity", "0")),
        }
        if item.get("unit_price") is not None:
            line_data["unit_price"] = str(item.get("unit_price"))
        if item.get("total") is not None:
            line_data["total"] = str(item.get("total"))
        received_lines.append(line_data)

    res = {
        "status": "FOUND",
        "receipt_id": receipt_id,
        "po_reference": rcpt.get("purchase_order_number"),
        "received_lines": received_lines,
        "delivery_date": rcpt.get("date", rcpt.get("delivery_date", "")),
    }
    if rcpt.get("subtotal") is not None:
        res["subtotal"] = str(rcpt.get("subtotal"))
    if rcpt.get("total") is not None:
        res["total"] = str(rcpt.get("total"))

    return res


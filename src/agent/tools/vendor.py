"""
Vendor History & Invoice Similarity Tools.

Retrieves historical vendor pricing records and finds similar past invoices
to determine standard pricing and vendor behavior.
"""
import difflib
from typing import Dict, Any, List, Optional


def get_vendor_history(
    vendor_id: str,
    item_id: Optional[str] = None,
    store: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Tool #4: Retrieves historical unit prices and transaction history for a vendor.
    """
    from agent.tools.registry import AgentDataStore
    datastore = store or AgentDataStore.get_default()
    norm_v = AgentDataStore._normalize_vendor(vendor_id)

    # Search for matching vendor keys
    records = []
    for stored_vendor, txs in datastore.vendor_history.items():
        if norm_v in stored_vendor or stored_vendor in norm_v:
            records.extend(txs)

    filtered_txs = []
    for tx in records:
        if item_id:
            if item_id.lower() in tx.get("description", "").lower():
                filtered_txs.append({
                    "invoice_id": tx.get("invoice_id"),
                    "unit_price": tx.get("unit_price"),
                    "date": tx.get("date"),
                    "description": tx.get("description"),
                })
        else:
            filtered_txs.append({
                "invoice_id": tx.get("invoice_id"),
                "unit_price": tx.get("unit_price"),
                "date": tx.get("date"),
                "description": tx.get("description"),
            })

    return {
        "status": "FOUND" if filtered_txs else "NOT_FOUND",
        "vendor_id": vendor_id,
        "transactions": filtered_txs,
        "message": f"Found {len(filtered_txs)} transactions" if filtered_txs else f"No prior transaction history found for vendor '{vendor_id}'.",
    }


def find_similar_invoices(
    vendor_id: str,
    item_description: str,
    limit: int = 5,
    store: Optional[Any] = None,
) -> List[Dict[str, Any]]:
    """
    Tool #6: Finds similar past invoices for the given vendor and item description
    using normalized token/string similarity.
    """
    from agent.tools.registry import AgentDataStore
    datastore = store or AgentDataStore.get_default()
    norm_v = AgentDataStore._normalize_vendor(vendor_id)
    norm_desc = item_description.lower().strip()

    candidates = []
    for stored_vendor, txs in datastore.vendor_history.items():
        if norm_v in stored_vendor or stored_vendor in norm_v:
            for tx in txs:
                cand_desc = tx.get("description", "").lower()
                sim = difflib.SequenceMatcher(None, norm_desc, cand_desc).ratio()
                candidates.append((sim, tx))

    candidates.sort(key=lambda x: x[0], reverse=True)
    results = []
    for sim, tx in candidates[:limit]:
        results.append({
            "invoice_id": tx.get("invoice_id"),
            "description": tx.get("description"),
            "unit_price": tx.get("unit_price"),
            "date": tx.get("date"),
            "similarity_score": round(sim, 2),
        })

    return results


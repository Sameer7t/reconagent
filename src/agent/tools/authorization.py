"""
Authorization & PO Amendment Investigation Tool.

Checks approved price changes, change orders, scope adjustments,
or management authorization records for a PO.
"""
from typing import Dict, Any, Optional


def check_authorization(
    po_id: str,
    discrepancy_type: str,
    amount: Optional[str] = None,
    store: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Tool #5: Checks approved changes, amendments, or authorization records for a PO.
    """
    from agent.tools.registry import AgentDataStore
    datastore = store or AgentDataStore.get_default()
    auth_records = datastore.authorizations.get(po_id, [])

    matching_records = []
    for rec in auth_records:
        rec_type = rec.get("discrepancy_type", "").lower()
        if not rec_type or rec_type == discrepancy_type.lower():
            matching_records.append({
                "authorization_id": rec.get("authorization_id", "AUTH-RECORD"),
                "approved_value": str(rec.get("approved_value", "")),
                "approved_by_role": rec.get("approved_by_role", "purchasing_manager"),
                "notes": rec.get("notes", "Approved formal amendment."),
            })

    if matching_records:
        return {
            "status": "FOUND",
            "authorized": True,
            "records": matching_records,
        }
    return {
        "status": "NOT_FOUND",
        "authorized": False,
        "records": [],
        "message": f"No authorization was found on file for PO '{po_id}'.",
    }


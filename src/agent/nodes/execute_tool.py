"""
AI Investigation Agent Tool Execution Node.

Executes Python tools safely through ToolRegistry, enforces case boundaries,
converts tool results into strongly-typed Evidence items, updates state provenance,
and increments tool counters.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from agent.state import InvestigationState
from agent.models import AgentAction, Evidence
from agent.tools import ToolRegistry, AgentDataStore


def execute_tool_node(
    state: InvestigationState,
    action: Optional[AgentAction] = None,
    registry: Optional[ToolRegistry] = None,
) -> InvestigationState:
    """
    Executes the requested tool action within strict security boundaries.
    
    Flow:
      1. Verify action type is 'investigate' and tool is specified.
      2. Call ToolRegistry.validate_and_execute (checks whitelist, params, case scope, duplicate protection).
      3. Convert valid execution results (including explicit NOT_FOUND outcomes) into Evidence objects.
      4. Append audit record to state['tool_calls'].
      5. Increment state['tool_call_count'].
      6. Return updated state.
    """
    reg = registry if registry is not None else ToolRegistry()

    if action is None:
        act_dict = state.get("selected_action") or state.get("last_action") or {}
        if act_dict:
            action = AgentAction(**act_dict)

    if action is None or action.action != "investigate" or not action.tool:
        return state

    tool_name = action.tool
    arguments = action.arguments or {}

    # Execute tool via security boundary (records audit entry and increments counter)
    result = reg.validate_and_execute(tool_name, arguments, state)
    is_dict = isinstance(result, dict)
    status = result.get("status") if is_dict else "FOUND"

    # If execution produced valid business outcome (FOUND or NOT_FOUND on file), extract Evidence
    if not is_dict or status in ("FOUND", "NOT_FOUND") or ("error" not in result and status not in ("ERROR", "UNAUTHORIZED", "DUPLICATE_CALL")):
        new_evidence_list = _convert_tool_result_to_evidence(
            tool_name=tool_name,
            arguments=arguments,
            result=result,
            current_evidence_count=len(state.get("evidence", [])),
        )
        if "evidence" not in state or state["evidence"] is None:
            state["evidence"] = []
        for ev in new_evidence_list:
            state["evidence"].append(ev.model_dump() if hasattr(ev, "model_dump") else ev)

    return state


def _convert_tool_result_to_evidence(
    tool_name: str,
    arguments: Dict[str, Any],
    result: Any,
    current_evidence_count: int,
) -> List[Evidence]:
    """
    Synthesizes authoritative, provenance-backed Evidence objects from raw tool output.
    Captures both verified records (FOUND) and document absence (NOT_FOUND) with precise semantics.
    """
    evidence_items: List[Evidence] = []
    cnt = current_evidence_count
    status = result.get("status") if isinstance(result, dict) else "FOUND"

    if tool_name == "get_purchase_order":
        po_id = result.get("po_id", arguments.get("po_id", ""))
        if status == "NOT_FOUND":
            cnt += 1
            evidence_items.append(Evidence(
                evidence_id=f"EVID-{cnt:03d}",
                source_type="purchase_order",
                source_id=po_id,
                field="document_status",
                value="NOT_FOUND",
                description=f"Purchase Order {po_id} was not found on file in enterprise records."
            ))
        else:
            for line in result.get("lines", []):
                cnt += 1
                evidence_items.append(Evidence(
                    evidence_id=f"EVID-{cnt:03d}",
                    source_type="purchase_order",
                    source_id=po_id,
                    field="unit_price",
                    value=str(line.get("unit_price", "")),
                    description=f"PO {po_id} line '{line.get('description')}' approved unit price is ${line.get('unit_price')} (authorized qty: {line.get('quantity')})."
                ))

    elif tool_name == "get_invoice":
        inv_id = result.get("invoice_id", arguments.get("invoice_id", ""))
        if status == "NOT_FOUND":
            cnt += 1
            evidence_items.append(Evidence(
                evidence_id=f"EVID-{cnt:03d}",
                source_type="invoice",
                source_id=inv_id,
                field="document_status",
                value="NOT_FOUND",
                description=f"Invoice {inv_id} was not found on file in enterprise records."
            ))
        else:
            for line in result.get("lines", []):
                cnt += 1
                evidence_items.append(Evidence(
                    evidence_id=f"EVID-{cnt:03d}",
                    source_type="invoice",
                    source_id=inv_id,
                    field="unit_price",
                    value=str(line.get("unit_price", "")),
                    description=f"Invoice {inv_id} line '{line.get('description')}' billed unit price is ${line.get('unit_price')} (billed qty: {line.get('quantity')}, line total: ${line.get('line_total')})."
                ))

    elif tool_name == "get_receipt":
        rcpt_id = result.get("receipt_id", arguments.get("receipt_id", ""))
        del_date = result.get("delivery_date", "")
        if status == "NOT_FOUND":
            cnt += 1
            evidence_items.append(Evidence(
                evidence_id=f"EVID-{cnt:03d}",
                source_type="receipt",
                source_id=rcpt_id,
                field="document_status",
                value="NOT_FOUND",
                description=f"Delivery receipt {rcpt_id} was not found on file in enterprise records."
            ))
        else:
            for line in result.get("received_lines", []):
                cnt += 1
                evidence_items.append(Evidence(
                    evidence_id=f"EVID-{cnt:03d}",
                    source_type="receipt",
                    source_id=rcpt_id,
                    field="quantity_delivered",
                    value=str(line.get("quantity_delivered", "")),
                    description=f"Receipt {rcpt_id} confirms physical delivery of {line.get('quantity_delivered')} units for '{line.get('description')}' on {del_date}."
                ))

    elif tool_name == "check_authorization":
        po_id = arguments.get("po_id", "")
        authorized = result.get("authorized", False)
        records = result.get("records", [])
        cnt += 1
        if authorized and records:
            rec = records[0]
            desc = f"Formal authorization {rec.get('authorization_id')} approved by {rec.get('approved_by_role')} (value: ${rec.get('approved_value')}). Notes: {rec.get('notes')}"
        else:
            desc = f"No formal authorization, change order, or price escalation approval was found on file for PO {po_id}."

        evidence_items.append(Evidence(
            evidence_id=f"EVID-{cnt:03d}",
            source_type="authorization",
            source_id=po_id,
            field="is_authorized",
            value=str(authorized),
            description=desc
        ))

    elif tool_name == "get_vendor_history":
        vendor_id = result.get("vendor_id", arguments.get("vendor_id", ""))
        txs = result.get("transactions", [])
        cnt += 1
        if txs:
            recent_rates = [f"${t.get('unit_price')}" for t in txs[:3]]
            desc = f"Vendor history for '{vendor_id}' contains {len(txs)} past transactions with historical rates: {', '.join(recent_rates)}."
        else:
            desc = f"No prior transaction history found for vendor '{vendor_id}'."

        evidence_items.append(Evidence(
            evidence_id=f"EVID-{cnt:03d}",
            source_type="vendor_history",
            source_id=vendor_id,
            field="historical_pricing",
            value=f"{len(txs)} transactions",
            description=desc
        ))

    elif tool_name == "find_similar_invoices":
        vendor_id = arguments.get("vendor_id", "")
        hits = result if isinstance(result, list) else result.get("results", [])
        cnt += 1
        desc = f"Similar invoice search returned {len(hits)} matching past invoice items for vendor '{vendor_id}'."
        evidence_items.append(Evidence(
            evidence_id=f"EVID-{cnt:03d}",
            source_type="similar_invoices",
            source_id=vendor_id,
            field="similarity_hits",
            value=str(len(hits)),
            description=desc
        ))

    return evidence_items


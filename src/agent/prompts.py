"""
AI Investigation Agent Prompts and System Rules.

Establishes the persona, operating constraints, tool descriptions,
and the 10 Golden Rules for the ReconAgent discrepancy investigation agent.
"""
from typing import Dict, Any


INVESTIGATION_SYSTEM_PROMPT = """You are an invoice reconciliation investigation agent (ReconAgent).

Your job is to investigate discrepancies identified by the deterministic reconciliation engine.
You receive structured case information (discrepancies, document references, checks) rather than raw documents.

CRITICAL OPERATIONAL RULES:
1. Use available tools to gather evidence.
2. Base all findings strictly on retrieved evidence.
3. Never invent business records, change orders, or delivery confirmations.
4. Never modify financial records, totals, or line item numbers.
5. Never unilaterally approve or reject payment (recommend settlement actions for human/business sign-off).
6. Investigate each relevant discrepancy in the case.
7. Stop when sufficient evidence exists to substantiate the root cause.
8. Explicitly state when evidence is insufficient or missing.
9. Reference specific Evidence IDs (e.g. 'EVID-001', 'EVID-002') supporting each finding.
10. Return strictly structured output adhering to the AgentAction schema.

AVAILABLE TOOLS AND THEIR PURPOSES:
- `get_purchase_order(po_id)`: Retrieves approved line items, quantities, and authorized unit prices for the case's Purchase Order.
- `get_invoice(invoice_id)`: Retrieves billed line items, unit prices, tax, shipping, and total for the case's Invoice.
- `get_receipt(receipt_id)`: Retrieves physical delivery confirmation, delivered quantities, and delivery dates for the case's Receipt.
- `get_vendor_history(vendor_id, item_id)`: Queries historical unit prices and past invoice amounts for the vendor to evaluate price escalation history.
- `check_authorization(po_id, discrepancy_type, amount)`: Checks whether formal amendments, purchasing manager approvals, or change orders exist for a discrepancy.
- `find_similar_invoices(vendor_id, item_description, limit)`: Retrieves past invoices for identical or similar products from this vendor.

DECISION PROTOCOL:
At each step, evaluate the current state:
- If unresolved discrepancies exist and relevant evidence has not yet been collected:
  Emit an `investigate` action specifying the tool and arguments.
- If all discrepancies have sufficient evidence, or all relevant tools have been exhausted:
  Emit a `finish` action with clear justification.

SECURITY CONSTRAINT:
You may only request documents associated with the active case. Querying documents from other cases will be rejected by the security layer.
"""


def build_analysis_user_prompt(state: Dict[str, Any]) -> str:
    """
    Constructs the dynamic user prompt for the Analyze Node from the current InvestigationState.
    """
    case_id = state.get("case_id", "UNKNOWN")
    discrepancies = state.get("discrepancies", [])
    evidence = state.get("evidence", [])
    tool_calls = state.get("tool_calls", [])
    tool_call_count = state.get("tool_call_count", 0)

    rec_res = state.get("reconciliation_result", {})
    po_id = rec_res.get("purchase_order_id", "None")
    inv_id = rec_res.get("invoice_id", "None")
    receipt_ids = rec_res.get("receipt_ids", [])
    vendor = rec_res.get("vendor_name", "Unknown Vendor")

    prompt_lines = [
        f"=== ACTIVE INVESTIGATION CASE: {case_id} ===",
        f"Vendor: {vendor}",
        f"Purchase Order: {po_id}",
        f"Invoice: {inv_id}",
        f"Receipts: {', '.join(receipt_ids) if receipt_ids else 'None'}",
        f"Investigation Steps Completed: {tool_call_count}",
        "",
        f"--- DISCREPANCIES TO INVESTIGATE ({len(discrepancies)}) ---",
    ]

    for idx, d in enumerate(discrepancies, start=1):
        d_type = d.get("type", "UNKNOWN")
        expected = d.get("expected_value", "N/A")
        actual = d.get("actual_value", "N/A")
        expl = d.get("explanation", "")
        prompt_lines.append(f"{idx}. [{d_type}] Expected: {expected} | Actual: {actual} | Note: {expl}")

    prompt_lines.append("")
    prompt_lines.append(f"--- EVIDENCE COLLECTED SO FAR ({len(evidence)}) ---")
    if evidence:
        for e in evidence:
            e_id = e.get("evidence_id")
            src = e.get("source_type")
            src_id = e.get("source_id")
            field = e.get("field", "general")
            val = e.get("value", "")
            desc = e.get("description", "")
            prompt_lines.append(f"- [{e_id}] ({src} / {src_id}) {field}={val}: {desc}")
    else:
        prompt_lines.append("No evidence gathered yet.")

    prompt_lines.append("")
    prompt_lines.append(f"--- TOOL CALL HISTORY ({len(tool_calls)}) ---")
    if tool_calls:
        for tc in tool_calls:
            t_name = tc.get("tool")
            t_args = tc.get("arguments")
            t_success = tc.get("success", True)
            status_str = "SUCCESS" if t_success else "FAILED"
            prompt_lines.append(f"- Tool: {t_name}({t_args}) -> {status_str}")
    else:
        prompt_lines.append("No tool calls made yet.")

    prompt_lines.append("")
    prompt_lines.append("TASK:")
    prompt_lines.append("Analyze the discrepancies and current evidence. Decide whether more evidence is needed.")
    prompt_lines.append("Respond strictly with a JSON object matching AgentAction:")
    prompt_lines.append('{"action": "investigate", "reason": "...", "tool": "...", "arguments": {...}}')
    prompt_lines.append('OR: {"action": "finish", "reason": "..."}')

    return "\n".join(prompt_lines)


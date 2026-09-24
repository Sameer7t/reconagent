"""
AI Investigation Agent Analyze Node.

Responsible for inspecting case discrepancies, evaluating current evidence,
and deciding whether to gather more evidence (investigate) or conclude (finish).
Enforces:
- Discrepancy-aware investigation pathways (Step 34)
- Purposeful tool selection without investigating irrelevant records (Step 35)
- Investigation policy filtering (Step 36)
- Resilient retry and error handling (Step 32)
"""
import os
import json
import logging
from typing import Dict, Any, Optional

from agent.state import InvestigationState
from agent.models import AgentAction
from agent.prompts import INVESTIGATION_SYSTEM_PROMPT, build_analysis_user_prompt
from agent.policies import get_allowed_tools_for_discrepancies

logger = logging.getLogger("AnalyzeNode")

# Upper bound on investigation queries per case
MAX_INVESTIGATION_STEPS = 8

from agent.router import GeminiModelRouter, DEFAULT_MODEL_CASCADE

_model_router = GeminiModelRouter()


def analyze(
    state: InvestigationState,
    client: Optional[Any] = None,
    model_name: Optional[str] = None,
) -> AgentAction:
    """
    Core reasoning node. Evaluates case state and returns an AgentAction.
    
    If an external LLM client is available, dynamically routes generation through
    GeminiModelRouter (9-tier cascade: 3.8 Flash down to 2.5 Flash Lite) with
    exponential backoff retries.
    If all LLM calls fail or no client is provided, it safely falls back to the
    deterministic discrepancy-aware strategic reasoner so the pipeline never crashes.
    """
    tool_call_count = state.get("tool_call_count", 0)

    # 1. Loop Termination Guard
    if tool_call_count >= MAX_INVESTIGATION_STEPS:
        return AgentAction(
            action="finish",
            reason=f"Reached maximum investigation step limit ({MAX_INVESTIGATION_STEPS}). Concluding with available evidence."
        )

    discrepancies = state.get("discrepancies", [])
    if not discrepancies:
        return AgentAction(
            action="finish",
            reason="No discrepancies recorded for this case. No investigation required."
        )

    # 2. Dynamic Model Cascade via GeminiModelRouter
    if client is not None:
        action_obj = _model_router.route_generation(
            state=state,
            client=client,
            preferred_model=model_name,
        )
        if action_obj is not None:
            return action_obj

    # 3. Deterministic Purposeful Reasoner
    return _deterministic_analyze(state)


def _deterministic_analyze(state: InvestigationState) -> AgentAction:
    """
    Deterministic discrepancy-aware reasoning engine that selects purposeful tools
    based on the specific discrepancy types and stops as soon as sufficient evidence exists.
    """
    discrepancies = state.get("discrepancies", [])
    tool_calls = state.get("tool_calls", [])
    evidence = state.get("evidence", [])
    
    # Filter executed tools and note failures
    executed_tools = {tc.get("tool") for tc in tool_calls}
    failed_tools = {tc.get("tool") for tc in tool_calls if not tc.get("success", True)}

    rec_res = state.get("reconciliation_result", {})
    po_id = rec_res.get("purchase_order_id")
    inv_id = rec_res.get("invoice_id")
    receipt_ids = rec_res.get("receipt_ids", [])
    vendor_name = (
        rec_res.get("vendor_name")
        or (rec_res.get("invoice_data", {}) or {}).get("vendor_name")
        or (rec_res.get("po_data", {}) or {}).get("vendor_name")
        or "Unknown Vendor"
    )

    allowed_tools = get_allowed_tools_for_discrepancies(discrepancies)
    disc_types = {str(d.get("type", "")).upper() for d in discrepancies}

    # Helper: check if evidence of a particular type has already been verified
    has_auth_evidence = any(e.get("source_type") == "authorization" for e in evidence)
    auth_is_approved = any(e.get("source_type") == "authorization" and e.get("value") == "True" for e in evidence)
    has_receipt_evidence = any(e.get("source_type") == "receipt" for e in evidence)

    # -------------------------------------------------------------
    # PATHWAY A: PRICE MISMATCH / UNIT RATE (Steps 34 & 35)
    # Target: PO -> check authorization -> vendor history
    # Never query receipts! Stop immediately if authorization is found.
    # -------------------------------------------------------------
    is_price_issue = any("PRICE" in dt or "RATE" in dt for dt in disc_types)
    if is_price_issue:
        # 1. Inspect baseline PO if allowed and not yet executed
        if "get_purchase_order" in allowed_tools and po_id and "get_purchase_order" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Need to inspect authorized unit prices and lines in Purchase Order {po_id}.",
                tool="get_purchase_order",
                arguments={"po_id": po_id}
            )

        # 2. Inspect Invoice lines if allowed and not yet executed
        if "get_invoice" in allowed_tools and inv_id and "get_invoice" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Need to inspect billed unit prices and line totals in Invoice {inv_id}.",
                tool="get_invoice",
                arguments={"invoice_id": inv_id}
            )

        # 3. Check authorization for formal price approval
        if "check_authorization" in allowed_tools and po_id and "check_authorization" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Checking if a formal price escalation or change order was approved on file for PO {po_id}.",
                tool="check_authorization",
                arguments={"po_id": po_id, "discrepancy_type": "PRICE_MISMATCH"}
            )

        # Step 35: If authorization was found and approved, STOP immediately! No need for vendor history.
        if auth_is_approved:
            return AgentAction(
                action="finish",
                reason="Discovered formal approved authorization on file confirming price adjustment. Sufficient evidence gathered."
            )

        # 4. If authorization is absent, check historical vendor rates
        if "get_vendor_history" in allowed_tools and vendor_name and "get_vendor_history" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"No formal approval found; checking past historical invoice rates for vendor '{vendor_name}'.",
                tool="get_vendor_history",
                arguments={"vendor_id": vendor_name}
            )

        # Sufficient evidence gathered to conclude price investigation
        return AgentAction(
            action="finish",
            reason="Completed price investigation across purchase order, invoice, authorization records, and vendor history."
        )

    # -------------------------------------------------------------
    # PATHWAY B: QUANTITY MISMATCH / DELIVERY SHORTAGE (Steps 34 & 35)
    # Target: PO -> Invoice -> Receipts
    # Never query authorizations or vendor history!
    # -------------------------------------------------------------
    is_qty_issue = any("QUANTITY" in dt or "SHORTAGE" in dt or "RECEIPT" in dt for dt in disc_types)
    if is_qty_issue:
        if "get_purchase_order" in allowed_tools and po_id and "get_purchase_order" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Need to verify ordered quantities on Purchase Order {po_id}.",
                tool="get_purchase_order",
                arguments={"po_id": po_id}
            )

        if "get_invoice" in allowed_tools and inv_id and "get_invoice" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Need to inspect billed quantities on Invoice {inv_id}.",
                tool="get_invoice",
                arguments={"invoice_id": inv_id}
            )

        if "get_receipt" in allowed_tools and receipt_ids and "get_receipt" not in executed_tools:
            first_receipt = receipt_ids[0]
            return AgentAction(
                action="investigate",
                reason=f"Need to inspect physical delivery confirmation and delivered quantities in Receipt {first_receipt}.",
                tool="get_receipt",
                arguments={"receipt_id": first_receipt}
            )

        # Receiving records checked -> conclude
        return AgentAction(
            action="finish",
            reason="Completed physical delivery receiving investigation across PO, invoice, and delivery receipts."
        )

    # -------------------------------------------------------------
    # PATHWAY C: UNAUTHORIZED CHARGES / SURCHARGES (Steps 34 & 35)
    # Target: PO -> Authorization
    # Never query receipts!
    # -------------------------------------------------------------
    is_charge_issue = any("UNAUTHORIZED" in dt or "CHARGE" in dt or "SHIPPING" in dt or "SURCHARGE" in dt for dt in disc_types)
    if is_charge_issue:
        if "get_purchase_order" in allowed_tools and po_id and "get_purchase_order" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Need to inspect authorized lines and fee terms on Purchase Order {po_id}.",
                tool="get_purchase_order",
                arguments={"po_id": po_id}
            )

        if "get_invoice" in allowed_tools and inv_id and "get_invoice" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Need to inspect billed surcharges and fee line items on Invoice {inv_id}.",
                tool="get_invoice",
                arguments={"invoice_id": inv_id}
            )

        if "check_authorization" in allowed_tools and po_id and "check_authorization" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Checking if supplemental charges were approved in change orders for PO {po_id}.",
                tool="check_authorization",
                arguments={"po_id": po_id, "discrepancy_type": "UNAUTHORIZED_CHARGE"}
            )

        return AgentAction(
            action="finish",
            reason="Completed unauthorized charge investigation across PO line agreements and authorizations."
        )

    # -------------------------------------------------------------
    # PATHWAY D: DUPLICATE INVOICE (Steps 34 & 35)
    # Target: Invoice -> Similar / Historical Invoices
    # -------------------------------------------------------------
    is_dup_issue = any("DUPLICATE" in dt for dt in disc_types)
    if is_dup_issue:
        if "get_invoice" in allowed_tools and inv_id and "get_invoice" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Inspecting full metadata for duplicate invoice candidate {inv_id}.",
                tool="get_invoice",
                arguments={"invoice_id": inv_id}
            )

        if "find_similar_invoices" in allowed_tools and vendor_name and "find_similar_invoices" not in executed_tools:
            return AgentAction(
                action="investigate",
                reason=f"Querying prior historical invoices for vendor '{vendor_name}' to corroborate duplicate submission.",
                tool="find_similar_invoices",
                arguments={"vendor_id": vendor_name, "item_description": "invoice"}
            )

        return AgentAction(
            action="finish",
            reason="Duplicate invoice records verified in historical ledger."
        )

    # -------------------------------------------------------------
    # General Fallback / Catch-All
    # -------------------------------------------------------------
    for tool_name in allowed_tools:
        if tool_name not in executed_tools and tool_name not in failed_tools:
            if tool_name == "get_purchase_order" and po_id:
                return AgentAction(action="investigate", reason="Querying PO records.", tool="get_purchase_order", arguments={"po_id": po_id})
            elif tool_name == "get_invoice" and inv_id:
                return AgentAction(action="investigate", reason="Querying Invoice records.", tool="get_invoice", arguments={"invoice_id": inv_id})
            elif tool_name == "get_receipt" and receipt_ids:
                return AgentAction(action="investigate", reason="Querying Receipt records.", tool="get_receipt", arguments={"receipt_id": receipt_ids[0]})

    return AgentAction(
        action="finish",
        reason="Concluded investigation: all policy-allowed document sources evaluated."
    )

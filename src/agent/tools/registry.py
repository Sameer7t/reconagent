"""
AI Investigation Agent Tools Registry & Execution Engine.

Implements AgentDataStore, central tool registry mapping,
security scoping, and duplicate tool protection.
"""
import re
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Any, Optional, Callable

from agent.state import InvestigationState
from agent.tools.purchase_order import get_purchase_order
from agent.tools.invoice import get_invoice
from agent.tools.receipt import get_receipt
from agent.tools.authorization import check_authorization
from agent.tools.vendor import get_vendor_history, find_similar_invoices
from agent.tools.validation import verify_document_arithmetic


# =====================================================================
# AGENT DATA STORE (Repository Pattern)
# =====================================================================

class AgentDataStore:
    """
    Mock/in-memory data repository backing the investigation tools.
    Can be populated from datasets, reconciliation results, or test fixtures.
    """
    _default_instance: Optional["AgentDataStore"] = None

    def __init__(self):
        self.purchase_orders: Dict[str, Dict[str, Any]] = {}
        self.invoices: Dict[str, Dict[str, Any]] = {}
        self.receipts: Dict[str, Dict[str, Any]] = {}
        self.vendor_history: Dict[str, List[Dict[str, Any]]] = {}
        self.authorizations: Dict[str, List[Dict[str, Any]]] = {}

    @classmethod
    def get_default(cls) -> "AgentDataStore":
        if cls._default_instance is None:
            cls._default_instance = AgentDataStore()
        return cls._default_instance

    @classmethod
    def reset_default(cls):
        cls._default_instance = AgentDataStore()

    def add_purchase_order(self, po_id: str, po_data: Dict[str, Any]):
        self.purchase_orders[po_id] = po_data

    def add_invoice(self, invoice_id: str, invoice_data: Dict[str, Any]):
        self.invoices[invoice_id] = invoice_data
        vendor = invoice_data.get("vendor_name") or (invoice_data.get("vendor", {}) or {}).get("name")
        if vendor:
            norm_vendor = self._normalize_vendor(vendor)
            if norm_vendor not in self.vendor_history:
                self.vendor_history[norm_vendor] = []
            for item in invoice_data.get("items", []):
                self.vendor_history[norm_vendor].append({
                    "invoice_id": invoice_id,
                    "date": invoice_data.get("invoice_date", ""),
                    "description": item.get("description", ""),
                    "unit_price": str(item.get("unit_price", "0.00")),
                    "quantity": str(item.get("quantity", "0")),
                })

    def add_receipt(self, receipt_id: str, receipt_data: Dict[str, Any]):
        self.receipts[receipt_id] = receipt_data

    def add_authorization(self, po_id: str, authorization_record: Dict[str, Any]):
        if po_id not in self.authorizations:
            self.authorizations[po_id] = []
        self.authorizations[po_id].append(authorization_record)

    def load_from_reconciliation_result(
        self,
        reconciliation_result: Dict[str, Any],
        po_data: Optional[Dict[str, Any]] = None,
        invoice_data: Optional[Dict[str, Any]] = None,
        receipts: Optional[List[Dict[str, Any]]] = None,
    ):
        """Loads contextual documents from a case into the store."""
        po_id = reconciliation_result.get("purchase_order_id")
        if po_id and po_data:
            self.add_purchase_order(po_id, po_data)

        inv_id = reconciliation_result.get("invoice_id")
        if inv_id and invoice_data:
            self.add_invoice(inv_id, invoice_data)

        for rcpt in (receipts or []):
            rcpt_id = rcpt.get("receipt_number")
            if rcpt_id:
                self.add_receipt(rcpt_id, rcpt)

    @staticmethod
    def _normalize_vendor(v: Optional[str]) -> str:
        if not v:
            return ""
        clean = v.lower()
        clean = re.sub(r"[^\w\s]", " ", clean)
        clean = re.sub(r"\b(inc|incorporated|llc|corp|corporation|ltd|limited|co|company)\b", "", clean)
        return " ".join(clean.split())


# =====================================================================
# CENTRAL TOOL REGISTRY MAPPINGS
# =====================================================================

TOOLS: Dict[str, Callable] = {
    "get_invoice": get_invoice,
    "get_purchase_order": get_purchase_order,
    "get_receipt": get_receipt,
    "get_vendor_history": get_vendor_history,
    "check_authorization": check_authorization,
    "find_similar_invoices": find_similar_invoices,
    "verify_document_arithmetic": verify_document_arithmetic,
}

TOOL_REQUIRED_ARGS: Dict[str, List[str]] = {
    "get_purchase_order": ["po_id"],
    "get_invoice": ["invoice_id"],
    "get_receipt": ["receipt_id"],
    "get_vendor_history": ["vendor_id"],
    "check_authorization": ["po_id", "discrepancy_type"],
    "find_similar_invoices": ["vendor_id", "item_description"],
    "verify_document_arithmetic": ["document_type", "document_id"],
}


def execute_tool(
    tool_name: str,
    arguments: Dict[str, Any],
    store: Optional[AgentDataStore] = None,
) -> Any:
    """
    Controlled single tool executor.
    Verifies that the requested tool is strictly in TOOLS,
    then executes the designated business operation.
    """
    if tool_name not in TOOLS:
        raise ValueError(f"Tool not allowed: {tool_name}")

    tool = TOOLS[tool_name]
    datastore = store or AgentDataStore.get_default()
    try:
        return tool(**arguments, store=datastore)
    except TypeError:
        return tool(**arguments)


# =====================================================================
# TOOL EXECUTION & CASE-SCOPING ENGINE
# =====================================================================

class ToolRegistry:
    """
    Production-grade Tool Execution Engine.
    Enforces whitelist, schema validation, policy rules, and case data isolation boundaries.
    """
    def __init__(self, datastore: Optional[AgentDataStore] = None):
        self.datastore = datastore or AgentDataStore.get_default()
        self.tools = dict(TOOLS)

    def validate_and_execute(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        state: InvestigationState,
    ) -> Dict[str, Any]:
        """
        Validates the tool request and executes it with case boundary enforcement.
        """
        # 1. Whitelist Check
        if tool_name not in self.tools:
            return {
                "status": "ERROR",
                "error": f"Tool '{tool_name}' is not allowed. Permitted tools: {sorted(self.tools.keys())}",
            }

        # 2. Argument Validation
        required_args = TOOL_REQUIRED_ARGS.get(tool_name, [])
        for req in required_args:
            if req not in arguments or arguments[req] is None or str(arguments[req]).strip() == "":
                return {
                    "status": "ERROR",
                    "error": f"Missing required argument '{req}' for tool '{tool_name}'.",
                }

        # 2.5 Investigation Policy Check
        from agent.policies import is_tool_allowed_for_case, get_allowed_tools_for_discrepancies
        if not is_tool_allowed_for_case(tool_name, state):
            allowed = get_allowed_tools_for_discrepancies(state.get("discrepancies", []))
            return {
                "status": "POLICY_VIOLATION",
                "error": f"Tool '{tool_name}' is not permitted by investigation policy for the reported discrepancies. Permitted tools: {sorted(allowed)}",
            }

        # 3. Case Boundary / Document Scoping Check
        case_id = state.get("case_id", "")
        rec_result = state.get("reconciliation_result", {})
        allowed_po = rec_result.get("purchase_order_id")
        allowed_inv = rec_result.get("invoice_id")
        allowed_receipts = rec_result.get("receipt_ids", [])

        if tool_name == "get_purchase_order":
            req_po = arguments.get("po_id", "").strip()
            if allowed_po and req_po != allowed_po:
                return {
                    "status": "UNAUTHORIZED",
                    "error": f"Access denied: Purchase Order '{req_po}' does not belong to case '{case_id}' (associated PO: '{allowed_po}').",
                }

        elif tool_name == "get_invoice":
            req_inv = arguments.get("invoice_id", "").strip()
            if allowed_inv and req_inv != allowed_inv:
                return {
                    "status": "UNAUTHORIZED",
                    "error": f"Access denied: Invoice '{req_inv}' does not belong to case '{case_id}' (associated Invoice: '{allowed_inv}').",
                }

        elif tool_name == "get_receipt":
            req_rcpt = arguments.get("receipt_id", "").strip()
            if allowed_receipts and req_rcpt not in allowed_receipts:
                return {
                    "status": "UNAUTHORIZED",
                    "error": f"Access denied: Receipt '{req_rcpt}' does not belong to case '{case_id}' (associated Receipts: {allowed_receipts}).",
                }

        elif tool_name == "check_authorization":
            req_po = arguments.get("po_id", "").strip()
            if allowed_po and req_po != allowed_po:
                return {
                    "status": "UNAUTHORIZED",
                    "error": f"Access denied: Authorization check for PO '{req_po}' does not belong to case '{case_id}'.",
                }

        elif tool_name == "verify_document_arithmetic":
            req_type = (arguments.get("document_type") or "").strip().lower()
            req_id = (arguments.get("document_id") or "").strip()
            if req_type in ("po", "purchase_order") and allowed_po and req_id != allowed_po:
                return {
                    "status": "UNAUTHORIZED",
                    "error": f"Access denied: Purchase Order '{req_id}' does not belong to case '{case_id}' (associated PO: '{allowed_po}').",
                }
            elif req_type in ("inv", "invoice") and allowed_inv and req_id != allowed_inv:
                return {
                    "status": "UNAUTHORIZED",
                    "error": f"Access denied: Invoice '{req_id}' does not belong to case '{case_id}' (associated Invoice: '{allowed_inv}').",
                }
            elif req_type in ("rcpt", "receipt") and allowed_receipts and req_id not in allowed_receipts:
                return {
                    "status": "UNAUTHORIZED",
                    "error": f"Access denied: Receipt '{req_id}' does not belong to case '{case_id}' (associated Receipts: {allowed_receipts}).",
                }

        # 4. Duplicate Tool Protection
        call_sig = f"{tool_name}:{json.dumps(arguments, sort_keys=True, default=str)}"
        past_sigs = [
            f"{tc.get('tool')}:{json.dumps(tc.get('arguments', {}), sort_keys=True, default=str)}"
            for tc in (state.get("tool_calls", []) or [])
            if tc.get("status") != "DUPLICATE_CALL"
        ]
        if call_sig in past_sigs:
            return {
                "status": "DUPLICATE_CALL",
                "error": f"Duplicate tool call blocked: '{tool_name}' with identical arguments {arguments} was already executed in this session.",
                "is_duplicate": True,
            }

        # 5. Execute tool
        fn = self.tools[tool_name]
        try:
            result = fn(**arguments, store=self.datastore)
        except TypeError:
            result = fn(**arguments)
        except Exception as err:
            result = {"status": "ERROR", "error": f"Tool execution failed: {str(err)}"}

        # 6. Record Tool Call Provenance in Agent State
        if isinstance(state, dict):
            if "tool_calls" not in state or state["tool_calls"] is None:
                state["tool_calls"] = []
            is_dict = isinstance(result, dict)
            is_success = ("error" not in result) if is_dict else True
            res_status = result.get("status", "SUCCESS" if is_success else "ERROR") if is_dict else "FOUND"
            audit_entry = {
                "tool": tool_name,
                "arguments": arguments,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "status": res_status,
                "success": is_success,
                "result": result,
            }
            if is_dict and not is_success:
                audit_entry["error"] = result.get("error")
            state["tool_calls"].append(audit_entry)
            state["tool_call_count"] = state.get("tool_call_count", 0) + 1

        return result


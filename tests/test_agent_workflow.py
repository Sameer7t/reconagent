
"""
Unit and Integration Tests for AI Investigation Agent Workflow, LangGraph Routing,
Duplicate Tool Protection, and Missing-Data Handling (Steps 21-25).

Tests:
1. Duplicate Tool Protection: blocks repeating identical queries (tool + arguments).
2. Duplicate Tool Allowed on Different Arguments: allows same tool with different args.
3. Missing-Data Outcomes & Semantics: explicit FOUND vs NOT_FOUND statuses.
4. Max Tool Calls Loop Prevention: MAX_TOOL_CALLS = 8 cutoff enforces exit to finalize.
5. LangGraph Full Autonomous Execution (Authorized Price Mismatch -> APPROVE_PAYMENT).
6. LangGraph Full Autonomous Execution (Unauthorized Price Mismatch -> REQUEST_CREDIT_MEMO).
7. LangGraph Full Autonomous Execution (Physical Delivery Shortage -> REQUEST_CREDIT_MEMO).
8. LangGraph Full Autonomous Execution (Duplicate Invoice -> REJECT_INVOICE).
9. Evidence Normalization and Executive Summary Generation.
"""
import sys
from decimal import Decimal
from pathlib import Path

# Path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from agent.state import InvestigationState, create_initial_state
from agent.models import Evidence, Finding, InvestigationResult, AgentAction
from agent.tools import (
    AgentDataStore,
    ToolRegistry,
    get_purchase_order,
    get_invoice,
    get_receipt,
    check_authorization,
)
from agent.nodes.finalize import finalize_node, create_investigation_result
from agent.workflow import (
    build_investigation_graph,
    run_investigation,
    MAX_TOOL_CALLS,
)


def _setup_workflow_test_datastore() -> AgentDataStore:
    """Creates a populated test datastore for workflow verification."""
    store = AgentDataStore()

    # PO-8831
    store.add_purchase_order("PO-8831", {
        "purchase_order_number": "PO-8831",
        "vendor_name": "Apex Global Logistics",
        "currency": "USD",
        "items": [
            {
                "product_code": "APX-SRV-01",
                "description": "Enterprise Cloud Server Unit",
                "quantity": Decimal("10"),
                "unit_price": Decimal("1500.00"),
                "line_total": Decimal("15000.00"),
            }
        ]
    })

    # INV-9001 (Authorized Price Adjustment case)
    store.add_invoice("INV-9001", {
        "invoice_number": "INV-9001",
        "purchase_order_number": "PO-8831",
        "vendor_name": "Apex Global Logistics",
        "currency": "USD",
        "invoice_date": "2024-03-01",
        "items": [
            {
                "product_code": "APX-SRV-01",
                "description": "Enterprise Cloud Server Unit",
                "quantity": Decimal("10"),
                "unit_price": Decimal("1700.00"),
                "line_total": Decimal("17000.00"),
            }
        ],
        "subtotal": Decimal("17000.00"),
        "total": Decimal("17000.00"),
    })

    # INV-9002 (Unauthorized Price Increase case)
    store.add_invoice("INV-9002", {
        "invoice_number": "INV-9002",
        "purchase_order_number": "PO-8831",
        "vendor_name": "Apex Global Logistics",
        "currency": "USD",
        "invoice_date": "2024-03-02",
        "items": [
            {
                "product_code": "APX-SRV-01",
                "description": "Enterprise Cloud Server Unit",
                "quantity": Decimal("10"),
                "unit_price": Decimal("1900.00"),
                "line_total": Decimal("19000.00"),
            }
        ],
        "subtotal": Decimal("19000.00"),
        "total": Decimal("19000.00"),
    })

    # DR-101 (Delivery Shortage: ordered 10, delivered 8)
    store.add_receipt("DR-101", {
        "receipt_number": "DR-101",
        "purchase_order_number": "PO-8831",
        "vendor_name": "Apex Global Logistics",
        "date": "2024-03-01",
        "items": [
            {
                "description": "Enterprise Cloud Server Unit",
                "quantity_ordered": Decimal("10"),
                "quantity": Decimal("8"),
            }
        ]
    })

    # DR-102 (Supplemental delivery: remaining 2)
    store.add_receipt("DR-102", {
        "receipt_number": "DR-102",
        "purchase_order_number": "PO-8831",
        "vendor_name": "Apex Global Logistics",
        "date": "2024-03-05",
        "items": [
            {
                "description": "Enterprise Cloud Server Unit",
                "quantity_ordered": Decimal("10"),
                "quantity": Decimal("2"),
            }
        ]
    })

    # Authorization for PO-8831 (Authorizes $1700 unit price, but NOT $1900)
    store.add_authorization("PO-8831", {
        "authorization_id": "AUTH-777",
        "discrepancy_type": "PRICE_MISMATCH",
        "approved_value": "1700.00",
        "approved_by_role": "vp_procurement",
        "notes": "Annual hardware index escalation approved.",
    })

    return store


# =====================================================================
# TEST 1 & 2: DUPLICATE TOOL PROTECTION (STEP 24)
# =====================================================================

def test_duplicate_tool_protection_blocks_identical():
    """Step 24: Verifies calling same tool with same args is blocked."""
    store = _setup_workflow_test_datastore()
    registry = ToolRegistry(datastore=store)

    state = create_initial_state({
        "case_id": "CASE-DUP-1",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-9001",
        "discrepancies": []
    })

    # First call: should succeed
    res1 = registry.validate_and_execute(
        "get_purchase_order",
        {"po_id": "PO-8831"},
        state
    )
    assert res1.get("status") == "FOUND"
    assert "error" not in res1
    assert state["tool_call_count"] == 1

    # Second call with IDENTICAL arguments: must be blocked
    res2 = registry.validate_and_execute(
        "get_purchase_order",
        {"po_id": "PO-8831"},
        state
    )
    assert res2.get("status") == "DUPLICATE_CALL"
    assert res2.get("is_duplicate") is True
    assert "Duplicate tool call blocked" in res2["error"]
    # State tool call count must not double
    assert state["tool_call_count"] == 1
    print("  PASS: test_duplicate_tool_protection_blocks_identical")


def test_duplicate_tool_protection_allows_different_args():
    """Step 24: Verifies calling same tool with different args is permitted."""
    store = _setup_workflow_test_datastore()
    registry = ToolRegistry(datastore=store)

    state = create_initial_state({
        "case_id": "CASE-DUP-2",
        "purchase_order_id": "PO-8831",
        "receipt_ids": ["DR-101", "DR-102"],
        "discrepancies": []
    })

    # Call 1: DR-101
    res1 = registry.validate_and_execute("get_receipt", {"receipt_id": "DR-101"}, state)
    assert res1.get("status") == "FOUND"
    assert res1.get("receipt_id") == "DR-101"

    # Call 2: DR-102 (same tool, different arguments) -> must succeed!
    res2 = registry.validate_and_execute("get_receipt", {"receipt_id": "DR-102"}, state)
    assert res2.get("status") == "FOUND"
    assert res2.get("receipt_id") == "DR-102"
    assert state["tool_call_count"] == 2
    print("  PASS: test_duplicate_tool_protection_allows_different_args")


# =====================================================================
# TEST 3: MISSING-DATA OUTCOMES & SEMANTICS (STEP 25)
# =====================================================================

def test_missing_data_semantics():
    """
    Step 25: Verifies explicit status outcomes (FOUND vs NOT_FOUND)
    and validates that NOT_FOUND means 'no record found on file'.
    """
    store = _setup_workflow_test_datastore()

    # Query existing PO
    po_found = get_purchase_order("PO-8831", store=store)
    assert po_found["status"] == "FOUND"
    assert po_found["po_id"] == "PO-8831"

    # Query non-existent PO
    po_missing = get_purchase_order("PO-NONEXISTENT", store=store)
    assert po_missing["status"] == "NOT_FOUND"
    assert "was not found on file" in po_missing["message"]

    # Query non-existent Invoice
    inv_missing = get_invoice("INV-NONEXISTENT", store=store)
    assert inv_missing["status"] == "NOT_FOUND"
    assert "was not found on file" in inv_missing["message"]

    # Query non-existent Receipt
    rcpt_missing = get_receipt("DR-NONEXISTENT", store=store)
    assert rcpt_missing["status"] == "NOT_FOUND"
    assert "was not found on file" in rcpt_missing["message"]

    # Query authorization for unapproved discrepancy type
    auth_res = check_authorization("PO-8831", discrepancy_type="UNAUTHORIZED_CHARGE", store=store)
    assert auth_res["status"] == "NOT_FOUND"
    assert auth_res["authorized"] is False
    assert "No authorization was found on file" in auth_res["message"]
    print("  PASS: test_missing_data_semantics")


# =====================================================================
# TEST 4: MAX TOOL CALLS CUTOFF (STEP 23)
# =====================================================================

def test_max_tool_calls_guard():
    """
    Step 23: Verifies that max_tool_calls = 2 forces the LangGraph state machine
    to route to finalize and exit cleanly without runaway iterations.
    """
    store = _setup_workflow_test_datastore()

    # Create a case with many discrepancies that would normally take 4+ tools
    case_data = {
        "case_id": "CASE-LIMIT-1",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-9001",
        "receipt_ids": ["DR-101"],
        "vendor_name": "Apex Global Logistics",
        "discrepancies": [
            {"type": "PRICE_MISMATCH", "expected_value": "1500.00", "actual_value": "1700.00"},
            {"type": "QUANTITY_SHORTAGE", "expected_value": "10", "actual_value": "8"},
            {"type": "UNAUTHORIZED_CHARGE", "actual_value": "500.00"},
        ]
    }

    # Restrict graph to maximum 2 tool calls
    graph = build_investigation_graph(datastore=store, max_tool_calls=2)
    initial_state = create_initial_state(case_data)

    final_state = graph.invoke(initial_state)

    # Must terminate and finalize
    assert final_state["status"] in ("COMPLETED", "REQUIRES_HUMAN_REVIEW")
    assert final_state["tool_call_count"] <= 2
    assert final_state["recommendation"] is not None
    assert len(final_state["findings"]) > 0
    print(f"  PASS: test_max_tool_calls_guard (stopped at {final_state['tool_call_count']} calls <= 2)")


# =====================================================================
# TEST 5-8: FULL LANGGRAPH AUTONOMOUS INVESTIGATION FLOWS (STEP 22)
# =====================================================================

def test_investigation_authorized_price_variance():
    """
    Scenario 1: Billed price is $1,700 vs PO $1,500.
    Authorization AUTH-777 approves $1,700.
    Agent should investigate PO, Invoice, Authorization and recommend APPROVE_PAYMENT.
    """
    store = _setup_workflow_test_datastore()

    case_data = {
        "case_id": "REC-AUTH-01",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-9001",
        "vendor_name": "Apex Global Logistics",
        "discrepancies": [
            {
                "type": "PRICE_MISMATCH",
                "expected_value": "1500.00",
                "actual_value": "1700.00",
                "explanation": "Invoice billed at $1,700.00 vs PO approved $1,500.00."
            }
        ]
    }

    result = run_investigation(case_data, datastore=store)

    assert isinstance(result, InvestigationResult)
    assert result.case_id == "REC-AUTH-01"
    assert result.recommendation == "APPROVE_PAYMENT"
    assert result.confidence == "HIGH"
    assert result.requires_human_review is False

    # Check evidence & findings
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.discrepancy_type == "PRICE_MISMATCH"
    assert "formal price escalation amendment was found on file" in finding.explanation
    assert len(finding.supporting_evidence_ids) >= 2
    print(f"  PASS: test_investigation_authorized_price_variance -> {result.recommendation}")


def test_investigation_unauthorized_price_variance():
    """
    Scenario 2: Billed price is $1,900 vs PO $1,500.
    No authorization exists for $1,900.
    Agent should investigate PO, Invoice, Authorization (finding NOT_FOUND)
    and recommend REQUEST_CREDIT_MEMO.
    """
    store = _setup_workflow_test_datastore()

    case_data = {
        "case_id": "REC-UNAUTH-02",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-9002",
        "vendor_name": "Apex Global Logistics",
        "discrepancies": [
            {
                "type": "PRICE_MISMATCH",
                "expected_value": "1500.00",
                "actual_value": "1900.00",
                "explanation": "Invoice billed at $1,900.00 vs PO rate $1,500.00."
            }
        ]
    }

    # Clear authorizations to ensure no match
    store.authorizations["PO-8831"] = []

    result = run_investigation(case_data, datastore=store)

    assert result.recommendation == "REQUEST_CREDIT_MEMO"
    assert result.confidence == "HIGH"
    assert result.requires_human_review is True

    finding = result.findings[0]
    assert "No formal price escalation or amendment authorization was found on file" in finding.explanation
    print(f"  PASS: test_investigation_unauthorized_price_variance -> {result.recommendation}")


def test_investigation_delivery_shortage():
    """
    Scenario 3: Vendor invoiced 10 units, but delivery receipt DR-101 confirms only 8 delivered.
    Agent should inspect delivery receipt and recommend REQUEST_CREDIT_MEMO.
    """
    store = _setup_workflow_test_datastore()

    case_data = {
        "case_id": "REC-SHORTAGE-03",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-9001",
        "receipt_ids": ["DR-101"],
        "vendor_name": "Apex Global Logistics",
        "discrepancies": [
            {
                "type": "QUANTITY_SHORTAGE",
                "expected_value": "10",
                "actual_value": "8",
                "explanation": "Delivered quantity 8 is less than invoiced quantity 10."
            }
        ]
    }

    result = run_investigation(case_data, datastore=store)

    assert result.recommendation == "REQUEST_CREDIT_MEMO"
    assert result.confidence == "HIGH"
    assert result.requires_human_review is True

    finding = result.findings[0]
    assert "Physical delivery shortage confirmed" in finding.explanation
    print(f"  PASS: test_investigation_delivery_shortage -> {result.recommendation}")


def test_investigation_duplicate_invoice():
    """
    Scenario 4: Duplicate invoice detected by reconciliation engine.
    Agent should recommend REJECT_INVOICE.
    """
    store = _setup_workflow_test_datastore()

    case_data = {
        "case_id": "REC-DUP-04",
        "invoice_id": "INV-9001",
        "vendor_name": "Apex Global Logistics",
        "discrepancies": [
            {
                "type": "DUPLICATE_INVOICE",
                "explanation": "Invoice fingerprint matches previously settled payment."
            }
        ]
    }

    result = run_investigation(case_data, datastore=store)

    assert result.recommendation == "REJECT_INVOICE"
    assert result.confidence == "HIGH"
    assert result.requires_human_review is True
    print(f"  PASS: test_investigation_duplicate_invoice -> {result.recommendation}")


# =====================================================================
# TEST 9: EVIDENCE NORMALIZATION & BRIEFING GENERATION (STEP 21)
# =====================================================================

def test_evidence_normalization_and_executive_briefing():
    """
    Step 21: Verifies evidence normalization schema and executive briefing output.
    """
    store = _setup_workflow_test_datastore()

    case_data = {
        "case_id": "REC-EXEC-05",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-9001",
        "receipt_ids": ["DR-101"],
        "vendor_name": "Apex Global Logistics",
        "discrepancies": [
            {
                "type": "PRICE_MISMATCH",
                "expected_value": "1500.00",
                "actual_value": "1700.00",
                "explanation": "Unit price difference."
            }
        ]
    }

    result = run_investigation(case_data, datastore=store)

    # Check evidence normalization fields (Step 21)
    assert len(result.evidence) >= 1
    for ev in result.evidence:
        assert ev.evidence_id.startswith("EVID-")
        assert ev.source_type in ("purchase_order", "invoice", "receipt", "authorization", "vendor_history", "similar_invoices")
        assert ev.source_id is not None
        assert ev.description != ""

    # Check executive summary formatting
    briefing = result.to_executive_summary()
    assert "=== INVESTIGATION REPORT: REC-EXEC-05 ===" in briefing
    assert "Recommendation: APPROVE_PAYMENT" in briefing
    assert "Findings (" in briefing
    assert "Evidence Records (" in briefing
    assert "EVID-" in briefing
    print("  PASS: test_evidence_normalization_and_executive_briefing")


def run_all_tests():
    print("\n" + "=" * 60)
    print("RUNNING AGENT WORKFLOW & LANGGRAPH INTEGRATION TEST SUITE")
    print("=" * 60)
    test_duplicate_tool_protection_blocks_identical()
    test_duplicate_tool_protection_allows_different_args()
    test_missing_data_semantics()
    test_max_tool_calls_guard()
    test_investigation_authorized_price_variance()
    test_investigation_unauthorized_price_variance()
    test_investigation_delivery_shortage()
    test_investigation_duplicate_invoice()
    test_evidence_normalization_and_executive_briefing()
    print("=" * 60)
    print("ALL AGENT WORKFLOW & LANGGRAPH TESTS PASSED (9/9)!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()


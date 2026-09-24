"""
Unit and Integration Tests for AI Investigation Agent Nodes & Reasoning Loop.

Tests:
1. System prompt rules (10 Golden Rules) & user prompt rendering
2. Analyze node decision logic (investigate vs finish)
3. Analyze node loop termination guard (MAX_INVESTIGATION_STEPS)
4. Tool node execution, Evidence synthesis, and provenance logging
5. End-to-end multi-step reasoning loop (Analyze -> Tool -> State -> Analyze -> Finish)
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
from agent.models import AgentAction, Evidence
from agent.prompts import INVESTIGATION_SYSTEM_PROMPT, build_analysis_user_prompt
from agent.tools import AgentDataStore, ToolRegistry
from agent.nodes.analyze import analyze, MAX_INVESTIGATION_STEPS
from agent.nodes.tools import execute_tool_node


def _create_mock_fixture_store() -> AgentDataStore:
    """Populates a test store with case REC-1001 data."""
    store = AgentDataStore()

    store.add_purchase_order("PO-8831", {
        "purchase_order_number": "PO-8831",
        "vendor_name": "TechTraders Solutions Inc.",
        "currency": "USD",
        "items": [
            {
                "product_code": "TT-CPU-109",
                "description": "Intel Core i9-13900K Processor",
                "quantity": Decimal("10"),
                "unit_price": Decimal("1500.00"),
                "line_total": Decimal("15000.00"),
            }
        ]
    })

    store.add_invoice("INV-4512", {
        "invoice_number": "INV-4512",
        "purchase_order_number": "PO-8831",
        "vendor_name": "TechTraders Solutions Inc.",
        "currency": "USD",
        "items": [
            {
                "product_code": "TT-CPU-109",
                "description": "Intel Core i9-13900K Processor",
                "quantity": Decimal("10"),
                "unit_price": Decimal("1700.00"),
                "line_total": Decimal("17000.00"),
            }
        ],
        "subtotal": Decimal("17000.00"),
        "total": Decimal("17000.00"),
    })

    store.add_receipt("DR-8831", {
        "receipt_number": "DR-8831",
        "purchase_order_number": "PO-8831",
        "vendor_name": "TechTraders Solutions Inc.",
        "date": "2024-02-15",
        "items": [
            {
                "description": "Intel Core i9-13900K Processor",
                "quantity_ordered": Decimal("10"),
                "quantity": Decimal("10"),
            }
        ]
    })

    store.add_authorization("PO-8831", {
        "authorization_id": "AUTH-44",
        "discrepancy_type": "PRICE_MISMATCH",
        "approved_value": "1700.00",
        "approved_by_role": "purchasing_manager",
        "notes": "Emergency vendor supply chain escalation approved."
    })

    return store


def test_prompts_and_golden_rules():
    """Verifies that the system prompt includes all 10 critical operational rules."""
    assert "1. Use available tools to gather evidence." in INVESTIGATION_SYSTEM_PROMPT
    assert "2. Base all findings strictly on retrieved evidence." in INVESTIGATION_SYSTEM_PROMPT
    assert "3. Never invent business records" in INVESTIGATION_SYSTEM_PROMPT
    assert "4. Never modify financial records" in INVESTIGATION_SYSTEM_PROMPT
    assert "5. Never unilaterally approve or reject payment" in INVESTIGATION_SYSTEM_PROMPT
    assert "6. Investigate each relevant discrepancy" in INVESTIGATION_SYSTEM_PROMPT
    assert "7. Stop when sufficient evidence exists" in INVESTIGATION_SYSTEM_PROMPT
    assert "8. Explicitly state when evidence is insufficient" in INVESTIGATION_SYSTEM_PROMPT
    assert "9. Reference specific Evidence IDs" in INVESTIGATION_SYSTEM_PROMPT
    assert "10. Return strictly structured output" in INVESTIGATION_SYSTEM_PROMPT

    # Test dynamic user prompt rendering
    mock_state: InvestigationState = {
        "case_id": "REC-1001",
        "reconciliation_result": {
            "purchase_order_id": "PO-8831",
            "invoice_id": "INV-4512",
            "receipt_ids": ["DR-8831"],
            "vendor_name": "TechTraders Solutions Inc."
        },
        "discrepancies": [
            {
                "type": "UNIT_PRICE_MISMATCH",
                "expected_value": "1500.00",
                "actual_value": "1700.00",
                "explanation": "Unit price mismatch."
            }
        ],
        "evidence": [
            {
                "evidence_id": "EVID-001",
                "source_type": "purchase_order",
                "source_id": "PO-8831",
                "field": "unit_price",
                "value": "1500.00",
                "description": "PO approved unit price is $1,500.00."
            }
        ],
        "tool_calls": [
            {"tool": "get_purchase_order", "arguments": {"po_id": "PO-8831"}, "success": True}
        ],
        "findings": [],
        "recommendation": None,
        "confidence": None,
        "requires_human_review": True,
        "status": "IN_PROGRESS",
        "tool_call_count": 1,
    }

    user_prompt = build_analysis_user_prompt(mock_state)
    assert "ACTIVE INVESTIGATION CASE: REC-1001" in user_prompt
    assert "TechTraders Solutions Inc." in user_prompt
    assert "UNIT_PRICE_MISMATCH" in user_prompt
    assert "EVID-001" in user_prompt
    assert "get_purchase_order" in user_prompt
    print("  PASS: test_prompts_and_golden_rules")


def test_analyze_node_decisions():
    """Verifies analyze node tool selection based on discrepancy state."""
    # Case with uninspected PO
    state = create_initial_state({
        "case_id": "REC-1001",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-4512",
        "receipt_ids": ["DR-8831"],
        "vendor_name": "TechTraders Solutions Inc.",
        "discrepancies": [
            {"type": "UNIT_PRICE_MISMATCH", "expected_value": "1500.00", "actual_value": "1700.00"}
        ]
    })

    action1 = analyze(state)
    assert action1.action == "investigate"
    assert action1.tool == "get_purchase_order"
    assert action1.arguments == {"po_id": "PO-8831"}

    # Simulate PO retrieved
    state["tool_calls"].append({"tool": "get_purchase_order", "arguments": {"po_id": "PO-8831"}, "success": True})
    state["tool_call_count"] = 1

    action2 = analyze(state)
    assert action2.action == "investigate"
    assert action2.tool == "get_invoice"

    # Simulate Invoice retrieved
    state["tool_calls"].append({"tool": "get_invoice", "arguments": {"invoice_id": "INV-4512"}, "success": True})
    state["tool_call_count"] = 2

    action3 = analyze(state)
    assert action3.action == "investigate"
    assert action3.tool == "check_authorization"
    print("  PASS: test_analyze_node_decisions")


def test_analyze_node_loop_termination_guard():
    """Verifies that analyze stops when tool call limit is reached."""
    state = create_initial_state({
        "case_id": "REC-1001",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-4512",
        "receipt_ids": ["DR-8831"],
        "discrepancies": [{"type": "UNIT_PRICE_MISMATCH"}]
    })
    state["tool_call_count"] = MAX_INVESTIGATION_STEPS

    action = analyze(state)
    assert action.action == "finish"
    assert "maximum investigation step limit" in action.reason
    print("  PASS: test_analyze_node_loop_termination_guard")


def test_tool_node_execution_and_evidence_conversion():
    """Verifies tool node execution, Evidence synthesis, and audit log generation."""
    store = _create_mock_fixture_store()
    registry = ToolRegistry(datastore=store)

    state = create_initial_state({
        "case_id": "REC-1001",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-4512",
        "receipt_ids": ["DR-8831"],
        "vendor_name": "TechTraders Solutions Inc.",
        "discrepancies": [{"type": "UNIT_PRICE_MISMATCH"}]
    })

    action = AgentAction(
        action="investigate",
        reason="Check PO lines",
        tool="get_purchase_order",
        arguments={"po_id": "PO-8831"}
    )

    updated_state = execute_tool_node(state, action, registry=registry)

    assert updated_state["tool_call_count"] == 1
    assert len(updated_state["tool_calls"]) == 1
    audit_entry = updated_state["tool_calls"][0]
    assert audit_entry["tool"] == "get_purchase_order"
    assert audit_entry["arguments"] == {"po_id": "PO-8831"}
    assert audit_entry["success"] is True
    assert "timestamp" in audit_entry

    # Check Evidence synthesized
    assert len(updated_state["evidence"]) >= 1
    ev0 = updated_state["evidence"][0]
    assert ev0["evidence_id"] == "EVID-001"
    assert ev0["source_type"] == "purchase_order"
    assert ev0["source_id"] == "PO-8831"
    assert ev0["value"] == "1500.00"
    print("  PASS: test_tool_node_execution_and_evidence_conversion")


def test_full_reasoning_loop():
    """Tests complete multi-turn reasoning loop: Analyze -> Tool -> State -> Finish."""
    store = _create_mock_fixture_store()
    registry = ToolRegistry(datastore=store)

    state = create_initial_state({
        "case_id": "REC-1001",
        "purchase_order_id": "PO-8831",
        "invoice_id": "INV-4512",
        "receipt_ids": ["DR-8831"],
        "vendor_name": "TechTraders Solutions Inc.",
        "discrepancies": [
            {"type": "UNIT_PRICE_MISMATCH", "expected_value": "1500.00", "actual_value": "1700.00"}
        ]
    })

    max_turns = 10
    turns = 0
    final_action = None

    while turns < max_turns:
        turns += 1
        action = analyze(state)
        if action.action == "finish":
            final_action = action
            break
        state = execute_tool_node(state, action, registry=registry)

    assert final_action is not None
    assert final_action.action == "finish"
    assert state["tool_call_count"] >= 3  # PO, Invoice, and Authorization checked
    assert len(state["evidence"]) >= 3     # Multiple evidence records accumulated
    assert len(state["tool_calls"]) == state["tool_call_count"]
    print(f"  PASS: test_full_reasoning_loop (finished in {turns} turns with {len(state['evidence'])} evidence records)")


def run_all_tests():
    print("\n" + "=" * 60)
    print("RUNNING AGENT NODES & REASONING LOOP TEST SUITE")
    print("=" * 60)
    test_prompts_and_golden_rules()
    test_analyze_node_decisions()
    test_analyze_node_loop_termination_guard()
    test_tool_node_execution_and_evidence_conversion()
    test_full_reasoning_loop()
    print("=" * 60)
    print("ALL AGENT NODES TESTS PASSED (5/5)!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()


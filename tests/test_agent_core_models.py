"""
Unit tests for AI Investigation Agent Core Foundation.

Tests:
1. InvestigationState definition & create_initial_state factory
2. Evidence model validation and serialization
3. Finding model linking to evidence IDs
4. InvestigationResult output model & executive summary rendering
5. AgentAction validation (allowed actions: 'investigate', 'finish', rejection of invalid actions)
6. Interoperability across `agent` and `agents` package namespaces
"""
import sys
from decimal import Decimal
from pathlib import Path

# Path setup
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# Test imports
from agent.state import InvestigationState, create_initial_state
from agent.models import (
    Evidence,
    Finding,
    InvestigationResult,
    AgentAction,
    ALLOWED_AGENT_ACTIONS,
)
from agents.models import Evidence as AgentsEvidence  # Test package alias
from schemas.reconciliation import (
    ReconciliationResult,
    ReconciliationStatus,
    Discrepancy,
    DiscrepancyType,
    Severity,
)


def test_investigation_state_from_reconciliation_result():
    """Verifies that InvestigationState initializes cleanly from a ReconciliationResult."""
    rec_result = ReconciliationResult(
        case_id="CASE-TEST-001",
        status=ReconciliationStatus.REVIEW_REQUIRED,
        purchase_order_id="PO-1001",
        invoice_id="INV-5001",
        discrepancies=[
            Discrepancy(
                type=DiscrepancyType.UNIT_PRICE_MISMATCH,
                severity=Severity.HIGH,
                po_line_id="PO-1001-L1",
                invoice_line_id="INV-5001-L1",
                expected_value="1500.00",
                actual_value="1700.00",
                variance=Decimal("200.00"),
                explanation="Unit price mismatch: expected $1500.00, got $1700.00."
            )
        ]
    )

    state = create_initial_state(rec_result)

    assert state["case_id"] == "CASE-TEST-001"
    assert state["status"] in ("PENDING", "INITIALIZED")
    assert len(state["discrepancies"]) == 1
    assert state["discrepancies"][0]["type"] == DiscrepancyType.UNIT_PRICE_MISMATCH
    assert state["evidence"] == []
    assert state["tool_calls"] == []
    assert state["findings"] == []
    assert state["recommendation"] is None
    assert state["requires_human_review"] is True
    assert state["tool_call_count"] == 0
    print("  PASS: test_investigation_state_from_reconciliation_result")


def test_evidence_model_creation_and_serialization():
    """Verifies Evidence model attributes and validation."""
    evidence = Evidence(
        evidence_id="EVID-001",
        source_type="purchase_order",
        source_id="PO-1001",
        field="unit_price",
        value="1500.00",
        description="PO approved unit price is $1,500.00."
    )

    assert evidence.evidence_id == "EVID-001"
    assert evidence.source_type == "purchase_order"
    assert evidence.source_id == "PO-1001"
    assert evidence.field == "unit_price"
    assert evidence.value == "1500.00"
    assert "1,500.00" in evidence.description

    d = evidence.model_dump()
    assert d["evidence_id"] == "EVID-001"
    print("  PASS: test_evidence_model_creation_and_serialization")


def test_finding_model_linking_to_evidence():
    """Verifies Finding model and linking to supporting evidence IDs."""
    finding = Finding(
        finding_id="FIND-001",
        discrepancy_type="PRICE_MISMATCH",
        explanation="Invoice unit price of $1,700 exceeds approved PO unit price of $1,500 without approved change order.",
        supporting_evidence_ids=["EVID-001", "EVID-002"],
        confidence="HIGH"
    )

    assert finding.finding_id == "FIND-001"
    assert finding.discrepancy_type == "PRICE_MISMATCH"
    assert len(finding.supporting_evidence_ids) == 2
    assert "EVID-001" in finding.supporting_evidence_ids
    assert finding.confidence == "HIGH"
    print("  PASS: test_finding_model_linking_to_evidence")


def test_investigation_result_and_summary():
    """Verifies final official InvestigationResult and executive summary output."""
    ev1 = Evidence(
        evidence_id="EVID-001",
        source_type="purchase_order",
        source_id="PO-1001",
        field="unit_price",
        value="1500.00",
        description="PO approved unit price is $1,500.00."
    )
    ev2 = Evidence(
        evidence_id="EVID-002",
        source_type="contract",
        source_id="CTR-2024-09",
        field="tier_pricing",
        value="1500.00",
        description="Vendor contract specifies standard fixed tier pricing at $1,500.00."
    )
    finding = Finding(
        finding_id="FIND-001",
        discrepancy_type="PRICE_MISMATCH",
        explanation="Vendor overbilled by $200.00 per unit without contractual or PO authorization.",
        supporting_evidence_ids=["EVID-001", "EVID-002"],
        confidence="HIGH"
    )

    inv_result = InvestigationResult(
        case_id="CASE-TEST-001",
        findings=[finding],
        evidence=[ev1, ev2],
        recommendation="REQUEST_CREDIT_MEMO",
        confidence="HIGH",
        requires_human_review=True
    )

    assert inv_result.case_id == "CASE-TEST-001"
    assert inv_result.recommendation == "REQUEST_CREDIT_MEMO"
    assert inv_result.requires_human_review is True
    assert len(inv_result.findings) == 1
    assert len(inv_result.evidence) == 2

    summary = inv_result.to_executive_summary()
    assert "INVESTIGATION REPORT: CASE-TEST-001" in summary
    assert "REQUEST_CREDIT_MEMO" in summary
    assert "FIND-001" in summary
    assert "EVID-001" in summary
    print("  PASS: test_investigation_result_and_summary")


def test_agent_action_validation():
    """Verifies AgentAction validation and permitted actions."""
    # Test valid 'investigate' action
    act_investigate = AgentAction(
        action="investigate",
        reason="Need to check if a change order exists for price variance.",
        tool="check_authorization",
        arguments={"po_id": "PO-1001"}
    )
    assert act_investigate.action == "investigate"
    assert act_investigate.tool == "check_authorization"
    assert act_investigate.arguments["po_id"] == "PO-1001"

    # Test valid 'finish' action with uppercase normalization
    act_finish = AgentAction(
        action="FINISH",
        reason="All evidence collected; findings synthesized."
    )
    assert act_finish.action == "finish"
    assert act_finish.tool is None

    # Test invalid action rejection
    invalid_caught = False
    try:
        AgentAction(
            action="execute_arbitrary_code",
            reason="Unsafe action"
        )
    except ValueError as e:
        invalid_caught = True
        assert "Invalid action" in str(e)

    assert invalid_caught, "Expected ValueError on invalid action"
    print("  PASS: test_agent_action_validation")


def test_package_namespaces_interoperability():
    """Verifies that both `agent` and `agents` package namespaces export identical models."""
    ev = AgentsEvidence(
        evidence_id="EVID-099",
        source_type="vendor_portal",
        source_id="PORTAL-1",
        description="Delivery confirmation log."
    )
    assert isinstance(ev, Evidence)
    print("  PASS: test_package_namespaces_interoperability")


def run_all_tests():
    print("\n" + "=" * 60)
    print("RUNNING AGENT CORE FOUNDATION TEST SUITE")
    print("=" * 60)
    test_investigation_state_from_reconciliation_result()
    test_evidence_model_creation_and_serialization()
    test_finding_model_linking_to_evidence()
    test_investigation_result_and_summary()
    test_agent_action_validation()
    test_package_namespaces_interoperability()
    print("=" * 60)
    print("ALL AGENT CORE FOUNDATION TESTS PASSED (6/6)!")
    print("=" * 60)


if __name__ == "__main__":
    run_all_tests()

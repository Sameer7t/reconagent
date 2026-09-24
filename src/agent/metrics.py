"""
AI Investigation Agent Evaluation Metrics.

Step 39: Implements production evaluation metrics:
1. Tool selection accuracy (did it select policy-permissible tools?)
2. Investigation completeness (did it investigate all relevant discrepancies?)
3. Evidence grounding rate (are findings backed by real evidence IDs?)
4. Hallucination rate (did it invent records or document IDs?)
5. Tool efficiency (how many tool queries were required?)
6. Structured-output validity (did it emit valid, compliant schema objects?)
7. Correct escalation rate (did it accurately identify when human review was needed?)
"""
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from agent.models import InvestigationResult
from agent.policies import get_allowed_tools_for_discrepancies
from agent.validation import validate_investigation_result


class CaseMetrics(BaseModel):
    """Evaluation metrics measured on a single investigation case."""
    case_id: str
    tool_selection_accuracy: float = Field(..., description="Proportion of tools matching investigation policy (0.0 - 1.0)")
    investigation_completeness: float = Field(..., description="Proportion of discrepancies investigated (0.0 - 1.0)")
    evidence_grounding_rate: float = Field(..., description="Proportion of findings with real, non-hallucinated evidence (0.0 - 1.0)")
    hallucination_rate: float = Field(..., description="Proportion of cited IDs that were fabricated (0.0 - 1.0)")
    tool_calls_count: int = Field(..., description="Total tool queries executed")
    structured_output_valid: bool = Field(..., description="True if output passed strict schema and post-validation")
    correct_escalation: bool = Field(..., description="True if human review flag correctly aligned with discrepancy status")


class AggregateMetricsReport(BaseModel):
    """Portfolio-level benchmark report across a test cohort."""
    total_cases: int
    mean_tool_selection_accuracy: float
    mean_investigation_completeness: float
    mean_evidence_grounding_rate: float
    mean_hallucination_rate: float
    mean_tool_calls_per_case: float
    structured_output_validity_rate: float
    correct_escalation_rate: float

    def render_summary(self) -> str:
        return "\n".join([
            "=" * 60,
            "AGENT EVALUATION BENCHMARK METRICS (PORTFOLIO REPORT)",
            "=" * 60,
            f"Total Cases Evaluated:         {self.total_cases}",
            f"Tool Selection Accuracy:       {self.mean_tool_selection_accuracy * 100:.1f}%",
            f"Investigation Completeness:    {self.mean_investigation_completeness * 100:.1f}%",
            f"Evidence Grounding Rate:       {self.mean_evidence_grounding_rate * 100:.1f}%",
            f"Hallucination Rate:            {self.mean_hallucination_rate * 100:.1f}%",
            f"Tool Efficiency (Mean Calls):  {self.mean_tool_calls_per_case:.2f} calls/case",
            f"Structured Output Validity:    {self.structured_output_validity_rate * 100:.1f}%",
            f"Correct Escalation Rate:       {self.correct_escalation_rate * 100:.1f}%",
            "=" * 60,
        ])


def evaluate_single_investigation(
    state: Dict[str, Any],
    result: InvestigationResult,
) -> CaseMetrics:
    """
    Computes rigorous quality and security metrics for one completed investigation.
    """
    discrepancies = state.get("discrepancies", [])
    tool_calls = state.get("tool_calls", [])
    allowed_tools = get_allowed_tools_for_discrepancies(discrepancies)

    # 1. Tool Selection Accuracy
    if tool_calls:
        policy_adherent_calls = sum(1 for tc in tool_calls if tc.get("tool") in allowed_tools)
        tool_selection_accuracy = policy_adherent_calls / len(tool_calls)
    else:
        tool_selection_accuracy = 1.0

    # 2. Investigation Completeness
    if discrepancies:
        disc_types = {str(d.get("type", "")).upper() for d in discrepancies}
        finding_types = {f.discrepancy_type.upper() for f in result.findings}
        covered = sum(1 for dt in disc_types if any(dt in ft or ft in dt for ft in finding_types))
        investigation_completeness = min(1.0, covered / len(disc_types))
    else:
        investigation_completeness = 1.0

    # 3. Evidence Grounding & Hallucination Rate
    valid_eids = {e.evidence_id for e in result.evidence}
    total_refs = 0
    valid_refs = 0
    hallucinated_refs = 0

    for f in result.findings:
        for eid in f.supporting_evidence_ids:
            total_refs += 1
            if eid in valid_eids:
                valid_refs += 1
            else:
                hallucinated_refs += 1

    grounding_rate = (valid_refs / total_refs) if total_refs > 0 else (1.0 if not result.findings else 0.0)
    hallucination_rate = (hallucinated_refs / total_refs) if total_refs > 0 else 0.0

    # 4. Structured Output Validity
    val_report = validate_investigation_result(result, state)
    structured_valid = val_report.is_valid

    # 5. Correct Escalation
    # Escalation is correct if:
    # - Case has unapproved price variance / shortage / duplicate / error -> requires_human_review is True
    # - Case is fully authorized clean match -> requires_human_review is False
    has_unresolved_issue = (result.recommendation != "APPROVE_PAYMENT")
    correct_escalation = (result.requires_human_review == has_unresolved_issue)

    return CaseMetrics(
        case_id=result.case_id,
        tool_selection_accuracy=round(tool_selection_accuracy, 3),
        investigation_completeness=round(investigation_completeness, 3),
        evidence_grounding_rate=round(grounding_rate, 3),
        hallucination_rate=round(hallucination_rate, 3),
        tool_calls_count=len(tool_calls),
        structured_output_valid=structured_valid,
        correct_escalation=correct_escalation,
    )


def aggregate_evaluation_metrics(metrics_list: List[CaseMetrics]) -> AggregateMetricsReport:
    """Aggregates single-case evaluation metrics across an entire test benchmark."""
    if not metrics_list:
        return AggregateMetricsReport(
            total_cases=0,
            mean_tool_selection_accuracy=1.0,
            mean_investigation_completeness=1.0,
            mean_evidence_grounding_rate=1.0,
            mean_hallucination_rate=0.0,
            mean_tool_calls_per_case=0.0,
            structured_output_validity_rate=1.0,
            correct_escalation_rate=1.0,
        )

    n = len(metrics_list)
    return AggregateMetricsReport(
        total_cases=n,
        mean_tool_selection_accuracy=sum(m.tool_selection_accuracy for m in metrics_list) / n,
        mean_investigation_completeness=sum(m.investigation_completeness for m in metrics_list) / n,
        mean_evidence_grounding_rate=sum(m.evidence_grounding_rate for m in metrics_list) / n,
        mean_hallucination_rate=sum(m.hallucination_rate for m in metrics_list) / n,
        mean_tool_calls_per_case=sum(m.tool_calls_count for m in metrics_list) / n,
        structured_output_validity_rate=sum(1 for m in metrics_list if m.structured_output_valid) / n,
        correct_escalation_rate=sum(1 for m in metrics_list if m.correct_escalation) / n,
    )


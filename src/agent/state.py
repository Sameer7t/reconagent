"""
AI Investigation Agent State Definition.

Defines the working memory schema for the ReconAgent investigation workflow.
Receives structured ReconciliationResult objects, never raw PDFs.
"""
from datetime import datetime, timezone
from typing import TypedDict, Any, List, Dict, Optional, Union


class InvestigationStatus:
    """
    Step 33: Explicit agent lifecycle states.
    Avoids ambiguous or non-standard states.
    """
    PENDING = "PENDING"
    INVESTIGATING = "INVESTIGATING"
    WAITING_FOR_TOOL = "WAITING_FOR_TOOL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    REQUIRES_HUMAN_REVIEW = "REQUIRES_HUMAN_REVIEW"


class InvestigationState(TypedDict, total=False):
    """
    Working memory of the AI Investigation Agent.
    Maintains provenance, tool history, gathered evidence, and synthesized findings.
    The reconciliation engine remains the sole source of truth for original discrepancies.
    """
    case_id: str

    reconciliation_result: dict
    discrepancies: list[dict]

    evidence: list[dict]
    findings: list[dict]

    selected_action: Optional[dict]
    tool_calls: list[dict]

    recommendation: Optional[str]
    confidence: Optional[str]
    requires_human_review: bool
    final_summary: Optional[str]

    status: str
    tool_call_count: int

    # Metadata & backward-compatibility aliases
    last_action: Optional[dict]
    investigation_result: Optional[dict]
    validation_report: Optional[dict]
    started_at: Optional[str]


def create_initial_state(
    reconciliation_result: Union[Dict[str, Any], Any],
    case_id: Optional[str] = None,
    **metadata,
) -> InvestigationState:
    """
    Initializes a fresh InvestigationState from a ReconciliationResult.
    The reconciliation engine is the authoritative source of truth for discrepancies.
    
    Args:
        reconciliation_result: Either a ReconciliationResult Pydantic model or a dictionary.
        case_id: Optional override for the case identifier.
        **metadata: Optional extra fields such as po_file, invoice_file, receipt_files, etc.
        
    Returns:
        A clean, initialized InvestigationState instance.
    """
    if hasattr(reconciliation_result, "model_dump"):
        result_dict = reconciliation_result.model_dump()
    elif isinstance(reconciliation_result, dict):
        result_dict = reconciliation_result
    else:
        result_dict = dict(reconciliation_result)

    resolved_case_id = (
        case_id
        or result_dict.get("case_id")
        or result_dict.get("purchase_order_id")
        or "UNKNOWN_CASE"
    )

    raw_discrepancies = result_dict.get("discrepancies", [])
    discrepancies_list = []
    for d in raw_discrepancies:
        if hasattr(d, "model_dump"):
            d_dict = d.model_dump()
        elif isinstance(d, dict):
            d_dict = dict(d)
        else:
            d_dict = dict(d)

        # Normalize type so it's a pure string like "CALCULATION_ERROR"
        raw_type = d_dict.get("type")
        if hasattr(raw_type, "value"):
            d_dict["type"] = str(raw_type.value)
        elif isinstance(raw_type, str):
            d_dict["type"] = raw_type.replace("DiscrepancyType.", "").strip()
        discrepancies_list.append(d_dict)

    state: InvestigationState = {
        "case_id": resolved_case_id,
        "reconciliation_result": result_dict,
        "discrepancies": discrepancies_list,
        "evidence": [],
        "findings": [],
        "selected_action": None,
        "tool_calls": [],
        "recommendation": None,
        "confidence": None,
        "requires_human_review": True,  # Default to review until investigation confirms otherwise
        "final_summary": None,
        "status": InvestigationStatus.PENDING,
        "tool_call_count": 0,
        "last_action": None,
        "investigation_result": None,
        "validation_report": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    state.update(metadata)
    return state


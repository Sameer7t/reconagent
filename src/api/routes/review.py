"""
Human Review Governance and Settlement Queue Endpoints.

Provides:
1. Queue Metrics (`GET /api/review/metrics`)
2. Review Queue List (`GET /api/review/queue`): Filterable by status (PENDING_REVIEW, APPROVED, OVERRIDDEN, ALL).
3. Case Briefing Dashboard (`GET /api/review/{case_id}`)
4. Specialist Decision Submission (`POST /api/review/{case_id}/decision`): Permanent sign-off / override persisted to SQLite.
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query

from api.dependencies import get_review_queue_dep
from api.schemas import (
    ReviewQueueMetricsResponse,
    ReviewItemResponse,
    ReviewQueueListResponse,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    DecisionActionRequest,
    FindingSchema,
    EvidenceSchema,
)
from agent.review_queue import ReviewQueueManager, ReviewItem
from api.routes.auth import require_role

router = APIRouter(tags=["Review Queue"])


def _to_review_item_response(item: ReviewItem) -> ReviewItemResponse:
    """Converts a domain ReviewItem to ReviewItemResponse."""
    findings = [
        FindingSchema(
            finding_id=f.finding_id,
            discrepancy_type=f.discrepancy_type,
            explanation=f.explanation,
            confidence=f.confidence,
            supporting_evidence_ids=f.supporting_evidence_ids,
        )
        for f in item.findings
    ]
    evidence = [
        EvidenceSchema(
            evidence_id=e.evidence_id,
            source_type=e.source_type,
            source_id=e.source_id,
            field=e.field,
            value=e.value,
            description=e.description,
        )
        for e in item.evidence
    ]

    return ReviewItemResponse(
        case_id=item.case_id,
        discrepancies=item.discrepancies,
        findings=findings,
        evidence=evidence,
        investigation_steps=item.investigation_steps,
        agent_recommendation=item.agent_recommendation,
        agent_confidence=item.agent_confidence,
        human_status=item.human_status,
        human_decision=item.human_decision,
        reviewer_notes=item.reviewer_notes,
        reviewed_by=item.reviewed_by,
        reviewed_at=item.reviewed_at,
        created_at=item.created_at,
        rendered_briefing=item.render_briefing(),
    )


@router.get("/metrics", response_model=ReviewQueueMetricsResponse)
def get_metrics(
    rq: ReviewQueueManager = Depends(get_review_queue_dep),
):
    """Returns real-time queue metrics and governance volume counts."""
    metrics = rq.get_metrics()
    return ReviewQueueMetricsResponse(
        total_count=metrics["total_count"],
        pending_count=metrics["pending_count"],
        auto_approved_count=metrics["auto_approved_count"],
        approved_count=metrics["approved_count"],
        overridden_count=metrics["overridden_count"],
    )


@router.get("", response_model=ReviewQueueListResponse)
@router.get("/queue", response_model=ReviewQueueListResponse)
def list_review_queue(
    status: str = Query("PENDING_REVIEW", description="Status filter: PENDING_REVIEW, APPROVED, OVERRIDDEN, or ALL"),
    rq: ReviewQueueManager = Depends(get_review_queue_dep),
):
    """
    Returns cases awaiting specialist review or past settled cases.
    """
    items = rq.list_all(status=status)
    metrics_dict = rq.get_metrics()
    metrics = ReviewQueueMetricsResponse(
        total_count=metrics_dict["total_count"],
        pending_count=metrics_dict["pending_count"],
        auto_approved_count=metrics_dict["auto_approved_count"],
        approved_count=metrics_dict["approved_count"],
        overridden_count=metrics_dict["overridden_count"],
    )

    return ReviewQueueListResponse(
        metrics=metrics,
        total=len(items),
        items=[_to_review_item_response(it) for it in items],
    )


@router.get("/{case_id}", response_model=ReviewItemResponse)
def get_review_item(
    case_id: str,
    rq: ReviewQueueManager = Depends(get_review_queue_dep),
):
    """
    Retrieves the complete human review package and rendered briefing dashboard for a case.
    """
    item = rq.get_item(case_id)
    if not item:
        raise HTTPException(
            status_code=404,
            detail=f"Case '{case_id}' was not found in the review queue.",
        )
    return _to_review_item_response(item)


@router.post("/{case_id}/decision", response_model=ReviewDecisionResponse, dependencies=[Depends(require_role(["Admin", "Reviewer"]))])
def submit_decision(
    case_id: str,
    payload: ReviewDecisionRequest,
    rq: ReviewQueueManager = Depends(get_review_queue_dep),
):
    """
    Submits specialist business decision:
    - APPROVE: confirms agent recommendation
    - OVERRIDE: overrides agent recommendation (e.g. approve with exception)
    - REJECT: confirms invoice rejection
    - ESCALATE: escalates to senior procurement
    Permanently records the decision and audit rationale in SQLite.
    """
    try:
        updated_item = rq.submit_decision(
            case_id=case_id,
            decision=payload.decision,
            reviewer_id=payload.reviewer_id,
            notes=payload.notes,
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Case '{case_id}' was not found in the review queue.",
        )

    return ReviewDecisionResponse(
        success=True,
        message=f"Decision '{payload.decision}' successfully recorded for case {case_id} by {payload.reviewer_id}.",
        item=_to_review_item_response(updated_item),
    )


@router.post("/{case_id}/approve", response_model=ReviewDecisionResponse, dependencies=[Depends(require_role(["Admin", "Reviewer"]))])
def approve_case(
    case_id: str,
    payload: Optional[DecisionActionRequest] = None,
    rq: ReviewQueueManager = Depends(get_review_queue_dep),
):
    """
    Human specialist approves the agent recommendation for the case.
    """
    p = payload or DecisionActionRequest()
    try:
        updated_item = rq.submit_decision(
            case_id=case_id,
            decision="APPROVE",
            reviewer_id=p.reviewer_id,
            notes=p.notes or "Human approved recommendation.",
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Case '{case_id}' was not found in the review queue.",
        )

    return ReviewDecisionResponse(
        success=True,
        message=f"Case {case_id} approved by {p.reviewer_id}.",
        item=_to_review_item_response(updated_item),
    )


@router.post("/{case_id}/reject", response_model=ReviewDecisionResponse, dependencies=[Depends(require_role(["Admin", "Reviewer"]))])
def reject_case(
    case_id: str,
    payload: Optional[DecisionActionRequest] = None,
    rq: ReviewQueueManager = Depends(get_review_queue_dep),
):
    """
    Human specialist rejects the invoice or recommendation.
    """
    p = payload or DecisionActionRequest()
    try:
        updated_item = rq.submit_decision(
            case_id=case_id,
            decision="REJECT_INVOICE",
            reviewer_id=p.reviewer_id,
            notes=p.notes or "Human rejected invoice.",
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Case '{case_id}' was not found in the review queue.",
        )

    return ReviewDecisionResponse(
        success=True,
        message=f"Case {case_id} rejected by {p.reviewer_id}.",
        item=_to_review_item_response(updated_item),
    )


@router.post("/{case_id}/escalate", response_model=ReviewDecisionResponse, dependencies=[Depends(require_role(["Admin", "Reviewer"]))])
def escalate_case(
    case_id: str,
    payload: Optional[DecisionActionRequest] = None,
    rq: ReviewQueueManager = Depends(get_review_queue_dep),
):
    """
    Human specialist escalates the case to senior finance leadership.
    """
    p = payload or DecisionActionRequest()
    try:
        updated_item = rq.submit_decision(
            case_id=case_id,
            decision="ESCALATE",
            reviewer_id=p.reviewer_id,
            notes=p.notes or "Escalated to senior finance leadership.",
        )
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Case '{case_id}' was not found in the review queue.",
        )

    return ReviewDecisionResponse(
        success=True,
        message=f"Case {case_id} escalated by {p.reviewer_id}.",
        item=_to_review_item_response(updated_item),
    )




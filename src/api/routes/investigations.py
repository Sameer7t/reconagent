"""
Autonomous AI Investigation Agent Routes.

Provides:
1. Investigation List (`GET /api/investigations`): Query past agent investigations.
2. Investigation Details (`GET /api/investigations/{case_id}`): Root causes, evidence citations, tool execution traces.
3. Trigger Investigation (`POST /api/investigations/{case_id}/run`): Re-runs an autonomous AI investigation for a case.
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, Query

from api.dependencies import get_db, get_orchestrator
from api.schemas import (
    InvestigationSummary,
    InvestigationListResponse,
    InvestigationDetailResponse,
    FindingSchema,
    EvidenceSchema,
    EventSchema,
    RunInvestigationRequest,
)
from agent.db import InvestigationDatabase
from pipeline.orchestrator import MasterOrchestrator

router = APIRouter(prefix="/investigations", tags=["Investigations"])


@router.get("", response_model=InvestigationListResponse)
def list_investigations(
    status: Optional[str] = Query(None, description="Filter by status (e.g. COMPLETED)"),
    requires_review: Optional[bool] = Query(None, description="Filter by requires_human_review"),
    search: Optional[str] = Query(None, description="Search by case_id"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: InvestigationDatabase = Depends(get_db),
):
    """
    Lists past AI agent investigations stored in durable SQLite persistence.
    """
    with db._get_connection() as conn:
        query = "SELECT * FROM investigations WHERE 1=1"
        params = []

        if status:
            query += " AND status = ?"
            params.append(status)

        if requires_review is not None:
            query += " AND requires_human_review = ?"
            params.append(1 if requires_review else 0)

        if search:
            query += " AND case_id LIKE ?"
            params.append(f"%{search}%")

        count_cur = conn.execute(f"SELECT COUNT(*) FROM ({query}) AS sub", params)
        total = count_cur.fetchone()[0]

        query += " ORDER BY completed_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        cur = conn.execute(query, params)
        rows = cur.fetchall()

    results: List[InvestigationSummary] = []
    for r in rows:
        d = dict(r)
        results.append(
            InvestigationSummary(
                id=d["id"],
                case_id=d["case_id"],
                status=d["status"],
                started_at=d.get("started_at"),
                completed_at=d.get("completed_at"),
                recommendation=d.get("recommendation"),
                confidence=d.get("confidence"),
                requires_human_review=bool(d.get("requires_human_review", 0)),
            )
        )

    return InvestigationListResponse(total=total, investigations=results)


@router.get("/{case_id}", response_model=InvestigationDetailResponse)
def get_investigation_detail(
    case_id: str,
    db: InvestigationDatabase = Depends(get_db),
):
    """
    Retrieves deep investigation results including root-cause findings,
    supporting evidence records, and tool execution traces for a case.
    """
    inv = db.get_investigation(case_id)
    if not inv:
        raise HTTPException(
            status_code=404,
            detail=f"Investigation for case '{case_id}' was not found.",
        )

    inv_id = inv["id"]
    findings_raw = db.get_investigation_findings(inv_id)
    evidence_raw = db.get_investigation_evidence(inv_id)
    events_raw = db.get_investigation_events(inv_id)
    review_dec = db.get_review_decision(case_id)

    findings: List[FindingSchema] = []
    for f in findings_raw:
        fid = f.get("id", "").split("_")[-1] if "_" in f.get("id", "") else f.get("id", "F1")
        findings.append(
            FindingSchema(
                finding_id=fid,
                discrepancy_type=f.get("discrepancy_type", "OTHER"),
                explanation=f.get("explanation", ""),
                confidence=f.get("confidence", "HIGH"),
                supporting_evidence_ids=[],
            )
        )

    evidence: List[EvidenceSchema] = []
    for e in evidence_raw:
        eid = e.get("id", "").split("_")[-1] if "_" in e.get("id", "") else e.get("id", "E1")
        evidence.append(
            EvidenceSchema(
                evidence_id=eid,
                source_type=e.get("source_type", "document"),
                source_id=e.get("source_id", ""),
                field=e.get("field"),
                value=e.get("value"),
                description=e.get("description", ""),
            )
        )

    events: List[EventSchema] = []
    for ev in events_raw:
        events.append(
            EventSchema(
                id=ev.get("id", ""),
                event_type=ev.get("event_type", "TOOL_CALL"),
                tool_name=ev.get("tool_name"),
                arguments=ev.get("arguments"),
                result=ev.get("result"),
                created_at=ev.get("created_at", ""),
            )
        )

    return InvestigationDetailResponse(
        id=inv_id,
        case_id=inv["case_id"],
        status=inv["status"],
        started_at=inv.get("started_at"),
        completed_at=inv.get("completed_at"),
        recommendation=inv.get("recommendation"),
        confidence=inv.get("confidence"),
        requires_human_review=bool(inv.get("requires_human_review", 0)),
        final_summary=inv.get("final_summary"),
        findings=findings,
        evidence=evidence,
        events=events,
        human_decision=review_dec,
    )


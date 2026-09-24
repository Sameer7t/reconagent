"""
AI Investigation Agent Human Review Gate & Queue Manager.

Step 29: Implements the human governance layer for cases flagged with requires_human_review = True.
Provides end-to-end presentation of:
- Original discrepancy
- Agent finding
- Gathered evidence
- Investigation tool steps
- Recommendation
And records human business sign-off or decision override.
"""
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

from agent.models import Finding, Evidence, InvestigationResult


class ReviewItem(BaseModel):
    """
    Complete human review package for an unresolved or review-flagged case.
    """
    case_id: str
    discrepancies: List[Dict[str, Any]] = Field(default_factory=list)
    findings: List[Finding] = Field(default_factory=list)
    evidence: List[Evidence] = Field(default_factory=list)
    investigation_steps: List[Dict[str, Any]] = Field(default_factory=list)
    agent_recommendation: str
    agent_confidence: str
    human_status: str = Field(default="PENDING_REVIEW")  # PENDING_REVIEW, APPROVED, OVERRIDDEN, REJECTED, ESCALATED
    human_decision: Optional[str] = None
    reviewer_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def render_briefing(self) -> str:
        """
        Renders a clean human reviewer briefing dashboard.
        """
        lines = [
            "=" * 65,
            f"HUMAN REVIEW DASHBOARD: CASE {self.case_id}",
            "=" * 65,
            f"Review Status:        {self.human_status}",
            f"Agent Recommendation: {self.agent_recommendation} (Confidence: {self.agent_confidence})",
            "",
            "1. ORIGINAL DISCREPANCIES IDENTIFIED BY RECONCILIATION ENGINE:",
        ]
        for idx, d in enumerate(self.discrepancies, start=1):
            exp = d.get("expected_value", "N/A")
            act = d.get("actual_value", "N/A")
            lines.append(f"   [{idx}] {d.get('type')}: Expected={exp} vs Actual={act} | {d.get('explanation', '')}")

        lines.append("\n2. AGENT INVESTIGATION FINDINGS (ROOT CAUSE ANALYSIS):")
        for f in self.findings:
            refs = ", ".join(f.supporting_evidence_ids) if f.supporting_evidence_ids else "None"
            lines.append(f"   [{f.finding_id}] {f.discrepancy_type} ({f.confidence} confidence):")
            lines.append(f"       Root Cause: {f.explanation}")
            lines.append(f"       Evidence:   {refs}")

        lines.append(f"\n3. AUDIT PROVENANCE EVIDENCE GATHERED ({len(self.evidence)} records):")
        for e in self.evidence:
            val = f"={e.value}" if e.value else ""
            lines.append(f"   [{e.evidence_id}] {e.source_type.upper()} ({e.source_id}): {e.field}{val}")
            lines.append(f"       Details: {e.description}")

        lines.append(f"\n4. INVESTIGATION STEPS TAKEN ({len(self.investigation_steps)} tool queries):")
        for idx, s in enumerate(self.investigation_steps, start=1):
            t_name = s.get("tool", "unknown")
            args = s.get("arguments", {})
            succ = "SUCCESS" if s.get("success", False) else "FAILED"
            lines.append(f"   Step {idx}: {t_name}({args}) -> [{succ}]")

        if self.human_decision:
            lines.append("\n5. HUMAN REVIEWER SETTLEMENT DECISION:")
            lines.append(f"   Decision:    {self.human_decision} ({self.human_status})")
            lines.append(f"   Reviewer:    {self.reviewed_by}")
            lines.append(f"   Timestamp:   {self.reviewed_at}")
            lines.append(f"   Audit Notes: {self.reviewer_notes}")

        lines.append("=" * 65)
        return "\n".join(lines)


class ReviewQueueManager:
    """
    Central review queue manager handling enqueuing, review retrieval,
    and human decision approval/overrides.
    """
    def __init__(self, db: Optional[Any] = None):
        self.queue: Dict[str, ReviewItem] = {}
        self.db = db

    def hydrate_from_db(self, db: Optional[Any] = None) -> int:
        """
        Hydrates in-memory review queue from durable SQLite persistence layer.
        Loads all cases flagged with requires_human_review = 1.
        """
        active_db = db or self.db
        if not active_db:
            return 0

        loaded = 0
        try:
            # 1. Fetch investigations requiring human review
            with active_db._get_connection() as conn:
                cur = conn.execute(
                    "SELECT * FROM investigations WHERE requires_human_review = 1 ORDER BY completed_at DESC"
                )
                inv_rows = [dict(r) for r in cur.fetchall()]

            # 2. Fetch existing decisions
            decisions_by_case = {}
            for dec in active_db.list_review_decisions():
                decisions_by_case[dec["case_id"]] = dec

            for inv in inv_rows:
                case_id = inv["case_id"]
                if case_id in self.queue:
                    continue

                inv_id = inv["id"]
                findings_raw = active_db.get_investigation_findings(inv_id)
                evidence_raw = active_db.get_investigation_evidence(inv_id)
                events_raw = active_db.get_investigation_events(inv_id)

                findings = [
                    Finding(
                        finding_id=f.get("id", "").split("_")[-1] if "_" in f.get("id", "") else f.get("id", "F1"),
                        discrepancy_type=f.get("discrepancy_type", "OTHER"),
                        explanation=f.get("explanation", ""),
                        confidence=f.get("confidence", "HIGH"),
                    )
                    for f in findings_raw
                ]
                evidence = [
                    Evidence(
                        evidence_id=e.get("id", "").split("_")[-1] if "_" in e.get("id", "") else e.get("id", "E1"),
                        source_type=e.get("source_type", "document"),
                        source_id=e.get("source_id", ""),
                        field=e.get("field"),
                        value=e.get("value"),
                        description=e.get("description", ""),
                    )
                    for e in evidence_raw
                ]

                # Check if decision was already recorded
                dec = decisions_by_case.get(case_id)
                human_status = dec["status"] if dec else "PENDING_REVIEW"
                human_decision = dec["decision"] if dec else None
                reviewer_notes = dec["notes"] if dec else None
                reviewed_by = dec["reviewer_id"] if dec else None
                reviewed_at = dec["reviewed_at"] if dec else None

                item = ReviewItem(
                    case_id=case_id,
                    discrepancies=[],
                    findings=findings,
                    evidence=evidence,
                    investigation_steps=events_raw,
                    agent_recommendation=inv.get("recommendation", "ESCALATE_TO_BUYER"),
                    agent_confidence=inv.get("confidence", "HIGH"),
                    human_status=human_status,
                    human_decision=human_decision,
                    reviewer_notes=reviewer_notes,
                    reviewed_by=reviewed_by,
                    reviewed_at=reviewed_at,
                    created_at=inv.get("completed_at") or datetime.now(timezone.utc).isoformat(),
                )
                self.queue[case_id] = item
                loaded += 1
        except Exception:
            pass

        return loaded

    def enqueue(
        self,
        case_id: str,
        discrepancy_count: int = 0,
        recommendation: str = "ESCALATE_TO_BUYER",
        confidence: str = "HIGH",
        requires_human_review: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
        discrepancies: Optional[List[Dict[str, Any]]] = None,
        findings: Optional[List[Finding]] = None,
        evidence: Optional[List[Evidence]] = None,
        investigation_steps: Optional[List[Dict[str, Any]]] = None,
    ) -> ReviewItem:
        """Enqueues case or logs auto-approval into queue history."""
        status = "PENDING_REVIEW" if requires_human_review else "AUTO_APPROVED"
        item = ReviewItem(
            case_id=case_id,
            discrepancies=discrepancies or [],
            findings=findings or [],
            evidence=evidence or [],
            investigation_steps=investigation_steps or [],
            agent_recommendation=recommendation,
            agent_confidence=confidence,
            human_status=status,
        )
        self.queue[case_id] = item
        return item

    def get_metrics(self) -> Dict[str, int]:
        """Returns high-level queue metrics."""
        pending = sum(1 for item in self.queue.values() if item.human_status == "PENDING_REVIEW")
        approved = sum(1 for item in self.queue.values() if item.human_status in ("APPROVED", "AUTO_APPROVED"))
        auto_approved = sum(1 for item in self.queue.values() if item.human_status == "AUTO_APPROVED")
        overridden = sum(1 for item in self.queue.values() if item.human_status == "OVERRIDDEN")
        return {
            "total_count": len(self.queue),
            "pending_count": pending,
            "auto_approved_count": auto_approved,
            "approved_count": approved,
            "overridden_count": overridden,
        }

    def enqueue_if_needed(
        self,
        state: Dict[str, Any],
        result: InvestigationResult,
    ) -> Optional[ReviewItem]:
        """Enqueues case if requires_human_review is True."""
        if not result.requires_human_review:
            return None

        item = ReviewItem(
            case_id=result.case_id,
            discrepancies=state.get("discrepancies", []),
            findings=result.findings,
            evidence=result.evidence,
            investigation_steps=state.get("tool_calls", []),
            agent_recommendation=result.recommendation,
            agent_confidence=result.confidence,
            human_status="PENDING_REVIEW",
        )
        self.queue[result.case_id] = item
        return item

    def list_pending(self) -> List[ReviewItem]:
        """Returns all cases awaiting human specialist review."""
        return [item for item in self.queue.values() if item.human_status == "PENDING_REVIEW"]

    def get_item(self, case_id: str) -> Optional[ReviewItem]:
        """Retrieves a specific review item by case ID."""
        return self.queue.get(case_id)

    def list_all(self, status: Optional[str] = None) -> List[ReviewItem]:
        """Returns all review items, optionally filtered by human_status."""
        if status and status.upper() != "ALL":
            return [item for item in self.queue.values() if item.human_status.upper() == status.upper()]
        return list(self.queue.values())

    def submit_decision(
        self,
        case_id: str,
        decision: str,
        reviewer_id: str,
        notes: str,
    ) -> ReviewItem:
        """
        Records human specialist business decision:
        - APPROVE: confirms agent recommendation
        - OVERRIDE: overrides agent recommendation (e.g. APPROVE_PAYMENT on approved business exception)
        - REJECT: confirms invoice rejection
        - ESCALATE: escalates to senior procurement
        """
        item = self.queue.get(case_id)
        if not item:
            raise KeyError(f"Case '{case_id}' is not in the human review queue.")

        clean_dec = decision.strip().upper()
        if clean_dec == item.agent_recommendation:
            status = "APPROVED"
        elif clean_dec in ("OVERRIDE", "APPROVE_PAYMENT", "REQUEST_CREDIT_MEMO", "REJECT_INVOICE"):
            status = "OVERRIDDEN" if clean_dec != item.agent_recommendation else "APPROVED"
        else:
            status = "RESOLVED"

        item.human_status = status
        item.human_decision = clean_dec
        item.reviewer_notes = notes
        item.reviewed_by = reviewer_id
        item.reviewed_at = datetime.now(timezone.utc).isoformat()

        if self.db:
            try:
                self.db.save_review_decision(
                    case_id=case_id,
                    decision=clean_dec,
                    status=status,
                    reviewer_id=reviewer_id,
                    notes=notes,
                    reviewed_at=item.reviewed_at,
                )
            except Exception:
                pass

        return item


# Default singleton
_default_review_queue: Optional[ReviewQueueManager] = None


def get_review_queue(db: Optional[Any] = None) -> ReviewQueueManager:
    global _default_review_queue
    if _default_review_queue is None:
        _default_review_queue = ReviewQueueManager(db=db)
        if db:
            _default_review_queue.hydrate_from_db(db)
    elif db and _default_review_queue.db is None:
        _default_review_queue.db = db
        _default_review_queue.hydrate_from_db(db)
    return _default_review_queue



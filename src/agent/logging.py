"""
AI Investigation Agent Structured Logging & Observability Layer.

Implements structured JSON logging (Step 31) and hierarchical execution trace trees (Step 40)
without leaking sensitive PII or credentials.
"""
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("ReconAgent")


class TraceEvent(BaseModel):
    """A discrete operation step within an investigation trace."""
    event_type: str = Field(..., description="Type of event: ANALYZE, TOOL, FINALIZE, VALIDATION")
    name: str = Field(..., description="Action name or tool name, e.g. 'get_purchase_order'")
    status: str = Field(default="SUCCESS", description="Outcome: SUCCESS, ERROR, NOT_FOUND, DUPLICATE")
    latency_ms: float = Field(default=0.0, description="Duration in milliseconds")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    details: Dict[str, Any] = Field(default_factory=dict, description="Metadata and parameters")


class InvestigationTrace(BaseModel):
    """
    Step 40: Hierarchical observability trace for an investigation session.
    Allows end-to-end debugging of LLM reasoning, tool calls, and final decision flow.
    """
    case_id: str
    investigation_id: str
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    completed_at: Optional[str] = None
    status: str = "IN_PROGRESS"
    recommendation: Optional[str] = None
    confidence: Optional[str] = None
    steps: List[TraceEvent] = Field(default_factory=list)

    def add_step(
        self,
        event_type: str,
        name: str,
        status: str = "SUCCESS",
        latency_ms: float = 0.0,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.steps.append(TraceEvent(
            event_type=event_type,
            name=name,
            status=status,
            latency_ms=round(latency_ms, 2),
            details=details or {},
        ))

    def complete(self, recommendation: str, confidence: str, status: str = "COMPLETED"):
        self.completed_at = datetime.now(timezone.utc).isoformat()
        self.recommendation = recommendation
        self.confidence = confidence
        self.status = status

    def render_trace_tree(self) -> str:
        """
        Renders a human-readable ASCII hierarchical execution trace tree.
        """
        lines = [
            f"{self.case_id}",
            f" └── {self.investigation_id} ({self.status} - {self.recommendation or 'IN_PROGRESS'})"
        ]
        for idx, step in enumerate(self.steps):
            is_last = (idx == len(self.steps) - 1)
            prefix = "      └── " if is_last else "      ├── "
            latency_str = f"({step.latency_ms}ms)" if step.latency_ms > 0 else ""
            status_str = f"[{step.status}]" if step.status != "SUCCESS" else ""
            lines.append(f"{prefix}[{step.event_type}] {step.name} {status_str} {latency_str}".rstrip())

        return "\n".join(lines)


class AgentLogger:
    """
    Step 31: Structured JSON and Console Event Logger.
    """
    def __init__(self, json_mode: bool = False):
        self.json_mode = json_mode
        self.traces: Dict[str, InvestigationTrace] = {}

    def get_or_create_trace(self, case_id: str, investigation_id: Optional[str] = None) -> InvestigationTrace:
        if case_id not in self.traces:
            inv_id = investigation_id or f"INV-RUN-{int(time.time()*1000)%1000000:06d}"
            self.traces[case_id] = InvestigationTrace(case_id=case_id, investigation_id=inv_id)
        return self.traces[case_id]

    def log_event(self, event_name: str, data: Dict[str, Any]):
        """Emits structured log entry without leaking sensitive credentials."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": event_name,
            **data,
        }
        if self.json_mode:
            print(json.dumps(entry, default=str))
        else:
            logger.info(f"[{event_name.upper()}] " + " | ".join(f"{k}={v}" for k, v in data.items()))

    def investigation_started(self, case_id: str, discrepancy_count: int, discrepancy_types: List[str]):
        trace = self.get_or_create_trace(case_id)
        self.log_event("investigation_started", {
            "case_id": case_id,
            "investigation_id": trace.investigation_id,
            "discrepancy_count": discrepancy_count,
            "types": discrepancy_types,
        })

    def agent_action_selected(self, case_id: str, action: str, tool: Optional[str], reason: str):
        self.log_event("agent_action_selected", {
            "case_id": case_id,
            "action": action,
            "tool": tool,
            "reason": reason[:120],
        })

    def tool_called(self, case_id: str, tool_name: str, arguments: Dict[str, Any]):
        # Sanitize arguments (remove any sensitive headers/tokens if present)
        sanitized = {k: v for k, v in arguments.items() if "token" not in k.lower() and "secret" not in k.lower()}
        self.log_event("tool_called", {
            "case_id": case_id,
            "tool": tool_name,
            "arguments": sanitized,
        })

    def tool_finished(self, case_id: str, tool_name: str, status: str, duration_ms: float):
        trace = self.get_or_create_trace(case_id)
        trace.add_step(
            event_type="TOOL",
            name=tool_name,
            status=status,
            latency_ms=duration_ms,
        )
        self.log_event("tool_finished", {
            "case_id": case_id,
            "tool": tool_name,
            "status": status,
            "duration_ms": round(duration_ms, 2),
        })

    def evidence_added(self, case_id: str, evidence_id: str, source_type: str, source_id: str):
        self.log_event("evidence_added", {
            "case_id": case_id,
            "evidence_id": evidence_id,
            "source_type": source_type,
            "source_id": source_id,
        })

    def investigation_completed(
        self,
        case_id: str,
        recommendation: str,
        confidence: str,
        requires_human_review: bool,
    ):
        trace = self.get_or_create_trace(case_id)
        trace.complete(recommendation=recommendation, confidence=confidence)
        self.log_event("investigation_completed", {
            "case_id": case_id,
            "investigation_id": trace.investigation_id,
            "recommendation": recommendation,
            "confidence": confidence,
            "requires_human_review": requires_human_review,
        })


# Default singleton
_default_logger: Optional[AgentLogger] = None


def get_agent_logger() -> AgentLogger:
    global _default_logger
    if _default_logger is None:
        _default_logger = AgentLogger()
    return _default_logger


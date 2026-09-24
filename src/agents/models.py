"""Forwarding module to src/agent/models.py for package compatibility."""
from agent.models import (
    Evidence,
    Finding,
    InvestigationResult,
    AgentAction,
    ALLOWED_AGENT_ACTIONS,
)

__all__ = [
    "Evidence",
    "Finding",
    "InvestigationResult",
    "AgentAction",
    "ALLOWED_AGENT_ACTIONS",
]


"""Agents package for invoice reconciliation and discrepancy investigation."""
from agent.state import InvestigationState, create_initial_state, InvestigationStatus
from agent.models import (
    Evidence,
    Finding,
    InvestigationResult,
    AgentAction,
    ALLOWED_AGENT_ACTIONS,
)
from agent.tools import (
    AgentDataStore,
    get_purchase_order,
    get_invoice,
    get_receipt,
    get_vendor_history,
    check_authorization,
    find_similar_invoices,
    TOOLS,
    ToolRegistry,
)
from agent.policies import (
    INVESTIGATION_POLICY,
    get_allowed_tools_for_discrepancies,
    is_tool_allowed_for_case,
)
from agent.validation import (
    validate_evidence_grounding,
    validate_investigation_result,
    ValidationReport,
)
from agent.nodes.finalize import finalize_node, create_investigation_result
from agent.workflow import (
    build_investigation_graph,
    run_investigation,
    MAX_TOOL_CALLS,
)
from agent.review_queue import (
    ReviewItem,
    ReviewQueueManager,
    get_review_queue,
)
from agent.db import InvestigationDatabase
from agent.logging import (
    AgentLogger,
    InvestigationTrace,
    get_agent_logger,
)
from agent.metrics import (
    evaluate_single_investigation,
    aggregate_evaluation_metrics,
    CaseMetrics,
    AggregateMetricsReport,
)
from agent.router import (
    GeminiModelRouter,
    DEFAULT_MODEL_CASCADE,
    route_extraction,
)

__all__ = [
    "InvestigationState",
    "create_initial_state",
    "InvestigationStatus",
    "Evidence",
    "Finding",
    "InvestigationResult",
    "AgentAction",
    "ALLOWED_AGENT_ACTIONS",
    "AgentDataStore",
    "get_purchase_order",
    "get_invoice",
    "get_receipt",
    "get_vendor_history",
    "check_authorization",
    "find_similar_invoices",
    "TOOLS",
    "ToolRegistry",
    "INVESTIGATION_POLICY",
    "get_allowed_tools_for_discrepancies",
    "is_tool_allowed_for_case",
    "validate_evidence_grounding",
    "validate_investigation_result",
    "ValidationReport",
    "finalize_node",
    "create_investigation_result",
    "build_investigation_graph",
    "run_investigation",
    "MAX_TOOL_CALLS",
    "ReviewItem",
    "ReviewQueueManager",
    "get_review_queue",
    "InvestigationDatabase",
    "AgentLogger",
    "InvestigationTrace",
    "get_agent_logger",
    "evaluate_single_investigation",
    "aggregate_evaluation_metrics",
    "CaseMetrics",
    "AggregateMetricsReport",
]

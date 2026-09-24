"""
AI Investigation Agent StateGraph (LangGraph).

Assembles the autonomous investigation state machine:
- StateGraph(InvestigationState)
- Conditional Routing: analyze -> tool -> analyze, with exit to finalize
- MAX_TOOL_CALLS = 8 hard cutoff to prevent runaway loops
- Duplicate tool protection enforcement
- Discrepancy-aware purposeful tool selection
- Grounding and deterministic post-validation in finalize node
- Automatic SQLite persistence and Human Review Queue integration
"""
import time
from typing import Dict, Any, Optional
from langgraph.graph import StateGraph, END

from agent.state import InvestigationState, create_initial_state, InvestigationStatus
from agent.models import AgentAction, InvestigationResult
from agent.tools import ToolRegistry, AgentDataStore
from agent.nodes.analyze import analyze
from agent.nodes.execute_tool import execute_tool_node
from agent.nodes.finalize import finalize_node, create_investigation_result
from agent.logging import get_agent_logger, AgentLogger
from agent.db import InvestigationDatabase
from agent.review_queue import get_review_queue, ReviewQueueManager

# Maximum investigation steps before forcing conclusion
MAX_TOOL_CALLS = 8


def build_investigation_graph(
    datastore: Optional[AgentDataStore] = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
    client: Optional[Any] = None,
    agent_logger: Optional[AgentLogger] = None,
):
    """
    Constructs and compiles the production LangGraph state graph.
    """
    store = datastore or AgentDataStore.get_default()
    registry = ToolRegistry(datastore=store)
    log = agent_logger or get_agent_logger()

    # 1. Define Node Functions
    def analyze_step(state: InvestigationState) -> InvestigationState:
        """Evaluates case evidence and decides next strategic action."""
        tool_call_count = state.get("tool_call_count", 0)
        case_id = state.get("case_id", "UNKNOWN")

        # Enforce loop termination guard
        if tool_call_count >= max_tool_calls:
            action = AgentAction(
                action="finish",
                reason=f"Reached maximum investigation step limit ({max_tool_calls}). Concluding with available evidence."
            )
        else:
            action = analyze(state, client=client)

        action_dict = action.model_dump()
        state["selected_action"] = action_dict
        state["last_action"] = action_dict
        state["status"] = InvestigationStatus.INVESTIGATING

        log.agent_action_selected(
            case_id=case_id,
            action=action.action,
            tool=action.tool,
            reason=action.reason,
        )

        trace = log.get_or_create_trace(case_id)
        trace.add_step(
            event_type="ANALYZE",
            name=f"action={action.action}" + (f":{action.tool}" if action.tool else ""),
            status="SUCCESS",
            details={"reason": action.reason},
        )
        return state

    def tool_step(state: InvestigationState) -> InvestigationState:
        """Executes selected tool, normalizes evidence, and updates provenance."""
        act_dict = state.get("selected_action") or state.get("last_action") or {}
        action = AgentAction(**act_dict)
        case_id = state.get("case_id", "UNKNOWN")
        tool_name = action.tool or "unknown_tool"

        state["status"] = InvestigationStatus.WAITING_FOR_TOOL
        log.tool_called(case_id=case_id, tool_name=tool_name, arguments=action.arguments)

        t_start = time.perf_counter()
        updated_state = execute_tool_node(state, action=action, registry=registry)
        duration_ms = (time.perf_counter() - t_start) * 1000

        # Check last tool call status
        last_tc = (updated_state.get("tool_calls") or [{}])[-1]
        status = last_tc.get("status", "SUCCESS" if last_tc.get("success") else "ERROR")

        log.tool_finished(case_id=case_id, tool_name=tool_name, status=status, duration_ms=duration_ms)
        return updated_state

    # 2. Define Conditional Routing Function
    def route_after_analyze(state: InvestigationState) -> str:
        """Routes to either 'execute_tool' or 'finalize' based on tool count and action."""
        if state.get("tool_call_count", 0) >= max_tool_calls:
            return "finalize"

        act_dict = state.get("selected_action") or state.get("last_action") or {}
        action_type = act_dict.get("action", "finish")

        if action_type == "finish":
            return "finalize"
        return "execute_tool"

    # 3. Assemble LangGraph StateGraph
    workflow = StateGraph(InvestigationState)

    workflow.add_node("analyze", analyze_step)
    workflow.add_node("execute_tool", tool_step)
    workflow.add_node("finalize", finalize_node)

    workflow.set_entry_point("analyze")

    workflow.add_conditional_edges(
        "analyze",
        route_after_analyze,
        {
            "execute_tool": "execute_tool",
            "finalize": "finalize",
        }
    )

    workflow.add_edge("execute_tool", "analyze")
    workflow.add_edge("finalize", END)

    return workflow.compile()


def run_investigation(
    reconciliation_result: Any,
    datastore: Optional[AgentDataStore] = None,
    max_tool_calls: int = MAX_TOOL_CALLS,
    client: Optional[Any] = None,
    db: Optional[InvestigationDatabase] = None,
    review_queue: Optional[ReviewQueueManager] = None,
    agent_logger: Optional[AgentLogger] = None,
    **metadata,
) -> InvestigationResult:
    """
    Convenience end-to-end runner that executes an investigation from a ReconciliationResult.
    The reconciliation engine remains the sole source of truth for original discrepancies.
    Handles logging, graph invocation, relational persistence, and human review enqueuing.
    """
    initial_state = create_initial_state(reconciliation_result, **metadata)
    case_id = initial_state["case_id"]
    disc_types = [str(d.get("type", "")) for d in initial_state.get("discrepancies", [])]

    log = agent_logger or get_agent_logger()
    log.investigation_started(
        case_id=case_id,
        discrepancy_count=len(initial_state.get("discrepancies", [])),
        discrepancy_types=disc_types,
    )

    graph = build_investigation_graph(
        datastore=datastore,
        max_tool_calls=max_tool_calls,
        client=client,
        agent_logger=log,
    )

    final_state = graph.invoke(initial_state)
    result = create_investigation_result(final_state)

    log.investigation_completed(
        case_id=case_id,
        recommendation=result.recommendation,
        confidence=result.confidence,
        requires_human_review=result.requires_human_review,
    )

    # Relational Database Persistence
    database = db or InvestigationDatabase()
    database.save_investigation(final_state, result, **metadata)

    # Human Review Queue Gate
    queue = review_queue or get_review_queue()
    queue.enqueue_if_needed(final_state, result)

    return result


"""
Workflow alias module.
Re-exports StateGraph implementation from agent.graph.
"""
from agent.graph import (
    build_investigation_graph,
    run_investigation,
    MAX_TOOL_CALLS,
)

__all__ = [
    "build_investigation_graph",
    "run_investigation",
    "MAX_TOOL_CALLS",
]

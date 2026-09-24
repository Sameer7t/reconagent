"""Forwarding module to src/agent/nodes/__init__.py for package compatibility."""
from agent.nodes import analyze, execute_tool_node, MAX_INVESTIGATION_STEPS

__all__ = ["analyze", "execute_tool_node", "MAX_INVESTIGATION_STEPS"]


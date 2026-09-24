"""
Tool Execution Node compatibility alias.
Exports execute_tool_node from agent.nodes.execute_tool.
"""
from agent.nodes.execute_tool import execute_tool_node, _convert_tool_result_to_evidence

__all__ = ["execute_tool_node", "_convert_tool_result_to_evidence"]

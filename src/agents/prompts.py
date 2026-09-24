"""Forwarding module to src/agent/prompts.py for package compatibility."""
from agent.prompts import INVESTIGATION_SYSTEM_PROMPT, build_analysis_user_prompt

__all__ = ["INVESTIGATION_SYSTEM_PROMPT", "build_analysis_user_prompt"]


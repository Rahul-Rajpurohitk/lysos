"""Lysos Workbench agent layer.

Multi-agent orchestration via LangGraph:
  - Designer (Gemma 4 31B-it) — proposes candidate SMILES
  - Critic   (Gemma 4 31B-it w/ critic prompt) — scores + identifies weakness
  - Editor   (rule-based RDKit + tools) — applies critic's suggestion
  - Strategist (rules-based) — terminates loop, manages curriculum

The LLM is abstracted via agents.llm.LLMEndpoint so we can swap:
  - Claude Sonnet 4.7 (pre-Day-4 placeholder)
  - vLLM Gemma 4 31B-it on MI300X (post-Day-4 production)
  - OpenAI / Gemini APIs (alternative backends)
"""
from .state import WorkbenchState, AgentMessage, Candidate, ToolCallRecord
from .llm import LLMEndpoint, get_llm
from .graph import build_workbench_graph

__all__ = [
    "WorkbenchState", "AgentMessage", "Candidate", "ToolCallRecord",
    "LLMEndpoint", "get_llm",
    "build_workbench_graph",
]

"""Lysos Workbench Tool Registry.

MCP-compatible, K-Dense Skill-format-compatible tool registry. Every tool:
  - Pydantic-typed inputs + outputs
  - Decorated with @tool to auto-register
  - Exposed as JSON schema for LLM function-calling
  - Reusable across Claude / GPT-4 / Gemma 4 31B / local LLMs

Categories:
  - amr/         5 AMR-specific tools (NEW — first set in Open Agent Skills)
  - scoring/     6 property/reward tools
  - generative/  4 transformation tools (REINVENT 4, PocketXMol)
  - structural/  3 docking + structure tools (Boltz-2, DiffDock)
  - knowledge/   4 retrieval + explanation tools
  - sandbox/     3 execution + visualization tools

Total: 25 tools. All implementations live alongside their schemas.
"""
from .base import Tool, ToolRegistry, tool, registry

# Auto-import categories so @tool decorators register at import time
from . import amr  # noqa: F401
from . import scoring  # noqa: F401
from . import generative  # noqa: F401
from . import structural  # noqa: F401
from . import knowledge  # noqa: F401
from . import sandbox  # noqa: F401
from . import chem_workbench  # noqa: F401  — molecule edit / inspect / match / valid-actions / diagnostics

__all__ = ["Tool", "ToolRegistry", "tool", "registry"]

"""Lysos agent harness — orchestration layer.

Pattern: lifted from atikan-agentic-module + atlas-terminal/atlas/harness,
adapted for chemistry/AMR domain.

Components:
- skills_loader: dynamic context assembly from config/skills/*.md
- orchestrator: pipeline (resolve → review → supervise → act) per request
- session_store: DB-backed session state (sessions, candidates, sandbox cells)
- tracer: structured event log for every command, tool call, and edit

Public API (what the FastAPI server uses):
    from workspace.agents.harness import Harness
    h = Harness()
    response = await h.handle_message(session_id, user_text, user_id)
"""

from .orchestrator import Harness  # noqa: F401
from .skills_loader import SkillsLoader  # noqa: F401

__all__ = ["Harness", "SkillsLoader"]

"""WorkbenchState — the LangGraph state schema.

Persistable to Postgres `agent_events` table. Every transition appends an
event; replay = walk the events forward; branching = fork from any event.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

class Constraint(BaseModel):
    """A user-imposed constraint on candidates the agent proposes."""
    type: Literal["property_min", "property_max", "exclude_smarts", "require_smarts"]
    field: str  # e.g. "qed", "logp", "smarts"
    value: Any  # number for property; SMARTS string for substructure


# ---------------------------------------------------------------------------
# Candidate
# ---------------------------------------------------------------------------

class CandidateScores(BaseModel):
    validity: float = 0.0
    structural_alerts: float = 0.0
    predicted_mic: float = 0.0
    drug_likeness_qed: float = 0.0
    synthesizability: float = 0.0
    hemolysis_safety: float = 0.0
    novelty: float = 0.0
    embedding_novelty: float = 0.0
    composite: float = 0.0


class Candidate(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    smiles: str
    parent_id: Optional[str] = None
    pathogen: str
    scores: CandidateScores = Field(default_factory=CandidateScores)
    affinity_kcal_mol: Optional[float] = None
    similar_to: list[str] = Field(default_factory=list)  # known drug names
    notes: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Agent messages + tool calls
# ---------------------------------------------------------------------------

class ToolCallRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tool: str
    args: dict
    result: Optional[dict] = None
    error: Optional[str] = None
    duration_ms: int = 0
    agent: str = "system"
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: Literal["system", "user", "designer", "critic", "editor", "strategist", "tool"]
    content: str
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    confidence: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Top-level WorkbenchState
# ---------------------------------------------------------------------------

class WorkbenchState(BaseModel):
    session_id: str
    target_pathogen: Literal["MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
                             "Abaum", "Paer", "VRE", "NGono"]
    mode: Literal["design", "red_team", "compare"] = "design"
    autonomy: Literal["auto", "copilot", "manual"] = "copilot"
    constraints: list[Constraint] = Field(default_factory=list)
    candidates: list[Candidate] = Field(default_factory=list)
    current_candidate_id: Optional[str] = None
    history: list[AgentMessage] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    resistome_summary: Optional[dict] = None  # cached get_pathogen_resistome result
    pareto_frontier: list[str] = Field(default_factory=list)  # candidate IDs
    iteration: int = 0
    max_iterations: int = 8
    terminated: bool = False
    termination_reason: Optional[str] = None

    # Each transition is appended to events for replay/branching
    events: list[dict] = Field(default_factory=list)

    def add_message(self, msg: AgentMessage) -> None:
        self.history.append(msg)
        self.events.append({
            "type": "message", "role": msg.role,
            "content": msg.content[:500],
            "ts": msg.created_at.isoformat(),
        })

    def add_candidate(self, cand: Candidate) -> None:
        self.candidates.append(cand)
        self.current_candidate_id = cand.id
        self.events.append({
            "type": "candidate", "id": cand.id, "smiles": cand.smiles,
            "ts": cand.created_at.isoformat(),
        })
        # Update Pareto frontier (greedy)
        self._update_pareto()

    def _update_pareto(self) -> None:
        """Maintain Pareto-frontier by composite + novelty axes."""
        if not self.candidates:
            return
        front: list[Candidate] = []
        for c in self.candidates:
            dominated = False
            for o in self.candidates:
                if o.id == c.id:
                    continue
                if (o.scores.composite >= c.scores.composite
                        and o.scores.novelty >= c.scores.novelty
                        and (o.scores.composite > c.scores.composite
                             or o.scores.novelty > c.scores.novelty)):
                    dominated = True
                    break
            if not dominated:
                front.append(c)
        self.pareto_frontier = [c.id for c in front]

"""Slash command framework — extensible chat command system.

Pattern lifted from ATLAS (atlas/agent/commands.py) which itself follows
Claude Code's `/commands/` structure. Adapted for Lysos's drug-design
domain: every command maps to a skill in SKILLS.md.

Three command types:
- LOCAL: executes locally, returns result directly (e.g. /score, /edit)
- PROMPT: sends to LLM with specific tool constraints (e.g. /design)
- SYSTEM: internal session ops (e.g. /clear, /run, /branch)

Each command:
- name, aliases, description, argument_hint
- type (LOCAL / PROMPT / SYSTEM)
- is_enabled(ctx) check
- execute(args, ctx) → CommandResult

The registry is consumed by:
- Chat composer ("/" → autocomplete picker filtered by typed prefix)
- Server route POST /api/commands/exec (for direct invocation)
- Help renderer (/help → produces a markdown table of available commands)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

log = logging.getLogger("workbench.agents.commands")

REPO_ROOT = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class CommandType(str, Enum):
    LOCAL = "local"      # Runs in-process, returns result directly to user
    PROMPT = "prompt"    # Sends to LLM with tool constraints
    SYSTEM = "system"    # Session-level (clear, run, branch, save)


@dataclass
class CommandResult:
    """What every command returns."""
    output: str = ""                    # markdown to render in chat
    error: str = ""                     # set if execution failed
    data: dict[str, Any] = field(default_factory=dict)    # structured payload
    artifact: Optional[dict] = None     # opt: scene/cell artifact for right panel
    should_send_to_llm: bool = False    # PROMPT-type sets this True
    follow_ups: list[str] = field(default_factory=list)   # next-action suggestions


@dataclass
class CommandContext:
    """Runtime context passed to every command."""
    session_id: str
    user_id: str
    active_smiles: Optional[str] = None     # currently-selected candidate
    active_target: Optional[str] = None     # currently-selected pathogen/target
    sandbox: Any = None                     # SandboxRuntime ref
    llm: Any = None                         # LLMEndpoint ref
    settings: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Base + Registry
# ---------------------------------------------------------------------------

@dataclass
class Command:
    name: str
    description: str
    type: CommandType = CommandType.LOCAL
    argument_hint: str = ""
    aliases: list[str] = field(default_factory=list)
    requires_smiles: bool = False           # gate: needs an active candidate
    requires_target: bool = False           # gate: needs a target

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        raise NotImplementedError(f"Command '{self.name}' has no execute()")

    def is_enabled(self, ctx: CommandContext) -> tuple[bool, str]:
        if self.requires_smiles and not ctx.active_smiles:
            return False, f"/{self.name} needs an active candidate. Try /design or /paste-smiles first."
        if self.requires_target and not ctx.active_target:
            return False, f"/{self.name} needs a target pathogen. Try /set-target <pathogen>."
        return True, ""


class CommandRegistry:
    """In-memory registry. Built once at server startup from create_default_registry()."""

    def __init__(self):
        self._by_name: dict[str, Command] = {}

    def register(self, cmd: Command) -> None:
        if cmd.name in self._by_name:
            raise ValueError(f"command name '{cmd.name}' already registered")
        self._by_name[cmd.name] = cmd
        for alias in cmd.aliases:
            if alias in self._by_name:
                raise ValueError(f"alias '{alias}' collides")
            self._by_name[alias] = cmd

    def get(self, name: str) -> Optional[Command]:
        return self._by_name.get(name.lstrip("/"))

    def search(self, prefix: str = "") -> list[Command]:
        prefix = prefix.lstrip("/")
        seen: set[str] = set()
        out: list[Command] = []
        for name, cmd in self._by_name.items():
            if cmd.name in seen:
                continue
            if name.startswith(prefix):
                out.append(cmd)
                seen.add(cmd.name)
        return sorted(out, key=lambda c: c.name)

    def all(self) -> list[Command]:
        return self.search("")


# ---------------------------------------------------------------------------
# Built-in commands
# ---------------------------------------------------------------------------

class HelpCommand(Command):
    def __init__(self):
        super().__init__(
            name="help", description="List all slash commands",
            type=CommandType.SYSTEM, aliases=["?", "skills"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        skills_md = REPO_ROOT / "SKILLS.md"
        if skills_md.exists():
            content = skills_md.read_text()
        else:
            content = "_SKILLS.md missing._"
        return CommandResult(output=content, data={"skills_md_path": str(skills_md)})


class ClearCommand(Command):
    def __init__(self):
        super().__init__(
            name="clear", description="Reset the chat & state",
            type=CommandType.SYSTEM,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        return CommandResult(
            output="Session cleared. Active candidate + sandbox state wiped.",
            data={"action": "clear_session", "session_id": ctx.session_id},
        )


class DesignCommand(Command):
    """W1 — kicks off a real multi-agent design session.

    Parses `<pathogen> [objective text]` from args, creates a WorkbenchState,
    spawns run_workbench_loop in the background, and returns the session_id
    so the frontend can subscribe to /workbench/sessions/{id}/events (SSE).

    The Designer/Critic/Editor/Strategist debate happens server-side; the
    chat panel renders agent_message + candidate_added events as they
    stream in.
    """

    PATHOGEN_CODES = {"MRSA", "Mtb", "EColi-CRE", "KpneuCRE",
                       "Abaum", "Paer", "VRE", "NGono"}
    PATHOGEN_ALIASES = {
        "mrsa": "MRSA", "mtb": "Mtb", "tb": "Mtb",
        "ecoli": "EColi-CRE", "ecoli-cre": "EColi-CRE", "e.coli": "EColi-CRE",
        "kpneu": "KpneuCRE", "kpneucre": "KpneuCRE", "klebsiella": "KpneuCRE",
        "abaum": "Abaum", "acinetobacter": "Abaum",
        "paer": "Paer", "pseudomonas": "Paer",
        "vre": "VRE", "ngono": "NGono", "gonorrhea": "NGono",
    }

    def __init__(self):
        super().__init__(
            name="design",
            description="Start a multi-agent design session",
            type=CommandType.LOCAL,
            argument_hint="<pathogen> [objective]",
            aliases=["d"],
        )

    @classmethod
    def _resolve_pathogen(cls, token: str, fallback: Optional[str]) -> str:
        """Map a user token to a canonical pathogen code, fall back to ctx."""
        if not token:
            return fallback or "MRSA"
        if token in cls.PATHOGEN_CODES:
            return token
        return cls.PATHOGEN_ALIASES.get(token.lower(), fallback or "MRSA")

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        # Parse: first token is pathogen (or alias); the rest is the objective
        # Examples:
        #   "MRSA"
        #   "MRSA non-toxic macrolide that escapes mecA"
        #   "mrsa β-lactam"
        head, _, tail = args.strip().partition(" ")
        pathogen = self._resolve_pathogen(head, ctx.active_target)
        objective = tail.strip() or None

        try:
            # Direct in-process call — no HTTP roundtrip needed
            from api.workbench import workbench_design, DesignRequest
        except ImportError as exc:
            return CommandResult(error=f"design route not available: {exc}")

        try:
            req = DesignRequest(
                pathogen=pathogen,
                objective=objective,
                constraints=[],
                max_iterations=8,
            )
            resp = await workbench_design(req)
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"design start failed: {exc}")

        line = f"design session started for **{pathogen}**"
        if objective:
            line += f" — *{objective}*"

        return CommandResult(
            output=line,
            data={
                "session_id": resp.session_id,
                "pathogen": resp.pathogen,
                "objective": resp.objective,
                "sse_url": resp.sse_url,
                "status": resp.status,
            },
            follow_ups=[
                "/score <smiles>  (when a candidate appears)",
                "/branch <smiles>  (stress-test it)",
                "/explain <target>  (mechanism brief)",
            ],
        )


class EditCommand(Command):
    def __init__(self):
        super().__init__(
            name="edit",
            description="Apply a deterministic edit op",
            type=CommandType.LOCAL,
            argument_hint="<op>",
            aliases=["e"],
            requires_smiles=True,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        op = args.strip()
        if not op:
            return CommandResult(error="Usage: /edit <op>. See /help for ops.")
        # Lazy import — sandbox dispatches the actual tool
        try:
            from workspace.tools.generative.transform_structure import transform_structure
            r = transform_structure(smiles=ctx.active_smiles, op=op)
            if not r.success:
                return CommandResult(error=r.note or "transform failed", data=r.model_dump())
            products_md = "\n".join(f"- `{p}`" for p in r.products)
            return CommandResult(
                output=(
                    f"**{op}** on `{ctx.active_smiles}`\n\n"
                    f"_{r.op_rationale}_\n\n"
                    f"Products:\n{products_md}"
                ),
                data=r.model_dump(),
                follow_ups=[f"/score {p}" for p in r.products[:2]],
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"edit failed: {exc}")


class ScoreCommand(Command):
    def __init__(self):
        super().__init__(
            name="score",
            description="Score with the 12-axis reward stack",
            type=CommandType.LOCAL,
            argument_hint="[smiles]",
            requires_smiles=False,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        smiles = args.strip() or ctx.active_smiles
        if not smiles:
            return CommandResult(error="No SMILES provided + no active candidate.")
        try:
            from workspace.tools.scoring.score_molecule import score_molecule
            r = score_molecule(smiles=smiles, target_pathogen=ctx.active_target or "MRSA")
            return CommandResult(
                output=f"`{smiles}` composite={r.composite:.3f}",
                data=r.model_dump() if hasattr(r, "model_dump") else dict(r),
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"score failed: {exc}")


class ExplainCommand(Command):
    """W4 — kicks off a streaming Markdown brief on a target/drug.

    Backend: POST /workbench/explain → spawns a Gemini-Pro background
    task that streams chunks via /workbench/sessions/{id}/events. The
    frontend's ExplainCard subscribes and pipes the chunks into the
    right-pane ArtifactPanel.
    """

    def __init__(self):
        super().__init__(
            name="explain",
            description="Mechanism + spectrum + resistance brief",
            type=CommandType.LOCAL,
            argument_hint="<target|drug>",
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        target = args.strip() or (ctx.active_target or "")
        if not target:
            return CommandResult(error="Provide a target/drug or set an active target. Try `/explain mecA` or `/explain cefiderocol`.")

        try:
            from api.workbench import workbench_explain, ExplainRequest
        except ImportError as exc:
            return CommandResult(error=f"explain route not available: {exc}")

        try:
            resp = await workbench_explain(ExplainRequest(target=target))
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"explain start failed: {exc}")

        line = (
            f"explain session started for **{target}** — "
            f"{resp.grounding_count} grounding entries, streaming to artifact pane"
        )
        return CommandResult(
            output=line,
            data={
                "session_id": resp.session_id,
                "target": resp.target,
                "sse_url": resp.sse_url,
                "status": resp.status,
                "grounding_count": resp.grounding_count,
            },
            follow_ups=[
                "/design <pathogen>  (start a session targeting this)",
                "/similar  (find related antibiotics)",
            ],
        )


class SimilarCommand(Command):
    def __init__(self):
        super().__init__(
            name="similar",
            description="Top-K similar antibiotics (embedding)",
            type=CommandType.LOCAL,
            argument_hint="[k=5]",
            aliases=["sim"],
            requires_smiles=True,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        k = 5
        try:
            if args.strip():
                k = int(args.strip())
        except ValueError:
            pass
        try:
            from workspace.tools.scoring.find_similar_drugs import find_similar_drugs
            r = find_similar_drugs(smiles=ctx.active_smiles, k=k)
            md = f"### Top-{k} similar drugs\n\n_{r.interpretation}_\n\n"
            md += "| Rank | Drug | Sim | Class |\n|---|---|---|---|\n"
            for i, m in enumerate(r.matches, 1):
                md += f"| {i} | {m.name} | {m.similarity:.3f} | {m.drug_class or '—'} |\n"
            return CommandResult(output=md, data=r.model_dump())
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"similar failed: {exc}")


class RunCommand(Command):
    def __init__(self):
        super().__init__(
            name="run",
            description="Run a Python cell in the sandbox",
            type=CommandType.SYSTEM,
            argument_hint="<code>",
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        if not args.strip():
            return CommandResult(error="Usage: /run <python>")
        if ctx.sandbox is None:
            return CommandResult(error="Sandbox not attached to this session.")
        try:
            cell = await ctx.sandbox.run_cell(args)
            return CommandResult(
                output=f"```\n{cell.stdout}\n```",
                data={"cell_id": cell.cell_id, "stderr": cell.stderr,
                      "elapsed_ms": cell.elapsed_ms},
                artifact={"kind": "sandbox_cell", "cell": cell.to_dict()},
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"sandbox error: {exc}")


class BranchCommand(Command):
    def __init__(self):
        super().__init__(
            name="branch",
            description="Fork the active candidate as a branch",
            type=CommandType.SYSTEM,
            argument_hint="<branch hint>",
            requires_smiles=True,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        return CommandResult(
            output=f"Branched at `{ctx.active_smiles}` — hint: _{args or 'unspecified'}_",
            data={"action": "branch", "from_smiles": ctx.active_smiles, "hint": args},
        )


class LibraryCommand(Command):
    """W7+W8 — list past workbench sessions for replay/resume."""
    def __init__(self):
        super().__init__(
            name="library",
            description="List past sessions for replay/resume",
            type=CommandType.LOCAL,
            argument_hint="",
            aliases=["lib", "sessions"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        try:
            from api.workbench import list_sessions
            d = await list_sessions()
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"library list failed: {exc}")
        sessions = d.get("sessions", [])
        if not sessions:
            return CommandResult(
                output="No saved sessions yet. Run `/design <pathogen>` to start one.",
                data={"sessions": []},
            )
        line = f"library · {len(sessions)} session{'s' if len(sessions) != 1 else ''}"
        return CommandResult(
            output=line,
            data={"sessions": sessions},
            follow_ups=[
                "Click a session row to replay it",
                "/design <pathogen>  (start a new one)",
            ],
        )


class CompareCommand(Command):
    """W6 — score N SMILES side-by-side."""
    def __init__(self):
        super().__init__(
            name="compare",
            description="Score N candidates side-by-side",
            type=CommandType.LOCAL,
            argument_hint="<smi1> <smi2> [smi3 …]",
            aliases=["cmp"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        # Accept space-, comma-, or newline-separated SMILES
        import re
        toks = [t.strip() for t in re.split(r"[\s,]+", args.strip()) if t.strip()]
        if len(toks) < 2:
            return CommandResult(error="Need at least 2 SMILES. Try `/compare CCO O=C(O)C`.")
        if len(toks) > 8:
            return CommandResult(error=f"Max 8 candidates per /compare (got {len(toks)}).")
        try:
            from api.workbench import workbench_compare, CompareRequest
        except ImportError as exc:
            return CommandResult(error=f"compare route not available: {exc}")
        try:
            resp = await workbench_compare(CompareRequest(
                smiles=toks,
                target_pathogen=ctx.active_target or "MRSA",
            ))
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"compare failed: {exc}")
        ranked = [e for e in resp.entries if not e.error]
        if ranked:
            top = max(ranked, key=lambda e: e.composite)
            line = (
                f"compared {len(resp.entries)} candidates · best: "
                f"`{top.smiles}` (composite {top.composite:.3f}) · "
                f"{resp.elapsed_ms}ms"
            )
        else:
            line = f"compared {len(resp.entries)} candidates · all errored · {resp.elapsed_ms}ms"
        return CommandResult(
            output=line,
            data={
                "target_pathogen": resp.target_pathogen,
                "entries": [e.model_dump() for e in resp.entries],
                "component_winners": resp.component_winners,
                "elapsed_ms": resp.elapsed_ms,
            },
        )


class StressCommand(Command):
    """W5 — adversarial Critic on the active candidate."""
    def __init__(self):
        super().__init__(
            name="stress",
            description="Adversarial Critic — list failure modes",
            type=CommandType.LOCAL,
            argument_hint="[smiles]",
            aliases=["redteam", "rt"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        smi = args.strip() or ctx.active_smiles
        if not smi:
            return CommandResult(error="Provide a SMILES or set an active candidate first.")
        try:
            from api.workbench import workbench_stress, StressTestRequest
        except ImportError as exc:
            return CommandResult(error=f"stress route not available: {exc}")
        try:
            resp = await workbench_stress(StressTestRequest(
                smiles=smi,
                target_pathogen=ctx.active_target or "MRSA",
                max_attacks=6,
            ))
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"stress test failed: {exc}")
        n_high = sum(1 for a in resp.attacks if a.severity == "high")
        line = (
            f"red-team complete · {len(resp.attacks)} attacks "
            f"({n_high} high-severity) · {resp.elapsed_ms}ms · model={resp.model}"
        )
        return CommandResult(
            output=line,
            data={
                "smiles": resp.smiles,
                "target_pathogen": resp.target_pathogen,
                "summary": resp.summary,
                "attacks": [a.model_dump() for a in resp.attacks],
                "model": resp.model,
                "elapsed_ms": resp.elapsed_ms,
            },
            follow_ups=[
                "/score <smiles>  (rescore the candidate)",
                "/sar  (try mutating to fix the worst attack)",
            ],
        )


class SARCommand(Command):
    """W3 — expand the active candidate into k mutants and score each."""
    def __init__(self):
        super().__init__(
            name="sar",
            description="Expand parent → k mutants + score deltas",
            type=CommandType.LOCAL,
            argument_hint="[k=5]",
            aliases=["expand"],
            requires_smiles=True,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        # Parse "k=N" or just "N"
        k = 5
        s = args.strip()
        if s:
            try:
                k = int(s.split("=")[-1])
            except Exception:
                k = 5
        try:
            from api.workbench import workbench_sar_expand, SARExpandRequest
        except ImportError as exc:
            return CommandResult(error=f"sar route not available: {exc}")
        try:
            resp = await workbench_sar_expand(SARExpandRequest(
                parent_smiles=ctx.active_smiles or "",
                k=k,
                target_pathogen=ctx.active_target or "MRSA",
            ))
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"sar expand failed: {exc}")
        line = (
            f"SAR expansion: parent composite "
            f"**{resp.parent.get('composite', 0):.3f}** → "
            f"{resp.n_accepted}/{resp.k if hasattr(resp,'k') else len(resp.children)} mutants scored "
            f"({resp.elapsed_ms}ms)"
        )
        return CommandResult(
            output=line,
            data={
                "parent": resp.parent,
                "children": [c.model_dump() for c in resp.children],
                "n_accepted": resp.n_accepted,
                "n_proposed": resp.n_proposed,
                "elapsed_ms": resp.elapsed_ms,
            },
            follow_ups=[
                "/score <smiles>  (rescore one of the mutants)",
                "/branch <smiles>  (stress-test a mutant)",
            ],
        )


class ScaffoldHopCommand(Command):
    def __init__(self):
        super().__init__(
            name="scaffold-hop",
            description="Bioisosteric scaffold replacements",
            type=CommandType.LOCAL,
            argument_hint="[n=5]",
            aliases=["hop"],
            requires_smiles=True,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        n = 5
        try:
            if args.strip():
                n = int(args.strip())
        except ValueError:
            pass
        try:
            from workspace.tools.generative.scaffold_hop import scaffold_hop
            r = scaffold_hop(smiles=ctx.active_smiles, n_alternatives=n)
            return CommandResult(
                output=f"Scaffold-hop on `{ctx.active_smiles}` returned {len(r.alternatives)} options.",
                data=r.model_dump() if hasattr(r, "model_dump") else dict(r),
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"scaffold-hop failed: {exc}")


class ResistanceCommand(Command):
    def __init__(self):
        super().__init__(
            name="resistance",
            description="Resistome + escape probability",
            type=CommandType.LOCAL,
            argument_hint="<pathogen>",
            aliases=["res"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        pathogen = args.strip() or ctx.active_target
        if not pathogen:
            return CommandResult(error="Usage: /resistance <pathogen>")
        try:
            from workspace.tools.amr.get_pathogen_resistome import get_pathogen_resistome
            r = get_pathogen_resistome(pathogen=pathogen)
            return CommandResult(
                output=f"Resistome for {pathogen}: {len(r.resistance_genes)} genes",
                data=r.model_dump() if hasattr(r, "model_dump") else dict(r),
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"resistance lookup failed: {exc}")


class SetTargetCommand(Command):
    def __init__(self):
        super().__init__(
            name="set-target",
            description="Set the active target pathogen",
            type=CommandType.SYSTEM,
            argument_hint="<pathogen>",
            aliases=["target"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        pathogen = args.strip()
        if not pathogen:
            return CommandResult(error="Usage: /set-target <pathogen>")
        return CommandResult(
            output=f"Active target: **{pathogen}**",
            data={"action": "set_target", "target": pathogen},
        )


# ---------------------------------------------------------------------------
# Default registry
# ---------------------------------------------------------------------------

class AdmetCommand(Command):
    def __init__(self):
        super().__init__(
            name="admet",
            description="ADMET panel (A/D/M/E/T predictions)",
            type=CommandType.LOCAL,
            argument_hint="[smiles]",
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        smiles = args.strip() or ctx.active_smiles
        if not smiles:
            return CommandResult(error="Provide a SMILES or set an active candidate.")
        try:
            from workspace.tools.scoring.predict_admet import predict_admet
            r = predict_admet(smiles=smiles)
            return CommandResult(
                output=f"ADMET panel for `{smiles}`",
                data=r.model_dump() if hasattr(r, "model_dump") else dict(r),
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"admet failed: {exc}")


class SynthCommand(Command):
    def __init__(self):
        super().__init__(
            name="synth",
            description="Retrosynthesis route + cost estimate",
            type=CommandType.LOCAL,
            argument_hint="[smiles]",
            requires_smiles=False,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        smiles = args.strip() or ctx.active_smiles
        if not smiles:
            return CommandResult(error="Provide a SMILES or set an active candidate.")
        try:
            from workspace.tools.scoring.predict_synthesis_route import predict_synthesis_route
            r = predict_synthesis_route(smiles=smiles)
            return CommandResult(
                output=f"Retrosynthesis route for `{smiles}`",
                data=r.model_dump() if hasattr(r, "model_dump") else dict(r),
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"synth failed: {exc}")


class DockCommand(Command):
    def __init__(self):
        super().__init__(
            name="dock",
            description="Dock candidate vs target PDB",
            type=CommandType.LOCAL,
            argument_hint="[pdb_id]",
            aliases=["docking"],
            requires_smiles=True,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        pdb_id = args.strip()
        try:
            from workspace.tools.structural.dock_against_target import dock_against_target
            r = dock_against_target(
                smiles=ctx.active_smiles,
                target_pdb=pdb_id or None,
                pathogen=ctx.active_target,
            )
            return CommandResult(
                output=f"Docking score for `{ctx.active_smiles}`",
                data=r.model_dump() if hasattr(r, "model_dump") else dict(r),
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"dock failed: {exc}")


class ComplexCommand(Command):
    def __init__(self):
        super().__init__(
            name="complex",
            description="Predict 3D complex pose (Boltz-2)",
            type=CommandType.LOCAL,
            argument_hint="[pathogen]",
            requires_smiles=True,
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        target = args.strip() or ctx.active_target
        try:
            from workspace.tools.structural.predict_complex_structure import predict_complex_structure
            r = predict_complex_structure(
                ligand_smiles=ctx.active_smiles,
                pathogen=target,
            )
            return CommandResult(
                output=f"Boltz-2 complex pose for `{ctx.active_smiles}` vs {target}",
                data=r.model_dump() if hasattr(r, "model_dump") else dict(r),
                artifact={
                    "kind": "scene_3d_request",
                    "smiles": ctx.active_smiles,
                    "target": target,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"complex failed: {exc}")


class TraceCommand(Command):
    def __init__(self):
        super().__init__(
            name="trace",
            description="Show last N harness events",
            type=CommandType.SYSTEM,
            argument_hint="[n=20]",
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        n = 20
        try:
            if args.strip():
                n = max(1, min(200, int(args.strip())))
        except ValueError:
            pass
        try:
            from workspace.agents.harness.tracing import get_tracer
            tracer = get_tracer(ctx.session_id)
            recent = tracer.dump_recent(n)
            if not recent:
                return CommandResult(output="_(no trace events yet)_")
            md_lines = ["| Time | Event | Elapsed |", "|---|---|---|"]
            for ev in recent[-n:]:
                ts = ev.get("timestamp", 0)
                t_str = f"{ts:.3f}" if isinstance(ts, (int, float)) else str(ts)
                el = ev.get("elapsed_ms")
                md_lines.append(
                    f"| `{t_str}` | {ev.get('type', '?')} | "
                    f"{el if el is not None else '—'} ms |"
                )
            return CommandResult(output="\n".join(md_lines), data={"events": recent})
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"trace failed: {exc}")


class DatasetsCommand(Command):
    """List HuggingScience datasets registered for grounding + benchmarks."""
    def __init__(self):
        super().__init__(
            name="datasets",
            description="List HuggingScience datasets registered for grounding",
            type=CommandType.LOCAL,
            argument_hint="",
            aliases=["ds"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        try:
            from api.workbench import list_datasets
            d = await list_datasets()
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"datasets list failed: {exc}")

        rows = d.get("datasets", [])
        if not rows:
            return CommandResult(
                output=(
                    "No datasets registered yet. Run "
                    "`python scripts/fetch_huggingscience.py --dataset tier1` "
                    "to seed the registry."
                ),
            )
        lines = ["### HuggingScience datasets (Lysos registry)\n"]
        for r in rows:
            mark = "✓" if r.get("fetched") else "○"
            lines.append(
                f"- {mark} **{r['name']}** (T{r['tier']}, ~{r['rows']}) — "
                f"{r['description']} "
                f"_(hf: `{r['hf_id']}`)_"
            )
        lines.append(
            "\n_✓ = local subset present · ○ = registered, run fetch script._"
        )
        return CommandResult(output="\n".join(lines), data={"datasets": rows})


def create_default_registry() -> CommandRegistry:
    """Build the production registry. Add new commands here."""
    r = CommandRegistry()
    for cmd in [
        HelpCommand(),
        ClearCommand(),
        DesignCommand(),
        EditCommand(),
        ScoreCommand(),
        ExplainCommand(),
        SimilarCommand(),
        ScaffoldHopCommand(),
        ResistanceCommand(),
        StressCommand(),
        SARCommand(),
        CompareCommand(),
        LibraryCommand(),
        RunCommand(),
        BranchCommand(),
        SetTargetCommand(),
        AdmetCommand(),
        SynthCommand(),
        DockCommand(),
        ComplexCommand(),
        TraceCommand(),
        DatasetsCommand(),
    ]:
        r.register(cmd)
    return r


# Module-level singleton (built once)
DEFAULT_REGISTRY: Optional[CommandRegistry] = None


def get_registry() -> CommandRegistry:
    global DEFAULT_REGISTRY
    if DEFAULT_REGISTRY is None:
        DEFAULT_REGISTRY = create_default_registry()
    return DEFAULT_REGISTRY

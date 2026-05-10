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

async def _gemini_edit_translator(
    parent_smiles: str,
    atom_idx: int,
    edit_description: str,
) -> dict:
    """Use Gemini Pro to translate a natural-language molecule edit
    into a concrete RDKit-valid SMILES.

    Input: parent SMILES + atom index + free-text description ("Replace
    cyclopropyl with tert-butyl", "C5-H → C5-CF3").
    Output: {"smiles": <new SMILES>, "rationale": <one sentence>}.

    Validates the returned SMILES with RDKit before returning. Used by
    /edit when the simple keyword/element parser doesn't match.
    """
    import os, re, httpx, json as _json
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return {"error": "GEMINI_API_KEY missing"}
    model_id = os.getenv("LYSOS_EDIT_MODEL", "gemini-2.5-pro")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:generateContent"
    system = (
        "You are a medicinal-chemistry SMILES editor. Given a parent "
        "SMILES, an atom index (0-indexed), and a natural-language edit "
        "description, return the resulting SMILES that an RDKit parser "
        "would accept.\n\n"
        "Output STRICT JSON: {\"smiles\": \"<RDKit-valid SMILES>\", "
        "\"rationale\": \"<one sentence: what changed and why it makes "
        "chemical sense>\"}\n\n"
        "Rules:\n"
        "- Preserve the rest of the scaffold; only modify what the "
        "  description says.\n"
        "- Make sure valences and aromaticity are valid.\n"
        "- If the edit is impossible without breaking valence, suggest "
        "  the closest valid alternative AND explain in rationale.\n"
        "- Do NOT wrap output in markdown code fences."
    )
    user = (
        f"Parent SMILES: {parent_smiles}\n"
        f"Edit at atom index: {atom_idx}\n"
        f"Description: {edit_description}\n\n"
        f"Return JSON only."
    )
    payload = {
        "system_instruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            # Gemini 2.5's thinking budget eats from the same pool as
            # the JSON response, so 512 was hitting the cap mid-string.
            # 4096 gives the model headroom for complex SMILES edits.
            "maxOutputTokens": 4096,
            "temperature": 0.2,
            "thinkingConfig": {"thinkingBudget": 1024, "includeThoughts": False},
        },
    }
    try:
        async with httpx.AsyncClient(timeout=20.0) as cx:
            r = await cx.post(url,
                              headers={"x-goog-api-key": key, "Content-Type": "application/json"},
                              json=payload)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"http error: {exc}"}
    if r.status_code != 200:
        return {"error": f"gemini http {r.status_code}: {r.text[:200]}"}
    body = r.json()
    cands = body.get("candidates") or []
    if not cands:
        return {"error": "no gemini candidates"}
    parts = (cands[0].get("content") or {}).get("parts") or []
    txt = "".join(p.get("text") or "" for p in parts).strip()
    if txt.startswith("```"):
        txt = re.sub(r"^```(?:json)?\s*|\s*```$", "", txt, flags=re.M).strip()
    try:
        parsed = _json.loads(txt)
    except _json.JSONDecodeError as exc:
        return {"error": f"json parse: {exc}", "raw": txt[:200]}
    smi = parsed.get("smiles", "").strip()
    if not smi:
        return {"error": "no smiles in gemini response", "raw": parsed}
    # Validate with RDKit
    try:
        from rdkit import Chem
        mol = Chem.MolFromSmiles(smi)
        if mol is None:
            return {"error": f"gemini returned unparseable SMILES: `{smi}`"}
        canonical = Chem.MolToSmiles(mol)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"rdkit failure: {exc}", "raw_smiles": smi}
    return {"smiles": canonical, "rationale": parsed.get("rationale", ""),
            "raw_smiles": smi}


class HelpCommand(Command):
    def __init__(self):
        super().__init__(
            name="help", description="List all slash commands",
            type=CommandType.SYSTEM, aliases=["?", "skills"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        # Tight, demo-ready overview. The full SKILLS.md is still on disk
        # for agent context but we no longer dump 6KB of markdown into
        # the chat — that was unreadable noise. Group by category, one
        # line each.
        content = (
            "## Lysos commands · 25 total\n"
            "\n"
            "**Design & build**\n"
            "- `/design <pathogen> [objective]` — multi-agent design session\n"
            "- `/edit <op>` — deterministic structural edit\n"
            "- `/scaffold-hop` — bioisosteric scaffold replacement\n"
            "- `/branch <hint>` — fork the active candidate\n"
            "\n"
            "**Score & assess**\n"
            "- `/score [smiles]` — 12-axis reward stack (composite)\n"
            "- `/admet [smiles]` — ADMET predictions\n"
            "- `/synth [smiles]` — retrosynthesis route + cost\n"
            "- `/similar [k=5]` — top-K nearest known antibiotics\n"
            "- `/sar [k=5]` — k mutants + score deltas\n"
            "- `/pareto [x] [y]` — multi-candidate Pareto frontier\n"
            "- `/compare <s1> <s2> ...` — side-by-side N candidates\n"
            "\n"
            "**Resistance & robustness**\n"
            "- `/resistance <pathogen>` — resistome + escape probability\n"
            "- `/escape [pdb_id]` — per-atom vulnerability map\n"
            "- `/stress [smiles]` — adversarial Critic failure modes\n"
            "\n"
            "**Structure & docking**\n"
            "- `/dock [pdb_id]` — Vina docking vs target\n"
            "- `/complex [pathogen]` — Boltz-2 complex pose\n"
            "- `/theater [smiles] [pdb_id]` — 3D target-ligand viewer\n"
            "\n"
            "**Knowledge**\n"
            "- `/explain <target|drug>` — mechanism + spectrum + resistance brief\n"
            "- `/datasets` — list grounding datasets\n"
            "- `/library` — past sessions for replay\n"
            "\n"
            "**System**\n"
            "- `/set-target <pathogen>` — change active pathogen\n"
            "- `/clear` — reset session state\n"
            "- `/run <code>` — Python sandbox cell\n"
            "- `/trace [n]` — last N harness events\n"
            "- `/wf <workflow_name>` — run a multi-step workflow (5 registered)\n"
            "\n"
            "💡 **Or just type natural language** — the orchestrator routes "
            "free text to the right command/workflow automatically."
        )
        return CommandResult(output=content, data={})


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
            return CommandResult(error="Usage: /edit atom=N <change>. Examples: `/edit atom=2 -OH`, `/edit atom=5 swap=F`, `/edit atom=0 add hydroxyl`, `/edit atom=3 Replace cyclopropyl with tert-butyl`.")

        # ── Smart parser: accept natural-language edit prompts ──
        # Tier 1: regex parse for obvious shapes (FG keywords, swap=X)
        # Tier 2: Gemini Pro structured-output call for arbitrary
        #         medicinal-chemistry English ("Replace cyclopropyl
        #         with tert-butyl", "C5-H → C5-CF3", etc.)
        import re as _re
        atom_m = _re.search(r"atom\s*=\s*(\d+)", op, _re.I)
        atom_idx = int(atom_m.group(1)) if atom_m else None
        body = op
        if atom_m:
            body = op[atom_m.end():].strip()

        active_smi = ctx.active_smiles
        if not active_smi:
            return CommandResult(error="No active SMILES to edit. Load a candidate first.")
        if atom_idx is None:
            return CommandResult(error="Couldn't parse atom index. Use `/edit atom=N <change>`.")

        # Functional-group keyword map → /workbench/molecule/edit op=add_functional_group_at
        FG_KEYWORDS = {
            "hydroxyl": "hydroxyl", "-oh": "hydroxyl", "oh": "hydroxyl", "phenol": "hydroxyl",
            "methyl": "methyl", "-ch3": "methyl", "ch3": "methyl",
            "amine": "amine", "-nh2": "amine", "nh2": "amine",
            "fluorine": "fluorine", "-f": "fluorine", "fluoro": "fluorine",
            "chlorine": "chlorine", "-cl": "chlorine",
            "bromine": "bromine", "-br": "bromine",
            "iodine": "iodine", "-i": "iodine",
            "thiol": "thiol", "-sh": "thiol", "sh": "thiol",
            "carbonyl": "carbonyl", "aldehyde": "aldehyde",
            "carboxyl": "carboxyl", "-cooh": "carboxyl", "cooh": "carboxyl",
            "amide": "amide", "ester": "ester",
            "nitro": "nitro", "-no2": "nitro", "no2": "nitro",
            "sulfonyl": "sulfonyl", "sulfonamide": "sulfonamide",
            "sulfide": "sulfide", "thioether": "sulfide",
            "cyano": "cyano", "-cn": "cyano", "nitrile": "cyano",
            "trifluoromethyl": "trifluoromethyl", "-cf3": "trifluoromethyl", "cf3": "trifluoromethyl",
            "ethyl": "ethyl", "vinyl": "vinyl",
            "phosphate": "phosphate", "phosphonate": "phosphonate",
        }
        body_low = body.lower()
        fg = next((v for k, v in FG_KEYWORDS.items() if k in body_low), None)

        # Element swap detection (single capital letter or common 2-letter)
        elem_m = _re.search(r"\b(swap|replace|to|->)\s*[=:]?\s*([A-Z][a-z]?)\b", body)
        new_element = elem_m.group(2) if elem_m else None

        try:
            from api.workbench import molecule_edit, AtomEditRequest
        except ImportError as exc:
            return CommandResult(error=f"molecule_edit route unavailable: {exc}")

        try:
            if fg:
                req = AtomEditRequest(
                    smiles=active_smi, op="add_functional_group_at",
                    atom_index=atom_idx, functional_group=fg,
                    actor="user",
                )
            elif new_element:
                req = AtomEditRequest(
                    smiles=active_smi, op="swap_element",
                    atom_index=atom_idx, new_element=new_element,
                    actor="user",
                )
            else:
                # ── Tier 2: Gemini Pro translates natural language to a
                # concrete SMILES edit. Real LLM call, structured output. ──
                gemini_smi = await _gemini_edit_translator(
                    parent_smiles=active_smi,
                    atom_idx=atom_idx,
                    edit_description=body,
                )
                if gemini_smi.get("error"):
                    return CommandResult(
                        error=f"Couldn't interpret `{body}`: {gemini_smi['error']}",
                        data=gemini_smi,
                    )
                new_smi = gemini_smi.get("smiles")
                rationale = gemini_smi.get("rationale", "")
                if not new_smi:
                    return CommandResult(error="Gemini returned no SMILES.", data=gemini_smi)
                return CommandResult(
                    output=(
                        f"Edited `{active_smi}` at atom **#{atom_idx}**.\n\n"
                        f"_{rationale}_\n\n"
                        f"Result: `{new_smi}`\n\n"
                        f"_Click below to load it into the canvas._"
                    ),
                    data={"smiles": new_smi, "edit": body, "atom_idx": atom_idx,
                          "parent_smiles": active_smi, "rationale": rationale,
                          "via": "gemini"},
                    follow_ups=[f"/load {new_smi}", f"/score {new_smi}"],
                )

            d = await molecule_edit(req)
            new_smi = d.get("smiles") if isinstance(d, dict) else None
            if not new_smi:
                return CommandResult(error=f"edit returned no SMILES: {d}")
            descr = fg or f"swap → {new_element}"
            return CommandResult(
                output=(
                    f"Edited `{active_smi}` at atom **#{atom_idx}** ({descr}).\n\n"
                    f"Result: `{new_smi}`\n\n"
                    f"_Click below to load it into the canvas._"
                ),
                data={"smiles": new_smi, "edit": descr, "atom_idx": atom_idx,
                      "parent_smiles": active_smi},
                follow_ups=[f"/load {new_smi}", f"/score {new_smi}"],
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
        # Resolution order: explicit args → session active_target → session
        # active pathogen (so a user with MRSA selected can just type
        # `/explain` and get a brief on the pathogen). Final fallback is
        # an explanatory error so the agent never silently no-ops.
        target = args.strip() or (ctx.active_target or "") or getattr(ctx, "active_pathogen", "") or ""
        if not target:
            return CommandResult(error=(
                "No target supplied and no active pathogen/target in this session. "
                "Try `/explain mecA`, `/explain cefiderocol`, or pick a pathogen in the top header."
            ))

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


# ───────────────────────────────────────────────────────────────────────
# Service 1/2/3 — chem dashboard slash commands
# Wire the user-typed chat path to the same endpoints the workbench cards
# call. So "/theater 1VQQ" gives them the same data the 3D Theater card
# is showing, but as a chat artifact they can save / share.
# ───────────────────────────────────────────────────────────────────────

class TheaterCommand(Command):
    """`/theater {smiles?} {pdb_id?}` — place candidate in target active site."""
    def __init__(self):
        super().__init__(
            name="theater",
            description="3D Target-Ligand Theater — place candidate in target active site",
            type=CommandType.LOCAL,
            argument_hint="[smiles] [pdb_id]",
            aliases=["pose"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        parts = args.strip().split() if args.strip() else []
        smiles: Optional[str] = None
        pdb_id: Optional[str] = None
        for p in parts:
            if p.upper().startswith(("1", "2", "3", "4", "5", "6", "7", "8", "9")) and len(p) == 4:
                pdb_id = p.upper()
            else:
                smiles = p
        if not smiles:
            smiles = ctx.active_smiles
        if not smiles:
            return CommandResult(error="Usage: /theater <smiles> <pdb_id>  (or set an active candidate first)")
        if not pdb_id:
            # default to the pathogen's preferred target
            try:
                from workspace.api.chem_3d import PATHOGEN_TARGETS
                ts = PATHOGEN_TARGETS.get(ctx.active_target or "MRSA", [])
                pdb_id = next((t["pdb_id"] for t in ts if t.get("preferred_default")), ts[0]["pdb_id"] if ts else None)
            except Exception:
                pdb_id = None
        if not pdb_id:
            return CommandResult(error="No PDB ID — set a pathogen via /set-target or specify a PDB explicitly.")
        try:
            from workspace.api.chem_3d import place_in_pocket as _ep, PlaceInPocketRequest, _find_target_meta
            result = await _ep(PlaceInPocketRequest(smiles=smiles, pdb_id=pdb_id))
            meta = _find_target_meta(pdb_id) or {}
            md = [
                f"### 🎯 Target-Ligand Theater · {meta.get('short_name', pdb_id)} ({pdb_id})",
                "",
                f"**Pathogen**: {meta.get('pathogen', '—')}  ·  **Mechanism**: {meta.get('mechanism', '—')}",
                f"**Pose score**: {result['pose_score']:.3f}  ·  **Contacts**: {result['n_contacts']}  ·  **Clashes**: {result['n_clashes']}",
                "",
                f"**Binding atoms**: {result['binding_atoms']}",
                f"**Clashing atoms**: {result['clashing_atoms']}",
                "",
                "**Top contacts**:",
            ]
            for c in result["key_contacts"][:6]:
                md.append(f"- `{c['residue']}` (chain {c['chain']}) ↔ atom {c['ligand_atom_idx']}({c['ligand_element']}) — {c['distance_a']} Å")
            return CommandResult(
                output="\n".join(md),
                data={"smiles": smiles, "pdb_id": pdb_id, "pose": result},
                follow_ups=[
                    f"/escape {pdb_id}",
                    "/score",
                    f"/explain {meta.get('short_name', '')}",
                ],
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"theater failed: {exc}")


class EscapeCommand(Command):
    """`/escape {pdb_id?}` — predict per-atom resistance vulnerability."""
    def __init__(self):
        super().__init__(
            name="escape",
            description="Resistance escape map — per-atom vulnerability vs known clinical mutations",
            type=CommandType.LOCAL,
            argument_hint="[pdb_id]",
            aliases=["resistance-map"],
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        smiles = ctx.active_smiles
        if not smiles:
            return CommandResult(error="Set an active candidate first (load from library or run /design).")
        from workspace.api.chem_3d import PATHOGEN_TARGETS
        pathogen_targets = PATHOGEN_TARGETS.get(ctx.active_target or "MRSA", [])

        def _default_pdb() -> Optional[str]:
            return next(
                (t["pdb_id"] for t in pathogen_targets if t.get("preferred_default")),
                pathogen_targets[0]["pdb_id"] if pathogen_targets else None,
            )

        # Resolve the user's first arg into a PDB. Three modes:
        #   (a) bare 4-char alphanumeric ID — use as-is (PDB regex)
        #   (b) gene/target alias — search PATHOGEN_TARGETS for a match
        #       on name / aliases / pathogen so "mecA" → 1VQQ (PBP2a).
        #   (c) anything else — fall back to active pathogen's preferred PDB.
        pdb_id: Optional[str] = None
        resolution_note = ""
        raw_arg = args.strip()
        if raw_arg:
            # Take the first token after stripping common separators —
            # users sometimes paste "mecA / PBP2a" or "PBP2a (1VQQ)".
            first_tok = raw_arg.split(maxsplit=1)[0].strip("()[],/")
            # PDB IDs are always 4 chars AND start with a digit
            # (e.g. 1VQQ, 2X22, 4FDO). "mecA" / "VanA" are alphanumeric
            # but DO NOT match this — so they correctly fall through to
            # the alias resolver instead of 404'ing as a fake PDB.
            import re as _re
            is_pdb = bool(_re.fullmatch(r"\d[A-Za-z0-9]{3}", first_tok))
            # (a) literal PDB ID
            if is_pdb:
                pdb_id = first_tok.upper()
            else:
                # (b) gene/target alias resolver — try the first token,
                # then the whole arg if needed.
                for needle in (first_tok.lower(), raw_arg.lower()):
                    if pdb_id:
                        break
                    for t in pathogen_targets:
                        name = (t.get("name") or "").lower()
                        aliases = [a.lower() for a in (t.get("aliases") or [])]
                        # Token match against name OR any alias
                        if (needle and (needle in name or name in needle
                            or any(needle == a or needle in a or a in needle
                                   for a in aliases))):
                            pdb_id = t["pdb_id"]
                            resolution_note = (
                                f"_(resolved `{first_tok}` → {t.get('name')} "
                                f"PDB **{pdb_id}** for "
                                f"{ctx.active_target or 'MRSA'})_\n\n"
                            )
                            break
            # (c) last-ditch: default for the active pathogen
            if not pdb_id:
                fallback = _default_pdb()
                if fallback:
                    pdb_id = fallback
                    resolution_note = (
                        f"_(`{raw_arg}` is not a PDB or known target alias — "
                        f"falling back to **{pdb_id}**, the default for "
                        f"{ctx.active_target or 'MRSA'}. Use `/theater` to see all targets.)_\n\n"
                    )
        else:
            pdb_id = _default_pdb()
        if not pdb_id:
            return CommandResult(error="No PDB ID and no targets registered for the active pathogen. Use `/set-target <pathogen>`.")
        try:
            from workspace.api.chem_resistance import predict_resistance as _ep, PredictResistanceRequest
            result = await _ep(PredictResistanceRequest(smiles=smiles, pdb_id=pdb_id))
            md = [
                f"### 🛡️ Resistance escape map · {result['target_name']}",
                "",
                resolution_note + f"**Pathogen**: {result['pathogen']}  ·  **PDB**: {pdb_id}",
                f"**Robustness**: {result['robustness_score']:.3f}  ·  **Escape vectors**: {result['n_escape_vectors']}",
                f"**Known clinical mutations checked**: {result['n_total_known_mutations']}",
                "",
                f"**Summary**: {result['summary']}",
                "",
            ]
            if result["vulnerable_atoms"]:
                md.append("**Top vulnerable atoms**:")
                for v in result["vulnerable_atoms"][:5]:
                    m = v["top_mutation"]
                    md.append(
                        f"- atom **{v['atom_idx']}** → escape **{v['escape_score']:.2f}** "
                        f"via `{m['wt']}{m['position']}{m['mutant']}` ({m['drug_class']})"
                    )
            else:
                md.append("✓ No clinical-resistance vulnerabilities detected for this candidate.")
            return CommandResult(
                output="\n".join(md),
                data={"pdb_id": pdb_id, "resistance": result},
                follow_ups=["/edit", "/sar"],
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"escape failed: {exc}")


class ParetoCommand(Command):
    """`/pareto {x?} {y?}` — show current Pareto frontier of session candidates."""
    def __init__(self):
        super().__init__(
            name="pareto",
            description="Multi-candidate Pareto frontier on selected axes",
            type=CommandType.LOCAL,
            argument_hint="[x_axis] [y_axis]",
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        sid = ctx.session_id
        if not sid:
            return CommandResult(error="No active session.")
        parts = args.strip().split() if args.strip() else []
        x_axis = parts[0] if len(parts) > 0 else "predicted_mic"
        y_axis = parts[1] if len(parts) > 1 else "composite_reward"
        try:
            from workspace.api.chem_pareto import session_pareto
            result = await session_pareto(sid=sid, x=x_axis, y=y_axis)
            md = [
                f"### 📊 Pareto frontier · {result['x_axis_meta']['label']} vs {result['y_axis_meta']['label']}",
                "",
                f"**Total candidates**: {result['stats']['n_total']}  ·  "
                f"**With scores**: {result['stats']['n_with_scores']}  ·  "
                f"**Pareto-optimal**: {result['stats']['n_pareto']}",
                "",
            ]
            if result["pareto_set"]:
                md.append("**Pareto-optimal candidates**:")
                for cid in result["pareto_set"]:
                    pt = next((p for p in result["all_points"] if p["candidate_id"] == cid), None)
                    if pt:
                        md.append(
                            f"- `{pt['smiles'][:50]}{'…' if len(pt['smiles']) > 50 else ''}` "
                            f"({pt['created_by']}) — x={pt['x_value']:.3f}, y={pt['y_value']:.3f}"
                        )
            else:
                md.append("_No Pareto-optimal candidates yet (need at least one with scores on both axes)._")
            return CommandResult(
                output="\n".join(md),
                data={"pareto": result},
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"pareto failed: {exc}")


class ChampionCommand(Command):
    """`/champion` — show reigning champion for the current pathogen.
    `/champion <smiles>` — A/B compare a SMILES against the reigning champion.
    `/champion promote` — promote the active candidate to champion.
    """

    def __init__(self):
        super().__init__(
            name="champion",
            description="Reigning best per pathogen + A/B vs prior best",
            type=CommandType.LOCAL,
            argument_hint="[promote|<smiles>]",
        )

    async def execute(self, args: str, ctx: CommandContext) -> CommandResult:
        from workspace.api import champions
        pathogen = (ctx.active_target or "MRSA").upper()
        sub = args.strip()

        # `/champion` (bare) — show reigning champion
        if not sub:
            champ = champions.get(pathogen)
            if not champ:
                return CommandResult(
                    output=(
                        f"### 🏆 Champion · {pathogen}\n\n"
                        f"_No champion crowned yet for {pathogen}._\n\n"
                        f"Run `/wf discover_and_assess pathogen={pathogen}` "
                        f"or `/wf design_with_debate` and the winner is auto-promoted."
                    ),
                    data={"champion": None, "pathogen": pathogen},
                )
            md = [
                f"### 🏆 Champion · {pathogen}",
                "",
                f"**SMILES**: `{champ['smiles']}`",
                f"**Composite**: {(champ.get('composite') or 0):.3f}  ·  "
                f"**Robustness**: {(champ.get('robustness') or 0):.3f}  ·  "
                f"**Fitness**: {(champ.get('fitness') or 0):.3f}",
            ]
            if champ.get("rationale"):
                md.append(f"\n_{champ['rationale']}_")
            return CommandResult(
                output="\n".join(md),
                data={"champion": champ, "pathogen": pathogen,
                      "ui_actions": [{"type": "load_smiles", "smiles": champ["smiles"]}]},
            )

        # `/champion promote` — auto-promote active candidate
        if sub.lower() == "promote":
            if not ctx.active_smiles:
                return CommandResult(error="No active candidate. Apply one first then `/champion promote`.")
            res = champions.propose(
                pathogen, ctx.active_smiles,
                composite=None, robustness=None,
                session_id=ctx.session_id, rationale="manual /champion promote",
            )
            if res.get("promoted"):
                return CommandResult(
                    output=f"✅ Promoted to {pathogen} champion.",
                    data={"champion_promotion": res, "pathogen": pathogen},
                )
            return CommandResult(
                output=f"Did not promote — {res.get('reason', 'unknown')}.",
                data={"champion_promotion": res, "pathogen": pathogen},
            )

        # `/champion <smiles>` — A/B compare
        smi = sub
        try:
            ab = champions.compare(pathogen, smi)
            md = [
                f"### ⚔️ A/B vs reigning {pathogen} champion",
                "",
                f"**Candidate**: `{smi}`",
            ]
            if ab.get("champion"):
                ch = ab["champion"]
                d = ab["deltas"]
                md.extend([
                    f"**Champion**: `{ch['smiles']}`",
                    "",
                    f"| axis | champion | candidate | Δ |",
                    f"|---|---:|---:|---:|",
                    f"| composite  | {(ch.get('composite') or 0):.3f} | {ab['candidate']['composite']:.3f} | {d['composite']:+.3f} |",
                    f"| robustness | {(ch.get('robustness') or 0):.3f} | {ab['candidate']['robustness']:.3f} | {d['robustness']:+.3f} |",
                    f"| fitness    | {(ch.get('fitness') or 0):.3f} | {ab['candidate']['fitness']:.3f} | {d['fitness']:+.3f} |",
                    "",
                    f"**Verdict**: {ab['verdict']}",
                ])
            else:
                md.append("\n_No reigning champion yet — promote with `/champion promote`._")
            return CommandResult(
                output="\n".join(md),
                data={"ab_compare": ab, "pathogen": pathogen,
                      "ui_actions": [{"type": "champion_ab", "ab": ab}]},
            )
        except Exception as exc:  # noqa: BLE001
            return CommandResult(error=f"champion compare failed: {exc}")


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
        # Service 1/2/3 — chem dashboard slash commands
        TheaterCommand(),
        EscapeCommand(),
        ParetoCommand(),
        # Wave C — champion table
        ChampionCommand(),
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

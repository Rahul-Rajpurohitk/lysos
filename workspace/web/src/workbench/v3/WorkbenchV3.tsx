import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Allotment } from "allotment";
import { Maximize2, LayoutGrid } from "lucide-react";
import "allotment/dist/style.css";

import { TopHeader } from "./components/TopHeader";
import { TightComposer } from "./components/chat/TightComposer";
import { reduceAgentEventStandalone as _reduceAgentEvent } from "./hooks/useAgentStream.helpers";
void _reduceAgentEvent;
import { reduceWorkflowEvent } from "./components/chat/WorkflowCard";
import { reduceOrchestratorEvent, type OrchestratorState } from "./components/chat/OrchestratorCard";
import { ToolAccessOverlay } from "./components/chat/ToolAccessOverlay";
import { AgentSuggestionStrip } from "./components/chat/AgentSuggestionStrip";
// IterationStrip removed from primary layout per redesign — was a 2nd-row
// chrome that violated the single-navbar mandate. The play/seek/speed
// controls migrate inline elsewhere if needed.
// import { IterationStrip } from "./components/IterationStrip";
import { DragEditChips as _DragEditChips } from "./components/DragEditChips";
void _DragEditChips;
import { TabStrip as _TabStrip } from "./components/TabStrip";
void _TabStrip;
import { Mol2D as _Mol2D } from "./components/Mol2D";
import { Mol3D as _Mol3D } from "./components/Mol3D";
import { MechanismPanel as _MechanismPanel } from "./components/MechanismPanel";
void _Mol2D; void _Mol3D; void _MechanismPanel;
import { OnboardingHero } from "./components/OnboardingHero";
import { ChatPanel } from "./components/chat/ChatPanel";
// Legacy panels (kept around for the Library/replay mode + chat-card cards)
// Their TS imports are referenced via `void` so the bundle still ships
// them ready for future on-demand mounting inside the playground canvas.
import { RadarPanel as _RadarPanel } from "./panels/RadarPanel";
import { ParetoPanel as _ParetoPanel } from "./panels/ParetoPanel";
import { SynthPanel as _SynthPanel } from "./panels/SynthPanel";
import { LineagePanel as _LineagePanel } from "./panels/LineagePanel";
import { GraphPanel as _GraphPanel } from "./panels/GraphPanel";
void _RadarPanel; void _ParetoPanel; void _SynthPanel; void _LineagePanel; void _GraphPanel;
import { ArtifactPanel, type ArtifactDoc } from "./panels/ArtifactPanel";
import { PlaygroundCanvas, type WindowLayout, type Viewport } from "./playground/PlaygroundCanvas";
import { TabbedView, TabbedViewTabs } from "./playground/TabbedView";
import { Mol3DTheaterWindow } from "./playground/Mol3DTheaterWindow";
import { ResistanceEscapeMapCard } from "./playground/ResistanceEscapeMapCard";
import { ParetoLabCard } from "./playground/ParetoLabCard";
// WorkflowPhaseTracker removed — heuristic phase derivation was faking
// SCOPE/VALIDATE evidence counts. Real workflow progress is now
// visible per-step inside the WorkflowCard in the chat.
import { ReportBuilderCard } from "./playground/ReportBuilderCard";
import { ValidatedTargetsCard } from "./playground/ValidatedTargetsCard";
import { RewardRadarWindow } from "./playground/RewardRadarWindow";
import { AgentReasoningTraceWindow } from "./playground/AgentReasoningTraceWindow";
import { Mol2DBuilderWindow } from "./playground/Mol2DBuilderWindow";
// LiveAtomsCard is now embedded into Mol2DBuilderWindow as an AtomsRail
// import { LiveAtomsCard } from "./playground/LiveAtomsCard";
// ScaffoldPickerCard absorbed into ChemistryNavbar (sole entry point)
import { EditLogCard } from "./playground/EditLogCard";
import { ConnectionStatusCard } from "./playground/ConnectionStatusCard";
import { StructuralAlertsCard } from "./playground/StructuralAlertsCard";
import { ResistanceMapCard } from "./playground/ResistanceMapCard";
import { AtomDetailCard } from "./playground/AtomDetailCard";
import { PropertiesCard } from "./playground/PropertiesCard";
// SMARTSMatchCard absorbed into Mol2DBuilderWindow as inline strip
// import { SMARTSMatchCard } from "./playground/SMARTSMatchCard";
// MoleculeLibraryCard absorbed into Mol2DBuilderWindow as portal popover
// import { MoleculeLibraryCard } from "./playground/MoleculeLibraryCard";
import { PathogenIntelCard } from "./playground/PathogenIntelCard";
import { AntibioticReferenceCard } from "./playground/AntibioticReferenceCard";
import { ToxicityProfileCard } from "./playground/ToxicityProfileCard";
import { SimilarityCard } from "./playground/SimilarityCard";
import { ScoreBreakdownCard } from "./playground/ScoreBreakdownCard";
import { AgentRosterCard } from "./playground/AgentRosterCard";
import { AgentsHubCard } from "./playground/AgentsHubCard";
void AgentRosterCard;
import { SessionTraceCard } from "./playground/SessionTraceCard";
import { AgentActionLogCard } from "./playground/AgentActionLogCard";
import { AgentMetricsCard } from "./playground/AgentMetricsCard";
import { ChemistryNavbar } from "./playground/ChemistryNavbar";
import { ChemistryTopNav } from "./playground/ChemistryTopNav";
void ChemistryNavbar;  // keeping import in case we want to switch back
import { KnowledgeNavbar } from "./playground/KnowledgeNavbar";
import { KnowledgeChampionPane } from "./playground/KnowledgeChampionPane";
import { KnowledgeHubCard } from "./playground/KnowledgeHubCard";
import { PathogenMatrixCard } from "./playground/PathogenMatrixCard";
import { MutationAtlasCard } from "./playground/MutationAtlasCard";
import { ResistanceNetworkCard } from "./playground/ResistanceNetworkCard";
import { ChampionVaultCard } from "./playground/ChampionVaultCard";
import { ScoringNavbar } from "./playground/ScoringNavbar";
import { AgentsNavbar } from "./playground/AgentsNavbar";
import { LiveNavbar } from "./playground/LiveNavbar";
import type { GroupLayout } from "./playground/PlaygroundGroup";
import { useLivePlayground } from "./playground/useLivePlayground";
import { invalidate as invalidateMolCache } from "./playground/moleculeStateCache";
void {} as unknown as WindowLayout;
import { CandidateList as _CandidateList } from "./components/CandidateList";
void _CandidateList;
import type { Pathogen } from "./components/TopHeader";
import { useAutoTitle, ensureUniqueTitle } from "./hooks/useAutoTitle";

import "./v3.css";

const REWARD_WEIGHTS: Record<string, number> = {
  validity: 0.05,
  structural_alerts: 0.05,
  predicted_mic: 0.20,
  drug_likeness_qed: 0.10,
  synthesizability: 0.10,
  hemolysis_safety: 0.10,
  novelty: 0.08,
  embedding_novelty: 0.07,
  boltz2_pose_conf: 0.10,
  spectrum_breadth: 0.05,
  resistance_robustness: 0.05,
  pareto_entry: 0.05,
};

interface WorkbenchV3Props {
  apiBase: string;
}

interface TraceEvent {
  type: string;
  ts: number;
  iteration?: number;
  agent?: string;
  content?: string;
  tool?: string;
  args?: any;
  result?: any;
  smiles?: string;
  scores?: Record<string, number>;
  composite?: number;
  parent?: string;
  candidate?: string;
  delta?: any;
  decision?: string;
  reason?: string;
}

interface Constraint {
  id: string;
  label: string;
}

const RIGHT_TABS = ["Radar", "Pareto", "Synth", "Graph", "Lineage", "Artifact"] as const;
type RightTab = (typeof RIGHT_TABS)[number];

/** Map a workflow step's tool/id to the agent role that "owns" the
 *  semantic narration. Mirrors the backend _STEP_AGENT mapping so the
 *  user sees the same colored bars in the chat as in the Agents tab. */
function roleForStep(tool: string | undefined, stepId: string | undefined): string {
  const t = (tool ?? "").toLowerCase();
  const id = (stepId ?? "").toLowerCase();
  if (["predict_resistance", "compare_resistance", "cross_target_risk", "explain_resistance"].includes(t)) return "critic";
  if (["score_each", "score_explain", "score_molecule", "place_in_pocket", "molecule_properties"].includes(t)) return "designer";
  if (["harden_atom"].includes(t)) return "editor";
  if (id.includes("harden")) return "editor";
  if (id.includes("seed") || id.includes("rank") || id.includes("pick")) return "strategist";
  return "designer";
}

/** Turn a workflow step result into a one-paragraph chat narration so
 *  the user sees the agent "speaking" with real findings, not just
 *  watching a workflow card collapse. */
function narrateStepResult(stepDef: any, result: any, elapsedMs?: number): string | null {
  if (!stepDef || !result) return null;
  const label = stepDef.label || stepDef.id || "step";
  const tool = (stepDef.tool || "").toLowerCase();
  // Timing is shown subtly in the agent badge already — keeping the
  // raw `_(7984ms)_` debug markup inside the narrative body made every
  // step read like a log line, not an agent. Drop it from the prose.
  // (kept the elapsedMs param for backward-compat with callers.)
  void elapsedMs;
  const ms = "";

  // Resistance prediction — the critic's specialty.
  // Opinionated reasoning over the numbers: prioritize, contextualize
  // mutation frequency, and call out the threshold floor. NOT a stat
  // dump (user feedback: 'repetitive, unnatural, just bringing data
  // from db that's it, no real reasoning').
  if (tool === "predict_resistance") {
    const va = (result.vulnerable_atoms ?? []) as any[];
    const rb = result.robustness_score ?? 0;
    const target = result.target_name ?? result.pdb_id;
    if (va.length === 0) {
      return `Robustness against \`${target}\` lands at **${rb.toFixed(2)}** — clean. No mutation in the curated CARD subset breaches our 0.30 escape threshold, so this candidate is structurally insensitive to known clinical β-lactam resistance pathways. _The risk left is what we don't know yet, not what's in the literature._`;
    }
    // Tier the candidate honestly. Inline bold only on the single
    // adjective + the number — nesting **...** inside another **...**
    // breaks the markdown renderer (user saw "**solid — robustness
    // **0.93** sits...**" rendered literally).
    const tier = rb >= 0.9 ? "solid" : rb >= 0.7 ? "borderline" : "fragile";
    const tierLine = rb >= 0.9
      ? `${tier} — robustness ${rb.toFixed(2)} sits well above the 0.70 floor`
      : rb >= 0.7
        ? `${tier} — robustness ${rb.toFixed(2)} is in the watch zone (0.70-0.90)`
        : `${tier} — robustness ${rb.toFixed(2)} below 0.70 means at least one common mutation breaks this binding mode`;
    // Triage atoms: priority = clinically frequent + high escape; soft
    // = very_rare or counter-selected ("kills enzyme") mutations.
    const priority: string[] = [];
    const soft: string[] = [];
    for (const v of va.slice(0, 4)) {
      const m = v.top_mutation ?? {};
      const tag = `atom #${v.atom_idx} (${m.wt}${m.position}${m.mutant}, escape ${(v.escape_score ?? 0).toFixed(2)})`;
      const note = (m.note ?? "").toLowerCase();
      const isSoft = (m.frequency === "very_rare")
        || note.includes("counter-selected")
        || note.includes("kills enzyme")
        || (v.escape_score ?? 0) < 0.04;
      (isSoft ? soft : priority).push(tag);
    }
    const lines: string[] = [`Reading the prediction: this candidate looks **${tier}**. ${tierLine}.`];
    if (priority.length) {
      lines.push(`Worth hardening: ${priority.join("; ")}.`);
    }
    if (soft.length) {
      lines.push(`I'd skip ${soft.join("; ")} — the mutation is too rare or counter-selected in the wild to over-engineer for.`);
    }
    return lines.join(" ");
  }

  // Scoring — designer's domain. Keep this conversational, like the
  // designer is reading the result out loud, not dumping JSON.
  if (tool === "score_explain" || tool === "score_molecule" || tool === "score_each") {
    void label; void ms; // older callers passed `label`+`ms`; we craft prose instead
    if (Array.isArray(result)) {
      const tops = result.slice(0, 3).map((r: any) =>
        `\`${r.smiles}\` at **${(r.composite ?? 0).toFixed(3)}**`).join(", ");
      const n = result.length;
      return `Scored ${n} candidate${n === 1 ? "" : "s"}. Top: ${tops}.`;
    }
    if (typeof result.composite === "number") {
      const c = result.composite as number;
      const tier = c >= 0.70 ? "strong" : c >= 0.50 ? "decent" : c >= 0.35 ? "borderline" : "weak";
      const weakest = result.weakest;
      const weakestLine = weakest
        ? ` Weakest axis is \`${weakest}\` — that's the lever for the next pass.`
        : "";
      return `\`${result.smiles}\` lands at composite **${c.toFixed(3)}** — ${tier}.${weakestLine}`;
    }
  }

  // Hardening — editor's domain. Surface Gemini's mechanism + delta
  // estimate so the chat looks like reasoning, not stat-dump.
  if (tool === "harden_atom") {
    const sugs = result.gemini_suggestions ?? result.suggestions ?? [];
    if (sugs.length === 0) return `For atom **#${result.atom_idx}** I couldn't find a viable hardening that beats the current robustness. Try a different atom or run \`/wf optimize_for_property\` to attack a different objective.`;
    const top = sugs[0];
    const after = top?.after_smiles;
    const mech = top?.mechanism ? ` via **${top.mechanism}** chemistry` : "";
    const delta = typeof top?.predicted_robustness_delta === "number"
      ? `, projected Δrobustness +${top.predicted_robustness_delta.toFixed(2)}`
      : "";
    const head = `For atom **#${result.atom_idx}** I'd push **${top?.swap ?? "?"}**${mech} (conf ${(top?.confidence ?? 0).toFixed(2)}${delta})`;
    const tail = after
      ? `. New structure: \`${after}\` — click to load.`
      : top?.rationale
        ? ` — ${String(top.rationale).slice(0, 140)}`
        : ".";
    return head + tail;
  }

  // Pick weak atoms — strategist's call. Frame it as a decision with
  // rationale, not a status line.
  if (stepDef.id === "pick_atoms") {
    return null;  // suppress — predict_resistance already named atoms
  }

  // Compare workflow — the backend returns `best_idx` (an int),
  // not `best_smiles`. Resolve the actual SMILES from rows so the
  // chat narration shows the winner's structure instead of "?".
  if (tool === "compare_resistance") {
    const rows = (result.rows ?? []) as any[];
    const bestIdx = result.best_idx;
    const winner = (typeof bestIdx === "number" && rows[bestIdx]) ? rows[bestIdx] : null;
    if (!winner) {
      return `**${label}**${ms}: no valid winner — all ${rows.length} candidates errored or were equal.`;
    }
    const others = rows.length - 1;
    const common = (result.common_weak_residues ?? []).slice(0, 3)
      .map((r: any) => r.position).join(", ");
    return `**${label}**${ms}: ${rows.length} candidates compared on \`${result.pdb_id}\`. ` +
      `Winner: \`${winner.smiles}\` (rob **${(winner.robustness_score ?? 0).toFixed(2)}**, ` +
      `escape ${winner.n_escape_vectors ?? 0}) beats ${others} other${others === 1 ? "" : "s"}` +
      (common ? `. Common weak residues: **${common}**.` : ".");
  }

  // Cross-target spectrum
  if (tool === "cross_target_risk") {
    return `**${label}**${ms}: tested against ${result.n_targets ?? 0} targets, avg robustness **${(result.avg_robustness ?? 0).toFixed(2)}** — classified as **${result.spectrum ?? "?"}**.`;
  }

  // Multi-agent debate — special: emit a rich debate summary
  if (result?.rounds && Array.isArray(result.rounds)) {
    const rounds = result.rounds;
    const winner = result.winner;
    const runner = result.runner_up;
    const cost = result.cost_usd;
    const tokens = (result.tokens_in ?? 0) + (result.tokens_out ?? 0);
    const out: string[] = [`**Multi-agent debate** complete${ms} — ${rounds.length} rounds, $${(cost ?? 0).toFixed(4)}, ${tokens.toLocaleString()} tokens.`];
    for (const r of rounds) {
      if (r.designer_thinking) out.push(`\n*Designer (round ${r.round}):* ${(r.designer_thinking ?? "").slice(0, 200)}`);
      if (r.critic_thinking) out.push(`\n*Critic (round ${r.round}):* ${(r.critic_thinking ?? "").slice(0, 200)}`);
      if (r.editor_thinking) out.push(`\n*Editor (round ${r.round}):* ${(r.editor_thinking ?? "").slice(0, 200)}`);
    }
    if (winner) out.push(`\n\n**Strategist's verdict**: winner \`${winner}\`, runner-up \`${runner}\`. Next: \`${result.next_action ?? "score"}\`. ${result.justification ?? ""}`);
    return out.join("");
  }

  // Inline / loop / unknown — emit a concrete summary if the result
  // has structure we can describe; otherwise return null so the chat
  // doesn't fill with vacuous "complete" rows.
  // harden_each loop suppressed — each harden_atom emits its own
  // editor narration via the branch above, plus the summary block
  // shows the full structured output. Don't duplicate.
  // No structured detail to narrate — skip the row entirely instead
  // of saying "complete" with no payload (the dead-end the user saw).
  return null;
}

export function WorkbenchV3({ apiBase }: WorkbenchV3Props) {
  // Header state
  const [pathogens, setPathogens] = useState<Pathogen[]>([]);
  const [selectedPathogen, setSelectedPathogen] = useState("MRSA");
  // Hovered atom from 2D builder — drives the AtomDetailCard inspector
  const [hoveredAtom, setHoveredAtom] = useState<number | null>(null);
  // SMARTS match highlight — atoms returned by SMARTSMatchCard, shown as
  // green halo overlay in the 2D builder
  const [smartsHighlight] = useState<number[] | null>(null);
  // Service 1 — 3D Target-Ligand Theater pose data. The Theater window
  // computes pose + binding/clashing atoms, and the 2D builder reflects
  // them as halos so the user sees the SAME atom-level signal in both
  // views. Single source of truth = WorkbenchV3 state.
  const [poseBindingAtoms, setPoseBindingAtoms] = useState<number[]>([]);
  const [poseClashingAtoms, setPoseClashingAtoms] = useState<number[]>([]);
  // Selected PDB target — lifted from the Theater's target picker so
  // sibling cards (Resistance Escape Map, Scoring) can use the same
  // target context.
  const [selectedPdbId, setSelectedPdbId] = useState<string | null>(null);
  // Service 2 — vulnerable atom indices from the Resistance Escape Map.
  // Rendered on the 2D builder as orange halos so the agent sees which
  // atoms are clinically vulnerable AND which are binding/clashing.
  const [vulnerableAtoms, setVulnerableAtoms] = useState<number[]>([]);
  // Cross-link focus from sibling cards. The Resistance Escape Map sets
  // these when the user clicks a heatmap cell or vulnerable-atom row,
  // and Pareto Compare sets them too. The 2D builder paints a lavender
  // pulse on focusedAtomIdx, the 3D theater flashes focusedResidueId.
  // Single source of truth — always reset together when the molecule changes.
  const [focusedAtomIdx, setFocusedAtomIdx] = useState<number | null>(null);
  const [focusedResidueId, setFocusedResidueId] = useState<number | null>(null);
  // Filter state for navbar buttons across containers
  const [drugClassFilter, setDrugClassFilter] = useState<string>("");
  const [scoringPreset, setScoringPreset] = useState<"default" | "mic" | "admet" | "novel">("default");
  const [scoringEmphasis, setScoringEmphasis] = useState<"radar" | "bars" | "tox" | "sim">("radar");
  const [agentFilter, setAgentFilter] = useState<string>("");
  const [actionFilter, setActionFilter] = useState<string>("");
  const [eventKindFilter, setEventKindFilter] = useState<string>("");
  void drugClassFilter; void scoringPreset; void scoringEmphasis; void agentFilter; void actionFilter; void eventKindFilter;
  const [mode, setMode] = useState<"Design" | "Discover" | "Repair" | "Robustify">("Design");
  const [autonomy, setAutonomy] = useState<"Co-pilot" | "Auto" | "Manual">("Co-pilot");
  const [iters, setIters] = useState(4);

  // Session state
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  // Lifecycle of a single chat-message fetch (set on submit, cleared
  // when response/stream returns). Powers the "agent is thinking…"
  // typing indicator so the chat doesn't go blank for 2-9s while the
  // model is processing.
  const [pendingChat, setPendingChat] = useState(false);
  // ---- Multi-chat tabs (Claude.ai-style) -------------------------------
  // Each tab is an independent chat: own events, own slash history.
  // We store events scoped by chat session id (Map preserves insertion order
  // for ordered tab list).
  type ChatTabMeta = { id: string; title: string; userRenamed?: boolean };
  // ── Session persistency ──
  // Chat tabs + their event timelines persist across page refreshes
  // via localStorage. Keyed by user (single-user app for now), schema
  // versioned so future migrations don't blow up old saves.
  const SESSION_KEY = "lysos.session.v1";
  type PersistedSession = {
    tabs: ChatTabMeta[];
    activeChatId: string;
    eventsBySid: Record<string, TraceEvent[]>;
  };
  const _loadPersistedSession = (): PersistedSession | null => {
    try {
      const raw = localStorage.getItem(SESSION_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw) as PersistedSession;
      if (!Array.isArray(parsed.tabs) || parsed.tabs.length === 0) return null;
      return parsed;
    } catch {
      return null;
    }
  };
  const _initialSession = _loadPersistedSession();
  const [chatTabs, setChatTabs] = useState<ChatTabMeta[]>(() => {
    if (_initialSession?.tabs?.length) return _initialSession.tabs;
    const id = `chat-${crypto.randomUUID().slice(0, 8)}`;
    return [{ id, title: "New chat", userRenamed: false }];
  });
  const [activeChatId, setActiveChatId] = useState<string>(
    () => _initialSession?.activeChatId || ""
  );
  // Lazily seed activeChatId after the initial tab is set
  useEffect(() => {
    if (!activeChatId && chatTabs.length > 0) setActiveChatId(chatTabs[0].id);
  }, [activeChatId, chatTabs]);
  const [chatEventsBySid, setChatEventsBySid] = useState<Record<string, TraceEvent[]>>(
    () => _initialSession?.eventsBySid || {}
  );

  // Persist session to localStorage on any change. Debounce-style via
  // microtask: setting state batched in React, single write per tick.
  // Cap each tab's events at 500 so storage doesn't grow unbounded.
  useEffect(() => {
    try {
      const trimmed: Record<string, TraceEvent[]> = {};
      for (const [sid, evs] of Object.entries(chatEventsBySid)) {
        trimmed[sid] = (evs as TraceEvent[]).slice(-500);
      }
      const payload: PersistedSession = {
        tabs: chatTabs,
        activeChatId,
        eventsBySid: trimmed,
      };
      localStorage.setItem(SESSION_KEY, JSON.stringify(payload));
    } catch (exc) {
      // QuotaExceededError or similar — silently drop, the in-memory
      // state is still good for this session.
      void exc;
    }
  }, [chatTabs, activeChatId, chatEventsBySid]);
  // (Slash registry no longer pre-fetched — every slash now goes
  // through the orchestrator agent the same way free text does. The
  // orchestrator decides whether to dispatch it, run a workflow, hand
  // off to the agent loop, or just answer.)
  const events: TraceEvent[] = chatEventsBySid[activeChatId] ?? [];
  function setEvents(updater: TraceEvent[] | ((prev: TraceEvent[]) => TraceEvent[])): void {
    setChatEventsBySid((bySid) => {
      const cur = bySid[activeChatId] ?? [];
      const next = typeof updater === "function" ? (updater as (p: TraceEvent[]) => TraceEvent[])(cur) : updater;
      return { ...bySid, [activeChatId]: next };
    });
  }
  function _legacy_setEvents_unused(_x: TraceEvent[]) { /* kept for refactor safety */ }
  void _legacy_setEvents_unused;

  // ── Auto-title for the active chat tab (LLM summarization) ─────────
  // Watches the active tab's events; after ≥1 user message + every 3
  // subsequent events (debounced 600ms), POSTs /api/chat/title and
  // updates the tab title (uniqueness-checked across siblings).
  const activeChatTab = chatTabs.find((t) => t.id === activeChatId);
  const activeHasUserMsg = events.some((e) => (e as any).agent === "user");
  const otherTitles = chatTabs
    .filter((t) => t.id !== activeChatId)
    .map((t) => t.title);
  useAutoTitle({
    apiBase,
    chatId: activeChatId,
    eventCount: events.length,
    hasUserMessage: activeHasUserMsg,
    isActive: !!activeChatId,
    userRenamed: !!activeChatTab?.userRenamed,
    takenTitles: otherTitles,
    onTitle: (newTitle) => {
      const unique = ensureUniqueTitle(newTitle, otherTitles);
      setChatTabs((tabs) =>
        tabs.map((t) =>
          t.id === activeChatId && !t.userRenamed
            ? { ...t, title: unique }
            : t
        )
      );
    },
  });
  const [constraints, setConstraints] = useState<Constraint[]>([]);
  const [activeTab, setActiveTab] = useState<RightTab>("Radar");
  void activeTab; void setActiveTab; // legacy: tab strip removed, kept for future picker
  // W4: artifact doc populated by streaming /explain markdown chunks.
  const [artifactDoc, setArtifactDoc] = useState<ArtifactDoc>(() => ({
    session_id: "artifact",
    active_smiles: null,
    active_target: null,
    active_score: null,
    blocks: [],
  }));

  // ── Playground canvas state ────────────────────────────────────────
  // Default layout sized for a ~1100px-wide right pane. All windows live
  // in canvas coords and are draggable/resizable. Persists per-chat-tab
  // via localStorage (key = lysos.playground.<chatId>).
  // ─── Playground GROUPS layout ─────────────────────────────────────────
  // Right-pane is now a categorized whiteboard. Four group containers:
  //   CHEMISTRY (emerald)  — 3D theater · 2D atom builder · live atoms
  //   SCORING (amber)      — reward radar
  //   AGENTS (violet)      — designer/critic/editor/strategist trace
  //   KNOWLEDGE (blue)     — artifact pane (only visible after /explain)
  // Each group is draggable + resizable. Cards inside each group are
  // arranged in a 2-col grid (size=2 for full-row cards).
  // Containers default to LANDSCAPE proportions (wider than tall) — they're
  // app-screens, not magazine pages. autoFit:true → height auto-computes
  // from cards. Width is the dimension we hand-tune for proportion.
  const DEFAULT_GROUP_LAYOUT: Record<string, GroupLayout> = {
    // Chem container — DIAGONAL scaling: width AND height grow together
    // proportionally, not just height. Original was 1500×1320 (1.14
    // ratio). New 1700×1480 keeps roughly the same aspect ratio while
    // adding room for left Properties panel + future control panels.
    // The 2D card uses internal scroll for any overflow inside.
    "chem":      { x: 16,   y: 16,   w: 1700, h: 1480, z: 1, autoFit: true },
    "scoring":   { x: 1732, y: 16,   w: 700,  h: 1200, z: 1, autoFit: true },
    "agents":    { x: 1732, y: 1240, w: 700,  h: 1100, z: 1, autoFit: true },
    "knowledge": { x: 16,   y: 1516, w: 1700, h: 1200, z: 1, autoFit: true },
    "live":      { x: 16,   y: 2740, w: 1700, h: 600,  z: 1, autoFit: true },
  };
  const [playgroundGroupLayouts, setPlaygroundGroupLayouts] = useState<Record<string, Record<string, GroupLayout>>>({});
  const [playgroundViewports, setPlaygroundViewports] = useState<Record<string, Viewport>>({});
  const playGroupLayout = playgroundGroupLayouts[activeChatId] ?? DEFAULT_GROUP_LAYOUT;
  const playViewport = playgroundViewports[activeChatId] ?? { pan: { x: 0, y: 0 }, zoom: 1 };
  function setPlayGroupLayoutItem(id: string, next: GroupLayout) {
    setPlaygroundGroupLayouts((m) => ({
      ...m,
      [activeChatId]: { ...(m[activeChatId] ?? DEFAULT_GROUP_LAYOUT), [id]: next },
    }));
  }
  function setPlayViewport(v: Viewport) {
    setPlaygroundViewports((m) => ({ ...m, [activeChatId]: v }));
  }

  // View mode — "whiteboard" (PlaygroundCanvas, all containers floating) vs
  // "tabs" (TabbedView, one container at a time, Claude-style). Stored in
  // localStorage so user's pick persists across reloads. Both modes render
  // the same WindowGroup[] config — just different layouts.
  const [viewMode, _setViewMode] = useState<"whiteboard" | "tabs">(() => {
    try {
      const v = localStorage.getItem("lys-viewmode");
      return v === "tabs" ? "tabs" : "whiteboard";
    } catch { return "whiteboard"; }
  });
  // Active tab ID — lifted out of TabbedView so the merged TopHeader can
  // render the tab strip inline with the rest of the nav (eliminating the
  // wasted second-row sub-nav). TabbedView reads this via controlledActiveId.
  const [playgroundActiveTabId, setPlaygroundActiveTabId] = useState<string>("chemistry");
  // Chat-pane (left Allotment pane) live width — used by TopHeader to
  // align its internal left/right split with the body's vertical
  // divider. Updated by Allotment's onChange.
  const [chatPaneWidth, setChatPaneWidth] = useState<number>(480);
  function setViewMode(v: "whiteboard" | "tabs") {
    _setViewMode(v);
    try { localStorage.setItem("lys-viewmode", v); } catch { /* noop */ }
  }

  // Live playground WebSocket — one connection per active chat tab.
  // Other actors' cursors + applied edits stream through this and propagate
  // to all canvas windows. The connection is permanent for the tab; chat
  // tab switches re-key the hook (handled by activeChatId in the deps).
  const livePlayground = useLivePlayground(activeChatId, apiBase);

  // ── Real DB-backed molecule state ──────────────────────────────────
  // Every time the user picks a scaffold OR applies an edit, we POST to
  // /workbench/playground/sessions/{sid}/molecule which materializes the
  // SMILES into Molecule + Atom + Bond rows in SQLite + broadcasts a
  // molecule.created event on the playground bus.
  // currentMoleculeId is the live "head" molecule id; LiveAtomsCard reads
  // its full state via /molecule/{mid}/state.
  const [currentMoleculeId, setCurrentMoleculeId] = useState<string | null>(null);
  const [editLog, setEditLog] = useState<any[]>([]);

  // Forward-declared ref so runWorkflow (defined before loadSmilesIntoCanvas)
  // can dispatch to emitWorkflowCandidates without a circular hook order.
  const emitWorkflowCandidatesRef = useRef<((wfState: any) => Promise<void>) | null>(null);

  /** Load a SMILES into the playground store + canvas state. Used by
   *  scaffold picker, agent SMILES emissions, and post-edit refresh.
   *
   *  Chat-emission policy:
   *    - silent:true    → no chat rows at all (default seed, internal refresh)
   *    - quiet:true     → tiny one-line "loaded" status pill (library / 3D
   *                       picker), suppresses the full candidate_added card
   *    - default        → small status pill; the candidate_added row is
   *                       deferred to the auto-score effect, which fires it
   *                       only after composite is real (no more 0.000 spam).
   */
  const loadSmilesIntoCanvas = useCallback(async (
    smi: string,
    opts: {
      createdBy?: string;
      parentId?: string | null;
      logLabel?: string;
      /** No chat rows (default seed, programmatic refresh). */
      silent?: boolean;
      /** One-line "loaded" status pill, no candidate card. */
      quiet?: boolean;
    } = {}
  ) => {
    if (!smi || !activeChatId) return null;
    try {
      const r = await fetch(`${apiBase}/workbench/playground/sessions/${activeChatId}/molecule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          smiles: smi,
          parent_id: opts.parentId ?? currentMoleculeId,
          created_by: opts.createdBy ?? "user",
        }),
      });
      if (!r.ok) return null;
      const d = await r.json();
      if (d.molecule_id) {
        setCurrentMoleculeId(d.molecule_id);
        // New molecule means stale cross-link focus — drop it so no
        // halo lingers on an atom/residue from the previous candidate.
        setFocusedAtomIdx(null);
        setFocusedResidueId(null);
        // ALWAYS emit a load_status event so currentSmiles (derived
        // from the events stream) can update — even for silent loads.
        // The `silent` flag on the event tells MessageRow to skip
        // rendering the row, but the SMILES still propagates to all
        // subscribers (2D viewer, 3D theater, scoring pipeline).
        const label = opts.logLabel ?? "[load]";
        setEvents((p) => [
          ...p,
          { type: "load_status", ts: Date.now()/1000, agent: opts.createdBy ?? "user",
            content: `${label} ${smi}`, smiles: smi,
            silent: opts.silent === true } as any,
        ]);
      }
      return d.molecule_id;
    } catch {
      return null;
    }
  }, [activeChatId, apiBase, currentMoleculeId]);

  /** Agent tool-result → UI dispatcher.
   *
   *  This is the "agentic SaaS" cross-link: when the LLM agent calls a
   *  chemistry tool (score_explain, predict_resistance, place_in_pocket,
   *  harden_atom), we mirror the result into the actual UI containers
   *  (Scoring radar, Resistance map atom halos, 2D pose halos) so the
   *  user SEES the agent's work happening in the visual surfaces — not
   *  just buried inside an agent message card.
   *
   *  Single source of truth: agent_state.steps still holds the raw
   *  call+result for the chat card; this dispatcher publishes the
   *  side effects on top.
   */
  // currentSmiles read via ref so this hook ordering is safe — the
  // useMemo for currentSmiles is declared further down. The ref is
  // updated in an effect once currentSmiles becomes available.
  const currentSmilesRef = useRef<string | null>(null);

  const dispatchAgentToolResult = useCallback((tool: string, args: any, result: any) => {
    if (!result || typeof result !== "object") return;
    const liveCurrentSmiles = currentSmilesRef.current;

    // SCORING: score_molecule / score_explain → emit a `score` event
    // (drives Reward Radar, Score Breakdown, Toxicity, Similarity cards).
    if (tool === "score_molecule" || tool === "score_explain") {
      const smi = args?.smiles;
      if (!smi) return;
      const composite: number = typeof result.composite === "number" ? result.composite : 0;
      const scores: Record<string, number> = {};
      if (Array.isArray(result.components)) {
        for (const c of result.components) {
          if (c?.name && typeof c.value === "number") scores[c.name] = c.value;
        }
      }
      setEvents((p) => [...p, {
        type: "score", ts: Date.now() / 1000,
        smiles: smi, scores, composite, agent: "agent",
      } as any]);
      // If the agent scored a SMILES that ISN'T currently loaded, also
      // emit a load_status so the user can click to inspect it.
      if (smi !== liveCurrentSmiles) {
        setEvents((p) => [...p, {
          type: "load_status", ts: Date.now() / 1000,
          agent: "agent",
          content: `[agent · scored] ${smi}`, smiles: smi,
        } as any]);
      }
    }

    // RESISTANCE: predict_resistance → paint vulnerable atom halos on
    // the 2D builder so user sees WHICH atoms are weak.
    if (tool === "predict_resistance") {
      const va = result.vulnerable_atoms;
      if (Array.isArray(va)) {
        const idxs: number[] = va
          .map((v: any) => v?.atom_idx)
          .filter((x: any): x is number => typeof x === "number");
        setVulnerableAtoms(idxs);
      }
    }

    // POSE: place_in_pocket → propagate binding/clashing atoms to 2D.
    if (tool === "place_in_pocket") {
      if (Array.isArray(result.binding_atoms)) setPoseBindingAtoms(result.binding_atoms);
      if (Array.isArray(result.clashing_atoms)) setPoseClashingAtoms(result.clashing_atoms);
      if (result.pdb_id) setSelectedPdbId((prev) => prev ?? result.pdb_id);
    }

    // HARDEN: harden_atom → if the AI suggested a valid hardened SMILES,
    // surface a load chip so the user can promote it with one click.
    if (tool === "harden_atom") {
      const sugs = result.gemini_suggestions ?? result.suggestions ?? [];
      const winner = sugs.find((s: any) => s?.proposed_smiles_valid && s?.proposed_smiles);
      if (winner?.proposed_smiles) {
        setEvents((p) => [...p, {
          type: "load_status", ts: Date.now() / 1000,
          agent: "agent",
          content: `[agent · harden suggests] ${winner.proposed_smiles}`,
          smiles: winner.proposed_smiles,
        } as any]);
      }
    }
  }, []);

  // Forward-declared ref (same trick as emitWorkflowCandidatesRef) so
  // the SSE consumer can dispatch without circular hook ordering.
  const dispatchAgentToolResultRef = useRef(dispatchAgentToolResult);
  useEffect(() => { dispatchAgentToolResultRef.current = dispatchAgentToolResult; }, [dispatchAgentToolResult]);

  /** Mine a completed workflow's state for candidate SMILES and emit
   *  candidate_added rows + auto-load the winner. Used by both the
   *  direct /wf path AND the orchestrator-delegated workflow path. */
  const emitWorkflowCandidates = useCallback(async (wfState: any) => {
    if (!wfState || wfState.status !== "done") return;
    const dump = wfState.state_dump ?? {};
    const ranking: Array<{
      smiles: string; composite?: number; robustness?: number; fitness?: number;
    }> = Array.isArray(dump.ranking) ? dump.ranking : [];
    if (ranking.length === 0) return;
    setEvents((p) => {
      const next = [...p];
      for (const r of ranking) {
        if (!r.smiles) continue;
        next.push({
          type: "candidate_added",
          ts: Date.now() / 1000,
          smiles: r.smiles,
          composite: typeof r.composite === "number" ? r.composite : 0,
          scores: typeof r.composite === "number" ? { composite: r.composite } : undefined,
          agent: "workflow",
          content: `[workflow · ${wfState.name}] fitness=${r.fitness ?? "?"} · rob=${r.robustness ?? "?"}`,
        } as any);
      }
      return next;
    });
    const winner = ranking[0];
    if (winner?.smiles) {
      await loadSmilesIntoCanvas(winner.smiles, {
        createdBy: "workflow",
        parentId: null,
        logLabel: `[workflow · ${wfState.name} · winner]`,
      });
    }
    // Emit a champion-promotion notification card if the workflow.done
    // payload included a champion_promotion side-effect (auto-promote
    // path on the backend).
    const promo = dump.champion_promotion;
    if (promo) {
      setEvents((p) => [...p, {
        type: "agent_message",
        ts: Date.now() / 1000,
        agent: "strategist",
        card_kind: "champion",
        data: {
          mode: "promote",
          promotion: promo,
          pathogen: dump.pathogen,
        },
        content: "",
      } as any]);
      // Wake the Knowledge-tab champion pane up so it refetches.
      try { window.dispatchEvent(new Event("lysos:champion-changed")); } catch {}
    }
  }, [loadSmilesIntoCanvas]);

  // Keep the ref synced so runWorkflow (defined above) can dispatch.
  useEffect(() => {
    emitWorkflowCandidatesRef.current = emitWorkflowCandidates;
  }, [emitWorkflowCandidates]);

  // Auto-clear pendingChat when ANY non-user agent_message lands OR
  // when a workflow_run / orchestrator_run row appears. This drains
  // the typing-indicator state for every code path that produces a
  // visible response, including the slash early-returns (`/load`,
  // `/swap`, `/fg`, `/wf help`, etc) where threading try/finally into
  // every branch is fragile.
  useEffect(() => {
    if (!pendingChat) return;
    if (events.length === 0) return;
    const last = events[events.length - 1] as any;
    const isUser = last.type === "agent_message" && last.agent === "user";
    const isAssistant = last.type === "agent_message" && !isUser;
    const isStream = last.type === "workflow_run" || last.type === "orchestrator_run";
    if (isAssistant || isStream) setPendingChat(false);
  }, [events, pendingChat]);

  /** Stream a workflow run via SSE and inject one workflow_run row into
   *  the chat timeline whose state mutates as events arrive. Reusable
   *  from both the /wf slash command path AND the AgentSuggestionStrip
   *  chip-click path so chip-launch and slash-launch share one code
   *  path (single source of truth for the SSE consumer). */
  const runWorkflow = useCallback(async (name: string, inputs: Record<string, any>) => {
    if (!activeChatId) return;
    const runId = `wfrow-${crypto.randomUUID().slice(0, 8)}`;
    // Echo as a user-side intent message so the chat shows WHAT the
    // user clicked. Without this, suggestion-chip / palette taps were
    // invisible — the workflow card popped in with no context, looking
    // like it appeared from nowhere.
    const argsText = Object.entries(inputs)
      .map(([k, v]) => `${k}=${typeof v === "string" && v.length > 30 ? v.slice(0, 30) + "…" : v}`)
      .join(" ");
    setEvents((p) => [...p, {
      type: "agent_message",
      ts: Date.now() / 1000,
      agent: "user",
      content: `/wf ${name}${argsText ? "  " + argsText : ""}`,
    } as any, {
      type: "workflow_run",
      ts: Date.now() / 1000,
      agent: "assistant",
      run_id: runId,
      api_base: apiBase,
      workflow_state: null,
    } as any]);
    const updateWf = (next: any) => {
      setEvents((evs) => evs.map((e: any) =>
        e.run_id === runId ? { ...e, workflow_state: next } : e));
    };
    let curWf: any = null;
    try {
      const r = await fetch(`${apiBase}/api/workflows/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, inputs, session_id: activeChatId }),
      });
      if (!r.ok || !r.body) {
        const errBody = await r.text().catch(() => "");
        curWf = { run_id: runId, name, label: name, status: "error",
          inputs, steps: [], cancellable: false,
          error: `HTTP ${r.status}: ${errBody.slice(0, 200)}` };
        updateWf(curWf);
        return;
      }
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buf = "";
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        const blocks = buf.split("\n\n");
        buf = blocks.pop() ?? "";
        for (const block of blocks) {
          const line = block.trim();
          if (!line.startsWith("data:")) continue;
          const json = line.slice(5).trim();
          if (!json) continue;
          try {
            const ev = JSON.parse(json);
            curWf = reduceWorkflowEvent(curWf, ev);
            updateWf(curWf);
            // ── Real-LLM agent commentary ──
            // When the backend emits step.narration, it's a real
            // Gemini-written critic/editor/strategist commentary over
            // the just-completed step. Render it as that agent's
            // message. No template strings — this is the actual
            // agentic surface the user asked for.
            if (ev?.event === "step.narration" && ev.text) {
              setEvents((p) => [...p, {
                type: "agent_message",
                ts: Date.now() / 1000,
                agent: ev.role || "assistant",
                content: ev.text,
              } as any]);
              continue;
            }
            // ── Auto-apply: backend asks the canvas to load the
            // editor's chosen SMILES. Closes the gap where the agent
            // narrated 'I'd apply X' but never actually pushed X to
            // the 2D viewer. User feedback: 'the agent dont even
            // execute that updated smiles too'.
            if (ev?.event === "step.apply_smiles" && ev.smiles) {
              try {
                await loadSmilesIntoCanvas(ev.smiles, {
                  createdBy: "agent",
                  parentId: null,
                  logLabel: `[editor → ${ev.swap_label ?? "apply"}]`,
                });
                setEvents((p) => [...p, {
                  type: "agent_message",
                  ts: Date.now() / 1000,
                  agent: "editor",
                  content: `Applied **${ev.swap_label ?? "swap"}** to the canvas — new SMILES: \`${ev.smiles}\`. Re-scoring now.`,
                } as any]);
              } catch (exc: any) {
                setEvents((p) => [...p, {
                  type: "agent_message",
                  ts: Date.now() / 1000,
                  agent: "editor",
                  content: `Couldn't auto-load \`${ev.smiles}\` (${exc?.message ?? exc}). Click the SMILES chip above to load manually.`,
                } as any]);
              }
              continue;
            }
            // Per-step UI dispatch + (legacy) template narration —
            // template only fires if the step had no narrator_role on
            // the backend, so steps without LLM commentary still get
            // a status line.
            if (ev?.event === "step.done" && ev.result) {
              const stepDef = curWf?.steps?.find((s: any) => s.id === ev.step_id);
              if (stepDef?.tool && stepDef.tool !== "__inline__"
                  && stepDef.tool !== "__loop__") {
                dispatchAgentToolResultRef.current?.(
                  stepDef.tool, curWf.inputs ?? {}, ev.result,
                );
              }
              // Skip template narration for steps that have a real
              // narrator — the step.narration event above already
              // emitted a per-agent message. Otherwise fall back to
              // the template so the chat still has a status line.
              const hasNarrator = !!(stepDef?.narrator_role);
              const role = roleForStep(stepDef?.tool, ev.step_id);
              const narration = hasNarrator
                ? null
                : narrateStepResult(stepDef, ev.result, ev.elapsed_ms);
              if (narration) {
                setEvents((p) => [...p, {
                  type: "agent_message",
                  ts: Date.now() / 1000,
                  agent: role,
                  content: narration,
                } as any]);
              }
              // Debate inline step → emit a ProposalCard so the user
              // gets the multi-option Apply / Compare / Decide UX.
              if (ev.step_id === "debate" && ev.result?.winner && ev.result?.runner_up) {
                setEvents((p) => [...p, {
                  type: "agent_message",
                  ts: Date.now() / 1000,
                  agent: "strategist",
                  content: "",
                  card_kind: "proposal",
                  data: {
                    api_base: apiBase,
                    session_id: activeChatId,
                    pathogen: selectedPathogen,
                    title: "Strategist's verdict — pick your winner",
                    verdict: ev.result.justification ?? "",
                    options: [
                      { smiles: ev.result.winner, label: "winner",
                        rationale: ev.result.justification ?? "" },
                      { smiles: ev.result.runner_up, label: "runner-up",
                        rationale: "Strategist's second-choice — useful for A/B vs winner." },
                    ],
                  },
                } as any]);
              }
            }
            // When the workflow finishes, mine state.ranking for candidate
            // SMILES and surface them as `candidate_added` rows so the
            // user sees real load-able candidates in the chat (instead
            // of a buried state_dump). Auto-loads the winner into 2D/3D
            // so the molecule actually changes on screen end-to-end.
            if (ev?.event === "workflow.done") {
              await emitWorkflowCandidatesRef.current?.(curWf);
            }
          } catch { /* malformed */ }
        }
      }
    } catch (exc: any) {
      curWf = { run_id: runId, name, label: name, status: "error",
        inputs, steps: [], cancellable: false,
        error: String(exc?.message ?? exc) };
      updateWf(curWf);
    }
  }, [activeChatId, apiBase]);

  /** Send a message into the chat harness from a sibling card (Resistance
   *  "ask agent", Pareto "explain" with agent fall-through, etc.). Mirrors
   *  the TightComposer onSend flow but skips the input box.
   *
   *  Workflow + special-slash pre-translation: any text that the composer
   *  pipeline knows how to upgrade (e.g. /harden → /wf harden_candidate,
   *  /wf <name> → SSE stream) gets routed through the global auto-slash
   *  channel so the side-card buttons share the SAME agentic path as
   *  composer-typed slashes. Everything else continues to /api/chat for
   *  the legacy harness. */
  const sendAgentMessage = useCallback(async (text: string) => {
    if (!text || !activeChatId) return;
    const trimmed = text.trim();
    // Slashes that the composer's regex translators upgrade into real
    // workflows must dispatch via lysos:auto-slash so they reach the
    // composer pipeline. Otherwise they hit /api/chat and the harness
    // returns "Unknown command: /harden" (since /harden is a frontend
    // pre-translator into /wf harden_candidate, not a registered slash).
    const SHOULD_AUTO_SLASH = (
      /^\/harden\b/i.test(trimmed) ||
      /^\/wf\b/i.test(trimmed)
    );
    if (SHOULD_AUTO_SLASH) {
      setPendingChat(true);
      window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
        detail: { text: trimmed },
      }));
      return;
    }
    setEvents((p) => [...p, {
      type: "agent_message", ts: Date.now() / 1000,
      agent: "user", content: text,
    } as any]);
    setPendingChat(true);
    try {
      const r = await fetch(`${apiBase}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: activeChatId, text,
          // Critical: bridge the ambient UI context so bare slashes
          // (`/explain`, `/score`, `/edit`, …) and side-card "send to
          // agent" buttons resolve from current pathogen/smiles/pdb
          // instead of erroring with "No active candidate".
          pathogen: selectedPathogen,
          smiles: currentSmilesRef.current ?? null,
          pdb_id: selectedPdbId ?? null,
        }),
      });
      if (!r.ok) return;
      const d = await r.json();
      // Use d.card_kind + d.data (the real harness response shape).
      // The earlier d.card check was dead code — that field never
      // existed, which is why "send to agent →" looked like an old
      // hardcoded UI when really it was the lack of a structured card.
      const finalContent = (d?.text && d.text.length > 0)
        ? d.text
        : (d?.error || "(no response)");
      setEvents((p) => [...p, {
        type: "agent_message", ts: Date.now() / 1000,
        // Errors from side-card "send to agent" buttons render under
        // the orchestrator persona too — the chat is a conversation
        // with agents; we never want a raw "system" bubble.
        agent: d?.error ? "orchestrator" : "assistant",
        content: finalContent,
        card_kind: d?.card_kind ?? undefined,
        data: d?.data ?? undefined,
      } as any]);
      // Auto-load the new SMILES into the canvas if the slash returned
      // one (e.g. /edit, /swap, /fg). The user's mental model: when the
      // agent says "Done, new structure is X" → the canvas should
      // visually update WITHOUT them clicking apply.
      const newSmi = (d?.data && typeof d.data === "object" && (d.data as any).smiles) as string | undefined;
      if (newSmi && !d?.error) {
        try {
          await loadSmilesIntoCanvas(newSmi, {
            createdBy: "agent",
            parentId: null,
            logLabel: `[agent edit · ${(d.data as any).edit ?? "edit"}]`,
          });
        } catch {/* canvas already in sync, or load failed silently */}
      }
    } catch { /* */ } finally { setPendingChat(false); }
  }, [activeChatId, apiBase, selectedPathogen, selectedPdbId, loadSmilesIntoCanvas]);

  /** Refresh the recent edit log from /sessions/{sid}/edits — drives the
   *  Edit-log card so the user sees every persisted MoleculeEdit row. */
  const refreshEditLog = useCallback(async () => {
    if (!activeChatId) return;
    try {
      const r = await fetch(`${apiBase}/workbench/playground/sessions/${activeChatId}/edits?limit=40`);
      if (!r.ok) return;
      const d = await r.json();
      setEditLog(d.edits ?? []);
    } catch { /* */ }
  }, [activeChatId, apiBase]);
  // Refresh edit log whenever a new edit lands (via WS) and invalidate
  // the SMILES-keyed molecule-state cache so subscribers (BottomProperties
  // strip, AtomsRail, etc.) automatically re-fetch when an agent mutates
  // the candidate behind the scenes. This is the front-end side of the
  // /molecule/edit WS broadcast we wired in workbench.py.
  useEffect(() => {
    if (!livePlayground.latest) return;
    const ev: any = livePlayground.latest;
    if (ev.event === "edit.applied" || ev.event === "molecule.created") {
      refreshEditLog();
    }
    if (ev.type === "molecule.edit" || ev.event === "molecule.edit") {
      // Invalidate cache for the new SMILES so all subscribers refetch
      // fresh data on the next render tick. Don't need the previous
      // SMILES — once an agent edit lands, all subscribers will move
      // to the new smiles via the canvas state update.
      const nextSmi = ev.smiles ?? ev.payload?.smiles;
      if (nextSmi) {
        invalidateMolCache(nextSmi);
      }
    }
  }, [livePlayground.latest, refreshEditLog]);
  useEffect(() => { refreshEditLog(); }, [refreshEditLog]);

  // Hover-prediction state: when the user hovers an atom, we POST to
  // /workbench/playground/predict-edit and show a ghost polygon on the
  // radar. Cleared on hover-out.
  const [predictedScores, setPredictedScores] = useState<Record<string, number> | null>(null);
  const [predictedLabel, setPredictedLabel] = useState<string>("");
  const predictAbortRef = useRef<AbortController | null>(null);
  async function fetchPrediction(smi: string, atomIdx: number) {
    predictAbortRef.current?.abort();
    const ac = new AbortController();
    predictAbortRef.current = ac;
    // Choose the most "informative" hypothetical: +F (boosts lipophilicity).
    // Future: cycle through ops, show the best-delta one.
    try {
      const r = await fetch(`${apiBase}/workbench/playground/predict-edit`, {
        method: "POST",
        signal: ac.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          smiles: smi,
          edit: { kind: "swap_element", atom_idx: atomIdx, new_element: "F" },
        }),
      });
      if (!r.ok) return;
      const d = await r.json();
      if (!d.ok) {
        setPredictedScores(null);
        setPredictedLabel("");
        return;
      }
      // Score the predicted molecule via /workbench/score
      const sr = await fetch(`${apiBase}/workbench/score`, {
        method: "POST",
        signal: ac.signal,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ smiles: d.new_smiles, target_pathogen: selectedPathogen }),
      });
      if (!sr.ok) return;
      const breakdown = await sr.json();
      const scores: Record<string, number> = {};
      for (const c of breakdown.components ?? []) scores[c.name] = c.value;
      setPredictedScores(scores);
      setPredictedLabel(`if →F at atom ${atomIdx}`);
    } catch { /* aborted or transient */ }
  }
  function clearPrediction() {
    predictAbortRef.current?.abort();
    setPredictedScores(null);
    setPredictedLabel("");
  }
  // Load saved layouts from localStorage on mount per chat
  useEffect(() => {
    if (!activeChatId) return;
    try {
      const raw = localStorage.getItem(`lysos.playground.${activeChatId}`);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed.groupLayout) setPlaygroundGroupLayouts((m) => ({ ...m, [activeChatId]: parsed.groupLayout }));
        if (parsed.viewport) setPlaygroundViewports((m) => ({ ...m, [activeChatId]: parsed.viewport }));
      }
    } catch { /* ignore */ }
  }, [activeChatId]);
  // Persist on change (debounced)
  useEffect(() => {
    if (!activeChatId) return;
    const t = setTimeout(() => {
      try {
        localStorage.setItem(
          `lysos.playground.${activeChatId}`,
          JSON.stringify({ groupLayout: playGroupLayout, viewport: playViewport }),
        );
      } catch { /* quota / disabled */ }
    }, 500);
    return () => clearTimeout(t);
  }, [activeChatId, playGroupLayout, playViewport]);
  const [mechanismOpen, setMechanismOpen] = useState(false);
  void mechanismOpen; void setMechanismOpen; // legacy: middle pane removed; mechanism opens inline now
  const [activeSubAgents, setActiveSubAgents] = useState<string[]>([]);
  const [currentIter, setCurrentIter] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  // Replay speed state — IterationStrip removed from primary layout but
  // kept for future inline render. setSpeed will reactivate when the
  // play/seek/speed control returns inline somewhere.
  const [speed] = useState<1 | 2 | 4>(1);
  void speed;
  const [composite, setComposite] = useState<number | null>(null);
  const [paretoCount, setParetoCount] = useState(0);
  const [resistanceCount, setResistanceCount] = useState(0);
  const [firstLineCount, setFirstLineCount] = useState(0);
  const [activeAgents, setActiveAgents] = useState<string[]>([]);

  const messagesRef = useRef<HTMLDivElement | null>(null);
  const sseRef = useRef<EventSource | null>(null);
  const replayTimer = useRef<number | null>(null);
  const [replayEvents, setReplayEvents] = useState<TraceEvent[] | null>(null);
  const [replayIdx, setReplayIdx] = useState(0);

  // Load pathogens
  useEffect(() => {
    fetch(`${apiBase}/workbench/pathogens`)
      .then((r) => r.json())
      .then((d) => {
        const list = (d.pathogens || []).map((p: any) => ({
          code: p.code,
          name: p.name,
          priority: priorityFor(p.code),
          resistanceCount: p.resistome_count,
          firstLineCount: p.first_line_count,
        }));
        setPathogens(list);
      })
      .catch(() => {});
  }, [apiBase]);

  // Update header stats when pathogen changes
  useEffect(() => {
    const p = pathogens.find((x) => x.code === selectedPathogen);
    setResistanceCount((p as any)?.resistanceCount ?? 0);
    setFirstLineCount((p as any)?.firstLineCount ?? 0);
  }, [selectedPathogen, pathogens]);

  // Auto-scroll on new events
  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight;
    }
  }, [events.length]);

  // Cleanup SSE on unmount
  useEffect(() => () => {
    sseRef.current?.close();
    if (replayTimer.current) window.clearTimeout(replayTimer.current);
  }, []);

  // Replay tick — push next trace event into the events array on a timer
  useEffect(() => {
    if (!isPlaying || !replayEvents) return;
    if (replayIdx >= replayEvents.length) {
      setIsPlaying(false);
      return;
    }
    const next = replayEvents[replayIdx];
    const nextNext = replayEvents[replayIdx + 1];
    const tickMs = nextNext
      ? Math.max(50, Math.min(800, ((nextNext.ts - next.ts) * 1000) / speed))
      : 200;
    replayTimer.current = window.setTimeout(() => {
      handleEvent(next);
      setReplayIdx((i) => i + 1);
    }, tickMs);
    return () => {
      if (replayTimer.current) window.clearTimeout(replayTimer.current);
    };
  }, [isPlaying, replayEvents, replayIdx, speed]);

  // loadReplay() — referenced only by the (now-removed) IterationStrip
  // play button. Re-wire when the inline replay control returns.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  async function loadReplay() {
    if (!sessionId) return;
    const r = await fetch(`${apiBase}/workbench/sandbox/trace/${sessionId}`);
    if (!r.ok) return;
    const d = await r.json();
    setReplayEvents(d.events || []);
    setReplayIdx(0);
    setEvents([]);
    setCurrentIter(0);
    setIsPlaying(true);
  }
  void loadReplay;

  async function startSession() {
    setEvents([]);
    setIsRunning(true);
    setCurrentIter(1);
    setComposite(null);
    setParetoCount(0);
    try {
      const create = await fetch(`${apiBase}/workbench/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_pathogen: selectedPathogen,
          // Backend Literal accepts "design" | "red_team" | "compare" only.
          // Frontend has more labels (Discover/Repair/Robustify); clamp.
          mode: ({ design: "design", discover: "design", repair: "design",
                   robustify: "design" } as Record<string, string>)
                   [mode.toLowerCase()] ?? "design",
          // Backend Literal expects "auto" | "copilot" | "manual" (no dash, no underscore).
          // Frontend label is "Co-pilot" — strip the dash, don't replace.
          autonomy: autonomy.toLowerCase().replace("-", ""),
          constraints: constraints.map((c) => ({ type: "raw", field: "note", value: c.label })),
          max_iterations: iters,
        }),
      }).then((r) => r.json());
      const sid: string = create.session_id;
      setSessionId(sid);

      sseRef.current?.close();
      const es = new EventSource(`${apiBase}/workbench/sessions/${sid}/events`);
      sseRef.current = es;
      es.onmessage = (msg) => {
        try {
          const ev: TraceEvent = JSON.parse(msg.data);
          handleEvent(ev);
        } catch {}
      };
      es.addEventListener("session_complete", () => {
        setIsRunning(false);
        es.close();
      });
      es.addEventListener("error", () => {
        setIsRunning(false);
        es.close();
      });

      await fetch(`${apiBase}/workbench/sessions/${sid}/start`, { method: "POST" });
    } catch (e) {
      console.error(e);
      setIsRunning(false);
    }
  }

  function handleEvent(ev: TraceEvent) {
    setEvents((prev) => [...prev, ev]);
    if (ev.type === "iteration_start" && typeof ev.iteration === "number") {
      setCurrentIter(ev.iteration);
    }
    if (ev.type === "score" && typeof ev.composite === "number") {
      setComposite(ev.composite);
    }
    if (ev.type === "candidate_added") {
      setParetoCount((p) => p + 1);
    }
    if (ev.type === "agent_message" && ev.agent) {
      setActiveAgents((prev) => Array.from(new Set([...prev, ev.agent!])));
    }
  }

  async function intervene(kind: "constraint" | "directive", payload: any) {
    if (kind === "constraint") {
      const id = `c-${Date.now()}`;
      setConstraints((cs) => [...cs, { id, label: payload.label }]);
    }
    if (sessionId && isRunning) {
      await fetch(`${apiBase}/workbench/sessions/${sessionId}/intervene`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind, payload }),
      });
    }
  }

  function exportSession() {
    if (!sessionId) return;
    window.open(`${apiBase}/workbench/sessions/${sessionId}/notebook`, "_blank");
  }

  function reset() {
    sseRef.current?.close();
    setSessionId(null);
    setEvents([]);
    setConstraints([]);
    setIsRunning(false);
    setCurrentIter(0);
    setComposite(null);
    setParetoCount(0);
    setActiveAgents([]);
  }

  const messages = useMemo(() => {
    // ALL user-visible activity counts — must include the SSE-streamed
    // *_run rows (agent_run, workflow_run, orchestrator_run) and the
    // tiny load_status pill, otherwise OnboardingHero + starter
    // prompts persist on top of an active workflow → big visual
    // overlap on every interaction. silent load_status entries are
    // excluded since they shouldn't count as a "real" user message.
    return events.filter((e: any) => {
      const t = e.type;
      if (["agent_message", "tool_call_result", "tool_call_error",
           "candidate_added", "state_change", "intervention", "mol_edit",
           "agent_run", "workflow_run", "orchestrator_run",
          ].includes(t)) return true;
      if (t === "load_status" && !e.silent) return true;
      return false;
    });
  }, [events]);

  // iterCompositeMap fed the (now-removed) IterationStrip's per-iter
  // composite bars. Will reactivate when an inline replay control returns.
  const iterCompositeMap = useMemo(() => {
    const m: Record<number, number> = {};
    for (const e of events) {
      if (e.type === "iteration_end" && typeof e.iteration === "number" && typeof e.composite === "number") {
        m[e.iteration] = e.composite;
      }
    }
    return m;
  }, [events]);
  void iterCompositeMap;

  const currentSmiles = useMemo(() => {
    // Pick the LAST event that carries a SMILES the viewer should show.
    // Order matters: load_status, candidate_added, and mol_edit all
    // count — load_status is what loadSmilesIntoCanvas emits when a
    // user picks a library/scaffold/winner SMILES (no full candidate
    // card until after auto-scoring lands). Without including it here,
    // the 2D viewer would NEVER refresh on library/winner loads, since
    // candidate_added is now gated on composite>0.
    for (let i = events.length - 1; i >= 0; i--) {
      const e: any = events[i];
      if (e.type === "candidate_added" && e.smiles) return e.smiles as string;
      if (e.type === "mol_edit" && e.candidate) return e.candidate as string;
      if (e.type === "load_status" && e.smiles) return e.smiles as string;
    }
    return null;
  }, [events]);

  // Keep currentSmilesRef in lockstep so the agent tool dispatcher
  // (declared above the currentSmiles useMemo to keep hook order safe)
  // can read the live value without taking it as a dependency.
  useEffect(() => { currentSmilesRef.current = currentSmiles; }, [currentSmiles]);

  // lastScores: the latest reward decomposition for the CURRENT SMILES.
  // Tied to currentSmiles so when the canvas changes (via /edit, /load,
  // harden Apply, etc), the radar + score breakdown clear and re-fetch
  // for the new structure instead of showing stale numbers.
  const lastScores = useMemo<Record<string, number> | null>(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i] as any;
      const smi = e.smiles ?? e.parent_smiles;
      const scoresMatchCurrent = !currentSmiles || !smi || smi === currentSmiles;
      if (e.type === "score" && e.scores && scoresMatchCurrent) return e.scores;
      if (e.type === "candidate_added" && e.scores && scoresMatchCurrent) return e.scores;
    }
    return null;
  }, [events, currentSmiles]);

  // lastComposite: backend-authoritative composite for the CURRENT
  // SMILES. Single source of truth so Chat card / Reward radar /
  // Score breakdown can't disagree (user saw 0.463 / 0.473 / 0.355
  // for the same molecule — the breakdown was recomputing Σ wᵢ·sᵢ
  // from a different axis set). Now they all consume this same value.
  const lastComposite = useMemo<number | null>(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i] as any;
      const smi = e.smiles ?? e.parent_smiles;
      const matches = !currentSmiles || !smi || smi === currentSmiles;
      if (!matches) continue;
      if (e.type === "score" && typeof e.composite === "number") return e.composite;
      if (e.type === "candidate_added" && typeof e.composite === "number") return e.composite;
    }
    return null;
  }, [events, currentSmiles]);

  const bestScores = useMemo<Record<string, number> | null>(() => {
    let best: { composite: number; scores: Record<string, number> } | null = null;
    for (const e of events) {
      if (e.type === "candidate_added" && e.scores && typeof e.composite === "number") {
        if (best == null || e.composite > best.composite) {
          best = { composite: e.composite, scores: e.scores };
        }
      }
    }
    // Auto-score side effect: if currentSmiles changes and we don't have
    // scores for it yet, fire /score and inject into events. Debounced via
    // last-scored-smiles tracking to avoid double-fire on rapid edits.
    return best?.scores ?? null;
  }, [events]);

  // ── AUTO-LOAD DEFAULT CANDIDATE — when a session opens with no candidate,
  // seed it with Benzene so every card has data immediately. Avoids the
  // "everything looks empty / broken" first-impression. Once user picks a
  // real scaffold or runs /design, this effect short-circuits because
  // currentSmiles becomes non-null.
  const autoLoadedFor = useRef<string | null>(null);
  useEffect(() => {
    if (!activeChatId || currentSmiles) return;
    if (autoLoadedFor.current === activeChatId) return;
    autoLoadedFor.current = activeChatId;
    // Stagger the auto-load slightly so the WS session is ready first
    const t = setTimeout(() => {
      loadSmilesIntoCanvas("c1ccccc1", {
        createdBy: "system",
        parentId: null,
        logLabel: "[default · benzene]",
        silent: true,  // default seed — no chat noise on first open
      });
    }, 1200);
    return () => clearTimeout(t);
  }, [activeChatId, currentSmiles, loadSmilesIntoCanvas]);

  // ── AUTO-SCORE — when currentSmiles changes and there's no score for it,
  // fire /score asynchronously + inject the result into the events stream.
  // This makes the Scoring container's 4 cards (Radar, Breakdown, Toxicity,
  // Similarity) populate live across the whole workbench without the user
  // having to type /score manually.
  const lastAutoScoredRef = useRef<string | null>(null);
  useEffect(() => {
    if (!currentSmiles || !activeChatId) return;
    if (lastAutoScoredRef.current === currentSmiles) return;
    if (lastScores) return;  // already scored from agent path
    lastAutoScoredRef.current = currentSmiles;
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/score`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ smiles: currentSmiles, target_pathogen: selectedPathogen }),
        });
        if (!r.ok) return;
        const d = await r.json();
        // /workbench/score returns components as an ARRAY of
        //   {name, value, weight, contribution}
        // (NOT keyed by axis name). The earlier Object.entries path
        // turned [0, 1, 2, ...] into the keys and zeroed everything.
        const scores: Record<string, number> = {};
        if (Array.isArray(d.components)) {
          for (const c of d.components) {
            if (c && typeof c.name === "string") {
              scores[c.name] = typeof c.value === "number" ? c.value : 0;
            }
          }
        } else if (d.components && typeof d.components === "object") {
          for (const [k, v] of Object.entries(d.components)) {
            const obj = v as any;
            scores[k] = typeof obj === "number" ? obj : (obj?.value ?? 0);
          }
        }
        const composite = typeof d.composite === "number" ? d.composite : 0;
        // Emit BOTH a `score` row (for radar/explainer) AND a
        // `candidate_added` row (for paretoRows + chat). The candidate
        // row is gated on composite>0 so the chat never shows an
        // unscored "0.000" placeholder. Default seed (silent load) is
        // skipped via the same gate (currentSmiles wouldn't be set
        // until POST returns, and the silent loader sets it without
        // any chat-side flag — so we additionally check the most
        // recent load_status row for `silent` is impossible because
        // silent loads emit none. Practical net: silent loads still
        // get a candidate_added once score lands, BUT the user never
        // sees a 0.000 placeholder).
        setEvents((prev) => {
          // Check whether currentSmiles came from a silent load (the
          // default benzene seed, programmatic refreshes). If so, emit
          // ONLY the score event (which feeds the radar/breakdown
          // cards) but NOT a candidate_added row — those count as
          // "user-initiated candidates" and should never include the
          // system seed.
          let cameFromSilent = false;
          for (let i = prev.length - 1; i >= 0; i--) {
            const e: any = prev[i];
            if (e.type === "load_status" && e.smiles === currentSmiles) {
              cameFromSilent = e.silent === true;
              break;
            }
            if ((e.type === "candidate_added" || e.type === "mol_edit")
                && (e.smiles === currentSmiles || e.candidate === currentSmiles)) {
              break;  // SMILES had a non-silent origin already
            }
          }
          const next: any[] = [
            ...prev,
            { type: "score", ts: Date.now()/1000, smiles: currentSmiles,
              scores, composite } as any,
          ];
          if (composite > 0 && !cameFromSilent) {
            next.push({
              type: "candidate_added",
              ts: Date.now()/1000,
              smiles: currentSmiles,
              composite,
              scores,
              agent: "scorer",
            } as any);
          }
          return next;
        });
      } catch {/*noop*/}
    }, 700);  // 700ms debounce — protects against rapid SMILES edits
    return () => clearTimeout(t);
  }, [currentSmiles, activeChatId, selectedPathogen, apiBase, lastScores]);

  // legacy: paretoRows / molEdits / candEvents fed the old TabStrip panels.
  // Now derived for future Pareto/Lineage windows on the canvas.
  // @ts-expect-error -- intentionally retained for upcoming W6 compare window
  const paretoRows = useMemo(() => {
    return events
      .filter((e) => e.type === "candidate_added" && e.smiles && e.scores)
      .map((e, i) => ({
        id: `c${i}`,
        smiles: e.smiles!,
        scores: e.scores!,
        composite: e.composite ?? 0,
        isPareto: true, // backend marks Pareto inclusion; default true for now
      }));
  }, [events]);

  // @ts-expect-error -- legacy panel-feeder, kept for upcoming Lineage window
  const molEdits = useMemo(
    () =>
      events
        .filter((e) => e.type === "mol_edit" && e.parent && e.candidate)
        .map((e) => ({
          ts: e.ts,
          parent: e.parent!,
          candidate: e.candidate!,
          delta: e.delta as Record<string, number> | undefined,
          agent: e.agent,
        })),
    [events]
  );

  // @ts-expect-error -- legacy panel-feeder, kept for upcoming Lineage window
  const candEvents = useMemo(
    () =>
      events
        .filter((e) => e.type === "candidate_added" && e.smiles)
        .map((e) => ({
          ts: e.ts,
          smiles: e.smiles!,
          composite: e.composite ?? 0,
        })),
    [events]
  );

  // Derive running processes (agent / workflow / orchestrator runs that
  // are currently executing) so the RunningProcessesTray at the top of
  // the chat reflects live system state. Each row is a `RunningProcess`
  // with kind, name, status sub-label, and startedAt timestamp.
  const runningProcesses = useMemo(() => {
    const procs: Array<{
      id: string; kind: "agent" | "workflow" | "score"; name: string;
      status: string; startedAt: number;
      cancellable?: boolean; onClick?: () => void;
    }> = [];
    for (const e of events as any[]) {
      // Workflow runs in flight
      if (e.type === "workflow_run" && e.workflow_state) {
        const ws = e.workflow_state;
        if (ws.status === "running" || ws.status === "pending") {
          const stepsDone = (ws.steps ?? []).filter((s: any) => s.status === "done").length;
          const total = (ws.steps ?? []).length;
          const cur = (ws.steps ?? []).find((s: any) => s.status === "running");
          const sub = cur
            ? `${cur.id ?? cur.name ?? "step"} · ${stepsDone}/${total}`
            : `${stepsDone}/${total} steps`;
          procs.push({
            id: e.run_id ?? `wf-${e.ts}`,
            kind: "workflow",
            name: ws.name ?? ws.label ?? "workflow",
            status: sub,
            startedAt: (e.ts ?? Date.now() / 1000) * 1000,
          });
        }
      }
      // Agent runs in flight
      if (e.type === "agent_run" && e.agent_state) {
        const ast = e.agent_state;
        if (ast.status === "running") {
          procs.push({
            id: e.run_id ?? `ag-${e.ts}`,
            kind: "agent",
            name: "lysos",
            status: ast.n_tool_calls
              ? `${ast.n_tool_calls} tool call${ast.n_tool_calls === 1 ? "" : "s"}`
              : "thinking…",
            startedAt: (e.ts ?? Date.now() / 1000) * 1000,
          });
        }
      }
      // Orchestrator runs in flight
      if (e.type === "orchestrator_run" && e.orchestrator_state) {
        const os = e.orchestrator_state;
        if (os.status === "running") {
          const route = os.plan?.route;
          procs.push({
            id: e.run_id ?? `or-${e.ts}`,
            kind: "agent",
            name: "orchestrator",
            status: route ? `routing → ${route}` : "classifying intent…",
            startedAt: (e.ts ?? Date.now() / 1000) * 1000,
          });
        }
      }
    }
    return procs;
  }, [events]);

  // Top-level tab list for the merged TopHeader. Categories are stable
  // (must match playgroundGroups[].id below). Used only when viewMode=tabs.
  const headerTabsGroups: { id: string; category: any; cards: any[] }[] = [
    { id: "chemistry", category: "Chemistry", cards: [{ id: "_" }] },
    { id: "scoring",   category: "Scoring",   cards: [{ id: "_" }] },
    { id: "agents",    category: "Agents",    cards: [{ id: "_" }] },
    { id: "report",    category: "Report",    cards: [{ id: "_" }] },
    { id: "knowledge", category: "Knowledge", cards: [{ id: "_" }] },
  ];

  // View-mode toggle (whiteboard ↔ tabs). Lifted out of the right-pane
  // IIFE so we can render it alongside the merged tabs strip in
  // TopHeader. The whiteboard-mode floating duplicate is built inline
  // by the right pane.
  const headerViewToggle = (
    <div style={{
      display: "inline-flex",
      background: "transparent",
      border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
      borderRadius: 4,
      height: 22,
      overflow: "hidden",
      flexShrink: 0,
    }}>
      <button type="button"
        onClick={() => setViewMode("whiteboard")}
        title="Whiteboard"
        style={{
          width: 26, height: 22, padding: 0, border: 0, cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          background: viewMode === "whiteboard" ? "var(--lys-text, #0f172a)" : "transparent",
          color: viewMode === "whiteboard" ? "white" : "var(--lys-text-faint, #94a3b8)",
        }}>
        <Maximize2 size={11} />
      </button>
      <button type="button"
        onClick={() => setViewMode("tabs")}
        title="Tabs"
        style={{
          width: 26, height: 22, padding: 0, border: 0, cursor: "pointer",
          display: "flex", alignItems: "center", justifyContent: "center",
          background: viewMode === "tabs" ? "var(--lys-text, #0f172a)" : "transparent",
          color: viewMode === "tabs" ? "white" : "var(--lys-text-faint, #94a3b8)",
        }}>
        <LayoutGrid size={11} />
      </button>
    </div>
  );

  return (
    <div className="lys-shell">
      {/* Floating tool-access popups — bottom-right overlay that surfaces
       *  every tool invocation (running / done / error) with elapsed
       *  timer + args preview. Pulls tool steps from agent_run /
       *  workflow_run rows + tool_call_result events in the chat events
       *  stream (single source of truth). Non-blocking. */}
      <ToolAccessOverlay events={events as any[]} />
      <TopHeader
        pathogens={pathogens}
        selectedPathogen={selectedPathogen}
        onPathogenChange={setSelectedPathogen}
        mode={mode}
        onModeChange={setMode}
        autonomy={autonomy}
        onAutonomyChange={setAutonomy}
        iters={iters}
        onItersChange={setIters}
        onStart={startSession}
        onExport={exportSession}
        onReset={reset}
        isRunning={isRunning}
        composite={composite}
        paretoCount={paretoCount}
        resistanceCount={resistanceCount}
        firstLineCount={firstLineCount}
        activeAgents={activeAgents}
        sessionId={sessionId}
        leftClusterWidth={chatPaneWidth}
        tabsSlot={
          viewMode === "tabs" ? (
            <TabbedViewTabs
              groups={headerTabsGroups}
              activeId={playgroundActiveTabId}
              onActiveIdChange={setPlaygroundActiveTabId}
              leftSlot={headerViewToggle}
            />
          ) : (
            // Whiteboard mode: just the view toggle (let the user flip
            // back to tabs). Right side stays empty otherwise — the
            // canvas itself owns its real estate.
            <div style={{
              display: "flex", alignItems: "center",
              padding: "0 8px",
            }}>
              {headerViewToggle}
            </div>
          )
        }
      />

      {/* IterationStrip moved into a thin hairline below the body bar.
          Removed second-row chrome per redesign — keep only one navbar. */}

      <div className="lys-body">
        {/* Strict 2-pane layout: chat left (35%), playground right (65%).
            Middle pane (legacy 3D + 2D + drag-chips + mechanism) was
            collapsed into the playground as windows per user direction. */}
        <Allotment
          defaultSizes={[35, 65]}
          onChange={(sizes) => {
            // First entry = chat-pane width in px. Drives TopHeader's
            // left/right split so the nav-bar divider tracks the
            // body's vertical splitter dynamically.
            if (sizes && sizes.length > 0 && Number.isFinite(sizes[0])) {
              setChatPaneWidth(Math.round(sizes[0]));
            }
          }}
        >
          {/* CHAT */}
          <Allotment.Pane minSize={340} preferredSize={480}>
            <ChatPanel
              events={events as any}
              isRunning={isRunning}
              isPending={pendingChat}
              totalMsgs={messages.length}
              runningProcesses={runningProcesses}
              showOnboarding={
                <OnboardingHero
                  apiBase={apiBase}
                  onPickPathogen={(code) => {
                    // Pick-pathogen → first-design loop:
                    //  1. set the global pathogen target (drives 3D viewer)
                    //  2. inject a synthetic user message ("/design <code>")
                    //  3. spin the agents — Designer reads the slash command
                    //     and produces the first candidate, Critic chimes in.
                    setSelectedPathogen(code);
                    const tag = code.toLowerCase();
                    setEvents((p) => [
                      ...p,
                      {
                        type: "agent_message",
                        ts: Date.now() / 1000,
                        agent: "user",
                        content: `/design ${tag}`,
                      } as any,
                    ]);
                    if (!isRunning) startSession();
                  }}
                />
              }
              composer={
                <TightComposer
                  isRunning={isRunning}
                  chatEmpty={messages.length === 0}
                  headerSlot={
                    <AgentSuggestionStrip
                      apiBase={apiBase}
                      smiles={currentSmiles}
                      pdbId={selectedPdbId}
                      pathogen={selectedPathogen}
                      hasScore={!!lastScores && Object.keys(lastScores).length > 0}
                      hasResistance={events.some((e: any) =>
                        e.type === "workflow_run" &&
                        e.workflow_state?.name === "harden_candidate" &&
                        e.workflow_state?.status === "done")}
                      hasHarden={events.some((e: any) =>
                        e.type === "workflow_run" &&
                        e.workflow_state?.name === "harden_candidate" &&
                        e.workflow_state?.steps?.some((s: any) => s.id === "harden_each" && s.status === "done"))}
                      nCandidates={Array.from(new Set(events
                        .filter((e: any) => e.type === "candidate_added" && e.smiles)
                        .map((e: any) => e.smiles))).length}
                      sessionCandidates={Array.from(new Set(events
                        .filter((e: any) => e.type === "candidate_added" && e.smiles)
                        .map((e: any) => e.smiles as string))).slice(-5)}
                      onRunWorkflow={(name, inputs) => runWorkflow(name, inputs)}
                      // ALWAYS show the +workflow button — it's the
                      // primary discovery point for advanced workflows.
                      // EMPTY chat → compact (just the +workflow pill).
                      // ACTIVE chat → also compact (suggestion cards
                      //   would duplicate the workflow card in the
                      //   timeline). The slash starter prompts in the
                      //   composer cover the empty-state guidance.
                      compact={true}
                    />
                  }
                  onSend={async (t: string) => {
                    // 1) Echo the user message into the timeline immediately
                    setEvents((p) => [...p, {
                      type: "agent_message",
                      ts: Date.now() / 1000,
                      agent: "user",
                      content: t,
                    } as any]);
                    // Light up the typing indicator instantly so the user
                    // sees "agent is thinking…" while the model warms up.
                    setPendingChat(true);
                    const chatSid = activeChatId;

                    // 1.5) Frontend-side fast-path slash commands that mutate
                    //      the canvas directly — no chat round-trip. The user
                    //      asked: "auto-send features … should not just go as
                    //      plain text but do prompt filling and such working".
                    //      So `/load <SMILES>` and `/swap <atom> <element>`
                    //      fire the actual canvas mutation immediately.
                    const trimmed = t.trim();

                    // /harden <smiles>? pdb=<pdb>?  →  /wf harden_candidate
                    // Buttons (Resistance Escape Map "send to harden",
                    // candidate row "harden", etc.) fire `/harden`. The
                    // backend has no slash for it — it's a workflow.
                    // Pre-translate so the user gets a real streaming
                    // WorkflowCard with steps + critic narration instead
                    // of "Unknown command: /harden".
                    const hardenMatch = trimmed.match(/^\/harden\b\s*(.*)$/i);
                    if (hardenMatch) {
                      const tail = (hardenMatch[1] || "").trim();
                      const inputs: Record<string, any> = {};
                      // Parse "smiles pdb=1VQQ" or "pdb=1VQQ smiles"
                      // or just bare "/harden" (use ambient context).
                      const parts = tail.split(/\s+/).filter(Boolean);
                      for (const p of parts) {
                        if (/^pdb=/i.test(p)) {
                          inputs.pdb_id = p.slice(4).toUpperCase();
                        } else if (/^max_atoms?=\d+$/i.test(p)) {
                          inputs.max_atoms = parseInt(p.split("=")[1], 10);
                        } else if (!inputs.smiles) {
                          // First non-flag token = SMILES
                          inputs.smiles = p;
                        }
                      }
                      // Fall back to ambient context if missing
                      inputs.smiles ??= currentSmilesRef.current ?? currentSmiles ?? null;
                      inputs.pdb_id ??= selectedPdbId ?? "1VQQ";
                      if (!inputs.smiles) {
                        setEvents((p) => [...p, {
                          type: "agent_message", ts: Date.now() / 1000,
                          agent: "user", content: trimmed,
                        } as any, {
                          type: "agent_message", ts: Date.now() / 1000,
                          agent: "orchestrator",
                          content: "Hardening needs a candidate SMILES. Load one (or run `/design`) and try `/harden` again.",
                        } as any]);
                        return;
                      }
                      await runWorkflow("harden_candidate", inputs);
                      return;
                    }

                    // /load <SMILES>  → load directly into 2D + 3D + auto-score.
                    // Pre-flight: reject obvious non-SMILES tokens (English
                    // words, accept-phrases the orchestrator may have
                    // hallucinated into smiles, etc.) so the canvas
                    // doesn't error with "Could not load 'ship'". Real
                    // SMILES have at least one non-letter chemistry char
                    // or are length>=2 with explicit atom syntax.
                    const loadMatch = trimmed.match(/^\/load\s+(\S.*)$/i);
                    if (loadMatch) {
                      const smi = loadMatch[1].trim();
                      // Lightweight SMILES sniff. Real SMILES contain at
                      // least one of: digit, parenthesis, bracket, =, #,
                      // /, \, @, -, +, or are a multi-atom string. Plain
                      // English words ("ship", "apply", "do it") fail
                      // this check and don't waste a canvas reload.
                      const looksLikeSmiles = /[0-9()\[\]=#\/\\@+\-]/.test(smi)
                        || /[A-Z][a-z]?[A-Z]/.test(smi)   // multi-cap (BrCl etc.)
                        || smi.length === 1 && /[A-Z]/.test(smi);  // single-atom
                      if (!looksLikeSmiles) {
                        setEvents((p) => [...p, {
                          type: "agent_message",
                          ts: Date.now() / 1000,
                          agent: "orchestrator",
                          content: `\`${smi}\` doesn't look like a SMILES — `
                            + `it might be a chat phrase like 'ship it' or `
                            + `'apply'. Did you mean to say **apply**? `
                            + `(That accepts a pending agent proposal.)`,
                        } as any]);
                        return;
                      }
                      const id = await loadSmilesIntoCanvas(smi, {
                        createdBy: "user",
                        parentId: null,
                        logLabel: "[/load]",
                      });
                      if (!id) {
                        setEvents((p) => [...p, {
                          type: "agent_message",
                          ts: Date.now() / 1000,
                          agent: "lysos",
                          content: `Couldn't parse \`${smi}\` as a valid SMILES. Try \`/design\` for a fresh candidate or paste a canonical form.`,
                        } as any]);
                        return;
                      }
                      // Agent-voiced placeholder so the chat reads as the
                      // agent owning the action — NOT the old "Loaded X
                      // into 2D+3D. Re-scoring…" script. Once Gemini Flash
                      // returns with the proper narration we splice in the
                      // model's line over this placeholder.
                      const narratorId = `narr_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
                      setEvents((p) => [...p, {
                        type: "agent_message",
                        ts: Date.now() / 1000,
                        agent: "lysos",
                        content: `On it — picking up \`${smi}\` and scoring against ${selectedPathogen || "MRSA"} now.`,
                        _narratorId: narratorId,
                      } as any]);
                      void (async () => {
                        try {
                          const r = await fetch(`${apiBase}/api/orchestrator/narrate`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                              session_id: chatSid,
                              action: "load",
                              smiles: smi,
                              pathogen: selectedPathogen || "MRSA",
                              last_composite: lastComposite,
                              trigger: "manual",
                            }),
                          });
                          const d = await r.json();
                          const line = (d && d.narration) ? String(d.narration).trim() : "";
                          if (line) {
                            setEvents((p) => p.map((e: any) =>
                              e._narratorId === narratorId
                                ? { ...e, content: line }
                                : e
                            ));
                          }
                        } catch { /* keep the placeholder line, the canvas already updated */ }
                      })();
                      return;
                    }

                    // /swap <atomIdx> <element>  → atom-element swap
                    const swapMatch = trimmed.match(/^\/swap\s+(\d+)\s+([A-Z][a-z]?)\s*$/);
                    if (swapMatch && currentSmiles) {
                      const atomIdx = parseInt(swapMatch[1], 10);
                      const newEl = swapMatch[2];
                      try {
                        const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            smiles: currentSmiles,
                            op: "swap_element",
                            atom_index: atomIdx,
                            new_element: newEl,
                            actor: "user",
                            session_id: activeChatId,
                          }),
                        });
                        const d = await r.json();
                        if (d.smiles) {
                          await loadSmilesIntoCanvas(d.smiles, {
                            createdBy: "user",
                            parentId: currentMoleculeId,
                            logLabel: `[/swap atom=${atomIdx} → ${newEl}]`,
                          });
                          setEvents((p) => [...p, {
                            type: "agent_message",
                            ts: Date.now() / 1000,
                            agent: "assistant",
                            content: `Swapped atom ${atomIdx} → ${newEl}. New SMILES: \`${d.smiles}\``,
                          } as any]);
                        } else {
                          setEvents((p) => [...p, {
                            type: "agent_message",
                            ts: Date.now() / 1000,
                            agent: "orchestrator",
                            content: `I tried to swap atom ${atomIdx}, but the chemistry tool refused: ${d.error ?? "unknown reason"}. Want me to try a different atom or element?`,
                          } as any]);
                        }
                      } catch (exc: any) {
                        setEvents((p) => [...p, {
                          type: "agent_message",
                          ts: Date.now() / 1000,
                          agent: "orchestrator",
                          content: `I lost the connection while swapping that atom — ${exc?.message ?? exc}. Mind retrying once we're back?`,
                        } as any]);
                      }
                      return;
                    }

                    // /fg <atomIdx> <fg_name>  → add functional group
                    const fgMatch = trimmed.match(/^\/fg\s+(\d+)\s+(\S+)\s*$/i);
                    if (fgMatch && currentSmiles) {
                      const atomIdx = parseInt(fgMatch[1], 10);
                      const fg = fgMatch[2].toLowerCase();
                      try {
                        const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            smiles: currentSmiles,
                            op: "add_functional_group_at",
                            atom_index: atomIdx,
                            functional_group: fg,
                            actor: "user",
                            session_id: activeChatId,
                          }),
                        });
                        const d = await r.json();
                        if (d.smiles) {
                          await loadSmilesIntoCanvas(d.smiles, {
                            createdBy: "user",
                            parentId: currentMoleculeId,
                            logLabel: `[/fg atom=${atomIdx} +${fg}]`,
                          });
                          setEvents((p) => [...p, {
                            type: "agent_message",
                            ts: Date.now() / 1000,
                            agent: "assistant",
                            content: `Added ${fg} at atom ${atomIdx}. New SMILES: \`${d.smiles}\``,
                          } as any]);
                        } else {
                          setEvents((p) => [...p, {
                            type: "agent_message",
                            ts: Date.now() / 1000,
                            agent: "orchestrator",
                            content: `Couldn't add the ${fg} group at atom ${atomIdx} — ${d.error ?? "the chemistry tool refused"}. Want me to suggest a different position?`,
                          } as any]);
                        }
                      } catch (exc: any) {
                        setEvents((p) => [...p, {
                          type: "agent_message",
                          ts: Date.now() / 1000,
                          agent: "orchestrator",
                          content: `Network blipped while adding the functional group — ${exc?.message ?? exc}.`,
                        } as any]);
                      }
                      return;
                    }

                    // 2) /wf <name> {json}  → run a workflow as SSE stream.
                    //    Other slash commands → legacy /api/chat (registered handlers).
                    //    Free text → /api/agent/run SSE (Gemini Pro tool-calling).

                    // 2a) /wf help OR bare /wf → render workflow catalog in
                    //    chat. The composer's pop-up catalog (the "+ workflow"
                    //    button) only works on click; users typing /wf help
                    //    should still get the list inline. (`trimmed` is
                    //    already declared a few lines up — reuse it.)
                    if (/^\/wf(\s+help)?\s*$/i.test(trimmed)) {
                      try {
                        setEvents((p) => [...p, {
                          type: "agent_message", ts: Date.now() / 1000,
                          agent: "user", content: trimmed,
                        } as any]);
                        const r = await fetch(`${apiBase}/api/workflows/list`);
                        if (!r.ok) {
                          setEvents((p) => [...p, {
                            type: "agent_message", ts: Date.now() / 1000,
                            agent: "orchestrator",
                            content: `I couldn't reach the workflow registry (HTTP ${r.status}). Backend might be reloading — try again in a sec.`,
                          } as any]);
                          return;
                        }
                        const d = await r.json();
                        const wfs = (d.workflows ?? d ?? []) as any[];
                        const lines: string[] = [
                          `### Available workflows · ${wfs.length}`,
                          "",
                          "| name | what it does | required inputs |",
                          "|---|---|---|",
                        ];
                        for (const w of wfs) {
                          const reqs = (w.inputs ?? [])
                            .filter((i: any) => i.required)
                            .map((i: any) => `\`${i.name}\``).join(" ");
                          lines.push(
                            `| **\`/wf ${w.name}\`** | ${(w.description || w.label || "").replace(/\|/g, "·")} | ${reqs || "_none_"} |`,
                          );
                        }
                        lines.push("");
                        lines.push("_Tip_: `/wf <name> {\"key\":\"value\"}` to pass JSON inputs. Bare slash auto-fills from context.");
                        setEvents((p) => [...p, {
                          type: "agent_message", ts: Date.now() / 1000,
                          agent: "assistant", content: lines.join("\n"),
                        } as any]);
                      } catch (exc: any) {
                        setEvents((p) => [...p, {
                          type: "agent_message", ts: Date.now() / 1000,
                          agent: "orchestrator",
                          content: `I had trouble fetching the workflow list — ${exc?.message ?? exc}. Want to keep going manually with \`/wf <name>\`?`,
                        } as any]);
                      }
                      return;
                    }

                    // Accept BOTH JSON and key=value forms:
                    //   /wf harden_candidate {"smiles": "...", "pdb_id": "1VQQ"}
                    //   /wf harden_candidate smiles=Cc1c(C#N)... pdb_id=1VQQ
                    //   /wf harden_candidate                          ← bare, ambient context
                    // Also tolerates newlines inside the JSON body
                    // (so wrapped chat-rendered slashes still parse).
                    const KNOWN_WORKFLOWS = new Set([
                      "design_with_debate", "harden_candidate",
                      "broad_spectrum_screen", "compare_top_n",
                      "optimize_for_property", "pareto_explore",
                      "discover_and_assess",
                    ]);
                    const wfMatch = t.trim().match(/^\/wf\s+(\S+)\s*([\s\S]*)$/i);
                    if (wfMatch) {
                      const wfName = wfMatch[1];
                      // If the typed name isn't a real workflow, treat the
                      // whole `/wf <natural language>` line as free text and
                      // let the orchestrator (Gemini) pick the right
                      // workflow. Avoids the 404 "unknown workflow: do"
                      // when the user types `/wf do anyworkflow from the
                      // options`.
                      if (!KNOWN_WORKFLOWS.has(wfName.toLowerCase())) {
                        // Render the workflow catalog inline as clickable
                        // chips. No auto-routing through the orchestrator
                        // (caused double user-message echo) and no
                        // robotic "rerouting" text. The user sees the
                        // 7 real workflows and picks one.
                        const wfs = [
                          ["design_with_debate",   "Designer ↔ Critic ↔ Editor ↔ Strategist debate to propose new candidates"],
                          ["harden_candidate",     "Find weak atoms + propose hardening edits against PBP2a / target"],
                          ["broad_spectrum_screen","Screen one SMILES against all priority pathogens"],
                          ["compare_top_n",        "Side-by-side comparison of N candidates on every axis"],
                          ["optimize_for_property","Iteratively improve a SMILES on one property (logP, MW, etc.)"],
                          ["pareto_explore",       "Explore the Pareto frontier across multiple objectives"],
                          ["discover_and_assess",  "Pull a candidate from the library + score it"],
                        ] as const;
                        const md = [
                          `I don't recognize \`${wfName}\` as a workflow. Pick one of these (click to run):`,
                          "",
                          ...wfs.map(([n, d]) => `- \`/wf ${n}\` — ${d}`),
                        ].join("\n");
                        setEvents((p) => [...p, {
                          type: "agent_message", ts: Date.now() / 1000,
                          agent: "orchestrator",
                          content: md,
                        } as any]);
                        return;
                      }
                      let wfInputs: Record<string, any> = {};
                      const argTail = (wfMatch[2] || "").trim();
                      // Try JSON first if the tail looks JSON-y
                      try {
                        if (argTail.startsWith("{")) {
                          // Extract just the {…} block (in case there's trailing text)
                          const m = argTail.match(/\{[\s\S]*\}/);
                          if (m) wfInputs = JSON.parse(m[0]);
                        } else if (argTail) {
                          // key=value form — split on whitespace, parse each pair
                          for (const pair of argTail.split(/\s+/)) {
                            const eq = pair.indexOf("=");
                            if (eq <= 0) continue;
                            const k = pair.slice(0, eq).trim();
                            const v = pair.slice(eq + 1).trim();
                            if (k && v) {
                              // Try numeric coercion for things like max_atoms=3
                              const numV = Number(v);
                              wfInputs[k] = !isNaN(numV) && /^\d+(?:\.\d+)?$/.test(v) ? numV : v;
                            }
                          }
                        }
                      } catch (_e) {/* fall through with empty inputs — ambient context fallback below fills them */}
                      // Auto-fill obvious context defaults
                      if (wfName === "harden_candidate" || wfName === "broad_spectrum_screen" ||
                          wfName === "optimize_for_property") {
                        // Fall back to a benzene seed so workflows that
                        // REQUIRE smiles never crash on "step predict
                        // args failed" when no candidate is loaded yet.
                        wfInputs.smiles ??= currentSmiles || "c1ccccc1";
                      }
                      if (wfName === "harden_candidate" || wfName === "discover_and_assess" ||
                          wfName === "compare_top_n") {
                        wfInputs.pdb_id ??= selectedPdbId ?? "1VQQ";
                      }
                      if (wfName === "compare_top_n") {
                        // Auto-fill smiles_list from recent session
                        // candidates so /wf compare_top_n doesn't crash
                        // on a missing required arg.
                        if (!wfInputs.smiles_list || (Array.isArray(wfInputs.smiles_list) && wfInputs.smiles_list.length === 0)) {
                          const cands = Array.from(new Set(events
                            .filter((e: any) => e.type === "candidate_added" && e.smiles)
                            .map((e: any) => e.smiles as string)));
                          wfInputs.smiles_list = cands.length > 0
                            ? cands.slice(-3)
                            : (currentSmiles ? [currentSmiles] : ["c1ccccc1"]);
                        }
                      }
                      if (wfName === "discover_and_assess" || wfName === "optimize_for_property") {
                        wfInputs.pathogen ??= selectedPathogen;
                      }
                      runWorkflow(wfName, wfInputs);
                      return;
                    }
                    // ── Agentic delegation ──
                    // Slashes are intent shortcuts, not bypasses. The
                    // orchestrator agent SEES every chat message — slash
                    // OR free text — and decides whether to dispatch a
                    // slash, run a workflow, hand off to the agent
                    // loop, or just answer. This matches Claude /
                    // Cursor: the agent is the front door, never
                    // bypassed. Canvas fast-paths (/load, /swap, /fg,
                    // /harden, /wf) are handled ABOVE this point
                    // because they mutate visuals immediately and
                    // don't need a Gemini round-trip.

                    // 3) Free text + unhandled slash → ORCHESTRATOR stream.
                    //    Plain English routes through /api/orchestrator/run,
                    //    which uses Gemini Pro to classify intent and pick
                    //    one of: workflow / slash / agent / answer. The
                    //    chosen route's downstream events are wrapped in
                    //    orchestrator.delegate sub-events so the chat shows
                    //    the routing decision + the live execution.
                    //    For dispatch_slash, we capture it locally and
                    //    re-trigger onSend() with the rendered slash so the
                    //    existing slash-command handlers fire (no duplicate
                    //    code path).
                    const runId = `run-${crypto.randomUUID().slice(0, 8)}`;
                    const initOrch: OrchestratorState = {
                      run_id: runId,
                      user_text: t,
                      status: "running",
                    };
                    setEvents((p) => [...p, {
                      type: "orchestrator_run",
                      ts: Date.now() / 1000,
                      agent: "orchestrator",
                      run_id: runId,
                      api_base: apiBase,
                      orchestrator_state: initOrch,
                    } as any]);

                    const updateRow = (next: OrchestratorState) => {
                      setEvents((evs) => evs.map((e: any) =>
                        e.run_id === runId ? { ...e, orchestrator_state: next } : e));
                    };
                    let curOrch: OrchestratorState = initOrch;
                    let dispatchedSlash: string | null = null;
                    // Ship the last ~14 visible chat messages so the
                    // orchestrator agent has conversational context for
                    // follow-up turns ("check the current candidate",
                    // "list commands", "check the agent traces").
                    const recentMessages = events
                      .filter((e: any) => e.type === "agent_message" && (e.content || "").length > 0)
                      .slice(-14)
                      .map((e: any) => ({
                        agent: e.agent || "system",
                        content: String(e.content || "").slice(0, 500),
                        ts: e.ts,
                      }));
                    try {
                      const r = await fetch(`${apiBase}/api/orchestrator/run`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({
                          session_id: chatSid,
                          text: t,
                          smiles: currentSmiles ?? null,
                          pathogen: selectedPathogen,
                          pdb_id: selectedPdbId ?? null,
                          last_composite: null,
                          n_candidates: 0,
                          recent_messages: recentMessages,
                        }),
                      });
                      if (!r.ok || !r.body) {
                        curOrch = { ...curOrch, status: "error",
                          error: `HTTP ${r.status}` };
                        updateRow(curOrch);
                        return;
                      }
                      const reader = r.body.getReader();
                      const decoder = new TextDecoder();
                      let buf = "";
                      for (;;) {
                        const { value, done } = await reader.read();
                        if (done) break;
                        buf += decoder.decode(value, { stream: true });
                        const blocks = buf.split("\n\n");
                        buf = blocks.pop() ?? "";
                        for (const block of blocks) {
                          const line = block.trim();
                          if (!line.startsWith("data:")) continue;
                          const json = line.slice(5).trim();
                          if (!json) continue;
                          try {
                            const ev = JSON.parse(json);
                            curOrch = reduceOrchestratorEvent(curOrch, ev);
                            updateRow(curOrch);
                            // Capture dispatch_slash so we can fire it
                            // automatically once the orchestrator is done.
                            if (ev?.event === "orchestrator.dispatch_slash" && ev.rendered) {
                              dispatchedSlash = ev.rendered;
                            }
                            // AGENT TOOL → UI dispatcher: when the
                            // orchestrator delegates to the agent loop
                            // and a `tool.result` lands inside, mirror
                            // it into the actual UI containers (radar,
                            // resistance halos, pose halos) so the user
                            // sees the agent doing the work, not just
                            // chatting about it.
                            if (ev?.event === "orchestrator.delegate"
                                && ev.sub_kind === "agent"
                                && ev.sub_event?.event === "tool.result") {
                              const callId = ev.sub_event.call_id;
                              for (let k = (curOrch.sub_events?.length ?? 0) - 1; k >= 0; k--) {
                                const s = curOrch.sub_events?.[k];
                                if (s?.event === "tool.call" && s.call_id === callId) {
                                  dispatchAgentToolResultRef.current?.(
                                    s.tool, s.args, ev.sub_event.result,
                                  );
                                  break;
                                }
                              }
                            }
                            // WORKFLOW STEP → UI dispatcher + chat narration.
                            // Two side effects per completed step:
                            //   (1) propagate the result into chemistry
                            //       visuals via dispatchAgentToolResult
                            //   (2) emit a per-agent chat row narrating
                            //       what just happened so the user sees
                            //       strategist/critic/editor actively
                            //       doing work in the timeline, not just
                            //       a workflow card collapsing.
                            if (ev?.event === "orchestrator.delegate"
                                && ev.sub_kind === "workflow"
                                && ev.sub_event?.event === "step.done"
                                && ev.sub_event.result) {
                              const stepId = ev.sub_event.step_id;
                              const planEv = curOrch.sub_events?.find(
                                (s) => s?.event === "workflow.plan");
                              const stepDef = planEv?.steps?.find(
                                (s: any) => s.id === stepId);
                              if (stepDef?.tool && stepDef.tool !== "__inline__"
                                  && stepDef.tool !== "__loop__") {
                                const wfStart = curOrch.sub_events?.find(
                                  (s) => s?.event === "workflow.start");
                                const synthArgs = wfStart?.inputs ?? {};
                                dispatchAgentToolResultRef.current?.(
                                  stepDef.tool, synthArgs, ev.sub_event.result,
                                );
                              }
                              // Narrate the step in the chat: pick the
                              // owning agent (strategist/critic/editor)
                              // and emit a human message summarizing
                              // what the result revealed.
                              const role = roleForStep(stepDef?.tool, stepId);
                              const narration = narrateStepResult(
                                stepDef, ev.sub_event.result, ev.sub_event.elapsed_ms,
                              );
                              if (narration) {
                                setEvents((p) => [...p, {
                                  type: "agent_message",
                                  ts: Date.now() / 1000,
                                  agent: role,
                                  content: narration,
                                } as any]);
                              }
                              // Debate → emit ProposalCard for multi-option pick.
                              if (stepId === "debate"
                                  && ev.sub_event.result?.winner
                                  && ev.sub_event.result?.runner_up) {
                                setEvents((p) => [...p, {
                                  type: "agent_message",
                                  ts: Date.now() / 1000,
                                  agent: "strategist",
                                  content: "",
                                  card_kind: "proposal",
                                  data: {
                                    api_base: apiBase,
                                    session_id: chatSid,
                                    pathogen: selectedPathogen,
                                    title: "Strategist's verdict — pick your winner",
                                    verdict: ev.sub_event.result.justification ?? "",
                                    options: [
                                      { smiles: ev.sub_event.result.winner, label: "winner",
                                        rationale: ev.sub_event.result.justification ?? "" },
                                      { smiles: ev.sub_event.result.runner_up, label: "runner-up",
                                        rationale: "Strategist's second-choice — useful for A/B vs winner." },
                                    ],
                                  },
                                } as any]);
                              }
                            }
                            // When the delegated workflow finishes,
                            // mine the inner workflow.done event for
                            // candidates (same as the direct /wf path).
                            if (ev?.event === "orchestrator.delegate"
                                && ev.sub_kind === "workflow"
                                && ev.sub_event?.event === "workflow.done") {
                              // Build a synthetic workflow_state from
                              // all the delegated workflow events so
                              // emitWorkflowCandidates has the same
                              // input shape as the direct path.
                              let syntheticWf: any = null;
                              for (const sub of curOrch.sub_events ?? []) {
                                if (sub.sub_kind && sub.sub_kind !== "workflow") continue;
                                syntheticWf = reduceWorkflowEvent(syntheticWf, sub);
                              }
                              if (syntheticWf) {
                                await emitWorkflowCandidatesRef.current?.(syntheticWf);
                              }
                            }
                          } catch { /* malformed line */ }
                        }
                      }
                    } catch (exc: any) {
                      curOrch = { ...curOrch, status: "error",
                        error: String(exc?.message ?? exc) };
                      updateRow(curOrch);
                    } finally {
                      // Orchestrator stream finished (or crashed) — drop
                      // the pending flag so the typing indicator clears.
                      // The orchestrator's own status pill remains, and
                      // any downstream slash that gets auto-dispatched
                      // sets pendingChat back to true via setPendingChat
                      // in its own onSend recursion.
                      setPendingChat(false);
                    }

                    // Auto-dispatch the slash command the orchestrator chose.
                    // Fire-and-forget: re-enter onSend with the rendered
                    // slash so the existing /score / /design / /harden …
                    // handlers run end-to-end. This is the "auto-slash
                    // routing" the user asked for — agent understands `/`
                    // commands from plain English without the user typing
                    // them explicitly.
                    if (dispatchedSlash) {
                      const renderedFinal = dispatchedSlash;
                      // Hit /api/chat directly to EXECUTE the slash the
                      // orchestrator picked. We can't re-enter onSend
                      // (it now routes everything through the
                      // orchestrator → infinite loop). The user already
                      // sees the dispatch choice in the OrchestratorCard
                      // above, so just run it and surface the result.
                      try {
                        const r = await fetch(`${apiBase}/api/chat`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            session_id: chatSid,
                            text: renderedFinal,
                            pathogen: selectedPathogen,
                            smiles: currentSmiles ?? null,
                            pdb_id: selectedPdbId ?? null,
                          }),
                        });
                        if (!r.ok) {
                          const errTxt = await r.text();
                          setEvents((p) => [...p, {
                            type: "agent_message",
                            ts: Date.now() / 1000,
                            agent: "orchestrator",
                            content: `Tried to run \`${renderedFinal}\` but got HTTP ${r.status}: ${errTxt.slice(0, 160)}`,
                          } as any]);
                          return;
                        }
                        const d = await r.json();
                        const finalContent = (d.text && d.text.length > 0)
                          ? d.text
                          : (d.error || "(no response)");
                        setEvents((p) => [...p, {
                          type: "agent_message",
                          ts: Date.now() / 1000,
                          agent: d.error ? "orchestrator" : "assistant",
                          content: finalContent,
                          card_kind: d.card_kind ?? undefined,
                          data: d.data ?? undefined,
                        } as any]);
                        // Auto-load returned SMILES into 2D + 3D when
                        // /load / /edit / /swap return one (same logic
                        // sendAgentMessage uses).
                        const newSmi = (d?.data && typeof d.data === "object" && (d.data as any).smiles) as string | undefined;
                        if (newSmi && !d?.error) {
                          try {
                            await loadSmilesIntoCanvas(newSmi, {
                              createdBy: "agent",
                              parentId: null,
                              logLabel: `[orchestrator → ${renderedFinal.split(" ")[0]}]`,
                            });
                          } catch {/* canvas already in sync */}
                        }
                      } catch (exc: any) {
                        setEvents((p) => [...p, {
                          type: "agent_message",
                          ts: Date.now() / 1000,
                          agent: "orchestrator",
                          content: `Couldn't execute \`${renderedFinal}\` — ${exc?.message ?? exc}`,
                        } as any]);
                      }
                    }
                  }}
                  onIntervene={intervene}
                  constraints={constraints}
                  onRemoveConstraint={(id: string) => setConstraints((cs) => cs.filter((c) => c.id !== id))}
                />
              }
              onIngestEvent={(ev) => {
                // SSE-streamed events from a DesignSessionCard etc. land here
                // and become rows in the chat timeline.
                setEvents((p) => [...p, ev as any]);
              }}
              onReplaySession={(p) => {
                // W7+W8: spawn a fresh chat tab named after the session,
                // switch to it, then open SSE on the workbench session id
                // so its persisted events stream into the new tab.
                const newTabId = `chat-${crypto.randomUUID().slice(0, 8)}`;
                const title = `replay ${p.target} · ${p.sessionId.slice(0, 8)}`;
                setChatTabs((tabs) => [...tabs, { id: newTabId, title, userRenamed: true }]);
                setActiveChatId(newTabId);
                // Wait one tick for the tab swap, then open SSE
                setTimeout(() => {
                  const url = p.sseUrl.startsWith("http")
                    ? p.sseUrl
                    : `${window.location.origin}${p.sseUrl}`;
                  const es = new EventSource(url);
                  const types = [
                    "message", "agent_message", "candidate_added",
                    "iteration_start", "iteration_end", "score",
                    "tool_call_result", "tool_call_error",
                    "session_complete", "agent_idle", "error",
                    "intervention_queued",
                  ];
                  const onMsg = (ev: MessageEvent) => {
                    try {
                      const e = JSON.parse(ev.data ?? "{}");
                      const chatMsg: any = {
                        type: e.type ?? "agent_message",
                        ts: Date.now() / 1000,
                        agent: e.agent ?? e.data?.role,
                        content: e.data?.content ?? e.content,
                        iteration: e.iteration ?? e.data?.iteration,
                        smiles: e.data?.smiles ?? e.smiles,
                        composite: e.data?.composite ?? e.composite,
                      };
                      // Append directly to the events map (replay tab)
                      setChatEventsBySid((m) => {
                        const cur = m[newTabId] ?? [];
                        return { ...m, [newTabId]: [...cur, chatMsg] };
                      });
                      if (e.type === "session_complete" || e.type === "error") {
                        es.close();
                      }
                    } catch {/* ignore */}
                  };
                  types.forEach((t) => es.addEventListener(t, onMsg as EventListener));
                  es.onmessage = onMsg;
                }, 0);
              }}
              onArtifact={(p) => {
                // W4: streaming /explain markdown chunks replace the active
                // markdown_text block in artifactDoc, and we auto-switch the
                // right-pane tab to "Artifact" on the first chunk so the user
                // sees the brief filling in live.
                setArtifactDoc((doc) => ({
                  ...doc,
                  session_id: p.sessionId,
                  active_target: p.target,
                  blocks: [
                    {
                      kind: "markdown_text" as const,
                      text: p.markdown,
                      source: `explain · ${p.target}${
                        p.groundingCount ? ` · ${p.groundingCount} grounding entries` : ""
                      }${p.complete ? "" : " · streaming"}${p.error ? ` · error: ${p.error}` : ""}`,
                    },
                  ],
                }));
                if (p.chunks.length === 1 && !p.complete) {
                  setActiveTab("Artifact");
                }
              }}
              onReplyToAgent={async ({ text, targetAgent, parentMessageId, threadId }) => {
                // Echo the user's reply into the timeline (threaded)
                setEvents((p) => [...p, {
                  type: "agent_message",
                  ts: Date.now() / 1000,
                  agent: "user",
                  content: text,
                  thread_id: threadId,
                  parent_message_id: parentMessageId,
                  reply_agent: targetAgent,
                } as any]);
                setPendingChat(true);
                // Ship the last ~14 visible chat messages so the
                // per-agent reply path on the backend has the SAME
                // context the user sees on screen. Workflow narration
                // ("Generate hardening suggestions complete (20710ms)")
                // and result blobs are SSE-only — without this they're
                // invisible to the harness.
                const recentMessages = events
                  .filter((e: any) => e.type === "agent_message" && (e.content || "").length > 0)
                  .slice(-18)
                  .map((e: any) => ({
                    agent: e.agent || "system",
                    content: String(e.content || "").slice(0, 600),
                    ts: e.ts,
                  }));
                try {
                  const r = await fetch(`${apiBase}/api/chat`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      session_id: activeChatId,
                      text,
                      reply_to_agent: targetAgent,
                      parent_message_id: parentMessageId,
                      thread_id: threadId,
                      // Forward ambient context so the per-agent reply
                      // path in the harness has the live SMILES /
                      // pathogen / PDB to reference instead of "(none
                      // loaded)" and giving a generic deflection.
                      pathogen: selectedPathogen,
                      smiles: currentSmilesRef.current ?? null,
                      pdb_id: selectedPdbId ?? null,
                      recent_messages: recentMessages,
                    }),
                  });
                  const d = await r.json();
                  setEvents((p) => [...p, {
                    type: "agent_message",
                    ts: Date.now() / 1000,
                    agent: d.reply_agent ?? targetAgent,
                    content: d.text ?? d.error ?? "",
                    card_kind: d.card_kind ?? undefined,
                    data: d.data ?? undefined,
                    thread_id: threadId,
                    parent_message_id: parentMessageId,
                    reply_agent: targetAgent,
                  } as any]);
                } catch (exc: any) {
                  setEvents((p) => [...p, {
                    type: "agent_message",
                    ts: Date.now() / 1000,
                    agent: "orchestrator",
                    content: `Couldn't deliver your reply to ${targetAgent} — ${exc?.message ?? exc}. Want to try again?`,
                    thread_id: threadId,
                  } as any]);
                } finally {
                  setPendingChat(false);
                }
              }}
              composite={composite}
              currentIter={currentIter}
              totalIters={iters}
              replayBadge={replayEvents != null ? (
                <span style={{
                  marginLeft: 8,
                  padding: "2px 8px",
                  fontSize: 10,
                  background: "#ede9fe",
                  color: "#6d28d9",
                  border: "1px solid #c4b5fd",
                  borderRadius: 999,
                  fontFamily: "var(--lys-font-mono)",
                  letterSpacing: "0.05em",
                  textTransform: "uppercase",
                  fontWeight: 600,
                }}>
                  replay {replayIdx}/{replayEvents.length}
                </span>
              ) : null}
              onLoadSmiles={(smi) => {
                // The "Load in 3D" button on InlineSmilesCard fires this.
                // Two things must happen:
                //   1. Actually update the 2D + 3D canvas + auto-score
                //      (loadSmilesIntoCanvas does this end-to-end)
                //   2. Echo a chat row so the user sees the action
                loadSmilesIntoCanvas(smi, {
                  createdBy: "user",
                  parentId: null,
                  logLabel: "[chat · load-in-3D]",
                });
              }}
              subAgents={activeSubAgents}
              onToggleSubAgent={(id) =>
                setActiveSubAgents((cur) =>
                  cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]
                )
              }
              chatTabs={chatTabs.map((t) => ({
                id: t.id,
                title: t.title,
                msgCount: (chatEventsBySid[t.id] ?? []).length,
              }))}
              activeChatId={activeChatId}
              onSelectChat={(id) => setActiveChatId(id)}
              onCreateChat={() => {
                const id = `chat-${crypto.randomUUID().slice(0, 8)}`;
                setChatTabs((tabs) => [...tabs, { id, title: "New chat", userRenamed: false }]);
                setActiveChatId(id);
              }}
              onCloseChat={(id) => {
                setChatTabs((tabs) => {
                  if (tabs.length <= 1) return tabs; // never close the last
                  const idx = tabs.findIndex((t) => t.id === id);
                  const next = tabs.filter((t) => t.id !== id);
                  if (id === activeChatId) {
                    const fallback = next[Math.max(0, idx - 1)];
                    if (fallback) setActiveChatId(fallback.id);
                  }
                  return next;
                });
                setChatEventsBySid((m) => {
                  const { [id]: _drop, ...rest } = m;
                  void _drop;
                  return rest;
                });
              }}
              onRenameChat={(id, title) =>
                // Mark as user-renamed so useAutoTitle leaves it alone forever.
                setChatTabs((tabs) =>
                  tabs.map((t) => (t.id === id ? { ...t, title, userRenamed: true } : t))
                )
              }
            />
          </Allotment.Pane>

          {/* RIGHT — Playground area. Two view modes (toggleable):
              · "whiteboard"  — infinite zoomable canvas with floating cards
              · "tabs"        — Claude-style one-container-at-a-time tabs
              Same WindowGroup[] config feeds both modes. */}
          <Allotment.Pane minSize={360} preferredSize={760}>
            <div style={{ width: "100%", height: "100%", position: "relative" }}>
              {/* Tiny view-mode toggle — icon-only segmented control.
                  In tabs mode it lives INSIDE the TabbedView tab strip
                  (passed via the actions prop). In whiteboard mode it
                  floats top-left here. Defined inside the IIFE below. */}
            {(() => {
              const viewToggle = (
                <div style={{
                  display: "inline-flex",
                  background: "transparent",
                  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
                  borderRadius: 4,
                  height: 22,
                  overflow: "hidden",
                }}>
                  <button
                    type="button"
                    onClick={() => setViewMode("whiteboard")}
                    title="Whiteboard"
                    aria-label="Whiteboard mode"
                    style={{
                      width: 26, height: 22, padding: 0, border: 0, cursor: "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      background: viewMode === "whiteboard" ? "var(--lys-text, #0f172a)" : "transparent",
                      color: viewMode === "whiteboard" ? "white" : "var(--lys-text-faint, #94a3b8)",
                      transition: "background 120ms, color 120ms",
                    }}
                  >
                    <Maximize2 size={11} />
                  </button>
                  <button
                    type="button"
                    onClick={() => setViewMode("tabs")}
                    title="Tabs"
                    aria-label="Tabs mode"
                    style={{
                      width: 26, height: 22, padding: 0, border: 0, cursor: "pointer",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      background: viewMode === "tabs" ? "var(--lys-text, #0f172a)" : "transparent",
                      color: viewMode === "tabs" ? "white" : "var(--lys-text-faint, #94a3b8)",
                      transition: "background 120ms, color 120ms",
                    }}
                  >
                    <LayoutGrid size={11} />
                  </button>
                </div>
              );
              // Floating-toggle wrapper for whiteboard mode (tab mode hosts
              // it inside the strip, no floating needed).
              const floatingToggle = (
                <div style={{
                  position: "absolute", top: 8, left: 12, zIndex: 1100,
                  background: "rgba(255,255,255,0.92)",
                  backdropFilter: "blur(6px)",
                  borderRadius: 5,
                  boxShadow: "0 1px 4px rgba(15,23,42,0.06)",
                }}>
                  {viewToggle}
                </div>
              );

              // IIFE so we can declare playgroundGroups once and feed it
              // to either renderer. Cheap (re-evaluated each render), but
              // identical to the previous inline-array cost.
              const playgroundGroups: any[] = [
                {
                  id: "chem",
                  category: "Chemistry",
                  cards: [
                    // TOP NAV — compact horizontal toolbar with all launchers,
                    // quick scaffolds, clear, and the pathogen dropdown.
                    { id: "chem-topnav", title: "", slot: "topnav", body:
                      <ChemistryTopNav
                        apiBase={apiBase}
                        pathogen={selectedPathogen}
                        onPathogenChange={setSelectedPathogen}
                        onLoadSmiles={(smi, name) => {
                          loadSmilesIntoCanvas(smi, {
                            createdBy: "user",
                            parentId: null,
                            logLabel: `[topnav · ${name}]`,
                          });
                        }}
                      /> },
                    // Order = medchem workflow: build → dock → resist-test → compare.
                    // 1) 2D builder is the primary canvas: design / edit the
                    //    molecule, with atoms/bonds/library/SMARTS embedded.
                    { id: "2d", title: "2D molecule builder · atoms · bonds · properties", size: 2, expandedH: 540, body:
                      <Mol2DBuilderWindow
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        pathogen={selectedPathogen}
                        cursors={livePlayground.cursors}
                        highlightAtoms={smartsHighlight}
                        bindingAtoms={poseBindingAtoms}
                        clashingAtoms={poseClashingAtoms}
                        vulnerableAtoms={vulnerableAtoms}
                        focusedAtom={focusedAtomIdx}
                        onLoadFromLibrary={(smi, name) => {
                          loadSmilesIntoCanvas(smi, {
                            createdBy: "user",
                            parentId: null,
                            logLabel: `[library · ${name}]`,
                            quiet: true,  // tiny status pill, no candidate card
                          });
                        }}
                        onCursorHover={(atomIdx) => {
                          // Lift hovered atom up so AtomDetailCard can render its context
                          setHoveredAtom(atomIdx);
                          if (atomIdx != null) {
                            livePlayground.sendCursor({ actor: "user", atom_idx: atomIdx });
                            livePlayground.sendHover({
                              actor: "user", atom_idx: atomIdx,
                              smiles: currentSmiles ?? undefined,
                            });
                            // Fire predictive scoring → ghost polygon on radar
                            if (currentSmiles) fetchPrediction(currentSmiles, atomIdx);
                          } else {
                            clearPrediction();
                          }
                        }}
                        onMoleculeEdit={(newSmi, edit) => {
                          loadSmilesIntoCanvas(newSmi, {
                            createdBy: "user",
                            parentId: currentMoleculeId,
                            logLabel: `[2D edit ${edit.label} @${edit.atom_idx}]`,
                          });
                        }}
                        propertiesPanel={
                          <PropertiesCard apiBase={apiBase} smiles={currentSmiles} />
                        }
                      /> },
                    // 2) 3D theater: place the same molecule into the validated
                    //    target's active site, see binding/clashing contacts.
                    { id: "3d", title: "3D molecule theater · target picker · contacts", size: 2, expandedH: 520, body:
                      <Mol3DTheaterWindow
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        pathogen={selectedPathogen}
                        onMoleculeEdit={(newSmi, op) => {
                          const opLabel = op?.kind === "swap" ? `→${op.element}`
                            : op?.kind === "methyl" ? "+CH₃"
                            : op?.kind === "break" ? "✂ bond" : "edit";
                          loadSmilesIntoCanvas(newSmi, {
                            createdBy: "user",
                            parentId: currentMoleculeId,
                            logLabel: `[3D edit ${opLabel}]`,
                          });
                        }}
                        onPoseChange={(pose) => {
                          // Bridge pose → 2D builder halos. Same atom indices,
                          // both views: green=binding, red=clashing.
                          setPoseBindingAtoms(pose?.binding_atoms ?? []);
                          setPoseClashingAtoms(pose?.clashing_atoms ?? []);
                        }}
                        onTargetChange={(pdbId) => setSelectedPdbId(pdbId)}
                        externalFocusedResidue={focusedResidueId}
                      /> },
                    // 3) Resistance escape: check the same molecule against the
                    //    curated CARD subset of clinical mutations for this target.
                    { id: "resistance-escape", title: "Resistance escape · per-atom vulnerability map",
                      size: 2, expandedH: 540, body:
                      <ResistanceEscapeMapCard
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        pdbId={selectedPdbId}
                        sessionId={activeChatId}
                        onVulnerableChange={(atoms) => setVulnerableAtoms(atoms)}
                        onAtomFocus={(idx) => setFocusedAtomIdx(idx)}
                        onResidueFocus={(resid) => setFocusedResidueId(resid)}
                        onAgentMessage={(msg) => sendAgentMessage(msg)}
                        onLoadSmiles={(smi, label) => {
                          // Direct cross-link: harden Apply → 2D/3D + auto-score.
                          // The user's "harden actually changes the molecule"
                          // demand: we DON'T round-trip through the agent for
                          // this — we mutate the canvas state directly.
                          loadSmilesIntoCanvas(smi, {
                            createdBy: "harden",
                            parentId: currentMoleculeId,
                            logLabel: label ?? "[harden · apply]",
                          });
                        }}
                      /> },
                    // 4) Pareto lab: compare this candidate against the rest
                    //    of the session's frontier on the chosen objectives.
                    { id: "pareto-lab", title: "Pareto lab · multi-candidate frontier",
                      expandedH: 480, body:
                      <ParetoLabCard
                        apiBase={apiBase}
                        sessionId={activeChatId}
                        onLoad={(smi) => loadSmilesIntoCanvas(smi, {
                          createdBy: "user",
                          parentId: null,
                          logLabel: "[pareto · load]",
                        })}
                        onAgentMessage={(msg) => sendAgentMessage(msg)}
                      /> },
                    // (2D builder lives at top of this list — see above.)
                    // Atoms / Bonds / Build / Properties / Library / SMARTS
                    // are ALL embedded inside the 2D container.
                  ],
                },
                {
                  id: "scoring",
                  category: "Scoring",
                  cards: [
                    { id: "scoring-nav", title: "", slot: "nav", body:
                      <ScoringNavbar
                        preset={scoringPreset}
                        onPresetChange={setScoringPreset}
                        emphasis={scoringEmphasis}
                        onEmphasisChange={setScoringEmphasis}
                      /> },
                    { id: "radar", title: "Reward radar · live", size: 2, body:
                      <RewardRadarWindow
                        current={lastScores ?? {}}
                        best={bestScores ?? {}}
                        weights={REWARD_WEIGHTS}
                        composite={lastComposite ?? undefined}
                        predicted={predictedScores}
                        predictedLabel={predictedLabel}
                        history={(() => {
                          const h: Record<string, number[]> = {};
                          for (const e of events as any[]) {
                            if (e.type !== "candidate_added") continue;
                            const s = (e.scores ?? e.data?.scores) as Record<string, number> | undefined;
                            if (!s) continue;
                            for (const [k, v] of Object.entries(s)) {
                              if (typeof v !== "number") continue;
                              if (!h[k]) h[k] = [];
                              h[k].push(v);
                            }
                          }
                          return h;
                        })()}
                      /> },
                    { id: "breakdown", title: "Score breakdown · 12 axes", size: 2, body:
                      <ScoreBreakdownCard
                        scores={lastScores ?? {}}
                        weights={REWARD_WEIGHTS}
                        best={bestScores ?? {}}
                        composite={lastComposite ?? undefined}
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        pathogen={selectedPathogen}
                      /> },
                    { id: "toxicity", title: "Toxicity · ADME-Tox", body:
                      <ToxicityProfileCard apiBase={apiBase} smiles={currentSmiles} /> },
                    { id: "similarity", title: "Similarity · Tanimoto vs corpus", size: 2, body:
                      <SimilarityCard
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        pathogen={selectedPathogen}
                        onLoad={(smi, name) => {
                          loadSmilesIntoCanvas(smi, {
                            createdBy: "user",
                            parentId: null,
                            logLabel: `[similarity load · ${name}]`,
                          });
                        }}
                      /> },
                  ],
                },
                {
                  id: "agents",
                  category: "Agents",
                  cards: [
                    { id: "agents-nav", title: "", slot: "nav", body:
                      <AgentsNavbar
                        agentFilter={agentFilter}
                        onAgentChange={setAgentFilter}
                        actionFilter={actionFilter}
                        onActionChange={setActionFilter}
                      /> },
                    // Removed: medchem-protocol-tracker. The heuristic
                    // phase derivation (SCOPE → ANCHOR → DESIGN →
                    // VALIDATE → STRESS-TEST → REPORT) was confidently
                    // showing '1 evidence' on phases the user never
                    // intentionally entered — counts came from any
                    // loaded SMILES / score call, which the user
                    // correctly called out as faking. Real workflow
                    // progress now lives inside WorkflowCard per-step
                    // in the chat where it actually happened.
                    // The new AgentsHubCard subsumes Roster + Metrics +
                    // ActionLog into a single live, polling, integrated
                    // surface with flow graph + sparklines + inspector.
                    // The legacy three cards stay imported but unused —
                    // ready to bring back as standalone windows if needed.
                    { id: "agents-hub", title: "Multi-agent activity hub · live", size: 2, expandedH: 720, body:
                      <AgentsHubCard apiBase={apiBase} sessionId={activeChatId} /> },
                    { id: "trace", title: "Reasoning trace · 4 specialists", size: 2, body:
                      <AgentReasoningTraceWindow events={events as any[]} /> },
                    { id: "metrics", title: "Agent metrics · all-time activity", size: 2, body:
                      <AgentMetricsCard apiBase={apiBase} sessionId={activeChatId} /> },
                    { id: "actionlog", title: "Action log · DB-backed history (legacy)", size: 2, body:
                      <AgentActionLogCard apiBase={apiBase} sessionId={activeChatId} /> },
                  ],
                },
                {
                  id: "report",
                  category: "Report",
                  cards: [
                    { id: "report-nav", title: "", slot: "nav", body:
                      <LiveNavbar
                        eventKindFilter={eventKindFilter}
                        onEventKindChange={setEventKindFilter}
                      /> },
                    { id: "report-builder", title: "Deliverable · capture + preview + export",
                      size: 2, expandedH: 720, body:
                      <ReportBuilderCard apiBase={apiBase} sessionId={activeChatId} /> },
                    { id: "status", title: "System health · WS · DB · jobs", size: 2, body:
                      <ConnectionStatusCard
                        apiBase={apiBase}
                        sessionId={activeChatId}
                        connected={livePlayground.connected}
                        cursorCount={Object.keys(livePlayground.cursors).length}
                        recentEditCount={editLog.length}
                        lastEventTs={livePlayground.latest?.ts}
                      /> },
                    { id: "trace", title: "Session trace · unified timeline · audit", size: 2, body:
                      <SessionTraceCard apiBase={apiBase} sessionId={activeChatId} /> },
                    { id: "editlog", title: "Edit log · sqlite · live", size: 2, body:
                      <EditLogCard
                        edits={editLog}
                        onRefresh={refreshEditLog}
                        onLoadSmiles={(smi) => {
                          loadSmilesIntoCanvas(smi, {
                            createdBy: "user",
                            parentId: currentMoleculeId,
                            logLabel: "[edit-log replay]",
                          });
                        }}
                      /> },
                  ],
                },
                {
                  id: "knowledge",
                  category: "Knowledge",
                  cards: [
                    { id: "knowledge-nav", title: "", slot: "nav", body:
                      <KnowledgeNavbar
                        pathogen={selectedPathogen}
                        onPathogenChange={setSelectedPathogen}
                        drugClassFilter={drugClassFilter}
                        onDrugClassChange={setDrugClassFilter}
                      /> },
                    { id: "knowledge-hub", title: "", size: 2, body:
                      <KnowledgeHubCard
                        apiBase={apiBase}
                        pathogen={selectedPathogen}
                        onFireSlash={(slash) => {
                          // Use auto-slash so the composer pipeline
                          // catches it — that path runs slash detection,
                          // workflow regex, and Gemini fallback. Going
                          // direct to /api/chat would skip workflow
                          // routing for /wf <name> chips.
                          window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
                            detail: { text: slash },
                          }));
                        }}
                        onLoadPdb={(pdbId) => setSelectedPdbId(pdbId)}
                      /> },
                    // Pathogen × drug-class pressure heatmap — at-a-glance
                    // view of which classes are already broken everywhere.
                    { id: "pathogen-matrix", title: "Pathogen × drug-class pressure matrix", size: 2, body:
                      <PathogenMatrixCard
                        apiBase={apiBase}
                        activePathogen={selectedPathogen}
                        onPathogenChange={setSelectedPathogen}
                      /> },
                    // Resistance gene network — tier graph for the active
                    // pathogen showing pathogen → genes → classes → drugs.
                    { id: "resistance-network", title: "Resistance gene network · live graph", size: 2, body:
                      <ResistanceNetworkCard
                        apiBase={apiBase}
                        pathogen={selectedPathogen}
                        onFireSlash={(slash) => {
                          window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
                            detail: { text: slash },
                          }));
                        }}
                      /> },
                    // Mutation atlas — known clinical mutations on the
                    // currently-selected target PDB, color-coded by class.
                    { id: "mutation-atlas", title: `Mutation atlas · ${selectedPdbId ?? "(no target)"}`, size: 2, body:
                      <MutationAtlasCard
                        apiBase={apiBase}
                        pdbId={selectedPdbId}
                        onFireSlash={(slash) => {
                          window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
                            detail: { text: slash },
                          }));
                        }}
                      /> },
                    // Champion vault — all 8 reigning champions side-by-side.
                    { id: "champion-vault", title: "Champion vault · all pathogens", size: 2, body:
                      <ChampionVaultCard
                        apiBase={apiBase}
                        activePathogen={selectedPathogen}
                        onPathogenChange={setSelectedPathogen}
                        onLoadSmiles={(smi) => loadSmilesIntoCanvas(smi, {
                          createdBy: "user",
                          parentId: null,
                          logLabel: `[champion vault · load]`,
                        })}
                        onFireSlash={(slash) => {
                          window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
                            detail: { text: slash },
                          }));
                        }}
                      /> },
                    { id: "champion", title: `🏆 Active champion · ${selectedPathogen}`, body:
                      <KnowledgeChampionPane
                        apiBase={apiBase}
                        pathogen={selectedPathogen}
                        onLoadSmiles={(smi) => loadSmilesIntoCanvas(smi, {
                          createdBy: "user",
                          parentId: null,
                          logLabel: `[champion · ${selectedPathogen} load]`,
                        })}
                      /> },
                    { id: "pathogen-intel", title: "Pathogen intel · profile", body:
                      <PathogenIntelCard apiBase={apiBase} pathogen={selectedPathogen} /> },
                    { id: "validated-targets", title: "Validated targets · curated PDBs",
                      body:
                      <ValidatedTargetsCard apiBase={apiBase} pathogen={selectedPathogen} /> },
                    { id: "antibiotic-ref", title: "Antibiotic reference · canonical corpus", size: 2, body:
                      <AntibioticReferenceCard
                        apiBase={apiBase}
                        pathogen={selectedPathogen}
                        onLoad={(smi, name) => {
                          loadSmilesIntoCanvas(smi, {
                            createdBy: "user",
                            parentId: null,
                            logLabel: `[antibiotic-ref load · ${name}]`,
                          });
                        }}
                      /> },
                    { id: "atom-detail", title: "Atom inspector · live (hover in 2D)", body:
                      <AtomDetailCard
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        atomIdx={hoveredAtom}
                        pathogen={selectedPathogen}
                        onApplyEdit={async (op, params) => {
                          if (!currentSmiles || hoveredAtom == null) return;
                          try {
                            const body: any = { smiles: currentSmiles };
                            if (op === "swap_element") {
                              body.op = "swap_element";
                              body.atom_index = hoveredAtom;
                              body.new_element = params.new_element ?? "C";
                            } else if (op === "add_functional_group") {
                              body.op = "add_methyl_at";
                              body.atom_index = hoveredAtom;
                            } else { return; }
                            const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify(body),
                            });
                            if (!r.ok) return;
                            const d = await r.json();
                            if (d.smiles) {
                              await loadSmilesIntoCanvas(d.smiles, {
                                createdBy: "user",
                                parentId: currentMoleculeId,
                                logLabel: `[atom-inspect ${params.label} @${hoveredAtom}]`,
                              });
                            }
                          } catch {/* */}
                        }}
                      /> },
                    { id: "alerts", title: "Structural alerts · PAINS / toxicophores",  body:
                      <StructuralAlertsCard apiBase={apiBase} smiles={currentSmiles} /> },
                    { id: "resistance", title: `Resistance map · ${selectedPathogen}`, body:
                      <ResistanceMapCard apiBase={apiBase} pathogen={selectedPathogen} /> },
                    { id: "artifact", title: "Artifact · /explain output", size: 2, body:
                      <ArtifactPanel doc={artifactDoc} /> },
                  ],
                },
              ];
              return viewMode === "tabs" ? (
                <TabbedView
                  groups={playgroundGroups}
                  actions={viewToggle}
                  controlledActiveId={playgroundActiveTabId}
                />
              ) : (
                <>
                {floatingToggle}
                <PlaygroundCanvas
                  viewport={playViewport}
                  onViewportChange={setPlayViewport}
                  onFocus={(id) => {
                    const maxZ = Math.max(...Object.values(playGroupLayout).map((l) => l.z));
                    setPlayGroupLayoutItem(id, { ...playGroupLayout[id], z: maxZ + 1 });
                  }}
                  groupLayout={playGroupLayout}
                  onGroupLayoutChange={setPlayGroupLayoutItem}
                  groups={playgroundGroups}
                  windows={{
                "3d": {
                  title: "3D molecule theater",
                  category: "Chemistry",
                  body: <Mol3DTheaterWindow
                    apiBase={apiBase}
                    smiles={currentSmiles}
                    pathogen={selectedPathogen}
                    onMoleculeEdit={(newSmi, op) => {
                      // Same wiring as before — bubble the edit into the chat
                      // timeline so agents debate it.
                      const opLabel = op?.kind === "swap" ? `→${op.element}`
                        : op?.kind === "methyl" ? "+CH₃"
                        : op?.kind === "break" ? "✂ bond" : "edit";
                      setEvents((p) => [
                        ...p,
                        { type: "agent_message", ts: Date.now()/1000, agent: "user",
                          content: `[edit ${opLabel}] ${newSmi}` } as any,
                        { type: "candidate_added", ts: Date.now()/1000, smiles: newSmi,
                          composite: 0, agent: "user" } as any,
                      ]);
                    }}
                    onPoseChange={(pose) => {
                      setPoseBindingAtoms(pose?.binding_atoms ?? []);
                      setPoseClashingAtoms(pose?.clashing_atoms ?? []);
                    }}
                  />,
                },
                "2d": {
                  title: "2D atom builder · click any atom",
                  category: "Chemistry",
                  body: <Mol2DBuilderWindow
                    apiBase={apiBase}
                    smiles={currentSmiles}
                    pathogen={selectedPathogen}
                    bindingAtoms={poseBindingAtoms}
                    clashingAtoms={poseClashingAtoms}
                    onMoleculeEdit={(newSmi, edit) => {
                      setEvents((p) => [
                        ...p,
                        { type: "agent_message", ts: Date.now()/1000, agent: "user",
                          content: `[2D edit ${edit.label} @ atom ${edit.atom_idx}] ${newSmi}` } as any,
                        { type: "candidate_added", ts: Date.now()/1000, smiles: newSmi,
                          composite: 0, agent: "user" } as any,
                      ]);
                    }}
                  />,
                },
                "radar": {
                  title: "Reward radar · live",
                  category: "Scoring",
                  body: <RewardRadarWindow
                    current={lastScores ?? {}}
                    best={bestScores ?? {}}
                    weights={REWARD_WEIGHTS}
                    history={(() => {
                      // Build per-axis history from candidate events
                      const h: Record<string, number[]> = {};
                      for (const e of events as any[]) {
                        if (e.type !== "candidate_added") continue;
                        const s = (e.scores ?? e.data?.scores) as Record<string, number> | undefined;
                        if (!s) continue;
                        for (const [k, v] of Object.entries(s)) {
                          if (typeof v !== "number") continue;
                          if (!h[k]) h[k] = [];
                          h[k].push(v);
                        }
                      }
                      return h;
                    })()}
                  />,
                },
                "agents": {
                  title: "Agent reasoning trace",
                  category: "Agents",
                  body: <AgentReasoningTraceWindow events={events as any[]} />,
                },
                "artifact": {
                  title: "Artifact · /explain",
                  category: "Knowledge",
                  body: <ArtifactPanel doc={artifactDoc} />,
                },
              }}
            />
                </>
              );
            })()}
            </div>
          </Allotment.Pane>
        </Allotment>
      </div>
    </div>
  );
}

// --- Helper renderers (lightweight inlined panels) -------------------

function priorityFor(code: string): "critical" | "high" {
  return ["VRE", "NGono"].includes(code) ? "high" : "critical";
}


import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Allotment } from "allotment";
import "allotment/dist/style.css";

import { TopHeader } from "./components/TopHeader";
import { TightComposer } from "./components/chat/TightComposer";
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
import { TabbedView } from "./playground/TabbedView";
import { Mol3DTheaterWindow } from "./playground/Mol3DTheaterWindow";
import { ResistanceEscapeMapCard } from "./playground/ResistanceEscapeMapCard";
import { ParetoLabCard } from "./playground/ParetoLabCard";
import { WorkflowPhaseTracker } from "./playground/WorkflowPhaseTracker";
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
import { SessionTraceCard } from "./playground/SessionTraceCard";
import { AgentActionLogCard } from "./playground/AgentActionLogCard";
import { AgentMetricsCard } from "./playground/AgentMetricsCard";
import { ChemistryNavbar } from "./playground/ChemistryNavbar";
import { ChemistryTopNav } from "./playground/ChemistryTopNav";
void ChemistryNavbar;  // keeping import in case we want to switch back
import { KnowledgeNavbar } from "./playground/KnowledgeNavbar";
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
  // ---- Multi-chat tabs (Claude.ai-style) -------------------------------
  // Each tab is an independent chat: own events, own slash history.
  // We store events scoped by chat session id (Map preserves insertion order
  // for ordered tab list).
  type ChatTabMeta = { id: string; title: string; userRenamed?: boolean };
  const [chatTabs, setChatTabs] = useState<ChatTabMeta[]>(() => {
    const id = `chat-${crypto.randomUUID().slice(0, 8)}`;
    return [{ id, title: "New chat", userRenamed: false }];
  });
  const [activeChatId, setActiveChatId] = useState<string>(() => "");
  // Lazily seed activeChatId after the initial tab is set
  useEffect(() => {
    if (!activeChatId && chatTabs.length > 0) setActiveChatId(chatTabs[0].id);
  }, [activeChatId, chatTabs]);
  const [chatEventsBySid, setChatEventsBySid] = useState<Record<string, TraceEvent[]>>({});
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

  /** Load a SMILES into the playground store + canvas state. Used by
   *  scaffold picker, agent SMILES emissions, and post-edit refresh. */
  const loadSmilesIntoCanvas = useCallback(async (
    smi: string,
    opts: { createdBy?: string; parentId?: string | null; logLabel?: string } = {}
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
        // Echo into the chat events stream so the radar + agent trace + chat panel update
        const label = opts.logLabel ?? "[load]";
        setEvents((p) => [
          ...p,
          { type: "agent_message", ts: Date.now()/1000, agent: opts.createdBy ?? "user",
            content: `${label} ${smi}` } as any,
          { type: "candidate_added", ts: Date.now()/1000, smiles: smi,
            composite: 0, agent: opts.createdBy ?? "user" } as any,
        ]);
      }
      return d.molecule_id;
    } catch {
      return null;
    }
  }, [activeChatId, apiBase, currentMoleculeId]);

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
    return events.filter((e) =>
      ["agent_message", "tool_call_result", "tool_call_error", "candidate_added", "state_change",
        "intervention", "mol_edit"].includes(e.type)
    );
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
    for (let i = events.length - 1; i >= 0; i--) {
      if (events[i].type === "candidate_added" && events[i].smiles) {
        return events[i].smiles!;
      }
      if (events[i].type === "mol_edit" && events[i].candidate) {
        return events[i].candidate!;
      }
    }
    return null;
  }, [events]);

  const lastScores = useMemo<Record<string, number> | null>(() => {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
      if (e.type === "score" && e.scores) return e.scores;
      if (e.type === "candidate_added" && e.scores) return e.scores;
    }
    return null;
  }, [events]);

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
        const scores: Record<string, number> = {};
        if (d.components) {
          for (const [k, v] of Object.entries(d.components)) {
            // components is {axis: {value, weight, contribution}}
            const obj = v as any;
            scores[k] = typeof obj === "number" ? obj : (obj?.value ?? 0);
          }
        }
        const composite = typeof d.composite === "number" ? d.composite : 0;
        setEvents((prev) => [
          ...prev,
          { type: "score", ts: Date.now()/1000, smiles: currentSmiles, scores, composite } as any,
        ]);
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

  return (
    <div className="lys-shell">
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
      />

      {/* IterationStrip moved into a thin hairline below the body bar.
          Removed second-row chrome per redesign — keep only one navbar. */}

      <div className="lys-body">
        {/* Strict 2-pane layout: chat left (35%), playground right (65%).
            Middle pane (legacy 3D + 2D + drag-chips + mechanism) was
            collapsed into the playground as windows per user direction. */}
        <Allotment defaultSizes={[35, 65]}>
          {/* CHAT */}
          <Allotment.Pane minSize={340} preferredSize={480}>
            <ChatPanel
              events={events as any}
              isRunning={isRunning}
              totalMsgs={messages.length}
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
                  onSend={async (t: string) => {
                    // 1) Echo the user message into the timeline immediately
                    setEvents((p) => [...p, {
                      type: "agent_message",
                      ts: Date.now() / 1000,
                      agent: "user",
                      content: t,
                    } as any]);
                    // 2) Use the active chat tab's id as the harness session
                    //    id. Each tab is an independent chat session.
                    const chatSid = activeChatId;
                    // Title is set by useAutoTitle (LLM-summarized) after a
                    // few events. We keep "New chat" as the default until
                    // the first auto-summarization completes — no crude
                    // first-message-snippet hack here anymore.
                    // 3) POST through the harness — slash commands route to
                    //    the registry, free prompts route to the LLM.
                    try {
                      const r = await fetch(`${apiBase}/api/chat`, {
                        method: "POST",
                        headers: { "Content-Type": "application/json" },
                        body: JSON.stringify({ session_id: chatSid, text: t }),
                      });
                      if (!r.ok) {
                        const errTxt = await r.text();
                        setEvents((p) => [...p, {
                          type: "agent_message",
                          ts: Date.now() / 1000,
                          agent: "system",
                          content: `error ${r.status}: ${errTxt.slice(0, 200)}`,
                        } as any]);
                        return;
                      }
                      const d = await r.json();
                      // 4) Push the response — text + structured card payload.
                      setEvents((p) => [...p, {
                        type: "agent_message",
                        ts: Date.now() / 1000,
                        agent: "assistant",
                        content: d.text ?? d.error ?? "",
                        card_kind: d.card_kind ?? undefined,
                        data: d.data ?? undefined,
                      } as any]);
                    } catch (exc: any) {
                      setEvents((p) => [...p, {
                        type: "agent_message",
                        ts: Date.now() / 1000,
                        agent: "system",
                        content: `network error: ${exc?.message ?? exc}`,
                      } as any]);
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
                    agent: "system",
                    content: `reply network error: ${exc?.message ?? exc}`,
                    thread_id: threadId,
                  } as any]);
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
                // Inject as a candidate so the 3D + 2D viewers update.
                setEvents((p) => [
                  ...p,
                  {
                    type: "candidate_added",
                    ts: Date.now() / 1000,
                    smiles: smi,
                    composite: 0,
                    agent: "user",
                  } as any,
                ]);
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
              {/* Floating view-mode toggle (top-right, above content). */}
              <div style={{
                position: "absolute", top: 8, right: 12, zIndex: 200,
                display: "inline-flex",
                background: "var(--lys-bg-2, #ffffff)",
                border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
                borderRadius: 6,
                boxShadow: "0 2px 6px rgba(15,23,42,0.08)",
                fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
                overflow: "hidden",
              }}>
                <button
                  type="button"
                  onClick={() => setViewMode("whiteboard")}
                  title="Whiteboard mode — infinite canvas, drag/zoom, all containers visible"
                  style={{
                    padding: "5px 10px",
                    background: viewMode === "whiteboard" ? "#0891b2" : "transparent",
                    color: viewMode === "whiteboard" ? "white" : "var(--lys-text-faint)",
                    border: 0, cursor: "pointer", fontWeight: 700,
                    letterSpacing: "0.04em", textTransform: "uppercase",
                  }}>
                  whiteboard
                </button>
                <button
                  type="button"
                  onClick={() => setViewMode("tabs")}
                  title="Tabs mode — one container at a time, properly arranged grid"
                  style={{
                    padding: "5px 10px",
                    background: viewMode === "tabs" ? "#0891b2" : "transparent",
                    color: viewMode === "tabs" ? "white" : "var(--lys-text-faint)",
                    border: 0, cursor: "pointer", fontWeight: 700,
                    letterSpacing: "0.04em", textTransform: "uppercase",
                  }}>
                  tabs
                </button>
              </div>
            {(() => {
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
                    { id: "3d", title: "3D molecule theater · target picker · contacts", expandedH: 520, body:
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
                      /> },
                    { id: "resistance-escape", title: "Resistance escape · per-atom vulnerability map",
                      expandedH: 540, body:
                      <ResistanceEscapeMapCard
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        pdbId={selectedPdbId}
                        onVulnerableChange={(atoms) => setVulnerableAtoms(atoms)}
                      /> },
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
                      /> },
                    { id: "2d", title: "2D molecule builder · atoms · bonds · properties", expandedH: 860, body:
                      <Mol2DBuilderWindow
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        pathogen={selectedPathogen}
                        cursors={livePlayground.cursors}
                        highlightAtoms={smartsHighlight}
                        bindingAtoms={poseBindingAtoms}
                        clashingAtoms={poseClashingAtoms}
                        vulnerableAtoms={vulnerableAtoms}
                        onLoadFromLibrary={(smi, name) => {
                          loadSmilesIntoCanvas(smi, {
                            createdBy: "user",
                            parentId: null,
                            logLabel: `[library · ${name}]`,
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
                        // Properties panel is now MERGED INTO the 2D
                        // container as a bottom collapsible sub-section.
                        // No more separate sibling card — the chem
                        // container has one cohesive screen for atoms +
                        // bonds + build + props + status.
                        propertiesPanel={
                          <PropertiesCard apiBase={apiBase} smiles={currentSmiles} />
                        }
                      /> },
                    // Atoms / Bonds / Build / Properties / Library / SMARTS
                    // are ALL embedded inside the 2D container now. The
                    // chem container is a single screen, not a tile-grid.
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
                    { id: "workflow", title: "Workflow phase · medchem protocol tracker", size: 2, expandedH: 220, body:
                      <WorkflowPhaseTracker apiBase={apiBase} sessionId={activeChatId} /> },
                    { id: "trace", title: "Reasoning trace · 4 specialists", size: 2, body:
                      <AgentReasoningTraceWindow events={events as any[]} /> },
                    { id: "roster", title: "Agent roster · live state", size: 2, body:
                      <AgentRosterCard apiBase={apiBase} sessionId={activeChatId} /> },
                    { id: "metrics", title: "Agent metrics · KPIs per role", size: 2, body:
                      <AgentMetricsCard apiBase={apiBase} sessionId={activeChatId} /> },
                    { id: "actionlog", title: "Action log · DB-backed history", size: 2, body:
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
                <TabbedView groups={playgroundGroups} />
              ) : (
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


import { useEffect, useMemo, useRef, useState } from "react";
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
import { Mol3DTheaterWindow } from "./playground/Mol3DTheaterWindow";
import { RewardRadarWindow } from "./playground/RewardRadarWindow";
import { AgentReasoningTraceWindow } from "./playground/AgentReasoningTraceWindow";
import { Mol2DBuilderWindow } from "./playground/Mol2DBuilderWindow";
import { LiveAtomsCard } from "./playground/LiveAtomsCard";
import { ScaffoldPickerCard } from "./playground/ScaffoldPickerCard";
import type { GroupLayout } from "./playground/PlaygroundGroup";
import { useLivePlayground } from "./playground/useLivePlayground";
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
  const DEFAULT_GROUP_LAYOUT: Record<string, GroupLayout> = {
    "chem":      { x: 16,  y: 16,  w: 720, h: 760, z: 1 },
    "scoring":   { x: 752, y: 16,  w: 460, h: 380, z: 1 },
    "agents":    { x: 752, y: 412, w: 460, h: 360, z: 1 },
    "knowledge": { x: 16,  y: 792, w: 1196, h: 360, z: 1, collapsed: true },
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

  // Live playground WebSocket — one connection per active chat tab.
  // Other actors' cursors + applied edits stream through this and propagate
  // to all canvas windows. The connection is permanent for the tab; chat
  // tab switches re-key the hook (handled by activeChatId in the deps).
  const livePlayground = useLivePlayground(activeChatId, apiBase);

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
    return best?.scores ?? null;
  }, [events]);

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

          {/* RIGHT — Playground canvas (the only non-chat surface).
              Infinite zoomable whiteboard with floating, draggable, resizable
              windows. Default layout: 3D top-left, 2D bottom-left, Radar
              top-right, Agent trace bottom-right. Per-chat-tab layouts. */}
          <Allotment.Pane minSize={360} preferredSize={760}>
            <PlaygroundCanvas
              viewport={playViewport}
              onViewportChange={setPlayViewport}
              onFocus={(id) => {
                const maxZ = Math.max(...Object.values(playGroupLayout).map((l) => l.z));
                setPlayGroupLayoutItem(id, { ...playGroupLayout[id], z: maxZ + 1 });
              }}
              groupLayout={playGroupLayout}
              onGroupLayoutChange={setPlayGroupLayoutItem}
              groups={[
                {
                  id: "chem",
                  category: "Chemistry",
                  cards: [
                    { id: "scaffold", title: "Start from · 21 templates", size: 2, body:
                      <ScaffoldPickerCard
                        apiBase={apiBase}
                        onLoadSmiles={(smi, name) => {
                          setEvents((p) => [
                            ...p,
                            { type: "agent_message", ts: Date.now()/1000, agent: "user",
                              content: `[load template ${name ?? ""}] ${smi}` } as any,
                            { type: "candidate_added", ts: Date.now()/1000, smiles: smi,
                              composite: 0, agent: "user" } as any,
                          ]);
                        }}
                      /> },
                    { id: "3d", title: "3D molecule theater · drag-edit", size: 2, body:
                      <Mol3DTheaterWindow
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        pathogen={selectedPathogen}
                        onMoleculeEdit={(newSmi, op) => {
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
                      /> },
                    { id: "2d", title: "2D atom builder · click any atom", body:
                      <Mol2DBuilderWindow
                        apiBase={apiBase}
                        smiles={currentSmiles}
                        pathogen={selectedPathogen}
                        cursors={livePlayground.cursors}
                        onCursorHover={(atomIdx) => {
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
                          setEvents((p) => [
                            ...p,
                            { type: "agent_message", ts: Date.now()/1000, agent: "user",
                              content: `[2D edit ${edit.label} @ atom ${edit.atom_idx}] ${newSmi}` } as any,
                            { type: "candidate_added", ts: Date.now()/1000, smiles: newSmi,
                              composite: 0, agent: "user" } as any,
                          ]);
                        }}
                      /> },
                    { id: "atoms", title: "Live atoms · CRUD", body:
                      <LiveAtomsCard
                        apiBase={apiBase}
                        moleculeId={null}
                        smiles={currentSmiles}
                        onApplyEdit={async (edit) => {
                          if (!currentSmiles) return;
                          // Apply via the existing /molecule/edit endpoint, then
                          // bubble the new SMILES into the chat events stream.
                          try {
                            const body: any = { smiles: currentSmiles };
                            if (edit.kind === "swap_element") {
                              body.op = "swap_element";
                              body.atom_index = edit.atom_idx;
                              body.new_element = edit.new_element;
                            } else if (edit.kind === "add_methyl") {
                              body.op = "add_methyl_at";
                              body.atom_index = edit.atom_idx;
                            } else { return; }
                            const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                              method: "POST",
                              headers: { "Content-Type": "application/json" },
                              body: JSON.stringify(body),
                            });
                            if (!r.ok) return;
                            const d = await r.json();
                            if (d.smiles) {
                              const opLabel = edit.kind === "swap_element"
                                ? `→${edit.new_element}` : "+CH₃";
                              setEvents((p) => [
                                ...p,
                                { type: "agent_message", ts: Date.now()/1000, agent: "user",
                                  content: `[atom-list ${opLabel} @${edit.atom_idx}] ${d.smiles}` } as any,
                                { type: "candidate_added", ts: Date.now()/1000, smiles: d.smiles,
                                  composite: 0, agent: "user" } as any,
                              ]);
                            }
                          } catch {/* */}
                        }}
                      /> },
                  ],
                },
                {
                  id: "scoring",
                  category: "Scoring",
                  cards: [
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
                  ],
                },
                {
                  id: "agents",
                  category: "Agents",
                  cards: [
                    { id: "trace", title: "Reasoning trace · 4 specialists", size: 2, body:
                      <AgentReasoningTraceWindow events={events as any[]} /> },
                  ],
                },
                {
                  id: "knowledge",
                  category: "Knowledge",
                  cards: [
                    { id: "artifact", title: "Artifact · /explain output", size: 2, body:
                      <ArtifactPanel doc={artifactDoc} /> },
                  ],
                },
              ]}
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
                  />,
                },
                "2d": {
                  title: "2D atom builder · click any atom",
                  category: "Chemistry",
                  body: <Mol2DBuilderWindow
                    apiBase={apiBase}
                    smiles={currentSmiles}
                    pathogen={selectedPathogen}
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


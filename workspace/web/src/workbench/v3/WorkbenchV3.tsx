import { useEffect, useMemo, useRef, useState } from "react";
import { Allotment } from "allotment";
import "allotment/dist/style.css";

import { TopHeader } from "./components/TopHeader";
import { Composer } from "./components/Composer";
import { IterationStrip } from "./components/IterationStrip";
import { DragEditChips } from "./components/DragEditChips";
import { TabStrip } from "./components/TabStrip";
import { Mol2D } from "./components/Mol2D";
import { Mol3D } from "./components/Mol3D";
import { MechanismPanel } from "./components/MechanismPanel";
import { OnboardingHero } from "./components/OnboardingHero";
import { ChatPanel } from "./components/chat/ChatPanel";
import { RadarPanel } from "./panels/RadarPanel";
import { ParetoPanel } from "./panels/ParetoPanel";
import { SynthPanel } from "./panels/SynthPanel";
import { LineagePanel } from "./panels/LineagePanel";
import { GraphPanel } from "./panels/GraphPanel";
import { CandidateList } from "./components/CandidateList";
import type { Pathogen } from "./components/TopHeader";

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

const RIGHT_TABS = ["Radar", "Pareto", "Synth", "Graph", "Lineage"] as const;
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
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [constraints, setConstraints] = useState<Constraint[]>([]);
  const [chatMode, setChatMode] = useState<"Stream" | "Columns">("Stream");
  const [activeTab, setActiveTab] = useState<RightTab>("Radar");
  const [mechanismOpen, setMechanismOpen] = useState(false);
  const [activeSubAgents, setActiveSubAgents] = useState<string[]>([]);
  const [currentIter, setCurrentIter] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [speed, setSpeed] = useState<1 | 2 | 4>(1);
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
          mode: mode.toLowerCase(),
          autonomy: autonomy.toLowerCase().replace("-", "_"),
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

  const iterCompositeMap = useMemo(() => {
    const m: Record<number, number> = {};
    for (const e of events) {
      if (e.type === "iteration_end" && typeof e.iteration === "number" && typeof e.composite === "number") {
        m[e.iteration] = e.composite;
      }
    }
    return m;
  }, [events]);

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

      <IterationStrip
        totalIters={iters}
        currentIter={currentIter}
        iterCompositeMap={iterCompositeMap}
        isPlaying={isPlaying}
        onPlayPause={() => {
          if (!isPlaying && !replayEvents && !isRunning && sessionId) {
            // No live run, no replay loaded yet — kick off replay from disk
            loadReplay();
          } else {
            setIsPlaying((p) => !p);
          }
        }}
        onPrev={() => setCurrentIter((n) => Math.max(1, n - 1))}
        onNext={() => setCurrentIter((n) => Math.min(iters, n + 1))}
        onSeek={(n) => setCurrentIter(n)}
        speed={speed}
        onSpeedChange={setSpeed}
      />

      <div className="lys-body">
        <Allotment defaultSizes={[38, 38, 24]}>
          {/* CHAT */}
          <Allotment.Pane minSize={340} preferredSize={480}>
            <ChatPanel
              events={events as any}
              isRunning={isRunning}
              totalMsgs={messages.length}
              showOnboarding={
                <OnboardingHero
                  apiBase={apiBase}
                  onPickPathogen={(code) => setSelectedPathogen(code)}
                />
              }
              modeToggle={
                <div className="lys-chat__mode-toggle">
                  <button
                    className={chatMode === "Stream" ? "active" : ""}
                    onClick={() => setChatMode("Stream")}
                  >
                    Stream
                  </button>
                  <button
                    className={chatMode === "Columns" ? "active" : ""}
                    onClick={() => setChatMode("Columns")}
                  >
                    Columns
                  </button>
                </div>
              }
              composer={
                <Composer
                  isRunning={isRunning}
                  onSend={(t) => {
                    setEvents((p) => [...p, { type: "agent_message", ts: Date.now() / 1000, agent: "user", content: t }]);
                    if (!isRunning) startSession();
                  }}
                  onIntervene={intervene}
                  constraints={constraints}
                  onRemoveConstraint={(id) => setConstraints((cs) => cs.filter((c) => c.id !== id))}
                />
              }
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
            />
          </Allotment.Pane>

          {/* 3D + 2D */}
          <Allotment.Pane minSize={320} preferredSize={460}>
            <Allotment vertical defaultSizes={[60, 40]}>
              <Allotment.Pane minSize={180}>
                <Mol3D
                  apiBase={apiBase}
                  smiles={currentSmiles}
                  pathogen={selectedPathogen}
                />
              </Allotment.Pane>
              <Allotment.Pane minSize={260} preferredSize={300}>
                <div style={{
                  height: "100%",
                  display: "flex",
                  flexDirection: "column",
                  background: "var(--lys-bg)",
                  position: "relative",
                  overflow: "hidden",
                }}>
                  <div style={{
                    padding: "8px 12px",
                    fontSize: 11,
                    color: "var(--lys-text-faint)",
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    borderBottom: "1px solid var(--lys-border)",
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}>
                    <span>2D structure · drag chips onto atoms</span>
                    <button
                      onClick={() => setMechanismOpen(true)}
                      disabled={!currentSmiles}
                      style={{
                        background: currentSmiles ? "var(--lys-accent-soft)" : "transparent",
                        border: "1px solid rgba(16, 185, 129, 0.45)",
                        color: "#047857",
                        padding: "3px 10px",
                        borderRadius: 999,
                        fontSize: 11,
                        cursor: currentSmiles ? "pointer" : "not-allowed",
                        opacity: currentSmiles ? 1 : 0.4,
                        fontFamily: "inherit",
                        fontWeight: 500,
                      }}
                    >
                      🧠 Mechanism
                    </button>
                  </div>
                  <Mol2D apiBase={apiBase} smiles={currentSmiles} />
                  <MechanismPanel
                    apiBase={apiBase}
                    smiles={currentSmiles}
                    target={selectedPathogen}
                    open={mechanismOpen}
                    onClose={() => setMechanismOpen(false)}
                  />
                  <DragEditChips
                    apiBase={apiBase}
                    currentSmiles={currentSmiles}
                    pathogen={selectedPathogen}
                    onTransformResult={(payload) => {
                      if (payload?.ok) {
                        const ts = Date.now() / 1000;
                        // Emit both the mol_edit event (for the lineage
                        // tree) and a score event (so the radar updates).
                        setEvents((p) => [
                          ...p,
                          {
                            type: "mol_edit",
                            ts,
                            parent: payload.parent,
                            candidate: payload.candidate,
                            delta: payload.delta,
                            agent: "editor",
                          },
                          ...(payload.candidate_scores
                            ? [{
                                type: "score" as const,
                                ts,
                                smiles: payload.candidate,
                                scores: payload.candidate_scores,
                                composite: Object.entries(payload.candidate_scores).reduce(
                                  (sum, [k, v]: [string, any]) =>
                                    sum + (REWARD_WEIGHTS[k] ?? 0) * v,
                                  0
                                ),
                              }]
                            : []),
                          ...(payload.candidate_scores
                            ? [{
                                type: "candidate_added" as const,
                                ts,
                                smiles: payload.candidate,
                                scores: payload.candidate_scores,
                                composite: Object.entries(payload.candidate_scores).reduce(
                                  (sum, [k, v]: [string, any]) =>
                                    sum + (REWARD_WEIGHTS[k] ?? 0) * v,
                                  0
                                ),
                              }]
                            : []),
                        ]);
                      }
                    }}
                  />
                </div>
              </Allotment.Pane>
            </Allotment>
          </Allotment.Pane>

          {/* RIGHT — analytics tabs */}
          <Allotment.Pane minSize={240} preferredSize={300}>
            <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--lys-bg-2)" }}>
              <TabStrip tabs={RIGHT_TABS} active={activeTab} onChange={setActiveTab} />
              <div style={{ flex: 1, overflow: "auto", padding: 12, color: "var(--lys-text-dim)" }}>
                <div style={{ fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--lys-text-faint)", marginBottom: 8 }}>
                  {activeTab}
                </div>
                <div style={{ fontSize: 13, lineHeight: 1.5 }}>
                  {activeTab === "Radar" && (
                    <RadarPanel
                      current={lastScores}
                      best={bestScores}
                      weights={REWARD_WEIGHTS}
                    />
                  )}
                  {activeTab === "Pareto" && <ParetoPanel candidates={paretoRows} />}
                  {activeTab === "Synth" && <SynthPanel apiBase={apiBase} smiles={currentSmiles} />}
                  {activeTab === "Graph" && <GraphPanel pathogen={selectedPathogen} apiBase={apiBase} />}
                  {activeTab === "Lineage" && (
                    <LineagePanel edits={molEdits} candidates={candEvents} />
                  )}
                </div>
              </div>
              <CandidateList items={paretoRows} />
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


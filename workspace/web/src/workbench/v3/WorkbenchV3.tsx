import { useEffect, useMemo, useRef, useState } from "react";
import { Allotment } from "allotment";
import "allotment/dist/style.css";

import { TopHeader } from "./components/TopHeader";
import { Composer } from "./components/Composer";
import { IterationStrip } from "./components/IterationStrip";
import { MessageBubble } from "./components/MessageBubble";
import { DragEditChips } from "./components/DragEditChips";
import { TabStrip } from "./components/TabStrip";
import type { Pathogen } from "./components/TopHeader";

import "./v3.css";

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

const AGENT_COLORS: Record<string, string> = {
  designer: "#34d399",
  critic: "#f87171",
  editor: "#60a5fa",
  strategist: "#a78bfa",
  user: "#fbbf24",
  system: "#8b949e",
};

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
  useEffect(() => () => sseRef.current?.close(), []);

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
    }
    return null;
  }, [events]);

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
        onPlayPause={() => setIsPlaying((p) => !p)}
        onPrev={() => setCurrentIter((n) => Math.max(1, n - 1))}
        onNext={() => setCurrentIter((n) => Math.min(iters, n + 1))}
        onSeek={(n) => setCurrentIter(n)}
        speed={speed}
        onSpeedChange={setSpeed}
      />

      <div className="lys-body">
        <Allotment defaultSizes={[38, 38, 24]}>
          {/* CHAT */}
          <Allotment.Pane minSize={320} preferredSize={460}>
            <div className="lys-chat">
              <div className="lys-chat__head">
                <span className="lys-chat__title">Conversation · {messages.length} msg</span>
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
              </div>

              <div className="lys-chat__agent-row">
                {Object.entries(AGENT_COLORS).map(([a, c]) => {
                  const count = messages.filter((m) => m.agent === a).length;
                  return (
                    <button
                      key={a}
                      className="lys-agent-chip"
                      style={{ borderColor: c, color: c }}
                      title={`${a} — ${count} messages`}
                    >
                      {a}
                      {count > 0 && <span className="lys-agent-chip__count">{count}</span>}
                    </button>
                  );
                })}
              </div>

              <div className="lys-chat__messages" ref={messagesRef}>
                {messages.length === 0 && (
                  <div style={{ color: "var(--lys-text-faint)", textAlign: "center", padding: 24 }}>
                    no messages yet — pick a pathogen and click Start
                  </div>
                )}
                {messages.map((m, i) => (
                  <MessageBubble
                    key={i}
                    agent={m.agent ?? m.type}
                    agentColor={AGENT_COLORS[(m.agent ?? "system").toLowerCase()] ?? "#888"}
                    ts={m.ts}
                    content={contentFor(m)}
                  />
                ))}
              </div>

              <div className="lys-chat__composer">
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
              </div>
            </div>
          </Allotment.Pane>

          {/* 3D + 2D */}
          <Allotment.Pane minSize={320} preferredSize={460}>
            <Allotment vertical defaultSizes={[60, 40]}>
              <Allotment.Pane minSize={180}>
                <div style={{
                  height: "100%",
                  display: "grid",
                  placeItems: "center",
                  background: "var(--lys-bg-2)",
                  color: "var(--lys-text-faint)",
                  position: "relative",
                  borderBottom: "1px solid var(--lys-border)",
                }}>
                  <div style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 11, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>3D · pocket view</div>
                    <div style={{ fontFamily: "var(--lys-font-mono)", fontSize: 13, color: "var(--lys-text)" }}>
                      {currentSmiles ?? "no candidate"}
                    </div>
                  </div>
                </div>
              </Allotment.Pane>
              <Allotment.Pane minSize={120}>
                <div style={{
                  height: "100%",
                  display: "flex",
                  flexDirection: "column",
                  background: "var(--lys-bg)",
                }}>
                  <div style={{
                    padding: "8px 12px",
                    fontSize: 11,
                    color: "var(--lys-text-faint)",
                    letterSpacing: "0.1em",
                    textTransform: "uppercase",
                    borderBottom: "1px solid var(--lys-border)",
                  }}>
                    2D structure · drag chips onto atoms
                  </div>
                  <div style={{
                    flex: 1,
                    display: "grid",
                    placeItems: "center",
                    color: "var(--lys-text-faint)",
                    fontSize: 13,
                  }}>
                    {currentSmiles ?? "—"}
                  </div>
                  <DragEditChips
                    apiBase={apiBase}
                    currentSmiles={currentSmiles}
                    pathogen={selectedPathogen}
                    onTransformResult={(payload) => {
                      if (payload?.ok) {
                        setEvents((p) => [...p, {
                          type: "mol_edit",
                          ts: Date.now() / 1000,
                          parent: payload.parent,
                          candidate: payload.candidate,
                          delta: payload.delta,
                          agent: "editor",
                        }]);
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
                  {activeTab === "Radar" && <RadarPanel events={events} />}
                  {activeTab === "Pareto" && <ParetoPanel events={events} />}
                  {activeTab === "Synth" && <SynthPanel currentSmiles={currentSmiles} apiBase={apiBase} />}
                  {activeTab === "Graph" && <GraphPanel />}
                  {activeTab === "Lineage" && <LineagePanel events={events} />}
                </div>
              </div>
            </div>
          </Allotment.Pane>
        </Allotment>
      </div>
    </div>
  );
}

// --- Helper renderers (lightweight inlined panels) -------------------

function contentFor(m: TraceEvent): string {
  if (m.content) return m.content;
  if (m.type === "tool_call_result") return `→ ${m.tool ?? "tool"}`;
  if (m.type === "tool_call_error") return `✗ ${m.tool ?? "tool"} (error)`;
  if (m.type === "candidate_added") return `★ added candidate ${m.smiles ?? ""}`;
  if (m.type === "state_change") return `${m.decision} — ${m.reason ?? ""}`;
  if (m.type === "intervention") return `(intervene)`;
  if (m.type === "mol_edit") return `${m.parent} → ${m.candidate}`;
  return JSON.stringify(m);
}

function priorityFor(code: string): "critical" | "high" {
  return ["VRE", "NGono"].includes(code) ? "high" : "critical";
}

function RadarPanel({ events }: { events: TraceEvent[] }) {
  const last = [...events].reverse().find((e) => e.type === "score" && e.scores);
  if (!last?.scores) return <div>no candidate scored yet</div>;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      {Object.entries(last.scores).map(([k, v]) => (
        <div key={k} style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ width: 140, fontFamily: "var(--lys-font-mono)", fontSize: 11 }}>{k}</span>
          <div style={{ flex: 1, height: 6, background: "var(--lys-border)", borderRadius: 3 }}>
            <div style={{
              height: "100%",
              width: `${Math.max(0, Math.min(1, v as number)) * 100}%`,
              background: "var(--lys-accent)",
              borderRadius: 3,
            }} />
          </div>
          <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 11, width: 40 }}>{(v as number).toFixed(2)}</span>
        </div>
      ))}
    </div>
  );
}

function ParetoPanel({ events }: { events: TraceEvent[] }) {
  const cands = events.filter((e) => e.type === "candidate_added");
  return <div>{cands.length} candidates so far</div>;
}

function SynthPanel({ currentSmiles }: { currentSmiles: string | null; apiBase: string }) {
  return (
    <div>
      <div>SMILES: {currentSmiles ?? "—"}</div>
      <div style={{ marginTop: 6, color: "var(--lys-text-faint)" }}>
        synth route loads from /workbench/molecule/synth on candidate change
      </div>
    </div>
  );
}

function GraphPanel() {
  return <div>resistance graph — wired to /workbench/pathogen/&lt;code&gt;/graph</div>;
}

function LineagePanel({ events }: { events: TraceEvent[] }) {
  const edits = events.filter((e) => e.type === "mol_edit");
  return (
    <div>
      <div>{edits.length} edits</div>
      <div style={{ marginTop: 6, fontFamily: "var(--lys-font-mono)", fontSize: 11 }}>
        {edits.slice(-5).map((e, i) => (
          <div key={i} style={{ marginBottom: 4 }}>
            {(e.parent || "?").slice(0, 24)} → {(e.candidate || "?").slice(0, 24)}
          </div>
        ))}
      </div>
    </div>
  );
}

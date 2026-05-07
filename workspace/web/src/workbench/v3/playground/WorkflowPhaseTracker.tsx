/**
 * WorkflowPhaseTracker — top of the Agents container.
 *
 * Visualizes the medchem workflow as a 6-phase strip:
 *   SCOPE → ANCHOR → DESIGN → VALIDATE → STRESS-TEST → REPORT
 *
 * Per-phase status (✓ done, ⏳ active, ○ pending), tool-call counts,
 * evidence counts. Click a phase → drill into what happened in that phase.
 *
 * The point: the user (and the judges) can see at a glance what the agentic
 * system is doing right now — not just "agents are talking", but "agents
 * are in VALIDATE phase, ran 3 pose computations + 2 resistance checks".
 *
 * This is the difference between a chatbot and an autonomous medchem assistant.
 */
import { useEffect, useState } from "react";
import { CheckCircle2, Circle, Loader2, ChevronRight } from "lucide-react";

interface PhaseInfo {
  id: string;
  label: string;
  status: "completed" | "active" | "pending";
  tools_called: number;
  evidence_count: number;
}

interface WorkflowState {
  session_id: string;
  current_phase: string;
  phases: PhaseInfo[];
  counts: Record<string, number>;
  transitions: { ts: number; from_phase: string; to_phase: string; agent: string }[];
}

interface Props {
  apiBase: string;
  sessionId: string | null;
}

const PHASE_COLOR: Record<string, string> = {
  scope:       "#6b7280",
  anchor:      "#0891b2",
  design:      "#10b981",
  validate:    "#8b5cf6",
  stress_test: "#dc2626",
  report:      "#f59e0b",
};

const PHASE_DESCRIPTIONS: Record<string, string> = {
  scope: "User defines pathogen + design constraints + success criteria",
  anchor: "Designer queries resistome, picks scaffold class to anchor on",
  design: "Designer/Critic/Editor loop with reward-guided selection",
  validate: "Top candidates run through 3D pose + resistance map + scoring",
  stress_test: "Adversarial Critic + red-team escape mutation analysis",
  report: "Snapshot every container + assemble medchem deliverable",
};

export function WorkflowPhaseTracker({ apiBase, sessionId }: Props) {
  const [data, setData] = useState<WorkflowState | null>(null);
  const [loading, setLoading] = useState(false);
  const [hoverPhase, setHoverPhase] = useState<string | null>(null);

  useEffect(() => {
    if (!sessionId) { setData(null); return; }
    let cancelled = false;
    const fetchOnce = async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/sessions/${encodeURIComponent(sessionId)}/workflow`);
        if (!r.ok) return;
        const d: WorkflowState = await r.json();
        if (!cancelled) setData(d);
      } catch {/*noop*/}
    };
    setLoading(true);
    fetchOnce().finally(() => { if (!cancelled) setLoading(false); });
    const t = setInterval(fetchOnce, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, [sessionId, apiBase]);

  if (!sessionId) {
    return (
      <div style={{
        padding: "16px 12px", fontSize: 10,
        color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)",
        textAlign: "center",
      }}>
        no active session — start /design to spawn a workflow
      </div>
    );
  }

  return (
    <div style={{
      padding: "8px 10px",
      display: "flex", flexDirection: "column", gap: 6,
      background: "var(--lys-bg, #fafafa)",
      borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
      fontFamily: "var(--lys-font-body)",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 9, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.06em",
        textTransform: "uppercase", fontWeight: 700,
      }}>
        <span>workflow</span>
        {loading && <Loader2 size={9} style={{ animation: "spin 1s linear infinite" }} />}
        {data && (
          <>
            <span>· current: <span style={{ color: PHASE_COLOR[data.current_phase] ?? "#6b7280" }}>
              {data.current_phase}</span>
            </span>
          </>
        )}
      </div>

      {/* Phase strip */}
      <div style={{
        display: "flex", alignItems: "stretch", gap: 0,
        background: "white", borderRadius: 6,
        border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
        overflow: "hidden",
      }}>
        {data?.phases.map((p, i) => {
          const c = PHASE_COLOR[p.id] ?? "#6b7280";
          const isActive = p.status === "active";
          const isDone = p.status === "completed";
          return (
            <div key={p.id}
              onMouseEnter={() => setHoverPhase(p.id)}
              onMouseLeave={() => setHoverPhase(null)}
              style={{
                flex: 1, minWidth: 0,
                padding: "6px 8px",
                position: "relative",
                borderRight: i < (data.phases.length - 1) ? "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))" : "none",
                background: isActive ? `${c}10` : isDone ? "rgba(16,185,129,0.04)" : "white",
                cursor: "pointer",
                display: "flex", flexDirection: "column", gap: 2,
              }}>
              <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                {isDone && <CheckCircle2 size={11} style={{ color: "#10b981", flexShrink: 0 }} />}
                {isActive && <Loader2 size={11} style={{ color: c, animation: "spin 1.5s linear infinite", flexShrink: 0 }} />}
                {!isDone && !isActive && <Circle size={11} style={{ color: "var(--lys-text-faint)", flexShrink: 0 }} />}
                <span style={{
                  fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
                  fontWeight: 700,
                  color: isActive ? c : isDone ? "#059669" : "var(--lys-text-dim)",
                  letterSpacing: "0.04em",
                  textTransform: "uppercase",
                }}>
                  {p.label}
                </span>
              </div>
              {(p.tools_called > 0 || p.evidence_count > 0) && (
                <div style={{
                  fontSize: 8.5, color: "var(--lys-text-faint)",
                  fontFamily: "var(--lys-font-mono)", paddingLeft: 15,
                }}>
                  {p.tools_called > 0 && <span>{p.tools_called} tools</span>}
                  {p.tools_called > 0 && p.evidence_count > 0 && <span> · </span>}
                  {p.evidence_count > 0 && <span>{p.evidence_count} evidence</span>}
                </div>
              )}
              {/* Active flag — pulsing dot */}
              {isActive && (
                <div style={{
                  position: "absolute", top: 4, right: 4,
                  width: 6, height: 6, borderRadius: 6,
                  background: c,
                  animation: "lys-pulse 1.4s infinite",
                }} />
              )}
            </div>
          );
        })}
      </div>

      {/* Hover detail */}
      {hoverPhase && (
        <div style={{
          padding: "5px 8px", borderRadius: 4,
          background: `${PHASE_COLOR[hoverPhase] ?? "#6b7280"}08`,
          borderLeft: `3px solid ${PHASE_COLOR[hoverPhase] ?? "#6b7280"}`,
          fontSize: 10, color: "var(--lys-text-dim)", lineHeight: 1.4,
        }}>
          <span style={{
            fontFamily: "var(--lys-font-mono)", fontWeight: 700,
            color: PHASE_COLOR[hoverPhase] ?? "#6b7280", marginRight: 6,
            textTransform: "uppercase", fontSize: 9,
          }}>
            {hoverPhase}
          </span>
          {PHASE_DESCRIPTIONS[hoverPhase]}
        </div>
      )}

      {/* Transition log (compact, last 3) */}
      {data && data.transitions.length > 0 && (
        <div style={{
          padding: "4px 6px", fontSize: 9,
          color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)",
          display: "flex", flexDirection: "column", gap: 1,
        }}>
          <div style={{ fontWeight: 700, opacity: 0.7, marginBottom: 2 }}>recent transitions</div>
          {data.transitions.slice(-3).reverse().map((t, i) => (
            <div key={i} style={{ display: "flex", alignItems: "center", gap: 3 }}>
              <span>{t.from_phase}</span>
              <ChevronRight size={9} />
              <span style={{ color: PHASE_COLOR[t.to_phase] ?? "#6b7280", fontWeight: 700 }}>
                {t.to_phase}
              </span>
              <span style={{ flex: 1 }} />
              <span style={{ opacity: 0.6 }}>{t.agent}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

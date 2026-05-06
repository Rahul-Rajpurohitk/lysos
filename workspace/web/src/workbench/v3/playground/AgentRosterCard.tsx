/**
 * AgentRosterCard — per-agent state dashboard.
 *
 * Reads /workbench/sessions/{sid}/agent-roster — returns each canonical
 * agent (Designer/Critic/Editor/Strategist/Orchestrator) with:
 *   - n_actions in this session
 *   - last_op (last action type)
 *   - last_summary (one-line description)
 *   - state (active vs idle)
 *
 * Each agent gets a colored avatar + activity tile + collapsible recent log.
 * Auto-polls every 4s while a session is running.
 */
import { useEffect, useState, useCallback } from "react";
import { Users, RefreshCw, Activity, Pause } from "lucide-react";

interface AgentInfo {
  actor: string;
  n_actions: number;
  last_ts: number | null;
  last_op: string;
  last_summary: string;
  state: string;
}

interface Roster {
  session: string;
  roster: AgentInfo[];
  total_actions: number;
}

interface Props {
  apiBase: string;
  sessionId: string | null;
}

const AGENT_META: Record<string, { color: string; role: string; emoji: string }> = {
  designer:     { color: "#10b981", role: "synthesizer of new candidates",      emoji: "✏️" },
  critic:       { color: "#ef4444", role: "adversarial weakness probe",         emoji: "🔍" },
  editor:       { color: "#3b82f6", role: "applies surgical SAR edits",         emoji: "✂️" },
  strategist:   { color: "#8b5cf6", role: "high-level direction setter",        emoji: "🎯" },
  orchestrator: { color: "#f59e0b", role: "meta-coordinator + arbiter",         emoji: "🧠" },
};

export function AgentRosterCard({ apiBase, sessionId }: Props) {
  const [data, setData] = useState<Roster | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!sessionId) { setData(null); return; }
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/sessions/${sessionId}/agent-roster`);
      if (!r.ok) return;
      setData(await r.json());
    } finally {
      setLoading(false);
    }
  }, [apiBase, sessionId]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 4000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      <div style={{
        padding: "5px 10px",
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.06em",
        textTransform: "uppercase",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <Users size={11} style={{ color: "#8b5cf6" }} />
        <span>agents · {data ? `${data.total_actions} actions` : "roster"}</span>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={refresh} disabled={loading}
          style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 6, display: "flex",
        flexDirection: "column", gap: 4 }}>
        {!sessionId && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            no session · start a /design or /score to spawn agents
          </div>
        )}
        {sessionId && data && data.roster.map((a) => {
          const meta = AGENT_META[a.actor.toLowerCase()] ?? { color: "#9ca3af", role: "", emoji: "🤖" };
          const isActive = a.state === "active";
          return (
            <div key={a.actor}
              style={{
                padding: "6px 8px", borderRadius: 5,
                background: isActive ? `${meta.color}06` : "rgba(0,0,0,0.01)",
                border: `1px solid ${isActive ? meta.color : "var(--lys-border-faint, rgba(0,0,0,0.06))"}`,
                borderLeft: `3px solid ${meta.color}`,
                display: "flex", flexDirection: "column", gap: 3,
              }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{
                  width: 22, height: 22, borderRadius: "50%",
                  background: meta.color, color: "white",
                  display: "grid", placeItems: "center",
                  fontSize: 11, flexShrink: 0,
                }}>{meta.emoji}</div>
                <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 1 }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color: "var(--lys-text)",
                    fontFamily: "var(--lys-font-mono)", textTransform: "capitalize",
                    display: "flex", alignItems: "center", gap: 6 }}>
                    {a.actor}
                    {isActive ? (
                      <Activity size={9} style={{ color: meta.color }} />
                    ) : (
                      <Pause size={9} style={{ color: "var(--lys-text-faint)" }} />
                    )}
                    <span style={{ fontSize: 8.5, padding: "0 5px", borderRadius: 999,
                      background: isActive ? meta.color : "var(--lys-bg-3, rgba(0,0,0,0.04))",
                      color: isActive ? "white" : "var(--lys-text-faint)",
                      fontWeight: 600, letterSpacing: "0.04em",
                      textTransform: "uppercase" }}>
                      {a.state}
                    </span>
                  </div>
                  <div style={{ fontSize: 9, color: "var(--lys-text-dim)",
                    fontFamily: "var(--lys-font-mono)" }}>{meta.role}</div>
                </div>
                <div style={{ fontSize: 14, fontWeight: 700, color: meta.color,
                  fontFamily: "var(--lys-font-mono)" }}>{a.n_actions}</div>
              </div>
              {a.last_summary && (
                <div style={{
                  fontSize: 9.5, padding: "3px 6px", borderRadius: 3,
                  background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
                  color: "var(--lys-text-dim)",
                  fontFamily: "var(--lys-font-mono)",
                  borderLeft: `2px solid ${meta.color}40`,
                }}>
                  <span style={{ color: meta.color, fontWeight: 600 }}>
                    {a.last_op || "—"}
                  </span>
                  {" · "}
                  {a.last_summary.length > 80 ? a.last_summary.slice(0, 77) + "…" : a.last_summary}
                </div>
              )}
            </div>
          );
        })}

        {sessionId && (!data || data.roster.length === 0) && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            agents idle · run a slash command to wake them
          </div>
        )}
      </div>
    </div>
  );
}

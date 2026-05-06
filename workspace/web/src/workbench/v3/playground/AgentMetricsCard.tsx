/**
 * AgentMetricsCard — per-agent KPI dashboard.
 *
 * Reads /workbench/sessions/{sid}/agent-metrics. For each agent:
 *   - n_actions
 *   - actions_per_hour (over session span)
 *   - avg_confidence (color-coded)
 *   - n_distinct_molecules touched
 *   - action-type breakdown (mini-chart)
 *
 * Auto-polls every 6s.
 */
import { useEffect, useState, useCallback } from "react";
import { BarChart3, RefreshCw, Activity, Brain, Target } from "lucide-react";

interface AgentMetric {
  agent: string;
  n_actions: number;
  actions_per_hour: number;
  avg_confidence: number;
  last_ts: number | null;
  action_type_breakdown: Record<string, number>;
  n_distinct_molecules: number;
}

interface Resp {
  session: string;
  agents: AgentMetric[];
  total_actions: number;
  duration_h: number;
}

interface Props {
  apiBase: string;
  sessionId: string | null;
}

const AGENT_COLOR: Record<string, string> = {
  designer: "#10b981", critic: "#ef4444", editor: "#3b82f6",
  strategist: "#8b5cf6", orchestrator: "#f59e0b",
};

const AGENT_ICON: Record<string, string> = {
  designer: "✏️", critic: "🔍", editor: "✂️",
  strategist: "🎯", orchestrator: "🧠",
};

export function AgentMetricsCard({ apiBase, sessionId }: Props) {
  const [data, setData] = useState<Resp | null>(null);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!sessionId) { setData(null); return; }
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/sessions/${sessionId}/agent-metrics`);
      if (!r.ok) return;
      setData(await r.json());
    } finally {
      setLoading(false);
    }
  }, [apiBase, sessionId]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 6000);
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
        <BarChart3 size={11} style={{ color: "#7c3aed" }} />
        <span>metrics · {data ? `${data.total_actions} actions in ${data.duration_h.toFixed(1)}h` : "KPIs"}</span>
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
            fontFamily: "var(--lys-font-mono)" }}>no session</div>
        )}
        {sessionId && data?.agents.map((m) => {
          const c = AGENT_COLOR[m.agent] ?? "#9ca3af";
          const isActive = m.n_actions > 0;
          // For type breakdown we sort by count desc
          const breakdown = Object.entries(m.action_type_breakdown)
            .sort((a, b) => b[1] - a[1]);
          return (
            <div key={m.agent} style={{
              padding: "5px 8px", borderRadius: 5,
              background: isActive ? `${c}06` : "rgba(0,0,0,0.01)",
              border: `1px solid ${isActive ? c : "var(--lys-border-faint, rgba(0,0,0,0.06))"}`,
              borderLeft: `3px solid ${c}`,
              display: "flex", flexDirection: "column", gap: 4,
              opacity: isActive ? 1 : 0.6,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 14 }}>{AGENT_ICON[m.agent] ?? "🤖"}</span>
                <span style={{ fontSize: 11, fontWeight: 700, color: c,
                  fontFamily: "var(--lys-font-mono)", textTransform: "capitalize" }}>
                  {m.agent}
                </span>
                <span style={{ flex: 1 }} />
                <span style={{ fontSize: 16, fontWeight: 700, color: c,
                  fontFamily: "var(--lys-font-mono)" }}>{m.n_actions}</span>
              </div>

              {isActive && (
                <>
                  {/* KPI row */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 3 }}>
                    <Kpi icon={<Activity size={9} />} label="rate" value={m.actions_per_hour.toFixed(1)} unit="/h" />
                    <Kpi icon={<Brain size={9} />} label="conf" value={(m.avg_confidence*100).toFixed(0)} unit="%" color={confColor(m.avg_confidence)} />
                    <Kpi icon={<Target size={9} />} label="mols" value={String(m.n_distinct_molecules)} unit="" />
                  </div>

                  {/* Type breakdown bars */}
                  {breakdown.length > 0 && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                      {breakdown.slice(0, 4).map(([t, n]) => {
                        const pct = (n / m.n_actions) * 100;
                        return (
                          <div key={t} style={{ display: "flex", alignItems: "center", gap: 4,
                            fontSize: 9, fontFamily: "var(--lys-font-mono)" }}>
                            <span style={{ minWidth: 60, color: "var(--lys-text-dim)" }}>{t}</span>
                            <div style={{ flex: 1, height: 4, borderRadius: 2,
                              background: "var(--lys-border-faint, rgba(0,0,0,0.04))",
                              overflow: "hidden" }}>
                              <div style={{ height: "100%", width: `${pct}%`,
                                background: c, transition: "width 200ms ease" }} />
                            </div>
                            <span style={{ minWidth: 24, textAlign: "right",
                              color: "var(--lys-text-faint)", fontWeight: 600 }}>{n}</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Kpi({ icon, label, value, unit, color }: {
  icon: React.ReactNode; label: string; value: string; unit: string; color?: string;
}) {
  return (
    <div style={{
      padding: "3px 5px", borderRadius: 3,
      background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
      display: "flex", flexDirection: "column", gap: 0,
      fontFamily: "var(--lys-font-mono)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 3,
        fontSize: 8, color: "var(--lys-text-faint)",
        letterSpacing: "0.04em", textTransform: "uppercase" }}>
        {icon}{label}
      </div>
      <div style={{ fontSize: 12, fontWeight: 700,
        color: color ?? "var(--lys-text)" }}>
        {value}<span style={{ fontSize: 8, fontWeight: 500,
          color: "var(--lys-text-faint)", marginLeft: 1 }}>{unit}</span>
      </div>
    </div>
  );
}

function confColor(c: number): string {
  if (c >= 0.75) return "#10b981";
  if (c >= 0.5) return "#d97706";
  return "#dc2626";
}

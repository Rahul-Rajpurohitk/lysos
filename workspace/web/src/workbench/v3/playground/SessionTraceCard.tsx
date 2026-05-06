/**
 * SessionTraceCard — unified session timeline.
 *
 * Reads /workbench/sessions/{sid}/timeline — merges molecule edits +
 * score snapshots + agent actions in chronological order.
 *
 * Filters: kind chips (edit / score / agent / all)
 * Each row: timestamp, actor avatar, kind icon, summary, expand → raw JSON
 * Auto-polls every 5s.
 */
import { useEffect, useState, useCallback } from "react";
import { Activity, RefreshCw, Edit3, Target, Bot } from "lucide-react";

interface Event {
  ts: number;
  kind: string;        // "edit" | "score" | "agent"
  actor: string;
  summary: string;
  result_smiles?: string;
  raw?: any;
}

interface Resp {
  session: string;
  n_events: number;
  timeline: Event[];
}

interface Props {
  apiBase: string;
  sessionId: string | null;
}

const KIND_META: Record<string, { color: string; icon: React.ReactNode }> = {
  edit:  { color: "#f59e0b", icon: <Edit3 size={10} /> },
  score: { color: "#0891b2", icon: <Target size={10} /> },
  agent: { color: "#8b5cf6", icon: <Bot size={10} /> },
};

const ACTOR_COLOR: Record<string, string> = {
  designer: "#10b981", critic: "#ef4444", editor: "#3b82f6",
  strategist: "#8b5cf6", orchestrator: "#f59e0b",
  user: "#f59e0b", scorer: "#0891b2",
};

function fmtTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function SessionTraceCard({ apiBase, sessionId }: Props) {
  const [data, setData] = useState<Resp | null>(null);
  const [filter, setFilter] = useState<string>("all");
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) { setData(null); return; }
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/sessions/${sessionId}/timeline?limit=200`);
      if (!r.ok) return;
      setData(await r.json());
    } finally {
      setLoading(false);
    }
  }, [apiBase, sessionId]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
    return () => clearInterval(t);
  }, [refresh]);

  const visible = data?.timeline.filter((e) => filter === "all" || e.kind === filter) ?? [];

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
        <Activity size={11} style={{ color: "#0891b2" }} />
        <span>trace · {data ? `${visible.length}/${data.n_events} events` : "session timeline"}</span>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={refresh} disabled={loading}
          style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Kind filters */}
      <div style={{ padding: "4px 8px", display: "flex", gap: 3,
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))" }}>
        {(["all", "edit", "score", "agent"] as const).map((k) => {
          const active = filter === k;
          const count = k === "all"
            ? data?.timeline.length
            : data?.timeline.filter((e) => e.kind === k).length;
          const c = k === "all" ? "#0891b2" : KIND_META[k]?.color ?? "#0891b2";
          return (
            <button key={k} type="button" onClick={() => setFilter(k)}
              style={{
                padding: "1px 8px", borderRadius: 999, fontSize: 9,
                fontFamily: "var(--lys-font-mono)",
                border: `1px solid ${active ? c : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
                background: active ? `${c}15` : "var(--lys-bg-3, rgba(0,0,0,0.02))",
                color: active ? c : "var(--lys-text-dim)",
                cursor: "pointer", fontWeight: active ? 700 : 400,
              }}>
              {k} · {count ?? 0}
            </button>
          );
        })}
      </div>

      <div style={{ flex: 1, overflow: "auto" }}>
        {!sessionId && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            no session yet
          </div>
        )}
        {sessionId && visible.length === 0 && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            no events yet · run /design /score /sar to populate
          </div>
        )}
        {visible.map((e, i) => {
          const meta = KIND_META[e.kind] ?? { color: "#9ca3af", icon: null };
          const ac = ACTOR_COLOR[e.actor.toLowerCase()] ?? "#9ca3af";
          const isExpanded = expanded === i;
          return (
            <div key={i} style={{
              padding: "4px 8px",
              borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
              borderLeft: `3px solid ${meta.color}`,
              display: "flex", flexDirection: "column", gap: 2,
              cursor: "pointer",
            }}
              onClick={() => setExpanded(isExpanded ? null : i)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ color: meta.color, display: "flex" }}>{meta.icon}</span>
                <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)" }}>
                  {e.ts ? fmtTs(e.ts) : "—"}
                </span>
                <span style={{
                  fontSize: 8.5, padding: "0 5px", borderRadius: 999,
                  background: `${ac}15`, color: ac,
                  fontFamily: "var(--lys-font-mono)", fontWeight: 600,
                  letterSpacing: "0.04em",
                }}>{e.actor || "system"}</span>
                <span style={{ flex: 1, fontSize: 10.5, color: "var(--lys-text)",
                  fontFamily: "var(--lys-font-mono)",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{e.summary}</span>
              </div>
              {isExpanded && e.raw && (
                <pre style={{
                  margin: 0, padding: 6, borderRadius: 4,
                  background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
                  fontSize: 9, color: "var(--lys-text-dim)",
                  fontFamily: "var(--lys-font-mono)",
                  whiteSpace: "pre-wrap", wordBreak: "break-all",
                  maxHeight: 160, overflow: "auto",
                }}>{JSON.stringify(e.raw, null, 2)}</pre>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

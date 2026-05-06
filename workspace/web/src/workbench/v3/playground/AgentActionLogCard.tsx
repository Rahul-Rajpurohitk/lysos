/**
 * AgentActionLogCard — DB-backed full agent action log.
 *
 * Reads /workbench/sessions/{sid}/agent-actions with filters:
 *   - per-agent chip filter (auto-populated from distinct values)
 *   - per-action-type chip filter
 *   - free-text search across message_text
 *
 * Each row: agent pill · action_type · timestamp · message preview ·
 *           confidence bar · expand → references + full message JSON.
 *
 * Auto-polls every 5s while session is active.
 */
import { useEffect, useState, useCallback } from "react";
import { Bot, RefreshCw, Search, Filter, ChevronDown, ChevronRight } from "lucide-react";

interface Action {
  id: string;
  ts: number;
  agent_name: string;
  action_type: string;
  target_molecule_id: string | null;
  target_atom_idx: number | null;
  message_text: string;
  confidence: number;
  references: Record<string, any>;
}

interface Resp {
  session: string;
  n: number;
  actions: Action[];
  distinct_agents: string[];
  distinct_action_types: string[];
}

interface Props {
  apiBase: string;
  sessionId: string | null;
}

const AGENT_COLOR: Record<string, string> = {
  designer: "#10b981", critic: "#ef4444", editor: "#3b82f6",
  strategist: "#8b5cf6", orchestrator: "#f59e0b",
};

const ACTION_COLOR: Record<string, string> = {
  propose: "#10b981", critique: "#ef4444", edit: "#3b82f6",
  decide: "#f59e0b", explain: "#0891b2", score: "#7c3aed",
};

function fmtTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}

export function AgentActionLogCard({ apiBase, sessionId }: Props) {
  const [data, setData] = useState<Resp | null>(null);
  const [agent, setAgent] = useState<string>("");
  const [actionType, setActionType] = useState<string>("");
  const [query, setQuery] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!sessionId) { setData(null); return; }
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (agent) params.set("agent", agent);
      if (actionType) params.set("action_type", actionType);
      if (query) params.set("q", query);
      params.set("limit", "100");
      const r = await fetch(`${apiBase}/workbench/sessions/${sessionId}/agent-actions?${params.toString()}`);
      if (!r.ok) return;
      setData(await r.json());
    } finally {
      setLoading(false);
    }
  }, [apiBase, sessionId, agent, actionType, query]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 5000);
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
        <Bot size={11} style={{ color: "#8b5cf6" }} />
        <span>action log · {data ? `${data.n} action${data.n!==1?"s":""}` : "history"}</span>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={refresh} disabled={loading}
          style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Search + filters */}
      <div style={{
        padding: "5px 8px", display: "flex", flexDirection: "column", gap: 3,
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Search size={10} style={{ color: "var(--lys-text-faint)" }} />
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="search messages…"
            style={inputStyle} />
        </div>
        {data && (data.distinct_agents.length > 0 || data.distinct_action_types.length > 0) && (
          <>
            {data.distinct_agents.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 3, alignItems: "center" }}>
                <Filter size={9} style={{ color: "var(--lys-text-faint)" }} />
                <button type="button" onClick={() => setAgent("")}
                  style={chipStyle(!agent, "#8b5cf6")}>all</button>
                {data.distinct_agents.map((a) => (
                  <button key={a} type="button" onClick={() => setAgent(a === agent ? "" : a)}
                    style={chipStyle(a === agent, AGENT_COLOR[a] ?? "#8b5cf6")}>{a}</button>
                ))}
              </div>
            )}
            {data.distinct_action_types.length > 0 && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                <button type="button" onClick={() => setActionType("")}
                  style={chipStyle(!actionType, "#0891b2")}>all-types</button>
                {data.distinct_action_types.map((t) => (
                  <button key={t} type="button" onClick={() => setActionType(t === actionType ? "" : t)}
                    style={chipStyle(t === actionType, ACTION_COLOR[t] ?? "#0891b2")}>{t}</button>
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <div style={{ flex: 1, overflow: "auto" }}>
        {!sessionId && (
          <Empty msg="no session yet" />
        )}
        {sessionId && data && data.n === 0 && (
          <Empty msg={query || agent || actionType ? "no matches" : "no agent activity yet · run /design /sar /score"} />
        )}
        {data?.actions.map((a) => {
          const ac = AGENT_COLOR[a.agent_name.toLowerCase()] ?? "#9ca3af";
          const tc = ACTION_COLOR[a.action_type.toLowerCase()] ?? "#9ca3af";
          const isExpanded = expanded === a.id;
          const hasRefs = Object.keys(a.references || {}).length > 0;
          return (
            <div key={a.id}
              style={{
                padding: "4px 8px", borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
                borderLeft: `3px solid ${ac}`,
                cursor: "pointer", display: "flex", flexDirection: "column", gap: 2,
              }}
              onClick={() => setExpanded(isExpanded ? null : a.id)}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 5,
                fontSize: 10, fontFamily: "var(--lys-font-mono)" }}>
                {isExpanded
                  ? <ChevronDown size={10} style={{ color: "var(--lys-text-faint)" }} />
                  : <ChevronRight size={10} style={{ color: "var(--lys-text-faint)" }} />}
                <span style={{
                  fontSize: 8.5, padding: "0 5px", borderRadius: 999,
                  background: `${ac}15`, color: ac, fontWeight: 700,
                  letterSpacing: "0.04em",
                }}>{a.agent_name}</span>
                <span style={{
                  fontSize: 8.5, padding: "0 5px", borderRadius: 999,
                  background: `${tc}15`, color: tc, fontWeight: 600,
                }}>{a.action_type}</span>
                <span style={{ fontSize: 9, color: "var(--lys-text-faint)" }}>{fmtTs(a.ts)}</span>
                <span style={{ flex: 1, color: "var(--lys-text)",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {a.message_text.replace(/\n/g, " ").slice(0, 90)}
                </span>
                {a.confidence > 0 && (
                  <span style={{
                    fontSize: 8.5, fontWeight: 700, color: confColor(a.confidence),
                    fontFamily: "var(--lys-font-mono)",
                  }}>
                    {(a.confidence * 100).toFixed(0)}%
                  </span>
                )}
              </div>
              {/* Confidence bar */}
              {a.confidence > 0 && (
                <div style={{ height: 2, borderRadius: 1, marginLeft: 18,
                  background: "var(--lys-border-faint, rgba(0,0,0,0.04))",
                  overflow: "hidden" }}>
                  <div style={{ height: "100%",
                    width: `${a.confidence * 100}%`,
                    background: confColor(a.confidence) }} />
                </div>
              )}
              {isExpanded && (
                <div style={{ marginLeft: 18, padding: "4px 6px", borderRadius: 4,
                  background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
                  fontSize: 10, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-dim)" }}>
                  <div style={{ whiteSpace: "pre-wrap", marginBottom: 4 }}>
                    {a.message_text}
                  </div>
                  {a.target_molecule_id && (
                    <div style={{ fontSize: 8.5, color: "var(--lys-text-faint)" }}>
                      target_mol_id: <code>{a.target_molecule_id}</code>
                      {a.target_atom_idx !== null && <> · atom {a.target_atom_idx}</>}
                    </div>
                  )}
                  {hasRefs && (
                    <pre style={{ margin: "4px 0 0 0", padding: 4,
                      borderRadius: 3, background: "var(--lys-bg-2, #ffffff)",
                      fontSize: 9, color: "var(--lys-text-dim)",
                      maxHeight: 100, overflow: "auto",
                    }}>
{JSON.stringify(a.references, null, 2)}
                    </pre>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{ padding: "20px 10px", textAlign: "center",
      color: "var(--lys-text-faint)", fontSize: 10.5,
      fontFamily: "var(--lys-font-mono)" }}>{msg}</div>
  );
}

function confColor(c: number): string {
  if (c >= 0.75) return "#10b981";
  if (c >= 0.5) return "#d97706";
  return "#dc2626";
}

const inputStyle: React.CSSProperties = {
  flex: 1, fontSize: 10, fontFamily: "var(--lys-font-mono)",
  padding: "2px 6px", borderRadius: 4,
  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
  background: "var(--lys-bg-1, #ffffff)", color: "var(--lys-text)",
  outline: "none",
};

function chipStyle(active: boolean, color: string): React.CSSProperties {
  return {
    padding: "1px 6px", borderRadius: 999, fontSize: 9,
    fontFamily: "var(--lys-font-mono)",
    border: `1px solid ${active ? color : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
    background: active ? `${color}15` : "var(--lys-bg-3, rgba(0,0,0,0.02))",
    color: active ? color : "var(--lys-text-dim)",
    cursor: "pointer", fontWeight: active ? 700 : 400,
    textTransform: "lowercase",
  };
}

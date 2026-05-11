/**
 * AgentsHubCard — staff-level Agents container surface.
 *
 * Live, queue-aware, end-to-end-wired view of every agent in the
 * session. Five panels stacked top-down:
 *
 *   1. AGENT FLOW GRAPH    — Designer → Critic → Editor → Strategist
 *                             with arrows lighting up as actions land
 *   2. PER-AGENT KPI GRID  — n_actions, avg latency, ok-rate, last-action
 *                             + a per-role 24-bucket sparkline
 *   3. ACTION TIMELINE     — bucketed counts per agent, stacked area
 *   4. ACTION LOG          — reverse-chrono live list, filterable by role
 *   5. ROLE INSPECTOR      — click any agent → drilldown of all its
 *                             actions with action_type breakdown
 *
 * Polls every 1.5s while the chat session is active. All five panels
 * share the same `useAgentsLive` hook so they paint in lockstep.
 *
 * Backend endpoints (workspace/api/workbench.py + agent_activity.py):
 *   GET /workbench/sessions/{sid}/agent-live/recent
 *   GET /workbench/sessions/{sid}/agent-live/metrics
 *   GET /workbench/sessions/{sid}/agent-live/timeline
 */
import { useEffect, useState } from "react";
import {
  Pencil, Search, Scissors, Target, Brain, Sparkles, Activity,
  Clock, Zap, ArrowRight, ChevronRight, ChevronDown,
} from "lucide-react";

const ROLES = ["designer", "critic", "editor", "strategist", "orchestrator"] as const;
type Role = typeof ROLES[number];

const ROLE_META: Record<Role, { label: string; color: string; bg: string; icon: any; tagline: string }> = {
  designer:    { label: "Designer",    color: "#10b981", bg: "rgba(16,185,129,0.10)",  icon: Pencil,    tagline: "synthesizer of new candidates" },
  critic:      { label: "Critic",      color: "#dc2626", bg: "rgba(220,38,38,0.10)",   icon: Search,    tagline: "adversarial weakness probe" },
  editor:      { label: "Editor",      color: "#3b82f6", bg: "rgba(59,130,246,0.10)",  icon: Scissors,  tagline: "applies surgical SAR edits" },
  strategist:  { label: "Strategist",  color: "#7c63d8", bg: "rgba(124,99,216,0.10)",  icon: Target,    tagline: "high-level direction setter" },
  orchestrator:{ label: "Orchestrator",color: "#f59e0b", bg: "rgba(245,158,11,0.10)",  icon: Brain,     tagline: "meta-coordinator + arbiter" },
};

interface AgentMetric {
  agent: Role;
  n_actions: number;
  avg_latency_ms: number;
  sum_latency_ms?: number;
  p50_ms: number; p95_ms: number; p99_ms: number;
  avg_confidence: number;
  ok_rate: number;
  error_count: number;
  tokens_in: number; tokens_out: number; cost_usd: number;
  last_ts: number | null;
  last_action: string | null;
  action_types: Record<string, number>;
}
interface MetricsResponse {
  session: string;
  agents: AgentMetric[];
  total_actions: number;
  duration_s: number;
  total_tokens_in: number;
  total_tokens_out: number;
  total_cost_usd: number;
  total_errors: number;
}
interface ActionRecord {
  id: string; session_id: string; ts: number;
  agent_name: string; action_type: string;
  message_text: string; elapsed_ms: number;
  confidence: number; status: string;
  tokens_in?: number; tokens_out?: number; cost_usd?: number;
  triggered_by?: string | null;
  parent_run_id?: string | null;
  tags?: string[];
  references?: any;
}
// (RecentResponse shape inlined — only the actions array is consumed)
interface TimelineResponse {
  session: string; bucket_s: number;
  buckets: number[]; by_agent: Record<Role, number[]>;
}
interface HandoffsResponse {
  session: string;
  edges: { from: string; to: string; count: number }[];
}

function useAgentsLive(apiBase: string, sessionId: string | null) {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [recent, setRecent] = useState<ActionRecord[]>([]);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [handoffs, setHandoffs] = useState<HandoffsResponse | null>(null);
  const [errors, setErrors] = useState<ActionRecord[]>([]);
  const [streamConnected, setStreamConnected] = useState(false);

  // SSE — push every record() to subscribers within ~50ms. The poll
  // below still runs every 3s as a self-heal in case the stream drops.
  useEffect(() => {
    if (!sessionId) return;
    const url = `${apiBase}/workbench/sessions/${sessionId}/agent-live/stream`;
    const es = new EventSource(url.startsWith("http") ? url : `${window.location.origin}${url}`);
    setStreamConnected(false);
    es.addEventListener("action", (ev) => {
      try {
        const a = JSON.parse((ev as MessageEvent).data ?? "{}") as ActionRecord;
        setRecent((prev) => {
          // Dedupe by id; keep last 400
          if (prev.some((p) => p.id === a.id)) return prev;
          return [...prev.slice(-399), a];
        });
      } catch { /* */ }
    });
    es.addEventListener("ping", () => setStreamConnected(true));
    es.onopen = () => setStreamConnected(true);
    es.onerror = () => setStreamConnected(false);
    return () => es.close();
  }, [apiBase, sessionId]);

  // Poll metrics + timeline + handoffs (cheap aggregates, 2s interval).
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const [mr, rr, tr, hr, er] = await Promise.all([
          fetch(`${apiBase}/workbench/sessions/${sessionId}/agent-live/metrics`),
          fetch(`${apiBase}/workbench/sessions/${sessionId}/agent-live/recent?limit=400`),
          fetch(`${apiBase}/workbench/sessions/${sessionId}/agent-live/timeline?bucket_s=5`),
          fetch(`${apiBase}/workbench/sessions/${sessionId}/agent-live/handoffs`),
          fetch(`${apiBase}/workbench/sessions/${sessionId}/agent-live/errors`),
        ]);
        if (cancelled) return;
        if (mr.ok) setMetrics(await mr.json());
        if (rr.ok) setRecent((await rr.json()).actions ?? []);
        if (tr.ok) setTimeline(await tr.json());
        if (hr.ok) setHandoffs(await hr.json());
        if (er.ok) setErrors((await er.json()).errors ?? []);
      } catch { /* */ }
    };
    tick();
    const t = setInterval(tick, 2200);
    return () => { cancelled = true; clearInterval(t); };
  }, [apiBase, sessionId]);

  return { metrics, recent, timeline, handoffs, errors, streamConnected };
}

interface Props { apiBase: string; sessionId: string | null }

export function AgentsHubCard({ apiBase, sessionId }: Props) {
  const { metrics, recent, timeline, handoffs, errors, streamConnected } =
    useAgentsLive(apiBase, sessionId);
  const [inspect, setInspect] = useState<Role | null>(null);
  const [filter, setFilter] = useState<Role | "all">("all");

  const totalActions = metrics?.total_actions ?? 0;
  const durationS = metrics?.duration_s ?? 0;

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 12,
      fontFamily: "var(--lys-font-body)",
    }}>
      {/* Top status strip */}
      <TopStrip
        total={totalActions} durationS={durationS} sessionId={sessionId}
        streamConnected={streamConnected}
      />

      {/* Token + cost meter — running spend across all Gemini calls */}
      <CostMeter metrics={metrics} />

      {/* Flow graph — Designer → Critic → Editor → Strategist arrows */}
      <FlowGraph metrics={metrics} recent={recent} />

      {/* Cross-agent handoff edge map — who triggered whom */}
      <HandoffGraph handoffs={handoffs} />

      {/* Per-agent KPI grid */}
      <KpiGrid
        metrics={metrics}
        timeline={timeline}
        onInspect={(r) => setInspect((cur) => cur === r ? null : r)}
        inspect={inspect}
      />

      {/* Latency percentiles per role (p50/p95/p99) */}
      <LatencyPanel metrics={metrics} />

      {/* Time-spent bar — total wall-clock per agent (where time goes) */}
      <TimeSpentBar metrics={metrics} />

      {/* Errors panel — alerts row */}
      {errors.length > 0 && <ErrorsPanel errors={errors} />}

      {/* Stacked timeline */}
      <Timeline timeline={timeline} />

      {/* Action log */}
      <ActionLog recent={recent} filter={filter} setFilter={setFilter} />

      {/* Role inspector — drilldown */}
      {inspect && metrics && (
        <RoleInspector
          role={inspect}
          metric={metrics.agents.find((a) => a.agent === inspect)!}
          actions={recent.filter((a) => a.agent_name === inspect)}
          onClose={() => setInspect(null)}
        />
      )}
    </div>
  );
}

// ── Token + cost meter ──────────────────────────────────────────────

function CostMeter({ metrics }: { metrics: MetricsResponse | null }) {
  if (!metrics) return null;
  const tin = metrics.total_tokens_in ?? 0;
  const tout = metrics.total_tokens_out ?? 0;
  const cost = metrics.total_cost_usd ?? 0;
  const errs = metrics.total_errors ?? 0;
  if (!tin && !tout && !cost && !errs) return null;
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6,
    }}>
      <BigStat
        label="cost so far" value={`$${cost.toFixed(4)}`}
        sub="cumulative LLM spend" color="#7c63d8"
      />
      <BigStat
        label="tokens in" value={fmtN(tin)}
        sub="prompts + system" color="#3b82f6"
      />
      <BigStat
        label="tokens out" value={fmtN(tout)}
        sub="completions" color="#10b981"
      />
      <BigStat
        label="errors" value={String(errs)}
        sub={errs ? "needs review" : "all clean"}
        color={errs ? "#dc2626" : "#10b981"}
      />
    </div>
  );
}

function BigStat({ label, value, sub, color }: {
  label: string; value: string; sub: string; color: string;
}) {
  return (
    <div style={{
      padding: "9px 12px",
      background: "white",
      border: "1px solid rgba(0,0,0,0.06)",
      borderLeft: `3px solid ${color}`,
      borderRadius: 5,
    }}>
      <div style={{
        fontSize: 9.5, color: "var(--lys-text-faint)",
        fontFamily: "var(--lys-font-mono)", textTransform: "uppercase",
        letterSpacing: "0.06em", fontWeight: 700,
      }}>{label}</div>
      <div style={{
        fontSize: 18, fontWeight: 700, color, fontFamily: "var(--lys-font-mono)",
        marginTop: 2, lineHeight: 1.05,
      }}>{value}</div>
      <div style={{
        fontSize: 10, color: "var(--lys-text-dim)", marginTop: 1,
      }}>{sub}</div>
    </div>
  );
}

// ── Handoff graph ───────────────────────────────────────────────────

function HandoffGraph({ handoffs }: { handoffs: HandoffsResponse | null }) {
  if (!handoffs || handoffs.edges.length === 0) return null;
  const max = Math.max(1, ...handoffs.edges.map((e) => e.count));
  return (
    <div style={{
      padding: 10,
      background: "white",
      border: "1px solid rgba(0,0,0,0.06)",
      borderRadius: 6,
    }}>
      <SectionTitle>Cross-agent handoffs · who triggers whom</SectionTitle>
      <div style={{
        marginTop: 6,
        display: "flex", flexDirection: "column", gap: 3,
      }}>
        {handoffs.edges.slice(0, 8).map((e) => {
          const fromMeta = ROLE_META[e.from as Role] ?? ROLE_META.designer;
          const toMeta = ROLE_META[e.to as Role] ?? ROLE_META.designer;
          const w = (e.count / max) * 100;
          return (
            <div key={`${e.from}->${e.to}`} style={{
              display: "flex", alignItems: "center", gap: 6,
              fontSize: 11, fontFamily: "var(--lys-font-body)",
            }}>
              <span style={{
                fontFamily: "var(--lys-font-mono)", fontSize: 10,
                color: fromMeta.color, fontWeight: 700,
                minWidth: 88,
              }}>{e.from}</span>
              <ArrowRight size={11} color="var(--lys-text-faint)" />
              <span style={{
                fontFamily: "var(--lys-font-mono)", fontSize: 10,
                color: toMeta.color, fontWeight: 700,
                minWidth: 88,
              }}>{e.to}</span>
              <div style={{
                flex: 1, height: 6, borderRadius: 999,
                background: "rgba(0,0,0,0.04)",
                position: "relative", overflow: "hidden",
              }}>
                <div style={{
                  position: "absolute", inset: 0,
                  width: `${w}%`,
                  background: `linear-gradient(90deg, ${fromMeta.color}, ${toMeta.color})`,
                  borderRadius: 999,
                }} />
              </div>
              <span style={{
                fontFamily: "var(--lys-font-mono)", fontSize: 10,
                color: "var(--lys-text-dim)", fontWeight: 600,
                minWidth: 26, textAlign: "right",
              }}>{e.count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Latency percentiles ─────────────────────────────────────────────

function LatencyPanel({ metrics }: { metrics: MetricsResponse | null }) {
  if (!metrics) return null;
  const rows = metrics.agents.filter((a) => a.n_actions > 0);
  if (!rows.length) return null;
  const max = Math.max(1, ...rows.map((r) => r.p99_ms));
  return (
    <div style={{
      padding: 10,
      background: "white",
      border: "1px solid rgba(0,0,0,0.06)",
      borderRadius: 6,
    }}>
      <SectionTitle>Latency distribution · p50 / p95 / p99 per role</SectionTitle>
      <div style={{
        marginTop: 6, display: "flex", flexDirection: "column", gap: 4,
      }}>
        {rows.map((r) => {
          const meta = ROLE_META[r.agent];
          return (
            <div key={r.agent} style={{
              display: "flex", alignItems: "center", gap: 6,
              fontSize: 11, fontFamily: "var(--lys-font-body)",
            }}>
              <span style={{
                fontFamily: "var(--lys-font-mono)", fontSize: 10,
                color: meta.color, fontWeight: 700, minWidth: 88,
                textTransform: "uppercase", letterSpacing: "0.04em",
              }}>{r.agent}</span>
              <div style={{
                flex: 1, height: 12, borderRadius: 4,
                background: "rgba(0,0,0,0.04)",
                position: "relative", overflow: "hidden",
              }}>
                <div style={{
                  position: "absolute", left: 0, top: 0, bottom: 0,
                  width: `${(r.p50_ms / max) * 100}%`,
                  background: meta.color, opacity: 0.7,
                }} />
                <div style={{
                  position: "absolute", left: `${(r.p50_ms / max) * 100}%`, top: 0, bottom: 0,
                  width: `${((r.p95_ms - r.p50_ms) / max) * 100}%`,
                  background: meta.color, opacity: 0.4,
                }} />
                <div style={{
                  position: "absolute", left: `${(r.p95_ms / max) * 100}%`, top: 0, bottom: 0,
                  width: `${((r.p99_ms - r.p95_ms) / max) * 100}%`,
                  background: meta.color, opacity: 0.2,
                }} />
              </div>
              <span style={{
                fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
                color: "var(--lys-text-dim)",
                minWidth: 130, textAlign: "right",
              }}>
                {formatMs(r.p50_ms)} / {formatMs(r.p95_ms)} / {formatMs(r.p99_ms)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Time-spent bar ──────────────────────────────────────────────────
// Where the agentic loop is actually spending wall-clock. Sums per
// agent's elapsed_ms and renders as a stacked horizontal bar — the
// bottleneck rises to the top by visual mass.

function TimeSpentBar({ metrics }: { metrics: MetricsResponse | null }) {
  if (!metrics) return null;
  // Prefer authoritative sum_latency_ms; fall back to n×avg.
  const rows = metrics.agents
    .map((m) => ({
      agent: m.agent,
      total: m.sum_latency_ms ?? (m.avg_latency_ms * m.n_actions),
      n: m.n_actions,
    }))
    .filter((r) => r.total > 0)
    .sort((a, b) => b.total - a.total);
  if (rows.length === 0) return null;
  const grand = rows.reduce((s, r) => s + r.total, 0);
  return (
    <div style={{
      padding: 10, background: "white",
      border: "1px solid rgba(0,0,0,0.06)", borderLeft: "3px solid #c2adff",
      borderRadius: 6,
    }}>
      <SectionTitle>Time spent · per agent (total wall-clock)</SectionTitle>
      <div style={{ marginTop: 6 }}>
        {/* Stacked bar */}
        <div style={{
          display: "flex", height: 14, borderRadius: 4, overflow: "hidden",
          border: "1px solid rgba(0,0,0,0.05)", background: "rgba(0,0,0,0.02)",
        }}>
          {rows.map((r) => {
            const meta = ROLE_META[r.agent as Role];
            const pct = (r.total / grand) * 100;
            return (
              <div
                key={r.agent}
                title={`${meta.label}: ${formatMs(r.total)} (${pct.toFixed(0)}%) · ${r.n} actions`}
                style={{
                  width: `${pct}%`, background: meta.color,
                  borderRight: "1px solid rgba(255,255,255,0.40)",
                }}
              />
            );
          })}
        </div>
        {/* Per-agent rows with totals */}
        <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 4 }}>
          {rows.map((r) => {
            const meta = ROLE_META[r.agent as Role];
            const pct = (r.total / grand) * 100;
            return (
              <div key={r.agent} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{
                  width: 10, height: 10, borderRadius: 2, background: meta.color,
                }} />
                <span style={{
                  fontFamily: "var(--lys-font-mono)", fontSize: 10.5, fontWeight: 700,
                  color: meta.color, minWidth: 80, textTransform: "uppercase",
                  letterSpacing: "0.04em",
                }}>{meta.label}</span>
                <div style={{
                  flex: 1, height: 6, background: "rgba(0,0,0,0.04)", borderRadius: 3,
                  overflow: "hidden",
                }}>
                  <div style={{ width: `${pct}%`, height: "100%", background: meta.color }} />
                </div>
                <span style={{
                  fontFamily: "var(--lys-font-mono)", fontSize: 10, color: "var(--lys-text-dim)",
                  minWidth: 100, textAlign: "right",
                }}>
                  {formatMs(r.total)} · {pct.toFixed(0)}% · {r.n} call{r.n !== 1 ? "s" : ""}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Errors panel ────────────────────────────────────────────────────

function ErrorsPanel({ errors }: { errors: ActionRecord[] }) {
  return (
    <div style={{
      padding: 10,
      background: "rgba(220,38,38,0.04)",
      border: "1px solid rgba(220,38,38,0.30)",
      borderLeft: "3px solid #dc2626",
      borderRadius: 6,
    }}>
      <SectionTitle>⚠ Errors · {errors.length} recent</SectionTitle>
      <div style={{ marginTop: 4, display: "flex", flexDirection: "column", gap: 3 }}>
        {errors.slice(-5).reverse().map((e) => (
          <div key={e.id} style={{
            fontSize: 10.5, fontFamily: "var(--lys-font-body)",
            display: "flex", gap: 6, alignItems: "center",
          }}>
            <span style={{
              fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
              color: "#dc2626", fontWeight: 700, minWidth: 88,
            }}>{e.agent_name}</span>
            <span style={{
              fontFamily: "var(--lys-font-mono)", fontSize: 10,
              color: "var(--lys-text-dim)", minWidth: 80,
            }}>{e.action_type}</span>
            <span style={{
              flex: 1, color: "#7f1d1d",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            }}>{e.message_text}</span>
            <span style={{
              fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
              color: "var(--lys-text-faint)",
            }}>{relTime(e.ts)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function fmtN(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}

// ── Top status strip ────────────────────────────────────────────────

function TopStrip({ total, durationS, sessionId, streamConnected }: {
  total: number; durationS: number; sessionId: string | null; streamConnected: boolean;
}) {
  const rate = durationS > 0 ? (total / durationS).toFixed(2) : "0.00";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap",
      padding: "6px 10px",
      background: "rgba(124,99,216,0.06)",
      border: "1px solid rgba(124,99,216,0.18)",
      borderRadius: 6,
      fontSize: 11.5,
    }}>
      <Sparkles size={12} color="#7c63d8" />
      <span style={{ fontWeight: 700, color: "#6041d0", textTransform: "uppercase",
        fontFamily: "var(--lys-font-mono)", fontSize: 10, letterSpacing: "0.06em" }}>
        agents · live
      </span>
      <span style={{
        display: "inline-flex", alignItems: "center", gap: 3,
        padding: "1px 5px", borderRadius: 999,
        background: streamConnected ? "rgba(16,185,129,0.12)" : "rgba(245,158,11,0.12)",
        color: streamConnected ? "#10b981" : "#ca8a04",
        fontFamily: "var(--lys-font-mono)", fontSize: 9.5, fontWeight: 700,
        textTransform: "uppercase", letterSpacing: "0.04em",
      }}>
        <span style={{
          width: 6, height: 6, borderRadius: 999,
          background: streamConnected ? "#10b981" : "#ca8a04",
          animation: streamConnected ? "lys-pulse 1.6s ease-in-out infinite" : "none",
        }} />
        {streamConnected ? "sse" : "polling"}
      </span>
      <span style={{ color: "var(--lys-text-faint)" }}>session</span>
      <code style={{
        fontFamily: "var(--lys-font-mono)", fontSize: 10.5,
        color: "var(--lys-text)", background: "rgba(0,0,0,0.04)",
        padding: "1px 5px", borderRadius: 3,
      }}>{(sessionId ?? "—").slice(0, 14)}</code>
      <span style={{ flex: 1 }} />
      <Stat icon={<Activity size={11} />} label="actions" value={String(total)} />
      <Stat icon={<Clock size={11} />} label="duration" value={`${durationS.toFixed(1)}s`} />
      <Stat icon={<Zap size={11} />} label="rate" value={`${rate}/s`} />
      <style>{`@keyframes lys-pulse{0%,100%{opacity:1}50%{opacity:0.4}}`}</style>
    </div>
  );
}

function Stat({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      padding: "1px 8px",
      background: "white",
      border: "1px solid rgba(0,0,0,0.06)",
      borderRadius: 4,
    }}>
      <span style={{ color: "#7c63d8" }}>{icon}</span>
      <span style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
        fontFamily: "var(--lys-font-mono)", textTransform: "uppercase",
        letterSpacing: "0.05em",
      }}>{label}</span>
      <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 11,
        fontWeight: 700, color: "var(--lys-text)",
      }}>{value}</span>
    </div>
  );
}

// ── Flow graph ──────────────────────────────────────────────────────

function FlowGraph({ metrics, recent }: { metrics: MetricsResponse | null; recent: ActionRecord[] }) {
  // Time-window the counts so the widget shows what the agents did
  // RIGHT NOW, not cumulative totals from earlier work in the same
  // session (which user correctly called out as misleading — same
  // numbers as the all-time card).
  const WINDOW_S = 300;   // last 5 minutes
  const ACTIVE_S = 4;     // pulsing pill if seen in last 4s
  const now = Date.now() / 1000;
  const recentInWindow = recent.filter((r) => now - r.ts < WINDOW_S);
  const activeRoles = new Set(
    recentInWindow.filter((r) => now - r.ts < ACTIVE_S).map((r) => r.agent_name)
  );
  // Per-role count inside the time window (NOT the cumulative
  // metrics.agents[].n_actions which spans the whole session).
  const counts: Record<string, number> = {};
  for (const r of recentInWindow) {
    counts[r.agent_name] = (counts[r.agent_name] ?? 0) + 1;
  }
  const totalActions = recentInWindow.length;
  const isEmpty = totalActions === 0;
  return (
    <div style={{
      padding: "10px 12px",
      background: "white",
      border: "1px solid rgba(0,0,0,0.06)",
      borderRadius: 6,
    }}>
      <SectionTitle>Multi-agent flow · last 5 minutes</SectionTitle>
      {isEmpty && (
        <div style={{
          marginTop: 6, padding: "8px 10px",
          background: "rgba(99, 102, 241, 0.06)",
          border: "1px dashed rgba(99, 102, 241, 0.30)",
          borderRadius: 6,
          fontSize: 11, color: "var(--lys-text-dim)",
          fontFamily: "var(--lys-font-body)",
          lineHeight: 1.45,
        }}>
          <strong>No agent activity in the last 5 minutes.</strong> Run a
          workflow like <code>/wf design_with_debate</code> or
          <code>/wf harden_candidate</code> — each step the
          Designer / Critic / Editor / Strategist takes will light up
          here in real time. Cumulative totals are in the "all-time"
          card below.
        </div>
      )}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        gap: 6, marginTop: 6,
      }}>
        {ROLES.slice(0, 4).map((r, i) => {
          const meta = ROLE_META[r];
          const Icon = meta.icon;
          const n = counts[r] ?? 0;
          const live = activeRoles.has(r);
          return (
            <div key={r} style={{ display: "flex", alignItems: "center", gap: 4, flex: 1, justifyContent: "center" }}>
              <div style={{
                display: "flex", flexDirection: "column", alignItems: "center", gap: 2,
                padding: "5px 8px",
                background: live ? meta.color : meta.bg,
                color: live ? "white" : meta.color,
                border: `1.5px solid ${meta.color}`,
                borderRadius: 999,
                minWidth: 80,
                transition: "background 0.2s, color 0.2s",
                boxShadow: live ? `0 0 0 4px ${meta.color}30` : "none",
              }}>
                <Icon size={14} />
                <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 10, fontWeight: 700 }}>
                  {meta.label}
                </span>
                <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 9, opacity: 0.85 }}>
                  {n} action{n === 1 ? "" : "s"}
                </span>
              </div>
              {i < 3 && (
                <ArrowRight size={14} color="var(--lys-text-faint)" style={{ flexShrink: 0 }} />
              )}
            </div>
          );
        })}
      </div>
      {/* Orchestrator runs LATERALLY — sits below the chain */}
      {metrics?.agents.find((a) => a.agent === "orchestrator")?.n_actions ? (
        <div style={{
          marginTop: 8, paddingTop: 6,
          borderTop: "1px dashed rgba(0,0,0,0.08)",
          display: "flex", alignItems: "center", gap: 6,
          fontSize: 10.5, color: "var(--lys-text-dim)",
        }}>
          <Brain size={11} color={ROLE_META.orchestrator.color} />
          <span style={{
            fontFamily: "var(--lys-font-mono)", fontWeight: 700,
            color: ROLE_META.orchestrator.color, textTransform: "uppercase",
            fontSize: 9.5, letterSpacing: "0.04em",
          }}>orchestrator</span>
          <span>{counts.orchestrator ?? 0} routing decisions · arbitrates the chain</span>
        </div>
      ) : null}
    </div>
  );
}

// ── KPI grid ────────────────────────────────────────────────────────

function KpiGrid({ metrics, timeline, onInspect, inspect }: {
  metrics: MetricsResponse | null;
  timeline: TimelineResponse | null;
  onInspect: (r: Role) => void;
  inspect: Role | null;
}) {
  const buckets = (role: Role): number[] => timeline?.by_agent?.[role] ?? [];
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
      gap: 6,
    }}>
      {ROLES.map((r) => {
        const meta = ROLE_META[r];
        const m = metrics?.agents.find((a) => a.agent === r);
        const Icon = meta.icon;
        const sel = inspect === r;
        return (
          <button
            key={r}
            type="button"
            onClick={() => onInspect(r)}
            style={{
              display: "flex", flexDirection: "column", gap: 4,
              padding: "8px 10px",
              background: sel ? meta.bg : "white",
              border: `1px solid ${sel ? meta.color : "rgba(0,0,0,0.06)"}`,
              borderLeft: `3px solid ${meta.color}`,
              borderRadius: 5,
              textAlign: "left",
              cursor: "pointer",
              transition: "background 0.12s, border-color 0.12s",
              fontFamily: "var(--lys-font-body)",
            }}
            onMouseEnter={(e) => { if (!sel) (e.currentTarget as HTMLButtonElement).style.background = meta.bg; }}
            onMouseLeave={(e) => { if (!sel) (e.currentTarget as HTMLButtonElement).style.background = "white"; }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 5,
            }}>
              <Icon size={12} color={meta.color} />
              <span style={{ fontWeight: 700, fontSize: 11.5, color: meta.color,
                fontFamily: "var(--lys-font-mono)", textTransform: "uppercase",
                letterSpacing: "0.04em",
              }}>{meta.label}</span>
              <span style={{ flex: 1 }} />
              <span style={{
                padding: "1px 5px", borderRadius: 3,
                background: meta.color, color: "white",
                fontFamily: "var(--lys-font-mono)", fontSize: 9.5, fontWeight: 700,
              }}>{m?.n_actions ?? 0}</span>
            </div>
            <Sparkline data={buckets(r)} color={meta.color} />
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 3,
              fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
              color: "var(--lys-text-dim)",
            }}>
              <Pip label="lat" value={m?.avg_latency_ms ? formatMs(m.avg_latency_ms) : "—"} />
              <Pip label="ok" value={m ? `${(m.ok_rate * 100).toFixed(0)}%` : "—"} />
              <Pip label="conf" value={m?.avg_confidence ? m.avg_confidence.toFixed(2) : "—"} />
            </div>
            <div style={{
              fontSize: 10, color: "var(--lys-text-faint)",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              fontStyle: "italic",
            }}>{m?.last_action ?? meta.tagline}</div>
          </button>
        );
      })}
    </div>
  );
}

function Pip({ label, value }: { label: string; value: string }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "flex-start",
    }}>
      <span style={{ fontSize: 8.5, opacity: 0.7,
        textTransform: "uppercase", letterSpacing: "0.04em",
      }}>{label}</span>
      <span style={{ fontWeight: 700, color: "var(--lys-text)" }}>{value}</span>
    </div>
  );
}

function Sparkline({ data, color }: { data: number[]; color: string }) {
  if (!data.length) {
    return <div style={{ height: 22, opacity: 0.4 }} />;
  }
  const max = Math.max(1, ...data);
  const W = 100; const H = 22;
  const dx = data.length > 1 ? W / (data.length - 1) : W;
  const pts = data.map((v, i) => `${(i * dx).toFixed(1)},${(H - (v / max) * (H - 2) - 1).toFixed(1)}`);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
      style={{ width: "100%", height: H, display: "block" }}>
      <polyline
        fill="none" stroke={color} strokeWidth="1.4"
        points={pts.join(" ")}
      />
      <polyline
        fill={color} fillOpacity="0.15" stroke="none"
        points={`0,${H} ${pts.join(" ")} ${W},${H}`}
      />
    </svg>
  );
}

// ── Timeline (stacked area) ─────────────────────────────────────────

function Timeline({ timeline }: { timeline: TimelineResponse | null }) {
  if (!timeline || !timeline.buckets.length) {
    return (
      <div style={{
        padding: 12, background: "white",
        border: "1px solid rgba(0,0,0,0.06)", borderRadius: 6,
      }}>
        <SectionTitle>Action timeline</SectionTitle>
        <div style={{ fontSize: 10.5, color: "var(--lys-text-faint)",
          fontStyle: "italic", textAlign: "center", padding: 12,
        }}>no agent activity yet — fire a workflow or chat</div>
      </div>
    );
  }
  const W = 600; const H = 80;
  const buckets = timeline.buckets.length;
  const dx = buckets > 1 ? W / (buckets - 1) : W;
  // Build stacked layers
  const stack: number[][] = [];
  let totals = new Array(buckets).fill(0);
  for (const r of ROLES) {
    const arr = timeline.by_agent[r] ?? new Array(buckets).fill(0);
    stack.push([...totals]);  // base
    totals = totals.map((v, i) => v + (arr[i] ?? 0));
  }
  const max = Math.max(1, ...totals);
  return (
    <div style={{
      padding: 12, background: "white",
      border: "1px solid rgba(0,0,0,0.06)", borderRadius: 6,
    }}>
      <SectionTitle>Action timeline · {timeline.bucket_s}s buckets</SectionTitle>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none"
        style={{ width: "100%", height: H, display: "block", marginTop: 4 }}>
        {ROLES.map((r, ri) => {
          const arr = timeline.by_agent[r] ?? new Array(buckets).fill(0);
          const base = stack[ri];
          const top = arr.map((v, i) => base[i] + v);
          const upPts = top.map((v, i) => `${(i * dx).toFixed(1)},${(H - (v / max) * (H - 2) - 1).toFixed(1)}`);
          const downPts = base.map((v, i) => `${(i * dx).toFixed(1)},${(H - (v / max) * (H - 2) - 1).toFixed(1)}`).reverse();
          return (
            <polygon
              key={r}
              fill={ROLE_META[r].color} fillOpacity={0.55}
              stroke={ROLE_META[r].color} strokeWidth="0.6"
              points={[...upPts, ...downPts].join(" ")}
            />
          );
        })}
      </svg>
      <div style={{
        marginTop: 4, display: "flex", flexWrap: "wrap", gap: 8,
        fontSize: 9.5, color: "var(--lys-text-dim)",
        fontFamily: "var(--lys-font-mono)",
      }}>
        {ROLES.map((r) => (
          <span key={r} style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 8, height: 8, borderRadius: 999, background: ROLE_META[r].color }} />
            {r}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── Action log ──────────────────────────────────────────────────────

function ActionLog({ recent, filter, setFilter }: {
  recent: ActionRecord[];
  filter: Role | "all";
  setFilter: (f: Role | "all") => void;
}) {
  const filtered = filter === "all"
    ? recent
    : recent.filter((r) => r.agent_name === filter);
  const items = [...filtered].reverse();
  return (
    <div style={{
      padding: 12, background: "white",
      border: "1px solid rgba(0,0,0,0.06)", borderRadius: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
        <SectionTitle>Action log · {recent.length} total</SectionTitle>
        <span style={{ flex: 1 }} />
        <FilterChip label="all" active={filter === "all"} onClick={() => setFilter("all")} />
        {ROLES.map((r) => (
          <FilterChip
            key={r}
            label={r}
            color={ROLE_META[r].color}
            active={filter === r}
            onClick={() => setFilter(filter === r ? "all" : r)}
          />
        ))}
      </div>
      <div style={{
        maxHeight: 220, overflowY: "auto",
        display: "flex", flexDirection: "column", gap: 3,
      }}>
        {items.length === 0 && (
          <div style={{ fontSize: 10.5, color: "var(--lys-text-faint)",
            fontStyle: "italic", textAlign: "center", padding: 12,
          }}>no matching actions</div>
        )}
        {items.slice(0, 80).map((a) => {
          const meta = ROLE_META[a.agent_name as Role] ?? ROLE_META.designer;
          return (
            <div key={a.id} style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "3px 6px",
              background: a.status === "running" ? meta.bg : "transparent",
              borderLeft: `2px solid ${meta.color}`,
              borderRadius: 2,
              fontSize: 11,
            }}>
              <span style={{
                fontFamily: "var(--lys-font-mono)", fontSize: 9.5, fontWeight: 700,
                color: meta.color, minWidth: 64,
              }}>{a.agent_name}</span>
              <span style={{
                fontFamily: "var(--lys-font-mono)", fontSize: 10,
                color: "var(--lys-text-dim)", minWidth: 80,
              }}>{a.action_type}</span>
              <span style={{
                flex: 1, minWidth: 0,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                color: "var(--lys-text)",
              }}>{a.message_text}</span>
              {a.elapsed_ms > 0 && (
                <span style={{
                  fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
                  color: "var(--lys-text-faint)",
                }}>{formatMs(a.elapsed_ms)}</span>
              )}
              <span style={{
                fontFamily: "var(--lys-font-mono)", fontSize: 9,
                color: "var(--lys-text-faint)", opacity: 0.7,
              }}>{relTime(a.ts)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FilterChip({ label, color, active, onClick }: {
  label: string; color?: string; active: boolean; onClick: () => void;
}) {
  return (
    <button onClick={onClick} style={{
      padding: "1px 7px",
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      fontWeight: active ? 700 : 500,
      background: active ? (color ?? "var(--lys-text)") : "transparent",
      color: active ? "white" : "var(--lys-text-dim)",
      border: `1px solid ${active ? (color ?? "var(--lys-text)") : "rgba(0,0,0,0.10)"}`,
      borderRadius: 999,
      cursor: "pointer",
      textTransform: "uppercase", letterSpacing: "0.04em",
    }}>{label}</button>
  );
}

// ── Inspector ───────────────────────────────────────────────────────

function RoleInspector({ role, metric, actions, onClose }: {
  role: Role; metric: AgentMetric; actions: ActionRecord[]; onClose: () => void;
}) {
  const meta = ROLE_META[role];
  const Icon = meta.icon;
  return (
    <div style={{
      padding: 12,
      background: meta.bg,
      border: `1px solid ${meta.color}`,
      borderLeft: `3px solid ${meta.color}`,
      borderRadius: 6,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
        <Icon size={14} color={meta.color} />
        <span style={{
          fontFamily: "var(--lys-font-mono)", fontWeight: 700, fontSize: 11.5,
          color: meta.color, textTransform: "uppercase", letterSpacing: "0.06em",
        }}>{meta.label} · inspector</span>
        <span style={{ flex: 1, fontSize: 10.5, color: "var(--lys-text-dim)",
          fontStyle: "italic", marginLeft: 6,
        }}>{meta.tagline}</span>
        <button onClick={onClose} style={{
          padding: "1px 8px", fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
          background: "transparent", border: `1px solid ${meta.color}40`,
          color: meta.color, borderRadius: 3, cursor: "pointer",
          textTransform: "uppercase", letterSpacing: "0.04em",
        }}>close</button>
      </div>

      {/* Action type histogram */}
      <div style={{ marginBottom: 8 }}>
        <SectionTitle>Action types · {Object.keys(metric.action_types).length}</SectionTitle>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
          {Object.entries(metric.action_types).map(([k, n]) => (
            <span key={k} style={{
              padding: "2px 7px",
              background: "white",
              border: `1px solid ${meta.color}40`,
              borderRadius: 999,
              fontSize: 10, fontFamily: "var(--lys-font-mono)",
              color: meta.color, fontWeight: 600,
            }}>
              {k} <strong>{n}</strong>
            </span>
          ))}
          {Object.keys(metric.action_types).length === 0 && (
            <span style={{ fontSize: 10, color: "var(--lys-text-faint)", fontStyle: "italic" }}>
              no actions yet
            </span>
          )}
        </div>
      </div>

      {/* Reverse-chrono action stream */}
      <SectionTitle>Reasoning trace · {actions.length} steps</SectionTitle>
      <div style={{
        marginTop: 4, maxHeight: 240, overflowY: "auto",
        display: "flex", flexDirection: "column", gap: 4,
      }}>
        {[...actions].reverse().slice(0, 50).map((a) => (
          <div key={a.id} style={{
            padding: "4px 8px",
            background: "white",
            borderLeft: `2px solid ${meta.color}`,
            borderRadius: 3,
            fontSize: 11,
          }}>
            <div style={{
              display: "flex", alignItems: "center", gap: 5,
              fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
              color: meta.color, fontWeight: 700, marginBottom: 1,
            }}>
              <span>{a.action_type}</span>
              <span style={{ flex: 1 }} />
              {a.elapsed_ms > 0 && <span>{formatMs(a.elapsed_ms)}</span>}
              <span style={{ opacity: 0.6 }}>{relTime(a.ts)}</span>
            </div>
            <div style={{
              fontFamily: "var(--lys-font-body)", fontSize: 11,
              color: "var(--lys-text)",
              wordBreak: "break-word", lineHeight: 1.45,
            }}>{a.message_text || "(no message)"}</div>
          </div>
        ))}
        {actions.length === 0 && (
          <div style={{ fontSize: 10.5, color: "var(--lys-text-faint)",
            fontStyle: "italic", padding: 12, textAlign: "center",
          }}>{meta.label} hasn't fired yet</div>
        )}
      </div>
    </div>
  );
}

// ── helpers ─────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <div style={{
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      color: "var(--lys-text-faint)", fontWeight: 700,
      letterSpacing: "0.06em", textTransform: "uppercase",
    }}>{children}</div>
  );
}

function formatMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m${Math.floor((ms % 60000) / 1000)}s`;
}

function relTime(ts: number): string {
  if (!ts) return "";
  const ms = ts < 1e12 ? ts * 1000 : ts;
  const elapsed = (Date.now() - ms) / 1000;
  if (elapsed < 5) return "now";
  if (elapsed < 60) return `${Math.round(elapsed)}s`;
  if (elapsed < 3600) return `${Math.round(elapsed / 60)}m`;
  return `${Math.round(elapsed / 3600)}h`;
}

// silence unused (kept imports for future use)
void ChevronRight; void ChevronDown;

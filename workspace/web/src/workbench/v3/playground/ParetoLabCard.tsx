/**
 * ParetoLabCard — Service 3 (heavy refactor, lavender-glass).
 *
 * Three modes:
 *   1. SCATTER  — single X-Y scatter with frontier highlight + axis pickers.
 *   2. MATRIX   — 2x2 grid of mini scatters (4 default axis pairs).
 *   3. COMPARE  — pick 2-5 candidates → parallel-coords table per axis.
 *
 * Live ops:
 *   - 8s polling refresh on the active scatter.
 *   - "Score missing" button kicks /pareto/score-missing for unscored candidates.
 *   - "Explain" button on hover popup → Gemini explanation.
 *
 * Design language: NOVEL lavender-glass — translucent accent bg, capsule
 * chips, click-to-collapse headers, font 9.5px/500/22-px height, no
 * black, body font-family.
 */
import { useEffect, useState, useMemo } from "react";
import type React from "react";
import { Activity, RefreshCw, ChevronDown, Grid3x3, Layers, Target, Sparkles, Zap } from "lucide-react";

interface AxisMeta {
  label: string;
  direction: string;
  source: string;
  unit: string;
}

interface PointDot {
  candidate_id: string;
  smiles: string;
  created_by: string;
  parent_id: string | null;
  x_value: number | null;
  y_value: number | null;
  on_pareto: boolean;
  valid: boolean;
}

interface ParetoResult {
  session_id: string;
  x_axis: string;
  y_axis: string;
  x_axis_meta: AxisMeta;
  y_axis_meta: AxisMeta;
  all_points: PointDot[];
  pareto_set: string[];
  stats: { n_total: number; n_with_scores: number; n_pareto: number };
}

interface MultiPanel {
  x: string;
  y: string;
  x_axis_meta: AxisMeta;
  y_axis_meta: AxisMeta;
  all_points: PointDot[];
  pareto_set: string[];
  stats: { n_total: number; n_with_scores: number; n_pareto: number };
}

interface CompareWinners { [axis: string]: string | null }
interface CompareRow {
  id: string;
  found: boolean;
  smiles?: string;
  created_by?: string;
  axes?: Record<string, number | null>;
  composite?: number | null;
}

interface AxesResp { axes: Record<string, AxisMeta> }

interface Props {
  apiBase: string;
  sessionId: string | null;
  onLoad?: (smiles: string) => void;
  /** Send a slash command to the agent thread. */
  onAgentMessage?: (message: string) => void;
}

const AGENT_DOT_COLOR: Record<string, string> = {
  designer: "#10b981",
  critic: "#ef4444",
  editor: "#3b82f6",
  strategist: "#8b5cf6",
  orchestrator: "#f59e0b",
  user: "#374151",
  agent: "#0891b2",
};

// Lavender-glass tokens (same as Resistance card)
const LAV = {
  bg: "rgba(174, 158, 244, 0.06)",
  bgStrong: "rgba(174, 158, 244, 0.12)",
  border: "rgba(174, 158, 244, 0.28)",
  borderStrong: "rgba(174, 158, 244, 0.42)",
  fg: "#7c63d8",
  fgDeep: "#6041d0",
} as const;

const RED = { bg: "rgba(220,38,38,0.08)", border: "rgba(220,38,38,0.32)", fg: "#dc2626" } as const;
const AMBER = { bg: "rgba(202,138,4,0.10)", border: "rgba(202,138,4,0.34)", fg: "#ca8a04" } as const;
const GREEN = { bg: "rgba(16,185,129,0.10)", border: "rgba(16,185,129,0.34)", fg: "#10b981" } as const;


// ─────────────────────────────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────────────────────────────

export function ParetoLabCard({ apiBase, sessionId, onLoad, onAgentMessage }: Props) {
  const [axes, setAxes] = useState<Record<string, AxisMeta>>({});
  const [xAxis, setXAxis] = useState<string>("predicted_mic");
  const [yAxis, setYAxis] = useState<string>("composite_reward");
  const [data, setData] = useState<ParetoResult | null>(null);
  const [multi, setMulti] = useState<MultiPanel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [pinnedId, setPinnedId] = useState<string | null>(null);
  const [xPickerOpen, setXPickerOpen] = useState(false);
  const [yPickerOpen, setYPickerOpen] = useState(false);
  const [headerOpen, setHeaderOpen] = useState(true);

  // Mode
  const [mode, setMode] = useState<"scatter" | "matrix" | "compare">("scatter");

  // Score-missing
  const [scoringStatus, setScoringStatus] = useState<{ n_missing: number; n_enqueued: number } | null>(null);
  const [scoringLoading, setScoringLoading] = useState(false);

  // Explain
  const [explainResult, setExplainResult] = useState<{ candidate_id: string; explanation: string } | null>(null);
  const [explainLoading, setExplainLoading] = useState(false);

  // Compare
  const [comparePicks, setComparePicks] = useState<string[]>([]);
  const [compareRows, setCompareRows] = useState<CompareRow[]>([]);
  const [compareWinners, setCompareWinners] = useState<CompareWinners>({});
  const [compareLoading, setCompareLoading] = useState(false);

  // ── Fetch axes registry once
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/chem/session/__init/axes`);
        if (!r.ok) return;
        const d: AxesResp = await r.json();
        if (!cancelled) setAxes(d.axes);
      } catch {/*noop*/}
    })();
    return () => { cancelled = true; };
  }, [apiBase]);

  // ── Refresh fn (used by polling + on-demand)
  const refresh = useMemo(() => async (cancelledRef: { current: boolean }) => {
    if (!sessionId) { setData(null); setMulti([]); return; }
    setLoading(true);
    try {
      if (mode === "matrix") {
        const r = await fetch(`${apiBase}/workbench/chem/session/${encodeURIComponent(sessionId)}/pareto/multi`);
        if (!r.ok) {
          const t = await r.text();
          if (!cancelledRef.current) { setError(t.slice(0, 100)); setMulti([]); }
          return;
        }
        const d = await r.json();
        if (!cancelledRef.current) { setMulti(d.panels || []); setError(""); }
      } else {
        const r = await fetch(`${apiBase}/workbench/chem/session/${encodeURIComponent(sessionId)}/pareto?x=${xAxis}&y=${yAxis}`);
        if (!r.ok) {
          const t = await r.text();
          if (!cancelledRef.current) { setError(t.slice(0, 100)); setData(null); }
          return;
        }
        const d: ParetoResult = await r.json();
        if (!cancelledRef.current) { setData(d); setError(""); }
      }
    } catch (e: any) {
      if (!cancelledRef.current) setError(String(e?.message ?? e));
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, [apiBase, sessionId, xAxis, yAxis, mode]);

  // ── Refresh on deps change + adaptive polling.
  //   Fast (1.5s) while candidates are unscored — backend auto-scores
  //   each new molecule so we want to surface results immediately.
  //   Slow (8s) once all candidates have scores.
  useEffect(() => {
    const ref = { current: false };
    refresh(ref);
    const hasUnscored = (data?.stats.n_total ?? 0) > (data?.stats.n_with_scores ?? 0);
    const interval = hasUnscored ? 1500 : 8000;
    const t = setInterval(() => refresh(ref), interval);
    return () => { ref.current = true; clearInterval(t); };
  }, [refresh, data?.stats.n_total, data?.stats.n_with_scores]);

  // ── Score missing
  const handleScoreMissing = async () => {
    if (!sessionId) return;
    setScoringLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/chem/session/${encodeURIComponent(sessionId)}/pareto/score-missing`, {
        method: "POST",
      });
      if (!r.ok) return;
      const d = await r.json();
      setScoringStatus({ n_missing: d.n_missing, n_enqueued: d.n_enqueued });
      setTimeout(() => refresh({ current: false }), 1200);
    } finally { setScoringLoading(false); }
  };

  // ── Explain a point
  const handleExplain = async (cid: string) => {
    if (!sessionId) return;
    setPinnedId(cid);
    setExplainLoading(true);
    setExplainResult(null);
    try {
      const r = await fetch(`${apiBase}/workbench/chem/session/${encodeURIComponent(sessionId)}/pareto/explain`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_id: cid, x_axis: xAxis, y_axis: yAxis }),
      });
      if (!r.ok) return;
      const d = await r.json();
      setExplainResult({ candidate_id: cid, explanation: d.explanation });
    } finally { setExplainLoading(false); }
  };

  // ── Compare action
  const togglePick = (id: string) => {
    setComparePicks((cur) => {
      if (cur.includes(id)) return cur.filter((x) => x !== id);
      if (cur.length >= 5) return cur;
      return [...cur, id];
    });
  };

  const runCompare = async () => {
    if (!sessionId || comparePicks.length < 2) return;
    setCompareLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/chem/session/${encodeURIComponent(sessionId)}/pareto/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ candidate_ids: comparePicks }),
      });
      if (!r.ok) return;
      const d = await r.json();
      setCompareRows(d.rows || []);
      setCompareWinners(d.winners || {});
    } finally { setCompareLoading(false); }
  };

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "linear-gradient(180deg, rgba(248,247,255,1) 0%, rgba(243,241,253,1) 100%)",
      overflow: "hidden",
      fontFamily: "var(--lys-font-body)",
    }}>
      {/* ── Header — click to collapse */}
      <div
        onClick={() => setHeaderOpen((o) => !o)}
        style={{
          padding: "6px 10px",
          fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)", letterSpacing: "0.06em",
          textTransform: "uppercase",
          borderBottom: "1px solid rgba(0,0,0,0.04)",
          display: "flex", alignItems: "center", gap: 6,
          cursor: "pointer", userSelect: "none",
          background: LAV.bg,
          backdropFilter: "blur(10px)",
        }}>
        <Activity size={11} style={{ color: LAV.fg }} />
        <span>pareto lab</span>
        {data && mode !== "matrix" && (
          <>
            <Pill bg={LAV.bg} border={LAV.border} fg={LAV.fgDeep} text={`${data.stats.n_total} cand`} />
            <Pill bg={GREEN.bg} border={GREEN.border} fg={GREEN.fg}
                  text={`${data.stats.n_pareto} on frontier`} bold />
            {data.stats.n_total > data.stats.n_with_scores && (
              <Pill bg={AMBER.bg} border={AMBER.border} fg={AMBER.fg}
                    text={`${data.stats.n_total - data.stats.n_with_scores} unscored`} />
            )}
          </>
        )}
        {mode === "matrix" && multi.length > 0 && (
          <Pill bg={LAV.bg} border={LAV.border} fg={LAV.fgDeep} text={`${multi.length} panels`} />
        )}
        <span style={{ flex: 1 }} />
        {loading && <RefreshCw size={11} style={{ animation: "spin 1s linear infinite", color: LAV.fg }} />}
        <ChevronDown size={11} style={{
          color: "var(--lys-text-faint)",
          transform: headerOpen ? "rotate(0deg)" : "rotate(-90deg)",
          transition: "transform 150ms",
        }} />
      </div>

      {!headerOpen ? null : (
        <>
          {/* ── Mode tabs + actions */}
          <div style={{
            padding: "4px 8px", display: "flex", gap: 4, alignItems: "center", flexWrap: "wrap",
            borderBottom: "1px solid rgba(0,0,0,0.04)",
            background: "rgba(255,255,255,0.4)",
          }}>
            <ModeTab active={mode === "scatter"} onClick={() => setMode("scatter")}
                     icon={<Target size={10} />} label="scatter" />
            <ModeTab active={mode === "matrix"} onClick={() => setMode("matrix")}
                     icon={<Grid3x3 size={10} />} label="matrix" />
            <ModeTab active={mode === "compare"} onClick={() => setMode("compare")}
                     icon={<Layers size={10} />} label="compare" />
            <span style={{ flex: 1 }} />
            {data && data.stats.n_total > data.stats.n_with_scores && (
              <ChipBtn
                onClick={handleScoreMissing}
                icon={<Zap size={10} />}
                label={scoringLoading ? "scoring…" : `score ${data.stats.n_total - data.stats.n_with_scores}`}
              />
            )}
            {sessionId && onAgentMessage && (
              <ChipBtn
                onClick={() => onAgentMessage(`/pareto-summary session=${sessionId}`)}
                icon={<Sparkles size={10} />}
                label="ask agent"
              />
            )}
          </div>

          {/* ── Axis pickers (scatter mode only) */}
          {mode === "scatter" && (
            <div style={{
              padding: "4px 8px", display: "flex", gap: 6, alignItems: "center",
              borderBottom: "1px solid rgba(0,0,0,0.04)",
              fontSize: 9.5, background: "rgba(255,255,255,0.3)",
            }}>
              <span style={{ color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>X:</span>
              <AxisPicker
                axes={axes} value={xAxis} onChange={setXAxis}
                open={xPickerOpen}
                onToggle={() => { setXPickerOpen((o) => !o); setYPickerOpen(false); }}
                onClose={() => setXPickerOpen(false)}
              />
              <span style={{ color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>Y:</span>
              <AxisPicker
                axes={axes} value={yAxis} onChange={setYAxis}
                open={yPickerOpen}
                onToggle={() => { setYPickerOpen((o) => !o); setXPickerOpen(false); }}
                onClose={() => setYPickerOpen(false)}
              />
            </div>
          )}

          {/* ── Score-missing status banner */}
          {scoringStatus && scoringStatus.n_enqueued > 0 && (
            <div style={{
              padding: "4px 10px", fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
              color: AMBER.fg, background: AMBER.bg,
              borderBottom: `1px solid ${AMBER.border}`,
              display: "flex", alignItems: "center", gap: 6,
            }}>
              <Zap size={10} />
              <span>{scoringStatus.n_enqueued} candidate(s) queued for scoring — frontier will refresh shortly</span>
              <span style={{ flex: 1 }} />
              <button onClick={() => setScoringStatus(null)} style={{
                border: 0, background: "transparent", cursor: "pointer",
                color: AMBER.fg, fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
              }}>×</button>
            </div>
          )}

          {/* ── Body */}
          <div style={{ flex: 1, overflow: "auto", padding: 8, position: "relative" }}>
            {!sessionId && <Empty msg="No active session" />}
            {error && <div style={{ padding: 8, color: RED.fg, fontSize: 10 }}>error: {error}</div>}
            {sessionId && mode === "scatter" && data && (
              <ScatterMode
                data={data}
                hoverId={hoverId}
                setHoverId={setHoverId}
                pinnedId={pinnedId}
                setPinnedId={setPinnedId}
                onLoad={onLoad}
                onExplain={handleExplain}
                explainResult={explainResult}
                explainLoading={explainLoading}
              />
            )}
            {sessionId && mode === "matrix" && (
              <MatrixMode panels={multi} onPick={(x, y) => { setMode("scatter"); setXAxis(x); setYAxis(y); }} />
            )}
            {sessionId && mode === "compare" && (
              <CompareMode
                axes={axes}
                data={data}
                comparePicks={comparePicks}
                togglePick={togglePick}
                runCompare={runCompare}
                rows={compareRows}
                winners={compareWinners}
                loading={compareLoading}
                onLoad={onLoad}
              />
            )}
          </div>

          {/* ── Footer legend */}
          <div style={{
            padding: "4px 8px",
            background: "rgba(255,255,255,0.5)",
            borderTop: "1px solid rgba(0,0,0,0.04)",
            fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
            display: "flex", gap: 8, flexWrap: "wrap", alignItems: "center",
          }}>
            <span style={{ color: GREEN.fg, fontWeight: 700 }}>green halo</span>
            <span>= pareto-optimal</span>
            <span style={{ flex: 1 }} />
            {Object.entries(AGENT_DOT_COLOR).slice(0, 5).map(([role, color]) => (
              <span key={role} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                <span style={{ width: 7, height: 7, borderRadius: 7, background: color, display: "inline-block" }} />
                {role}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────
// SCATTER MODE
// ─────────────────────────────────────────────────────────────────────

function ScatterMode({
  data, hoverId, setHoverId, pinnedId, setPinnedId,
  onLoad, onExplain, explainResult, explainLoading,
}: {
  data: ParetoResult;
  hoverId: string | null;
  setHoverId: (id: string | null) => void;
  pinnedId: string | null;
  setPinnedId: (id: string | null) => void;
  onLoad?: (smiles: string) => void;
  onExplain: (id: string) => void;
  explainResult: { candidate_id: string; explanation: string } | null;
  explainLoading: boolean;
}) {
  const W = 560, H = 320, PAD_L = 40, PAD_R = 12, PAD_T = 10, PAD_B = 28;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;

  const validPts = (data.all_points || []).filter((p) => p.valid && p.x_value !== null && p.y_value !== null);

  const xToPx = (v: number) => PAD_L + v * plotW;
  const yToPx = (v: number) => PAD_T + plotH - v * plotH;

  if (data.stats.n_total === 0) return <Empty msg="No candidates yet — design something first" />;
  if (data.stats.n_with_scores === 0)
    return <Empty msg={`${data.stats.n_total} candidate(s) but none have scores on these axes yet — try "score N" above`} />;

  const activeId = pinnedId ?? hoverId;
  const activePt = activeId ? validPts.find((p) => p.candidate_id === activeId) : null;

  // Single-candidate mode — a scatter with one point looks empty. Render
  // a rich detail panel underneath instead, showing SMILES + composite
  // gauge + per-axis breakdown + guidance to design more candidates.
  const isSingle = validPts.length === 1;
  const sole = isSingle ? validPts[0] : null;

  return (
    <>
      <svg width={W} height={H} style={{ display: "block", maxWidth: "100%" }}>
        {/* Background gridlines */}
        {[0, 0.25, 0.5, 0.75, 1].map((g) => (
          <g key={`g-${g}`}>
            <line x1={xToPx(g)} y1={PAD_T} x2={xToPx(g)} y2={PAD_T + plotH}
                  stroke="rgba(124,99,216,0.08)" strokeWidth={1} />
            <line x1={PAD_L} y1={yToPx(g)} x2={PAD_L + plotW} y2={yToPx(g)}
                  stroke="rgba(124,99,216,0.08)" strokeWidth={1} />
            <text x={xToPx(g)} y={PAD_T + plotH + 14}
                  textAnchor="middle" fontSize={8.5}
                  fill="var(--lys-text-faint)" fontFamily="var(--lys-font-mono)">{g}</text>
            <text x={PAD_L - 6} y={yToPx(g) + 3}
                  textAnchor="end" fontSize={8.5}
                  fill="var(--lys-text-faint)" fontFamily="var(--lys-font-mono)">{g}</text>
          </g>
        ))}

        {/* Axis labels */}
        <text x={PAD_L + plotW / 2} y={PAD_T + plotH + 26}
              textAnchor="middle" fontSize={10}
              fill={LAV.fgDeep} fontFamily="var(--lys-font-mono)" fontWeight={700}>
          {data.x_axis_meta.label}
        </text>
        <text x={12} y={PAD_T + plotH / 2}
              textAnchor="middle" fontSize={10}
              fill={LAV.fgDeep} fontFamily="var(--lys-font-mono)" fontWeight={700}
              transform={`rotate(-90, 12, ${PAD_T + plotH / 2})`}>
          {data.y_axis_meta.label}
        </text>

        {/* Pareto frontier line */}
        {(() => {
          const paretoPts = validPts.filter((p) => p.on_pareto)
            .sort((a, b) => (a.x_value! - b.x_value!));
          if (paretoPts.length < 2) return null;
          const path = paretoPts.map((p, i) =>
            `${i === 0 ? "M" : "L"} ${xToPx(p.x_value!)} ${yToPx(p.y_value!)}`
          ).join(" ");
          return (
            <path d={path} stroke={GREEN.fg} strokeWidth={1.5}
                  strokeDasharray="4,2" fill="none" opacity={0.55} />
          );
        })()}

        {/* Points */}
        {validPts.map((p) => {
          const cx = xToPx(p.x_value!);
          const cy = yToPx(p.y_value!);
          const isPareto = p.on_pareto;
          const isHover = p.candidate_id === hoverId;
          const isPinned = p.candidate_id === pinnedId;
          const c = AGENT_DOT_COLOR[(p.created_by || "agent").toLowerCase()] ?? "#6b7280";
          const r = isPareto ? 6 : 4;
          return (
            <g key={p.candidate_id}>
              {isPareto && <circle cx={cx} cy={cy} r={11} fill="rgba(16,185,129,0.18)" />}
              {isPinned && <circle cx={cx} cy={cy} r={13} fill="none"
                                   stroke={LAV.fgDeep} strokeWidth={2} strokeDasharray="2,2" />}
              <circle
                cx={cx} cy={cy} r={(isHover || isPinned) ? r + 2 : r}
                fill={c}
                stroke={isPareto ? GREEN.fg : "white"}
                strokeWidth={isPareto ? 2 : 1}
                onMouseEnter={() => setHoverId(p.candidate_id)}
                onMouseLeave={() => setHoverId(null)}
                onClick={() => setPinnedId(isPinned ? null : p.candidate_id)}
                style={{ cursor: "pointer" }}
              />
            </g>
          );
        })}
      </svg>

      {/* Hover/pinned detail */}
      {activePt && (
        <div style={{
          position: "absolute", top: 10, right: 10,
          padding: "6px 10px",
          background: LAV.bg,
          backdropFilter: "blur(10px)",
          border: `1px solid ${LAV.borderStrong}`,
          borderRadius: 5, fontFamily: "var(--lys-font-body)",
          fontSize: 9.5, maxWidth: 260,
          boxShadow: "0 4px 12px rgba(96,65,208,0.10)",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 2 }}>
            {activePt.on_pareto && (
              <span style={{
                padding: "1px 5px", borderRadius: 999, fontSize: 8.5,
                background: GREEN.fg, color: "white", fontWeight: 800,
                fontFamily: "var(--lys-font-mono)",
              }}>PARETO</span>
            )}
            <span style={{
              color: AGENT_DOT_COLOR[activePt.created_by] ?? "#6b7280",
              fontWeight: 700, fontFamily: "var(--lys-font-mono)",
            }}>{activePt.created_by}</span>
            <span style={{ flex: 1 }} />
            <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 8.5,
                           color: "var(--lys-text-faint)" }}>
              {activePt.candidate_id.slice(0, 6)}
            </span>
          </div>
          <div style={{
            marginTop: 2, color: "var(--lys-text-dim)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            fontFamily: "var(--lys-font-mono)", fontSize: 9,
          }}>
            {(activePt.smiles || "").slice(0, 50)}
          </div>
          <div style={{ marginTop: 3, fontSize: 9.5, fontFamily: "var(--lys-font-mono)" }}>
            <span>{data.x_axis_meta.label}: <strong style={{ color: LAV.fgDeep }}>{activePt.x_value?.toFixed(3)}</strong></span>
            <br />
            <span>{data.y_axis_meta.label}: <strong style={{ color: LAV.fgDeep }}>{activePt.y_value?.toFixed(3)}</strong></span>
          </div>
          <div style={{ marginTop: 5, display: "flex", gap: 4 }}>
            <button onClick={() => activePt.smiles && onLoad?.(activePt.smiles)}
                    style={ctaBtnStyle(false)}>
              load
            </button>
            <button onClick={() => onExplain(activePt.candidate_id)}
                    disabled={explainLoading}
                    style={ctaBtnStyle(explainLoading)}>
              {explainLoading ? "…" : "explain"}
            </button>
          </div>
          {explainResult && explainResult.candidate_id === activePt.candidate_id && (
            <div style={{
              marginTop: 6, padding: "5px 7px",
              background: "rgba(255,255,255,0.7)",
              border: `1px solid ${LAV.border}`,
              borderRadius: 4,
              fontSize: 9.5, lineHeight: 1.45, color: "var(--lys-text)",
            }}>
              {explainResult.explanation}
            </div>
          )}
        </div>
      )}

      {/* SINGLE-CANDIDATE PANEL — a scatter with one point looks empty.
          Surface a rich detail block below: SMILES + composite gauge +
          full axis breakdown + a CTA encouraging the user to design more
          so the frontier becomes meaningful. */}
      {isSingle && sole && (
        <SingleCandidatePanel point={sole} onLoad={onLoad} onExplain={onExplain}
          explainResult={explainResult} explainLoading={explainLoading} />
      )}
    </>
  );
}


/** Single-candidate detail panel — replaces the empty-scatter feeling
 *  when only 1 candidate exists. Shows the candidate's full identity +
 *  composite gauge + per-axis bars + guidance to design more. */
function SingleCandidatePanel({
  point, onLoad, onExplain, explainResult, explainLoading,
}: {
  point: PointDot;
  onLoad?: (smiles: string) => void;
  onExplain: (id: string) => void;
  explainResult: { candidate_id: string; explanation: string } | null;
  explainLoading: boolean;
}) {
  const composite = ((point.x_value ?? 0) + (point.y_value ?? 0)) / 2;
  const tier = composite >= 0.7 ? GREEN : composite >= 0.4 ? AMBER : RED;
  const c = AGENT_DOT_COLOR[(point.created_by || "agent").toLowerCase()] ?? "#6b7280";
  return (
    <div style={{
      marginTop: 12, padding: "10px 12px",
      background: LAV.bg,
      border: `1px solid ${LAV.borderStrong}`,
      borderLeft: `3px solid ${LAV.fgDeep}`,
      borderRadius: 5,
      display: "flex", flexDirection: "column", gap: 8,
      backdropFilter: "blur(10px)",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{
          fontFamily: "var(--lys-font-mono)", fontWeight: 800,
          fontSize: 12, color: LAV.fgDeep,
        }}>only candidate · {point.candidate_id.slice(0, 8)}</span>
        <span style={{
          padding: "1px 6px", borderRadius: 999,
          background: c, color: "white", fontWeight: 700, fontSize: 9,
          fontFamily: "var(--lys-font-mono)",
        }}>{point.created_by || "?"}</span>
        {point.on_pareto && (
          <span style={{
            padding: "1px 6px", borderRadius: 999,
            background: GREEN.fg, color: "white", fontWeight: 800, fontSize: 9,
            fontFamily: "var(--lys-font-mono)",
          }}>PARETO</span>
        )}
        <span style={{ flex: 1 }} />
        <button onClick={() => point.smiles && onLoad?.(point.smiles)}
          style={ctaBtnStyle(false)}>load</button>
        <button onClick={() => onExplain(point.candidate_id)}
          disabled={explainLoading}
          style={ctaBtnStyle(explainLoading)}>
          {explainLoading ? "…" : "explain"}
        </button>
      </div>

      {/* Composite gauge */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)", letterSpacing: "0.06em",
            textTransform: "uppercase", fontWeight: 700, marginBottom: 2,
          }}>{`avg of ${point.x_value?.toFixed(2)} and ${point.y_value?.toFixed(2)}`}</div>
          <div style={{
            height: 10, borderRadius: 5,
            background: "rgba(0,0,0,0.06)", overflow: "hidden",
          }}>
            <div style={{
              width: `${Math.round(composite * 100)}%`, height: "100%",
              background: tier.fg, opacity: 0.85,
            }} />
          </div>
        </div>
        <div style={{
          fontFamily: "var(--lys-font-body)", fontSize: 22, fontWeight: 700,
          color: tier.fg, lineHeight: 1,
        }}>{(composite * 100).toFixed(0)}<span style={{ fontSize: 11, opacity: 0.6 }}>%</span></div>
      </div>

      {/* SMILES */}
      <div style={{
        fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
        color: "var(--lys-text-dim)", lineHeight: 1.4,
        wordBreak: "break-all",
        padding: "5px 7px", background: "rgba(255,255,255,0.55)",
        border: `1px solid ${LAV.border}`, borderRadius: 4,
      }}>{point.smiles}</div>

      {/* Per-axis values shown */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6,
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      }}>
        <div style={{
          padding: "4px 7px", background: "rgba(255,255,255,0.55)",
          border: `1px solid ${LAV.border}`, borderRadius: 4,
          display: "flex", justifyContent: "space-between", alignItems: "baseline",
        }}>
          <span style={{ color: "var(--lys-text-faint)" }}>X axis</span>
          <span style={{ fontWeight: 700, color: LAV.fgDeep }}>{point.x_value?.toFixed(3)}</span>
        </div>
        <div style={{
          padding: "4px 7px", background: "rgba(255,255,255,0.55)",
          border: `1px solid ${LAV.border}`, borderRadius: 4,
          display: "flex", justifyContent: "space-between", alignItems: "baseline",
        }}>
          <span style={{ color: "var(--lys-text-faint)" }}>Y axis</span>
          <span style={{ fontWeight: 700, color: LAV.fgDeep }}>{point.y_value?.toFixed(3)}</span>
        </div>
      </div>

      {explainResult && explainResult.candidate_id === point.candidate_id && (
        <div style={{
          padding: "6px 8px",
          background: "rgba(255,255,255,0.7)",
          border: `1px solid ${LAV.border}`,
          borderRadius: 4,
          fontSize: 9.5, lineHeight: 1.45, color: "var(--lys-text)",
        }}>
          {explainResult.explanation}
        </div>
      )}

      {/* Guidance */}
      <div style={{
        padding: "6px 8px",
        background: AMBER.bg,
        border: `1px solid ${AMBER.border}`,
        borderLeft: `3px solid ${AMBER.fg}`,
        borderRadius: 4,
        fontSize: 9.5, color: "var(--lys-text-dim)", lineHeight: 1.45,
      }}>
        <strong style={{ color: AMBER.fg, fontFamily: "var(--lys-font-mono)" }}>
          frontier needs ≥2 candidates
        </strong>{" "}
        — design or load one more candidate to see real Pareto trade-offs
        between objectives. Type{" "}
        <code style={{
          fontFamily: "var(--lys-font-mono)", fontSize: 9,
          background: "rgba(0,0,0,0.05)", padding: "1px 4px", borderRadius: 3,
        }}>/design 1</code>{" "}
        in the chat or pick a scaffold from the Library.
      </div>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────
// MATRIX MODE
// ─────────────────────────────────────────────────────────────────────

function MatrixMode({ panels, onPick }: {
  panels: MultiPanel[];
  onPick: (x: string, y: string) => void;
}) {
  if (panels.length === 0) return <Empty msg="Loading multi-axis matrix…" />;
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, height: "100%",
    }}>
      {panels.slice(0, 4).map((panel) => (
        <MiniScatter key={`${panel.x}_${panel.y}`} panel={panel} onPick={onPick} />
      ))}
    </div>
  );
}

function MiniScatter({ panel, onPick }: {
  panel: MultiPanel;
  onPick: (x: string, y: string) => void;
}) {
  const W = 260, H = 200, PAD = 18;
  const plotW = W - PAD * 2;
  const plotH = H - PAD * 2;
  const validPts = (panel.all_points || []).filter((p) => p.valid && p.x_value !== null && p.y_value !== null);
  const xToPx = (v: number) => PAD + v * plotW;
  const yToPx = (v: number) => PAD + plotH - v * plotH;

  return (
    <div style={{
      background: LAV.bg, border: `1px solid ${LAV.border}`,
      borderRadius: 4, padding: 6,
      backdropFilter: "blur(10px)",
      cursor: "pointer",
    }}
      onClick={() => onPick(panel.x, panel.y)}
      title="click to open in scatter view"
    >
      <div style={{
        fontSize: 8.5, fontFamily: "var(--lys-font-mono)", fontWeight: 700,
        color: LAV.fgDeep, marginBottom: 2, letterSpacing: "0.04em",
        textTransform: "uppercase", textAlign: "center",
      }}>
        {panel.x_axis_meta.label} × {panel.y_axis_meta.label}
        <span style={{ marginLeft: 5, color: GREEN.fg }}>({panel.stats.n_pareto})</span>
      </div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto" }}>
        {/* Frame */}
        <rect x={PAD} y={PAD} width={plotW} height={plotH}
              fill="rgba(255,255,255,0.5)" stroke="rgba(124,99,216,0.15)" />
        {/* Frontier */}
        {(() => {
          const ppts = validPts.filter((p) => p.on_pareto).sort((a, b) => (a.x_value! - b.x_value!));
          if (ppts.length < 2) return null;
          const path = ppts.map((p, i) =>
            `${i === 0 ? "M" : "L"} ${xToPx(p.x_value!)} ${yToPx(p.y_value!)}`
          ).join(" ");
          return <path d={path} stroke={GREEN.fg} strokeWidth={1.2}
                       strokeDasharray="3,2" fill="none" opacity={0.55} />;
        })()}
        {validPts.map((p) => {
          const cx = xToPx(p.x_value!);
          const cy = yToPx(p.y_value!);
          const c = AGENT_DOT_COLOR[(p.created_by || "agent").toLowerCase()] ?? "#6b7280";
          const r = p.on_pareto ? 4 : 2.5;
          return (
            <g key={p.candidate_id}>
              {p.on_pareto && <circle cx={cx} cy={cy} r={7} fill="rgba(16,185,129,0.22)" />}
              <circle cx={cx} cy={cy} r={r} fill={c}
                      stroke={p.on_pareto ? GREEN.fg : "white"} strokeWidth={p.on_pareto ? 1.2 : 0.8} />
            </g>
          );
        })}
      </svg>
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────
// COMPARE MODE
// ─────────────────────────────────────────────────────────────────────

function CompareMode({
  axes, data, comparePicks, togglePick, runCompare,
  rows, winners, loading, onLoad,
}: {
  axes: Record<string, AxisMeta>;
  data: ParetoResult | null;
  comparePicks: string[];
  togglePick: (id: string) => void;
  runCompare: () => void;
  rows: CompareRow[];
  winners: CompareWinners;
  loading: boolean;
  onLoad?: (smiles: string) => void;
}) {
  const allPoints = data?.all_points || [];
  if (allPoints.length === 0) {
    return <Empty msg="No candidates in this session yet" />;
  }
  const axisOrder = Object.keys(axes);

  return (
    <>
      <SectionLabel text="Pick 2-5 candidates to compare across all axes" />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
        {allPoints.map((p) => {
          const sel = comparePicks.includes(p.candidate_id);
          const c = AGENT_DOT_COLOR[(p.created_by || "agent").toLowerCase()] ?? "#6b7280";
          return (
            <button
              key={p.candidate_id}
              onClick={() => togglePick(p.candidate_id)}
              style={{
                padding: "2px 8px", height: 22,
                fontSize: 9.5, fontWeight: 500, fontFamily: "var(--lys-font-body)",
                borderRadius: 4, cursor: "pointer",
                background: sel ? LAV.bgStrong : "rgba(255,255,255,0.6)",
                border: `1px solid ${sel ? LAV.borderStrong : LAV.border}`,
                color: sel ? LAV.fgDeep : "var(--lys-text)",
                display: "inline-flex", alignItems: "center", gap: 5,
                backdropFilter: "blur(10px)",
              }}>
              <span style={{ width: 6, height: 6, borderRadius: 6, background: c, display: "inline-block" }} />
              <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 700 }}>{p.candidate_id.slice(0, 6)}</span>
              {p.on_pareto && (
                <span style={{
                  padding: "0 3px", borderRadius: 2, fontSize: 8,
                  background: GREEN.fg, color: "white", fontWeight: 700,
                  fontFamily: "var(--lys-font-mono)",
                }}>P</span>
              )}
            </button>
          );
        })}
      </div>
      <button
        onClick={runCompare}
        disabled={comparePicks.length < 2 || loading}
        style={{
          padding: "2px 10px", height: 22,
          fontSize: 9.5, fontWeight: 600, fontFamily: "var(--lys-font-body)",
          borderRadius: 4,
          cursor: comparePicks.length < 2 ? "not-allowed" : "pointer",
          background: comparePicks.length < 2 ? "rgba(0,0,0,0.04)" : LAV.fgDeep,
          color: comparePicks.length < 2 ? "var(--lys-text-faint)" : "white",
          border: "none",
          marginBottom: 8,
        }}>
        {loading ? "Comparing…" : `Compare ${comparePicks.length}`}
      </button>

      {rows.length > 0 && (
        <div style={{ overflowX: "auto", marginTop: 4 }}>
          <table style={{
            width: "100%", borderCollapse: "collapse",
            fontSize: 9.5, fontFamily: "var(--lys-font-body)",
          }}>
            <thead>
              <tr>
                <th style={cellHead}>axis</th>
                {rows.map((r) => (
                  <th key={r.id} style={{ ...cellHead, textAlign: "center" }}>
                    <div style={{
                      display: "inline-flex", flexDirection: "column", alignItems: "center", gap: 2,
                    }}>
                      <span style={{
                        fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                        color: LAV.fgDeep,
                      }}>{r.id.slice(0, 6)}</span>
                      <span style={{ fontSize: 8.5, fontWeight: 500, color: "var(--lys-text-faint)" }}>
                        {r.created_by || "?"}
                      </span>
                      {r.smiles && onLoad && (
                        <button
                          onClick={() => onLoad(r.smiles!)}
                          style={{
                            padding: "1px 5px", fontSize: 8,
                            background: LAV.bgStrong, border: `1px solid ${LAV.border}`,
                            borderRadius: 3, color: LAV.fgDeep, cursor: "pointer",
                            fontFamily: "var(--lys-font-body)",
                          }}>load</button>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {axisOrder.map((axisName) => {
                const meta = axes[axisName];
                const winnerId = winners[axisName];
                return (
                  <tr key={axisName}>
                    <td style={{ ...cellBody, fontWeight: 600 }}>
                      {meta?.label ?? axisName}
                    </td>
                    {rows.map((r) => {
                      const v = r.axes?.[axisName] ?? null;
                      const isWinner = r.id === winnerId;
                      return (
                        <td key={r.id} style={{
                          ...cellBody, textAlign: "center",
                          fontFamily: "var(--lys-font-mono)",
                          fontWeight: isWinner ? 800 : 500,
                          color: isWinner ? GREEN.fg : "var(--lys-text)",
                          background: isWinner ? GREEN.bg : "transparent",
                        }}>
                          {v == null ? "—" : v.toFixed(3)}
                          {isWinner && <span style={{ marginLeft: 3 }}>★</span>}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}
              <tr>
                <td style={{ ...cellBody, fontWeight: 700, color: LAV.fgDeep }}>composite</td>
                {rows.map((r) => (
                  <td key={r.id} style={{
                    ...cellBody, textAlign: "center",
                    fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                    color: LAV.fgDeep,
                  }}>
                    {r.composite == null ? "—" : r.composite.toFixed(3)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}


// ─────────────────────────────────────────────────────────────────────
// AxisPicker — lavender-glass restyle
// ─────────────────────────────────────────────────────────────────────

function AxisPicker({ axes, value, onChange, open, onToggle, onClose }: {
  axes: Record<string, AxisMeta>;
  value: string;
  onChange: (v: string) => void;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
}) {
  const meta = axes[value];
  return (
    <div style={{ position: "relative" }}>
      <button
        type="button"
        onClick={onToggle}
        style={{
          padding: "2px 7px", height: 22,
          background: LAV.bg, border: `1px solid ${LAV.border}`,
          borderRadius: 4, cursor: "pointer",
          fontFamily: "var(--lys-font-body)", fontSize: 9.5, fontWeight: 500,
          display: "inline-flex", alignItems: "center", gap: 4,
          color: LAV.fgDeep,
          backdropFilter: "blur(10px)",
        }}>
        <span style={{ fontWeight: 600 }}>{meta?.label ?? value}</span>
        <ChevronDown size={10} />
      </button>
      {open && (
        <>
          <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 70 }} />
          <div style={{
            position: "absolute", top: "100%", left: 0, marginTop: 2,
            background: "rgba(252,251,255,0.97)",
            backdropFilter: "blur(10px)",
            border: `1px solid ${LAV.borderStrong}`,
            borderRadius: 5, boxShadow: "0 8px 20px rgba(96,65,208,0.18)",
            minWidth: 220, maxHeight: 280, overflowY: "auto",
            zIndex: 71, fontFamily: "var(--lys-font-body)",
          }}>
            {Object.entries(axes).map(([k, m]) => (
              <button
                key={k}
                type="button"
                onClick={() => { onChange(k); onClose(); }}
                style={{
                  display: "block", width: "100%", textAlign: "left",
                  padding: "5px 8px", border: 0,
                  background: k === value ? LAV.bgStrong : "transparent",
                  cursor: "pointer", fontSize: 10,
                  borderLeft: `3px solid ${k === value ? LAV.fgDeep : "transparent"}`,
                }}>
                <div style={{ fontWeight: k === value ? 700 : 500, color: k === value ? LAV.fgDeep : "var(--lys-text)" }}>{m.label}</div>
                <div style={{ fontSize: 8.5, color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>
                  {k} · {m.unit}
                </div>
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────
// Tiny atoms
// ─────────────────────────────────────────────────────────────────────

function Pill({ bg, border, fg, text, bold }:
  { bg: string; border: string; fg: string; text: string; bold?: boolean }) {
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 999,
      background: bg, border: `1px solid ${border}`,
      color: fg, fontWeight: bold ? 700 : 600, fontSize: 9,
      fontFamily: "var(--lys-font-mono)",
    }}>{text}</span>
  );
}

function ChipBtn({ onClick, icon, label }: { onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "2px 7px", height: 22,
        fontSize: 9.5, fontWeight: 500, fontFamily: "var(--lys-font-body)",
        borderRadius: 4, cursor: "pointer",
        background: LAV.bgStrong, border: `1px solid ${LAV.borderStrong}`,
        color: LAV.fgDeep,
        display: "inline-flex", alignItems: "center", gap: 4,
        backdropFilter: "blur(10px)",
      }}>
      {icon}{label}
    </button>
  );
}

function ModeTab({ active, onClick, icon, label }:
  { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "2px 7px", height: 22,
        fontSize: 9.5, fontWeight: 500, fontFamily: "var(--lys-font-body)",
        borderRadius: 4, cursor: "pointer",
        background: active ? LAV.bgStrong : "transparent",
        border: `1px solid ${active ? LAV.borderStrong : "transparent"}`,
        color: active ? LAV.fgDeep : "var(--lys-text-faint)",
        display: "inline-flex", alignItems: "center", gap: 4,
        textTransform: "uppercase", letterSpacing: "0.04em",
      }}>
      {icon}{label}
    </button>
  );
}

function SectionLabel({ text, mt = 0 }: { text: string; mt?: number }) {
  return (
    <div style={{
      fontSize: 8.5, color: "var(--lys-text-faint)",
      fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
      textTransform: "uppercase", fontWeight: 700,
      marginTop: mt, marginBottom: 4,
    }}>{text}</div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{
      padding: "30px 10px", textAlign: "center",
      color: "var(--lys-text-faint)", fontSize: 10.5,
      fontFamily: "var(--lys-font-mono)",
    }}>{msg}</div>
  );
}

const cellHead: React.CSSProperties = {
  padding: "4px 6px", textAlign: "left",
  fontSize: 9, color: "var(--lys-text-faint)",
  fontFamily: "var(--lys-font-mono)", fontWeight: 700,
  letterSpacing: "0.04em", textTransform: "uppercase",
  borderBottom: `1px solid ${LAV.border}`,
};

const cellBody: React.CSSProperties = {
  padding: "3px 6px",
  fontSize: 9.5,
  borderBottom: "1px solid rgba(124,99,216,0.06)",
};

function ctaBtnStyle(disabled: boolean): React.CSSProperties {
  return {
    padding: "2px 7px", height: 20,
    fontSize: 9, fontWeight: 600, fontFamily: "var(--lys-font-body)",
    borderRadius: 3, cursor: disabled ? "wait" : "pointer",
    background: LAV.bgStrong, border: `1px solid ${LAV.borderStrong}`,
    color: LAV.fgDeep,
    opacity: disabled ? 0.6 : 1,
  };
}

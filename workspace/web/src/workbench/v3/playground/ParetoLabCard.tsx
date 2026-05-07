/**
 * ParetoLabCard — Service 3: Multi-Candidate Pareto Lab.
 *
 * Renders all candidates from the current session as a scatter plot, with
 * Pareto-optimal points highlighted. Lets the user (and the agent — via
 * pareto_summary tool) detect "we have N dominant candidates already,
 * stop searching" or "no new Pareto points in 5 iterations, BRANCH".
 *
 * Axis selection: dropdown for X and Y. Defaults: predicted_mic vs
 * composite_reward (inverted MIC-likeness so higher = lower MIC = better).
 * Click any point → loadSmilesIntoCanvas via the parent's onLoad handler.
 *
 * No external charting library — pure SVG scatter for the build budget.
 */
import { useEffect, useState, useMemo } from "react";
import { Activity, RefreshCw, ChevronDown } from "lucide-react";

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

interface AxesResp { axes: Record<string, AxisMeta> }

interface Props {
  apiBase: string;
  sessionId: string | null;
  onLoad?: (smiles: string) => void;
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

export function ParetoLabCard({ apiBase, sessionId, onLoad }: Props) {
  const [axes, setAxes] = useState<Record<string, AxisMeta>>({});
  const [xAxis, setXAxis] = useState<string>("predicted_mic");
  const [yAxis, setYAxis] = useState<string>("composite_reward");
  const [data, setData] = useState<ParetoResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hoverId, setHoverId] = useState<string | null>(null);
  const [xPickerOpen, setXPickerOpen] = useState(false);
  const [yPickerOpen, setYPickerOpen] = useState(false);

  // Fetch axis registry once
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

  // Fetch Pareto on session/axis change. Polls every 8s while session active.
  const refresh = useMemo(() => async (cancelledRef: { current: boolean }) => {
    if (!sessionId) { setData(null); return; }
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/chem/session/${encodeURIComponent(sessionId)}/pareto?x=${xAxis}&y=${yAxis}`);
      if (!r.ok) {
        const t = await r.text();
        if (!cancelledRef.current) { setError(t.slice(0, 100)); setData(null); }
        return;
      }
      const d: ParetoResult = await r.json();
      if (!cancelledRef.current) { setData(d); setError(""); }
    } catch (e: any) {
      if (!cancelledRef.current) setError(String(e?.message ?? e));
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, [apiBase, sessionId, xAxis, yAxis]);

  useEffect(() => {
    const ref = { current: false };
    refresh(ref);
    const t = setInterval(() => refresh(ref), 8000);
    return () => { ref.current = true; clearInterval(t); };
  }, [refresh]);

  // Plot dimensions
  const W = 560;
  const H = 320;
  const PAD_L = 40;
  const PAD_R = 12;
  const PAD_T = 10;
  const PAD_B = 28;
  const plotW = W - PAD_L - PAD_R;
  const plotH = H - PAD_T - PAD_B;

  const validPts = useMemo(() => (data?.all_points || []).filter((p) => p.valid && p.x_value !== null && p.y_value !== null), [data]);

  const xMin = 0;
  const xMax = 1;  // axes default to 0-1 normalized
  const yMin = 0;
  const yMax = 1;

  const xToPx = (v: number) => PAD_L + ((v - xMin) / (xMax - xMin)) * plotW;
  const yToPx = (v: number) => PAD_T + plotH - ((v - yMin) / (yMax - yMin)) * plotH;

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "5px 10px",
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.06em",
        textTransform: "uppercase",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <Activity size={11} style={{ color: "#10b981" }} />
        <span>Pareto lab · {data?.stats.n_total ?? 0} candidates · {data?.stats.n_pareto ?? 0} on frontier</span>
        <span style={{ flex: 1 }} />
        {loading && <RefreshCw size={11} style={{ animation: "spin 1s linear infinite" }} />}
      </div>

      {/* Axis pickers */}
      <div style={{
        padding: "4px 8px",
        display: "flex", gap: 8, alignItems: "center",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      }}>
        <span style={{ color: "var(--lys-text-faint)" }}>X:</span>
        <AxisPicker
          axes={axes}
          value={xAxis}
          onChange={setXAxis}
          open={xPickerOpen}
          onToggle={() => { setXPickerOpen((o) => !o); setYPickerOpen(false); }}
          onClose={() => setXPickerOpen(false)}
        />
        <span style={{ color: "var(--lys-text-faint)" }}>Y:</span>
        <AxisPicker
          axes={axes}
          value={yAxis}
          onChange={setYAxis}
          open={yPickerOpen}
          onToggle={() => { setYPickerOpen((o) => !o); setXPickerOpen(false); }}
          onClose={() => setYPickerOpen(false)}
        />
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 8, position: "relative" }}>
        {!sessionId && <Empty msg="No active session" />}
        {sessionId && data && data.stats.n_total === 0 && <Empty msg="No candidates yet — design something first" />}
        {sessionId && data && data.stats.n_with_scores === 0 && data.stats.n_total > 0 && (
          <Empty msg={`${data.stats.n_total} candidate(s) but none have scores on these axes yet`} />
        )}
        {error && <div style={{ padding: 8, color: "#dc2626", fontSize: 10 }}>error: {error}</div>}

        {data && validPts.length > 0 && (
          <>
            <svg width={W} height={H} style={{ display: "block", maxWidth: "100%" }}>
              {/* Background gridlines (every 0.25) */}
              {[0, 0.25, 0.5, 0.75, 1].map((g) => (
                <g key={`g-${g}`}>
                  <line x1={xToPx(g)} y1={PAD_T} x2={xToPx(g)} y2={PAD_T + plotH}
                    stroke="rgba(0,0,0,0.05)" strokeWidth={1} />
                  <line x1={PAD_L} y1={yToPx(g)} x2={PAD_L + plotW} y2={yToPx(g)}
                    stroke="rgba(0,0,0,0.05)" strokeWidth={1} />
                  <text x={xToPx(g)} y={PAD_T + plotH + 14}
                    textAnchor="middle" fontSize={8.5}
                    fill="var(--lys-text-faint)" fontFamily="var(--lys-font-mono)">
                    {g}
                  </text>
                  <text x={PAD_L - 6} y={yToPx(g) + 3}
                    textAnchor="end" fontSize={8.5}
                    fill="var(--lys-text-faint)" fontFamily="var(--lys-font-mono)">
                    {g}
                  </text>
                </g>
              ))}

              {/* Axis labels */}
              <text x={PAD_L + plotW / 2} y={PAD_T + plotH + 26}
                textAnchor="middle" fontSize={10}
                fill="var(--lys-text-dim)" fontFamily="var(--lys-font-mono)" fontWeight={700}>
                {data.x_axis_meta.label}
              </text>
              <text x={12} y={PAD_T + plotH / 2}
                textAnchor="middle" fontSize={10}
                fill="var(--lys-text-dim)" fontFamily="var(--lys-font-mono)" fontWeight={700}
                transform={`rotate(-90, 12, ${PAD_T + plotH / 2})`}>
                {data.y_axis_meta.label}
              </text>

              {/* Pareto frontier line — connect Pareto points sorted by x */}
              {(() => {
                const paretoPts = validPts
                  .filter((p) => p.on_pareto)
                  .sort((a, b) => (a.x_value! - b.x_value!));
                if (paretoPts.length < 2) return null;
                const path = paretoPts.map((p, i) =>
                  `${i === 0 ? "M" : "L"} ${xToPx(p.x_value!)} ${yToPx(p.y_value!)}`
                ).join(" ");
                return (
                  <path d={path} stroke="#10b981" strokeWidth={1.5}
                    strokeDasharray="4,2" fill="none" opacity={0.55} />
                );
              })()}

              {/* Points */}
              {validPts.map((p) => {
                const cx = xToPx(p.x_value!);
                const cy = yToPx(p.y_value!);
                const isPareto = p.on_pareto;
                const isHover = p.candidate_id === hoverId;
                const c = AGENT_DOT_COLOR[(p.created_by || "agent").toLowerCase()] ?? "#6b7280";
                const r = isPareto ? 6 : 4;
                return (
                  <g key={p.candidate_id}>
                    {isPareto && (
                      <circle cx={cx} cy={cy} r={11} fill="rgba(16,185,129,0.18)" />
                    )}
                    <circle
                      cx={cx} cy={cy} r={isHover ? r + 2 : r}
                      fill={c}
                      stroke={isPareto ? "#10b981" : "white"}
                      strokeWidth={isPareto ? 2 : 1}
                      onMouseEnter={() => setHoverId(p.candidate_id)}
                      onMouseLeave={() => setHoverId(null)}
                      onClick={() => p.smiles && onLoad?.(p.smiles)}
                      style={{ cursor: "pointer" }}
                    />
                  </g>
                );
              })}
            </svg>

            {/* Hover detail panel */}
            {hoverId && (() => {
              const p = validPts.find((x) => x.candidate_id === hoverId);
              if (!p) return null;
              return (
                <div style={{
                  position: "absolute", top: 10, right: 10,
                  padding: "5px 10px", background: "rgba(255,255,255,0.96)",
                  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
                  borderRadius: 5, fontFamily: "var(--lys-font-mono)",
                  fontSize: 9.5, maxWidth: 240,
                  boxShadow: "0 4px 12px rgba(15,23,42,0.10)",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    {p.on_pareto && (
                      <span style={{
                        padding: "1px 5px", borderRadius: 999, fontSize: 8,
                        background: "#10b981", color: "white", fontWeight: 800,
                      }}>PARETO</span>
                    )}
                    <span style={{ color: AGENT_DOT_COLOR[p.created_by] ?? "#6b7280", fontWeight: 700 }}>
                      {p.created_by}
                    </span>
                  </div>
                  <div style={{ marginTop: 2, color: "var(--lys-text-dim)",
                    whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {(p.smiles || "").slice(0, 50)}
                  </div>
                  <div style={{ marginTop: 2, fontSize: 9 }}>
                    <span>{data.x_axis_meta.label}: <strong>{p.x_value?.toFixed(3)}</strong></span>
                    {" · "}
                    <span>{data.y_axis_meta.label}: <strong>{p.y_value?.toFixed(3)}</strong></span>
                  </div>
                  <div style={{ marginTop: 2, fontSize: 8, color: "var(--lys-text-faint)" }}>
                    click to load into builder
                  </div>
                </div>
              );
            })()}

            {/* Legend */}
            <div style={{
              marginTop: 6, fontSize: 9, fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-faint)", display: "flex", gap: 8, flexWrap: "wrap",
            }}>
              <span><span style={{ color: "#10b981", fontWeight: 700 }}>green halo</span> = Pareto-optimal</span>
              <span>·</span>
              {Object.entries(AGENT_DOT_COLOR).map(([role, color]) => (
                <span key={role} style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                  <span style={{ width: 7, height: 7, borderRadius: 7, background: color, display: "inline-block" }} />
                  {role}
                </span>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

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
          padding: "2px 8px",
          background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
          borderRadius: 4, cursor: "pointer",
          fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
          display: "inline-flex", alignItems: "center", gap: 4,
          color: "var(--lys-text)",
        }}>
        <span style={{ fontWeight: 700 }}>{meta?.label ?? value}</span>
        <ChevronDown size={10} />
      </button>
      {open && (
        <>
          <div onClick={onClose} style={{ position: "fixed", inset: 0, zIndex: 70 }} />
          <div style={{
            position: "absolute", top: "100%", left: 0, marginTop: 2,
            background: "white",
            border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
            borderRadius: 5, boxShadow: "0 8px 20px rgba(15,23,42,0.18)",
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
                  padding: "5px 8px", border: 0, background: k === value ? "rgba(8,145,178,0.06)" : "transparent",
                  cursor: "pointer", fontSize: 10,
                  borderLeft: `3px solid ${k === value ? "#0891b2" : "transparent"}`,
                }}>
                <div style={{ fontWeight: k === value ? 700 : 500 }}>{m.label}</div>
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

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{
      padding: "30px 10px", textAlign: "center",
      color: "var(--lys-text-faint)", fontSize: 10.5,
      fontFamily: "var(--lys-font-mono)",
    }}>{msg}</div>
  );
}

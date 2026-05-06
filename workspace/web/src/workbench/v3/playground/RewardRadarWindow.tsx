/**
 * RewardRadarWindow — 12-axis spider chart + per-axis sparklines.
 *
 * Ingests the events stream and rebuilds two state shapes:
 *   - `current` : latest scores per axis (drives the radar polygon)
 *   - `history`: per-axis array of values over the last N edits
 *                (drives the sparklines under each axis label)
 *
 * Visual: SVG radar at top (240×240), 4 axis-cards below in a 2×6 grid
 * showing label · value · sparkline. Borderless, accent green for
 * top-tier values.
 */
import { useMemo } from "react";

const AXES = [
  "predicted_mic", "drug_likeness_qed", "synthesizability",
  "hemolysis_safety", "embedding_novelty", "novelty",
  "structural_alerts", "validity",
];

type ScoreMap = Record<string, number>;

interface Props {
  current: ScoreMap;
  best: ScoreMap;
  weights?: Record<string, number>;
  /** Per-axis history (chronological, oldest first). */
  history: Record<string, number[]>;
  /** Optional ghost polygon: predicted-after-edit scores. Renders dashed
   *  when set; clears when null. Used by hover-prediction in 2D builder. */
  predicted?: ScoreMap | null;
  /** Optional small hint label drawn in the header (e.g. "if +F at atom 5"). */
  predictedLabel?: string;
}

function tierColor(v: number): string {
  if (v >= 0.7) return "var(--lys-accent)";
  if (v >= 0.4) return "#d97706";
  return "#9ca3af";
}

export function RewardRadarWindow({ current, best, weights, history, predicted, predictedLabel }: Props) {
  void predictedLabel; // displayed in header subtitle (next iter polish)
  const axes = AXES.filter((a) => a in current || a in best || a in (weights ?? {}));

  // Radar polygon points
  const RADIUS = 100;
  const CX = 120, CY = 120;
  const points = axes.map((axis, i) => {
    const angle = (i / axes.length) * 2 * Math.PI - Math.PI / 2;
    const r = (current[axis] ?? 0) * RADIUS;
    return [CX + r * Math.cos(angle), CY + r * Math.sin(angle)] as const;
  });
  const polygon = points.map((p) => p.join(",")).join(" ");
  const bestPolygon = axes.map((axis, i) => {
    const angle = (i / axes.length) * 2 * Math.PI - Math.PI / 2;
    const r = (best[axis] ?? 0) * RADIUS;
    return `${CX + r * Math.cos(angle)},${CY + r * Math.sin(angle)}`;
  }).join(" ");

  const composite = useMemo(() => {
    let sum = 0, wSum = 0;
    for (const axis of axes) {
      const w = weights?.[axis] ?? 0.1;
      sum += (current[axis] ?? 0) * w;
      wSum += w;
    }
    return wSum ? sum / wSum : 0;
  }, [current, weights, axes]);

  return (
    <div style={{
      width: "100%",
      height: "100%",
      overflow: "auto",
      padding: 8,
      display: "flex",
      flexDirection: "column",
      gap: 6,
      fontFamily: "var(--lys-font-body)",
      fontSize: 10.5,
    }}>
      {/* Header strip */}
      <div style={{
        display: "flex",
        alignItems: "baseline",
        gap: 6,
        padding: "0 4px 4px",
      }}>
        <span style={{
          fontSize: 9.5,
          color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}>
          composite
        </span>
        <span style={{
          fontFamily: "var(--lys-font-mono)",
          fontSize: 18,
          fontWeight: 700,
          color: tierColor(composite),
        }}>
          {composite.toFixed(3)}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 9,
          color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)",
        }}>
          {axes.length} axes
        </span>
      </div>

      {/* Radar SVG */}
      <svg viewBox="0 0 240 240" width="100%" style={{ maxHeight: 220, alignSelf: "center" }}>
        {/* concentric grid */}
        {[0.25, 0.5, 0.75, 1.0].map((r) => (
          <polygon
            key={r}
            points={axes.map((_, i) => {
              const a = (i / axes.length) * 2 * Math.PI - Math.PI / 2;
              return `${CX + r * RADIUS * Math.cos(a)},${CY + r * RADIUS * Math.sin(a)}`;
            }).join(" ")}
            fill="none"
            stroke="rgba(15,23,42,0.05)"
            strokeWidth="1"
          />
        ))}
        {/* axis spokes */}
        {axes.map((_, i) => {
          const a = (i / axes.length) * 2 * Math.PI - Math.PI / 2;
          return (
            <line
              key={i}
              x1={CX} y1={CY}
              x2={CX + RADIUS * Math.cos(a)}
              y2={CY + RADIUS * Math.sin(a)}
              stroke="rgba(15,23,42,0.05)"
              strokeWidth="1"
            />
          );
        })}
        {/* best polygon (faint) */}
        <polygon
          points={bestPolygon}
          fill="rgba(16, 185, 129, 0.08)"
          stroke="rgba(16, 185, 129, 0.35)"
          strokeWidth="1"
          strokeDasharray="3 3"
        />
        {/* current polygon (accent) */}
        <polygon
          points={polygon}
          fill="rgba(16, 185, 129, 0.20)"
          stroke="var(--lys-accent)"
          strokeWidth="1.5"
        />
        {/* predicted polygon (ghost, dashed amber) — drawn on top so it's
            visible when hovering an atom for a hypothetical edit */}
        {predicted && (
          <polygon
            points={axes.map((axis, i) => {
              const angle = (i / axes.length) * 2 * Math.PI - Math.PI / 2;
              const r = (predicted[axis] ?? 0) * RADIUS;
              return `${CX + r * Math.cos(angle)},${CY + r * Math.sin(angle)}`;
            }).join(" ")}
            fill="rgba(217, 119, 6, 0.10)"
            stroke="#d97706"
            strokeWidth="1.2"
            strokeDasharray="4 3"
          />
        )}
        {/* axis labels */}
        {axes.map((axis, i) => {
          const a = (i / axes.length) * 2 * Math.PI - Math.PI / 2;
          const lx = CX + (RADIUS + 14) * Math.cos(a);
          const ly = CY + (RADIUS + 14) * Math.sin(a);
          const v = current[axis] ?? 0;
          return (
            <text
              key={axis}
              x={lx}
              y={ly}
              textAnchor={Math.cos(a) > 0.3 ? "start" : Math.cos(a) < -0.3 ? "end" : "middle"}
              dominantBaseline={Math.sin(a) > 0.3 ? "hanging" : Math.sin(a) < -0.3 ? "auto" : "middle"}
              fontSize="7"
              fill={tierColor(v)}
              fontFamily="var(--lys-font-mono)"
            >
              {axis.slice(0, 12)}
            </text>
          );
        })}
      </svg>

      {/* Per-axis sparklines */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 4,
      }}>
        {axes.map((axis) => {
          const hist = history[axis] ?? [];
          const cur = current[axis] ?? 0;
          return (
            <div
              key={axis}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 4,
                padding: "2px 4px",
                borderRadius: 4,
              }}
            >
              <span style={{
                fontFamily: "var(--lys-font-mono)",
                fontSize: 8.5,
                color: "var(--lys-text-dim)",
                width: 60,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}>
                {axis.slice(0, 9)}
              </span>
              <Sparkline values={hist} color={tierColor(cur)} />
              <span style={{
                fontFamily: "var(--lys-font-mono)",
                fontSize: 9,
                color: tierColor(cur),
                fontWeight: 600,
                width: 32,
                textAlign: "right",
              }}>
                {cur.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (!values || values.length < 2) {
    return <div style={{ flex: 1, height: 14, opacity: 0.3 }}>—</div>;
  }
  const w = 60, h = 14;
  const min = 0, max = 1;
  const stepX = w / (values.length - 1);
  const path = values.map((v, i) => {
    const x = i * stepX;
    const y = h - ((v - min) / (max - min)) * h;
    return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={w} height={h} style={{ flexShrink: 0 }}>
      <path d={path} fill="none" stroke={color} strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  );
}

import {
  Radar,
  RadarChart,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Legend,
} from "recharts";

interface RadarPanelProps {
  current: Record<string, number> | null;
  best?: Record<string, number> | null;
  // Optional weights for the contribution legend
  weights?: Record<string, number>;
}

const AXES = [
  { key: "validity", label: "Valid" },
  { key: "predicted_mic", label: "MIC" },
  { key: "drug_likeness_qed", label: "QED" },
  { key: "synthesizability", label: "SA" },
  { key: "hemolysis_safety", label: "Safe" },
  { key: "novelty", label: "Tan-Nov" },
  { key: "embedding_novelty", label: "Sem-Nov" },
  { key: "structural_alerts", label: "Alerts" },
];

export function RadarPanel({ current, best, weights }: RadarPanelProps) {
  if (!current) {
    return <Empty msg="no scored candidate yet — run a session first" />;
  }
  const data = AXES.map(({ key, label }) => ({
    axis: label,
    current: round(current[key] ?? 0),
    best: best ? round(best[key] ?? 0) : undefined,
  }));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ height: 240, background: "var(--lys-surface)", borderRadius: 12, padding: 8, border: "1px solid var(--lys-border)" }}>
        <ResponsiveContainer>
          <RadarChart data={data} outerRadius="78%">
            <PolarGrid stroke="rgba(15,23,42,0.08)" />
            <PolarAngleAxis dataKey="axis" tick={{ fill: "#475569", fontSize: 11 }} />
            <PolarRadiusAxis
              domain={[0, 1]}
              tick={false}
              axisLine={false}
              stroke="rgba(15,23,42,0.05)"
            />
            <Radar
              name="current"
              dataKey="current"
              stroke="#10b981"
              fill="#10b981"
              fillOpacity={0.32}
              strokeWidth={2}
            />
            {best && (
              <Radar
                name="best"
                dataKey="best"
                stroke="#8b5cf6"
                fill="#8b5cf6"
                fillOpacity={0.12}
                strokeDasharray="4 4"
              />
            )}
            <Legend
              wrapperStyle={{ fontSize: 11, color: "#475569" }}
              iconSize={8}
            />
          </RadarChart>
        </ResponsiveContainer>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {AXES.map(({ key, label }) => {
          const v = current[key] ?? 0;
          const w = weights?.[key];
          const contrib = w != null ? v * w : null;
          return (
            <div
              key={key}
              style={{
                display: "grid",
                gridTemplateColumns: "70px 1fr 50px 60px",
                gap: 8,
                alignItems: "center",
                fontSize: 11,
                fontFamily: "var(--lys-font-mono)",
              }}
            >
              <span style={{ color: "var(--lys-text-dim)" }}>{label}</span>
              <div style={{ height: 4, background: "var(--lys-border)", borderRadius: 2 }}>
                <div
                  style={{
                    height: "100%",
                    width: `${Math.min(100, v * 100)}%`,
                    background: contributionColor(v),
                    borderRadius: 2,
                  }}
                />
              </div>
              <span style={{ textAlign: "right" }}>{v.toFixed(2)}</span>
              <span style={{ color: "var(--lys-text-faint)", fontSize: 10, textAlign: "right" }}>
                {contrib != null ? `→ ${contrib.toFixed(3)}` : ""}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function contributionColor(v: number): string {
  if (v >= 0.75) return "#34d399";
  if (v >= 0.5) return "#fbbf24";
  if (v >= 0.25) return "#fb923c";
  return "#f87171";
}

function round(v: number): number {
  return Math.round(v * 1000) / 1000;
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{
      padding: 24,
      textAlign: "center",
      color: "var(--lys-text-faint)",
      fontSize: 12,
    }}>
      {msg}
    </div>
  );
}

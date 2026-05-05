import { useMemo, useState } from "react";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  ZAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";

interface CandidateRow {
  id: string;
  smiles: string;
  scores: Record<string, number>;
  composite: number;
  isPareto: boolean;
}

interface ParetoPanelProps {
  candidates: CandidateRow[];
}

const AXES_OPTIONS = [
  { key: "predicted_mic", label: "MIC" },
  { key: "drug_likeness_qed", label: "QED" },
  { key: "synthesizability", label: "SA" },
  { key: "hemolysis_safety", label: "Safe" },
  { key: "novelty", label: "Tan-Nov" },
  { key: "embedding_novelty", label: "Sem-Nov" },
  { key: "structural_alerts", label: "Alerts" },
  { key: "validity", label: "Valid" },
] as const;

export function ParetoPanel({ candidates }: ParetoPanelProps) {
  const [xKey, setXKey] = useState<string>("predicted_mic");
  const [yKey, setYKey] = useState<string>("drug_likeness_qed");

  const data = useMemo(
    () =>
      candidates.map((c) => ({
        x: c.scores[xKey] ?? 0,
        y: c.scores[yKey] ?? 0,
        composite: c.composite,
        isPareto: c.isPareto,
        smiles: c.smiles,
      })),
    [candidates, xKey, yKey]
  );

  if (candidates.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--lys-text-faint)", fontSize: 12 }}>
        no candidates yet
      </div>
    );
  }

  const xLabel = AXES_OPTIONS.find((a) => a.key === xKey)?.label ?? xKey;
  const yLabel = AXES_OPTIONS.find((a) => a.key === yKey)?.label ?? yKey;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ display: "flex", gap: 8, alignItems: "center", fontSize: 11 }}>
        <AxisSelect label="X" value={xKey} onChange={setXKey} />
        <AxisSelect label="Y" value={yKey} onChange={setYKey} />
        <span style={{ marginLeft: "auto", color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>
          {data.filter((d) => d.isPareto).length}/{data.length} on Pareto
        </span>
      </div>

      <div style={{ height: 240, background: "var(--lys-surface)", borderRadius: 12, padding: 8 }}>
        <ResponsiveContainer>
          <ScatterChart margin={{ top: 8, right: 12, bottom: 24, left: 0 }}>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" />
            <XAxis
              type="number"
              dataKey="x"
              domain={[0, 1]}
              tick={{ fill: "#8b949e", fontSize: 10 }}
              label={{ value: xLabel, position: "insideBottom", offset: -8, fill: "#8b949e", fontSize: 11 }}
              stroke="#30363d"
            />
            <YAxis
              type="number"
              dataKey="y"
              domain={[0, 1]}
              tick={{ fill: "#8b949e", fontSize: 10 }}
              label={{ value: yLabel, angle: -90, position: "insideLeft", offset: 12, fill: "#8b949e", fontSize: 11 }}
              stroke="#30363d"
            />
            <ZAxis range={[40, 120]} dataKey="composite" />
            <Tooltip
              cursor={{ stroke: "#34d399", strokeOpacity: 0.3 }}
              content={({ active, payload }) => {
                if (!active || !payload || payload.length === 0) return null;
                const p: any = payload[0].payload;
                return (
                  <div style={{
                    background: "#161b22",
                    border: "1px solid rgba(255,255,255,0.16)",
                    borderRadius: 6,
                    padding: 8,
                    fontSize: 11,
                    fontFamily: "var(--lys-font-mono)",
                  }}>
                    <div style={{ color: p.isPareto ? "#34d399" : "#8b949e" }}>
                      {p.isPareto ? "★ Pareto" : "dominated"}
                    </div>
                    <div>{xLabel}: {p.x.toFixed(3)}</div>
                    <div>{yLabel}: {p.y.toFixed(3)}</div>
                    <div>composite: {p.composite.toFixed(3)}</div>
                    <div style={{ marginTop: 4, color: "#e6edf3", fontSize: 10, maxWidth: 220, wordBreak: "break-all" }}>
                      {p.smiles}
                    </div>
                  </div>
                );
              }}
            />
            <Scatter data={data} fill="#34d399">
              {data.map((d, i) => (
                <Cell key={i} fill={d.isPareto ? "#34d399" : "#475569"} />
              ))}
            </Scatter>
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function AxisSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span style={{ color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)" }}>{label}:</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          background: "var(--lys-surface)",
          border: "1px solid var(--lys-border)",
          color: "var(--lys-text)",
          borderRadius: 6,
          padding: "2px 6px",
          fontFamily: "inherit",
          fontSize: 11,
        }}
      >
        {AXES_OPTIONS.map((o) => (
          <option key={o.key} value={o.key}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

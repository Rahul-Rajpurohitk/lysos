import { useEffect, useMemo, useRef, useState } from "react";

interface Node {
  id: string;
  kind: "pathogen" | "resistance_gene" | "drug_class";
  label: string;
}

interface Edge {
  src: string;
  dst: string;
  kind: string;
}

interface GraphData {
  pathogen: string;
  nodes: Node[];
  edges: Edge[];
}

interface GraphPanelProps {
  apiBase: string;
  pathogen: string;
}

const COLORS: Record<Node["kind"], string> = {
  pathogen: "#f59e0b",
  resistance_gene: "#ef4444",
  drug_class: "#10b981",
};

const RADIUS: Record<Node["kind"], number> = {
  pathogen: 22,
  resistance_gene: 14,
  drug_class: 12,
};

interface PositionedNode extends Node {
  x: number;
  y: number;
}

export function GraphPanel({ apiBase, pathogen }: GraphPanelProps) {
  const [data, setData] = useState<GraphData | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const W = 380;
  const H = 360;

  useEffect(() => {
    fetch(`${apiBase}/workbench/sandbox/resistance-graph/${pathogen}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setData)
      .catch(() => setData(null));
  }, [apiBase, pathogen]);

  const positioned = useMemo<PositionedNode[]>(() => {
    if (!data) return [];
    // Simple radial layout: pathogen at center, genes on inner ring,
    // drug classes on outer ring.
    const cx = W / 2;
    const cy = H / 2;
    const out: PositionedNode[] = [];

    const path = data.nodes.find((n) => n.kind === "pathogen");
    if (path) out.push({ ...path, x: cx, y: cy });

    const genes = data.nodes.filter((n) => n.kind === "resistance_gene");
    genes.forEach((g, i) => {
      const angle = (i / Math.max(1, genes.length)) * 2 * Math.PI;
      out.push({ ...g, x: cx + 90 * Math.cos(angle), y: cy + 90 * Math.sin(angle) });
    });

    const classes = data.nodes.filter((n) => n.kind === "drug_class");
    classes.forEach((c, i) => {
      const angle = (i / Math.max(1, classes.length)) * 2 * Math.PI + 0.2;
      out.push({ ...c, x: cx + 160 * Math.cos(angle), y: cy + 160 * Math.sin(angle) });
    });
    return out;
  }, [data]);

  if (!data) {
    return <div style={{ padding: 24, textAlign: "center", color: "var(--lys-text-faint)", fontSize: 12 }}>loading graph for {pathogen}…</div>;
  }

  const byId = new Map(positioned.map((n) => [n.id, n]));

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div style={{ background: "var(--lys-surface)", borderRadius: 12, padding: 8 }}>
        <svg
          ref={svgRef}
          viewBox={`0 0 ${W} ${H}`}
          style={{ width: "100%", height: 360 }}
        >
          {data.edges.map((e, i) => {
            const a = byId.get(e.src);
            const b = byId.get(e.dst);
            if (!a || !b) return null;
            const isHl = hovered != null && (hovered === e.src || hovered === e.dst);
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={isHl ? "#10b981" : "rgba(15,23,42,0.16)"}
                strokeWidth={isHl ? 2 : 1}
              />
            );
          })}
          {positioned.map((n) => {
            const r = RADIUS[n.kind];
            const isHl = hovered === n.id;
            return (
              <g
                key={n.id}
                onMouseEnter={() => setHovered(n.id)}
                onMouseLeave={() => setHovered(null)}
                style={{ cursor: "pointer" }}
              >
                <circle
                  cx={n.x}
                  cy={n.y}
                  r={r}
                  fill={COLORS[n.kind]}
                  stroke={isHl ? "#0f172a" : "white"}
                  strokeWidth={isHl ? 2 : 2}
                  fillOpacity={isHl ? 1 : 0.9}
                />
                <text
                  x={n.x}
                  y={n.y + r + 12}
                  fill="var(--lys-text)"
                  fontSize={n.kind === "pathogen" ? 12 : 10}
                  fontFamily="var(--lys-font-mono)"
                  textAnchor="middle"
                >
                  {n.label.slice(0, 14)}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <div style={{ display: "flex", gap: 12, fontSize: 11, alignItems: "center" }}>
        <Legend kind="pathogen" label="pathogen" />
        <Legend kind="resistance_gene" label="resistance gene" />
        <Legend kind="drug_class" label="affected drug class" />
      </div>
    </div>
  );
}

function Legend({ kind, label }: { kind: Node["kind"]; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span style={{
        width: 10, height: 10, borderRadius: 5,
        background: COLORS[kind], display: "inline-block",
      }} />
      <span style={{ color: "var(--lys-text-dim)" }}>{label}</span>
    </span>
  );
}

/**
 * ResistanceNetworkCard — pathogen → resistance gene → drug class
 * graph for the active pathogen.
 *
 * Three-tier hierarchical layout (left → right):
 *   Tier 0: pathogen node (single)
 *   Tier 1: resistance genes (one per top_resistance entry)
 *   Tier 2: drug classes affected (deduped across genes)
 *
 * Edges: carries (pathogen→gene) and blocks (gene→class).
 *
 * Hover a gene → shows its mechanism + which classes it hits.
 * Click a node → fires `/explain <name>`.
 */
import { useEffect, useState, useMemo } from "react";

interface Node {
  id: string;
  kind: "pathogen" | "gene" | "drug_class" | "first_line";
  label: string;
  mechanism?: string;
  tier: number;
}
interface Edge { source: string; target: string; kind: string }
interface NetworkResponse {
  pathogen: string;
  full_name: string;
  nodes: Node[];
  edges: Edge[];
  n_genes: number;
  n_classes: number;
  n_first_line: number;
}

interface Props {
  apiBase: string;
  pathogen: string;
  onFireSlash?: (slash: string) => void;
}

const TIER_COLORS = {
  pathogen: { fill: "#8458ff", text: "white" },
  gene: { fill: "#dc2626", text: "white" },
  drug_class: { fill: "#f59e0b", text: "black" },
  first_line: { fill: "#10b981", text: "white" },
};

export function ResistanceNetworkCard({ apiBase, pathogen, onFireSlash }: Props) {
  const [data, setData] = useState<NetworkResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [hover, setHover] = useState<string | null>(null);

  useEffect(() => {
    if (!pathogen) return;
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/knowledge/network/${encodeURIComponent(pathogen)}`);
        if (!r.ok) return;
        const d = await r.json();
        if (alive) setData(d);
      } catch {/* offline */}
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [apiBase, pathogen]);

  // Compute tier columns + per-node positions
  const layout = useMemo(() => {
    if (!data) return null;
    const W = 720, H = 320;
    const tierX = [60, 240, 460, 660];
    const byTier: Record<number, Node[]> = { 0: [], 1: [], 2: [], 3: [] };
    for (const n of data.nodes) (byTier[n.tier] ??= []).push(n);
    const nodePos: Record<string, { x: number; y: number; node: Node }> = {};
    for (const t of [0, 1, 2, 3] as const) {
      const list = byTier[t] || [];
      const gap = list.length > 1 ? (H - 40) / (list.length - 1) : 0;
      for (let i = 0; i < list.length; i++) {
        nodePos[list[i].id] = {
          x: tierX[t],
          y: list.length === 1 ? H / 2 : 20 + i * gap,
          node: list[i],
        };
      }
    }
    return { W, H, nodePos };
  }, [data]);

  if (loading) return <div style={{ padding: 12, fontSize: 11, color: "var(--lys-text-dim)" }}>Loading network…</div>;
  if (!data || !layout) return null;

  const { W, H, nodePos } = layout;
  const nodeR = 18;

  // Hover-related: which edges to highlight?
  const hoverEdges = new Set<string>();
  if (hover) {
    for (const e of data.edges) {
      if (e.source === hover || e.target === hover) hoverEdges.add(`${e.source}→${e.target}`);
    }
  }

  return (
    <div style={{ padding: 8 }}>
      <div style={{
        fontSize: 9, color: "var(--lys-text-faint)", textTransform: "uppercase",
        letterSpacing: 0.6, marginBottom: 6, fontWeight: 600,
      }}>
        {data.full_name} · {data.n_genes} genes → {data.n_classes} classes
        · {data.n_first_line} first-line drugs
      </div>
      <div style={{ overflowX: "auto" }}>
        <svg width={W} height={H} style={{ display: "block" }}>
          {/* Tier headers */}
          <text x={60} y={14} textAnchor="middle" fontSize={9}
                fill="#8458ff" fontFamily="var(--lys-font-mono)" fontWeight="700">
            PATHOGEN
          </text>
          <text x={240} y={14} textAnchor="middle" fontSize={9}
                fill="#dc2626" fontFamily="var(--lys-font-mono)" fontWeight="700">
            RESISTANCE GENES
          </text>
          <text x={460} y={14} textAnchor="middle" fontSize={9}
                fill="#f59e0b" fontFamily="var(--lys-font-mono)" fontWeight="700">
            DRUG CLASSES BLOCKED
          </text>
          <text x={660} y={14} textAnchor="middle" fontSize={9}
                fill="#10b981" fontFamily="var(--lys-font-mono)" fontWeight="700">
            FIRST-LINE
          </text>
          {/* Edges */}
          {data.edges.map((e, i) => {
            const a = nodePos[e.source], b = nodePos[e.target];
            if (!a || !b) return null;
            const key = `${e.source}→${e.target}`;
            const lit = hoverEdges.has(key);
            return (
              <line
                key={i}
                x1={a.x} y1={a.y} x2={b.x} y2={b.y}
                stroke={lit ? "#dc2626" : "rgba(0,0,0,0.18)"}
                strokeWidth={lit ? 2 : 1}
                opacity={hover && !lit ? 0.25 : 1}
              />
            );
          })}
          {/* Nodes */}
          {Object.values(nodePos).map(({ x, y, node }) => {
            const c = TIER_COLORS[node.kind] || { fill: "#666", text: "white" };
            const isHover = hover === node.id;
            const dim = hover && !isHover && !hoverEdges.size;
            return (
              <g
                key={node.id}
                onMouseEnter={() => setHover(node.id)}
                onMouseLeave={() => setHover(null)}
                onClick={() => {
                  if (node.kind === "gene") {
                    onFireSlash?.(`/explain ${node.label.split(/\s|\//)[0]}`);
                  } else if (node.kind === "first_line") {
                    onFireSlash?.(`/explain ${node.label.split(/\s/)[0]}`);
                  }
                }}
                style={{ cursor: node.kind === "gene" || node.kind === "first_line" ? "pointer" : "default", opacity: dim ? 0.4 : 1 }}
              >
                <circle cx={x} cy={y} r={nodeR}
                        fill={c.fill}
                        stroke={isHover ? "black" : "white"}
                        strokeWidth={isHover ? 2 : 1.5} />
                <text x={x} y={y - nodeR - 5} textAnchor="middle"
                      fontSize={9.5} fontFamily="var(--lys-font-mono)"
                      fill="var(--lys-text)" fontWeight="600">
                  {node.label.length > 20 ? node.label.slice(0, 19) + "…" : node.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      {/* Hover detail */}
      {hover && (() => {
        const n = data.nodes.find((x) => x.id === hover);
        if (!n) return null;
        return (
          <div style={{
            marginTop: 6, padding: "5px 9px",
            background: "rgba(0,0,0,0.03)", borderRadius: 4,
            borderLeft: `3px solid ${TIER_COLORS[n.kind]?.fill || "#666"}`,
            fontSize: 11,
          }}>
            <strong style={{ color: TIER_COLORS[n.kind]?.fill || "#666" }}>
              {n.label}
            </strong>
            {n.mechanism && (
              <span style={{ marginLeft: 8, color: "var(--lys-text-dim)" }}>
                — {n.mechanism}
              </span>
            )}
            {n.kind === "gene" && (
              <span style={{ marginLeft: 8, color: "var(--lys-text-faint)", fontSize: 10 }}>
                (click to /explain)
              </span>
            )}
          </div>
        );
      })()}
    </div>
  );
}

export default ResistanceNetworkCard;

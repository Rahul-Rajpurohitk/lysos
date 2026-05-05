import { useMemo } from "react";

interface MolEditEvent {
  ts: number;
  parent: string;
  candidate: string;
  delta?: Record<string, number>;
  agent?: string;
}

interface CandidateEvent {
  ts: number;
  smiles: string;
  composite: number;
}

interface LineagePanelProps {
  edits: MolEditEvent[];
  candidates: CandidateEvent[];
}

interface Node {
  smiles: string;
  composite: number;
  parent: string | null;
  depth: number;
  x: number;
  y: number;
}

const NODE_R = 14;
const COL_W = 160;
const ROW_H = 56;

export function LineagePanel({ edits, candidates }: LineagePanelProps) {
  const { nodes, edges } = useMemo(() => {
    // Build parent map: candidate.smiles -> parent.smiles
    const parentOf: Record<string, string | null> = {};
    const compOf: Record<string, number> = {};
    for (const c of candidates) {
      parentOf[c.smiles] = parentOf[c.smiles] ?? null;
      compOf[c.smiles] = c.composite;
    }
    for (const e of edits) {
      parentOf[e.candidate] = e.parent;
    }

    // Compute depth (root = no parent)
    const depthOf: Record<string, number> = {};
    function depth(s: string): number {
      if (depthOf[s] != null) return depthOf[s];
      const p = parentOf[s];
      depthOf[s] = p == null ? 0 : depth(p) + 1;
      return depthOf[s];
    }

    // Layout: column = depth, row = order within depth
    const nodes: Node[] = [];
    const byDepth: Record<number, string[]> = {};
    for (const s of Object.keys(parentOf)) {
      const d = depth(s);
      byDepth[d] = byDepth[d] ?? [];
      byDepth[d].push(s);
    }
    for (const [dStr, list] of Object.entries(byDepth)) {
      const d = parseInt(dStr, 10);
      list.forEach((s, i) => {
        nodes.push({
          smiles: s,
          composite: compOf[s] ?? 0,
          parent: parentOf[s],
          depth: d,
          x: d * COL_W + 40,
          y: i * ROW_H + 30,
        });
      });
    }

    const nodeMap = new Map(nodes.map((n) => [n.smiles, n]));
    const edges: Array<{ from: Node; to: Node; label?: string }> = [];
    for (const e of edits) {
      const a = nodeMap.get(e.parent);
      const b = nodeMap.get(e.candidate);
      if (a && b) {
        edges.push({ from: a, to: b, label: deltaSummary(e.delta) });
      }
    }
    return { nodes, edges };
  }, [edits, candidates]);

  if (nodes.length === 0) {
    return (
      <div style={{ padding: 24, textAlign: "center", color: "var(--lys-text-faint)", fontSize: 12 }}>
        no candidates yet
      </div>
    );
  }

  const maxX = Math.max(...nodes.map((n) => n.x)) + COL_W;
  const maxY = Math.max(...nodes.map((n) => n.y)) + ROW_H;

  return (
    <div style={{
      width: "100%",
      height: 360,
      background: "var(--lys-surface)",
      border: "1px solid var(--lys-border)",
      borderRadius: 12,
      overflow: "auto",
    }}>
      <svg viewBox={`0 0 ${maxX} ${maxY}`} style={{ minWidth: maxX, minHeight: maxY }}>
        {edges.map((e, i) => (
          <g key={i}>
            <line
              x1={e.from.x + NODE_R}
              y1={e.from.y}
              x2={e.to.x - NODE_R}
              y2={e.to.y}
              stroke="rgba(255,255,255,0.18)"
              strokeWidth={1.5}
            />
            {e.label && (
              <text
                x={(e.from.x + e.to.x) / 2}
                y={(e.from.y + e.to.y) / 2 - 4}
                fill="#8b949e"
                fontSize={10}
                textAnchor="middle"
                fontFamily="var(--lys-font-mono)"
              >
                {e.label}
              </text>
            )}
          </g>
        ))}
        {nodes.map((n, i) => (
          <g key={i}>
            <circle
              cx={n.x}
              cy={n.y}
              r={NODE_R}
              fill={compositeColor(n.composite)}
              stroke="rgba(255,255,255,0.25)"
              strokeWidth={2}
            />
            <text
              x={n.x}
              y={n.y + 3}
              fill="white"
              fontSize={11}
              textAnchor="middle"
              fontFamily="var(--lys-font-mono)"
              fontWeight={600}
            >
              {n.composite.toFixed(2)}
            </text>
            <text
              x={n.x}
              y={n.y + NODE_R + 14}
              fill="#8b949e"
              fontSize={9}
              textAnchor="middle"
              fontFamily="var(--lys-font-mono)"
            >
              {n.smiles.slice(0, 14)}{n.smiles.length > 14 ? "…" : ""}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function deltaSummary(delta?: Record<string, number>): string {
  if (!delta) return "";
  const significant = Object.entries(delta)
    .filter(([_, v]) => Math.abs(v) > 0.02)
    .sort(([, a], [, b]) => Math.abs(b) - Math.abs(a))
    .slice(0, 1);
  if (significant.length === 0) return "";
  const [k, v] = significant[0];
  const sign = v > 0 ? "+" : "";
  return `${k.split("_")[0].slice(0, 4)}${sign}${v.toFixed(2)}`;
}

function compositeColor(v: number): string {
  if (v >= 0.7) return "#16a34a";
  if (v >= 0.5) return "#65a30d";
  if (v >= 0.3) return "#f59e0b";
  return "#dc2626";
}

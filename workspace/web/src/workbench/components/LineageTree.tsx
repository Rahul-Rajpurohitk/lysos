// Lineage tree — git-graph layout of candidates (light theme)

import { useMemo } from 'react'
import type { Candidate } from '../types'

interface LineageTreeProps {
  candidates: Candidate[]
  selectedId: string | null
  paretoIds: string[]
  onSelect: (id: string) => void
}

interface Node {
  id: string
  parent_id: string | null
  composite: number
  smiles: string
  isPareto: boolean
  isSelected: boolean
  x: number
  y: number
  depth: number
}

function scoreColor(s: number): string {
  if (s < 0.4) return '#ef4444'   // red
  if (s < 0.6) return '#f59e0b'   // amber
  if (s < 0.75) return '#eab308'  // yellow
  if (s < 0.85) return '#22c55e'  // green
  return '#10b981'                // emerald
}

export function LineageTree({ candidates, selectedId, paretoIds, onSelect }: LineageTreeProps) {
  const { nodes, edges, width, height } = useMemo(() => {
    if (candidates.length === 0) {
      return { nodes: [], edges: [], width: 0, height: 0 }
    }
    const childMap = new Map<string | null, string[]>()
    for (const c of candidates) {
      const arr = childMap.get(c.parent_id) ?? []
      arr.push(c.id)
      childMap.set(c.parent_id, arr)
    }
    const computed = new Map<string, { depth: number; lane: number }>()
    const lanes: number[] = []

    function walk(id: string, depth: number) {
      const lane = lanes[depth] ?? 0
      computed.set(id, { depth, lane })
      lanes[depth] = lane + 1
      const children = childMap.get(id) ?? []
      for (const cid of children) walk(cid, depth + 1)
    }

    const roots = childMap.get(null) ?? []
    for (const r of roots) walk(r, 0)

    const NODE_R = 16
    const X_GAP = 80
    const Y_GAP = 60
    const PAD = 24

    const nodes: Node[] = candidates.map((c) => {
      const pos = computed.get(c.id) ?? { depth: 0, lane: 0 }
      return {
        id: c.id,
        parent_id: c.parent_id,
        composite: c.scores.composite,
        smiles: c.smiles,
        isPareto: paretoIds.includes(c.id),
        isSelected: c.id === selectedId,
        x: PAD + pos.depth * X_GAP + NODE_R,
        y: PAD + pos.lane * Y_GAP + NODE_R,
        depth: pos.depth,
      }
    })

    const edges = candidates
      .filter((c) => c.parent_id)
      .map((c) => {
        const child = nodes.find((n) => n.id === c.id)!
        const parent = nodes.find((n) => n.id === c.parent_id)!
        return { from: parent, to: child, id: `${parent.id}->${child.id}` }
      })

    const maxDepth = Math.max(...nodes.map((n) => n.depth), 0)
    const maxLane = Math.max(...nodes.map((n) => n.y), 0)
    const w = PAD * 2 + (maxDepth + 1) * X_GAP
    const h = Math.max(maxLane + PAD * 2, 80)

    return { nodes, edges, width: w, height: h }
  }, [candidates, selectedId, paretoIds])

  if (nodes.length === 0) {
    return (
      <div className="text-slate-400 text-sm p-4">
        Lineage tree appears as candidates are proposed.
      </div>
    )
  }

  return (
    <div className="w-full p-2">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="xMidYMid meet"
        className="block w-full h-auto"
        style={{ maxHeight: 320 }}
      >
        {edges.map((e) => (
          <path
            key={e.id}
            d={`M ${e.from.x} ${e.from.y} C ${(e.from.x + e.to.x) / 2} ${e.from.y}, ${(e.from.x + e.to.x) / 2} ${e.to.y}, ${e.to.x} ${e.to.y}`}
            fill="none"
            stroke="#94a3b8"
            strokeWidth={1.5}
          />
        ))}
        {nodes.map((n) => (
          <g key={n.id} transform={`translate(${n.x}, ${n.y})`}>
            <circle
              r={n.isSelected ? 12 : 10}
              fill={scoreColor(n.composite)}
              stroke={n.isSelected ? '#0f172a' : (n.isPareto ? '#10b981' : 'transparent')}
              strokeWidth={n.isPareto ? 3 : 2}
              onClick={() => onSelect(n.id)}
              style={{ cursor: 'pointer' }}
            >
              <title>{`${n.smiles.slice(0, 40)}\ncomposite=${n.composite.toFixed(3)}`}</title>
            </circle>
            <text
              y={20}
              textAnchor="middle"
              fill="#475569"
              fontSize={9}
              style={{ pointerEvents: 'none' }}
            >
              {n.composite.toFixed(2)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  )
}

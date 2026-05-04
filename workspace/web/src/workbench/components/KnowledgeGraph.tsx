// Knowledge graph — pathogen × resistance gene × drug class network
// Pure-SVG force-free layout (radial), no extra deps.

import { useEffect, useMemo, useState } from 'react'
import { invokeTool } from '../api'
import type { Pathogen } from '../types'

interface KnowledgeGraphProps {
  pathogen: Pathogen
}

interface Node {
  id: string
  label: string
  type: 'pathogen' | 'gene' | 'drug_class'
  x: number
  y: number
}

interface Edge {
  from: string
  to: string
  kind: 'has_gene' | 'gene_affects'
}

const NODE_STYLE = {
  pathogen: { fill: '#fef3c7', stroke: '#d97706', text: '#78350f', r: 36 },
  gene: { fill: '#fee2e2', stroke: '#dc2626', text: '#7f1d1d', r: 22 },
  drug_class: { fill: '#d1fae5', stroke: '#059669', text: '#064e3b', r: 22 },
}

export function KnowledgeGraph({ pathogen }: KnowledgeGraphProps) {
  const [resistome, setResistome] = useState<any>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    setLoading(true)
    invokeTool('get_pathogen_resistome', { pathogen })
      .then((r) => setResistome(((r as any).result) ?? null))
      .catch(() => setResistome(null))
      .finally(() => setLoading(false))
  }, [pathogen])

  const { nodes, edges } = useMemo(() => {
    if (!resistome) return { nodes: [], edges: [] }
    const cx = 300
    const cy = 200

    const ns: Node[] = [{
      id: 'pathogen',
      label: pathogen,
      type: 'pathogen',
      x: cx, y: cy,
    }]
    const es: Edge[] = []
    const drugClassMap = new Map<string, Set<string>>()  // drug → genes

    const genes = (resistome.resistome ?? []).slice(0, 8)
    const total = genes.length
    genes.forEach((g: any, i: number) => {
      const angle = (i / total) * Math.PI * 2 - Math.PI / 2
      const r = 130
      ns.push({
        id: `gene-${i}`,
        label: g.gene.split(' ')[0].slice(0, 12),
        type: 'gene',
        x: cx + Math.cos(angle) * r,
        y: cy + Math.sin(angle) * r,
      })
      es.push({ from: 'pathogen', to: `gene-${i}`, kind: 'has_gene' })

      // Aggregate drug classes
      for (const aff of g.affects) {
        const cls = aff.split(/[\s_(]/)[0].slice(0, 16)
        if (!drugClassMap.has(cls)) drugClassMap.set(cls, new Set())
        drugClassMap.get(cls)!.add(`gene-${i}`)
      }
    })

    // Add drug classes around the outside
    const classes = Array.from(drugClassMap.entries()).slice(0, 8)
    classes.forEach(([cls, geneIds], i) => {
      const angle = (i / classes.length) * Math.PI * 2 - Math.PI / 2 + 0.3
      const r = 230
      const id = `cls-${i}`
      ns.push({
        id,
        label: cls,
        type: 'drug_class',
        x: cx + Math.cos(angle) * r,
        y: cy + Math.sin(angle) * r,
      })
      for (const gid of geneIds) {
        es.push({ from: gid, to: id, kind: 'gene_affects' })
      }
    })
    return { nodes: ns, edges: es }
  }, [resistome, pathogen])

  if (loading) {
    return <div className="text-slate-500 text-xs p-3 animate-pulse">building graph…</div>
  }
  if (!resistome) {
    return <div className="text-slate-400 text-xs p-3">No resistome data.</div>
  }

  return (
    <div className="p-2 w-full">
      <svg viewBox="0 0 620 420" preserveAspectRatio="xMidYMid meet" className="block w-full h-auto max-h-[480px]">
        {/* Edges */}
        {edges.map((e) => {
          const from = nodes.find((n) => n.id === e.from)
          const to = nodes.find((n) => n.id === e.to)
          if (!from || !to) return null
          const stroke = e.kind === 'has_gene' ? '#fbbf24' : '#ef4444'
          return (
            <line
              key={`${e.from}-${e.to}`}
              x1={from.x} y1={from.y} x2={to.x} y2={to.y}
              stroke={stroke}
              strokeWidth={1.2}
              strokeOpacity={0.6}
            />
          )
        })}
        {/* Nodes */}
        {nodes.map((n) => {
          const s = NODE_STYLE[n.type]
          return (
            <g key={n.id} transform={`translate(${n.x}, ${n.y})`}>
              <circle r={s.r} fill={s.fill} stroke={s.stroke} strokeWidth={2} />
              <text
                textAnchor="middle"
                dy={4}
                fontSize={n.type === 'pathogen' ? 13 : 9}
                fontWeight={n.type === 'pathogen' ? 700 : 500}
                fill={s.text}
                style={{ pointerEvents: 'none' }}
              >
                {n.label}
              </text>
            </g>
          )
        })}
      </svg>
      <div className="text-[10px] text-slate-500 mt-2 flex items-center gap-3">
        <span><span className="inline-block w-3 h-3 rounded-full bg-amber-200 border border-amber-600 mr-1 align-middle" /> pathogen</span>
        <span><span className="inline-block w-3 h-3 rounded-full bg-rose-200 border border-rose-600 mr-1 align-middle" /> resistance gene</span>
        <span><span className="inline-block w-3 h-3 rounded-full bg-emerald-200 border border-emerald-600 mr-1 align-middle" /> affected drug class</span>
      </div>
    </div>
  )
}

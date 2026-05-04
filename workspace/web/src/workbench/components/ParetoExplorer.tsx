// Pareto frontier explorer — 2D scatter of MIC × QED × novelty (3 axes overlay)

import { useMemo, useState } from 'react'
import {
  ScatterChart, Scatter, XAxis, YAxis, ZAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from 'recharts'
import type { Candidate } from '../types'

interface ParetoExplorerProps {
  candidates: Candidate[]
  paretoIds: string[]
  onSelect?: (id: string) => void
}

type Axis = 'predicted_mic' | 'drug_likeness_qed' | 'novelty' | 'embedding_novelty' | 'synthesizability' | 'composite'

const AXIS_LABELS: Record<Axis, string> = {
  predicted_mic: 'MIC',
  drug_likeness_qed: 'QED',
  novelty: 'Tanimoto-Novelty',
  embedding_novelty: 'Semantic-Novelty',
  synthesizability: 'SA',
  composite: 'Composite',
}

const AXES: Axis[] = [
  'predicted_mic', 'drug_likeness_qed', 'novelty',
  'embedding_novelty', 'synthesizability', 'composite',
]

interface ScatterPoint {
  id: string
  x: number
  y: number
  z: number
  smiles: string
  isPareto: boolean
}

function CustomTooltip({ active, payload }: any) {
  if (active && payload?.length) {
    const p = payload[0].payload as ScatterPoint
    return (
      <div className="bg-white border border-slate-300 rounded p-2 text-xs shadow">
        <div className="font-mono mb-1 truncate max-w-[260px]">{p.smiles}</div>
        <div>x: {p.x.toFixed(3)}</div>
        <div>y: {p.y.toFixed(3)}</div>
        <div>composite: {p.z.toFixed(3)}</div>
        {p.isPareto && <div className="text-emerald-600 font-semibold">★ Pareto</div>}
      </div>
    )
  }
  return null
}

export function ParetoExplorer({ candidates, paretoIds, onSelect }: ParetoExplorerProps) {
  const [xAxis, setXAxis] = useState<Axis>('predicted_mic')
  const [yAxis, setYAxis] = useState<Axis>('drug_likeness_qed')

  const data = useMemo<ScatterPoint[]>(() => {
    return candidates.map((c) => ({
      id: c.id,
      x: (c.scores as any)[xAxis] ?? 0,
      y: (c.scores as any)[yAxis] ?? 0,
      z: c.scores.composite,
      smiles: c.smiles,
      isPareto: paretoIds.includes(c.id),
    }))
  }, [candidates, paretoIds, xAxis, yAxis])

  const paretoData = data.filter((d) => d.isPareto)
  const otherData = data.filter((d) => !d.isPareto)

  if (candidates.length === 0) {
    return (
      <div className="text-slate-400 text-sm p-4">
        Pareto explorer plots candidates as they accumulate.
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-200 bg-slate-50">
        <label className="text-xs text-slate-500 flex items-center gap-1">
          x:
          <select
            value={xAxis}
            onChange={(e) => setXAxis(e.target.value as Axis)}
            className="bg-white border border-slate-300 rounded px-1.5 py-0.5 text-xs"
          >
            {AXES.map((a) => (
              <option key={a} value={a}>{AXIS_LABELS[a]}</option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-500 flex items-center gap-1">
          y:
          <select
            value={yAxis}
            onChange={(e) => setYAxis(e.target.value as Axis)}
            className="bg-white border border-slate-300 rounded px-1.5 py-0.5 text-xs"
          >
            {AXES.map((a) => (
              <option key={a} value={a}>{AXIS_LABELS[a]}</option>
            ))}
          </select>
        </label>
        <span className="ml-auto text-xs text-slate-500">
          {paretoData.length}/{data.length} on Pareto frontier
        </span>
      </div>

      <div className="flex-1 p-2 min-h-0">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart>
            <CartesianGrid stroke="#e2e8f0" />
            <XAxis
              dataKey="x"
              type="number"
              domain={[0, 1]}
              stroke="#475569"
              fontSize={10}
              label={{ value: AXIS_LABELS[xAxis], position: 'bottom', fill: '#475569', fontSize: 11 }}
            />
            <YAxis
              dataKey="y"
              type="number"
              domain={[0, 1]}
              stroke="#475569"
              fontSize={10}
              label={{ value: AXIS_LABELS[yAxis], angle: -90, position: 'left', fill: '#475569', fontSize: 11 }}
            />
            <ZAxis dataKey="z" range={[40, 200]} />
            <Tooltip content={<CustomTooltip />} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            <Scatter
              name="Pareto"
              data={paretoData}
              fill="#10b981"
              stroke="#059669"
              strokeWidth={2}
              onClick={(p: any) => onSelect?.(p.id)}
            />
            <Scatter
              name="Dominated"
              data={otherData}
              fill="#94a3b8"
              fillOpacity={0.5}
              onClick={(p: any) => onSelect?.(p.id)}
            />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

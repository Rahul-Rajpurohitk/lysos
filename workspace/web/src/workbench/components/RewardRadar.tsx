// 8-axis polar chart of the reward stack (light theme)

import {
  Radar, RadarChart, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Tooltip,
} from 'recharts'
import type { CandidateScores } from '../types'

interface RewardRadarProps {
  scores: CandidateScores
  comparison?: CandidateScores
}

const AXES = [
  { key: 'predicted_mic', label: 'MIC' },
  { key: 'drug_likeness_qed', label: 'QED' },
  { key: 'synthesizability', label: 'SA' },
  { key: 'hemolysis_safety', label: 'Safe' },
  { key: 'novelty', label: 'Tani-Nov' },
  { key: 'embedding_novelty', label: 'Sem-Nov' },
  { key: 'structural_alerts', label: 'Alerts' },
  { key: 'validity', label: 'Valid' },
] as const

export function RewardRadar({ scores, comparison }: RewardRadarProps) {
  const data = AXES.map((a) => ({
    axis: a.label,
    current: Number((scores[a.key as keyof CandidateScores] ?? 0).toFixed(3)),
    previous: comparison
      ? Number((comparison[a.key as keyof CandidateScores] ?? 0).toFixed(3))
      : undefined,
  }))

  return (
    <div className="w-full">
      <ResponsiveContainer width="100%" height={280}>
        <RadarChart data={data} margin={{ top: 16, right: 30, bottom: 8, left: 30 }}>
          <PolarGrid stroke="#cbd5e1" />
          <PolarAngleAxis dataKey="axis" stroke="#475569" fontSize={10} tickLine={false} />
          <PolarRadiusAxis stroke="#e2e8f0" tick={false} domain={[0, 1]} axisLine={false} />
          <Radar
            name="Current"
            dataKey="current"
            stroke="#059669"
            fill="#10b981"
            fillOpacity={0.32}
          />
          {comparison && (
            <Radar
              name="Previous"
              dataKey="previous"
              stroke="#0284c7"
              fill="#0ea5e9"
              fillOpacity={0.16}
            />
          )}
          <Tooltip
            wrapperStyle={{ outline: 'none', zIndex: 50 }}
            cursor={{ stroke: '#94a3b8', strokeDasharray: '3 3' }}
            position={{ y: -8 }}
            allowEscapeViewBox={{ x: true, y: true }}
            contentStyle={{
              background: 'rgba(15, 23, 42, 0.95)',
              border: 'none',
              borderRadius: 6,
              padding: '4px 8px',
              fontSize: 11,
              color: '#fff',
              boxShadow: '0 4px 12px -2px rgba(15,23,42,0.30)',
            }}
            labelStyle={{ color: '#94a3b8', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 2 }}
            itemStyle={{ color: '#fff', padding: 0, fontSize: 11 }}
          />
        </RadarChart>
      </ResponsiveContainer>
      {/* Component grid below — guaranteed-readable axis values, no tooltip needed */}
      <div className="grid grid-cols-4 gap-1 px-2 pb-1 mt-1">
        {data.map((d) => (
          <div key={d.axis} className="text-center">
            <div className="text-[8.5px] uppercase tracking-wider text-slate-400 font-semibold">{d.axis}</div>
            <div className="text-[11px] font-mono tabular-nums text-slate-700 font-semibold">{d.current.toFixed(2)}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

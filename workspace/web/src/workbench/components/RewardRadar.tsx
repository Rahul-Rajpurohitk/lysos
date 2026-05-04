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
    <ResponsiveContainer width="100%" height={300}>
      <RadarChart data={data}>
        <PolarGrid stroke="#cbd5e1" />
        <PolarAngleAxis dataKey="axis" stroke="#475569" fontSize={11} />
        <PolarRadiusAxis stroke="#cbd5e1" tick={false} domain={[0, 1]} />
        <Radar
          name="Current"
          dataKey="current"
          stroke="#059669"
          fill="#10b981"
          fillOpacity={0.35}
        />
        {comparison && (
          <Radar
            name="Previous"
            dataKey="previous"
            stroke="#0284c7"
            fill="#0ea5e9"
            fillOpacity={0.18}
          />
        )}
        <Tooltip
          contentStyle={{
            background: '#ffffff',
            border: '1px solid #e2e8f0',
            color: '#0f172a',
            fontSize: 12,
          }}
        />
      </RadarChart>
    </ResponsiveContainer>
  )
}

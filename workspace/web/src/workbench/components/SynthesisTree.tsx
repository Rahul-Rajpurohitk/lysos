// Synthesis route summary — uses predict_synthesis_route + estimate_synth_cost

import { useEffect, useState } from 'react'
import { invokeTool } from '../api'

interface SynthesisTreeProps {
  smiles: string | null
}

interface RouteData {
  sa_score: number
  estimated_steps: number
  estimated_cost_usd_per_g: number
  confidence_route_found: number
  interpretation: string
}

export function SynthesisTree({ smiles }: SynthesisTreeProps) {
  const [route, setRoute] = useState<RouteData | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!smiles) return
    setLoading(true)
    invokeTool('predict_synthesis_route', { smiles })
      .then((r) => setRoute(((r as any).result) ?? null))
      .catch(() => setRoute(null))
      .finally(() => setLoading(false))
  }, [smiles])

  if (!smiles) {
    return (
      <div className="text-slate-400 text-xs p-3">
        Synthesis route appears with a candidate.
      </div>
    )
  }

  if (loading || !route) {
    return (
      <div className="text-slate-500 text-xs p-3 animate-pulse">
        Calculating synthesis route…
      </div>
    )
  }

  // Visual: bar gauge of SA score (1=easy, 10=hard)
  const saPct = Math.min(100, (route.sa_score / 10) * 100)
  const saColor =
    route.sa_score <= 3 ? '#10b981'
    : route.sa_score <= 5 ? '#f59e0b'
    : route.sa_score <= 7 ? '#ef4444'
    : '#7c2d12'

  // Cost color
  const costColor =
    route.estimated_cost_usd_per_g <= 100 ? 'text-emerald-700'
    : route.estimated_cost_usd_per_g <= 500 ? 'text-amber-700'
    : route.estimated_cost_usd_per_g <= 5000 ? 'text-rose-700'
    : 'text-rose-900'

  return (
    <div className="p-3 space-y-3">
      <div>
        <div className="flex items-center justify-between text-xs mb-1">
          <span className="text-slate-500 uppercase">Synthetic accessibility</span>
          <span className="font-mono">{route.sa_score.toFixed(2)}/10</span>
        </div>
        <div className="h-2 bg-slate-100 rounded overflow-hidden">
          <div className="h-full transition-all" style={{ width: `${saPct}%`, background: saColor }} />
        </div>
        <div className="text-[10px] text-slate-500 mt-1">
          1 = easy · 10 = very hard
        </div>
      </div>

      <div className="grid grid-cols-3 gap-2">
        <div className="bg-slate-50 rounded p-2 border border-slate-200">
          <div className="text-[10px] uppercase text-slate-500">Steps</div>
          <div className="text-lg font-mono">{route.estimated_steps}</div>
        </div>
        <div className="bg-slate-50 rounded p-2 border border-slate-200">
          <div className="text-[10px] uppercase text-slate-500">Cost / g</div>
          <div className={`text-lg font-mono ${costColor}`}>
            ${route.estimated_cost_usd_per_g.toLocaleString()}
          </div>
        </div>
        <div className="bg-slate-50 rounded p-2 border border-slate-200">
          <div className="text-[10px] uppercase text-slate-500">Confidence</div>
          <div className="text-lg font-mono">
            {(route.confidence_route_found * 100).toFixed(0)}%
          </div>
        </div>
      </div>

      <div className="text-xs text-slate-700 leading-relaxed border-l-2 border-emerald-500 pl-2 bg-emerald-50/40 py-2">
        {route.interpretation}
      </div>

      <div className="text-[10px] text-slate-400">
        v0 SA-heuristic; AiZynthFinder retrosynthesis tree on Day 1.
      </div>
    </div>
  )
}

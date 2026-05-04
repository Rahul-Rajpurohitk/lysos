// Mechanism-of-action side panel — explains a candidate's MoA + resistance concerns
// via the explain_mechanism + check_resistance_genes tools.

import { useEffect, useState } from 'react'
import { Beaker, AlertTriangle, X } from 'lucide-react'
import { invokeTool } from '../api'
import type { Pathogen } from '../types'

interface MoAPanelProps {
  smiles: string | null
  pathogen: Pathogen
  onClose: () => void
}

interface MoAData {
  inferred_class: string
  mechanism_narrative: string
  resistance_concerns: string[]
}

interface ResistanceData {
  pathogen: string
  drug_class_inferred: string | null
  relevant_genes: { gene: string; affects: string[]; relevance: string }[]
  summary: string
}

export function MoAPanel({ smiles, pathogen, onClose }: MoAPanelProps) {
  const [moa, setMoa] = useState<MoAData | null>(null)
  const [resist, setResist] = useState<ResistanceData | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    if (!smiles) return
    setLoading(true)
    setErr(null)

    Promise.all([
      invokeTool('explain_mechanism', { smiles, target: pathogen }),
      invokeTool('check_resistance_genes', { pathogen, drug_class_or_smiles: smiles }),
    ])
      .then(([m, r]) => {
        setMoa(((m as any).result) ?? null)
        setResist(((r as any).result) ?? null)
      })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false))
  }, [smiles, pathogen])

  if (!smiles) return null

  return (
    <div className="absolute right-0 top-0 h-full w-[360px] bg-white border-l border-slate-200 shadow-xl z-20 flex flex-col">
      <div className="px-3 py-2 border-b border-slate-200 flex items-center justify-between bg-slate-50">
        <div className="flex items-center gap-2">
          <Beaker className="w-4 h-4 text-emerald-600" />
          <span className="text-xs font-semibold text-slate-700 uppercase tracking-wider">
            Mechanism of action
          </span>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-3 space-y-4 text-sm">
        <div>
          <div className="text-[10px] uppercase text-slate-500 mb-1">Candidate</div>
          <code className="text-xs font-mono text-slate-700 break-all">{smiles}</code>
        </div>

        {loading && (
          <div className="text-slate-500 text-sm animate-pulse">analyzing…</div>
        )}
        {err && (
          <div className="bg-rose-50 border border-rose-200 rounded p-2 text-rose-700 text-xs">
            {err}
          </div>
        )}

        {moa && (
          <div>
            <div className="text-[10px] uppercase text-slate-500 mb-1">Inferred class</div>
            <div className="text-emerald-700 font-mono text-sm mb-2">
              {moa.inferred_class}
            </div>

            <div className="text-[10px] uppercase text-slate-500 mb-1">Mechanism</div>
            <p className="text-sm leading-relaxed text-slate-700">
              {moa.mechanism_narrative}
            </p>

            {moa.resistance_concerns.length > 0 && (
              <>
                <div className="text-[10px] uppercase text-slate-500 mt-3 mb-1">
                  Resistance concerns
                </div>
                <ul className="text-xs space-y-0.5 text-rose-700">
                  {moa.resistance_concerns.map((c) => (
                    <li key={c}>• {c}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}

        {resist && resist.relevant_genes.length > 0 && (
          <div>
            <div className="text-[10px] uppercase text-slate-500 mb-1">
              {pathogen} resistome × this candidate
            </div>
            <div className="text-xs text-slate-600 mb-2 italic">
              {resist.summary}
            </div>
            <ul className="space-y-1.5">
              {resist.relevant_genes.slice(0, 6).map((g) => {
                const color =
                  g.relevance === 'high' ? 'border-rose-400 bg-rose-50 text-rose-700'
                  : g.relevance === 'medium' ? 'border-amber-400 bg-amber-50 text-amber-700'
                  : 'border-slate-200 bg-slate-50 text-slate-600'
                return (
                  <li key={g.gene} className={`border rounded p-1.5 ${color}`}>
                    <div className="flex items-start gap-1.5">
                      {g.relevance === 'high' && <AlertTriangle className="w-3 h-3 mt-0.5 shrink-0" />}
                      <div className="text-xs flex-1">
                        <div className="font-mono font-semibold">{g.gene}</div>
                        <div className="text-[10px] opacity-80 mt-0.5">
                          affects: {g.affects.join(', ')}
                        </div>
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          </div>
        )}
      </div>
    </div>
  )
}

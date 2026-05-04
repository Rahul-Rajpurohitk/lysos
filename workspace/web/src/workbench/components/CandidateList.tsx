// Compact list of candidates (light theme)

import clsx from 'clsx'
import type { Candidate } from '../types'

interface CandidateListProps {
  candidates: Candidate[]
  selectedId: string | null
  paretoIds: string[]
  onSelect: (id: string) => void
}

export function CandidateList({
  candidates, selectedId, paretoIds, onSelect,
}: CandidateListProps) {
  if (candidates.length === 0) {
    return (
      <div className="text-slate-400 text-xs p-3">
        Candidates appear as the agent proposes them.
      </div>
    )
  }
  return (
    <div className="space-y-1 p-2">
      {candidates.map((c, i) => {
        const isPareto = paretoIds.includes(c.id)
        const isSel = c.id === selectedId
        return (
          <button
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={clsx(
              'w-full text-left px-2 py-1.5 rounded border text-xs transition-colors',
              isSel
                ? 'bg-emerald-100 border-emerald-500 text-emerald-900'
                : 'border-slate-200 hover:bg-slate-50 text-slate-700',
            )}
          >
            <div className="flex items-center gap-2">
              <span className="font-mono text-[11px] text-slate-500">#{i + 1}</span>
              {isPareto && <span className="text-emerald-600 text-[10px] font-semibold">★ Pareto</span>}
              <span className="ml-auto font-mono text-[11px]">
                {c.scores.composite.toFixed(3)}
              </span>
            </div>
            <div className="font-mono text-[10px] truncate text-slate-500 mt-0.5">
              {c.smiles}
            </div>
            {c.similar_to.length > 0 && (
              <div className="text-[10px] text-slate-500 mt-0.5">
                ~ {c.similar_to.slice(0, 2).join(', ')}
              </div>
            )}
          </button>
        )
      })}
    </div>
  )
}

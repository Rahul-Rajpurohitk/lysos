// Constraint bar — declarative constraints the agent must honor.

import { useState } from 'react'
import { Plus, X } from 'lucide-react'
import type { Constraint } from '../types'

interface ConstraintBarProps {
  constraints: Constraint[]
  onAdd: (c: Constraint) => void
  onRemove: (idx: number) => void
  disabled?: boolean
}

const PRESETS: { label: string; constraint: Constraint }[] = [
  { label: 'logP < 5',         constraint: { type: 'property_max', field: 'logp', value: 5 } },
  { label: 'MW < 500',         constraint: { type: 'property_max', field: 'mw', value: 500 } },
  { label: 'QED > 0.5',        constraint: { type: 'property_min', field: 'qed', value: 0.5 } },
  { label: 'TPSA < 140',       constraint: { type: 'property_max', field: 'tpsa', value: 140 } },
  { label: 'no PAINS',         constraint: { type: 'exclude_smarts', field: 'pains', value: '[*]' } },
  { label: 'no Michael accept',constraint: { type: 'exclude_smarts', field: 'michael', value: 'C=CC=O' } },
  { label: 'beta-lactam core', constraint: { type: 'require_smarts', field: 'beta_lactam', value: '[NX3]1[CX3](=O)[CX4][CX4]1' } },
  { label: 'thiazole',         constraint: { type: 'require_smarts', field: 'thiazole', value: 'c1scnc1' } },
]

export function ConstraintBar({ constraints, onAdd, onRemove, disabled }: ConstraintBarProps) {
  const [showMenu, setShowMenu] = useState(false)

  return (
    <div className="px-3 py-2 bg-slate-50 border-t border-slate-200 flex items-center gap-2 flex-wrap relative">
      <span className="text-[10px] uppercase tracking-wider text-slate-500">
        Constraints
      </span>

      {constraints.map((c, i) => (
        <span
          key={`${c.type}:${c.field}:${i}`}
          className="inline-flex items-center gap-1.5 px-2 py-1 rounded bg-white border border-slate-300 text-xs"
        >
          <span className="font-mono">
            {c.type === 'property_max' && `${c.field} < ${c.value}`}
            {c.type === 'property_min' && `${c.field} > ${c.value}`}
            {c.type === 'exclude_smarts' && `exclude ${c.field}`}
            {c.type === 'require_smarts' && `require ${c.field}`}
          </span>
          {!disabled && (
            <button
              onClick={() => onRemove(i)}
              className="text-slate-400 hover:text-rose-600"
            >
              <X className="w-3 h-3" />
            </button>
          )}
        </span>
      ))}

      <button
        onClick={() => setShowMenu((v) => !v)}
        disabled={disabled}
        className="inline-flex items-center gap-1 px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs disabled:opacity-30"
      >
        <Plus className="w-3 h-3" />
        Add
      </button>

      {showMenu && (
        <div className="absolute top-full left-0 mt-1 z-30 bg-white border border-slate-200 rounded shadow-lg p-2 grid grid-cols-2 gap-1">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => { onAdd(p.constraint); setShowMenu(false) }}
              className="text-left px-2 py-1 rounded hover:bg-slate-100 text-xs"
            >
              {p.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

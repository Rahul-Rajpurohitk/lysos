// Paste an abstract or paragraph → agent extracts constraints automatically.
// Uses heuristic regex on common phrases — Day 1 swap with LLM.

import { useState } from 'react'
import { Sparkles, Plus } from 'lucide-react'
import type { Constraint } from '../types'

interface ConstraintFromPaperProps {
  onAdd: (c: Constraint) => void
}

function extractConstraints(text: string): Constraint[] {
  const t = text.toLowerCase()
  const out: Constraint[] = []

  // logP < N or "lipophilicity less than N"
  const logp = t.match(/log\s*p\s*[<≤]\s*(\d+(?:\.\d+)?)/i)
  if (logp) out.push({ type: 'property_max', field: 'logp', value: Number(logp[1]) })

  // MW < N
  const mw = t.match(/m(?:olecular\s*)?w(?:eight)?\s*[<≤]\s*(\d+(?:\.\d+)?)/i)
  if (mw) out.push({ type: 'property_max', field: 'mw', value: Number(mw[1]) })

  // QED > N
  const qed = t.match(/qed\s*[>≥]\s*(\d+(?:\.\d+)?)/i)
  if (qed) out.push({ type: 'property_min', field: 'qed', value: Number(qed[1]) })

  // TPSA < N
  const tpsa = t.match(/tpsa\s*[<≤]\s*(\d+(?:\.\d+)?)/i)
  if (tpsa) out.push({ type: 'property_max', field: 'tpsa', value: Number(tpsa[1]) })

  // Lipinski / Veber / drug-likeness mentions → exclude PAINS
  if (/lipinski|drug.?like|veber|rule.?of.?five/.test(t)) {
    out.push({ type: 'exclude_smarts', field: 'pains', value: '[*]' })
  }

  // Beta-lactam / cephalosporin / carbapenem scaffold mentions → require core
  if (/beta.?lactam/.test(t)) {
    out.push({ type: 'require_smarts', field: 'beta_lactam',
              value: '[NX3]1[CX3](=O)[CX4][CX4]1' })
  }
  if (/thiazole/.test(t)) {
    out.push({ type: 'require_smarts', field: 'thiazole', value: 'c1scnc1' })
  }
  if (/triazole|1,2,4.?triazole/.test(t)) {
    out.push({ type: 'require_smarts', field: 'triazole', value: 'c1ncnn1' })
  }

  // Avoid PAINS / Michael acceptors
  if (/pains?|reactive\s*group|michael/.test(t)) {
    out.push({ type: 'exclude_smarts', field: 'michael', value: 'C=CC=O' })
  }

  return out
}

export function ConstraintFromPaper({ onAdd }: ConstraintFromPaperProps) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState('')
  const [extracted, setExtracted] = useState<Constraint[]>([])

  function handleExtract() {
    setExtracted(extractConstraints(text))
  }

  function handleApply() {
    extracted.forEach(onAdd)
    setExtracted([])
    setText('')
    setOpen(false)
  }

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-1 px-2 py-1 rounded bg-violet-100 hover:bg-violet-200 text-violet-700 text-xs"
        title="Paste a paper abstract to extract constraints"
      >
        <Sparkles className="w-3 h-3" />
        From paper
      </button>
    )
  }

  return (
    <div className="bg-white border border-violet-300 rounded p-2 shadow-sm flex flex-col gap-2 w-full">
      <div className="flex items-center gap-2">
        <Sparkles className="w-3.5 h-3.5 text-violet-600" />
        <span className="text-xs font-semibold text-violet-700">
          Extract constraints from text
        </span>
        <button
          onClick={() => setOpen(false)}
          className="ml-auto text-slate-400 hover:text-slate-600 text-xs"
        >
          cancel
        </button>
      </div>

      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={4}
        placeholder="Paste an abstract / constraints paragraph. e.g. 'logP < 4, MW < 500, QED > 0.6, must contain a beta-lactam core, exclude PAINS.'"
        className="w-full text-xs p-2 border border-slate-200 rounded font-mono"
      />

      <div className="flex items-center gap-2">
        <button
          onClick={handleExtract}
          disabled={!text.trim()}
          className="px-2 py-1 rounded bg-violet-600 hover:bg-violet-700 text-white text-xs disabled:opacity-30"
        >
          Extract
        </button>
        {extracted.length > 0 && (
          <button
            onClick={handleApply}
            className="px-2 py-1 rounded bg-emerald-600 hover:bg-emerald-700 text-white text-xs flex items-center gap-1"
          >
            <Plus className="w-3 h-3" />
            Apply {extracted.length} constraint(s)
          </button>
        )}
      </div>

      {extracted.length > 0 && (
        <div className="text-xs text-slate-700">
          <div className="text-[10px] uppercase text-slate-500 mb-1">Found</div>
          <ul className="space-y-0.5">
            {extracted.map((c, i) => (
              <li key={i} className="font-mono">
                • {c.type === 'property_max' && `${c.field} < ${c.value}`}
                {c.type === 'property_min' && `${c.field} > ${c.value}`}
                {c.type === 'exclude_smarts' && `exclude ${c.field}`}
                {c.type === 'require_smarts' && `require ${c.field}`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

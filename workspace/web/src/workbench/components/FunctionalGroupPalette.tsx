// Drag-edit palette — apply named transformations to the current candidate.
// Calls transform_structure tool when a button is clicked (drag-drop is v2).

import { useState } from 'react'
import { invokeTool } from '../api'

interface FunctionalGroupPaletteProps {
  smiles: string
  onTransform: (newSmiles: string, op: string) => void
}

const OPS: { id: string; label: string; tint: string; tooltip: string }[] = [
  { id: 'add_hydroxyl',      label: '–OH',     tint: 'bg-rose-100 text-rose-700',     tooltip: 'Add hydroxyl' },
  { id: 'add_fluorine',      label: '–F',      tint: 'bg-sky-100 text-sky-700',       tooltip: 'Add fluorine' },
  { id: 'add_methyl',        label: '–CH₃',    tint: 'bg-amber-100 text-amber-700',   tooltip: 'Add methyl' },
  { id: 'add_amine',         label: '–NH₂',    tint: 'bg-violet-100 text-violet-700', tooltip: 'Add amine' },
  { id: 'add_carboxyl',      label: '–COOH',   tint: 'bg-emerald-100 text-emerald-700', tooltip: 'Add carboxyl' },
  { id: 'add_sulfonamide',   label: '–SO₂NH', tint: 'bg-indigo-100 text-indigo-700', tooltip: 'Cap amine with sulfonamide' },
  { id: 'swap_chloro_to_fluoro', label: 'Cl→F', tint: 'bg-cyan-100 text-cyan-700',   tooltip: 'Replace -Cl with -F' },
  { id: 'swap_fluoro_to_chloro', label: 'F→Cl', tint: 'bg-cyan-50 text-cyan-700',    tooltip: 'Replace -F with -Cl' },
  { id: 'remove_methyl',     label: '−CH₃',    tint: 'bg-slate-200 text-slate-700',   tooltip: 'Strip a methyl' },
  { id: 'ring_close',        label: 'ring',    tint: 'bg-pink-100 text-pink-700',     tooltip: 'Close 5-ring' },
]

export function FunctionalGroupPalette({ smiles, onTransform }: FunctionalGroupPaletteProps) {
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)

  async function apply(op: string) {
    setBusy(op)
    setErr(null)
    try {
      const res = (await invokeTool('transform_structure', { smiles, op })) as any
      const products = res?.result?.products
      if (!products || products.length === 0) {
        setErr(`${op}: no products`)
      } else {
        onTransform(products[0], op)
      }
    } catch (e) {
      setErr(String(e))
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="px-3 py-2 bg-slate-50 border-t border-slate-200 flex items-center gap-2 flex-wrap">
      <span className="text-[10px] uppercase tracking-wider text-slate-500">
        Drag-edit
      </span>
      {OPS.map((op) => (
        <button
          key={op.id}
          onClick={() => apply(op.id)}
          disabled={!smiles || busy === op.id}
          title={op.tooltip}
          className={`px-2 py-1 rounded text-xs font-mono ${op.tint} hover:opacity-80 disabled:opacity-30 transition-opacity`}
        >
          {busy === op.id ? '…' : op.label}
        </button>
      ))}
      {err && <span className="text-[10px] text-rose-600 ml-2">{err}</span>}
    </div>
  )
}

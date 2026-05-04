// Atomic playground — 3Dmol.js viewer with chemistry-correct rendering.
//
// Pipeline:
//   1. SMILES  -> POST /workbench/molecule/3d  (RDKit ETKDG embed + MMFF)
//                  returns SDF with explicit 3D coordinates + metadata
//   2. PDB     -> https://files.rcsb.org/download/{id}.pdb
//   3. Pocket  -> GET /workbench/pathogen/{code}/pocket  (binding-site center)
//   4. Render  -> protein cartoon (transparent) + pocket surface +
//                  ligand ball-and-stick (CPK colors)
//
// Features:
//   - Top toolbar: protein viz · ligand viz · surface · spin · reset
//   - Bottom-left: energy / formula / MW / logP readout
//   - Bottom-right: atom-hover tooltip with element + valence + degree
//   - Pocket-aware translation: the ligand is moved into the binding
//     pocket so the viewer shows the actual interaction context.

import { useEffect, useRef, useState } from 'react'
import {
  RotateCcw, RefreshCw, Eye, EyeOff, Atom, Sparkles, Layers, Loader2,
} from 'lucide-react'
import type { Pathogen } from '../types'

interface MolViewerProps {
  smiles?: string
  pdbId?: string
  pathogen?: Pathogen
  className?: string
  // Called when the user edits the molecule via atom-click → swap-element
  // or add-methyl. Receives the new canonical SMILES.
  onMoleculeEdit?: (newSmiles: string, op: string) => void
}

declare global {
  interface Window { $3Dmol?: any }
}

type ProteinStyle = 'cartoon' | 'cartoon-transparent' | 'surface' | 'none'
type LigandStyle = 'ball-stick' | 'spacefill' | 'wireframe' | 'stick'

interface MolMeta {
  n_atoms: number
  n_bonds: number
  energy: number | null
  formula: string
  mw: number
  logp: number
  elements: Record<string, number>
}

const ELEMENT_COLORS: Record<string, string> = {
  C: '#414754', H: '#cbd5e1', N: '#3b82f6', O: '#ef4444',
  F: '#10b981', S: '#facc15', Cl: '#22c55e', Br: '#a855f7',
  P: '#f97316', I: '#7c3aed',
}

export function MolViewer({ smiles, pdbId, pathogen, className, onMoleculeEdit }: MolViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<any>(null)
  const ligandModelRef = useRef<any>(null)
  const [proteinStyle, setProteinStyle] = useState<ProteinStyle>('cartoon-transparent')
  const [ligandStyle, setLigandStyle] = useState<LigandStyle>('ball-stick')
  const [showSurface, setShowSurface] = useState(false)
  const [spinning, setSpinning] = useState(false)
  const [meta, setMeta] = useState<MolMeta | null>(null)
  const [hoverAtom, setHoverAtom] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  // Click-edit popover state — atom index + screen-space coords
  const [editPopover, setEditPopover] = useState<{
    atomIdx: number; x: number; y: number
  } | null>(null)
  const [editing, setEditing] = useState(false)

  // Load 3Dmol.js once, render whenever inputs change
  useEffect(() => {
    let cancelled = false

    async function ensure3Dmol() {
      if (window.$3Dmol) return
      await new Promise<void>((resolve, reject) => {
        const script = document.createElement('script')
        script.src = 'https://3Dmol.org/build/3Dmol-min.js'
        script.onload = () => resolve()
        script.onerror = () => reject(new Error('Failed to load 3Dmol'))
        document.head.appendChild(script)
      })
    }

    async function render() {
      setError(null)
      setLoading(true)
      try {
        await ensure3Dmol()
        if (cancelled || !containerRef.current || !window.$3Dmol) return

        if (!viewerRef.current) {
          viewerRef.current = window.$3Dmol.createViewer(containerRef.current, {
            backgroundColor: '#fafbfc',
          })
        }

        const viewer = viewerRef.current
        viewer.removeAllModels()
        viewer.removeAllShapes()
        viewer.removeAllSurfaces()
        ligandModelRef.current = null

        // -------- protein --------
        let pocketCenter: [number, number, number] | null = null
        if (pdbId) {
          const [pdb, pocketRes] = await Promise.all([
            fetch(`https://files.rcsb.org/download/${pdbId}.pdb`).then((r) => r.text()),
            pathogen
              ? fetch(`/workbench/pathogen/${pathogen}/pocket`)
                  .then((r) => r.ok ? r.json() : null).catch(() => null)
              : Promise.resolve(null),
          ])
          if (cancelled) return
          viewer.addModel(pdb, 'pdb')
          applyProteinStyle(viewer, proteinStyle)
          if (pocketRes?.pocket_center) {
            const c = pocketRes.pocket_center
            pocketCenter = [c.x, c.y, c.z]
          }
        }

        // -------- ligand from RDKit (proper 3D) --------
        if (smiles) {
          const r = await fetch('/workbench/molecule/3d', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ smiles, optimize: true, add_hydrogens: true }),
          })
          if (!r.ok) {
            const detail = await r.json().catch(() => null)
            throw new Error(detail?.detail ?? `molecule/3d ${r.status}`)
          }
          const data = await r.json()
          if (cancelled) return

          setMeta({
            n_atoms: data.n_atoms, n_bonds: data.n_bonds,
            energy: data.energy_kcal_mol,
            formula: data.formula, mw: data.mw, logp: data.logp,
            elements: data.element_counts,
          })

          const m = viewer.addModel(data.sdf, 'sdf')
          ligandModelRef.current = m

          // Translate ligand to pocket center if available
          if (pocketCenter) {
            const atoms = m.selectedAtoms({})
            // Compute current centroid of the ligand
            let cx = 0, cy = 0, cz = 0
            for (const a of atoms) { cx += a.x; cy += a.y; cz += a.z }
            cx /= atoms.length; cy /= atoms.length; cz /= atoms.length
            const dx = pocketCenter[0] - cx
            const dy = pocketCenter[1] - cy
            const dz = pocketCenter[2] - cz
            for (const a of atoms) { a.x += dx; a.y += dy; a.z += dz }
          }

          applyLigandStyle(viewer, ligandStyle)
          attachAtomHover(viewer, setHoverAtom)
          attachAtomClick(viewer, m, (atomIdx, x, y) => {
            setEditPopover({ atomIdx, x, y })
          })
        } else {
          setMeta(null)
        }

        // -------- pocket surface --------
        if (showSurface && pocketCenter) {
          const [px, py, pz] = pocketCenter
          viewer.addSurface(window.$3Dmol.SurfaceType.SAS, {
            opacity: 0.45,
            color: '#fbbf24',
          }, { within: { distance: 8.0, sel: { x: px, y: py, z: pz } } })
        } else if (showSurface) {
          viewer.addSurface(window.$3Dmol.SurfaceType.VDW, {
            opacity: 0.25, color: '#94a3b8',
          })
        }

        // -------- camera --------
        // Zoom tight on the LIGAND model using the stored model reference.
        // Plain {model:-1} sometimes frames the whole scene; targeting the
        // ligand by atom-array gets a clean tight bbox.
        if (ligandModelRef.current) {
          const ligAtoms = ligandModelRef.current.selectedAtoms({})
          if (ligAtoms.length) {
            // Compute centroid + bbox manually to control zoom factor
            let minx = +Infinity, miny = +Infinity, minz = +Infinity
            let maxx = -Infinity, maxy = -Infinity, maxz = -Infinity
            for (const a of ligAtoms) {
              if (a.x < minx) minx = a.x; if (a.x > maxx) maxx = a.x
              if (a.y < miny) miny = a.y; if (a.y > maxy) maxy = a.y
              if (a.z < minz) minz = a.z; if (a.z > maxz) maxz = a.z
            }
            viewer.center({
              x: (minx + maxx) / 2, y: (miny + maxy) / 2, z: (minz + maxz) / 2,
            }, 0)
            // Use atom selection for zoomTo so 3Dmol fits the ligand box
            viewer.zoomTo({ serial: ligAtoms.map((a: any) => a.serial) })
            // Pull camera in slightly so the ligand fills more of the view
            viewer.zoom(1.4, 200)
          } else {
            viewer.zoomTo()
          }
        } else {
          viewer.zoomTo()
        }
        viewer.render()
        if (spinning) viewer.spin('y')
        else viewer.spin(false)
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err)
        setError(msg)
      } finally {
        setLoading(false)
      }
    }

    render()
    return () => { cancelled = true }
  }, [smiles, pdbId, pathogen, proteinStyle, ligandStyle, showSurface, spinning])

  // Hide the toolbar entirely while the hero/empty state is showing —
  // otherwise the floating buttons clip the title.
  const hasContent = Boolean(smiles)

  return (
    <div className={className ?? 'w-full h-full relative'}>
      <div
        ref={containerRef}
        className="absolute inset-0"
        style={{ background: '#fafbfc' }}
      />

      {/* Top toolbar — only when a ligand is loaded so it never overlaps onboarding */}
      {hasContent && (
      <div className="absolute top-2 right-2 z-10 flex items-center gap-1 bg-white/95 backdrop-blur border border-slate-200 rounded-md p-0.5 shadow-sm">
        <ToolbarSelect
          icon={<Layers className="h-3 w-3" />}
          value={proteinStyle}
          onChange={(v) => setProteinStyle(v as ProteinStyle)}
          options={[
            { id: 'cartoon-transparent', label: 'Cartoon (T)' },
            { id: 'cartoon', label: 'Cartoon' },
            { id: 'surface', label: 'Surface' },
            { id: 'none', label: 'No protein' },
          ]}
        />
        <Sep />
        <ToolbarSelect
          icon={<Atom className="h-3 w-3" />}
          value={ligandStyle}
          onChange={(v) => setLigandStyle(v as LigandStyle)}
          options={[
            { id: 'ball-stick', label: 'Ball+stick' },
            { id: 'spacefill', label: 'Spacefill' },
            { id: 'stick', label: 'Sticks' },
            { id: 'wireframe', label: 'Wireframe' },
          ]}
        />
        <Sep />
        <ToolbarToggle
          on={showSurface}
          onClick={() => setShowSurface((v) => !v)}
          icon={showSurface ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
          label="Pocket"
        />
        <ToolbarToggle
          on={spinning}
          onClick={() => setSpinning((v) => !v)}
          icon={<RotateCcw className="h-3 w-3" />}
          label="Spin"
        />
        <ToolbarBtn
          onClick={() => { viewerRef.current?.zoomTo({ model: -1 }); viewerRef.current?.render() }}
          icon={<RefreshCw className="h-3 w-3" />}
          label="Recenter"
        />
      </div>
      )}

      {/* Atom-click edit popover */}
      {editPopover && smiles && (
        <AtomEditPopover
          atomIdx={editPopover.atomIdx}
          x={editPopover.x}
          y={editPopover.y}
          containerRef={containerRef}
          editing={editing}
          onClose={() => setEditPopover(null)}
          onApply={async (op, payload) => {
            if (!smiles) return
            setEditing(true)
            try {
              const r = await fetch('/workbench/molecule/edit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                  smiles, op, atom_index: editPopover.atomIdx, ...payload,
                }),
              })
              const data = await r.json()
              if (!r.ok) {
                setError(data?.detail ?? `edit failed`)
                return
              }
              setEditPopover(null)
              onMoleculeEdit?.(data.smiles, op)
            } catch (e) {
              setError(String(e))
            } finally {
              setEditing(false)
            }
          }}
        />
      )}

      {/* Energy / metadata readout (bottom-left) */}
      {meta && (
        <div className="absolute bottom-2 left-2 z-10 bg-white/95 backdrop-blur border border-slate-200 rounded-md px-2.5 py-1.5 shadow-sm font-mono text-[10.5px] text-slate-700 leading-snug">
          <div className="flex items-center gap-2 mb-0.5">
            <Sparkles className="h-3 w-3 text-emerald-600" />
            <span className="font-semibold text-slate-900">{meta.formula}</span>
            <span className="text-slate-400">·</span>
            <span>MW {meta.mw}</span>
            <span className="text-slate-400">·</span>
            <span>logP {meta.logp.toFixed(2)}</span>
          </div>
          <div className="flex items-center gap-2 text-slate-500">
            <span>{meta.n_atoms} atoms · {meta.n_bonds} bonds</span>
            {meta.energy != null && (
              <>
                <span className="text-slate-300">|</span>
                <span title="MMFF94s minimized energy">
                  <span className="text-slate-400">E</span> {meta.energy.toFixed(1)} kcal/mol
                </span>
              </>
            )}
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            {Object.entries(meta.elements).map(([el, n]) => (
              <span
                key={el}
                className="inline-flex items-center gap-0.5 text-[10px] font-mono"
              >
                <span
                  className="inline-block h-1.5 w-1.5 rounded-full"
                  style={{ background: ELEMENT_COLORS[el] ?? '#94a3b8' }}
                />
                <span className="text-slate-700 font-semibold">{el}</span>
                <span className="text-slate-400">{n}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Atom hover tooltip (bottom-right) */}
      {hoverAtom && (
        <div className="absolute bottom-2 right-2 z-10 bg-slate-900/90 text-white rounded-md px-2 py-1 text-[10px] font-mono shadow-lg pointer-events-none">
          {hoverAtom}
        </div>
      )}

      {loading && (
        <div className="absolute top-2 left-2 z-10 bg-white/90 border border-slate-200 rounded px-2 py-1 text-[10px] font-mono text-slate-500">
          embedding 3D…
        </div>
      )}
      {error && (
        <div className="absolute top-2 left-2 z-10 bg-rose-50 border border-rose-200 rounded px-2 py-1 text-[10px] text-rose-700">
          ⚠ {error}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Style helpers
// ---------------------------------------------------------------------------
// IMPORTANT: select by model index, NOT by hetflag.
// SDF-loaded atoms don't have hetflag set, so a hetflag=false selector
// for the protein silently catches the ligand carbons too — which is
// what produced the brown / spectrum-coloured ligand atoms before.
function applyProteinStyle(viewer: any, style: ProteinStyle) {
  const sel = { model: 0 }   // first model is always the PDB
  viewer.setStyle(sel, {})
  if (style === 'none') return
  if (style === 'cartoon') {
    viewer.setStyle(sel, { cartoon: { color: 'spectrum' } })
  } else if (style === 'cartoon-transparent') {
    viewer.setStyle(sel, { cartoon: { color: 'spectrum', opacity: 0.55 } })
  } else if (style === 'surface') {
    viewer.setStyle(sel, { cartoon: { color: 'spectrum', opacity: 0.2 } })
    viewer.addSurface(window.$3Dmol.SurfaceType.VDW, {
      opacity: 0.55, color: '#cbd5e1',
    }, sel)
  }
}

function applyLigandStyle(viewer: any, style: LigandStyle) {
  // Ligand = the LAST model added (the SDF we just embedded).
  const sel = { model: -1 }
  viewer.setStyle(sel, {})
  if (style === 'ball-stick') {
    viewer.setStyle(sel, {
      stick: { radius: 0.20, colorscheme: 'Jmol' },
      sphere: { radius: 0.34, colorscheme: 'Jmol' },
    })
  } else if (style === 'spacefill') {
    viewer.setStyle(sel, { sphere: { colorscheme: 'Jmol' } })
  } else if (style === 'stick') {
    viewer.setStyle(sel, { stick: { radius: 0.24, colorscheme: 'Jmol' } })
  } else if (style === 'wireframe') {
    viewer.setStyle(sel, { line: { linewidth: 2, colorscheme: 'Jmol' } })
  }
}

function attachAtomClick(
  _viewer: any,
  ligandModel: any,
  onPick: (atomIdx: number, x: number, y: number) => void,
) {
  // 3Dmol clickable: per-atom callback. We compute the SDF-local atom index
  // from the atom's `index` field (set by 3Dmol when reading SDF).
  ligandModel.setClickable({}, true, function (atom: any, _viewer: any, event: any) {
    const idx = atom.index ?? atom.serial ?? 0
    const x = event?.clientX ?? event?.x ?? 0
    const y = event?.clientY ?? event?.y ?? 0
    onPick(idx, x, y)
  })
}

function attachAtomHover(viewer: any, set: (s: string | null) => void) {
  viewer.setHoverable(
    { model: -1 },
    true,
    function (atom: any) {
      const el = atom?.elem ?? '?'
      const valence = atom?.bonds?.length ?? 0
      const charge = atom?.formalCharge ?? 0
      const chargeStr = charge ? ` · q=${charge > 0 ? '+' : ''}${charge}` : ''
      set(`${el} #${atom?.serial ?? '?'} · ${valence} bonds${chargeStr}`)
    },
    function () { set(null) }
  )
}

// ---------------------------------------------------------------------------
// Tiny toolbar primitives
// ---------------------------------------------------------------------------
function ToolbarSelect(props: {
  icon: React.ReactNode
  value: string
  onChange: (v: string) => void
  options: { id: string; label: string }[]
}) {
  return (
    <label className="inline-flex items-center gap-1 px-1.5 h-6 rounded text-[10px] text-slate-600 hover:bg-slate-100 cursor-pointer">
      <span className="text-slate-500">{props.icon}</span>
      <select
        value={props.value}
        onChange={(e) => props.onChange(e.target.value)}
        className="bg-transparent text-[10px] outline-none cursor-pointer pr-0.5"
      >
        {props.options.map((o) => (
          <option key={o.id} value={o.id}>{o.label}</option>
        ))}
      </select>
    </label>
  )
}

function ToolbarToggle(props: {
  on: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      onClick={props.onClick}
      title={props.label}
      className={[
        'inline-flex items-center gap-1 px-1.5 h-6 rounded text-[10px] transition',
        props.on
          ? 'bg-emerald-100 text-emerald-700'
          : 'text-slate-600 hover:bg-slate-100',
      ].join(' ')}
    >
      {props.icon}<span>{props.label}</span>
    </button>
  )
}

function ToolbarBtn(props: { onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      onClick={props.onClick}
      title={props.label}
      className="inline-flex items-center gap-1 px-1.5 h-6 rounded text-[10px] text-slate-600 hover:bg-slate-100 transition"
    >
      {props.icon}<span>{props.label}</span>
    </button>
  )
}

function Sep() { return <span className="h-3 w-px bg-slate-200 mx-0.5" /> }

// ---------------------------------------------------------------------------
// AtomEditPopover — appears at click position; lets the user swap the atom's
// element OR add a methyl substituent. Backend sanitises chemistry.
// ---------------------------------------------------------------------------
const SWAP_ELEMENTS = [
  { sym: 'C',  bg: '#414754', text: '#fff' },
  { sym: 'N',  bg: '#3b82f6', text: '#fff' },
  { sym: 'O',  bg: '#ef4444', text: '#fff' },
  { sym: 'F',  bg: '#10b981', text: '#fff' },
  { sym: 'S',  bg: '#facc15', text: '#000' },
  { sym: 'Cl', bg: '#22c55e', text: '#fff' },
  { sym: 'Br', bg: '#a855f7', text: '#fff' },
]

interface AtomEditPopoverProps {
  atomIdx: number
  x: number
  y: number
  containerRef: React.RefObject<HTMLDivElement>
  editing: boolean
  onClose: () => void
  onApply: (op: 'swap_element' | 'add_methyl_at', payload?: Record<string, unknown>) => void
}

function AtomEditPopover(props: AtomEditPopoverProps) {
  const { atomIdx, x, y, containerRef, editing, onClose, onApply } = props
  // Translate page-space click coords into local coords inside the container
  const rect = containerRef.current?.getBoundingClientRect()
  const left = Math.max(8, Math.min((rect?.width ?? 800) - 240, x - (rect?.left ?? 0) - 120))
  const top = Math.max(8, Math.min((rect?.height ?? 600) - 140, y - (rect?.top ?? 0) - 12))

  return (
    <>
      {/* Click-out catcher */}
      <div className="absolute inset-0 z-20" onClick={onClose} />
      <div
        className="absolute z-30 bg-white border border-slate-200 rounded-lg shadow-2xl p-2.5 min-w-[240px]"
        style={{ left, top }}
      >
        <div className="flex items-center gap-2 mb-2">
          <span className="text-[10px] uppercase tracking-widest text-slate-400 font-bold">
            Edit atom #{atomIdx}
          </span>
          {editing && <Loader2 className="h-3 w-3 text-slate-400 animate-spin" />}
          <button
            onClick={onClose}
            className="ml-auto text-slate-400 hover:text-slate-700 text-[10px]"
          >
            close
          </button>
        </div>
        <div className="text-[10px] text-slate-500 mb-1.5">Swap to element</div>
        <div className="flex flex-wrap gap-1 mb-2">
          {SWAP_ELEMENTS.map((el) => (
            <button
              key={el.sym}
              disabled={editing}
              onClick={() => onApply('swap_element', { new_element: el.sym })}
              title={`Replace this atom with ${el.sym}`}
              className="h-7 min-w-[28px] px-1.5 rounded font-mono font-bold text-[11px] hover:scale-110 transition-transform shadow-sm disabled:opacity-50"
              style={{ background: el.bg, color: el.text }}
            >
              {el.sym}
            </button>
          ))}
        </div>
        <div className="border-t border-slate-100 pt-2">
          <button
            disabled={editing}
            onClick={() => onApply('add_methyl_at')}
            className="w-full inline-flex items-center justify-center gap-1.5 h-7 rounded bg-slate-100 hover:bg-slate-200 text-[11px] font-semibold text-slate-700 disabled:opacity-50"
          >
            <Sparkles className="h-3 w-3" /> Add methyl (–CH₃)
          </button>
        </div>
        <div className="text-[9.5px] text-slate-400 mt-1.5 text-center">
          Backend validates valence + sanitises with RDKit.
        </div>
      </div>
    </>
  )
}


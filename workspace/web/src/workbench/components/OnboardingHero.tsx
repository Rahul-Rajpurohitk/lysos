// Pre-flight hero — shown on the 3D viewer surface when no candidate is
// loaded yet. Communicates what the workbench does, what the user gets,
// and the agent pipeline visually. Replaces the empty "no model" stare.

import { FlaskConical, ScanSearch, PenLine, Compass, ArrowRight, Sparkles, Atom, Layers, GitBranch, FileDown, Bot, Database, Workflow } from 'lucide-react'

interface OnboardingHeroProps {
  pathogenName?: string
  pathogenCode?: string
  resistomeCount?: number
  firstLineCount?: number
  onStart?: () => void
  running?: boolean
}

const PIPELINE = [
  { Icon: Compass,      label: 'Strategist', sub: 'loads resistome',          color: 'violet'  },
  { Icon: FlaskConical, label: 'Designer',   sub: 'proposes SMILES',          color: 'emerald' },
  { Icon: ScanSearch,   label: 'Critic',     sub: 'scores · finds weakness',  color: 'rose'    },
  { Icon: PenLine,      label: 'Editor',     sub: 'transforms · re-scores',   color: 'sky'     },
] as const

const COLOR_MAP: Record<string, { ring: string; bg: string; text: string; dot: string }> = {
  violet:  { ring: 'ring-violet-200',  bg: 'bg-violet-50',  text: 'text-violet-700',  dot: 'bg-violet-500'  },
  emerald: { ring: 'ring-emerald-200', bg: 'bg-emerald-50', text: 'text-emerald-700', dot: 'bg-emerald-500' },
  rose:    { ring: 'ring-rose-200',    bg: 'bg-rose-50',    text: 'text-rose-700',    dot: 'bg-rose-500'    },
  sky:     { ring: 'ring-sky-200',     bg: 'bg-sky-50',     text: 'text-sky-700',     dot: 'bg-sky-500'     },
}

const DELIVERABLES = [
  { Icon: Atom,      label: 'Novel SMILES',     hint: 'scored across 8 reward axes' },
  { Icon: Layers,    label: 'Pareto frontier',  hint: 'trade-off explorer · radar'  },
  { Icon: GitBranch, label: 'Lineage',          hint: 'edits + parent-child tree'   },
  { Icon: FileDown,  label: 'Notebook',         hint: 'Jupyter export, reproducible' },
]

export function OnboardingHero(props: OnboardingHeroProps) {
  const { pathogenName, pathogenCode, resistomeCount, firstLineCount, onStart, running } = props
  return (
    <div className="absolute inset-0 overflow-auto flex items-center justify-center p-6">
      <div className="max-w-[640px] w-full">
        {/* Eyebrow + title */}
        <div className="text-center mb-5">
          <div className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-emerald-50 ring-1 ring-emerald-200/80 text-[10px] uppercase tracking-[0.18em] font-bold text-emerald-700 mb-3">
            <Sparkles className="h-3 w-3" /> Generative drug design · for AMR
          </div>
          <h1 className="text-[26px] font-bold tracking-tight text-slate-900 leading-tight">
            Design a novel antibiotic against
            <br />
            {pathogenName
              ? <span className="text-emerald-700">{pathogenName}</span>
              : <span className="text-slate-400">a target pathogen</span>}
          </h1>
          {pathogenCode && (
            <p className="text-[12px] text-slate-500 mt-2 font-mono">
              {pathogenCode} ·
              {resistomeCount != null && <> {resistomeCount} resistance genes ·</>}
              {firstLineCount != null && <> {firstLineCount} first-line drugs</>}
            </p>
          )}
        </div>

        {/* Pipeline diagram */}
        <div className="lcard p-3 mb-3">
          <div className="section-eyebrow mb-2 flex items-center gap-1.5">
            <Workflow className="h-3 w-3" /> Multi-agent pipeline
          </div>
          <div className="grid grid-cols-7 items-center gap-1.5">
            {PIPELINE.map((p, i) => {
              const c = COLOR_MAP[p.color]
              return (
                <>
                  <div key={p.label} className="col-span-1.5 flex flex-col items-center text-center" style={{ gridColumn: 'span 1' }}>
                    <div className={[
                      'h-12 w-12 rounded-2xl ring-1 flex items-center justify-center mb-1',
                      c.bg, c.ring,
                    ].join(' ')}>
                      <p.Icon className={['h-5 w-5', c.text].join(' ')} strokeWidth={2.25} />
                    </div>
                    <div className={['text-[11px] font-semibold', c.text].join(' ')}>{p.label}</div>
                    <div className="text-[9.5px] text-slate-400 leading-tight">{p.sub}</div>
                  </div>
                  {i < PIPELINE.length - 1 && (
                    <div key={`arr-${i}`} className="col-span-1 flex items-center justify-center text-slate-300">
                      <ArrowRight className="h-4 w-4" />
                    </div>
                  )}
                </>
              )
            })}
          </div>
          <div className="mt-3 text-[11px] text-slate-500 leading-relaxed text-center">
            They iterate — <span className="text-slate-700 font-semibold">propose → critique → transform → re-score</span> —
            until the candidate reaches <span className="font-mono text-emerald-700">composite ≥ 0.80</span> or the
            Strategist branches to a different scaffold.
          </div>
        </div>

        {/* Deliverables grid */}
        <div className="lcard p-3 mb-3">
          <div className="section-eyebrow mb-2 flex items-center gap-1.5">
            <FileDown className="h-3 w-3" /> What you'll get
          </div>
          <div className="grid grid-cols-2 gap-2">
            {DELIVERABLES.map((d) => (
              <div key={d.label} className="flex items-start gap-2 px-2 py-1.5 rounded-lg bg-slate-50/60 ring-1 ring-slate-200/60">
                <div className="h-7 w-7 rounded-lg bg-white ring-1 ring-slate-200 flex items-center justify-center shrink-0">
                  <d.Icon className="h-3.5 w-3.5 text-slate-700" strokeWidth={2.25} />
                </div>
                <div className="leading-tight">
                  <div className="text-[12px] font-semibold text-slate-800">{d.label}</div>
                  <div className="text-[10.5px] text-slate-500">{d.hint}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* System capabilities ribbon */}
        <div className="lcard p-3 mb-4">
          <div className="section-eyebrow mb-2 flex items-center gap-1.5">
            <Bot className="h-3 w-3" /> System
          </div>
          <div className="flex flex-wrap gap-1.5 text-[11px]">
            <span className="chip-slate"><Database className="h-3 w-3" />25 tools · 6 categories</span>
            <span className="chip-emerald">Gemma 4 31B-it</span>
            <span className="chip-violet">GRPO · 8-axis reward</span>
            <span className="chip-sky">RDKit ETKDG · MMFF94s</span>
            <span className="chip-rose">Boltz-2 affinity</span>
            <span className="chip-amber">vLLM on MI300X</span>
          </div>
        </div>

        {/* CTA */}
        {onStart && (
          <div className="text-center">
            <button
              onClick={onStart}
              disabled={running}
              className="inline-flex items-center gap-2 px-4 h-10 rounded-lg bg-gradient-to-b from-emerald-500 to-emerald-600 hover:from-emerald-400 hover:to-emerald-500 disabled:from-slate-300 disabled:to-slate-400 text-white font-semibold text-[13px] shadow-[0_2px_0_rgba(5,150,105,0.4),0_8px_20px_-8px_rgba(5,150,105,0.6)] transition-all"
            >
              {running ? 'Running…' : 'Start a design loop'}
              <span className="kbd bg-white/20 border-white/30 text-white">⌘ ↵</span>
            </button>
            <div className="text-[10px] text-slate-400 mt-2 font-mono">
              You can intervene mid-loop with directives, or pause to inspect any iteration.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

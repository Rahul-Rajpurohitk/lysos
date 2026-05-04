// Pre-flight hero — what the user does, not what we built.
// Audience: medicinal chemists, infectious-disease researchers, AMR teams
// Lens: workflows + outcomes, not tool counts.

import { Play, Workflow, GitBranch, Megaphone, Microscope } from 'lucide-react'

interface OnboardingHeroProps {
  pathogenName?: string
  pathogenCode?: string
  resistomeCount?: number
  firstLineCount?: number
  onStart?: () => void
  running?: boolean
}

const WORKFLOWS: { Icon: typeof Play; eyebrow: string; title: string; body: string }[] = [
  {
    Icon: Microscope,
    eyebrow: 'Hand-off',
    title: 'I have a pathogen and a deadline',
    body: 'Drop in a target, press Start. A multi-agent loop returns a defensible candidate scored across MIC, drug-likeness, synthesizability, and resistance compatibility — typically inside a minute.',
  },
  {
    Icon: GitBranch,
    eyebrow: 'Provenance',
    title: 'I need to defend every step',
    body: 'Replay any iteration. Inspect the resistome briefing the Designer used. Audit each tool call. Export the full session as a Jupyter notebook a reviewer can re-run.',
  },
  {
    Icon: Megaphone,
    eyebrow: 'Steering',
    title: 'I want to drive the design',
    body: 'Pause. Push a directive ("avoid quinolones — too many escape mutations"). Add a constraint ("logP under 4, must contain a penam core"). The agents adapt on the next turn.',
  },
]

export function OnboardingHero(props: OnboardingHeroProps) {
  const { pathogenName, pathogenCode, resistomeCount, firstLineCount, onStart, running } = props
  return (
    <div className="absolute inset-0 overflow-auto flex items-start justify-center pt-12 pb-6 px-6">
      <div className="max-w-[760px] w-full">
        {/* Title */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-50 ring-1 ring-emerald-200/80 text-[10px] uppercase tracking-[0.18em] font-bold text-emerald-700 mb-4">
            Generative drug design · for AMR
          </div>
          <h1 className="text-[28px] font-bold tracking-tight text-slate-900 leading-[1.15]">
            Design a novel antibiotic against
          </h1>
          <h1 className="text-[28px] font-bold tracking-tight leading-[1.15] mt-1">
            {pathogenName
              ? <span className="text-emerald-700">{pathogenName}</span>
              : <span className="text-slate-400">a target pathogen</span>}
          </h1>
          {pathogenCode && (
            <p className="text-[12px] text-slate-500 mt-3 font-mono tabular-nums">
              <span className="font-semibold text-slate-700">{pathogenCode}</span>
              {resistomeCount != null && <> · {resistomeCount} resistance genes</>}
              {firstLineCount != null && <> · {firstLineCount} first-line drugs</>}
            </p>
          )}
          <p className="text-[13px] text-slate-600 mt-4 max-w-[540px] mx-auto leading-relaxed">
            A team of four AI agents — <span className="text-violet-700 font-semibold">Strategist</span>,
            {' '}<span className="text-emerald-700 font-semibold">Designer</span>,
            {' '}<span className="text-rose-700 font-semibold">Critic</span>,
            {' '}<span className="text-sky-700 font-semibold">Editor</span> —
            {' '}collaborates in your workspace. You watch every reasoning step, intervene with directives whenever you want, and walk away with a candidate that is reproducible end-to-end.
          </p>
        </div>

        {/* Three workflow cards — what users actually do */}
        <div className="grid grid-cols-3 gap-3 mb-8">
          {WORKFLOWS.map((w) => (
            <div
              key={w.title}
              className="lcard p-3 flex flex-col gap-2 hover:border-emerald-300/60 hover:shadow-[0_8px_24px_-12px_rgba(16,185,129,0.25)] transition-all"
            >
              <div className="flex items-center gap-2">
                <div className="h-7 w-7 rounded-lg bg-slate-50 ring-1 ring-slate-200 flex items-center justify-center">
                  <w.Icon className="h-3.5 w-3.5 text-slate-700" strokeWidth={2.25} />
                </div>
                <span className="text-[9.5px] uppercase tracking-[0.16em] font-bold text-slate-400">
                  {w.eyebrow}
                </span>
              </div>
              <div className="text-[13px] font-semibold text-slate-900 leading-tight">
                "{w.title}"
              </div>
              <p className="text-[11.5px] text-slate-600 leading-relaxed">
                {w.body}
              </p>
            </div>
          ))}
        </div>

        {/* Audience strip — implicit positioning */}
        <div className="text-center text-[11px] text-slate-500 mb-6">
          <span className="font-semibold text-slate-700">For</span>
          {' '}medicinal chemists · infectious-disease teams · AMR stewardship programs
        </div>

        {/* CTA */}
        {onStart && (
          <div className="text-center">
            <button
              onClick={onStart}
              disabled={running}
              className="inline-flex items-center gap-2 px-5 h-11 rounded-lg bg-gradient-to-b from-emerald-500 to-emerald-600 hover:from-emerald-400 hover:to-emerald-500 disabled:from-slate-300 disabled:to-slate-400 text-white font-semibold text-[14px] shadow-[0_2px_0_rgba(5,150,105,0.4),0_8px_20px_-8px_rgba(5,150,105,0.6)] transition-all"
              title="Run a multi-agent design loop on the selected pathogen"
            >
              <Play className="h-3.5 w-3.5" />
              {running ? 'Running…' : 'Start a design loop'}
              <span className="kbd bg-white/20 border-white/30 text-white">⌘ ↵</span>
            </button>
            <div className="text-[10px] text-slate-400 mt-3 font-mono">
              <Workflow className="h-3 w-3 inline mr-1 -mt-px" />
              Designer multi-turn tool use → Critic finds the weakest reward → Editor transforms → Strategist decides
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Pre-flight hero — plain language, white surfaces over the protein backdrop.
// Audience: anyone who can read a webpage. Technical terms get tooltips.

import { Play, GitBranch, Megaphone, Microscope, Info } from 'lucide-react'

interface OnboardingHeroProps {
  pathogenName?: string
  pathogenCode?: string
  resistomeCount?: number
  firstLineCount?: number
  onStart?: () => void
  running?: boolean
}

// A tiny inline tooltip — wraps a term with a dotted underline and a popover.
// Pure CSS hover, no extra deps.
function Term({ children, hint }: { children: React.ReactNode; hint: string }) {
  return (
    <span className="relative group cursor-help">
      <span className="border-b border-dotted border-slate-400 hover:text-slate-900">
        {children}
      </span>
      <span className="hidden group-hover:block absolute left-1/2 -translate-x-1/2 -translate-y-full -top-1.5 z-50 w-[260px] bg-slate-900 text-white text-[11px] font-normal leading-relaxed px-2.5 py-1.5 rounded-md shadow-xl pointer-events-none">
        {hint}
        <span className="absolute left-1/2 -translate-x-1/2 top-full w-2 h-2 bg-slate-900 rotate-45 -mt-1" />
      </span>
    </span>
  )
}

const WORKFLOWS: { Icon: typeof Play; eyebrow: string; title: string; bodyJSX: React.ReactNode }[] = [
  {
    Icon: Microscope,
    eyebrow: 'Pick · push start',
    title: 'Get a candidate fast',
    bodyJSX: (
      <>
        Choose the bug you're fighting. Press Start. A team of AI specialists invents a new molecule and tells you, in plain numbers, how good it is — how
        {' '}<Term hint="MIC = the lowest dose that stops the bug from growing in a dish. Lower is better.">strong</Term>,
        {' '}how
        {' '}<Term hint="A score that estimates whether a real drug developer would touch this molecule (orally absorbable, sane size, no obvious flags).">drug-like</Term>,
        {' '}how
        {' '}<Term hint="A rough estimate of how many lab steps it takes to make this molecule from off-the-shelf starting materials.">easy to make</Term>,
        {' '}and how
        {' '}<Term hint="Looks for known toxic substructures, hemolysis (red-blood-cell bursting), reactive warheads, etc.">safe</Term>.
        Usually under a minute.
      </>
    ),
  },
  {
    Icon: GitBranch,
    eyebrow: 'Show your work',
    title: 'Every step is auditable',
    bodyJSX: (
      <>
        Nothing is a black box. You see every thought the AI had, every
        {' '}<Term hint="A 'tool' is a function the AI can call — like 'check if this scaffold is already broken by resistance genes', or 'predict 3D binding'.">tool it called</Term>,
        and every score it computed. Rewind to any iteration. Hand the run as a Jupyter notebook to a reviewer — they can re-run it and get the same answer.
      </>
    ),
  },
  {
    Icon: Megaphone,
    eyebrow: 'You stay in control',
    title: 'Steer mid-design',
    bodyJSX: (
      <>
        Don't like where it's heading? Type a note —{' '}
        <em>"stop trying ciprofloxacin-like scaffolds, the bug is already resistant to those"</em> — and the agents read it before the next turn. Or add a hard rule (size limit, must contain a specific ring) with one click.
      </>
    ),
  },
]

export function OnboardingHero(props: OnboardingHeroProps) {
  const { pathogenName, pathogenCode, resistomeCount, firstLineCount, onStart, running } = props
  return (
    <div className="absolute inset-0 overflow-auto p-6">
      <div className="max-w-[820px] mx-auto flex flex-col gap-4">
        {/* Title card — solid white so it sits clearly above the protein backdrop */}
        <div className="lcard p-6 text-center">
          <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-emerald-50 ring-1 ring-emerald-200/80 text-[10px] uppercase tracking-[0.18em] font-bold text-emerald-700 mb-3">
            New antibiotic · designed by AI · auditable
          </div>
          <h1 className="text-[26px] font-bold tracking-tight text-slate-900 leading-[1.15]">
            Invent a new antibiotic against
          </h1>
          <h1 className="text-[26px] font-bold tracking-tight leading-[1.15] mt-1">
            {pathogenName
              ? <span className="text-emerald-700">{pathogenName}</span>
              : <span className="text-slate-400">a target pathogen</span>}
          </h1>
          {pathogenCode && (
            <p className="text-[12px] text-slate-500 mt-3 font-mono tabular-nums flex items-center justify-center gap-1.5 flex-wrap">
              <span className="font-semibold text-slate-700">{pathogenCode}</span>
              {resistomeCount != null && (
                <>
                  <span>·</span>
                  <Term hint="Genes the bacterium carries that disable existing antibiotics. The more it has, the harder it is to treat.">
                    {resistomeCount} resistance genes
                  </Term>
                </>
              )}
              {firstLineCount != null && (
                <>
                  <span>·</span>
                  <Term hint="What hospitals reach for first when treating this infection today. When these stop working, the patient is in trouble.">
                    {firstLineCount} drugs that still work today
                  </Term>
                </>
              )}
            </p>
          )}
          <p className="text-[13px] text-slate-600 mt-4 max-w-[600px] mx-auto leading-relaxed">
            <Term hint="A small team of language models with different jobs, like a research group: one proposes ideas, one critiques, one edits, one decides what to do next.">Four AI specialists</Term> — a{' '}
            <span className="text-violet-700 font-semibold">Strategist</span> who reads the case file,
            a <span className="text-emerald-700 font-semibold">Designer</span> who proposes a molecule,
            a <span className="text-rose-700 font-semibold">Critic</span> who finds its weak spots,
            and an <span className="text-sky-700 font-semibold">Editor</span> who fixes them — work in your browser. You watch them collaborate. You jump in when you want. You walk away with a molecule and a paper trail.
          </p>
        </div>

        {/* Workflow cards — three concrete jobs the product does */}
        <div className="grid grid-cols-3 gap-3">
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
              <div className="text-[13px] font-bold text-slate-900 leading-tight">
                {w.title}
              </div>
              <p className="text-[11.5px] text-slate-600 leading-relaxed">
                {w.bodyJSX}
              </p>
            </div>
          ))}
        </div>

        {/* Audience strip — plain English */}
        <div className="lcard px-4 py-2.5 text-center">
          <div className="text-[11px] text-slate-500">
            <span className="font-semibold text-slate-700">Who's this for —</span>
            {' '}drug-discovery chemists who need a starting point fast, infection researchers tracking what does and doesn't kill resistant bacteria, and teams worried about the next post-antibiotic-era pathogen.
          </div>
        </div>

        {/* CTA */}
        {onStart && (
          <div className="text-center mt-1">
            <button
              onClick={onStart}
              disabled={running}
              className="inline-flex items-center gap-2 px-5 h-11 rounded-lg bg-gradient-to-b from-emerald-500 to-emerald-600 hover:from-emerald-400 hover:to-emerald-500 disabled:from-slate-300 disabled:to-slate-400 text-white font-semibold text-[14px] shadow-[0_2px_0_rgba(5,150,105,0.4),0_8px_20px_-8px_rgba(5,150,105,0.6)] transition-all"
              title="Run a multi-agent design loop on the selected pathogen"
            >
              <Play className="h-3.5 w-3.5" />
              {running ? 'Designing…' : 'Start designing'}
              <span className="kbd bg-white/20 border-white/30 text-white">⌘ ↵</span>
            </button>
            <div className="text-[10.5px] text-slate-500 mt-3 inline-flex items-center gap-1.5">
              <Info className="h-3 w-3" />
              The agents will start working. You'll see their conversation on the left.
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// Lysos Workbench — meta-engineered 3-column layout.
//
//   Header        compact actions (pathogen, mode, autonomy, iters, start, export)
//   Ribbon        pathogen briefing + session id (single line)
//
//   Main grid (h-full):
//     col-span-4  ChatPanel (full height) + composer
//     col-span-5  3D viewer (large) + 2D viewer + functional-group palette
//     col-span-3  RightDock (tabbed: Radar / Pareto / Synth / Graph /
//                  Lineage / Tools) + Candidates list
//
//   BottomDock    constraint chips + replay scrubber (slim, single row)

import { useEffect, useMemo, useState } from 'react'
import {
  Beaker, Play, Loader2, RefreshCw, Download, ChevronRight, Brain,
} from 'lucide-react'
import {
  createSession, startSession, streamEvents, listPathogens, intervene,
} from './api'
import type {
  AgentMessage, Candidate, Pathogen, ToolCallRecord, PathogenInfo,
  Autonomy, Mode, Constraint,
} from './types'
import { useWorkbench } from './store'
import { MolViewer } from './components/MolViewer'
import { Mol2D } from './components/Mol2D'
import { RewardRadar } from './components/RewardRadar'
import { LineageTree } from './components/LineageTree'
import { ChatPanel } from './components/ChatPanel'
import { ToolCallTimeline } from './components/ToolCallTimeline'
import { CandidateList } from './components/CandidateList'
import { MultiAgentColumns } from './components/MultiAgentColumns'
import { ParetoExplorer } from './components/ParetoExplorer'
import { MoAPanel } from './components/MoAPanel'
import { FunctionalGroupPalette } from './components/FunctionalGroupPalette'
import { ReplayScrubber } from './components/ReplayScrubber'
import { ConstraintBar } from './components/ConstraintBar'
import { SynthesisTree } from './components/SynthesisTree'
import { KnowledgeGraph } from './components/KnowledgeGraph'

const PATHOGEN_TARGET_PDB: Record<Pathogen, string> = {
  MRSA: '1VQQ', Mtb: '2X22', 'EColi-CRE': '5UL8', KpneuCRE: '6QWN',
  Abaum: '7M4F', Paer: '5DPX', VRE: '1MWS', NGono: '5XFT',
}

type RightTab = 'radar' | 'pareto' | 'synth' | 'graph' | 'lineage' | 'tools'

const RIGHT_TABS: { id: RightTab; label: string }[] = [
  { id: 'radar',   label: 'Radar' },
  { id: 'pareto',  label: 'Pareto' },
  { id: 'synth',   label: 'Synth' },
  { id: 'graph',   label: 'Graph' },
  { id: 'lineage', label: 'Lineage' },
  { id: 'tools',   label: 'Tools' },
]

export default function Workbench() {
  const {
    sessionId, candidates, history, toolCalls, paretoFrontier,
    selectedCandidateId, status, errorMessage, iteration, maxIterations: storeMaxIters,
    setSessionId, addCandidate, addMessage, addToolCall, setStatus, setError,
    setSelected, reset, setIteration, setMaxIterations,
  } = useWorkbench()

  const [pathogens, setPathogens] = useState<PathogenInfo[]>([])
  const [target, setTarget] = useState<Pathogen>('MRSA')
  const [mode, setMode] = useState<Mode>('design')
  const [autonomy, setAutonomy] = useState<Autonomy>('copilot')
  const [maxIters, setMaxIters] = useState(4)
  const [chatView, setChatView] = useState<'stream' | 'columns'>('stream')
  const [rightTab, setRightTab] = useState<RightTab>('radar')
  const [showMoA, setShowMoA] = useState(false)
  const [constraints, setConstraints] = useState<Constraint[]>([])

  useEffect(() => { setMaxIterations(maxIters) }, [maxIters, setMaxIterations])
  useEffect(() => {
    listPathogens().then((r) => setPathogens(r.pathogens)).catch(() => {})
  }, [])

  const selectedCandidate = useMemo(() => {
    if (!selectedCandidateId) return candidates[candidates.length - 1] ?? null
    return candidates.find((c) => c.id === selectedCandidateId) ?? null
  }, [candidates, selectedCandidateId])

  async function handleStart() {
    reset()
    setMaxIterations(maxIters)
    setError(null)
    setStatus('running')
    try {
      const { session_id } = await createSession({
        target_pathogen: target, mode, autonomy,
        max_iterations: maxIters, constraints,
      })
      setSessionId(session_id)

      const es = streamEvents(session_id, (ev) => {
        switch (ev.type) {
          case 'iteration_start': {
            const d = ev.data as { i: number }
            if (d?.i) setIteration(d.i)
            break
          }
          case 'candidate_added':
            addCandidate(ev.data as Candidate); break
          case 'agent_message':
            addMessage(ev.data as AgentMessage); break
          case 'tool_call_result':
            addToolCall(ev.data as ToolCallRecord); break
          case 'intervention': {
            const d = ev.data as { kind: string; payload: unknown }
            const content = d.kind === 'directive'
              ? `📣 ${String(d.payload)}`
              : `📣 new constraint: ${JSON.stringify(d.payload)}`
            addMessage({
              id: `intervention-${Date.now()}`,
              role: 'user', content, tool_calls: [], confidence: null,
              created_at: new Date().toISOString(),
            })
            break
          }
          case 'agent_idle':
          case 'session_complete':
            setStatus('terminated'); es.close(); break
          case 'error':
            setError(String(ev.data ?? 'unknown'))
            setStatus('error'); es.close(); break
        }
      }, (err) => { setError(String(err)); setStatus('error') })

      await startSession(session_id)
    } catch (err) {
      setError(String(err)); setStatus('error')
    }
  }

  async function handleSendDirective(text: string) {
    if (!sessionId) return
    await intervene(sessionId, { kind: 'directive', payload: text })
  }

  async function handleExportNotebook() {
    if (!sessionId) return
    const r = await fetch(`/workbench/sessions/${sessionId}/notebook`)
    if (!r.ok) return
    const nb = await r.json()
    const blob = new Blob([JSON.stringify(nb, null, 2)], { type: 'application/x-ipynb+json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `lysos-${sessionId.slice(0, 8)}.ipynb`
    a.click()
    URL.revokeObjectURL(url)
  }

  const targetInfo = pathogens.find((p) => p.code === target)
  const composite = selectedCandidate?.scores.composite ?? 0

  return (
    <div className="h-screen flex flex-col bg-slate-100/60 text-slate-900 antialiased font-sans">
      {/* ============ Header ============ */}
      <header className="flex items-center gap-3 px-4 h-12 border-b border-slate-200/80 bg-white/80 backdrop-blur shrink-0">
        <div className="flex items-center gap-2 mr-2">
          <div className="h-7 w-7 rounded-lg bg-emerald-600 text-white flex items-center justify-center shadow-sm">
            <Beaker className="h-4 w-4" strokeWidth={2.25} />
          </div>
          <div className="leading-tight">
            <div className="text-[13px] font-bold tracking-tight text-slate-900">Lysos</div>
            <div className="text-[9px] uppercase tracking-widest text-slate-400 font-semibold">
              Workbench v0.2
            </div>
          </div>
        </div>

        <Selector
          value={target}
          onChange={(v) => setTarget(v as Pathogen)}
          disabled={status === 'running'}
          width="w-[280px]"
        >
          {pathogens.length === 0
            ? <option>{target}</option>
            : pathogens.map((p) => (
                <option key={p.code} value={p.code}>{p.code} · {p.name}</option>
              ))
          }
        </Selector>

        <Selector value={mode} onChange={(v) => setMode(v as Mode)} disabled={status === 'running'}>
          <option value="design">Design</option>
          <option value="red_team">Red-team</option>
          <option value="compare">Compare</option>
        </Selector>

        <Selector value={autonomy} onChange={(v) => setAutonomy(v as Autonomy)} disabled={status === 'running'}>
          <option value="auto">Auto</option>
          <option value="copilot">Co-pilot</option>
          <option value="manual">Manual</option>
        </Selector>

        <label className="flex items-center gap-1 text-[10px] uppercase tracking-widest text-slate-400 font-semibold">
          iters
          <input
            type="number" min={1} max={20}
            value={maxIters}
            onChange={(e) => setMaxIters(Number(e.target.value))}
            disabled={status === 'running'}
            className="bg-white border border-slate-200 rounded-md px-2 py-1 text-[12px] w-14 text-slate-900 font-mono"
          />
        </label>

        <div className="ml-auto flex items-center gap-1.5">
          <button
            onClick={handleStart}
            disabled={status === 'running'}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-300 disabled:text-slate-500 text-white px-3.5 h-8 rounded-md font-semibold text-[12px] flex items-center gap-1.5 transition-colors shadow-sm"
          >
            {status === 'running'
              ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
              : <Play className="h-3.5 w-3.5" />}
            {status === 'running' ? 'Running' : 'Start'}
          </button>
          <IconButton title="Export notebook" disabled={!sessionId} onClick={handleExportNotebook}>
            <Download className="h-3.5 w-3.5" />
          </IconButton>
          <IconButton title="Reset" onClick={reset}>
            <RefreshCw className="h-3.5 w-3.5" />
          </IconButton>
        </div>
      </header>

      {/* ============ Pathogen ribbon ============ */}
      {targetInfo && (
        <div className="px-4 h-8 border-b border-slate-200/70 bg-white/40 flex items-center gap-3 text-[11px] shrink-0">
          <span className="font-semibold text-slate-800">{targetInfo.code}</span>
          <span className="text-slate-500">{targetInfo.name}</span>
          <Divider />
          <Stat label="resistance" value={String(targetInfo.resistome_count)} />
          <Stat label="first-line" value={String(targetInfo.first_line_count)} />
          <Stat label="best" value={composite > 0 ? composite.toFixed(3) : '—'} accent={composite >= 0.8 ? 'text-emerald-700' : 'text-slate-700'} />
          <Stat label="pareto" value={String(paretoFrontier.length)} />
          <span className="ml-auto text-slate-400 font-mono text-[10px]">
            session · {sessionId ?? '—'}
          </span>
        </div>
      )}

      {/* ============ Main grid ============ */}
      <div className="flex-1 grid grid-cols-12 gap-2 p-2 min-h-0">
        {/* LEFT — chat */}
        <section className={clsxColCount(chatView === 'columns')}>
          <Card className="flex flex-col min-h-0">
            <CardHeader>
              <span>{chatView === 'columns' ? 'Multi-agent debate' : 'Conversation'}</span>
              <Toggle
                value={chatView}
                onChange={(v) => setChatView(v as 'stream' | 'columns')}
                options={[{ id: 'stream', label: 'Stream' }, { id: 'columns', label: 'Columns' }]}
              />
            </CardHeader>
            <div className="flex-1 min-h-0 flex flex-col">
              {chatView === 'stream' ? (
                <ChatPanel
                  messages={history}
                  toolCalls={toolCalls}
                  status={status}
                  iteration={iteration}
                  maxIterations={storeMaxIters}
                  onSelectSmiles={(smi) => {
                    const c = candidates.find((x) => x.smiles === smi)
                    if (c) setSelected(c.id)
                  }}
                  onSendDirective={handleSendDirective}
                />
              ) : (
                <MultiAgentColumns messages={history} />
              )}
            </div>
          </Card>
        </section>

        {/* CENTER — visuals */}
        <section className={chatView === 'columns' ? 'col-span-3 flex flex-col gap-2 min-h-0' : 'col-span-5 flex flex-col gap-2 min-h-0'}>
          <Card className="flex-1 relative min-h-0">
            <div className="absolute top-2 left-2 z-10 flex items-center gap-2 bg-white/95 px-2 py-1 rounded-md text-[10px] font-mono text-slate-600 shadow-sm border border-slate-200/60">
              <span className="text-slate-400">3D</span>
              <span className="font-semibold">{PATHOGEN_TARGET_PDB[target]}</span>
              {selectedCandidate && (
                <>
                  <ChevronRight className="h-3 w-3 text-slate-300" />
                  <span className="truncate max-w-[260px]">{selectedCandidate.smiles}</span>
                </>
              )}
            </div>
            <MolViewer
              smiles={selectedCandidate?.smiles}
              pdbId={PATHOGEN_TARGET_PDB[target]}
              pathogen={target}
              className="w-full h-full"
            />
          </Card>

          <Card className="flex flex-col" style={{ minHeight: 220 }}>
            <CardHeader>
              <span>2D structure</span>
              {selectedCandidate && (
                <span className="ml-2 text-[10px] font-mono text-slate-400 truncate flex-1">
                  {selectedCandidate.smiles}
                </span>
              )}
              {selectedCandidate && (
                <button
                  onClick={() => setShowMoA(true)}
                  className="ml-auto text-[10px] text-emerald-700 hover:bg-emerald-50 px-1.5 py-0.5 rounded inline-flex items-center gap-1"
                >
                  <Brain className="h-3 w-3" /> Mechanism
                </button>
              )}
            </CardHeader>
            <div className="flex-1 flex items-center justify-center p-2 min-h-[140px]">
              {selectedCandidate
                ? <Mol2D smiles={selectedCandidate.smiles} width={460} height={140} />
                : <span className="text-slate-300 text-xs">2D structure appears here</span>
              }
            </div>
            {selectedCandidate && (
              <FunctionalGroupPalette
                smiles={selectedCandidate.smiles}
                onTransform={(newSmi, op) => console.log('Drag-edit:', op, '→', newSmi)}
              />
            )}
          </Card>
        </section>

        {/* RIGHT — combo dock */}
        <section className="col-span-3 flex flex-col gap-2 min-h-0">
          <Card className="flex flex-col" style={{ height: '52%' }}>
            <CardHeader>
              <span className="capitalize">{rightTab}</span>
              <div className="ml-auto flex items-center gap-0.5 bg-slate-100 p-0.5 rounded-md">
                {RIGHT_TABS.map((t) => (
                  <button
                    key={t.id}
                    onClick={() => setRightTab(t.id)}
                    className={[
                      'px-1.5 py-0.5 text-[10px] rounded transition',
                      rightTab === t.id
                        ? 'bg-white text-slate-900 font-semibold shadow-sm'
                        : 'text-slate-500 hover:text-slate-800',
                    ].join(' ')}
                  >
                    {t.label}
                  </button>
                ))}
              </div>
            </CardHeader>
            <div className="flex-1 overflow-auto p-2 min-h-0">
              {rightTab === 'radar' && (
                selectedCandidate
                  ? <RewardRadar
                      scores={selectedCandidate.scores}
                      comparison={candidates.length >= 2
                        ? candidates[candidates.length - 2].scores : undefined}
                    />
                  : <EmptyHint label="Reward radar appears with candidate" />
              )}
              {rightTab === 'pareto' && (
                <ParetoExplorer
                  candidates={candidates}
                  paretoIds={paretoFrontier}
                  onSelect={setSelected}
                />
              )}
              {rightTab === 'synth' && (
                <SynthesisTree smiles={selectedCandidate?.smiles ?? null} />
              )}
              {rightTab === 'graph' && <KnowledgeGraph pathogen={target} />}
              {rightTab === 'lineage' && (
                candidates.length > 0
                  ? <LineageTree
                      candidates={candidates}
                      selectedId={selectedCandidateId ?? selectedCandidate?.id ?? null}
                      paretoIds={paretoFrontier}
                      onSelect={setSelected}
                    />
                  : <EmptyHint label="Lineage tree builds as candidates are proposed" />
              )}
              {rightTab === 'tools' && (
                <ToolCallTimeline calls={toolCalls} />
              )}
            </div>
          </Card>

          <Card className="flex-1 flex flex-col min-h-0">
            <CardHeader>
              <span>Candidates</span>
              <span className="text-[10px] font-mono text-slate-400">{candidates.length} · {paretoFrontier.length} pareto</span>
            </CardHeader>
            <div className="flex-1 overflow-auto min-h-0">
              <CandidateList
                candidates={candidates}
                selectedId={selectedCandidateId ?? selectedCandidate?.id ?? null}
                paretoIds={paretoFrontier}
                onSelect={setSelected}
              />
            </div>
          </Card>
        </section>
      </div>

      {/* ============ Bottom dock — slim ============ */}
      <div className="border-t border-slate-200/80 bg-white/70 backdrop-blur shrink-0">
        <ConstraintBar
          constraints={constraints}
          onAdd={(c) => setConstraints((prev) => [...prev, c])}
          onRemove={(idx) => setConstraints((prev) => prev.filter((_, i) => i !== idx))}
          disabled={status === 'running'}
        />
        <ReplayScrubber
          candidates={candidates}
          selectedId={selectedCandidateId ?? selectedCandidate?.id ?? null}
          onSelect={setSelected}
        />
      </div>

      {errorMessage && (
        <div className="bg-rose-50 border-t border-rose-200 px-4 py-1.5 text-rose-700 text-[12px]">
          ⚠ {errorMessage}
        </div>
      )}

      {showMoA && selectedCandidate && (
        <MoAPanel
          smiles={selectedCandidate.smiles}
          pathogen={target}
          onClose={() => setShowMoA(false)}
        />
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// UI primitives — kept inline so this file is the single source of truth.
// ---------------------------------------------------------------------------
function clsxColCount(columnsView: boolean): string {
  return [
    columnsView ? 'col-span-6' : 'col-span-4',
    'flex flex-col min-h-0 transition-all',
  ].join(' ')
}

interface CardProps {
  className?: string
  style?: React.CSSProperties
  children: React.ReactNode
}
function Card({ className, style, children }: CardProps) {
  return (
    <div
      className={['bg-white border border-slate-200/80 rounded-lg shadow-[0_1px_0_rgba(15,23,42,0.04)] overflow-hidden', className].filter(Boolean).join(' ')}
      style={style}
    >
      {children}
    </div>
  )
}

function CardHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 px-3 h-9 border-b border-slate-200/80 bg-slate-50/50 text-[11px] font-semibold uppercase tracking-wider text-slate-500 shrink-0">
      {children}
    </div>
  )
}

function Selector(props: {
  value: string
  onChange: (v: string) => void
  disabled?: boolean
  width?: string
  children: React.ReactNode
}) {
  return (
    <select
      value={props.value}
      onChange={(e) => props.onChange(e.target.value)}
      disabled={props.disabled}
      className={[
        'bg-white border border-slate-200 rounded-md px-2 h-8 text-[12px] text-slate-900',
        'focus:outline-none focus:ring-2 focus:ring-emerald-300/40 focus:border-emerald-400',
        'disabled:opacity-60',
        props.width ?? '',
      ].join(' ')}
    >
      {props.children}
    </select>
  )
}

function IconButton(props: {
  onClick?: () => void
  disabled?: boolean
  title?: string
  children: React.ReactNode
}) {
  return (
    <button
      onClick={props.onClick}
      disabled={props.disabled}
      title={props.title}
      className="bg-slate-100 hover:bg-slate-200 disabled:bg-slate-50 disabled:text-slate-300 text-slate-700 h-8 w-8 rounded-md flex items-center justify-center transition-colors"
    >
      {props.children}
    </button>
  )
}

function Toggle<T extends string>(props: {
  value: T
  onChange: (v: T) => void
  options: { id: T; label: string }[]
}) {
  return (
    <div className="ml-auto flex items-center gap-0.5 bg-slate-100 p-0.5 rounded-md">
      {props.options.map((o) => (
        <button
          key={o.id}
          onClick={() => props.onChange(o.id)}
          className={[
            'px-2 py-0.5 text-[10px] rounded transition',
            props.value === o.id
              ? 'bg-white text-slate-900 font-semibold shadow-sm'
              : 'text-slate-500 hover:text-slate-800',
          ].join(' ')}
        >
          {o.label}
        </button>
      ))}
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <span className="inline-flex items-baseline gap-1">
      <span className="text-[9px] uppercase tracking-widest text-slate-400 font-semibold">{label}</span>
      <span className={['font-mono font-semibold', accent ?? 'text-slate-700'].join(' ')}>{value}</span>
    </span>
  )
}

function Divider() {
  return <span className="text-slate-200">·</span>
}

function EmptyHint({ label }: { label: string }) {
  return (
    <div className="h-full flex items-center justify-center text-slate-300 text-[11px] text-center px-4">
      {label}
    </div>
  )
}

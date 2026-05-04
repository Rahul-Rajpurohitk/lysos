// Lysos Workbench — main 4-pane page
//   Left:    multi-agent chat
//   Center:  3D Mol* + 2D RDKit-JS stage
//   Right:   reward radar + candidate list
//   Bottom:  lineage tree + tool-call timeline + constraint bar

import { useEffect, useMemo, useState } from 'react'
import { Beaker, Play, Loader2, RefreshCw } from 'lucide-react'
import {
  createSession, startSession, streamEvents, listPathogens,
} from './api'
import type {
  AgentMessage, Candidate, Pathogen, ToolCallRecord, PathogenInfo, Autonomy, Mode,
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
import type { Constraint } from './types'

const PATHOGEN_TARGET_PDB: Record<Pathogen, string> = {
  MRSA: '1VQQ',
  Mtb: '2X22',
  'EColi-CRE': '5UL8',
  KpneuCRE: '6QWN',
  Abaum: '7M4F',
  Paer: '5DPX',
  VRE: '1MWS',
  NGono: '5XFT',
}

export default function Workbench() {
  const {
    sessionId, candidates, history, toolCalls, paretoFrontier,
    selectedCandidateId, status, errorMessage,
    setSessionId, addCandidate, addMessage, addToolCall, setStatus, setError,
    setSelected, reset,
  } = useWorkbench()

  const [pathogens, setPathogens] = useState<PathogenInfo[]>([])
  const [target, setTarget] = useState<Pathogen>('MRSA')
  const [mode, setMode] = useState<Mode>('design')
  const [autonomy, setAutonomy] = useState<Autonomy>('copilot')
  const [maxIterations, setMaxIterations] = useState(4)
  const [chatView, setChatView] = useState<'stream' | 'columns'>('stream')
  const [rightTab, setRightTab] = useState<'radar' | 'pareto'>('radar')
  const [showMoA, setShowMoA] = useState(false)
  const [constraints, setConstraints] = useState<Constraint[]>([])

  useEffect(() => {
    listPathogens().then((r) => setPathogens(r.pathogens)).catch((e) => {
      console.error('listPathogens', e)
    })
  }, [])

  const selectedCandidate = useMemo(() => {
    if (!selectedCandidateId) return candidates[candidates.length - 1] ?? null
    return candidates.find((c) => c.id === selectedCandidateId) ?? null
  }, [candidates, selectedCandidateId])

  async function handleStart() {
    reset()
    setError(null)
    setStatus('running')
    try {
      const { session_id } = await createSession({
        target_pathogen: target,
        mode,
        autonomy,
        max_iterations: maxIterations,
        constraints,
      })
      setSessionId(session_id)

      const es = streamEvents(session_id, (ev) => {
        switch (ev.type) {
          case 'candidate_added':
            addCandidate(ev.data as Candidate)
            break
          case 'agent_message':
            addMessage(ev.data as AgentMessage)
            break
          case 'tool_call_result':
            addToolCall(ev.data as ToolCallRecord)
            break
          case 'agent_idle':
          case 'session_complete':
            setStatus('terminated')
            es.close()
            break
          case 'error':
            setError(String(ev.data ?? 'unknown'))
            setStatus('error')
            es.close()
            break
        }
      }, (err) => {
        setError(String(err))
        setStatus('error')
      })

      // Kick off the loop
      await startSession(session_id)
    } catch (err) {
      setError(String(err))
      setStatus('error')
    }
  }

  const targetInfo = pathogens.find((p) => p.code === target)

  return (
    <div className="h-screen flex flex-col bg-slate-50 text-slate-900">
      {/* Header */}
      <header className="flex items-center gap-4 px-5 py-3 border-b border-slate-200">
        <div className="flex items-center gap-2">
          <Beaker className="w-5 h-5 text-emerald-600" />
          <span className="font-bold tracking-wide">Lysos Workbench</span>
          <span className="text-slate-400 text-xs ml-2">v0.2 · agentic playground</span>
        </div>

        <div className="flex items-center gap-3 ml-auto">
          <select
            value={target}
            onChange={(e) => setTarget(e.target.value as Pathogen)}
            className="bg-white border border-slate-300 px-2 py-1 rounded text-sm"
            disabled={status === 'running'}
          >
            {pathogens.length === 0
              ? <option>{target}</option>
              : pathogens.map((p) => (
                  <option key={p.code} value={p.code}>{p.code} — {p.name}</option>
                ))
            }
          </select>

          <select
            value={mode}
            onChange={(e) => setMode(e.target.value as Mode)}
            className="bg-white border border-slate-300 px-2 py-1 rounded text-sm"
            disabled={status === 'running'}
          >
            <option value="design">Design</option>
            <option value="red_team">Red-team</option>
            <option value="compare">Compare</option>
          </select>

          <select
            value={autonomy}
            onChange={(e) => setAutonomy(e.target.value as Autonomy)}
            className="bg-white border border-slate-300 px-2 py-1 rounded text-sm"
            disabled={status === 'running'}
          >
            <option value="auto">Auto</option>
            <option value="copilot">Co-pilot</option>
            <option value="manual">Manual</option>
          </select>

          <label className="text-xs text-slate-500 flex items-center gap-1.5">
            iters
            <input
              type="number"
              min={1}
              max={20}
              value={maxIterations}
              onChange={(e) => setMaxIterations(Number(e.target.value))}
              disabled={status === 'running'}
              className="bg-white border border-slate-300 px-2 py-1 rounded text-sm w-16"
            />
          </label>

          <button
            onClick={handleStart}
            disabled={status === 'running'}
            className="bg-emerald-600 hover:bg-emerald-500 disabled:bg-slate-300 disabled:text-slate-500 px-4 py-1.5 rounded font-medium text-sm flex items-center gap-2 transition-colors"
          >
            {status === 'running'
              ? <Loader2 className="w-4 h-4 animate-spin" />
              : <Play className="w-4 h-4" />
            }
            {status === 'running' ? 'Running…' : 'Start'}
          </button>

          <button
            onClick={reset}
            className="bg-slate-200 hover:bg-slate-300 text-slate-700 px-3 py-1.5 rounded text-sm flex items-center gap-1 transition-colors"
            title="Reset"
          >
            <RefreshCw className="w-3.5 h-3.5" />
          </button>
        </div>
      </header>

      {/* Pathogen ribbon */}
      {targetInfo && (
        <div className="px-5 py-2 border-b border-slate-200 bg-white text-xs text-slate-500 flex items-center gap-4">
          <span><strong className="text-slate-900">{targetInfo.code}</strong> · {targetInfo.name}</span>
          <span>{targetInfo.resistome_count} resistance genes</span>
          <span>{targetInfo.first_line_count} first-line drugs</span>
          <span className="ml-auto text-slate-400 font-mono">
            session: {sessionId ?? '—'}
          </span>
        </div>
      )}

      {/* Main 3-column layout */}
      <div className="flex-1 grid grid-cols-12 gap-2 p-2 min-h-0">
        {/* LEFT — chat panel (stream OR multi-agent columns) */}
        <div className={`${chatView === 'columns' ? 'col-span-6' : 'col-span-3'} bg-white border border-slate-200 rounded flex flex-col min-h-0 transition-all`}>
          <div className="px-3 py-2 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider flex items-center justify-between">
            <span>{chatView === 'columns' ? 'Multi-agent debate' : 'Conversation'}</span>
            <div className="flex gap-1">
              <button
                onClick={() => setChatView('stream')}
                className={`px-2 py-0.5 text-[10px] rounded ${chatView === 'stream' ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-600'}`}
              >
                Stream
              </button>
              <button
                onClick={() => setChatView('columns')}
                className={`px-2 py-0.5 text-[10px] rounded ${chatView === 'columns' ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-600'}`}
              >
                Columns
              </button>
            </div>
          </div>
          {chatView === 'stream' ? (
            <ChatPanel messages={history} status={status} />
          ) : (
            <MultiAgentColumns messages={history} />
          )}
        </div>

        {/* CENTER — 3D + 2D viewer (shrinks when columns view active) */}
        <div className={`${chatView === 'columns' ? 'col-span-3' : 'col-span-6'} flex flex-col gap-2 min-h-0 transition-all`}>
          <div className="flex-1 bg-white border border-slate-200 rounded relative">
            <div className="absolute top-2 left-2 z-10 text-xs text-slate-500 bg-white/95 px-2 py-1 rounded">
              3D · {selectedCandidate ? selectedCandidate.smiles.slice(0, 36) : 'select a candidate'}
            </div>
            <MolViewer
              smiles={selectedCandidate?.smiles}
              pdbId={PATHOGEN_TARGET_PDB[target]}
              className="w-full h-full"
            />
          </div>

          <div className="bg-white border border-slate-200 rounded flex flex-col min-h-[200px]">
            <div className="flex-1 flex items-center justify-center p-3">
              {selectedCandidate
                ? <Mol2D smiles={selectedCandidate.smiles} width={420} height={140} />
                : <span className="text-slate-500 text-xs">2D structure appears here.</span>
              }
            </div>
            {selectedCandidate && (
              <FunctionalGroupPalette
                smiles={selectedCandidate.smiles}
                onTransform={(newSmi, op) => {
                  console.log('Drag-edit:', op, '→', newSmi)
                }}
              />
            )}
            {selectedCandidate && (
              <button
                onClick={() => setShowMoA(true)}
                className="px-3 py-1.5 border-t border-slate-200 text-xs text-emerald-700 hover:bg-emerald-50 flex items-center justify-center gap-1.5"
              >
                Show mechanism-of-action panel →
              </button>
            )}
          </div>
        </div>

        {/* RIGHT — reward radar + candidate list */}
        <div className="col-span-3 flex flex-col gap-2 min-h-0">
          <div className="bg-white border border-slate-200 rounded flex flex-col">
            <div className="px-3 py-2 border-b border-slate-200 flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
                {rightTab === 'radar' ? 'Reward radar' : 'Pareto explorer'}
              </span>
              <div className="flex gap-1">
                <button
                  onClick={() => setRightTab('radar')}
                  className={`px-2 py-0.5 text-[10px] rounded ${rightTab === 'radar' ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-600'}`}
                >
                  Radar
                </button>
                <button
                  onClick={() => setRightTab('pareto')}
                  className={`px-2 py-0.5 text-[10px] rounded ${rightTab === 'pareto' ? 'bg-emerald-600 text-white' : 'bg-slate-100 text-slate-600'}`}
                >
                  Pareto
                </button>
              </div>
            </div>
            <div className="p-2 min-h-[300px]">
              {rightTab === 'radar' ? (
                selectedCandidate
                  ? <RewardRadar
                      scores={selectedCandidate.scores}
                      comparison={
                        candidates.length >= 2
                          ? candidates[candidates.length - 2].scores
                          : undefined
                      }
                    />
                  : <div className="h-[300px] flex items-center justify-center text-slate-400 text-xs">
                      Radar appears with candidate
                    </div>
              ) : (
                <ParetoExplorer
                  candidates={candidates}
                  paretoIds={paretoFrontier}
                  onSelect={setSelected}
                />
              )}
            </div>
          </div>

          <div className="flex-1 bg-white border border-slate-200 rounded overflow-y-auto min-h-0">
            <div className="px-3 py-2 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider sticky top-0 bg-white/95 backdrop-blur">
              Candidates ({candidates.length})
            </div>
            <CandidateList
              candidates={candidates}
              selectedId={selectedCandidateId ?? selectedCandidate?.id ?? null}
              paretoIds={paretoFrontier}
              onSelect={setSelected}
            />
          </div>
        </div>
      </div>

      {/* Bottom drawers — lineage + timeline */}
      <div className="grid grid-cols-12 gap-2 p-2 pt-0 max-h-[260px]">
        <div className="col-span-7 bg-white border border-slate-200 rounded overflow-auto">
          <div className="px-3 py-2 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Lineage tree
          </div>
          <LineageTree
            candidates={candidates}
            selectedId={selectedCandidateId ?? selectedCandidate?.id ?? null}
            paretoIds={paretoFrontier}
            onSelect={setSelected}
          />
        </div>

        <div className="col-span-5 bg-white border border-slate-200 rounded overflow-auto">
          <div className="px-3 py-2 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase tracking-wider">
            Tool calls ({toolCalls.length})
          </div>
          <ToolCallTimeline calls={toolCalls} />
        </div>
      </div>

      {/* Constraint bar + replay scrubber (above bottom drawers) */}
      <div className="bg-white border-t border-slate-200">
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
        <div className="bg-rose-50 border-t border-rose-200 px-4 py-2 text-rose-700 text-sm">
          ⚠ {errorMessage}
        </div>
      )}

      {/* MoA side panel (overlay) */}
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

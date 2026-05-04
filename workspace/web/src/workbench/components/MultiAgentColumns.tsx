// Multi-agent debate columns — 4 vertical streams (Designer / Critic / Editor / Strategist)

import clsx from 'clsx'
import type { AgentMessage, AgentRole } from '../types'

interface MultiAgentColumnsProps {
  messages: AgentMessage[]
}

const COLUMNS: { role: AgentRole; label: string; tint: string }[] = [
  { role: 'designer',   label: 'Designer',   tint: 'bg-emerald-50 border-emerald-300 text-emerald-900' },
  { role: 'critic',     label: 'Critic',     tint: 'bg-rose-50 border-rose-300 text-rose-900' },
  { role: 'editor',     label: 'Editor',     tint: 'bg-sky-50 border-sky-300 text-sky-900' },
  { role: 'strategist', label: 'Strategist', tint: 'bg-violet-50 border-violet-300 text-violet-900' },
]

function MsgCard({ m }: { m: AgentMessage }) {
  const dot = (() => {
    if (m.confidence == null) return null
    if (m.confidence >= 0.85) return 'bg-emerald-500'
    if (m.confidence >= 0.65) return 'bg-amber-500'
    return 'bg-rose-500'
  })()
  return (
    <div className="bg-white rounded border border-slate-200 p-2 mb-2 shadow-sm">
      {dot && (
        <div className="flex items-center gap-1.5 mb-1">
          <span className={clsx('w-2 h-2 rounded-full', dot)} />
          <span className="text-[10px] text-slate-500">
            conf {(m.confidence ?? 0).toFixed(2)}
          </span>
        </div>
      )}
      <div className="text-xs leading-relaxed whitespace-pre-wrap font-mono text-slate-800">
        {m.content}
      </div>
    </div>
  )
}

export function MultiAgentColumns({ messages }: MultiAgentColumnsProps) {
  const grouped = COLUMNS.map((c) => ({
    ...c,
    msgs: messages.filter((m) => m.role === c.role),
  }))

  if (messages.length === 0) {
    return (
      <div className="text-slate-400 text-sm p-4">
        Multi-agent debate will appear here. Run a session to see Designer →
        Critic → Editor → Strategist collaborate in real time.
      </div>
    )
  }

  return (
    <div className="grid grid-cols-4 gap-2 p-2 h-full">
      {grouped.map((col) => (
        <div
          key={col.role}
          className={clsx('flex flex-col rounded border', col.tint, 'min-h-0')}
        >
          <div className="px-2 py-1.5 border-b border-current/30 text-xs font-semibold uppercase tracking-wider sticky top-0 bg-inherit">
            {col.label}
            <span className="ml-2 text-[10px] opacity-60 normal-case">
              {col.msgs.length} msg
            </span>
          </div>
          <div className="flex-1 overflow-y-auto p-1.5">
            {col.msgs.length === 0 ? (
              <div className="text-[10px] opacity-50 italic px-1">
                no messages yet
              </div>
            ) : (
              col.msgs.map((m) => <MsgCard key={m.id} m={m} />)
            )}
          </div>
        </div>
      ))}
    </div>
  )
}

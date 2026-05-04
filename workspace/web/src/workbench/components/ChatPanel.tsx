// Multi-agent chat panel (light theme)

import type { AgentMessage, AgentRole } from '../types'
import clsx from 'clsx'

interface ChatPanelProps {
  messages: AgentMessage[]
  status: 'idle' | 'running' | 'terminated' | 'error'
}

const ROLE_STYLE: Record<AgentRole, { color: string; label: string; bg: string; border: string }> = {
  system:     { color: 'text-slate-600',   label: 'system',     bg: 'bg-slate-50',    border: 'border-slate-300' },
  user:       { color: 'text-amber-700',   label: 'You',        bg: 'bg-amber-50',    border: 'border-amber-400' },
  designer:   { color: 'text-emerald-700', label: 'Designer',   bg: 'bg-emerald-50',  border: 'border-emerald-500' },
  critic:     { color: 'text-rose-700',    label: 'Critic',     bg: 'bg-rose-50',     border: 'border-rose-500' },
  editor:     { color: 'text-sky-700',     label: 'Editor',     bg: 'bg-sky-50',      border: 'border-sky-500' },
  strategist: { color: 'text-violet-700',  label: 'Strategist', bg: 'bg-violet-50',   border: 'border-violet-500' },
  tool:       { color: 'text-slate-600',   label: 'tool',       bg: 'bg-slate-50',    border: 'border-slate-300' },
}

function MessageRow({ m }: { m: AgentMessage }) {
  const style = ROLE_STYLE[m.role] ?? ROLE_STYLE.system
  return (
    <div className={clsx('px-3 py-2 rounded border-l-4 mb-2', style.bg, style.color, style.border)}>
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-semibold uppercase tracking-wider opacity-80">
          {style.label}
        </span>
        {m.confidence != null && (
          <span className="text-[10px] opacity-60">
            conf {m.confidence.toFixed(2)}
          </span>
        )}
      </div>
      <div className="text-sm leading-relaxed whitespace-pre-wrap font-mono">
        {m.content}
      </div>
    </div>
  )
}

export function ChatPanel({ messages, status }: ChatPanelProps) {
  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-2">
        {messages.length === 0 ? (
          <div className="text-slate-400 text-sm p-4">
            Multi-agent conversation appears here. Start a session to see the
            Designer, Critic, Editor, and Strategist agents collaborate.
          </div>
        ) : (
          messages.map((m) => <MessageRow key={m.id} m={m} />)
        )}
        {status === 'running' && (
          <div className="text-emerald-600 text-xs animate-pulse mt-2 px-3">
            agents thinking…
          </div>
        )}
        {status === 'terminated' && (
          <div className="text-emerald-700 text-xs mt-2 px-3 font-semibold">
            ◾ session complete
          </div>
        )}
        {status === 'error' && (
          <div className="text-rose-600 text-xs mt-2 px-3 font-semibold">
            ◾ session error
          </div>
        )}
      </div>
    </div>
  )
}

// ToolCallCard — single tool invocation rendered inline in the chat stream.
// Collapsed by default: tool name + duration + agent + ok/err glyph.
// Expanded: args (top) + result/error (bottom) in mono code.

import { useState } from 'react'
import { ChevronRight, CheckCircle2, AlertTriangle, Wrench } from 'lucide-react'
import clsx from 'clsx'
import type { ToolCallRecord } from '../types'
import { ROLE_META } from './AgentBadge'

interface ToolCallCardProps {
  call: ToolCallRecord
  defaultOpen?: boolean
}

function pretty(value: unknown, max = 1400): string {
  try {
    const s = JSON.stringify(value, null, 2)
    return s.length > max ? s.slice(0, max) + '\n…' : s
  } catch {
    return String(value)
  }
}

export function ToolCallCard({ call, defaultOpen = false }: ToolCallCardProps) {
  const [open, setOpen] = useState(defaultOpen)
  const ok = !call.error
  const meta = ROLE_META[call.agent as keyof typeof ROLE_META] ?? ROLE_META.system

  return (
    <div className={clsx(
      'rounded-md border bg-white text-[11px] font-mono',
      ok ? 'border-slate-200' : 'border-rose-200 bg-rose-50/60',
    )}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-2 py-1.5 hover:bg-slate-50 rounded-md transition-colors"
      >
        <ChevronRight className={clsx('h-3 w-3 text-slate-400 transition-transform shrink-0',
          open && 'rotate-90')} />
        <Wrench className="h-3 w-3 text-slate-500 shrink-0" />
        <span className="font-semibold text-slate-800 truncate">{call.tool}</span>
        <span className={clsx('text-[10px] tracking-tight px-1 py-px rounded', meta.text, meta.bg)}>
          {meta.label}
        </span>
        <span className="ml-auto text-slate-400 text-[10px] shrink-0">
          {call.duration_ms}ms
        </span>
        {ok ? (
          <CheckCircle2 className="h-3 w-3 text-emerald-600 shrink-0" />
        ) : (
          <AlertTriangle className="h-3 w-3 text-rose-600 shrink-0" />
        )}
      </button>

      {open && (
        <div className="border-t border-slate-200/70 divide-y divide-slate-100">
          {Object.keys(call.args || {}).length > 0 && (
            <div className="px-2 py-1.5">
              <div className="text-[9px] uppercase tracking-wider text-slate-400 mb-0.5">args</div>
              <pre className="text-[10.5px] leading-snug text-slate-700 whitespace-pre-wrap break-words">{pretty(call.args)}</pre>
            </div>
          )}
          {ok && call.result != null && (
            <div className="px-2 py-1.5">
              <div className="text-[9px] uppercase tracking-wider text-slate-400 mb-0.5">result</div>
              <pre className="text-[10.5px] leading-snug text-slate-700 whitespace-pre-wrap break-words">{pretty(call.result)}</pre>
            </div>
          )}
          {!ok && call.error && (
            <div className="px-2 py-1.5">
              <div className="text-[9px] uppercase tracking-wider text-rose-500 mb-0.5">error</div>
              <pre className="text-[10.5px] leading-snug text-rose-700 whitespace-pre-wrap break-words">{call.error}</pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

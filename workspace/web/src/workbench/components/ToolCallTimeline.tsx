// Timeline of tool calls — collapsible (light theme)

import { useState } from 'react'
import { ChevronDown, ChevronRight, AlertTriangle, CheckCircle2, Clock } from 'lucide-react'
import type { ToolCallRecord } from '../types'

interface ToolCallTimelineProps {
  calls: ToolCallRecord[]
}

function tsLabel(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return iso
  }
}

function CallRow({ call }: { call: ToolCallRecord }) {
  const [expanded, setExpanded] = useState(false)
  const Icon = expanded ? ChevronDown : ChevronRight
  const StatusIcon = call.error ? AlertTriangle : CheckCircle2
  const statusColor = call.error ? 'text-red-500' : 'text-emerald-600'

  return (
    <div className="border-b border-slate-200 last:border-0">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-slate-50"
      >
        <Icon className="w-3.5 h-3.5 mt-0.5 text-slate-400 shrink-0" />
        <span className="text-xs font-mono text-slate-500 shrink-0 w-20">
          {tsLabel(call.created_at)}
        </span>
        <StatusIcon className={`w-3.5 h-3.5 mt-0.5 shrink-0 ${statusColor}`} />
        <span className="font-mono text-sm text-emerald-700 shrink-0">
          {call.tool}
        </span>
        <span className="text-xs text-slate-500 truncate flex-1">
          ({call.agent}, {call.duration_ms}ms)
        </span>
        <Clock className="w-3 h-3 mt-1 text-slate-400 shrink-0" />
      </button>
      {expanded && (
        <div className="px-9 pb-3 text-xs">
          <div className="mb-2">
            <div className="text-slate-500 mb-1">args</div>
            <pre className="bg-slate-100 rounded p-2 text-slate-700 overflow-x-auto border border-slate-200">
              {JSON.stringify(call.args, null, 2)}
            </pre>
          </div>
          {call.error && (
            <div className="mb-2">
              <div className="text-red-500 mb-1">error</div>
              <pre className="bg-red-50 rounded p-2 text-red-700 overflow-x-auto border border-red-200">
                {call.error}
              </pre>
            </div>
          )}
          {call.result && (
            <div>
              <div className="text-slate-500 mb-1">result</div>
              <pre className="bg-slate-100 rounded p-2 text-slate-700 overflow-x-auto max-h-64 border border-slate-200">
                {JSON.stringify(call.result, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ToolCallTimeline({ calls }: ToolCallTimelineProps) {
  if (calls.length === 0) {
    return (
      <div className="text-slate-400 text-sm p-3">
        Tool calls appear here as the agent works.
      </div>
    )
  }
  return (
    <div className="divide-y divide-slate-200">
      {[...calls].reverse().map((c) => (
        <CallRow key={c.id} call={c} />
      ))}
    </div>
  )
}

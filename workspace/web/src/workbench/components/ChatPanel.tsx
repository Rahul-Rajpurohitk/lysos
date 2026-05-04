// ChatPanel — agentic conversation surface, claude.ai-style.
//
//  - Iteration boundaries inferred from the SSE iteration_start events.
//  - Messages render via MessageBubble (per-role styling, SMILES extraction).
//  - Tool calls appear inline AFTER the message that triggered them
//    (grouped per-agent + per-iteration, never duplicated).
//  - Sticky composer at bottom: textarea + Send. Sends as a directive
//    intervention while the loop is running.
//  - Auto-scrolls to bottom unless the user has scrolled up; "Jump to latest"
//    chip appears when not anchored.

import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, Send, Megaphone, Loader2, Filter, ListTree } from 'lucide-react'
import clsx from 'clsx'
import type { AgentMessage, AgentRole, ToolCallRecord } from '../types'
import { MessageBubble } from './MessageBubble'
import { ToolCallCard } from './ToolCallCard'
import { AgentBadge, ROLE_META } from './AgentBadge'

interface ChatPanelProps {
  messages: AgentMessage[]
  toolCalls: ToolCallRecord[]
  status: 'idle' | 'running' | 'terminated' | 'error'
  iteration: number
  maxIterations: number
  onSelectSmiles?: (smi: string) => void
  onSendDirective?: (text: string) => Promise<void>
  // For status indicator: which agent is "thinking" right now (the role of
  // the most-recent message + a pulse).
}

const ALL_ROLES: AgentRole[] = ['designer', 'critic', 'editor', 'strategist', 'user']

export function ChatPanel(props: ChatPanelProps) {
  const {
    messages, toolCalls, status, iteration, maxIterations,
    onSelectSmiles, onSendDirective,
  } = props

  const scrollRef = useRef<HTMLDivElement | null>(null)
  const bottomRef = useRef<HTMLDivElement | null>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  const [filter, setFilter] = useState<Set<AgentRole> | null>(null)

  // Composer state
  const [draft, setDraft] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Auto-scroll if pinned to bottom
  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [messages.length, toolCalls.length, autoScroll])

  function onScroll() {
    const el = scrollRef.current
    if (!el) return
    const threshold = 24
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < threshold
    setAutoScroll(atBottom)
  }

  const filteredMessages = useMemo(() => {
    if (!filter) return messages
    return messages.filter((m) => filter.has(m.role as AgentRole))
  }, [messages, filter])

  // Build grouped timeline: walk messages chronologically, attach the
  // tool-calls that happened between this message and the next (same agent
  // OR system-level scoring calls). This avoids duplicate rendering.
  const timeline = useMemo(() => buildTimeline(filteredMessages, toolCalls), [filteredMessages, toolCalls])

  // Active-agent indicator: most recent message's role
  const lastRole = (messages[messages.length - 1]?.role ?? 'system') as AgentRole

  async function send() {
    const text = draft.trim()
    if (!text || !onSendDirective) return
    setSending(true)
    setError(null)
    try {
      await onSendDirective(text)
      setDraft('')
    } catch (e) {
      setError(String(e))
    } finally {
      setSending(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-white">
      {/* Toolbar */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-slate-200 bg-slate-50/40">
        <ListTree className="h-3.5 w-3.5 text-slate-400" />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">
          Conversation
        </span>
        <span className="text-[10px] text-slate-400 font-mono">
          {messages.length} msg · {toolCalls.length} tools
        </span>

        <div className="ml-auto flex items-center gap-1">
          <Filter className="h-3 w-3 text-slate-400" />
          {ALL_ROLES.map((r) => {
            const active = !filter || filter.has(r)
            const m = ROLE_META[r]
            return (
              <button
                key={r}
                onClick={() => {
                  setFilter((prev) => {
                    const next = new Set(prev ?? new Set(ALL_ROLES))
                    if (next.has(r)) next.delete(r)
                    else next.add(r)
                    if (next.size === ALL_ROLES.length) return null
                    if (next.size === 0) return null
                    return next
                  })
                }}
                title={m.label}
                className={clsx(
                  'h-5 w-5 rounded-md flex items-center justify-center ring-1 transition',
                  active ? `${m.bg} ${m.ring}` : 'bg-white ring-slate-200 opacity-40',
                )}
              >
                <m.Icon className={clsx('h-3 w-3', active ? m.text : 'text-slate-400')} strokeWidth={2.25} />
              </button>
            )
          })}
        </div>
      </div>

      {/* Iteration meter */}
      {(iteration > 0 || status === 'running') && (
        <div className="px-3 py-1.5 border-b border-slate-200/70 bg-white">
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-widest text-slate-400 font-semibold">
              Iteration
            </span>
            <span className="text-[11px] font-mono text-slate-700 font-semibold">
              {iteration}/{maxIterations}
            </span>
            <div className="flex-1 h-1 rounded-full bg-slate-100 overflow-hidden">
              <div
                className={clsx('h-full transition-all', status === 'running'
                  ? 'bg-emerald-400'
                  : status === 'terminated' ? 'bg-emerald-600'
                  : status === 'error' ? 'bg-rose-500' : 'bg-slate-300')}
                style={{ width: `${Math.min(100, (iteration / Math.max(1, maxIterations)) * 100)}%` }}
              />
            </div>
            {status === 'running' && (
              <span className="inline-flex items-center gap-1 text-[10px] text-emerald-700">
                <Loader2 className="h-3 w-3 animate-spin" />
                <AgentBadge role={lastRole} size="xs" pulse />
              </span>
            )}
            {status === 'terminated' && (
              <span className="text-[10px] font-semibold text-emerald-700">complete</span>
            )}
            {status === 'error' && (
              <span className="text-[10px] font-semibold text-rose-700">error</span>
            )}
          </div>
        </div>
      )}

      {/* Scrollable body */}
      <div
        ref={scrollRef}
        onScroll={onScroll}
        className="flex-1 overflow-y-auto px-2.5 py-2 relative"
      >
        {timeline.length === 0 ? (
          <EmptyState />
        ) : (
          timeline.map((entry, i) => {
            if (entry.kind === 'iter') {
              return <IterationDivider key={`it-${i}`} n={entry.n} />
            }
            return (
              <div key={entry.message.id} className="animate-fade-in">
                <MessageBubble message={entry.message} onSelectSmiles={onSelectSmiles} />
                {entry.tools.length > 0 && (
                  <div className="ml-2 pl-3 border-l-2 border-slate-100 space-y-1 -mt-1 mb-2">
                    {entry.tools.map((tc) => (
                      <ToolCallCard key={tc.id} call={tc} />
                    ))}
                  </div>
                )}
              </div>
            )
          })
        )}
        <div ref={bottomRef} />

        {!autoScroll && (
          <button
            onClick={() => {
              setAutoScroll(true)
              bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
            }}
            className="sticky bottom-2 left-1/2 -translate-x-1/2 inline-flex items-center gap-1 bg-slate-900 text-white text-[10px] px-2 py-1 rounded-full shadow-lg"
          >
            <ArrowDown className="h-3 w-3" /> Jump to latest
          </button>
        )}
      </div>

      {/* Composer (intervene-style; only meaningful while running) */}
      <div className={clsx(
        'border-t border-slate-200 px-2.5 py-2 transition',
        status === 'running' ? 'bg-amber-50/30' : 'bg-slate-50/40',
      )}>
        <div className="flex items-end gap-2">
          <Megaphone className={clsx('h-3.5 w-3.5 mt-1.5 shrink-0',
            status === 'running' ? 'text-amber-600' : 'text-slate-400')} />
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') send()
            }}
            disabled={sending || status !== 'running'}
            placeholder={
              status === 'running'
                ? 'Intervene · "focus on penam scaffolds, drop fluoroquinolones" (⌘↵)'
                : 'Composer activates while a session is running'
            }
            rows={2}
            className={clsx(
              'flex-1 resize-none rounded-md border bg-white px-2 py-1.5 text-[12px] font-mono leading-snug',
              'focus:outline-none focus:ring-2 focus:ring-amber-300/40 focus:border-amber-400',
              'placeholder:text-slate-300',
              status !== 'running' && 'border-slate-200 opacity-60',
              status === 'running' && 'border-amber-300/70',
            )}
          />
          <button
            onClick={send}
            disabled={sending || !draft.trim() || status !== 'running'}
            className={clsx(
              'shrink-0 inline-flex items-center gap-1 px-2.5 py-1.5 rounded-md text-[11px] font-semibold transition',
              'bg-slate-900 text-white hover:bg-slate-800',
              'disabled:bg-slate-200 disabled:text-slate-400',
            )}
          >
            {sending
              ? <Loader2 className="h-3 w-3 animate-spin" />
              : <Send className="h-3 w-3" />}
            Push
          </button>
        </div>
        {error && (
          <div className="mt-1 text-[10px] text-rose-600">{error}</div>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------
function EmptyState() {
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-6 py-10 text-slate-400">
      <div className="text-[40px] leading-none mb-3">⌬</div>
      <div className="text-[12px] font-semibold text-slate-500">
        No conversation yet
      </div>
      <div className="text-[11px] mt-1 max-w-[260px]">
        Press <kbd className="px-1.5 py-0.5 rounded border border-slate-200 bg-white text-slate-600 font-mono text-[10px]">Start</kbd> to launch the multi-agent loop. Designer · Critic · Editor · Strategist will collaborate to design a candidate.
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Iteration divider
// ---------------------------------------------------------------------------
function IterationDivider({ n }: { n: number }) {
  return (
    <div className="flex items-center gap-2 my-2 text-[10px] uppercase tracking-widest text-slate-400 font-semibold">
      <div className="flex-1 h-px bg-slate-200" />
      <span className="px-1.5 py-0.5 rounded bg-slate-100 text-slate-500">iter {n}</span>
      <div className="flex-1 h-px bg-slate-200" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Timeline builder — interleaves iteration markers + groups tool calls under
// the message that produced them.
// ---------------------------------------------------------------------------
type TimelineEntry =
  | { kind: 'iter'; n: number; ts: number }
  | { kind: 'msg'; message: AgentMessage; tools: ToolCallRecord[]; ts: number }

function buildTimeline(messages: AgentMessage[], tools: ToolCallRecord[]): TimelineEntry[] {
  if (messages.length === 0 && tools.length === 0) return []

  // Sort by created_at
  const ts = (s: string) => new Date(s).getTime() || 0
  const sortedMsgs = [...messages].sort((a, b) => ts(a.created_at) - ts(b.created_at))
  const sortedTools = [...tools].sort((a, b) => ts(a.created_at) - ts(b.created_at))

  // Attach each tool call to the most-recent prior message from the same agent
  // (or system-level if no message of that agent exists yet).
  const toolByMsg = new Map<string, ToolCallRecord[]>()
  const orphanTools: ToolCallRecord[] = []
  for (const tc of sortedTools) {
    let attach: AgentMessage | null = null
    for (let i = sortedMsgs.length - 1; i >= 0; i--) {
      const m = sortedMsgs[i]
      if (ts(m.created_at) > ts(tc.created_at)) continue
      if (m.role === tc.agent || tc.agent === 'system') {
        attach = m
        break
      }
    }
    if (attach) {
      const arr = toolByMsg.get(attach.id) ?? []
      arr.push(tc)
      toolByMsg.set(attach.id, arr)
    } else {
      orphanTools.push(tc)
    }
  }

  // Infer iteration boundaries: each Designer message starts a new iteration
  const out: TimelineEntry[] = []
  let iter = 0
  for (const m of sortedMsgs) {
    if (m.role === 'designer') {
      iter += 1
      out.push({ kind: 'iter', n: iter, ts: ts(m.created_at) })
    }
    out.push({
      kind: 'msg', message: m, tools: toolByMsg.get(m.id) ?? [], ts: ts(m.created_at),
    })
  }

  // Surface orphans (tool calls that arrived before any message — strategist init)
  if (orphanTools.length > 0) {
    out.unshift({
      kind: 'msg',
      message: {
        id: 'preflight',
        role: 'system',
        content: 'Pre-flight tool calls (resistome bootstrap)',
        tool_calls: [],
        confidence: null,
        created_at: orphanTools[0].created_at,
      },
      tools: orphanTools,
      ts: ts(orphanTools[0].created_at),
    })
  }

  return out
}

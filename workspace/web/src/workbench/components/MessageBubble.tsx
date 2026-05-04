// MessageBubble — renders a single AgentMessage with structured parsing.
// Recognizes:
//   PROPOSAL: <SMILES>           -> highlighted SMILES card with copy button
//   RATIONALE: <text>            -> indented italic body
//   WEAKNESS / TRANSFORMATION /  -> labelled key/value rows (Critic blocks)
//     EXPECTED_DELTA / VERDICT
//   ```...``` fenced blocks      -> mono code block with copy
// Falls back to plain text otherwise. Keeps the rendering tight + scannable.

import { useState } from 'react'
import { Copy, Check, ChevronDown } from 'lucide-react'
import clsx from 'clsx'
import type { AgentMessage } from '../types'
import { AgentBadge, ROLE_META } from './AgentBadge'

interface MessageBubbleProps {
  message: AgentMessage
  onSelectSmiles?: (smi: string) => void
}

interface ParsedBlock {
  kind: 'text' | 'proposal' | 'rationale' | 'weakness' | 'transformation' |
        'expected_delta' | 'verdict' | 'decision' | 'fence'
  value: string
  language?: string
}

const KEY_RE = /^(PROPOSAL|RATIONALE|WEAKNESS|TRANSFORMATION|EXPECTED_DELTA|VERDICT|DECISION):\s*(.+)$/i

function parseContent(content: string): ParsedBlock[] {
  const out: ParsedBlock[] = []
  const fenceRe = /```(\w*)\n([\s\S]*?)```/g
  let lastIdx = 0
  let m: RegExpExecArray | null
  while ((m = fenceRe.exec(content)) !== null) {
    if (m.index > lastIdx) {
      pushPlain(out, content.slice(lastIdx, m.index))
    }
    out.push({ kind: 'fence', value: m[2].trim(), language: m[1] || 'text' })
    lastIdx = fenceRe.lastIndex
  }
  if (lastIdx < content.length) {
    pushPlain(out, content.slice(lastIdx))
  }
  return out
}

function pushPlain(out: ParsedBlock[], chunk: string) {
  for (const rawLine of chunk.split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line) continue
    const k = line.match(KEY_RE)
    if (k) {
      out.push({ kind: k[1].toLowerCase() as ParsedBlock['kind'], value: k[2].trim() })
    } else {
      const last = out[out.length - 1]
      if (last && last.kind === 'text') {
        last.value += '\n' + line
      } else {
        out.push({ kind: 'text', value: line })
      }
    }
  }
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <button
      onClick={(e) => {
        e.stopPropagation()
        navigator.clipboard.writeText(text)
        setCopied(true)
        setTimeout(() => setCopied(false), 1500)
      }}
      className="opacity-0 group-hover:opacity-100 text-slate-400 hover:text-slate-700 transition-opacity p-0.5 rounded"
      title="Copy"
    >
      {copied
        ? <Check className="h-3 w-3 text-emerald-600" />
        : <Copy className="h-3 w-3" />}
    </button>
  )
}

function ProposalCard({ smiles, onSelect }: { smiles: string; onSelect?: (s: string) => void }) {
  return (
    <div className="group rounded-lg border border-emerald-300/60 bg-emerald-50/60 px-2.5 py-2 mt-1.5">
      <div className="flex items-center gap-1.5 mb-0.5">
        <span className="text-[9px] uppercase tracking-widest font-bold text-emerald-700">
          Proposal
        </span>
        <CopyButton text={smiles} />
        {onSelect && (
          <button
            onClick={() => onSelect(smiles)}
            className="ml-auto text-[10px] text-emerald-700 hover:text-emerald-900 px-1.5 py-0.5 rounded hover:bg-emerald-100"
          >
            View →
          </button>
        )}
      </div>
      <div className="font-mono text-[11px] text-emerald-900 leading-snug break-all">
        {smiles}
      </div>
    </div>
  )
}

function KeyRow({ label, value, accent }: { label: string; value: string; accent: string }) {
  return (
    <div className="flex items-baseline gap-2 mt-1">
      <span className={clsx('text-[9.5px] uppercase tracking-widest font-bold shrink-0 w-[88px]', accent)}>
        {label}
      </span>
      <span className="text-[12px] font-mono text-slate-700 leading-snug">{value}</span>
    </div>
  )
}

function FenceBlock({ value, language }: { value: string; language?: string }) {
  return (
    <div className="group relative rounded-md border border-slate-200 bg-slate-50 mt-1.5">
      <div className="flex items-center gap-2 px-2 py-1 border-b border-slate-200/80">
        <span className="text-[9px] uppercase tracking-widest text-slate-400">{language ?? 'text'}</span>
        <CopyButton text={value} />
      </div>
      <pre className="text-[11px] font-mono text-slate-800 leading-snug px-2 py-1.5 overflow-x-auto whitespace-pre-wrap break-words">{value}</pre>
    </div>
  )
}

export function MessageBubble({ message, onSelectSmiles }: MessageBubbleProps) {
  const meta = ROLE_META[message.role]
  const [open, setOpen] = useState(true)
  const blocks = parseContent(message.content)

  const ts = (() => {
    try {
      return new Date(message.created_at).toLocaleTimeString([], {
        hour: '2-digit', minute: '2-digit', second: '2-digit',
      })
    } catch { return '' }
  })()

  return (
    <div className={clsx('group rounded-lg border bg-white px-3 py-2 mb-2 shadow-[0_1px_0_rgba(15,23,42,0.04)]',
      'border-slate-200/70')}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 text-left"
      >
        <AgentBadge role={message.role} size="xs" />
        {message.confidence != null && (
          <span className="text-[10px] text-slate-400 font-mono">
            conf {message.confidence.toFixed(2)}
          </span>
        )}
        <span className="ml-auto text-[10px] text-slate-300 font-mono opacity-0 group-hover:opacity-100 transition">
          {ts}
        </span>
        <ChevronDown className={clsx('h-3 w-3 text-slate-300 transition-transform', !open && '-rotate-90')} />
      </button>

      {open && (
        <div className="mt-1 pl-1">
          {blocks.map((b, i) => {
            switch (b.kind) {
              case 'proposal':
                return <ProposalCard key={i} smiles={b.value} onSelect={onSelectSmiles} />
              case 'fence':
                return <FenceBlock key={i} value={b.value} language={b.language} />
              case 'rationale':
                return (
                  <div key={i} className="mt-1.5 text-[12px] text-slate-700 leading-relaxed italic border-l-2 border-slate-200 pl-2">
                    {b.value}
                  </div>
                )
              case 'weakness':
                return <KeyRow key={i} label="Weakness" value={b.value} accent="text-rose-700" />
              case 'transformation':
                return <KeyRow key={i} label="Transform" value={b.value} accent="text-sky-700" />
              case 'expected_delta':
                return <KeyRow key={i} label="delta-expect" value={b.value} accent="text-emerald-700" />
              case 'verdict':
                return (
                  <div key={i} className="mt-1.5 inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-800 text-[11px] font-bold tracking-wide">
                    Verdict · {b.value}
                  </div>
                )
              case 'decision':
                return <KeyRow key={i} label="Decision" value={b.value} accent={meta.text} />
              default:
                return (
                  <div key={i} className="mt-0.5 text-[12.5px] text-slate-700 leading-relaxed whitespace-pre-wrap">
                    {b.value}
                  </div>
                )
            }
          })}
        </div>
      )}
    </div>
  )
}

// AgentBadge — consistent role-pill used across the chat + columns + lineage.
// Iconography mirrors the agent semantics in agents/prompts.py:
//   Designer  → FlaskConical (proposes molecules)
//   Critic    → ScanSearch    (evaluates + finds weakness)
//   Editor    → PenLine       (applies transformation)
//   Strategist→ Compass       (decides terminate/continue/branch)

import {
  FlaskConical, ScanSearch, PenLine, Compass,
  User as UserIcon, Bot, Wrench,
} from 'lucide-react'
import type { AgentRole } from '../types'
import clsx from 'clsx'

export const ROLE_META: Record<AgentRole, {
  label: string
  Icon: typeof Bot
  text: string    // foreground text colour
  ring: string    // border colour
  bg: string      // background colour
  dot: string     // status dot
}> = {
  designer:   { label: 'Designer',   Icon: FlaskConical, text: 'text-emerald-700',  ring: 'ring-emerald-300/70', bg: 'bg-emerald-50', dot: 'bg-emerald-500' },
  critic:     { label: 'Critic',     Icon: ScanSearch,   text: 'text-rose-700',     ring: 'ring-rose-300/70',    bg: 'bg-rose-50',    dot: 'bg-rose-500'    },
  editor:     { label: 'Editor',     Icon: PenLine,      text: 'text-sky-700',      ring: 'ring-sky-300/70',     bg: 'bg-sky-50',     dot: 'bg-sky-500'     },
  strategist: { label: 'Strategist', Icon: Compass,      text: 'text-violet-700',   ring: 'ring-violet-300/70',  bg: 'bg-violet-50',  dot: 'bg-violet-500'  },
  user:       { label: 'You',        Icon: UserIcon,     text: 'text-amber-700',    ring: 'ring-amber-300/70',   bg: 'bg-amber-50',   dot: 'bg-amber-500'   },
  system:     { label: 'System',     Icon: Bot,          text: 'text-slate-600',    ring: 'ring-slate-300/70',   bg: 'bg-slate-100',  dot: 'bg-slate-400'   },
  tool:       { label: 'Tool',       Icon: Wrench,       text: 'text-slate-600',    ring: 'ring-slate-300/70',   bg: 'bg-slate-100',  dot: 'bg-slate-400'   },
}

interface AgentBadgeProps {
  role: AgentRole
  size?: 'xs' | 'sm' | 'md'
  showLabel?: boolean
  pulse?: boolean
  className?: string
}

export function AgentBadge({
  role, size = 'sm', showLabel = true, pulse = false, className,
}: AgentBadgeProps) {
  const m = ROLE_META[role] ?? ROLE_META.system
  const sizing = {
    xs: { box: 'h-5 px-1.5', icon: 'h-3 w-3', text: 'text-[10px]' },
    sm: { box: 'h-6 px-2',   icon: 'h-3.5 w-3.5', text: 'text-[11px]' },
    md: { box: 'h-7 px-2.5', icon: 'h-4 w-4', text: 'text-[12px]' },
  }[size]
  return (
    <span className={clsx(
      'inline-flex items-center gap-1.5 rounded-md ring-1 font-semibold tracking-tight',
      sizing.box, sizing.text, m.text, m.bg, m.ring, className,
    )}>
      <m.Icon className={sizing.icon} strokeWidth={2.25} />
      {showLabel && <span>{m.label}</span>}
      {pulse && <span className={clsx('h-1.5 w-1.5 rounded-full animate-pulse', m.dot)} />}
    </span>
  )
}

// Mid-loop intervention bar — visible only while a session is running.
// Lets the user push a free-text directive or a quick constraint that the
// Designer will consume on its next iteration.

import { useState } from 'react'
import { Megaphone, Send } from 'lucide-react'
import { intervene } from '../api'

interface InterveneBarProps {
  sessionId: string | null
  running: boolean
}

export function InterveneBar({ sessionId, running }: InterveneBarProps) {
  const [text, setText] = useState('')
  const [pending, setPending] = useState(false)
  const [confirmation, setConfirmation] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (!running || !sessionId) return null

  async function send() {
    if (!sessionId || !text.trim()) return
    setPending(true)
    setError(null)
    try {
      const r = await intervene(sessionId, { kind: 'directive', payload: text.trim() })
      setConfirmation(`queued (depth ${r.queue_depth})`)
      setText('')
      setTimeout(() => setConfirmation(null), 2500)
    } catch (e) {
      setError(String(e))
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex items-center gap-2 px-3 py-2 bg-amber-50 border-t border-amber-200">
      <Megaphone className="w-4 h-4 text-amber-700 shrink-0" />
      <span className="text-[10px] font-semibold uppercase tracking-wider text-amber-800 shrink-0">
        Intervene
      </span>
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === 'Enter') send() }}
        placeholder="e.g. focus on penam scaffolds, drop fluoroquinolones"
        disabled={pending}
        className="flex-1 bg-white border border-amber-300 rounded px-2 py-1 text-xs font-mono focus:outline-none focus:border-amber-500"
      />
      <button
        onClick={send}
        disabled={pending || !text.trim()}
        className="bg-amber-600 hover:bg-amber-500 disabled:bg-amber-300 text-white px-2.5 py-1 rounded text-xs flex items-center gap-1.5 shrink-0"
      >
        <Send className="w-3 h-3" />
        Push
      </button>
      {confirmation && (
        <span className="text-[10px] text-emerald-700 shrink-0">{confirmation}</span>
      )}
      {error && (
        <span className="text-[10px] text-rose-700 shrink-0">{error}</span>
      )}
    </div>
  )
}

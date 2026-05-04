// Time-travel scrubber — slider through agent's history

import { useEffect, useState } from 'react'
import { Pause, Play, ChevronsLeft, ChevronsRight } from 'lucide-react'
import type { Candidate } from '../types'

interface ReplayScrubberProps {
  candidates: Candidate[]
  selectedId: string | null
  onSelect: (id: string) => void
}

export function ReplayScrubber({ candidates, selectedId, onSelect }: ReplayScrubberProps) {
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(800)  // ms per step

  const currentIndex = selectedId
    ? candidates.findIndex((c) => c.id === selectedId)
    : candidates.length - 1

  useEffect(() => {
    if (!playing) return
    const id = setInterval(() => {
      const next = currentIndex + 1
      if (next >= candidates.length) {
        setPlaying(false)
        return
      }
      onSelect(candidates[next].id)
    }, speed)
    return () => clearInterval(id)
  }, [playing, speed, currentIndex, candidates, onSelect])

  if (candidates.length === 0) {
    return (
      <div className="text-slate-400 text-xs px-3 py-2">
        Replay scrubber appears as candidates accumulate.
      </div>
    )
  }

  return (
    <div className="px-3 py-2 bg-slate-50 border-t border-slate-200 flex items-center gap-3">
      <button
        onClick={() => onSelect(candidates[0].id)}
        className="text-slate-500 hover:text-slate-700"
        title="Jump to first"
      >
        <ChevronsLeft className="w-4 h-4" />
      </button>
      <button
        onClick={() => setPlaying((p) => !p)}
        className="text-emerald-600 hover:text-emerald-700"
        title="Play / pause replay"
      >
        {playing ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4" />}
      </button>
      <button
        onClick={() => onSelect(candidates[candidates.length - 1].id)}
        className="text-slate-500 hover:text-slate-700"
        title="Jump to last"
      >
        <ChevronsRight className="w-4 h-4" />
      </button>

      <input
        type="range"
        min={0}
        max={candidates.length - 1}
        value={Math.max(0, currentIndex)}
        onChange={(e) => onSelect(candidates[Number(e.target.value)].id)}
        className="flex-1 accent-emerald-600"
      />

      <span className="text-xs font-mono text-slate-600 w-16">
        {Math.max(0, currentIndex) + 1}/{candidates.length}
      </span>

      <select
        value={speed}
        onChange={(e) => setSpeed(Number(e.target.value))}
        className="text-xs bg-white border border-slate-300 rounded px-1.5 py-0.5"
      >
        <option value={1500}>1×</option>
        <option value={800}>2×</option>
        <option value={400}>4×</option>
        <option value={200}>8×</option>
      </select>
    </div>
  )
}

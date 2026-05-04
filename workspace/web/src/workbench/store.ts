// Workbench Zustand store — local UI state + session sync

import { create } from 'zustand'
import type { Candidate, AgentMessage, ToolCallRecord, WorkbenchState } from './types'

interface WorkbenchStore {
  sessionId: string | null
  state: WorkbenchState | null
  candidates: Candidate[]
  history: AgentMessage[]
  toolCalls: ToolCallRecord[]
  paretoFrontier: string[]
  selectedCandidateId: string | null
  iteration: number
  status: 'idle' | 'running' | 'terminated' | 'error'
  errorMessage: string | null

  setSessionId: (id: string) => void
  setState: (s: WorkbenchState) => void
  addCandidate: (c: Candidate) => void
  addMessage: (m: AgentMessage) => void
  addToolCall: (t: ToolCallRecord) => void
  setStatus: (s: WorkbenchStore['status']) => void
  setError: (msg: string | null) => void
  setSelected: (id: string | null) => void
  reset: () => void
}

export const useWorkbench = create<WorkbenchStore>((set) => ({
  sessionId: null,
  state: null,
  candidates: [],
  history: [],
  toolCalls: [],
  paretoFrontier: [],
  selectedCandidateId: null,
  iteration: 0,
  status: 'idle',
  errorMessage: null,

  setSessionId: (sessionId) => set({ sessionId }),
  setState: (state) => set({
    state,
    candidates: state.candidates,
    history: state.history,
    toolCalls: state.tool_calls,
    paretoFrontier: state.pareto_frontier,
    iteration: state.iteration,
  }),
  addCandidate: (c) => set((s) => ({
    candidates: [...s.candidates, c],
    selectedCandidateId: c.id,
  })),
  addMessage: (m) => set((s) => ({ history: [...s.history, m] })),
  addToolCall: (t) => set((s) => ({ toolCalls: [...s.toolCalls, t] })),
  setStatus: (status) => set({ status }),
  setError: (errorMessage) => set({ errorMessage }),
  setSelected: (id) => set({ selectedCandidateId: id }),
  reset: () => set({
    sessionId: null, state: null,
    candidates: [], history: [], toolCalls: [],
    paretoFrontier: [], selectedCandidateId: null,
    iteration: 0, status: 'idle', errorMessage: null,
  }),
}))

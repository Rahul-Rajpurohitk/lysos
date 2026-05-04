// Workbench API client — typed REST + SSE wrappers

import type {
  Pathogen, Mode, Autonomy, Constraint,
  WorkbenchState, SSEEvent, PathogenInfo,
} from './types'

const API_BASE = '/workbench'

export interface CreateSessionInput {
  target_pathogen: Pathogen
  mode?: Mode
  autonomy?: Autonomy
  constraints?: Constraint[]
  max_iterations?: number
}

export async function createSession(input: CreateSessionInput): Promise<{ session_id: string }> {
  const res = await fetch(`${API_BASE}/sessions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  })
  if (!res.ok) throw new Error(`createSession ${res.status}`)
  return res.json()
}

export async function getSession(id: string): Promise<WorkbenchState> {
  const res = await fetch(`${API_BASE}/sessions/${id}`)
  if (!res.ok) throw new Error(`getSession ${res.status}`)
  return res.json()
}

export async function startSession(id: string): Promise<{ status: string }> {
  const res = await fetch(`${API_BASE}/sessions/${id}/start`, { method: 'POST' })
  if (!res.ok) throw new Error(`startSession ${res.status}`)
  return res.json()
}

export interface SessionListItem {
  session_id: string
  target_pathogen: Pathogen
  mode: Mode
  autonomy: Autonomy
  iteration: number
  max_iterations: number
  n_candidates: number
  n_pareto: number
  last_composite: number
  terminated: boolean
  termination_reason: string | null
}

export async function listSessions(): Promise<{ total: number; sessions: SessionListItem[] }> {
  const res = await fetch(`${API_BASE}/sessions`)
  if (!res.ok) throw new Error(`listSessions ${res.status}`)
  return res.json()
}

export type Intervention =
  | { kind: 'constraint'; payload: Constraint }
  | { kind: 'directive'; payload: string }

export async function intervene(
  sessionId: string, intervention: Intervention,
): Promise<{ session_id: string; queued: boolean; queue_depth: number }> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/intervene`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(intervention),
  })
  if (!res.ok) throw new Error(`intervene ${res.status}`)
  return res.json()
}

export async function fetchNotebook(sessionId: string): Promise<unknown> {
  const res = await fetch(`${API_BASE}/sessions/${sessionId}/notebook`)
  if (!res.ok) throw new Error(`fetchNotebook ${res.status}`)
  return res.json()
}

export async function listPathogens(): Promise<{ pathogens: PathogenInfo[] }> {
  const res = await fetch(`${API_BASE}/pathogens`)
  if (!res.ok) throw new Error(`listPathogens ${res.status}`)
  return res.json()
}

export async function listSkills(): Promise<{ total: number; by_category: Record<string, unknown[]> }> {
  const res = await fetch(`${API_BASE}/skills`)
  if (!res.ok) throw new Error(`listSkills ${res.status}`)
  return res.json()
}

export async function invokeTool(name: string, args: Record<string, unknown>): Promise<unknown> {
  const res = await fetch(`${API_BASE}/tools/${name}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(args),
  })
  if (!res.ok) throw new Error(`invokeTool ${res.status}`)
  return res.json()
}

// SSE streaming — returns an EventSource that the caller manages.
export function streamEvents(
  sessionId: string,
  onEvent: (ev: SSEEvent) => void,
  onError?: (err: Error) => void,
): EventSource {
  const es = new EventSource(`${API_BASE}/sessions/${sessionId}/events`)
  const types: SSEEvent['type'][] = [
    'agent_message', 'tool_call_result', 'tool_call_start',
    'candidate_added', 'iteration_start', 'agent_idle',
    'intervention', 'session_complete', 'error', 'ping',
  ]
  for (const t of types) {
    es.addEventListener(t, (e) => {
      try {
        const data = JSON.parse((e as MessageEvent).data)
        onEvent({ type: t, ...data })
      } catch (err) {
        console.error('SSE parse error', err)
      }
    })
  }
  es.onerror = (err) => {
    if (onError) onError(err as unknown as Error)
  }
  return es
}

// Workbench TypeScript types — mirrors workspace/agents/state.py

export type Pathogen =
  | 'MRSA' | 'Mtb' | 'EColi-CRE' | 'KpneuCRE'
  | 'Abaum' | 'Paer' | 'VRE' | 'NGono'

export type Mode = 'design' | 'red_team' | 'compare'
export type Autonomy = 'auto' | 'copilot' | 'manual'

export interface CandidateScores {
  validity: number
  structural_alerts: number
  predicted_mic: number
  drug_likeness_qed: number
  synthesizability: number
  hemolysis_safety: number
  novelty: number
  embedding_novelty: number
  composite: number
}

export interface Candidate {
  id: string
  smiles: string
  parent_id: string | null
  pathogen: Pathogen
  scores: CandidateScores
  affinity_kcal_mol: number | null
  similar_to: string[]
  notes: string[]
  created_at: string
}

export interface ToolCallRecord {
  id: string
  tool: string
  args: Record<string, unknown>
  result: Record<string, unknown> | null
  error: string | null
  duration_ms: number
  agent: string
  created_at: string
}

export type AgentRole =
  | 'system' | 'user' | 'designer' | 'critic'
  | 'editor' | 'strategist' | 'tool'

export interface AgentMessage {
  id: string
  role: AgentRole
  content: string
  tool_calls: ToolCallRecord[]
  confidence: number | null
  created_at: string
}

export interface Constraint {
  type: 'property_min' | 'property_max' | 'exclude_smarts' | 'require_smarts'
  field: string
  value: unknown
}

export interface WorkbenchState {
  session_id: string
  target_pathogen: Pathogen
  mode: Mode
  autonomy: Autonomy
  constraints: Constraint[]
  candidates: Candidate[]
  current_candidate_id: string | null
  history: AgentMessage[]
  tool_calls: ToolCallRecord[]
  pareto_frontier: string[]
  iteration: number
  max_iterations: number
  terminated: boolean
  termination_reason: string | null
}

export type SSEEventType =
  | 'agent_message'
  | 'tool_call_result'
  | 'tool_call_start'
  | 'candidate_added'
  | 'iteration_start'
  | 'agent_idle'
  | 'session_complete'
  | 'error'
  | 'ping'

export interface SSEEvent<T = unknown> {
  type: SSEEventType
  agent?: string
  data?: T
}

export interface PathogenInfo {
  code: Pathogen
  name: string
  intrinsic_features: string[]
  resistome_count: number
  first_line_count: number
  common_syndromes: string[]
}

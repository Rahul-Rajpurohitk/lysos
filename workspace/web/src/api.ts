// Lysos API client — typed wrappers for the FastAPI backend.

export interface Pathogen {
  short: string;
  name: string;
  category: string;
  priority: "critical" | "high";
  description: string;
}

export interface CandidateScores {
  validity: number;
  predicted_mic: number;
  drug_likeness_qed: number;
  synthesizability: number;
  hemolysis_safety: number;
  novelty: number;
}

export interface Candidate {
  smiles: string | null;
  sequence: string | null;
  raw: string;
  scores: CandidateScores;
  combined: number;
}

export interface DesignResponse {
  target: string;
  pathogen: Pathogen;
  n_total: number;
  n_returned: number;
  elapsed_s: number;
  model: string;
  candidates: Candidate[];
  aggregate: Record<string, number>;
}

export interface DesignRequest {
  target: string;
  n?: number;
  modality?: "smiles" | "peptide";
  temperature?: number;
  top_p?: number;
  max_new_tokens?: number;
  return_top?: number;
}

export interface Health {
  status: string;
  model: string | null;
  loaded: boolean;
  uptime_s: number;
}

const API_BASE = ""; // same-origin

export async function fetchPathogens(): Promise<Pathogen[]> {
  const r = await fetch(`${API_BASE}/api/pathogens`);
  if (!r.ok) throw new Error(`pathogens fetch failed: ${r.status}`);
  return r.json();
}

export async function fetchHealth(): Promise<Health> {
  const r = await fetch(`${API_BASE}/api/health`);
  if (!r.ok) throw new Error(`health fetch failed: ${r.status}`);
  return r.json();
}

export async function design(req: DesignRequest): Promise<DesignResponse> {
  const r = await fetch(`${API_BASE}/api/design`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) {
    const detail = await r.text().catch(() => "");
    throw new Error(`design failed: ${r.status} ${detail}`);
  }
  return r.json();
}

export async function scoreSmiles(smiles: string, target = "MRSA") {
  const r = await fetch(`${API_BASE}/api/score?smiles=${encodeURIComponent(smiles)}&target=${target}`);
  if (!r.ok) throw new Error(`score failed: ${r.status}`);
  return r.json();
}

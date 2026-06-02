/**
 * ResistanceEscapeMapCard — Service 2 (heavy refactor, lavender-glass).
 *
 * Three modes:
 *   1. MAP        — heatmap (residue × mutation) with click cross-link
 *                   to 2D builder atom + 3D Theater residue.
 *   2. HARDEN     — pick a vulnerable atom → /chem/resistance/harden →
 *                   ranked substituent-swap suggestions (Gemini + playbook).
 *   3. COMPARE    — pick N session candidates → side-by-side robustness +
 *                   common-weak-residues summary.
 *
 * Design language: NOVEL lavender-glass — translucent accent bg, capsule
 * chips, click-to-collapse headers, font 9.5px/500/22-px height, no
 * black, body font-family. Mirrors the 2D / 3D canvas overlay style.
 *
 * Cross-link callbacks (single source of truth = WorkbenchV3 state):
 *   onAtomFocus(idx | null)    — flash atom in 2D builder
 *   onResidueFocus(pos | null) — flash residue in 3D theater
 *   onVulnerableChange(idx[])  — orange halos on 2D for ALL vuln atoms
 */
import { useEffect, useState, Fragment, useMemo } from "react";
import type React from "react";
import { Shield, RefreshCw, AlertTriangle, Wrench, Layers, Map as MapIcon, Sparkles, ChevronDown } from "lucide-react";
import { Mol2DThumb } from "./Mol2DThumb";

interface TopMutation {
  position: number;
  wt: string;
  mutant: string;
  drug_class: string;
  frequency: string;
  note: string;
  distance_a: number;
  residue_name: string;
}

interface VulnerableAtom {
  atom_idx: number;
  escape_score: number;
  top_mutation: TopMutation;
}

interface ClinicalOverlap {
  position: number;
  wt: string;
  mutant: string;
  drug_class: string;
  frequency: string;
  score: number;
  ligand_atom_idx: number;
  ligand_element: string;
  distance_a: number;
  residue_name: string;
  note: string;
}

interface ContactResidueDetail {
  position: number;
  residue_name: string;
  residue_chain: string;
  wt: string;
  ligand_atom_idx: number;
  ligand_element: string;
  distance_a: number;
  contact_strength: number;
  n_known_mutations: number;
  known_mutations: {
    wt: string; mutant: string; drug_class: string;
    frequency: string; freq_score: number; note: string;
    escape_score: number;
  }[];
}

interface DrugClassProfile {
  drug_class: string;
  n_total: number;
  n_threatening: number;
  n_contacted: number;
  max_escape: number;
  robustness: number;
}

interface ResistanceResult {
  pdb_id: string;
  smiles: string;
  target_name: string;
  pathogen: string;
  robustness_score: number;
  n_escape_vectors: number;
  vulnerable_atoms: VulnerableAtom[];
  clinical_overlap: ClinicalOverlap[];
  all_residue_scores: Record<number, {
    wt: string;
    mutations: Record<string, number>;
    /** Per-mutation factor breakdown — backend's chemistry-aware
     *  composition of the escape score. Renders inside per-mutation
     *  tooltips so users see WHY a score is what it is. */
    _factors?: Record<string, {
      freq: number; dist: number; chem: number; cons: number; grantham: number;
    }>;
  }>;
  contact_residue_details?: ContactResidueDetail[];
  drug_class_profile?: DrugClassProfile[];
  n_total_known_mutations: number;
  n_residues_with_contacts: number;
  summary: string;
}

interface Suggestion {
  swap: string;
  rationale: string;
  source: "playbook" | "gemini";
  confidence: number;
  rank: number;
  /** Per-suggestion calculative breakdown — bucket match, Grantham
   *  factor, contact distance, atom valence feasibility. Renders in
   *  the suggestion tooltip so the user sees the math. */
  _factors?: {
    bucket_match: number;
    chem_inverse: number;
    bond_proximity: number;
    atom_feasible: number;
    rank_decay: number;
    grantham: number;
  };
}

interface HardenResult {
  pdb_id: string;
  smiles: string;
  atom_idx: number;
  target_atom: VulnerableAtom;
  bucket: string;
  suggestions: Suggestion[];
  /** AI-bespoke suggestions from Gemini Pro — candidate-specific. */
  gemini_suggestions?: Suggestion[];
  /** Curated medchem playbook suggestions — class-tier heuristics. */
  playbook_suggestions?: Suggestion[];
  /** Status of the optional Gemini AI tier. "ok" | "no_api_key" |
   *  "call_failed" | "skipped". Surfaced in UI so user knows WHY
   *  no AI suggestion appears (or that one is included). */
  llm_status?: string;
  compute_inputs?: {
    bucket?: string;
    atom_environment?: string;
    bucket_match?: number;
    chem_disrupt?: number;
    chem_inverse?: number;
    bond_proximity?: number;
    atom_feasible?: number;
    grantham: number;
    wt?: string; mutant?: string; drug_class?: string; frequency?: string;
    current_robustness?: number;
  };
}

interface CompareRow {
  label: string;
  smiles: string;
  valid: boolean;
  error?: string;
  robustness_score?: number;
  n_escape_vectors?: number;
  n_residues_with_contacts?: number;
  n_clinical_overlaps?: number;
  top_vulnerable_atom?: VulnerableAtom | null;
  summary?: string;
}

interface CompareResult {
  pdb_id: string;
  rows: CompareRow[];
  n: number;
  n_valid: number;
  common_weak_residues: { position: number; n_candidates: number; fraction: number }[];
  best_idx: number | null;
}

interface SessionCandidate {
  id: string;
  smiles: string;
  created_by: string;
  composite: number | null;
}

interface Props {
  apiBase: string;
  smiles: string | null;
  pdbId: string | null;
  sessionId?: string | null;
  /** Bubble vulnerable-atom indices upward so 2D builder can paint halos. */
  onVulnerableChange?: (atomIdxs: number[]) => void;
  /** Cross-link: flash one atom in 2D when user clicks heatmap cell / row. */
  onAtomFocus?: (atomIdx: number | null) => void;
  /** Cross-link: flash one residue in 3D when user clicks heatmap cell / row. */
  onResidueFocus?: (resid: number | null) => void;
  /** Send a slash command to the agent thread (e.g., "/harden …"). */
  onAgentMessage?: (message: string) => void;
  /** DIRECT cross-link: load a SMILES into the 2D builder + 3D theater
   *  + auto-score (no chat round-trip). Used by the Apply button on
   *  harden suggestions so the molecule actually changes on screen. */
  onLoadSmiles?: (smi: string, label?: string) => void;
}

const AA_ROW_ORDER = ["A", "T", "V", "I", "L", "M", "F", "Y", "W", "S", "R", "K", "Q", "N", "D", "E", "H", "C", "G", "P"];

// Lavender-glass design tokens — must match Mol3D / 2D builder chips.
const LAV = {
  bg: "rgba(174, 158, 244, 0.06)",
  bgStrong: "rgba(174, 158, 244, 0.12)",
  border: "rgba(174, 158, 244, 0.28)",
  borderStrong: "rgba(174, 158, 244, 0.42)",
  fg: "#7c63d8",
  fgDeep: "#6041d0",
} as const;

const RED = {
  bg: "rgba(220,38,38,0.08)",
  border: "rgba(220,38,38,0.32)",
  fg: "#dc2626",
} as const;

const AMBER = {
  bg: "rgba(202,138,4,0.10)",
  border: "rgba(202,138,4,0.34)",
  fg: "#ca8a04",
} as const;

const GREEN = {
  bg: "rgba(16,185,129,0.10)",
  border: "rgba(16,185,129,0.34)",
  fg: "#10b981",
} as const;


// ─────────────────────────────────────────────────────────────────────
// MAIN
// ─────────────────────────────────────────────────────────────────────

export function ResistanceEscapeMapCard({
  apiBase, smiles, pdbId, sessionId,
  onVulnerableChange, onAtomFocus, onResidueFocus, onAgentMessage, onLoadSmiles,
}: Props) {
  const [data, setData] = useState<ResistanceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hoverCell, setHoverCell] = useState<{ pos: number; aa: string; score: number } | null>(null);

  // Mode + collapsibles
  const [mode, setMode] = useState<"map" | "harden" | "compare">("map");
  const [headerOpen, setHeaderOpen] = useState(true);

  // Pinned cell (sticky cross-link)
  const [pinnedCell, setPinnedCell] = useState<{ pos: number; atom_idx: number | null } | null>(null);

  // Harden mode state
  const [hardenAtomIdx, setHardenAtomIdx] = useState<number | null>(null);
  const [hardenResult, setHardenResult] = useState<HardenResult | null>(null);
  const [hardenLoading, setHardenLoading] = useState(false);
  const [hardenError, setHardenError] = useState<string>("");

  // Compare mode state
  const [sessionCandidates, setSessionCandidates] = useState<SessionCandidate[]>([]);
  const [comparePicks, setComparePicks] = useState<string[]>([]);
  const [compareResult, setCompareResult] = useState<CompareResult | null>(null);
  const [compareLoading, setCompareLoading] = useState(false);

  // ── Fetch resistance prediction
  useEffect(() => {
    if (!smiles || !pdbId) {
      setData(null);
      onVulnerableChange?.([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError("");
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/chem/resistance/predict`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ smiles, pdb_id: pdbId }),
        });
        if (!r.ok) {
          const txt = await r.text();
          if (!cancelled) {
            setError(txt.slice(0, 200));
            setData(null);
            onVulnerableChange?.([]);
          }
          return;
        }
        const d: ResistanceResult = await r.json();
        if (cancelled) return;
        setData(d);
        onVulnerableChange?.(d.vulnerable_atoms.map((v) => v.atom_idx));
      } catch (e: any) {
        if (!cancelled) {
          setError(String(e?.message ?? e));
          setData(null);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }, 350);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [smiles, pdbId, apiBase]);

  // ── Fetch session candidates when entering compare mode
  useEffect(() => {
    if (mode !== "compare" || !sessionId) return;
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/chem/session/${encodeURIComponent(sessionId)}/candidates`);
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setSessionCandidates(d.candidates || []);
      } catch {/*noop*/}
    })();
    return () => { cancelled = true; };
  }, [mode, sessionId, apiBase]);

  // ── Trigger harden when atom changes
  useEffect(() => {
    if (mode !== "harden" || !smiles || !pdbId || hardenAtomIdx == null) {
      setHardenResult(null);
      setHardenError("");
      return;
    }
    let cancelled = false;
    setHardenLoading(true);
    setHardenError("");
    setHardenResult(null);
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/chem/resistance/harden`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ smiles, pdb_id: pdbId, atom_idx: hardenAtomIdx, use_llm: true }),
        });
        if (!r.ok) {
          const txt = await r.text();
          if (!cancelled) setHardenError(`HTTP ${r.status} · ${txt.slice(0, 240)}`);
          return;
        }
        const d: HardenResult = await r.json();
        if (!cancelled) setHardenResult(d);
      } catch (e: any) {
        if (!cancelled) setHardenError(`network error · ${String(e?.message ?? e).slice(0, 240)}`);
      }
      finally { if (!cancelled) setHardenLoading(false); }
    })();
    return () => { cancelled = true; };
  }, [mode, smiles, pdbId, hardenAtomIdx, apiBase]);

  // ── Robustness color tier
  const rs = data?.robustness_score ?? 0;
  const rsTier = rs >= 0.7 ? "robust" : rs >= 0.4 ? "moderate" : "vulnerable";
  const rc = rsTier === "robust" ? GREEN : rsTier === "moderate" ? AMBER : RED;

  // ── Heatmap data
  const positions = data ? Object.keys(data.all_residue_scores).map(Number).sort((a, b) => a - b) : [];

  // Sequential YlOrRd escape scale (ColorBrewer) — vivid + perceptually
  // ordered, full opacity, so even low-but-real escape reads clearly and
  // high escape is unmistakably hot. Replaces the old faint low-alpha amber
  // that made the heatmap look empty.
  const scoreColor = (s: number): string => {
    if (s <= 0) return "transparent";
    const stops: [number, [number, number, number]][] = [
      [0.0, [255, 247, 188]], [0.2, [254, 217, 118]], [0.4, [254, 178, 76]],
      [0.6, [253, 141, 60]], [0.8, [240, 59, 32]], [1.0, [189, 0, 38]],
    ];
    const t = Math.max(0, Math.min(1, s));
    let lo = stops[0], hi = stops[stops.length - 1];
    for (let i = 0; i < stops.length - 1; i++) {
      if (t >= stops[i][0] && t <= stops[i + 1][0]) { lo = stops[i]; hi = stops[i + 1]; break; }
    }
    const span = hi[0] - lo[0] || 1;
    const f = (t - lo[0]) / span;
    const r = Math.round(lo[1][0] + f * (hi[1][0] - lo[1][0]));
    const g = Math.round(lo[1][1] + f * (hi[1][1] - lo[1][1]));
    const b = Math.round(lo[1][2] + f * (hi[1][2] - lo[1][2]));
    return `rgb(${r},${g},${b})`;
  };

  const clinicalCells = useMemo(
    () => new Set(data ? data.clinical_overlap.map((c) => `${c.position}_${c.mutant}`) : []),
    [data]
  );

  // Cell click → cross-link AND set pinned
  const handleCellClick = (pos: number, score: number, isClinical: boolean) => {
    if (score <= 0 && !isClinical) return;
    const cm = data?.clinical_overlap.find((c) => c.position === pos);
    const atomIdx = cm?.ligand_atom_idx ?? null;
    setPinnedCell({ pos, atom_idx: atomIdx });
    onResidueFocus?.(pos);
    if (atomIdx != null) onAtomFocus?.(atomIdx);
  };

  // Vulnerable-atom row click
  const handleVulnRowClick = (v: VulnerableAtom) => {
    onAtomFocus?.(v.atom_idx);
    onResidueFocus?.(v.top_mutation.position);
    setPinnedCell({ pos: v.top_mutation.position, atom_idx: v.atom_idx });
  };

  // Compare action
  const togglePick = (id: string) => {
    setComparePicks((cur) => {
      if (cur.includes(id)) return cur.filter((x) => x !== id);
      if (cur.length >= 5) return cur;
      return [...cur, id];
    });
  };

  const runCompare = async () => {
    if (!pdbId || comparePicks.length < 2) return;
    const picked = sessionCandidates.filter((c) => comparePicks.includes(c.id));
    setCompareLoading(true);
    setCompareResult(null);
    try {
      const r = await fetch(`${apiBase}/workbench/chem/resistance/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          smiles_list: picked.map((p) => p.smiles),
          pdb_id: pdbId,
          labels: picked.map((p) => `${p.created_by} · ${p.id.slice(0, 6)}`),
        }),
      });
      if (!r.ok) return;
      const d: CompareResult = await r.json();
      setCompareResult(d);
    } finally { setCompareLoading(false); }
  };

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "linear-gradient(180deg, rgba(248,247,255,1) 0%, rgba(243,241,253,1) 100%)",
      overflow: "hidden",
      fontFamily: "var(--lys-font-body)",
    }}>
      {/* ── Header — click to collapse */}
      <div
        onClick={() => setHeaderOpen((o) => !o)}
        style={{
          padding: "6px 10px",
          fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)", letterSpacing: "0.06em",
          textTransform: "uppercase",
          borderBottom: "1px solid rgba(0,0,0,0.04)",
          display: "flex", alignItems: "center", gap: 6,
          cursor: "pointer", userSelect: "none",
          background: LAV.bg,
          backdropFilter: "blur(10px)",
        }}>
        <Shield size={11} style={{ color: LAV.fg }} />
        <span>resistance escape map</span>
        {data && (
          <>
            <Pill {...rc} text={`${rsTier} · ${rs.toFixed(2)}`} bold />
            {data.n_escape_vectors > 0 && (
              <Pill {...RED} text={`${data.n_escape_vectors} escape`} bold />
            )}
            {data.vulnerable_atoms.length === 0 && data.n_residues_with_contacts > 0 && (
              <Pill {...GREEN} text="hardened" />
            )}
          </>
        )}
        <span style={{ flex: 1 }} />
        {loading && <RefreshCw size={11} style={{ animation: "spin 1s linear infinite", color: LAV.fg }} />}
        <ChevronDown size={11} style={{
          color: "var(--lys-text-faint)",
          transform: headerOpen ? "rotate(0deg)" : "rotate(-90deg)",
          transition: "transform 150ms",
        }} />
      </div>

      {!headerOpen ? null : (
        <>
          {/* ── Mode tabs + actions */}
          <div style={{
            padding: "4px 8px", display: "flex", gap: 4, alignItems: "center",
            borderBottom: "1px solid rgba(0,0,0,0.04)",
            background: "rgba(255,255,255,0.4)",
          }}>
            <ModeTab active={mode === "map"} onClick={() => setMode("map")} icon={<MapIcon size={10} />} label="map" />
            <ModeTab active={mode === "harden"} onClick={() => setMode("harden")} icon={<Wrench size={10} />} label="harden" />
            <ModeTab active={mode === "compare"} onClick={() => setMode("compare")} icon={<Layers size={10} />} label="compare" />
            <span style={{ flex: 1 }} />
            {data && onAgentMessage && (
              <ChipBtn
                onClick={() => onAgentMessage(`/harden ${smiles} pdb=${pdbId}`)}
                icon={<Sparkles size={10} />}
                label="ask agent"
              />
            )}
          </div>

          {/* ── Body */}
          <div style={{ flex: 1, overflow: "auto", padding: 8 }}>
            {!smiles && <Empty msg="Pick a candidate to see resistance vulnerability" />}
            {smiles && !pdbId && <Empty msg="Pick a target in the 3D theater to map resistance" />}
            {error && (
              <div style={{ padding: 10, color: RED.fg, fontSize: 10, fontFamily: "var(--lys-font-mono)" }}>
                error: {error}
              </div>
            )}
            {data && mode === "map" && (
              <MapMode
                data={data}
                apiBase={apiBase}
                smiles={smiles}
                positions={positions}
                aas={AA_ROW_ORDER}
                hoverCell={hoverCell}
                setHoverCell={setHoverCell}
                pinnedCell={pinnedCell}
                clinicalCells={clinicalCells}
                scoreColor={scoreColor}
                onCellClick={handleCellClick}
                onVulnRowClick={handleVulnRowClick}
                onHardenAtom={(idx) => { setMode("harden"); setHardenAtomIdx(idx); }}
                onAtomFocus={onAtomFocus}
                onResidueFocus={onResidueFocus}
              />
            )}
            {data && mode === "harden" && (
              <HardenMode
                data={data}
                hardenAtomIdx={hardenAtomIdx}
                setHardenAtomIdx={(idx) => { setHardenAtomIdx(idx); onAtomFocus?.(idx); }}
                hardenResult={hardenResult}
                hardenLoading={hardenLoading}
                hardenError={hardenError}
                onAgentMessage={onAgentMessage}
                onResidueFocus={onResidueFocus}
                onLoadSmiles={onLoadSmiles}
              />
            )}
            {data && mode === "compare" && (
              <CompareMode
                pdbId={pdbId}
                sessionCandidates={sessionCandidates}
                comparePicks={comparePicks}
                togglePick={togglePick}
                runCompare={runCompare}
                compareResult={compareResult}
                compareLoading={compareLoading}
                onResidueFocus={onResidueFocus}
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}


// ─────────────────────────────────────────────────────────────────────
// MAP MODE
// ─────────────────────────────────────────────────────────────────────

// Drug-class color palette — matches BioLuminate / Cresset conventions
const DRUG_CLASS_COLOR: Record<string, string> = {
  "β-lactam": "#0891b2",
  "beta-lactam": "#0891b2",
  "fluoroquinolone": "#dc2626",
  "macrolide": "#a855f7",
  "aminoglycoside": "#f59e0b",
  "tetracycline": "#10b981",
  "glycopeptide": "#6366f1",
  "rifamycin": "#ea580c",
  "oxazolidinone": "#ec4899",
  "lincosamide": "#14b8a6",
  "polymyxin": "#84cc16",
  "fosfomycin": "#3b82f6",
  "sulfonamide": "#8b5cf6",
  "trimethoprim": "#06b6d4",
  "default": "#6b7280",
};

function classColor(cls: string): string {
  const k = (cls || "").toLowerCase();
  for (const [key, col] of Object.entries(DRUG_CLASS_COLOR)) {
    if (k.includes(key)) return col;
  }
  return DRUG_CLASS_COLOR.default;
}

function MapMode({
  data, positions, aas, hoverCell, setHoverCell, pinnedCell,
  clinicalCells, scoreColor, onCellClick, onVulnRowClick, onHardenAtom,
  onAtomFocus, onResidueFocus, apiBase, smiles,
}: {
  data: ResistanceResult;
  apiBase: string;
  smiles: string | null;
  positions: number[];
  aas: string[];
  hoverCell: { pos: number; aa: string; score: number } | null;
  setHoverCell: (c: { pos: number; aa: string; score: number } | null) => void;
  pinnedCell: { pos: number; atom_idx: number | null } | null;
  clinicalCells: Set<string>;
  scoreColor: (s: number) => string;
  onCellClick: (pos: number, score: number, isClinical: boolean) => void;
  onVulnRowClick: (v: VulnerableAtom) => void;
  onHardenAtom: (idx: number) => void;
  onAtomFocus?: (atomIdx: number | null) => void;
  onResidueFocus?: (resid: number | null) => void;
}) {
  // ── Derive missing fields client-side as a fallback. Backends that
  //    haven't picked up the contact_residue_details / drug_class_profile
  //    additions still serve the legacy clinical_overlap[] + vulnerable_atoms[]
  //    fields, which carry enough information to reconstruct both. We
  //    prefer the backend's authoritative fields when present.
  const contactResidueDetails: ContactResidueDetail[] = useMemo<ContactResidueDetail[]>(() => {
    if (data.contact_residue_details && data.contact_residue_details.length > 0) {
      return data.contact_residue_details;
    }
    // Group clinical_overlap + vulnerable_atom data by position
    const byPos: Map<number, ContactResidueDetail> = new Map();
    const allKnown: ClinicalOverlap[] = [];
    for (const co of (data.clinical_overlap ?? [])) allKnown.push(co);
    // Also include any vulnerable atoms whose mutation isn't in clinical_overlap
    for (const v of (data.vulnerable_atoms ?? [])) {
      const m = v.top_mutation;
      const present = allKnown.find((c) => c.position === m.position && c.mutant === m.mutant);
      if (!present) {
        allKnown.push({
          position: m.position, wt: m.wt, mutant: m.mutant,
          drug_class: m.drug_class, frequency: m.frequency,
          score: v.escape_score,
          ligand_atom_idx: v.atom_idx, ligand_element: "?",
          distance_a: m.distance_a, residue_name: m.residue_name,
          note: m.note,
        });
      }
    }
    for (const c of allKnown) {
      if (!byPos.has(c.position)) {
        const d = c.distance_a;
        const cs = d <= 2.5 ? 1.0 : d >= 4.0 ? 0.0 : 1.0 - ((d - 2.5) / 1.5);
        byPos.set(c.position, {
          position: c.position,
          residue_name: c.residue_name,
          residue_chain: "A",
          wt: c.wt,
          ligand_atom_idx: c.ligand_atom_idx,
          ligand_element: c.ligand_element,
          distance_a: c.distance_a,
          contact_strength: cs,
          n_known_mutations: 0,
          known_mutations: [],
        });
      }
      const acc = byPos.get(c.position)!;
      acc.known_mutations.push({
        wt: c.wt, mutant: c.mutant,
        drug_class: c.drug_class, frequency: c.frequency,
        freq_score: c.score / Math.max(0.001, Math.min(1, c.score / 0.5)),
        note: c.note,
        escape_score: c.score,
      });
      acc.n_known_mutations = acc.known_mutations.length;
    }
    return Array.from(byPos.values()).sort((a, b) => a.position - b.position);
  }, [data.contact_residue_details, data.clinical_overlap, data.vulnerable_atoms]);

  // Map position → contact_strength (used by the heatmap).
  const contactStrength: Record<number, number> = {};
  for (const cd of contactResidueDetails) {
    contactStrength[cd.position] = cd.contact_strength;
  }

  // Drug-class profile — backend-authoritative or derived from
  // contactResidueDetails (group by drug_class, compute robustness).
  const classProfile: DrugClassProfile[] = useMemo(() => {
    if (data.drug_class_profile && data.drug_class_profile.length > 0) {
      return data.drug_class_profile;
    }
    const byClass = new Map<string, DrugClassProfile>();
    for (const cd of contactResidueDetails) {
      for (const m of cd.known_mutations) {
        const cls = m.drug_class || "unknown";
        if (!byClass.has(cls)) {
          byClass.set(cls, {
            drug_class: cls, n_total: 0, n_threatening: 0,
            n_contacted: 0, max_escape: 0, robustness: 1,
          });
        }
        const row = byClass.get(cls)!;
        row.n_total += 1;
        row.n_contacted += 1;
        if (m.escape_score > 0) {
          row.n_threatening += 1;
          if (m.escape_score > row.max_escape) row.max_escape = m.escape_score;
        }
      }
    }
    return Array.from(byClass.values())
      .map((r) => ({ ...r, robustness: Math.round((1 - r.max_escape) * 1000) / 1000 }))
      .sort((a, b) => b.max_escape - a.max_escape);
  }, [data.drug_class_profile, contactResidueDetails]);

  // (focusedResidueDetail panel was folded into per-contact cards.)

  // KPI strip values (computed once, cheap)
  const rs = data.robustness_score;
  const rsTier = rs >= 0.7 ? GREEN : rs >= 0.4 ? AMBER : RED;
  const rsLabel = rs >= 0.7 ? "robust" : rs >= 0.4 ? "moderate" : "vulnerable";
  const nClasses = classProfile.length;
  const nClassesAtRisk = classProfile.filter((c) => c.max_escape > 0).length;
  const distMin = contactResidueDetails.reduce((m, c) =>
    Math.min(m, c.distance_a), 99);
  const distMax = contactResidueDetails.reduce((m, c) =>
    Math.max(m, c.distance_a), 0);

  // Protein-ladder range — show ±20aa around the curated mutation span.
  const allPos = positions.length > 0 ? positions : [0];
  const ladderMin = Math.max(1, Math.min(...allPos) - 20);
  const ladderMax = Math.max(...allPos) + 20;
  const ladderSpan = ladderMax - ladderMin || 1;
  const ladderX = (p: number) => ((p - ladderMin) / ladderSpan) * 100;
  const contactPositions = new Set(contactResidueDetails.map((c) => c.position));

  return (
    <>
      {/* ── KPI STRIP — 4 big metric cards. Industry-grade at-a-glance
              dashboard: Robustness · Escape Vectors · Contacts · Classes. ── */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
        gap: 5, marginBottom: 10,
      }}>
        <KPICard
          label="Robustness"
          value={rs.toFixed(2)}
          unit="/ 1.00"
          sub={rsLabel}
          tier={rsTier}
          gauge={rs}
        />
        <KPICard
          label="Escape vectors"
          value={String(data.n_escape_vectors)}
          unit={`of ${data.vulnerable_atoms.length}`}
          sub={data.n_escape_vectors > 0 ? "above 0.30" : "all sub-threshold"}
          tier={data.n_escape_vectors > 0 ? RED : GREEN}
        />
        <KPICard
          label="Contacts"
          value={String(data.n_residues_with_contacts)}
          unit="residues"
          sub={distMin < 99 ? `${distMin.toFixed(1)}–${distMax.toFixed(1)}Å` : "—"}
          tier={data.n_residues_with_contacts > 0 ? LAV : AMBER}
        />
        <KPICard
          label="Drug classes"
          value={`${nClasses - nClassesAtRisk}/${nClasses}`}
          unit="covered"
          sub={nClassesAtRisk === 0 ? "fully resilient" : `${nClassesAtRisk} at risk`}
          tier={nClassesAtRisk === 0 ? GREEN : nClassesAtRisk <= 1 ? AMBER : RED}
        />
      </div>

      {/* ── PROTEIN LADDER — 1D residue track. Industry-standard for
              showing where contacts AND clinical mutations sit relative
              to the full target protein. Click any tick to focus that
              residue across 3D + heatmap. ── */}
      {contactResidueDetails.length > 0 && (
        <div style={{
          padding: "6px 10px", marginBottom: 10,
          background: LAV.bg, border: `1px solid ${LAV.border}`,
          borderRadius: 4, backdropFilter: "blur(10px)",
        }}>
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            marginBottom: 4,
          }}>
            <span style={{
              fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
              color: LAV.fgDeep, fontWeight: 700,
              letterSpacing: "0.06em", textTransform: "uppercase",
            }}>{data.target_name} · residue ladder</span>
            <span style={{ flex: 1 }} />
            <span style={{
              fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-faint)",
            }}>res {ladderMin}–{ladderMax}</span>
          </div>
          <div style={{
            position: "relative", height: 28,
            background: "rgba(124,99,216,0.06)",
            borderRadius: 3,
          }}>
            {/* Spine — horizontal line through the middle */}
            <div style={{
              position: "absolute", top: "50%", left: 0, right: 0,
              height: 2, background: LAV.border, transform: "translateY(-50%)",
            }} />
            {/* Tick marks every 50 residues */}
            {Array.from({ length: Math.floor(ladderSpan / 50) + 1 }, (_, i) => {
              const pos = Math.ceil(ladderMin / 50) * 50 + i * 50;
              if (pos > ladderMax) return null;
              return (
                <div key={`tick-${pos}`} style={{
                  position: "absolute", top: 0, height: "100%",
                  left: `${ladderX(pos)}%`,
                  borderLeft: "1px dashed rgba(124,99,216,0.20)",
                }}>
                  <div style={{
                    position: "absolute", bottom: -10, left: -8,
                    fontSize: 7.5, color: "var(--lys-text-faint)",
                    fontFamily: "var(--lys-font-mono)",
                  }}>{pos}</div>
                </div>
              );
            })}
            {/* Position markers — every curated mutation position */}
            {positions.map((p) => {
              const cd = contactResidueDetails.find((c) => c.position === p);
              const isContact = contactPositions.has(p);
              const muts = data.all_residue_scores[p]?.mutations || {};
              const maxScore = Math.max(0, ...Object.values(muts));
              const tier = maxScore >= 0.5 ? RED : maxScore >= 0.3 ? AMBER : maxScore > 0 ? AMBER : isContact ? LAV : { fg: "rgba(124,99,216,0.45)" };
              const isPinned = pinnedCell?.pos === p;
              const x = ladderX(p);
              return (
                <button key={`mark-${p}`}
                  onClick={() => onResidueFocus?.(p)}
                  title={`${data.all_residue_scores[p]?.wt || ""}${p}${cd ? ` · contact ${cd.distance_a}Å` : ""}${maxScore > 0 ? ` · max escape ${maxScore.toFixed(2)}` : ""}`}
                  style={{
                    position: "absolute", left: `calc(${x}% - 5px)`,
                    top: "50%", transform: "translateY(-50%)",
                    width: 10, height: 10, borderRadius: 999,
                    background: tier.fg,
                    border: isPinned ? `2px solid ${LAV.fgDeep}` : isContact ? "1.5px solid white" : "1px solid white",
                    boxShadow: isContact ? "0 1px 3px rgba(15,23,42,0.20)" : "none",
                    cursor: "pointer", padding: 0,
                    zIndex: isPinned ? 3 : isContact ? 2 : 1,
                  }} />
              );
            })}
          </div>
          <div style={{
            display: "flex", gap: 8, marginTop: 10,
            fontSize: 8, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
          }}>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: LAV.fg, border: "1.5px solid white" }} />
              contact
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: RED.fg }} />
              high escape
            </span>
            <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
              <span style={{ width: 8, height: 8, borderRadius: 999, background: AMBER.fg }} />
              moderate
            </span>
            <span style={{ flex: 1 }} />
            <span style={{ opacity: 0.7 }}>click marker to focus</span>
          </div>
        </div>
      )}

      {/* ── Summary capsule ── */}
      <div style={{
        padding: "6px 10px", marginBottom: 8,
        fontSize: 10, color: "var(--lys-text-dim)",
        background: LAV.bg,
        border: `1px solid ${LAV.border}`,
        borderRadius: 4, lineHeight: 1.4,
        backdropFilter: "blur(10px)",
      }}>
        <span style={{ fontWeight: 700, color: LAV.fgDeep }}>{data.target_name}</span>
        {" · "}
        {data.summary}
      </div>

      {/* ── PER-CONTACT VULNERABILITY DASHBOARD — the primary view.
          One full-width card per contact residue, with inline mutation
          impact bars sorted by escape score. Replaces the sparse-grid
          heatmap that was 95% empty cells. ── */}
      {contactResidueDetails.length > 0 && (
        <>
          <SectionLabel text={`Contact-by-contact risk · ${contactResidueDetails.length} site${contactResidueDetails.length === 1 ? "" : "s"}`} />
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 12 }}>
            {contactResidueDetails.map((cd) => {
              const isPinned = pinnedCell?.pos === cd.position;
              const muts = (cd.known_mutations || []).slice().sort((a, b) => b.escape_score - a.escape_score);
              const maxEsc = muts.length > 0 ? Math.max(...muts.map((m) => m.escape_score)) : 0;
              const tier = maxEsc >= 0.5 ? RED : maxEsc >= 0.3 ? AMBER : maxEsc > 0 ? AMBER : GREEN;
              const distTier = cd.distance_a < 3 ? GREEN : cd.distance_a < 4 ? AMBER : RED;
              return (
                <div key={cd.position}
                  onClick={() => {
                    if (cd.ligand_atom_idx != null) onAtomFocus?.(cd.ligand_atom_idx);
                    onResidueFocus?.(cd.position);
                  }}
                  style={{
                    padding: "8px 10px",
                    background: isPinned ? LAV.bgStrong : "rgba(255,255,255,0.45)",
                    border: `1px solid ${isPinned ? LAV.borderStrong : LAV.border}`,
                    borderLeft: `3px solid ${tier.fg}`,
                    borderRadius: 5,
                    display: "flex", flexDirection: "column", gap: 6,
                    cursor: "pointer",
                    backdropFilter: "blur(10px)",
                  }}>
                  {/* Card header — residue badge + atom + distance + mut count */}
                  <div style={{
                    display: "flex", alignItems: "center", gap: 6,
                    fontSize: 10, fontFamily: "var(--lys-font-body)",
                  }}>
                    <span style={{
                      fontFamily: "var(--lys-font-mono)", fontWeight: 800,
                      fontSize: 13, color: LAV.fgDeep,
                    }}>{cd.wt || ""}{cd.position}</span>
                    <span style={{
                      fontFamily: "var(--lys-font-mono)",
                      fontSize: 9, color: "var(--lys-text-faint)",
                    }}>{cd.residue_name}</span>
                    <span style={{ flex: 1 }} />
                    <span style={{
                      padding: "1px 6px", borderRadius: 3,
                      background: "rgba(0,0,0,0.04)",
                      fontFamily: "var(--lys-font-mono)", fontSize: 9,
                    }}>
                      <span style={{ color: "var(--lys-text-faint)" }}>atom </span>
                      <span style={{ fontWeight: 700, color: "#374151" }}>{cd.ligand_atom_idx}</span>
                      <span style={{ color: "var(--lys-text-faint)" }}> · {cd.ligand_element}</span>
                    </span>
                    <Pill {...distTier} text={`${cd.distance_a}Å`} bold />
                    {muts.length > 0 ? (
                      <Pill {...tier} text={`${muts.length} mut`} bold />
                    ) : (
                      <Pill {...GREEN} text="✓ safe" bold />
                    )}
                  </div>
                  {/* Mutation impact bars — sorted by escape score desc */}
                  {muts.length > 0 ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                      {muts.map((m, i) => {
                        const col = classColor(m.drug_class);
                        const escTier = m.escape_score >= 0.5 ? RED : m.escape_score >= 0.3 ? AMBER : m.escape_score > 0 ? AMBER : GREEN;
                        const pct = Math.max(2, Math.round(m.escape_score * 100));
                        // Pull backend's chemistry-aware factor breakdown
                        // (freq × dist × chem × cons) so the tooltip
                        // reveals WHY the score is what it is. Avoids
                        // black-box numbers — every multiplier is shown.
                        const factors = data.all_residue_scores[cd.position]?._factors?.[m.mutant];
                        const factorLine = factors ? (
                          `\n\nscore = freq(${factors.freq.toFixed(2)})` +
                          ` × dist(${factors.dist.toFixed(2)})` +
                          ` × chem(${factors.chem.toFixed(2)})` +
                          ` × cons(${factors.cons.toFixed(2)})` +
                          `\nGrantham(${m.wt}→${m.mutant}) = ${factors.grantham}` +
                          (factors.grantham < 30 ? " (conservative swap)"
                            : factors.grantham < 80 ? " (moderate change)"
                            : " (disruptive change)")
                        ) : "";
                        return (
                          <div key={i}
                            title={`${m.wt}${cd.position}${m.mutant} · ${m.drug_class} · freq ${m.frequency}\n${m.note.slice(0, 200)}${factorLine}`}
                            style={{
                              display: "grid",
                              gridTemplateColumns: "60px 1fr 38px auto",
                              gap: 6, alignItems: "center",
                              fontSize: 9.5, fontFamily: "var(--lys-font-body)",
                            }}>
                            <span style={{
                              padding: "1px 5px", borderRadius: 3,
                              background: `${col}20`, color: col, fontWeight: 700,
                              fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
                              textAlign: "center",
                            }}>{m.wt}{cd.position}{m.mutant}</span>
                            <div style={{
                              display: "flex", alignItems: "center", gap: 4,
                              minWidth: 0,
                            }}>
                              <div style={{
                                flex: 1, height: 7, borderRadius: 4,
                                background: "rgba(0,0,0,0.05)", overflow: "hidden",
                              }}>
                                <div style={{
                                  width: `${pct}%`, height: "100%",
                                  background: escTier.fg, opacity: 0.85,
                                }} />
                              </div>
                              <span style={{
                                fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                                color: "var(--lys-text-faint)", flexShrink: 0,
                                minWidth: 0, overflow: "hidden",
                                textOverflow: "ellipsis", whiteSpace: "nowrap",
                                maxWidth: 130,
                              }}>{m.drug_class} · {m.frequency}</span>
                            </div>
                            <span style={{
                              fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                              fontSize: 9.5, color: escTier.fg,
                              textAlign: "right",
                            }}>{m.escape_score.toFixed(2)}</span>
                            {m.escape_score > 0 ? (
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  if (cd.ligand_atom_idx != null) onHardenAtom(cd.ligand_atom_idx);
                                }}
                                style={{
                                  padding: "1px 6px", height: 18,
                                  fontSize: 8.5, fontWeight: 600,
                                  fontFamily: "var(--lys-font-body)",
                                  background: LAV.bgStrong, border: `1px solid ${LAV.border}`,
                                  borderRadius: 3, color: LAV.fgDeep, cursor: "pointer",
                                }}>harden →</button>
                            ) : <span />}
                          </div>
                        );
                      })}
                    </div>
                  ) : (
                    <div style={{
                      fontSize: 9.5, color: GREEN.fg,
                      fontFamily: "var(--lys-font-body)",
                      display: "inline-flex", alignItems: "center", gap: 4,
                    }}>
                      <Shield size={10} />
                      No clinical mutation curated at this position — safe contact.
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </>
      )}

      {/* ── DRUG-CLASS COVERAGE — full-width donut + per-class bars ── */}
      {classProfile.length > 0 && (
        <>
          <SectionLabel text={`Drug-class coverage · ${classProfile.length} class${classProfile.length === 1 ? "" : "es"}`} />
          <div style={{
            display: "grid", gridTemplateColumns: "auto 1fr",
            gap: 12, alignItems: "center",
            padding: "8px 10px",
            background: "rgba(255,255,255,0.45)",
            border: `1px solid ${LAV.border}`,
            borderRadius: 5, marginBottom: 12,
            backdropFilter: "blur(10px)",
          }}>
            {/* SVG donut chart — segments are class robustness % weighted equally */}
            <CoverageDonut classes={classProfile} />

            {/* Per-class horizontal bars + stats */}
            <div style={{ display: "flex", flexDirection: "column", gap: 4, minWidth: 0 }}>
              {classProfile.map((c) => {
                const col = classColor(c.drug_class);
                const robPct = Math.round(c.robustness * 100);
                const tier = c.robustness >= 0.7 ? GREEN : c.robustness >= 0.4 ? AMBER : RED;
                return (
                  <div key={c.drug_class}
                    title={`${c.drug_class} · ${c.n_total} curated mutation${c.n_total === 1 ? "" : "s"}, ${c.n_contacted} at contact residues, ${c.n_threatening} producing escape > 0`}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "auto minmax(90px, 1fr) auto auto",
                      gap: 6, alignItems: "center",
                      fontSize: 9.5, fontFamily: "var(--lys-font-body)",
                    }}>
                    <span style={{
                      width: 8, height: 8, borderRadius: 8,
                      background: col, flexShrink: 0,
                    }} />
                    <span style={{
                      fontWeight: 600, color: "var(--lys-text)",
                      minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}>{c.drug_class}</span>
                    <div style={{
                      width: 100, height: 6, borderRadius: 3,
                      background: "rgba(0,0,0,0.05)", overflow: "hidden",
                    }}>
                      <div style={{
                        width: `${robPct}%`, height: "100%",
                        background: tier.fg, opacity: 0.85,
                      }} />
                    </div>
                    <span style={{
                      fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                      color: tier.fg, fontSize: 9,
                      minWidth: 38, textAlign: "right",
                    }}>{c.robustness.toFixed(2)}</span>
                  </div>
                );
              })}
            </div>
          </div>
        </>
      )}

      {/* ── ESCAPE HEATMAP — the centerpiece. Always visible (was hidden in a
          collapsed <details>, so the best visual went unseen). Every residue ×
          every substitution, coloured by escape score; clinical mutations
          ringed red; click a cell/residue → focus it in the 3D theater. ── */}
      {data.n_residues_with_contacts > 0 && (
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8,
            marginBottom: 6 }}>
            <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              color: LAV.fgDeep, letterSpacing: "0.06em",
              textTransform: "uppercase", fontWeight: 700 }}>
              escape heatmap · 20 substitutions × {positions.length} residues
            </span>
            <span style={{ flex: 1 }} />
            {/* colour-scale legend */}
            <span style={{ display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-faint)" }}>
              <span>low</span>
              <span style={{ display: "inline-flex", borderRadius: 2, overflow: "hidden",
                border: "1px solid rgba(0,0,0,0.08)" }}>
                {[0.05, 0.2, 0.35, 0.5, 0.7, 0.9].map((s) => (
                  <span key={s} style={{ width: 12, height: 8, background: scoreColor(s) }} />
                ))}
              </span>
              <span>high escape</span>
              <span style={{ width: 9, height: 9, borderRadius: 2, marginLeft: 6,
                border: `1.5px solid ${RED.fg}` }} />
              <span>clinical</span>
            </span>
          </div>
          <FullHeatmap
            data={data}
            positions={positions}
            aas={aas}
            hoverCell={hoverCell}
            setHoverCell={setHoverCell}
            pinnedCell={pinnedCell}
            clinicalCells={clinicalCells}
            scoreColor={scoreColor}
            contactStrength={contactStrength}
            onCellClick={onCellClick}
            onResidueFocus={onResidueFocus}
          />
          <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)", marginTop: 4 }}>
            rows = the 20 amino-acid substitutions · columns = pocket-contact
            residues (with distance) · hover a cell for the escape-score
            breakdown, click to focus the residue in 3D
          </div>
        </div>
      )}

      {/* ── Vulnerable atoms ── */}
      {data.vulnerable_atoms.length > 0 && (
        <>
          <SectionLabel text={`Vulnerable atoms · top ${data.vulnerable_atoms.length}`} mt={4} />
          {/* The candidate structure with its escape-vulnerable atoms ringed
              red — "which bonds of MY molecule resistance will attack first."
              Click the molecule to focus the top vulnerable atom in 2D/3D. */}
          {smiles && (
            <div style={{ display: "flex", gap: 10, alignItems: "center",
              marginBottom: 5, padding: "6px 8px", borderRadius: 6,
              background: RED.bg, border: `1px solid ${RED.border}` }}>
              <Mol2DThumb apiBase={apiBase} smiles={smiles} w={132} h={96}
                accent={RED.fg} caption="escape-vulnerable sites"
                highlight={data.vulnerable_atoms.map((v) => v.atom_idx)}
                onClick={() => onVulnRowClick(data.vulnerable_atoms[0])}
                title="Red-ringed atoms = most resistance-vulnerable. Click to focus." />
              <div style={{ flex: 1, minWidth: 0, fontSize: 9.5,
                color: "var(--lys-text-dim)", lineHeight: 1.5 }}>
                The <b style={{ color: RED.fg }}>red-ringed atoms</b> are where a
                single clinical mutation most weakens this candidate's binding —
                the positions to harden first. Each maps to a known escape
                mutation below.
              </div>
            </div>
          )}
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {data.vulnerable_atoms.slice(0, 6).map((v) => {
              const m = v.top_mutation;
              const col = classColor(m.drug_class);
              return (
                <div key={v.atom_idx}
                  onClick={() => onVulnRowClick(v)}
                  title={`${m.note}\n\nclick to focus atom ${v.atom_idx} + residue ${m.position}`}
                  style={{
                    padding: "4px 6px", borderRadius: 4,
                    background: RED.bg, border: `1px solid ${RED.border}`,
                    borderLeft: `3px solid ${RED.fg}`,
                    display: "grid", gridTemplateColumns: "auto auto 1fr auto auto",
                    gap: 6, alignItems: "center",
                    fontSize: 9.5, cursor: "pointer",
                    backdropFilter: "blur(10px)",
                  }}>
                  <span style={{
                    padding: "1px 5px", borderRadius: 3,
                    background: RED.fg, color: "white",
                    fontFamily: "var(--lys-font-mono)", fontWeight: 800,
                    fontSize: 9,
                  }}>atom {v.atom_idx}</span>
                  <span style={{
                    padding: "0 4px", borderRadius: 2,
                    background: `${col}20`, color: col, fontWeight: 700,
                    fontFamily: "var(--lys-font-mono)", fontSize: 9,
                  }}>{m.wt}{m.position}{m.mutant}</span>
                  <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                    color: "var(--lys-text-dim)", fontSize: 9,
                  }}>{m.drug_class} · {m.frequency}</span>
                  <span style={{
                    fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                    color: v.escape_score >= 0.5 ? RED.fg : v.escape_score >= 0.25 ? AMBER.fg : "var(--lys-text-faint)",
                  }}>{v.escape_score.toFixed(2)}</span>
                  <button
                    onClick={(e) => { e.stopPropagation(); onHardenAtom(v.atom_idx); }}
                    style={{
                      padding: "1px 6px",
                      fontSize: 8.5, fontWeight: 600, fontFamily: "var(--lys-font-body)",
                      background: LAV.bgStrong, border: `1px solid ${LAV.border}`,
                      borderRadius: 3, color: LAV.fgDeep, cursor: "pointer",
                    }}>harden →</button>
                </div>
              );
            })}
          </div>
        </>
      )}

      {data.vulnerable_atoms.length === 0 && data.n_residues_with_contacts > 0 && (
        <div style={{
          marginTop: 4, padding: "6px 10px",
          background: GREEN.bg, border: `1px solid ${GREEN.border}`,
          borderRadius: 4, fontSize: 10, color: "#059669",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <Shield size={12} />
          No clinical-resistance vulnerabilities detected for this candidate's contact residues.
        </div>
      )}

      {data.n_residues_with_contacts === 0 && (
        <div style={{
          marginTop: 4, padding: "6px 10px",
          background: AMBER.bg, border: `1px solid ${AMBER.border}`,
          borderRadius: 4, fontSize: 10, color: "#92400e",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <AlertTriangle size={12} />
          Candidate makes no contacts with active-site residues — pose may be off, check 3D theater.
        </div>
      )}
    </>
  );
}


// ─────────────────────────────────────────────────────────────────────
// HARDEN MODE
// ─────────────────────────────────────────────────────────────────────

function HardenMode({
  data, hardenAtomIdx, setHardenAtomIdx, hardenResult, hardenLoading, hardenError,
  onAgentMessage, onResidueFocus, onLoadSmiles,
}: {
  data: ResistanceResult;
  hardenAtomIdx: number | null;
  setHardenAtomIdx: (idx: number | null) => void;
  hardenResult: HardenResult | null;
  hardenLoading: boolean;
  hardenError: string;
  onAgentMessage?: (msg: string) => void;
  onResidueFocus?: (resid: number | null) => void;
  onLoadSmiles?: (smi: string, label?: string) => void;
}) {
  const vulns = data.vulnerable_atoms;

  return (
    <>
      <SectionLabel text="Pick a vulnerable atom to harden" />
      {vulns.length === 0 ? (
        <div style={{
          padding: "6px 10px",
          background: GREEN.bg, border: `1px solid ${GREEN.border}`,
          borderRadius: 4, fontSize: 10, color: "#059669",
        }}>
          No vulnerable atoms detected — nothing to harden.
        </div>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 10 }}>
          {vulns.map((v) => {
            const sel = hardenAtomIdx === v.atom_idx;
            return (
              <button
                key={v.atom_idx}
                onClick={() => {
                  setHardenAtomIdx(v.atom_idx);
                  onResidueFocus?.(v.top_mutation.position);
                }}
                style={{
                  padding: "2px 8px", height: 22,
                  fontSize: 9.5, fontWeight: 500, fontFamily: "var(--lys-font-body)",
                  borderRadius: 4, cursor: "pointer",
                  background: sel ? LAV.bgStrong : "rgba(255,255,255,0.6)",
                  border: `1px solid ${sel ? LAV.borderStrong : LAV.border}`,
                  color: sel ? LAV.fgDeep : "var(--lys-text)",
                  display: "inline-flex", alignItems: "center", gap: 5,
                  backdropFilter: "blur(10px)",
                }}>
                <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 700 }}>atom {v.atom_idx}</span>
                <span style={{ opacity: 0.65 }}>{v.top_mutation.wt}{v.top_mutation.position}{v.top_mutation.mutant}</span>
                <span style={{
                  fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                  color: v.escape_score >= 0.5 ? RED.fg : AMBER.fg,
                }}>{v.escape_score.toFixed(2)}</span>
              </button>
            );
          })}
        </div>
      )}

      {/* Empty-state guidance — when no atom chosen, explain what HARDEN does */}
      {hardenAtomIdx == null && vulns.length > 0 && (
        <div style={{
          padding: "8px 10px",
          background: LAV.bg, border: `1px solid ${LAV.border}`,
          borderLeft: `3px solid ${LAV.fg}`,
          borderRadius: 4, fontSize: 10,
          color: "var(--lys-text-dim)", lineHeight: 1.5,
        }}>
          <div style={{
            fontSize: 9, fontFamily: "var(--lys-font-mono)",
            color: LAV.fgDeep, fontWeight: 700, marginBottom: 3,
            letterSpacing: "0.06em", textTransform: "uppercase",
          }}>What "harden" does</div>
          Pick a vulnerable atom above. The system identifies the clinical
          mutation that defeats it (e.g., K247T disabling β-lactam binding)
          and returns specific medchem swaps that survive that escape vector
          — drawn from a curated playbook (e.g., add 6α-methoxy for PBP2a
          escape) plus an AI-bespoke recommendation. Click "send to agent"
          on any suggestion to apply it through the chat thread.
        </div>
      )}

      {hardenLoading && (
        <div style={{
          padding: "8px 10px",
          background: LAV.bg, border: `1px solid ${LAV.border}`,
          borderRadius: 4, fontSize: 10, color: LAV.fgDeep,
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <RefreshCw size={11} style={{ animation: "spin 1s linear infinite" }} />
          Generating hardening suggestions for atom {hardenAtomIdx}…
        </div>
      )}

      {/* Live backend result — when the harden endpoint returns,
          render the suggestions. If it fails (or fetch dropped), we
          surface the error visibly so the issue can be diagnosed
          rather than silently empty. NO client-side fallback here —
          the backend IS the source of truth. */}
      {hardenAtomIdx != null && !hardenLoading && hardenError && (
        <div style={{
          marginTop: 4, padding: "8px 10px",
          background: RED.bg, border: `1px solid ${RED.border}`,
          borderLeft: `3px solid ${RED.fg}`,
          borderRadius: 4, fontSize: 9.5,
          lineHeight: 1.5, color: RED.fg,
          fontFamily: "var(--lys-font-mono)",
        }}>
          <div style={{ fontWeight: 700, marginBottom: 2 }}>
            ⚠ harden endpoint failed
          </div>
          <div style={{ color: "var(--lys-text-dim)", fontFamily: "var(--lys-font-body)" }}>
            {hardenError}
          </div>
        </div>
      )}

      {hardenAtomIdx != null && !hardenLoading && !hardenError && hardenResult && (() => {
        const suggestions = hardenResult.suggestions ?? [];
        const targetAtom = vulns.find((v) => v.atom_idx === hardenAtomIdx);
        const m = targetAtom?.top_mutation;
        if (suggestions.length === 0) {
          return (
            <div style={{
              marginTop: 4, padding: "8px 10px",
              background: AMBER.bg, border: `1px solid ${AMBER.border}`,
              borderRadius: 4, fontSize: 10, color: AMBER.fg,
            }}>
              Backend returned no suggestions for atom {hardenAtomIdx}. Check
              GEMINI_API_KEY and the playbook bucket coverage server-side.
            </div>
          );
        }
        return (
          <>
            {/* Atom-context summary — what we're hardening against */}
            {m && (
              <div style={{
                marginTop: 4, padding: "5px 8px",
                background: RED.bg, border: `1px solid ${RED.border}`,
                borderLeft: `3px solid ${RED.fg}`,
                borderRadius: 4, fontSize: 9.5,
                lineHeight: 1.5, color: "var(--lys-text-dim)",
              }}>
                Hardening{" "}
                <strong style={{ fontFamily: "var(--lys-font-mono)", color: RED.fg }}>
                  atom {hardenAtomIdx}
                </strong>{" "}
                against{" "}
                <strong style={{ fontFamily: "var(--lys-font-mono)", color: RED.fg }}>
                  {m.wt}{m.position}{m.mutant}
                </strong>{" "}
                — {m.drug_class}, {m.frequency} clinical frequency
                {m.note ? `. ${m.note.slice(0, 140)}` : ""}.
              </div>
            )}
            {/* Calculative inputs strip — every per-suggestion confidence
                is derived from these signals. Surfacing them so the user
                knows what's calculated vs what's a curated swap. */}
            {hardenResult.compute_inputs && (
              <div style={{
                marginTop: 6, padding: "6px 9px",
                background: LAV.bg, border: `1px solid ${LAV.border}`,
                borderRadius: 4, fontFamily: "var(--lys-font-mono)",
                fontSize: 9,
                display: "grid", gridTemplateColumns: "repeat(6, minmax(0, 1fr))",
                gap: 6,
              }}>
                <FactorPip label="bucket" v={hardenResult.compute_inputs.bucket_match ?? 0} />
                <FactorPip label="chem"   v={hardenResult.compute_inputs.chem_inverse ?? 0} />
                <FactorPip label="dist"   v={hardenResult.compute_inputs.bond_proximity ?? 0} />
                <FactorPip label="atom"   v={hardenResult.compute_inputs.atom_feasible ?? 0} />
                <FactorPip label="Δaa"    v={hardenResult.compute_inputs.grantham} max={215} mono />
                <FactorPip label="class"  v={hardenResult.bucket}  raw />
              </div>
            )}
            {hardenResult.llm_status === "no_api_key" && (
              <div style={{
                marginTop: 6, padding: "5px 9px",
                background: AMBER.bg, border: `1px solid ${AMBER.border}`,
                borderLeft: `3px solid ${AMBER.fg}`,
                borderRadius: 4, fontSize: 9.5,
                color: AMBER.fg, fontFamily: "var(--lys-font-mono)",
              }}>
                AI suggestion skipped — set GEMINI_API_KEY env var on the
                backend to enable bespoke recommendations.
              </div>
            )}
            {hardenResult.llm_status === "call_failed" && (
              <div style={{
                marginTop: 6, padding: "5px 9px",
                background: RED.bg, border: `1px solid ${RED.border}`,
                borderLeft: `3px solid ${RED.fg}`,
                borderRadius: 4, fontSize: 9.5,
                color: RED.fg, fontFamily: "var(--lys-font-mono)",
              }}>
                AI tier failed — check backend logs.
                Playbook suggestions still available below.
              </div>
            )}
            {/* TWO SECTIONS — AI-bespoke + Curated playbook side by side. */}
            {(() => {
              const gem = hardenResult.gemini_suggestions ?? suggestions.filter(s => s.source === "gemini");
              const pb  = hardenResult.playbook_suggestions ?? suggestions.filter(s => s.source === "playbook");
              return (
                <>
                  {gem.length > 0 && (
                    <>
                      <SectionLabel text={`AI-bespoke · ${gem.length} candidate-specific swap${gem.length === 1 ? "" : "s"}`} mt={8} />
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {gem.map((s, i) => (
                          <SuggestionCard key={`g${i}`} s={s}
                            atomIdx={hardenAtomIdx} onAgentMessage={onAgentMessage}
                            onLoadSmiles={onLoadSmiles} />
                        ))}
                      </div>
                    </>
                  )}
                  {pb.length > 0 && (
                    <>
                      <SectionLabel text={`Curated playbook · ${pb.length} medchem heuristic${pb.length === 1 ? "" : "s"} · bucket ${hardenResult.bucket}`} mt={10} />
                      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                        {pb.map((s, i) => (
                          <SuggestionCard key={`p${i}`} s={s}
                            atomIdx={hardenAtomIdx} onAgentMessage={onAgentMessage}
                            onLoadSmiles={onLoadSmiles} />
                        ))}
                      </div>
                    </>
                  )}
                </>
              );
            })()}
          </>
        );
      })()}
    </>
  );
}


// ─────────────────────────────────────────────────────────────────────
// COMPARE MODE
// ─────────────────────────────────────────────────────────────────────

function CompareMode({
  pdbId, sessionCandidates, comparePicks, togglePick, runCompare,
  compareResult, compareLoading, onResidueFocus,
}: {
  pdbId: string | null;
  sessionCandidates: SessionCandidate[];
  comparePicks: string[];
  togglePick: (id: string) => void;
  runCompare: () => void;
  compareResult: CompareResult | null;
  compareLoading: boolean;
  onResidueFocus?: (resid: number | null) => void;
}) {
  if (!pdbId) {
    return <Empty msg="Pick a target in the 3D theater first" />;
  }
  if (sessionCandidates.length === 0) {
    return <Empty msg="No candidates in this session yet" />;
  }
  return (
    <>
      <SectionLabel text="Pick 2-5 candidates to compare" />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginBottom: 8 }}>
        {sessionCandidates.map((c) => {
          const sel = comparePicks.includes(c.id);
          return (
            <button
              key={c.id}
              onClick={() => togglePick(c.id)}
              style={{
                padding: "2px 8px", height: 22,
                fontSize: 9.5, fontWeight: 500, fontFamily: "var(--lys-font-body)",
                borderRadius: 4, cursor: "pointer",
                background: sel ? LAV.bgStrong : "rgba(255,255,255,0.6)",
                border: `1px solid ${sel ? LAV.borderStrong : LAV.border}`,
                color: sel ? LAV.fgDeep : "var(--lys-text)",
                display: "inline-flex", alignItems: "center", gap: 5,
                backdropFilter: "blur(10px)",
              }}>
              <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 700 }}>{c.id.slice(0, 6)}</span>
              <span style={{ opacity: 0.7 }}>{c.created_by}</span>
              {c.composite != null && (
                <span style={{ fontFamily: "var(--lys-font-mono)", color: GREEN.fg, fontWeight: 700 }}>
                  {c.composite.toFixed(2)}
                </span>
              )}
            </button>
          );
        })}
      </div>
      <button
        onClick={runCompare}
        disabled={comparePicks.length < 2 || compareLoading}
        style={{
          padding: "2px 10px", height: 22,
          fontSize: 9.5, fontWeight: 600, fontFamily: "var(--lys-font-body)",
          borderRadius: 4,
          cursor: comparePicks.length < 2 ? "not-allowed" : "pointer",
          background: comparePicks.length < 2 ? "rgba(0,0,0,0.04)" : LAV.fgDeep,
          color: comparePicks.length < 2 ? "var(--lys-text-faint)" : "white",
          border: "none",
          marginBottom: 8,
        }}>
        {compareLoading ? "Comparing…" : `Compare ${comparePicks.length}`}
      </button>

      {compareResult && (
        <>
          <SectionLabel text={`Results · ${compareResult.n_valid}/${compareResult.n} valid`} mt={4} />
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {compareResult.rows.map((r, i) => {
              if (!r.valid) return (
                <div key={i} style={{
                  padding: "4px 8px", fontSize: 9.5, color: RED.fg,
                  background: RED.bg, border: `1px solid ${RED.border}`,
                  borderRadius: 4,
                }}>{r.label}: {r.error || "invalid"}</div>
              );
              const isBest = compareResult.best_idx === i;
              const robTier = (r.robustness_score! >= 0.7 ? GREEN : r.robustness_score! >= 0.4 ? AMBER : RED);
              return (
                <div key={i} style={{
                  padding: "5px 9px",
                  background: isBest ? GREEN.bg : LAV.bg,
                  border: `1px solid ${isBest ? GREEN.border : LAV.border}`,
                  borderLeft: `3px solid ${isBest ? GREEN.fg : LAV.fg}`,
                  borderRadius: 4,
                  display: "grid", gridTemplateColumns: "1fr auto auto auto",
                  gap: 8, alignItems: "center", fontSize: 9.5,
                  backdropFilter: "blur(10px)",
                }}>
                  <span style={{ fontWeight: 600 }}>
                    {r.label}{isBest && <span style={{ marginLeft: 4, color: GREEN.fg, fontFamily: "var(--lys-font-mono)" }}>★ best</span>}
                  </span>
                  <Pill {...robTier} text={`R ${r.robustness_score!.toFixed(2)}`} bold />
                  <Pill {...((r.n_escape_vectors || 0) > 0 ? RED : GREEN)}
                        text={`${r.n_escape_vectors || 0} esc`} />
                  <Pill bg={LAV.bg} border={LAV.border} fg={LAV.fgDeep}
                        text={`${r.n_residues_with_contacts || 0} contacts`} />
                </div>
              );
            })}
          </div>

          {compareResult.common_weak_residues.length > 0 && (
            <>
              <SectionLabel text="Common weak residues · ≥50% of candidates affected" mt={10} />
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {compareResult.common_weak_residues.slice(0, 8).map((r) => (
                  <button
                    key={r.position}
                    onClick={() => onResidueFocus?.(r.position)}
                    style={{
                      padding: "2px 8px", height: 22,
                      fontSize: 9.5, fontWeight: 500,
                      borderRadius: 4, cursor: "pointer",
                      background: AMBER.bg, border: `1px solid ${AMBER.border}`,
                      color: AMBER.fg,
                      fontFamily: "var(--lys-font-body)",
                    }}>
                    <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 700 }}>res {r.position}</span>
                    {" "}<span style={{ opacity: 0.7 }}>{r.n_candidates}/{compareResult.n_valid}</span>
                  </button>
                ))}
              </div>
            </>
          )}
        </>
      )}
    </>
  );
}


// ─────────────────────────────────────────────────────────────────────
// Tiny atoms
// ─────────────────────────────────────────────────────────────────────

function Pill({ bg, border, fg, text, bold }:
  { bg: string; border: string; fg: string; text: string; bold?: boolean }) {
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 999,
      background: bg, border: `1px solid ${border}`,
      color: fg, fontWeight: bold ? 700 : 600, fontSize: 9,
      fontFamily: "var(--lys-font-mono)",
    }}>{text}</span>
  );
}

function ChipBtn({ onClick, icon, label }: { onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "2px 7px", height: 22,
        fontSize: 9.5, fontWeight: 500, fontFamily: "var(--lys-font-body)",
        borderRadius: 4, cursor: "pointer",
        background: LAV.bgStrong, border: `1px solid ${LAV.borderStrong}`,
        color: LAV.fgDeep,
        display: "inline-flex", alignItems: "center", gap: 4,
        backdropFilter: "blur(10px)",
      }}>
      {icon}{label}
    </button>
  );
}

function ModeTab({ active, onClick, icon, label }:
  { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      onClick={onClick}
      style={{
        padding: "2px 7px", height: 22,
        fontSize: 9.5, fontWeight: 500, fontFamily: "var(--lys-font-body)",
        borderRadius: 4, cursor: "pointer",
        background: active ? LAV.bgStrong : "transparent",
        border: `1px solid ${active ? LAV.borderStrong : "transparent"}`,
        color: active ? LAV.fgDeep : "var(--lys-text-faint)",
        display: "inline-flex", alignItems: "center", gap: 4,
        textTransform: "uppercase", letterSpacing: "0.04em",
      }}>
      {icon}{label}
    </button>
  );
}

/** Render one harden suggestion. Same visual language for both AI-bespoke
 *  (lavender) and curated playbook (white-glass) sources, but with full
 *  metadata exposed: mechanism, proposed SMILES, predicted Δrobustness,
 *  factor breakdown — calculative end-to-end. */
function SuggestionCard({ s, atomIdx, onAgentMessage, onLoadSmiles }: {
  s: Suggestion & {
    mechanism?: string;
    proposed_smiles?: string;
    proposed_smiles_valid?: boolean;
    predicted_robustness_delta?: number;
  };
  atomIdx: number | null;
  onAgentMessage?: (msg: string) => void;
  /** DIRECT cross-link: load proposed SMILES into 2D + 3D canvas
   *  + auto-score (the hardening actually changes the molecule on
   *  screen, not just a chat ping). */
  onLoadSmiles?: (smi: string, label?: string) => void;
}) {
  const isAI = s.source === "gemini";
  const accent = isAI ? LAV.fgDeep : LAV.fg;
  return (
    <div style={{
      padding: "7px 10px",
      background: isAI ? LAV.bg : "rgba(255,255,255,0.6)",
      border: `1px solid ${isAI ? LAV.borderStrong : LAV.border}`,
      borderLeft: `3px solid ${accent}`,
      borderRadius: 4,
      backdropFilter: "blur(10px)",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 5, flexWrap: "wrap",
        fontSize: 10, fontWeight: 700, color: LAV.fgDeep, marginBottom: 3,
      }}>
        <span style={{
          padding: "1px 5px", borderRadius: 3,
          background: accent, color: "white",
          fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
        }}>{isAI ? "AI" : "PLAYBOOK"}</span>
        {s.mechanism && (
          <span style={{
            padding: "1px 5px", borderRadius: 3,
            background: "rgba(0,0,0,0.05)", color: "var(--lys-text-dim)",
            fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
            fontWeight: 600, textTransform: "uppercase",
          }}>{s.mechanism}</span>
        )}
        <span>{s.swap}</span>
        <span style={{ flex: 1 }} />
        {typeof s.predicted_robustness_delta === "number" && s.predicted_robustness_delta > 0 && (
          <span style={{
            padding: "1px 5px", borderRadius: 3,
            background: GREEN.bg, color: GREEN.fg, fontWeight: 700,
            fontFamily: "var(--lys-font-mono)", fontSize: 8.5,
          }}
            title="Predicted gain in robustness if applied">
            +{s.predicted_robustness_delta.toFixed(2)} Δrob
          </span>
        )}
        <span style={{
          fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)", fontWeight: 600,
        }}>conf {s.confidence.toFixed(2)}</span>
      </div>
      <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)", lineHeight: 1.45 }}>
        {s.rationale}
      </div>
      {s.proposed_smiles && (
        <div style={{
          marginTop: 4,
          display: "flex", alignItems: "center", gap: 6,
          padding: "3px 6px",
          background: s.proposed_smiles_valid ? GREEN.bg : RED.bg,
          border: `1px solid ${s.proposed_smiles_valid ? GREEN.border : RED.border}`,
          borderRadius: 3,
          fontFamily: "var(--lys-font-mono)", fontSize: 8.5,
          color: "var(--lys-text-dim)",
        }}>
          <span style={{
            color: s.proposed_smiles_valid ? GREEN.fg : RED.fg,
            fontWeight: 700,
          }}>{s.proposed_smiles_valid ? "✓ valid" : "⚠ invalid"}</span>
          <span style={{ minWidth: 0, overflow: "hidden",
            textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
            {s.proposed_smiles}
          </span>
        </div>
      )}
      {s._factors && (
        <div style={{
          marginTop: 4,
          display: "flex", flexWrap: "wrap", gap: 4,
          fontSize: 8, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
        }}>
          {Object.entries(s._factors).map(([k, v]) => (
            <span key={k} style={{
              padding: "1px 5px", borderRadius: 2,
              background: "rgba(0,0,0,0.04)",
            }}>
              {k}={typeof v === "number" ? (v > 1 ? v.toFixed(0) : v.toFixed(2)) : String(v)}
            </span>
          ))}
        </div>
      )}
      {(onAgentMessage || onLoadSmiles) && (
        <div style={{ marginTop: 5, display: "flex", gap: 5, flexWrap: "wrap" }}>
          {/* PRIMARY: Apply to canvas — direct cross-link, no chat round-trip.
           *  Loads the hardened SMILES into BOTH the 2D builder and the 3D
           *  theater, triggers auto-scoring, and updates the radar. The
           *  whole molecule actually changes on screen, fulfilling the
           *  "harden actually changes the candidate" promise. */}
          {s.proposed_smiles && s.proposed_smiles_valid && onLoadSmiles && (
            <button
              onClick={() => onLoadSmiles(
                s.proposed_smiles!,
                `[harden · ${s.swap}]`,
              )}
              title="Load this hardened analog into the 2D builder + 3D theater + re-score"
              style={{
                padding: "2px 9px",
                fontSize: 9.5, fontWeight: 700, fontFamily: "var(--lys-font-body)",
                background: GREEN.fg, border: `1px solid ${GREEN.fg}`,
                borderRadius: 3, color: "white", cursor: "pointer",
              }}>✓ apply to canvas</button>
          )}
          {onAgentMessage && (
            <button
              onClick={() => {
                // Build a rich, multi-word prompt so the EditCommand routes
                // through the Gemini reasoning path (not the keyword shortcut).
                // Includes the rationale so the agent can reason about WHY
                // this swap was suggested and decide if it's right or tweak it.
                const rationale = (s.rationale || "").replace(/\s+/g, " ").slice(0, 240);
                const msg = `/edit atom=${atomIdx} please review and apply this swap: ${s.swap}. Rationale from harden suggestion: ${rationale}`;
                onAgentMessage(msg);
              }}
              title="Send the swap as a slash command for the agent to enact"
              style={{
                padding: "1px 7px",
                fontSize: 8.5, fontWeight: 600, fontFamily: "var(--lys-font-body)",
                background: LAV.bgStrong, border: `1px solid ${LAV.border}`,
                borderRadius: 3, color: LAV.fgDeep, cursor: "pointer",
              }}>send to agent →</button>
          )}
          {s.proposed_smiles && s.proposed_smiles_valid && onAgentMessage && !onLoadSmiles && (
            <button
              onClick={() => onAgentMessage(`/load ${s.proposed_smiles}`)}
              style={{
                padding: "1px 7px",
                fontSize: 8.5, fontWeight: 600, fontFamily: "var(--lys-font-body)",
                background: GREEN.bg, border: `1px solid ${GREEN.border}`,
                borderRadius: 3, color: GREEN.fg, cursor: "pointer",
              }}>load analog →</button>
          )}
        </div>
      )}
    </div>
  );
}


/** Compact factor pip for the calculative-inputs strip. Renders a label
 *  + numeric value + tiny tier-colored bar when v is 0..1. For raw
 *  values (string bucket) renders just the value; for monotone scales
 *  (Grantham 5-215) uses `max` for the bar normalization. */
function FactorPip({ label, v, max, mono, raw }: {
  label: string;
  v: number | string;
  max?: number;
  mono?: boolean;
  raw?: boolean;
}) {
  if (raw || typeof v === "string") {
    return (
      <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 1 }}>
        <span style={{ fontSize: 8, color: "var(--lys-text-faint)", letterSpacing: "0.04em", textTransform: "uppercase" }}>{label}</span>
        <span style={{ fontSize: 9.5, fontWeight: 700, color: LAV.fgDeep,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {String(v)}
        </span>
      </div>
    );
  }
  const m = max ?? 1;
  const norm = Math.max(0, Math.min(1, Number(v) / m));
  const tier = mono ? AMBER : norm >= 0.7 ? GREEN : norm >= 0.4 ? AMBER : RED;
  return (
    <div style={{ minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontSize: 8, color: "var(--lys-text-faint)", letterSpacing: "0.04em", textTransform: "uppercase" }}>{label}</span>
      <span style={{ fontSize: 9.5, fontWeight: 700, color: tier.fg }}>
        {typeof v === "number" ? (max ? v.toFixed(0) : v.toFixed(2)) : String(v)}
      </span>
      <div style={{ height: 3, borderRadius: 2, background: "rgba(0,0,0,0.06)", overflow: "hidden" }}>
        <div style={{ width: `${Math.round(norm * 100)}%`, height: "100%", background: tier.fg, opacity: 0.85 }} />
      </div>
    </div>
  );
}

function SectionLabel({ text, mt = 0 }: { text: string; mt?: number }) {
  return (
    <div style={{
      fontSize: 8.5, color: "var(--lys-text-faint)",
      fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
      textTransform: "uppercase", fontWeight: 700,
      marginTop: mt, marginBottom: 4,
    }}>{text}</div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{
      padding: "30px 10px", textAlign: "center",
      color: "var(--lys-text-faint)", fontSize: 10.5,
      fontFamily: "var(--lys-font-mono)",
    }}>{msg}</div>
  );
}


/** Coverage donut — SVG ring chart showing the per-class robustness.
 *  Each class gets an equal-angle wedge; arc length within the wedge
 *  is filled proportional to that class's robustness. The center shows
 *  the overall robustness fraction. */
function CoverageDonut({ classes }: { classes: DrugClassProfile[] }) {
  const SIZE = 72;
  const R_OUTER = 30;
  const R_INNER = 22;
  const cx = SIZE / 2;
  const cy = SIZE / 2;
  const n = classes.length || 1;
  const wedgeAngle = (Math.PI * 2) / n;
  const overallRob = classes.length > 0
    ? classes.reduce((s, c) => s + c.robustness, 0) / classes.length
    : 0;
  const overallTier = overallRob >= 0.7 ? GREEN : overallRob >= 0.4 ? AMBER : RED;

  return (
    <svg width={SIZE} height={SIZE} style={{ flexShrink: 0 }}>
      {classes.map((c, i) => {
        const start = -Math.PI / 2 + i * wedgeAngle;
        const end = start + wedgeAngle * c.robustness;
        const fullEnd = start + wedgeAngle;
        const col = classColor(c.drug_class);
        const fillPath = arcPath(cx, cy, R_OUTER, R_INNER, start, end);
        const trackPath = arcPath(cx, cy, R_OUTER, R_INNER, end, fullEnd);
        return (
          <g key={c.drug_class}>
            {/* Track (unfilled portion = escape) */}
            <path d={trackPath} fill={`${col}20`} />
            {/* Fill (robustness portion) */}
            <path d={fillPath} fill={col} opacity={0.85} />
          </g>
        );
      })}
      {/* Center number */}
      <text x={cx} y={cy + 1} textAnchor="middle" dominantBaseline="middle"
        fontSize={13} fontWeight={700}
        fill={overallTier.fg}
        fontFamily="var(--lys-font-body)">
        {(overallRob * 100).toFixed(0)}%
      </text>
      <text x={cx} y={cy + 13} textAnchor="middle" dominantBaseline="middle"
        fontSize={6.5}
        fill="var(--lys-text-faint)"
        fontFamily="var(--lys-font-mono)"
        letterSpacing={0.6}>
        AVG
      </text>
    </svg>
  );
}

function arcPath(cx: number, cy: number, rOut: number, rIn: number,
                 start: number, end: number): string {
  if (Math.abs(end - start) < 0.001) return "";
  const x1 = cx + rOut * Math.cos(start);
  const y1 = cy + rOut * Math.sin(start);
  const x2 = cx + rOut * Math.cos(end);
  const y2 = cy + rOut * Math.sin(end);
  const x3 = cx + rIn * Math.cos(end);
  const y3 = cy + rIn * Math.sin(end);
  const x4 = cx + rIn * Math.cos(start);
  const y4 = cy + rIn * Math.sin(start);
  const large = end - start > Math.PI ? 1 : 0;
  return `M ${x1} ${y1} A ${rOut} ${rOut} 0 ${large} 1 ${x2} ${y2} L ${x3} ${y3} A ${rIn} ${rIn} 0 ${large} 0 ${x4} ${y4} Z`;
}


/** Full heatmap — the original 20-amino-acid × N-residues grid. Hidden
 *  by default behind a <details> in MapMode; only specialists need this
 *  level of detail. The per-contact risk cards above carry the same
 *  signal in a denser, less-empty layout. */
function FullHeatmap({
  data, positions, aas, hoverCell, setHoverCell, pinnedCell,
  clinicalCells, scoreColor, contactStrength,
  onCellClick, onResidueFocus,
}: {
  data: ResistanceResult;
  positions: number[];
  aas: string[];
  hoverCell: { pos: number; aa: string; score: number } | null;
  setHoverCell: (c: { pos: number; aa: string; score: number } | null) => void;
  pinnedCell: { pos: number; atom_idx: number | null } | null;
  clinicalCells: Set<string>;
  scoreColor: (s: number) => string;
  contactStrength: Record<number, number>;
  onCellClick: (pos: number, score: number, isClinical: boolean) => void;
  onResidueFocus?: (resid: number | null) => void;
}) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: `34px repeat(${positions.length}, minmax(30px, 1fr))`,
      gap: 2, fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
      alignItems: "stretch",
    }}>
      <div></div>
      {positions.map((p) => {
        const cd = data.contact_residue_details?.find((c) => c.position === p);
        const distLabel = cd ? `${cd.distance_a}Å` : "";
        const isPinned = pinnedCell?.pos === p;
        const colHot = hoverCell?.pos === p;
        return (
          <div key={`hdr-${p}`}
            onClick={() => onResidueFocus?.(p)}
            title={`Residue ${data.all_residue_scores[p].wt}${p}${distLabel ? ` · contact ${distLabel}` : ""} — click to focus in 3D`}
            style={{
              textAlign: "center", padding: "2px 0",
              fontSize: 8.5, color: (isPinned || colHot) ? LAV.fgDeep : "var(--lys-text-dim)",
              fontWeight: 800, cursor: "pointer", lineHeight: 1.05,
              borderRadius: 3,
              background: colHot ? "rgba(124,99,216,0.12)" : "transparent",
            }}>
            <div>{data.all_residue_scores[p].wt}{p}</div>
            {distLabel && (
              <div style={{ fontSize: 6.5, opacity: 0.7, fontWeight: 600,
                color: cd && cd.distance_a <= 3 ? RED.fg : "var(--lys-text-faint)" }}>
                {distLabel}
              </div>
            )}
          </div>
        );
      })}
      {aas.map((aa) => {
        const rowHot = hoverCell?.aa === aa;
        return (
        <Fragment key={`aa-${aa}`}>
          <div style={{
            textAlign: "right", padding: "0 5px",
            fontSize: 9, color: rowHot ? LAV.fgDeep : "var(--lys-text-faint)",
            fontWeight: 800, display: "flex", alignItems: "center",
            justifyContent: "flex-end",
          }}>{aa}</div>
          {positions.map((p) => {
            const score = data.all_residue_scores[p].mutations[aa] ?? 0;
            const isClinical = clinicalCells.has(`${p}_${aa}`);
            const isWt = data.all_residue_scores[p].wt === aa;
            const isPinned = pinnedCell?.pos === p;
            const cs = contactStrength[p] ?? 0;
            // crosshair: cells sharing the hovered row OR column stay lit
            const cross = !!hoverCell && (hoverCell.pos === p || hoverCell.aa === aa);
            const exact = hoverCell?.pos === p && hoverCell?.aa === aa;
            let bg: string;
            if (isWt) bg = "rgba(100,116,139,0.16)";
            else if (score > 0) bg = scoreColor(score);
            else if (cs > 0) bg = `rgba(124,99,216,${0.05 + cs * 0.07})`;
            else bg = "var(--lys-surface)";
            const showVal = !isWt && score >= 0.2;
            const valColor = score >= 0.55 ? "#ffffff" : "#7a2e0e";
            return (
              <div
                key={`cell-${p}-${aa}`}
                title={isWt ? `${aa}${p} · wild-type`
                  : `${data.all_residue_scores[p].wt}${p}${aa} · escape ${score.toFixed(2)}${isClinical ? " · CLINICAL mutation" : ""}${cs > 0 ? ` · contact ${cs.toFixed(2)}` : ""}`}
                onMouseEnter={() => setHoverCell({ pos: p, aa, score })}
                onMouseLeave={() => setHoverCell(null)}
                onClick={() => onCellClick(p, score, isClinical)}
                style={{
                  height: 17, display: "flex", alignItems: "center",
                  justifyContent: "center",
                  background: bg,
                  border: isClinical
                    ? `2px solid ${RED.fg}`
                    : exact
                      ? `2px solid ${LAV.fgDeep}`
                      : isPinned
                        ? `1.5px solid ${LAV.fgDeep}`
                        : "1px solid rgba(0,0,0,0.06)",
                  borderRadius: 3,
                  cursor: score > 0 || isClinical ? "pointer" : "default",
                  opacity: hoverCell && !cross ? 0.38 : 1,
                  boxShadow: exact ? `0 0 0 2px ${LAV.bg}` : "none",
                  transition: "opacity 90ms",
                  fontSize: 7, fontWeight: 800, color: valColor,
                  position: "relative",
                }}>
                {isWt ? (
                  <span style={{ width: 3, height: 3, borderRadius: 3,
                    background: "rgba(100,116,139,0.5)" }} />
                ) : showVal ? score.toFixed(2).replace(/^0/, "") : null}
              </div>
            );
          })}
        </Fragment>
        );
      })}
    </div>
  );
}


/** KPI metric card. Bigger value, smaller label, optional gauge bar.
 *  Used in the Resistance Map's top-of-card dashboard strip. */
function KPICard({ label, value, unit, sub, tier, gauge }: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  tier: { bg: string; border: string; fg: string };
  gauge?: number;  // 0..1, optional
}) {
  return (
    <div style={{
      padding: "6px 8px",
      background: tier.bg, border: `1px solid ${tier.border}`,
      borderLeft: `3px solid ${tier.fg}`,
      borderRadius: 4,
      backdropFilter: "blur(10px)",
      display: "flex", flexDirection: "column", gap: 2,
      minWidth: 0,
    }}>
      <div style={{
        fontSize: 8, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)",
        letterSpacing: "0.06em", textTransform: "uppercase", fontWeight: 700,
      }}>{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 3 }}>
        <span style={{
          fontSize: 17, fontWeight: 700, color: tier.fg,
          fontFamily: "var(--lys-font-body)", lineHeight: 1.1,
        }}>{value}</span>
        {unit && (
          <span style={{
            fontSize: 8.5, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)",
          }}>{unit}</span>
        )}
      </div>
      {sub && (
        <div style={{
          fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
          color: tier.fg, fontWeight: 600,
          minWidth: 0, overflow: "hidden", textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>{sub}</div>
      )}
      {gauge != null && (
        <div style={{
          marginTop: 2, height: 3, borderRadius: 2,
          background: "rgba(0,0,0,0.06)", overflow: "hidden",
        }}>
          <div style={{
            width: `${Math.round(gauge * 100)}%`, height: "100%",
            background: tier.fg, opacity: 0.85,
          }} />
        </div>
      )}
    </div>
  );
}

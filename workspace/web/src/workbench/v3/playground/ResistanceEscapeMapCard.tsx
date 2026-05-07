/**
 * ResistanceEscapeMapCard — Service 2: per-atom resistance vulnerability
 * heatmap + clinical-overlap list for the Chemistry container.
 *
 * For the current 2D candidate + selected target (passed from the 3D
 * Theater's target picker), this card calls /chem/resistance/predict
 * and renders:
 *   1. A heatmap of position × mutant_aa colored by escape score, with
 *      red borders on cells that match known clinical mutations
 *   2. A robustness badge (green/amber/red)
 *   3. A list of clinical-overlap mutations sorted by score
 *   4. Vulnerable atoms list — clicking an atom row should bubble back to
 *      the 2D builder so it gets a halo (handled by parent state)
 *
 * Same UX rule as the rest of the chem container: every signal here also
 * appears as a halo on the 2D builder. Single source of truth = WorkbenchV3
 * state. The card pushes vulnerableAtoms[] up via onVulnerableChange so the
 * 2D builder can paint orange halos on those exact atoms.
 */
import { useEffect, useState } from "react";
import { Shield, RefreshCw, AlertTriangle } from "lucide-react";

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

interface ResistanceResult {
  pdb_id: string;
  smiles: string;
  target_name: string;
  pathogen: string;
  robustness_score: number;
  n_escape_vectors: number;
  vulnerable_atoms: VulnerableAtom[];
  clinical_overlap: ClinicalOverlap[];
  all_residue_scores: Record<number, { wt: string; mutations: Record<string, number> }>;
  n_total_known_mutations: number;
  n_residues_with_contacts: number;
  summary: string;
}

interface Props {
  apiBase: string;
  smiles: string | null;
  pdbId: string | null;
  /** Bubble vulnerable-atom indices upward so 2D builder can paint halos. */
  onVulnerableChange?: (atomIdxs: number[]) => void;
}

const AA_ROW_ORDER = ["A", "T", "V", "I", "L", "M", "F", "Y", "W", "S", "R", "K", "Q", "N", "D", "E", "H", "C", "G", "P"];

export function ResistanceEscapeMapCard({ apiBase, smiles, pdbId, onVulnerableChange }: Props) {
  const [data, setData] = useState<ResistanceResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hoverCell, setHoverCell] = useState<{ pos: number; aa: string; score: number } | null>(null);

  // Fetch on smiles + pdbId change
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

  // Robustness color tier
  const rs = data?.robustness_score ?? 0;
  const rsTier = rs >= 0.7 ? "robust" : rs >= 0.4 ? "moderate" : "vulnerable";
  const RS_COLORS = {
    robust:     { fg: "#10b981", bg: "rgba(16,185,129,0.10)", border: "rgba(16,185,129,0.40)", label: "robust" },
    moderate:   { fg: "#ca8a04", bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.40)",  label: "moderate" },
    vulnerable: { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.40)",  label: "vulnerable" },
  } as const;
  const rc = RS_COLORS[rsTier];

  // Build heatmap grid
  const positions = data ? Object.keys(data.all_residue_scores).map(Number).sort((a, b) => a - b) : [];
  const aas = AA_ROW_ORDER;

  // Score color: 0 = light, 1 = deep red. Color scale via inline interpolation.
  const scoreColor = (s: number): string => {
    if (s <= 0) return "rgba(0,0,0,0)";
    const intensity = Math.min(1, s);
    // light yellow → orange → red
    const r = 254;
    const g = Math.round(220 - 100 * intensity);
    const b = Math.round(180 - 180 * intensity);
    return `rgba(${r},${g},${b},${0.25 + 0.75 * intensity})`;
  };

  // Set of (position, aa) cells that match known clinical mutations
  const clinicalCells = new Set(
    data ? data.clinical_overlap.map((c) => `${c.position}_${c.mutant}`) : []
  );

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      {/* Header */}
      <div style={{
        padding: "5px 10px",
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.06em",
        textTransform: "uppercase",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <Shield size={11} style={{ color: "#dc2626" }} />
        <span>resistance escape map</span>
        {data && (
          <>
            <span style={{ flex: 1 }} />
            <span style={{
              padding: "1px 6px", borderRadius: 999,
              background: rc.bg, border: `1px solid ${rc.border}`,
              color: rc.fg, fontWeight: 700, fontSize: 9,
            }}>
              {rc.label} · {rs.toFixed(2)}
            </span>
            {data.n_escape_vectors > 0 && (
              <span style={{
                padding: "1px 6px", borderRadius: 999,
                background: "rgba(220,38,38,0.10)",
                color: "#dc2626", fontWeight: 700, fontSize: 9,
              }}>
                {data.n_escape_vectors} escape vector{data.n_escape_vectors === 1 ? "" : "s"}
              </span>
            )}
          </>
        )}
        {loading && <RefreshCw size={11} style={{ animation: "spin 1s linear infinite" }} />}
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 8 }}>
        {!smiles && (
          <Empty msg="Pick a candidate to see resistance vulnerability" />
        )}
        {smiles && !pdbId && (
          <Empty msg="Pick a target in the 3D theater to map resistance" />
        )}
        {error && (
          <div style={{ padding: 10, color: "#dc2626", fontSize: 10, fontFamily: "var(--lys-font-mono)" }}>
            error: {error}
          </div>
        )}
        {data && (
          <>
            {/* Summary line */}
            <div style={{
              padding: "5px 8px", marginBottom: 8,
              fontSize: 10, color: "var(--lys-text-dim)",
              background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
              borderRadius: 4, lineHeight: 1.4,
            }}>
              <span style={{ fontWeight: 700, color: "var(--lys-text)" }}>{data.target_name}</span>
              {" · "}
              {data.summary}
            </div>

            {/* Heatmap: positions (cols) × mutation aa (rows) */}
            <div style={{
              fontSize: 8.5, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
              textTransform: "uppercase", fontWeight: 700,
              marginBottom: 4,
            }}>
              Heatmap · residue × mutation
            </div>
            <div style={{
              display: "grid",
              gridTemplateColumns: `26px repeat(${positions.length}, minmax(20px, 1fr))`,
              gap: 1, fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
              alignItems: "center",
            }}>
              {/* Top-left corner */}
              <div></div>
              {/* Position headers */}
              {positions.map((p) => (
                <div key={`hdr-${p}`}
                  title={`Residue ${data.all_residue_scores[p].wt}${p}`}
                  style={{
                    textAlign: "center", padding: "1px 0",
                    fontSize: 7.5, color: "var(--lys-text-faint)",
                    fontWeight: 700,
                  }}>
                  {data.all_residue_scores[p].wt}{p}
                </div>
              ))}
              {/* AA rows */}
              {aas.map((aa) => (
                <>
                  <div key={`row-${aa}`} style={{
                    textAlign: "right", padding: "0 4px",
                    fontSize: 7.5, color: "var(--lys-text-faint)",
                    fontWeight: 700,
                  }}>
                    {aa}
                  </div>
                  {positions.map((p) => {
                    const score = data.all_residue_scores[p].mutations[aa] ?? 0;
                    const isClinical = clinicalCells.has(`${p}_${aa}`);
                    const isWt = data.all_residue_scores[p].wt === aa;
                    return (
                      <div
                        key={`cell-${p}-${aa}`}
                        title={
                          isWt ? `${aa}${p} (wild-type)`
                          : `${data.all_residue_scores[p].wt}${p}${aa} · escape ${score.toFixed(2)}${isClinical ? " · CLINICAL" : ""}`
                        }
                        onMouseEnter={() => setHoverCell({ pos: p, aa, score })}
                        onMouseLeave={() => setHoverCell(null)}
                        style={{
                          height: 14,
                          background: isWt ? "rgba(0,0,0,0.04)" : scoreColor(score),
                          border: isClinical
                            ? "1.5px solid #dc2626"
                            : "1px solid rgba(0,0,0,0.04)",
                          borderRadius: 2,
                          cursor: score > 0 || isClinical ? "pointer" : "default",
                          opacity: hoverCell && (hoverCell.pos !== p || hoverCell.aa !== aa) ? 0.6 : 1,
                          transition: "opacity 100ms",
                        }}
                      />
                    );
                  })}
                </>
              ))}
            </div>

            {/* Hover cell tooltip-like detail */}
            {hoverCell && hoverCell.score > 0 && (() => {
              const cm = data.clinical_overlap.find((c) => c.position === hoverCell.pos && c.mutant === hoverCell.aa);
              return (
                <div style={{
                  marginTop: 6, padding: "4px 8px",
                  background: "rgba(220,38,38,0.06)",
                  border: "1px solid rgba(220,38,38,0.20)",
                  borderRadius: 4,
                  fontSize: 9.5, fontFamily: "var(--lys-font-body)",
                }}>
                  <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 700, color: "#dc2626" }}>
                    {data.all_residue_scores[hoverCell.pos].wt}{hoverCell.pos}{hoverCell.aa}
                  </span>
                  <span style={{ marginLeft: 8 }}>escape {hoverCell.score.toFixed(2)}</span>
                  {cm && (
                    <span style={{ marginLeft: 8, opacity: 0.85 }}>
                      · {cm.drug_class} · {cm.note.slice(0, 80)}
                    </span>
                  )}
                </div>
              );
            })()}

            {/* Vulnerable atoms list */}
            {data.vulnerable_atoms.length > 0 && (
              <>
                <div style={{
                  fontSize: 8.5, color: "var(--lys-text-faint)",
                  fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
                  textTransform: "uppercase", fontWeight: 700,
                  marginTop: 12, marginBottom: 4,
                }}>
                  Vulnerable atoms · top {data.vulnerable_atoms.length}
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                  {data.vulnerable_atoms.slice(0, 6).map((v) => {
                    const m = v.top_mutation;
                    return (
                      <div key={v.atom_idx}
                        title={m.note}
                        style={{
                          padding: "4px 6px", borderRadius: 4,
                          background: "rgba(220,38,38,0.04)",
                          borderLeft: `3px solid #dc2626`,
                          display: "grid", gridTemplateColumns: "auto 1fr auto",
                          gap: 6, alignItems: "center",
                          fontSize: 9.5, fontFamily: "var(--lys-font-body)",
                        }}>
                        <span style={{
                          padding: "1px 5px", borderRadius: 3,
                          background: "#dc2626", color: "white",
                          fontFamily: "var(--lys-font-mono)", fontWeight: 800,
                          fontSize: 9,
                        }}>
                          atom {v.atom_idx}
                        </span>
                        <span style={{ minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 700 }}>
                            {m.wt}{m.position}{m.mutant}
                          </span>
                          {" · "}
                          <span style={{ color: "var(--lys-text-dim)" }}>{m.drug_class}</span>
                        </span>
                        <span style={{
                          fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                          color: v.escape_score >= 0.5 ? "#dc2626" : v.escape_score >= 0.25 ? "#ca8a04" : "var(--lys-text-faint)",
                        }}>
                          {v.escape_score.toFixed(2)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </>
            )}

            {data.vulnerable_atoms.length === 0 && data.n_residues_with_contacts > 0 && (
              <div style={{
                marginTop: 12, padding: "8px 10px",
                background: "rgba(16,185,129,0.06)",
                border: "1px solid rgba(16,185,129,0.30)",
                borderRadius: 4, fontSize: 10,
                color: "#059669",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                <Shield size={12} />
                No known clinical-resistance vulnerabilities detected for this candidate's contact residues.
              </div>
            )}

            {data.n_residues_with_contacts === 0 && (
              <div style={{
                marginTop: 12, padding: "8px 10px",
                background: "rgba(202,138,4,0.06)",
                border: "1px solid rgba(202,138,4,0.30)",
                borderRadius: 4, fontSize: 10,
                color: "#92400e",
                display: "flex", alignItems: "center", gap: 6,
              }}>
                <AlertTriangle size={12} />
                Candidate makes no contacts with active-site residues — pose may be off, check 3D theater.
              </div>
            )}
          </>
        )}
      </div>
    </div>
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

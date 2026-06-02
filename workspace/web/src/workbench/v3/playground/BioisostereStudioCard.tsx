/**
 * BioisostereStudioCard — interactive matched-molecular-pair optimization.
 *
 * The med-chemist's daily move, made systematic: take the loaded lead, apply
 * real RDKit bioisosteric transformations, score every analog through the
 * live engine stack, and show an interactive grid of parent → analog with the
 * per-property DELTAS, the medchem rationale, and one-tap "apply this analog".
 *
 * The most interactive surface in the platform: each row is a real molecule
 * you can adopt as the new candidate. Backend: /workbench/chem/bioisostere/*.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { GitBranch, RefreshCw, ArrowRight, Sparkles } from "lucide-react";
import { Mol2DThumb } from "./Mol2DThumb";
import { ProvenanceBadge, SectionLabel, EmptyState } from "./uiPrimitives";

interface Scores { composite: number | null; sa_score: number | null; activity: number | null; }
interface Analog {
  smiles: string; rule_id: string; transformation: string; axis: string;
  rationale: string; scores: Scores;
  delta_composite: number | null; delta_sa: number | null; delta_activity: number | null;
  improved: boolean;
}
interface Run {
  parent: string; pathogen: string; parent_scores: Scores;
  n_analogs: number; n_improved: number; analogs: Analog[];
  best_improvement: Analog | null; elapsed_s: number; n_rules: number;
  note?: string; artifact_id?: string | null;
}
interface Props {
  apiBase: string; smiles: string | null; pathogen: string | null;
  onLoad?: (smiles: string) => void;
}

const VIO = { fg: "#7c3aed", fgDeep: "#6d28d9", border: "rgba(124,58,237,0.28)",
  bg: "rgba(124,58,237,0.06)" } as const;
const ACT = { fg: "#059669", border: "rgba(16,185,129,0.4)", bg: "rgba(16,185,129,0.08)" } as const;

function deltaColor(d: number | null, goodIsUp = true): string {
  if (d == null || d === 0) return "var(--lys-text-faint)";
  const positive = goodIsUp ? d > 0 : d < 0;
  return positive ? "#16a34a" : "#dc2626";
}
function fmtDelta(d: number | null): string {
  if (d == null) return "—";
  return (d >= 0 ? "+" : "") + d.toFixed(2);
}

export function BioisostereStudioCard({ apiBase, smiles, pathogen, onLoad }: Props) {
  const [run, setRun] = useState<Run | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);
  // Clear when the lead changes.
  useEffect(() => { setRun(null); setError(null); }, [smiles]);

  const explore = useCallback(async () => {
    if (!smiles) return;
    setError(null); setRunning(true);
    abortRef.current?.abort();
    const ac = new AbortController(); abortRef.current = ac;
    try {
      const r = await fetch(`${apiBase}/workbench/chem/bioisostere/run`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ smiles, pathogen: pathogen || "MRSA",
          max_analogs: 12, save: true }),
        signal: ac.signal,
      });
      if (!r.ok) { setError(`run failed (HTTP ${r.status})`); return; }
      setRun(await r.json());
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("studio error");
    } finally { setRunning(false); }
  }, [apiBase, smiles, pathogen]);

  function apply(smi: string) {
    if (onLoad) onLoad(smi);
    else window.dispatchEvent(new CustomEvent("lysos:auto-slash",
      { detail: { text: `/load ${smi}` } }));
  }

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      {/* header */}
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: VIO.fgDeep,
        borderBottom: `1px solid ${VIO.border}` }}>
        <GitBranch size={11} style={{ color: VIO.fg }} />
        <span>bioisostere studio · matched pairs</span>
        <span style={{ flex: 1 }} />
        <ProvenanceBadge real label="RDKit MMP" />
      </div>

      {/* action */}
      <div style={{ padding: "8px 10px", display: "flex", alignItems: "center",
        gap: 8, borderBottom: "1px solid rgba(0,0,0,0.05)" }}>
        <button type="button" onClick={explore} disabled={running || !smiles}
          style={{ display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 11px", borderRadius: 6, border: 0,
            background: !smiles ? "rgba(0,0,0,0.05)" : VIO.fg,
            color: !smiles ? "var(--lys-text-faint)" : "white",
            fontSize: 11, fontWeight: 700, cursor: running || !smiles ? "not-allowed" : "pointer" }}>
          <GitBranch size={12} />
          {running ? "Generating + scoring analogs…" : "Explore bioisosteres"}
        </button>
        <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {smiles ? "real matched-molecular-pair swaps, each scored live"
            : "load a lead to optimize"}
        </span>
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!run && !running && (
          <EmptyState icon={<GitBranch size={22} style={{ opacity: 0.4 }} />}
            msg="Take the lead and apply real medicinal-chemistry bioisosteric swaps — COOH→tetrazole, CH₃→CF₃, phenol→F, and more — each generated with RDKit and scored through the live engines. The daily lead-optimization move, systematized." />
        )}
        {running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 20,
            textAlign: "center", color: VIO.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Applying bioisostere rules + scoring each analog…</div>
          </div>
        )}

        {run && (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {/* summary + parent */}
            <div style={{ display: "flex", alignItems: "center", gap: 10,
              padding: 8, borderRadius: 7, background: VIO.bg,
              border: `1px solid ${VIO.border}` }}>
              <Mol2DThumb apiBase={apiBase} smiles={run.parent} w={92} h={72}
                accent={VIO.fg} caption="lead" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--lys-text)" }}>
                  {run.n_analogs} matched pairs · {run.n_improved} improved
                </div>
                <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", marginTop: 2 }}>
                  parent composite {run.parent_scores.composite?.toFixed(3) ?? "—"} ·
                  {" "}SA {run.parent_scores.sa_score ?? "—"} ·
                  {" "}{run.n_rules} rules · {run.elapsed_s}s
                </div>
              </div>
            </div>

            {/* best improvement hero */}
            {run.best_improvement && (
              <div style={{ border: `1.5px solid ${ACT.border}`, borderRadius: 7,
                background: ACT.bg, padding: "8px 9px" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 5,
                  fontSize: 10, fontWeight: 700, color: ACT.fg, marginBottom: 6 }}>
                  <Sparkles size={12} />
                  <span>Best improvement — {run.best_improvement.transformation}</span>
                </div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
                  gap: 8, padding: "2px 0 6px" }}>
                  <Mol2DThumb apiBase={apiBase} smiles={run.parent} w={120} h={92}
                    accent="rgba(124,58,237,0.4)" caption="lead" />
                  <div style={{ display: "flex", flexDirection: "column",
                    alignItems: "center", gap: 2 }}>
                    <ArrowRight size={18} style={{ color: ACT.fg }} />
                    <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                      color: ACT.fg, fontWeight: 700 }}>
                      {fmtDelta(run.best_improvement.delta_composite)}</span>
                  </div>
                  <Mol2DThumb apiBase={apiBase} smiles={run.best_improvement.smiles}
                    w={120} h={92} accent={ACT.fg} caption="analog" />
                </div>
                <div style={{ fontSize: 9, color: "var(--lys-text-dim)",
                  lineHeight: 1.4, textAlign: "center" }}>
                  {run.best_improvement.rationale}
                </div>
                <button type="button" onClick={() => apply(run.best_improvement!.smiles)}
                  style={{ marginTop: 6, width: "100%", padding: "6px 0", border: 0,
                    borderRadius: 5, background: ACT.fg, color: "white",
                    fontSize: 10.5, fontWeight: 700, cursor: "pointer" }}>
                  Apply this analog → load + re-score
                </button>
              </div>
            )}

            {/* the matched-pair grid */}
            <SectionLabel color={VIO.fgDeep}>matched-pair delta grid</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {run.analogs.map((a, i) => (
                <div key={i} title={a.rationale}
                  style={{ display: "flex", alignItems: "center", gap: 8,
                    padding: "6px 8px", borderRadius: 6,
                    background: a.improved ? "rgba(16,185,129,0.05)" : "var(--lys-surface)",
                    border: `1px solid ${a.improved ? ACT.border : "var(--lys-border)"}` }}>
                  <Mol2DThumb apiBase={apiBase} smiles={a.smiles} w={64} h={50}
                    accent={a.improved ? ACT.fg : VIO.fg}
                    onClick={() => apply(a.smiles)} title={a.smiles} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: "var(--lys-text)",
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {a.transformation}
                    </div>
                    <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
                      color: "var(--lys-text-faint)", textTransform: "uppercase",
                      letterSpacing: "0.03em" }}>{a.axis}</div>
                  </div>
                  {/* delta chips */}
                  <div style={{ display: "flex", gap: 8, flexShrink: 0,
                    fontFamily: "var(--lys-font-mono)" }}>
                    <Delta label="comp" d={a.delta_composite} goodUp />
                    <Delta label="SA" d={a.delta_sa} goodUp={false} />
                    <Delta label="act" d={a.delta_activity} goodUp />
                  </div>
                  <button type="button" onClick={() => apply(a.smiles)}
                    style={{ flexShrink: 0, padding: "3px 9px", borderRadius: 5,
                      border: `1px solid ${a.improved ? ACT.border : VIO.border}`,
                      background: "transparent", color: a.improved ? ACT.fg : VIO.fg,
                      fontSize: 9, fontWeight: 700, cursor: "pointer" }}>
                    apply
                  </button>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", textAlign: "right" }}>
              {run.note ?? ""}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Delta({ label, d, goodUp }: { label: string; d: number | null; goodUp: boolean }) {
  const col = deltaColor(d, goodUp);
  return (
    <div style={{ textAlign: "center", minWidth: 34 }}>
      <div style={{ fontSize: 7, color: "var(--lys-text-faint)",
        textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 10, fontWeight: 700, color: col }}>{fmtDelta(d)}</div>
    </div>
  );
}

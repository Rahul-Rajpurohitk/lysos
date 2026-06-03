/**
 * BioisostereStudioCard — interactive matched-molecular-pair optimization.
 *
 * The med-chemist's daily move, made systematic: take the loaded lead, apply
 * real RDKit bioisosteric transformations, score every analog through the
 * live engine stack, profile it across 10 physicochemical descriptors, and
 * show an interactive board of parent → analog where the SWAP SITE is
 * highlighted on the structure, every property delta is visible, liabilities
 * the swap introduced are flagged, and one tap adopts the analog.
 *
 * The most interactive surface in the platform: each card is a real molecule
 * you can adopt as the new candidate. Backend: /workbench/chem/bioisostere/*.
 */
import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { GitBranch, RefreshCw, ArrowRight, Sparkles, AlertTriangle, ShieldCheck } from "lucide-react";
import { Mol2DThumb } from "./Mol2DThumb";
import { ProvenanceBadge, SectionLabel, EmptyState } from "./uiPrimitives";

interface Scores { composite: number | null; sa_score: number | null; activity: number | null; }
interface SwapAtoms { parent: number[]; analog: number[]; }
interface Alert { name: string; note: string; }
interface DescMeta { label: string; is_int: boolean; good: "up" | "down" | "neutral"; }
interface Analog {
  smiles: string; rule_id: string; transformation: string; axis: string;
  rationale: string; scores: Scores;
  delta_composite: number | null; delta_sa: number | null; delta_activity: number | null;
  improved: boolean; clean?: boolean;
  descriptors?: Record<string, number>;
  delta_props?: Record<string, number>;
  swap_atoms?: SwapAtoms;
  new_alerts?: Alert[];
}
interface Run {
  parent: string; pathogen: string; parent_scores: Scores;
  parent_descriptors?: Record<string, number>;
  desc_keys?: string[]; desc_meta?: Record<string, DescMeta>;
  n_analogs: number; n_improved: number; n_clean?: number; analogs: Analog[];
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

// Per-property "meaningful change" scale → bar fraction. Each descriptor
// lives on a different axis, so we normalise |Δ| by a typical med-chem step.
const PROP_NORM: Record<string, number> = {
  mw: 50, clogp: 1.0, tpsa: 20, hbd: 2, hba: 2, rotb: 2,
  qed: 0.1, fsp3: 0.2, aromatic_rings: 1, heavy: 4,
};

function deltaColor(d: number | null, goodIsUp = true): string {
  if (d == null || d === 0) return "var(--lys-text-faint)";
  const positive = goodIsUp ? d > 0 : d < 0;
  return positive ? "#16a34a" : "#dc2626";
}
function fmtDelta(d: number | null): string {
  if (d == null) return "—";
  return (d >= 0 ? "+" : "") + d.toFixed(2);
}
function fmtPropDelta(d: number, isInt: boolean, key: string): string {
  if (d === 0) return "·";
  const sign = d > 0 ? "+" : "";
  if (isInt) return sign + Math.round(d);
  const dp = key === "qed" || key === "fsp3" ? 2 : 1;
  return sign + d.toFixed(dp);
}

export function BioisostereStudioCard({ apiBase, smiles, pathogen, onLoad }: Props) {
  const [run, setRun] = useState<Run | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<"composite" | "activity" | "qed" | "mw">("composite");
  const [improvedOnly, setImprovedOnly] = useState(false);
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
          max_analogs: 14, save: true }),
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

  const descKeys = run?.desc_keys ?? Object.keys(PROP_NORM);
  const descMeta = run?.desc_meta ?? {};

  const shown = useMemo(() => {
    if (!run) return [] as Analog[];
    let xs = run.analogs.slice();
    if (improvedOnly) xs = xs.filter((a) => a.improved);
    const val = (a: Analog): number => {
      if (sortKey === "composite") return a.delta_composite ?? -9;
      if (sortKey === "activity") return a.delta_activity ?? -9;
      if (sortKey === "qed") return a.delta_props?.qed ?? -9;
      if (sortKey === "mw") return -(a.delta_props?.mw ?? 999);  // prefer MW cut
      return 0;
    };
    return xs.sort((a, b) => val(b) - val(a));
  }, [run, sortKey, improvedOnly]);

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

      {/* action + controls */}
      <div style={{ padding: "8px 10px", display: "flex", alignItems: "center",
        gap: 8, borderBottom: "1px solid rgba(0,0,0,0.05)", flexWrap: "wrap" }}>
        <button type="button" onClick={explore} disabled={running || !smiles}
          style={{ display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 11px", borderRadius: 6, border: 0,
            background: !smiles ? "rgba(0,0,0,0.05)" : VIO.fg,
            color: !smiles ? "var(--lys-text-faint)" : "white",
            fontSize: 11, fontWeight: 700, cursor: running || !smiles ? "not-allowed" : "pointer" }}>
          <GitBranch size={12} />
          {running ? "Generating + scoring…" : run ? "Re-run swaps" : "Explore bioisosteres"}
        </button>
        {run && (
          <>
            <div style={{ display: "inline-flex", alignItems: "center", gap: 4,
              fontSize: 9, fontFamily: "var(--lys-font-mono)", color: "var(--lys-text-faint)" }}>
              <span>sort</span>
              <select value={sortKey} onChange={(e) => setSortKey(e.target.value as typeof sortKey)}
                style={{ fontSize: 9.5, fontFamily: "var(--lys-font-mono)", padding: "2px 4px",
                  borderRadius: 4, border: `1px solid ${VIO.border}`, background: "white",
                  color: VIO.fgDeep, cursor: "pointer" }}>
                <option value="composite">Δ composite</option>
                <option value="activity">Δ activity</option>
                <option value="qed">Δ QED</option>
                <option value="mw">MW reduction</option>
              </select>
            </div>
            <button type="button" onClick={() => setImprovedOnly((v) => !v)}
              style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)", padding: "3px 8px",
                borderRadius: 4, cursor: "pointer",
                border: `1px solid ${improvedOnly ? ACT.border : "var(--lys-border)"}`,
                background: improvedOnly ? ACT.bg : "transparent",
                color: improvedOnly ? ACT.fg : "var(--lys-text-faint)", fontWeight: 700 }}>
              improved only
            </button>
          </>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {smiles ? "real MMP swaps · scored + profiled live" : "load a lead to optimize"}
        </span>
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!run && !running && (
          <EmptyState icon={<GitBranch size={22} style={{ opacity: 0.4 }} />}
            msg="Take the lead and apply real medicinal-chemistry bioisosteric swaps — COOH→tetrazole, CH₃→CF₃, phenol→F, and more. Each is generated with RDKit, scored through the live engines, and profiled across 10 physicochemical descriptors, with the swap site highlighted on the structure. The daily lead-optimization move, systematized." />
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
            {/* summary + parent profile */}
            <div style={{ display: "flex", alignItems: "center", gap: 10,
              padding: 8, borderRadius: 7, background: VIO.bg,
              border: `1px solid ${VIO.border}` }}>
              <Mol2DThumb apiBase={apiBase} smiles={run.parent} w={92} h={72}
                accent={VIO.fg} caption="lead" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 10.5, fontWeight: 700, color: "var(--lys-text)" }}>
                  {run.n_analogs} matched pairs · {run.n_improved} improved
                  {typeof run.n_clean === "number" && ` · ${run.n_clean} clean`}
                </div>
                {run.parent_descriptors && (
                  <ParentProfile desc={run.parent_descriptors} keys={descKeys} meta={descMeta} />
                )}
                <div style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", marginTop: 3 }}>
                  composite {run.parent_scores.composite?.toFixed(3) ?? "—"} ·
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
                  <Mol2DThumb apiBase={apiBase} smiles={run.parent} w={116} h={90}
                    accent="rgba(124,58,237,0.4)" caption="lead"
                    highlight={run.best_improvement.swap_atoms?.parent} />
                  <div style={{ display: "flex", flexDirection: "column",
                    alignItems: "center", gap: 2 }}>
                    <ArrowRight size={18} style={{ color: ACT.fg }} />
                    <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                      color: ACT.fg, fontWeight: 700 }}>
                      {fmtDelta(run.best_improvement.delta_composite)}</span>
                  </div>
                  <Mol2DThumb apiBase={apiBase} smiles={run.best_improvement.smiles}
                    w={116} h={90} accent={ACT.fg} caption="analog"
                    highlight={run.best_improvement.swap_atoms?.analog} />
                </div>
                {run.best_improvement.delta_props && (
                  <PropDeltaStrip deltas={run.best_improvement.delta_props}
                    meta={descMeta} keys={descKeys} />
                )}
                <div style={{ fontSize: 9, color: "var(--lys-text-dim)",
                  lineHeight: 1.4, textAlign: "center", marginTop: 6 }}>
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

            {/* the matched-pair board */}
            <SectionLabel color={VIO.fgDeep}>
              matched-pair board · swap site highlighted · full property profile
            </SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {shown.map((a, i) => (
                <AnalogCard key={a.rule_id + i} a={a} apiBase={apiBase}
                  descKeys={descKeys} descMeta={descMeta} onApply={() => apply(a.smiles)} />
              ))}
              {shown.length === 0 && (
                <div style={{ fontSize: 10, color: "var(--lys-text-faint)",
                  textAlign: "center", padding: 12 }}>
                  No analogs match this filter — turn off “improved only”.
                </div>
              )}
            </div>
            <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", textAlign: "right", lineHeight: 1.4 }}>
              {run.note ?? ""}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** One analog = one matched molecular pair: highlighted structure, the
 *  transformation, liability flags, the engine score deltas, and the full
 *  physicochemical delta strip. */
function AnalogCard({ a, apiBase, descKeys, descMeta, onApply }: {
  a: Analog; apiBase: string;
  descKeys: string[]; descMeta: Record<string, DescMeta>; onApply: () => void;
}) {
  const border = a.improved ? ACT.border : "var(--lys-border)";
  const bg = a.improved ? "rgba(16,185,129,0.05)" : "var(--lys-surface)";
  return (
    <div title={a.rationale}
      style={{ padding: "7px 8px", borderRadius: 7, background: bg,
        border: `1px solid ${border}`, display: "flex", flexDirection: "column", gap: 6 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {/* analog structure with the swap atoms ringed */}
        <Mol2DThumb apiBase={apiBase} smiles={a.smiles} w={62} h={50}
          accent={a.improved ? ACT.fg : VIO.fg} highlight={a.swap_atoms?.analog}
          onClick={onApply} title={a.smiles} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
            <span style={{ fontSize: 10.5, fontWeight: 700, color: "var(--lys-text)",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
              {a.transformation}
            </span>
            {a.clean ? (
              <span title="adds no new structural-alert liability"
                style={{ display: "inline-flex", alignItems: "center", gap: 2,
                  fontSize: 7.5, fontWeight: 700, color: ACT.fg,
                  fontFamily: "var(--lys-font-mono)" }}>
                <ShieldCheck size={9} /> clean
              </span>
            ) : null}
            {(a.new_alerts ?? []).map((al) => (
              <span key={al.name} title={al.note}
                style={{ display: "inline-flex", alignItems: "center", gap: 2,
                  fontSize: 7.5, fontWeight: 700, color: "#b45309",
                  background: "rgba(245,158,11,0.13)", borderRadius: 3,
                  padding: "1px 4px", fontFamily: "var(--lys-font-mono)" }}>
                <AlertTriangle size={9} /> {al.name}
              </span>
            ))}
          </div>
          <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)", textTransform: "uppercase",
            letterSpacing: "0.03em", marginTop: 1 }}>{a.axis}</div>
        </div>
        {/* engine score deltas */}
        <div style={{ display: "flex", gap: 8, flexShrink: 0,
          fontFamily: "var(--lys-font-mono)" }}>
          <Delta label="comp" d={a.delta_composite} goodUp />
          <Delta label="act" d={a.delta_activity} goodUp />
          <Delta label="SA" d={a.delta_sa} goodUp={false} />
        </div>
        <button type="button" onClick={onApply}
          style={{ flexShrink: 0, padding: "4px 10px", borderRadius: 5,
            border: `1px solid ${a.improved ? ACT.border : VIO.border}`,
            background: a.improved ? ACT.fg : "transparent",
            color: a.improved ? "white" : VIO.fg,
            fontSize: 9.5, fontWeight: 700, cursor: "pointer" }}>
          apply
        </button>
      </div>
      {/* full physicochemical delta strip */}
      {a.delta_props && (
        <PropDeltaStrip deltas={a.delta_props} meta={descMeta} keys={descKeys} />
      )}
    </div>
  );
}

/** Horizontal strip of per-property deltas — the whole point of an MMP:
 *  see how EVERY property moved, green/red by whether the move is favourable. */
function PropDeltaStrip({ deltas, meta, keys }: {
  deltas: Record<string, number>; meta: Record<string, DescMeta>; keys: string[];
}) {
  return (
    <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
      {keys.map((k) => {
        const d = deltas[k];
        if (d === undefined) return null;
        const m = meta[k] || { label: k, is_int: false, good: "neutral" as const };
        const good = m.good === "down" ? d < 0 : m.good === "up" ? d > 0 : null;
        const col = d === 0 ? "var(--lys-text-faint)"
          : good === null ? "#64748b" : good ? "#16a34a" : "#dc2626";
        const frac = Math.min(1, Math.abs(d) / (PROP_NORM[k] || 1));
        return (
          <div key={k} title={`${m.label} Δ ${fmtPropDelta(d, m.is_int, k)}`}
            style={{ flex: "1 1 36px", minWidth: 34, display: "flex",
              flexDirection: "column", alignItems: "center", gap: 1,
              padding: "2px 1px", borderRadius: 4,
              background: d === 0 ? "transparent" : "rgba(0,0,0,0.02)" }}>
            <span style={{ fontSize: 7, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", letterSpacing: "-0.02em" }}>{m.label}</span>
            <span style={{ fontSize: 9, fontWeight: 700, color: col,
              fontFamily: "var(--lys-font-mono)" }}>
              {fmtPropDelta(d, m.is_int, k)}</span>
            <div style={{ width: "82%", height: 3, borderRadius: 2,
              background: "rgba(0,0,0,0.06)", overflow: "hidden" }}>
              <div style={{ width: `${Math.round(frac * 100)}%`, height: "100%",
                background: col === "var(--lys-text-faint)" ? "transparent" : col }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Compact one-line parent physchem profile shown in the summary header. */
function ParentProfile({ desc, keys, meta }: {
  desc: Record<string, number>; keys: string[]; meta: Record<string, DescMeta>;
}) {
  const show = keys.filter((k) => k in desc).slice(0, 7);
  return (
    <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 3 }}>
      {show.map((k) => {
        const m = meta[k] || { label: k, is_int: false, good: "neutral" as const };
        const v = desc[k];
        return (
          <span key={k} style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-dim)" }}>
            <span style={{ color: "var(--lys-text-faint)" }}>{m.label} </span>
            {m.is_int ? Math.round(v) : v}
          </span>
        );
      })}
    </div>
  );
}

function Delta({ label, d, goodUp }: { label: string; d: number | null; goodUp: boolean }) {
  const col = deltaColor(d, goodUp);
  return (
    <div style={{ textAlign: "center", minWidth: 32 }}>
      <div style={{ fontSize: 7, color: "var(--lys-text-faint)",
        textTransform: "uppercase" }}>{label}</div>
      <div style={{ fontSize: 10, fontWeight: 700, color: col }}>{fmtDelta(d)}</div>
    </div>
  );
}

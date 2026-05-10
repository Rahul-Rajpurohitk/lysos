import { useEffect, useState } from "react";

interface DeepExplain {
  rdkit_properties?: {
    valid: boolean; formula?: string; mw?: number; logp?: number;
    hba?: number; hbd?: number; tpsa?: number; rotatable_bonds?: number;
    rings?: number; aromatic_rings?: number; fsp3?: number;
    n_heavy_atoms?: number; n_stereo_centers?: number; qed?: number;
    bertz_complexity?: number;
  };
  rules?: Record<string, { pass: boolean; n_violations: number; violations: string[] }>;
  axis_reasoning?: Record<string, { explanation: string; improvement: string; predicted_delta: number }>;
}

function useDeepExplain(apiBase?: string, smiles?: string | null, pathogen?: string):
  [DeepExplain | null, (v: DeepExplain | null) => void] {
  const [deep, setDeep] = useState<DeepExplain | null>(null);
  useEffect(() => {
    if (!apiBase || !smiles) { setDeep(null); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/score-explain`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ smiles, target_pathogen: pathogen ?? "MRSA" }),
        });
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setDeep(d);
      } catch {/*noop*/}
    }, 600);
    return () => { cancelled = true; clearTimeout(t); };
  }, [apiBase, smiles, pathogen]);
  return [deep, setDeep];
}

/**
 * ScoreBreakdownCard — full 12-axis reward decomposition.
 *
 * Renders the same 12 axes the agent loop scores against, with
 * weighted bars showing each axis's contribution to the composite.
 * Sorted by contribution (weight × value) descending so the user
 * sees the BIGGEST levers first.
 *
 * Colors:
 *   green = strong (>0.7)
 *   amber = moderate (0.4-0.7)
 *   red   = weak (<0.4)
 *
 * Each row: axis label · weight · value bar · weighted contribution
 *
 * Below: composite total + delta-vs-best if best scores provided.
 */

interface Props {
  scores: Record<string, number>;
  weights: Record<string, number>;
  best?: Record<string, number>;
  composite?: number;
  /** Optional context for the deep-explain panel — when set, the card
   *  fetches /workbench/score-explain and renders RDKit properties +
   *  per-axis Gemini reasoning + rule compliance. */
  apiBase?: string;
  smiles?: string | null;
  pathogen?: string;
}

const AXIS_LABEL: Record<string, string> = {
  validity:               "validity",
  structural_alerts:      "structural alerts",
  predicted_mic:          "predicted MIC",
  drug_likeness_qed:      "drug-likeness (QED)",
  synthesizability:       "synthesizability",
  hemolysis_safety:       "hemolysis safety",
  novelty:                "novelty",
  embedding_novelty:      "embedding novelty",
  boltz2_pose_conf:       "boltz2 pose conf.",
  spectrum_breadth:       "spectrum breadth",
  resistance_robustness:  "resistance robustness",
  pareto_entry:           "pareto entry",
};

const AXIS_TOOLTIP: Record<string, string> = {
  validity:               "RDKit valency / sanity. 0 = unparseable.",
  structural_alerts:      "PAINS + toxicophore SMARTS hit count. 1 = clean.",
  predicted_mic:          "ChemProp regressor on pathogen-specific bioactivity.",
  drug_likeness_qed:      "Bickerton QED, normalized to [0,1]. >0.67 ≈ drug-like.",
  synthesizability:       "Inverse SAscore. 1 = trivial, 0 = very hard.",
  hemolysis_safety:       "Predicted RBC lysis. 1 = no toxicity.",
  novelty:                "Tanimoto distance to nearest known antibiotic.",
  embedding_novelty:      "Cosine novelty in MolFormer latent space.",
  boltz2_pose_conf:       "Boltz2 docking pose pLDDT.",
  spectrum_breadth:       "Predicted activity across pathogen panel.",
  resistance_robustness:  "Predicted resilience to common resistance mechanisms.",
  pareto_entry:           "Position on Pareto front of all-axis tradeoffs.",
};

// Honesty stamps — be explicit about which axes are real, which are
// proxies, which are stubs. Better than fake authoritativeness.
//   real  = computed from real data, no estimation
//   proxy = approximation; indicative but not validated
//   stub  = placeholder when source data unavailable
const AXIS_STATUS: Record<string, "real" | "proxy" | "stub"> = {
  validity:               "real",   // RDKit parse
  structural_alerts:      "real",   // RDKit FILTER (PAINS / tox)
  predicted_mic:          "proxy",  // XGBoost on small dataset
  drug_likeness_qed:      "real",   // Bickerton 2012
  synthesizability:       "real",   // Ertl 2009 SAscore
  hemolysis_safety:       "proxy",  // structural-alert based, unvalidated
  novelty:                "real",   // Tanimoto Morgan-2 vs 30+ knowns
  embedding_novelty:      "real",   // Gemini 3072d cosine
  boltz2_pose_conf:       "stub",   // cache-empty for novel SMILES
  spectrum_breadth:       "stub",   // not yet implemented
  resistance_robustness:  "proxy",  // Service 2 backs this when pdb_id available
  pareto_entry:           "real",   // Service 3 (live frontier computation)
};

const STATUS_BADGES = {
  real:  { color: "#10b981", label: "real",  dot: "🟢" },
  proxy: { color: "#ca8a04", label: "proxy", dot: "🟡" },
  stub:  { color: "#dc2626", label: "stub",  dot: "🔴" },
} as const;

function colorFor(v: number): string {
  if (v >= 0.7) return "#10b981";
  if (v >= 0.4) return "#d97706";
  return "#dc2626";
}

export function ScoreBreakdownCard({ scores, weights, best, composite, apiBase, smiles, pathogen }: Props) {
  // Deep explain state — fetched lazily when the user opens the panel.
  const [deep, setDeep] = useDeepExplain(apiBase, smiles, pathogen);
  void setDeep;
  const axes = Object.keys(weights);
  const enriched = axes.map((axis) => {
    const v = scores[axis] ?? 0;
    const w = weights[axis] ?? 0;
    const b = best?.[axis];
    return {
      axis,
      label: AXIS_LABEL[axis] ?? axis,
      tip: AXIS_TOOLTIP[axis] ?? "",
      value: v,
      weight: w,
      contribution: v * w,
      best: b,
      delta: b !== undefined ? v - b : undefined,
    };
  });
  enriched.sort((a, b) => b.contribution - a.contribution);

  const total = enriched.reduce((s, e) => s + e.contribution, 0);
  const compositeShown = composite ?? total;

  const hasScores = Object.keys(scores).length > 0;

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      <div style={{
        padding: "5px 10px",
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.06em",
        textTransform: "uppercase",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <span style={{ width: 11, height: 11, borderRadius: 2,
          background: hasScores ? colorFor(compositeShown) : "#9ca3af" }} />
        <span>score breakdown · 12 axes</span>
        <span style={{ flex: 1 }} />
        {hasScores && (
          <span style={{ fontSize: 11, fontWeight: 700,
            color: colorFor(compositeShown), fontFamily: "var(--lys-font-mono)" }}>
            {compositeShown.toFixed(3)}
          </span>
        )}
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: "6px 8px" }}>
        {!hasScores && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            no scores yet · run /score or /design
          </div>
        )}
        {hasScores && enriched.map((e) => {
          const c = colorFor(e.value);
          const status = AXIS_STATUS[e.axis] ?? "proxy";
          const badge = STATUS_BADGES[status];
          return (
            <div key={e.axis} title={`${e.tip}\n\nstatus: ${badge.label.toUpperCase()} — ${
              status === "real" ? "computed from real data, no estimation" :
              status === "proxy" ? "approximation; indicative but not externally validated" :
              "placeholder when source data unavailable; treat as no signal"
            }`}
              style={{ padding: "3px 0", display: "flex", flexDirection: "column", gap: 2 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6,
                fontSize: 10, fontFamily: "var(--lys-font-mono)" }}>
                <span title={`${badge.label} — see tooltip on row for explanation`}
                  style={{
                    width: 7, height: 7, borderRadius: 7,
                    background: badge.color, flexShrink: 0,
                  }} />
                <span style={{ flex: 1, color: "var(--lys-text)",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {e.label}
                </span>
                <span style={{ fontSize: 8, color: badge.color, fontWeight: 700,
                  letterSpacing: "0.04em", textTransform: "uppercase" }}>
                  {badge.label}
                </span>
                <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)" }}>
                  w={e.weight.toFixed(2)}
                </span>
                <span style={{ fontWeight: 700, color: c, minWidth: 36, textAlign: "right" }}>
                  {e.value.toFixed(3)}
                </span>
                {e.delta !== undefined && (
                  <span style={{
                    fontSize: 8.5, fontWeight: 700,
                    color: e.delta >= 0 ? "#10b981" : "#dc2626",
                    minWidth: 38, textAlign: "right",
                  }}>
                    {e.delta >= 0 ? "+" : ""}{e.delta.toFixed(2)}
                  </span>
                )}
              </div>
              <div style={{ display: "flex", gap: 2, alignItems: "center" }}>
                {/* Value bar (foreground = current, dim = remaining) */}
                <div style={{ flex: 1, height: 4, borderRadius: 2,
                  background: "var(--lys-border-faint, rgba(0,0,0,0.05))",
                  overflow: "hidden", position: "relative" }}>
                  <div style={{
                    position: "absolute", inset: 0,
                    width: `${Math.max(0, Math.min(1, e.value)) * 100}%`,
                    background: c,
                    transition: "width 200ms ease",
                  }} />
                  {/* Best marker */}
                  {e.best !== undefined && (
                    <div style={{
                      position: "absolute", top: -1, bottom: -1,
                      left: `${Math.max(0, Math.min(1, e.best)) * 100}%`,
                      width: 1, background: "var(--lys-text)",
                      opacity: 0.5,
                    }} />
                  )}
                </div>
                {/* Weighted contribution */}
                <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
                  fontFamily: "var(--lys-font-mono)", minWidth: 36, textAlign: "right" }}>
                  +{e.contribution.toFixed(3)}
                </div>
              </div>
              {/* Per-axis Gemini reasoning + improvement suggestion */}
              {(() => {
                const reason = deep?.axis_reasoning?.[e.axis];
                if (!reason) return null;
                return (
                  <div style={{
                    marginTop: 4, padding: "5px 8px",
                    background: "rgba(124,99,216,0.05)",
                    border: "1px solid rgba(124,99,216,0.18)",
                    borderLeft: "2px solid #6041d0",
                    borderRadius: 3, fontSize: 9.5, lineHeight: 1.45,
                    fontFamily: "var(--lys-font-body)",
                  }}>
                    <div style={{ color: "var(--lys-text-dim)", marginBottom: 3 }}>
                      <strong style={{ color: "#6041d0", fontFamily: "var(--lys-font-mono)",
                        fontSize: 8.5, letterSpacing: "0.04em", textTransform: "uppercase",
                        marginRight: 5 }}>why</strong>
                      {reason.explanation}
                    </div>
                    {reason.improvement && (
                      <div style={{ color: "var(--lys-text-dim)" }}>
                        <strong style={{ color: "#10b981", fontFamily: "var(--lys-font-mono)",
                          fontSize: 8.5, letterSpacing: "0.04em", textTransform: "uppercase",
                          marginRight: 5 }}>improve</strong>
                        {reason.improvement}
                        {reason.predicted_delta > 0 && (
                          <span style={{
                            marginLeft: 6, padding: "0 5px", borderRadius: 3,
                            background: "rgba(16,185,129,0.12)",
                            color: "#10b981", fontFamily: "var(--lys-font-mono)",
                            fontSize: 8.5, fontWeight: 700,
                          }}>+{reason.predicted_delta.toFixed(2)}</span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          );
        })}

        {/* RDKit-derived properties strip — concrete molecular numbers */}
        {hasScores && deep?.rdkit_properties?.valid && (
          <div style={{
            marginTop: 10, padding: "6px 9px",
            background: "rgba(0,0,0,0.025)",
            border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
            borderRadius: 4,
          }}>
            <div style={{
              fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-faint)", letterSpacing: "0.06em",
              textTransform: "uppercase", fontWeight: 700, marginBottom: 4,
            }}>RDKit · molecular properties</div>
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
              gap: 4, fontSize: 9, fontFamily: "var(--lys-font-mono)",
            }}>
              {[
                ["formula", deep.rdkit_properties.formula],
                ["MW", deep.rdkit_properties.mw],
                ["LogP", deep.rdkit_properties.logp],
                ["TPSA", deep.rdkit_properties.tpsa],
                ["HBA", deep.rdkit_properties.hba],
                ["HBD", deep.rdkit_properties.hbd],
                ["rot", deep.rdkit_properties.rotatable_bonds],
                ["rings", deep.rdkit_properties.rings],
                ["arom", deep.rdkit_properties.aromatic_rings],
                ["fsp3", deep.rdkit_properties.fsp3],
                ["heavy", deep.rdkit_properties.n_heavy_atoms],
                ["QED", deep.rdkit_properties.qed],
              ].map(([k, v]) => (
                <div key={String(k)} style={{
                  display: "flex", justifyContent: "space-between",
                  padding: "1px 4px",
                }}>
                  <span style={{ color: "var(--lys-text-faint)" }}>{k}</span>
                  <span style={{ color: "var(--lys-text)", fontWeight: 700 }}>{String(v ?? "—")}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Rule compliance badges — Lipinski/Veber/Egan/Ghose */}
        {hasScores && deep?.rules && (
          <div style={{
            marginTop: 6,
            display: "flex", flexWrap: "wrap", gap: 4,
          }}>
            {(["lipinski", "veber", "egan", "ghose"] as const).map((rule) => {
              const r = deep.rules?.[rule];
              if (!r) return null;
              const ok = r.pass;
              return (
                <span key={rule}
                  title={r.violations?.length ? r.violations.join(" · ") : "all checks pass"}
                  style={{
                    padding: "1px 7px", borderRadius: 3, fontSize: 9,
                    fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                    background: ok ? "rgba(16,185,129,0.10)" : "rgba(220,38,38,0.10)",
                    color: ok ? "#059669" : "#dc2626",
                    border: `1px solid ${ok ? "rgba(16,185,129,0.30)" : "rgba(220,38,38,0.30)"}`,
                  }}>
                  {ok ? "✓" : "✗"} {rule}{r.n_violations > 0 ? ` (${r.n_violations})` : ""}
                </span>
              );
            })}
          </div>
        )}

        {hasScores && (
          <div style={{
            marginTop: 8, padding: "5px 8px", borderRadius: 4,
            background: `${colorFor(compositeShown)}10`,
            borderLeft: `3px solid ${colorFor(compositeShown)}`,
            display: "flex", alignItems: "center",
            fontFamily: "var(--lys-font-mono)",
          }}>
            <span style={{ flex: 1, fontSize: 10, color: "var(--lys-text)",
              fontWeight: 600 }}>composite (Σ wᵢ·sᵢ)</span>
            <span style={{ fontSize: 14, fontWeight: 700,
              color: colorFor(compositeShown) }}>
              {compositeShown.toFixed(3)}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

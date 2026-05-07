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

export function ScoreBreakdownCard({ scores, weights, best, composite }: Props) {
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
            </div>
          );
        })}

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

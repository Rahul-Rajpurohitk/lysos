/**
 * ChampionCard — A/B comparison vs the reigning per-pathogen champion.
 *
 * Three modes by `mode` field on data:
 *   - "show":    Display reigning champion (single column)
 *   - "compare": Side-by-side champion vs candidate with axis Δ bars
 *   - "promote": Promotion notification (winner just dethroned the prior)
 *
 * Used by:
 *   - /champion slash command
 *   - workflow.done auto-promotion event
 *   - Knowledge tab champion pane (KnowledgeHubCard)
 */
import React, { useEffect, useRef } from "react";
import { motion } from "framer-motion";

interface ChampionRecord {
  pathogen: string;
  smiles: string;
  composite: number | null;
  robustness: number | null;
  fitness: number | null;
  scores?: Record<string, number>;
  rationale?: string;
  created_ts?: number;
}

interface ABCompare {
  pathogen: string;
  champion: ChampionRecord | null;
  candidate: { smiles: string; composite: number; robustness: number; fitness: number; scores?: Record<string, number> };
  deltas?: { composite: number; robustness: number; fitness: number };
  axis_deltas?: Record<string, number>;
  verdict: string;
}

interface PromotionData {
  promoted: boolean;
  current: ChampionRecord | null;
  new: ChampionRecord;
  score_axis: string;
  delta_fitness?: number;
  reason?: string;
}

interface Props {
  msg: {
    data: {
      mode: "show" | "compare" | "promote";
      champion?: ChampionRecord | null;
      ab?: ABCompare;
      promotion?: PromotionData;
      pathogen?: string;
    };
  };
  onLoadSmiles?: (smiles: string) => void;
}

const fmt = (v: number | null | undefined, d = 3) =>
  v == null || isNaN(v) ? "—" : v.toFixed(d);

const SmilesPill: React.FC<{ smiles: string; onLoad?: (s: string) => void; muted?: boolean }> = ({
  smiles, onLoad, muted,
}) => (
  <button
    onClick={() => onLoad?.(smiles)}
    title={`Click to load: ${smiles}`}
    style={{
      fontFamily: "JetBrains Mono, monospace",
      fontSize: 11,
      padding: "3px 7px",
      background: muted ? "rgba(255,255,255,0.04)" : "rgba(132, 88, 255, 0.12)",
      border: `1px solid ${muted ? "rgba(255,255,255,0.10)" : "rgba(132, 88, 255, 0.35)"}`,
      borderRadius: 4,
      color: muted ? "#a8b5ce" : "#c2adff",
      maxWidth: "100%",
      overflow: "hidden",
      textOverflow: "ellipsis",
      whiteSpace: "nowrap",
      textAlign: "left",
      cursor: "pointer",
    }}
  >
    {smiles.length > 48 ? smiles.slice(0, 47) + "…" : smiles}
  </button>
);

const DeltaBar: React.FC<{ label: string; champion: number; candidate: number; delta: number; max?: number }> = ({
  label, champion, candidate, delta, max = 1,
}) => {
  const pctChamp = Math.max(0, Math.min(1, (champion || 0) / max)) * 100;
  const pctCand = Math.max(0, Math.min(1, (candidate || 0) / max)) * 100;
  const deltaColor = delta > 0.001 ? "#39e08e" : delta < -0.001 ? "#ff7e7e" : "#9aa3b8";
  const deltaSign = delta > 0 ? "+" : "";
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "#9aa3b8", marginBottom: 3 }}>
        <span style={{ textTransform: "uppercase", letterSpacing: 0.5, fontWeight: 600 }}>{label}</span>
        <span style={{ color: deltaColor, fontFamily: "JetBrains Mono, monospace", fontWeight: 700 }}>
          Δ {deltaSign}{fmt(delta)}
        </span>
      </div>
      {/* champion track */}
      <div style={{ height: 6, background: "rgba(255,255,255,0.04)", borderRadius: 3, overflow: "hidden", marginBottom: 2 }}>
        <div style={{ width: `${pctChamp}%`, height: "100%", background: "rgba(255,255,255,0.30)" }} />
      </div>
      {/* candidate track */}
      <div style={{ height: 6, background: "rgba(255,255,255,0.04)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{
          width: `${pctCand}%`, height: "100%",
          background: delta >= 0
            ? "linear-gradient(90deg, #5d8aff, #39e08e)"
            : "linear-gradient(90deg, #ff7e7e, #d76b6b)",
        }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 9, color: "#6e7891", marginTop: 2 }}>
        <span>champ {fmt(champion)}</span>
        <span>cand {fmt(candidate)}</span>
      </div>
    </div>
  );
};

const ChampionPanel: React.FC<{ rec: ChampionRecord; onLoad?: (s: string) => void }> = ({ rec, onLoad }) => (
  <div style={{
    padding: 12, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 6,
  }}>
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
      <span style={{ fontSize: 14 }}>🏆</span>
      <span style={{ fontSize: 11, fontWeight: 700, color: "#ffd166", textTransform: "uppercase", letterSpacing: 1 }}>
        Reigning · {rec.pathogen}
      </span>
    </div>
    <SmilesPill smiles={rec.smiles} onLoad={onLoad} />
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 10 }}>
      <Stat label="Composite" value={fmt(rec.composite)} />
      <Stat label="Robustness" value={fmt(rec.robustness)} />
      <Stat label="Fitness" value={fmt(rec.fitness)} accent />
    </div>
    {rec.rationale && (
      <div style={{ fontSize: 10, color: "#9aa3b8", marginTop: 8, fontStyle: "italic" }}>
        {rec.rationale}
      </div>
    )}
  </div>
);

const Stat: React.FC<{ label: string; value: string; accent?: boolean }> = ({ label, value, accent }) => (
  <div>
    <div style={{ fontSize: 9, color: "#6e7891", textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 2 }}>
      {label}
    </div>
    <div style={{
      fontFamily: "JetBrains Mono, monospace",
      fontSize: 14,
      fontWeight: 700,
      color: accent ? "#39e08e" : "#e6ecff",
    }}>
      {value}
    </div>
  </div>
);

const ChampionCard: React.FC<Props> = ({ msg, onLoadSmiles }) => {
  const data = msg.data;

  // Auto-load the champion's SMILES into the 2D + 3D canvas when this
  // card first mounts. Fixes user-reported "I asked to show the best
  // component but nothing appeared in the visuals" — they had to click
  // the SMILES pill manually before, easy to miss. Now the visuals
  // light up the moment /champion runs.
  const autoLoadedRef = useRef<string | null>(null);
  useEffect(() => {
    if (!onLoadSmiles) return;
    let smi: string | undefined;
    if (data.mode === "show" && data.champion?.smiles) smi = data.champion.smiles;
    else if (data.mode === "compare" && data.ab?.champion?.smiles) smi = data.ab.champion.smiles;
    else if (data.mode === "promote" && data.promotion?.new?.smiles) smi = data.promotion.new.smiles;
    if (smi && autoLoadedRef.current !== smi) {
      autoLoadedRef.current = smi;
      onLoadSmiles(smi);
    }
  }, [data, onLoadSmiles]);

  if (data.mode === "show") {
    const c = data.champion;
    if (!c) {
      return (
        <div style={{
          padding: 12, background: "rgba(255,255,255,0.02)", border: "1px dashed rgba(255,255,255,0.10)",
          borderRadius: 6, fontSize: 11, color: "#9aa3b8",
        }}>
          No champion crowned yet for {data.pathogen ?? "this pathogen"}. Run a workflow to crown one.
        </div>
      );
    }
    return (
      <motion.div initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.2 }}>
        <ChampionPanel rec={c} onLoad={onLoadSmiles} />
      </motion.div>
    );
  }

  if (data.mode === "promote" && data.promotion) {
    const p = data.promotion;
    if (!p.promoted) {
      return (
        <div style={{
          padding: 10, background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 6, fontSize: 11, color: "#9aa3b8",
        }}>
          🥈 Candidate did not dethrone the reigning champion · {p.reason ?? "score didn't beat current"}.
        </div>
      );
    }
    return (
      <motion.div
        initial={{ opacity: 0, scale: 0.98 }}
        animate={{ opacity: 1, scale: 1 }}
        transition={{ duration: 0.25 }}
        style={{
          padding: 12,
          background: "linear-gradient(135deg, rgba(255, 209, 102, 0.10), rgba(132, 88, 255, 0.06))",
          border: "1px solid rgba(255, 209, 102, 0.35)",
          borderRadius: 6,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
          <span style={{ fontSize: 16 }}>🏆</span>
          <span style={{ fontSize: 12, fontWeight: 700, color: "#ffd166" }}>
            New {p.new.pathogen} champion crowned
          </span>
          {p.delta_fitness != null && (
            <span style={{
              marginLeft: "auto",
              fontFamily: "JetBrains Mono, monospace", fontSize: 11,
              color: "#39e08e", fontWeight: 700,
            }}>
              Δ fitness +{fmt(p.delta_fitness)}
            </span>
          )}
        </div>
        <SmilesPill smiles={p.new.smiles} onLoad={onLoadSmiles} />
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginTop: 10 }}>
          <Stat label="Composite" value={fmt(p.new.composite)} />
          <Stat label="Robustness" value={fmt(p.new.robustness)} />
          <Stat label="Fitness" value={fmt(p.new.fitness)} accent />
        </div>
        {p.current && (
          <div style={{
            marginTop: 10, paddingTop: 8, borderTop: "1px solid rgba(255,255,255,0.06)",
            fontSize: 10, color: "#9aa3b8",
          }}>
            <span style={{ marginRight: 6 }}>Dethroned:</span>
            <code style={{ fontSize: 10, color: "#a8b5ce" }}>
              {p.current.smiles.slice(0, 40)}{p.current.smiles.length > 40 ? "…" : ""}
            </code>
            <span style={{ marginLeft: 6 }}>(fitness {fmt(p.current.fitness)})</span>
          </div>
        )}
      </motion.div>
    );
  }

  if (data.mode === "compare" && data.ab) {
    const ab = data.ab;
    if (!ab.champion) {
      return (
        <div style={{
          padding: 12, background: "rgba(255,255,255,0.02)", border: "1px dashed rgba(255,255,255,0.10)",
          borderRadius: 6,
        }}>
          <div style={{ fontSize: 11, color: "#9aa3b8", marginBottom: 6 }}>
            No reigning champion for {ab.pathogen} yet — your candidate would crown.
          </div>
          <SmilesPill smiles={ab.candidate.smiles} onLoad={onLoadSmiles} />
        </div>
      );
    }
    const d = ab.deltas ?? { composite: 0, robustness: 0, fitness: 0 };
    return (
      <motion.div
        initial={{ opacity: 0, y: 4 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.2 }}
        style={{
          padding: 12,
          background: "rgba(255,255,255,0.02)",
          border: "1px solid rgba(255,255,255,0.08)",
          borderRadius: 6,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 10 }}>
          <span style={{ fontSize: 14 }}>⚔️</span>
          <span style={{
            fontSize: 11, fontWeight: 700, color: "#c2adff",
            textTransform: "uppercase", letterSpacing: 1,
          }}>
            A/B vs {ab.pathogen} champion
          </span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 9, color: "#ffd166", textTransform: "uppercase", letterSpacing: 1, marginBottom: 4, fontWeight: 700 }}>
              🏆 Champion
            </div>
            <SmilesPill smiles={ab.champion.smiles} onLoad={onLoadSmiles} muted />
          </div>
          <div>
            <div style={{ fontSize: 9, color: "#5d8aff", textTransform: "uppercase", letterSpacing: 1, marginBottom: 4, fontWeight: 700 }}>
              🆕 Candidate
            </div>
            <SmilesPill smiles={ab.candidate.smiles} onLoad={onLoadSmiles} />
          </div>
        </div>
        <div>
          <DeltaBar label="Composite"  champion={ab.champion.composite ?? 0}  candidate={ab.candidate.composite}  delta={d.composite} />
          <DeltaBar label="Robustness" champion={ab.champion.robustness ?? 0} candidate={ab.candidate.robustness} delta={d.robustness} />
          <DeltaBar label="Fitness"    champion={ab.champion.fitness ?? 0}    candidate={ab.candidate.fitness}    delta={d.fitness} />
        </div>
        {ab.axis_deltas && Object.keys(ab.axis_deltas).length > 0 && (
          <div style={{ marginTop: 8, paddingTop: 8, borderTop: "1px solid rgba(255,255,255,0.06)" }}>
            <div style={{ fontSize: 9, color: "#6e7891", textTransform: "uppercase", letterSpacing: 0.6, marginBottom: 4, fontWeight: 600 }}>
              Per-axis deltas
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {Object.entries(ab.axis_deltas).map(([k, v]) => (
                <span key={k} style={{
                  fontSize: 10, padding: "2px 6px", borderRadius: 3,
                  fontFamily: "JetBrains Mono, monospace",
                  background: v > 0 ? "rgba(57, 224, 142, 0.10)" : v < 0 ? "rgba(255, 126, 126, 0.10)" : "rgba(255,255,255,0.04)",
                  color: v > 0 ? "#39e08e" : v < 0 ? "#ff7e7e" : "#9aa3b8",
                  border: `1px solid ${v > 0 ? "rgba(57, 224, 142, 0.25)" : v < 0 ? "rgba(255, 126, 126, 0.25)" : "rgba(255,255,255,0.08)"}`,
                }}>
                  {k} {v > 0 ? "+" : ""}{fmt(v)}
                </span>
              ))}
            </div>
          </div>
        )}
        <div style={{
          marginTop: 10, padding: "6px 10px",
          background: d.fitness > 0 ? "rgba(57, 224, 142, 0.08)" : d.fitness < 0 ? "rgba(255, 126, 126, 0.08)" : "rgba(255,255,255,0.04)",
          border: `1px solid ${d.fitness > 0 ? "rgba(57, 224, 142, 0.30)" : d.fitness < 0 ? "rgba(255, 126, 126, 0.30)" : "rgba(255,255,255,0.08)"}`,
          borderRadius: 4, fontSize: 11,
          color: d.fitness > 0 ? "#39e08e" : d.fitness < 0 ? "#ff7e7e" : "#9aa3b8",
          fontWeight: 600,
        }}>
          {ab.verdict}
        </div>
      </motion.div>
    );
  }

  return null;
};

export default ChampionCard;

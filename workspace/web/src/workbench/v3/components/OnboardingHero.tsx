/**
 * OnboardingHero — compact, borderless, non-scrollable on first paint.
 *
 * Design intent:
 *  - No top "AMD Hackathon" badge (per user feedback, dead weight)
 *  - Title pushed up; description tightened; cards laid out 2-col with
 *    real labelling (full pathogen name, WHO tier badge, mech of action,
 *    drug-count + resistance-count in human-readable form)
 *  - Borderless cards, hover = soft accent-tint bg
 *  - Feature row at bottom, 4 cols, no borders, no boxes
 *  - Whole hero fits without scroll on a 600px chat panel
 */
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Brain, Target, FlaskConical, Microscope } from "lucide-react";

interface OnboardingHeroProps {
  apiBase: string;
  onPickPathogen: (code: string) => void;
}

interface PathogenSummary {
  code: string;
  name: string;
  resistance_count: number;
  first_line_count: number;
}

const TIER_ORDER = ["MRSA", "Mtb", "EColi-CRE", "KpneuCRE", "Abaum", "Paer", "VRE", "NGono"];

interface PathogenMeta {
  fullName: string;       // human-readable pathogen name
  mech: string;            // primary resistance mechanism / target
  whoTier: "CRITICAL" | "HIGH";
}

const PATHOGEN_META: Record<string, PathogenMeta> = {
  "MRSA":      { fullName: "Methicillin-resistant S. aureus",  mech: "mecA · PBP2a",        whoTier: "HIGH" },
  "Mtb":       { fullName: "M. tuberculosis (MDR)",            mech: "rpoB · katG",          whoTier: "CRITICAL" },
  "EColi-CRE": { fullName: "Carbapenem-resistant E. coli",     mech: "KPC · NDM · OXA-48",   whoTier: "CRITICAL" },
  "KpneuCRE":  { fullName: "Carbapenem-resistant K. pneumoniae", mech: "KPC producers",      whoTier: "CRITICAL" },
  "Abaum":     { fullName: "A. baumannii (carbapenem-R)",      mech: "OXA-23 · OXA-24/58",   whoTier: "CRITICAL" },
  "Paer":      { fullName: "P. aeruginosa (MDR)",              mech: "mexAB-oprM · AmpC",   whoTier: "CRITICAL" },
  "VRE":       { fullName: "Vancomycin-resistant E. faecium",  mech: "vanA · vanB",          whoTier: "HIGH" },
  "NGono":     { fullName: "Drug-resistant N. gonorrhoeae",    mech: "penA · 23S rRNA",      whoTier: "HIGH" },
};

const FEATURES = [
  { icon: <Brain size={13} />, title: "Multi-agent debate", body: "Designer · Critic · Editor · Strategist + 9 sub-agents." },
  { icon: <FlaskConical size={13} />, title: "12-component reward", body: "MIC · QED · SAscore · hemolysis · novelty · pose · spectrum." },
  { icon: <Microscope size={13} />, title: "Drag-edit chemistry", body: "Click an atom; pose recomputes, radar live-updates." },
  { icon: <Target size={13} />, title: "MI300X-trained policy", body: "Gemma 4 31B · TxGemma → AMR SFT → DPO → GRPO." },
];

export function OnboardingHero({ apiBase, onPickPathogen }: OnboardingHeroProps) {
  const [pathogens, setPathogens] = useState<PathogenSummary[]>([]);

  useEffect(() => {
    fetch(`${apiBase}/workbench/pathogens`)
      .then((r) => r.json())
      .then((d) => setPathogens(d.pathogens || []))
      .catch(() => {});
  }, [apiBase]);

  const sorted = [...pathogens].sort(
    (a, b) => TIER_ORDER.indexOf(a.code) - TIER_ORDER.indexOf(b.code)
  );

  return (
    <div style={{
      width: "100%",
      height: "100%",
      overflow: "hidden",
      padding: "10px 14px 14px",
      display: "flex",
      flexDirection: "column",
      gap: 12,
      background: "radial-gradient(ellipse at top, rgba(16, 185, 129, 0.06), transparent 55%)",
    }}>
      {/* ────────── Title block (no top tag — pushed up) ────────── */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        style={{ textAlign: "center", maxWidth: 580, margin: "0 auto" }}
      >
        <h1 style={{
          fontSize: 21,
          fontWeight: 600,
          letterSpacing: "-0.02em",
          margin: 0,
          marginBottom: 4,
          color: "var(--lys-text)",
          lineHeight: 1.15,
        }}>
          Lysos Workbench
        </h1>
        <p style={{
          fontSize: 11.5,
          color: "var(--lys-text-dim)",
          margin: 0,
          lineHeight: 1.4,
        }}>
          Generative drug design for antimicrobial resistance. Pick a WHO-priority pathogen below to begin.
        </p>
      </motion.div>

      {/* ────────── Pathogen grid: 2-col, borderless, real labels ────────── */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.35, delay: 0.08 }}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 4,
          maxWidth: 760,
          margin: "0 auto",
          width: "100%",
        }}
      >
        {sorted.slice(0, 8).map((p, i) => {
          const meta = PATHOGEN_META[p.code];
          return (
            <motion.button
              key={p.code}
              initial={{ opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.22, delay: 0.08 + i * 0.025 }}
              onClick={() => onPickPathogen(p.code)}
              className="lys-onb-card"
              style={{
                padding: "8px 10px",
                border: 0,
                borderRadius: 8,
                background: "transparent",
                textAlign: "left",
                cursor: "pointer",
                fontFamily: "inherit",
                color: "var(--lys-text)",
                transition: "background 0.12s",
                display: "flex",
                flexDirection: "column",
                gap: 2,
              }}
            >
              {/* Row 1: code + WHO tier pill (justify-between) */}
              <div style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                justifyContent: "space-between",
              }}>
                <span style={{
                  fontSize: 12,
                  fontWeight: 700,
                  color: "var(--lys-accent)",
                  fontFamily: "var(--lys-font-mono)",
                  letterSpacing: "-0.01em",
                }}>{p.code}</span>
                {meta && (
                  <span style={{
                    fontSize: 8.5,
                    fontFamily: "var(--lys-font-mono)",
                    letterSpacing: "0.08em",
                    padding: "1px 5px",
                    borderRadius: 3,
                    background: meta.whoTier === "CRITICAL"
                      ? "rgba(239, 68, 68, 0.10)"
                      : "rgba(245, 158, 11, 0.10)",
                    color: meta.whoTier === "CRITICAL" ? "#b91c1c" : "#92400e",
                    fontWeight: 600,
                  }}>
                    {meta.whoTier}
                  </span>
                )}
              </div>
              {/* Row 2: full pathogen name */}
              <div style={{
                fontSize: 11,
                color: "var(--lys-text)",
                fontWeight: 500,
                lineHeight: 1.3,
              }}>
                {meta?.fullName ?? p.name}
              </div>
              {/* Row 3: mechanism + counts (single line) */}
              <div style={{
                fontSize: 9.5,
                color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)",
                display: "flex",
                gap: 6,
                alignItems: "center",
                flexWrap: "wrap",
              }}>
                <span>{meta?.mech ?? ""}</span>
                <span style={{ opacity: 0.4 }}>·</span>
                <span>{p.resistance_count} resistance</span>
                <span style={{ opacity: 0.4 }}>·</span>
                <span>{p.first_line_count} first-line</span>
              </div>
            </motion.button>
          );
        })}
      </motion.div>

      {/* ────────── Feature row: 4 cols, no boxes, no borders ────────── */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.35, delay: 0.18 }}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
          gap: 12,
          maxWidth: 760,
          margin: "0 auto",
          width: "100%",
          paddingTop: 8,
          borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
        }}
      >
        {FEATURES.map((f) => (
          <div key={f.title} style={{
            display: "flex",
            flexDirection: "column",
            gap: 2,
          }}>
            <div style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              color: "var(--lys-accent)",
            }}>
              {f.icon}
              <span style={{
                fontSize: 11,
                color: "var(--lys-text)",
                fontWeight: 600,
              }}>{f.title}</span>
            </div>
            <p style={{
              fontSize: 10.5,
              color: "var(--lys-text-dim)",
              margin: 0,
              lineHeight: 1.35,
            }}>{f.body}</p>
          </div>
        ))}
      </motion.div>
    </div>
  );
}

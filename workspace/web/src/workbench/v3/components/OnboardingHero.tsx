/**
 * OnboardingHero — feature-led, pathogen-demoted.
 *
 * User direction: lead with the multi-agent / reward / drag-edit / MI300X
 * value props (the "feature thing"), demote the pathogen list to a thin
 * inline pill strip ("pick a pathogen to start").
 *
 * Layout:
 *    title block            — name + tagline
 *    feature cards (2x2)    — borderless, bigger, with copy
 *    pathogen pill strip    — single horizontal row, click to launch
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

const FEATURES = [
  {
    icon: <Brain size={14} />,
    title: "Multi-agent debate",
    body: "Four specialists negotiate every candidate — Designer drafts, Critic challenges, Editor refines, Strategist directs.",
  },
  {
    icon: <FlaskConical size={14} />,
    title: "12-axis live reward",
    body: "Each edit re-scores potency, drug-likeness, toxicity, novelty, pose, and spectrum. The radar updates the moment an atom changes.",
  },
  {
    icon: <Microscope size={14} />,
    title: "Click-to-edit chemistry",
    body: "Mutate any atom on the 3D ligand. The pose recomputes, the agents debate the move, the score shifts.",
  },
  {
    icon: <Target size={14} />,
    title: "Trained on AMD MI300X",
    body: "Gemma 4 31B fine-tuned in four stages: TxGemma supervision → AMR SFT → DPO preferences → GRPO reinforcement on real assays.",
  },
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
      padding: "16px 16px 14px",
      display: "flex",
      flexDirection: "column",
      gap: 16,
      background: "radial-gradient(ellipse at top, rgba(16, 185, 129, 0.07), transparent 55%)",
    }}>
      {/* ────────── Title + tagline ────────── */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        style={{ textAlign: "center", maxWidth: 620, margin: "0 auto" }}
      >
        <h1 style={{
          fontSize: 22,
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
          fontSize: 12,
          color: "var(--lys-text-dim)",
          margin: 0,
          lineHeight: 1.4,
        }}>
          The AI drug-design lab for antimicrobial resistance.
          <span style={{ color: "var(--lys-text-faint)" }}>
            {" "}4 specialist agents · 12-axis reward · MI300X-trained.
          </span>
        </p>
      </motion.div>

      {/* ────────── Feature cards (2×2) — the lead content now ────────── */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, delay: 0.06 }}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 8,
          maxWidth: 760,
          margin: "0 auto",
          width: "100%",
        }}
      >
        {FEATURES.map((f, i) => (
          <motion.div
            key={f.title}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: 0.06 + i * 0.04 }}
            style={{
              padding: "10px 12px",
              borderRadius: 8,
              background: "rgba(16, 185, 129, 0.03)",
              display: "flex",
              flexDirection: "column",
              gap: 4,
              minWidth: 0,
            }}
          >
            <div style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
              color: "var(--lys-accent)",
            }}>
              {f.icon}
              <span style={{
                fontSize: 12,
                color: "var(--lys-text)",
                fontWeight: 600,
                letterSpacing: "-0.005em",
              }}>{f.title}</span>
            </div>
            <p style={{
              fontSize: 11,
              color: "var(--lys-text-dim)",
              margin: 0,
              lineHeight: 1.4,
            }}>{f.body}</p>
          </motion.div>
        ))}
      </motion.div>

      {/* ────────── Pathogen pill strip — single line, demoted ────────── */}
      {sorted.length > 0 && (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.3, delay: 0.22 }}
          style={{
            maxWidth: 760,
            margin: "0 auto",
            width: "100%",
            paddingTop: 10,
            borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <div style={{
            fontSize: 10,
            color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}>
            Pick a pathogen to start
          </div>
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 4,
          }}>
            {sorted.slice(0, 8).map((p) => (
              <button
                key={p.code}
                onClick={() => onPickPathogen(p.code)}
                className="lys-onb-pill"
                style={{
                  padding: "4px 8px",
                  border: 0,
                  borderRadius: 999,
                  background: "rgba(16, 185, 129, 0.08)",
                  color: "var(--lys-accent)",
                  fontFamily: "var(--lys-font-mono)",
                  fontSize: 10.5,
                  fontWeight: 600,
                  cursor: "pointer",
                  transition: "background 0.12s, transform 0.12s",
                  textAlign: "center",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {p.code}
              </button>
            ))}
          </div>
        </motion.div>
      )}
    </div>
  );
}

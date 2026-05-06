import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Brain, Target, Zap, FlaskConical, Microscope } from "lucide-react";

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

const TIER_DESCRIPTIONS: Record<string, string> = {
  MRSA: "methicillin-resistant; mecA / PBP2a target",
  Mtb: "M. tuberculosis; rpoB / katG escape mutations",
  "EColi-CRE": "carbapenem-resistant E. coli; KPC / NDM / OXA-48",
  KpneuCRE: "K. pneumoniae CRE; KPC producers",
  Abaum: "A. baumannii; OXA-23/24/58 carbapenemases",
  Paer: "P. aeruginosa; mexAB-oprM efflux + AmpC",
  VRE: "vancomycin-resistant E. faecium; vanA/vanB",
  NGono: "drug-resistant gonorrhea; penA / mosaic 23S rRNA",
};

const FEATURES = [
  {
    icon: <Brain size={16} />,
    title: "Multi-agent reasoning",
    body: "4 first-class agents (Designer / Critic / Editor / Strategist) + 9 sub-agents debate every candidate.",
  },
  {
    icon: <FlaskConical size={16} />,
    title: "12-component reward stack",
    body: "Each candidate scored on validity, MIC, QED, SAscore, hemolysis, novelty, pose, spectrum, resistance robustness, and Pareto entry.",
  },
  {
    icon: <Microscope size={16} />,
    title: "Drag-edit chemistry",
    body: "Drop functional groups onto atoms; the 3D pose recomputes and reward radar re-renders live.",
  },
  {
    icon: <Target size={16} />,
    title: "AMD MI300X-trained policy",
    body: "Gemma 4 31B base, 4-stage pipeline (TxGemma / AMR SFT / DPO hard-negatives / GRPO RL).",
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
      overflowY: "auto",
      padding: 32,
      display: "flex",
      flexDirection: "column",
      gap: 32,
      background: "radial-gradient(ellipse at top, rgba(16, 185, 129, 0.08), transparent 60%)",
    }}>
      {/* Hero */}
      <motion.div
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.4 }}
        style={{ textAlign: "center", maxWidth: 700, margin: "0 auto" }}
      >
        <div style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          background: "var(--lys-accent-soft)",
          border: "1px solid rgba(16, 185, 129, 0.25)",
          borderRadius: 999,
          fontSize: 9.5,
          color: "#047857",
          fontFamily: "var(--lys-font-mono)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          marginBottom: 10,
        }}>
          <Zap size={9} fill="currentColor" /> AMD Hackathon · May 2026
        </div>
        <h1 style={{
          fontSize: 22,
          fontWeight: 600,
          letterSpacing: "-0.02em",
          margin: 0,
          marginBottom: 6,
          color: "var(--lys-text)",
          lineHeight: 1.15,
        }}>
          Lysos Workbench
        </h1>
        <p style={{
          fontSize: 12.5,
          color: "var(--lys-text-dim)",
          margin: 0,
          marginBottom: 14,
          lineHeight: 1.45,
        }}>
          Generative drug-design for antimicrobial resistance. Pick a WHO-priority
          pathogen, watch 4 agents debate, drag-edit the molecule, and follow
          the reward radar in real time.
        </p>

        <div style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          color: "var(--lys-text-faint)",
          fontSize: 10.5,
          fontFamily: "var(--lys-font-mono)",
        }}>
          <span>start with a pathogen ↓</span>
        </div>
      </motion.div>

      {/* Pathogen cards */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.4, delay: 0.1 }}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
          gap: 12,
          maxWidth: 1100,
          margin: "0 auto",
          width: "100%",
        }}
      >
        {sorted.map((p, i) => (
          <motion.button
            key={p.code}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: 0.1 + i * 0.05 }}
            onClick={() => onPickPathogen(p.code)}
            style={{
              padding: 16,
              border: "1px solid var(--lys-border)",
              borderRadius: 12,
              background: "var(--lys-surface)",
              textAlign: "left",
              cursor: "pointer",
              fontFamily: "inherit",
              color: "var(--lys-text)",
              transition: "border-color 0.15s, transform 0.15s",
            }}
            whileHover={{
              y: -2,
              borderColor: "rgba(16, 185, 129, 0.45)",
              boxShadow: "var(--lys-shadow-md)",
            }}
          >
            <div style={{
              display: "flex",
              alignItems: "baseline",
              gap: 8,
              marginBottom: 4,
            }}>
              <span style={{
                fontSize: 12,
                fontWeight: 600,
                color: "var(--lys-accent)",
                fontFamily: "var(--lys-font-mono)",
              }}>{p.code}</span>
              <span style={{
                fontSize: 9,
                color: "var(--lys-text-faint)",
                letterSpacing: "0.04em",
                textTransform: "uppercase",
              }}>{p.name.split("(")[0].trim()}</span>
            </div>
            <p style={{
              fontSize: 11,
              color: "var(--lys-text-dim)",
              margin: 0,
              marginBottom: 6,
              lineHeight: 1.4,
            }}>
              {TIER_DESCRIPTIONS[p.code] ?? p.name}
            </p>
            <div style={{
              display: "flex",
              gap: 10,
              fontSize: 9.5,
              fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-faint)",
            }}>
              <span>{p.resistance_count} resistance genes</span>
              <span>·</span>
              <span>{p.first_line_count} first-line</span>
            </div>
          </motion.button>
        ))}
      </motion.div>

      {/* Feature row */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.4, delay: 0.4 }}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
          gap: 12,
          maxWidth: 1100,
          margin: "0 auto",
          width: "100%",
          paddingTop: 24,
          borderTop: "1px solid var(--lys-border)",
        }}
      >
        {FEATURES.map((f) => (
          <div key={f.title} style={{
            padding: 12,
            background: "transparent",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}>
            <div style={{
              display: "flex",
              alignItems: "center",
              gap: 8,
              color: "var(--lys-accent)",
            }}>
              {f.icon}
              <span style={{
                fontSize: 12,
                color: "var(--lys-text)",
                fontWeight: 600,
              }}>{f.title}</span>
            </div>
            <p style={{
              fontSize: 11,
              color: "var(--lys-text-dim)",
              margin: 0,
              lineHeight: 1.4,
            }}>{f.body}</p>
          </div>
        ))}
      </motion.div>
    </div>
  );
}

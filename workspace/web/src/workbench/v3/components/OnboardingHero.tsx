/**
 * OnboardingHero — compact, borderless, non-scrollable on first paint.
 *
 * Design intent (per user feedback):
 *  - The previous version was bulky (boxed cards with 1px borders, 16-32px
 *    padding, 280-min-col grid → 1-col fallback below 600px chat panel).
 *    That made the new-chat view scrollable and amateur-looking.
 *  - New version is title-led, with a tight 3-col pathogen grid that
 *    collapses to 2 only on very narrow chats. Each card is borderless;
 *    hover gets a soft bg-tint instead of border-flash.
 *  - Feature row is inline — 4 columns, icon + 1-line title + 2-line body.
 *  - All vertical gaps are 8/10/12px (down from 24-32). The whole hero
 *    fits under ~520px on a 360+px wide chat panel.
 *  - Once the user picks a pathogen, the chat takes over with full
 *    streams/reasoning UI — this view is just a fast launchpad.
 */
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

const TIER_BLURB: Record<string, string> = {
  MRSA: "mecA / PBP2a",
  Mtb: "rpoB / katG",
  "EColi-CRE": "KPC / NDM / OXA-48",
  KpneuCRE: "KPC producers",
  Abaum: "OXA-23/24/58",
  Paer: "mexAB-oprM + AmpC",
  VRE: "vanA / vanB",
  NGono: "penA / 23S rRNA",
};

const FEATURES = [
  { icon: <Brain size={13} />, title: "Multi-agent debate", body: "Designer, Critic, Editor, Strategist + 9 sub-agents." },
  { icon: <FlaskConical size={13} />, title: "12-component reward", body: "MIC, QED, SAscore, hemolysis, novelty, pose, spectrum." },
  { icon: <Microscope size={13} />, title: "Drag-edit chemistry", body: "Drop groups; pose recomputes, radar live-updates." },
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
      overflow: "hidden",          // non-scrollable on new chat per spec
      padding: "16px 14px",
      display: "flex",
      flexDirection: "column",
      gap: 14,
      background: "radial-gradient(ellipse at top, rgba(16, 185, 129, 0.06), transparent 55%)",
    }}>
      {/* ────────── Hero title block ────────── */}
      <motion.div
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        style={{ textAlign: "center", maxWidth: 560, margin: "0 auto" }}
      >
        <div style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "1px 7px",
          background: "var(--lys-accent-soft)",
          borderRadius: 999,
          fontSize: 9,
          color: "#047857",
          fontFamily: "var(--lys-font-mono)",
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          marginBottom: 8,
        }}>
          <Zap size={8} fill="currentColor" /> AMD Hackathon · May 2026
        </div>
        <h1 style={{
          fontSize: 19,
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
          Generative drug-design for AMR. Pick a pathogen, watch 4 agents debate, drag-edit, score live.
        </p>
      </motion.div>

      {/* ────────── Pathogen grid: borderless, 3 cols, tight ────────── */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.35, delay: 0.08 }}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
          gap: 6,
          maxWidth: 720,
          margin: "0 auto",
          width: "100%",
        }}
      >
        {sorted.slice(0, 8).map((p, i) => (
          <motion.button
            key={p.code}
            initial={{ opacity: 0, y: 4 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.25, delay: 0.08 + i * 0.03 }}
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
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <span style={{
                fontSize: 11.5,
                fontWeight: 600,
                color: "var(--lys-accent)",
                fontFamily: "var(--lys-font-mono)",
              }}>{p.code}</span>
              <span style={{
                fontSize: 9.5,
                color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)",
              }}>{TIER_BLURB[p.code] ?? ""}</span>
            </div>
            <div style={{
              fontSize: 9.5,
              color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)",
            }}>
              {p.resistance_count}r · {p.first_line_count}fl
            </div>
          </motion.button>
        ))}
      </motion.div>

      {/* ────────── Feature row: 4 cols, no boxes, no borders ────────── */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.35, delay: 0.18 }}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: 10,
          maxWidth: 720,
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

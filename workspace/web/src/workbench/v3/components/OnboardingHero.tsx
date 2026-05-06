/**
 * OnboardingHero — compact 2-col pathogen grid + visible feature row.
 *
 * Constraints (from user feedback):
 *  - Cards must be 2-col, not list-style — vertical space is precious
 *  - The bottom feature row must be visible without scroll on first paint
 *  - No top tag, no scroll on the new-chat surface
 *
 * Vertical budget on a 600×480 chat panel:
 *    title block      52px
 *    pathogen grid   ~210px (4 rows × ~50px + gaps)
 *    feature row     ~100px (2x2 on narrow, 4-col on wide)
 *    container pad   ~24px
 *    ──────────────
 *    total          ~386px → fits 600px area with ~200px breathing room
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
  fullName: string;       // human-readable pathogen name (short form)
  mech: string;            // primary mechanism / target
  whoTier: "CRITICAL" | "HIGH";
}

const PATHOGEN_META: Record<string, PathogenMeta> = {
  "MRSA":      { fullName: "S. aureus (MRSA)",          mech: "mecA · PBP2a",       whoTier: "HIGH" },
  "Mtb":       { fullName: "M. tuberculosis (MDR)",     mech: "rpoB · katG",         whoTier: "CRITICAL" },
  "EColi-CRE": { fullName: "E. coli (CRE)",             mech: "KPC · NDM · OXA-48",  whoTier: "CRITICAL" },
  "KpneuCRE":  { fullName: "K. pneumoniae (CRE)",       mech: "KPC producers",       whoTier: "CRITICAL" },
  "Abaum":     { fullName: "A. baumannii",              mech: "OXA-23/24/58",        whoTier: "CRITICAL" },
  "Paer":      { fullName: "P. aeruginosa (MDR)",       mech: "mexAB · AmpC",       whoTier: "CRITICAL" },
  "VRE":       { fullName: "E. faecium (VRE)",          mech: "vanA · vanB",         whoTier: "HIGH" },
  "NGono":     { fullName: "N. gonorrhoeae",            mech: "penA · 23S rRNA",     whoTier: "HIGH" },
};

const FEATURES = [
  { icon: <Brain size={12} />, title: "Multi-agent debate", body: "Designer · Critic · Editor · Strategist." },
  { icon: <FlaskConical size={12} />, title: "12-component reward", body: "MIC · QED · SAscore · pose · spectrum." },
  { icon: <Microscope size={12} />, title: "Drag-edit chemistry", body: "Click an atom; pose recomputes live." },
  { icon: <Target size={12} />, title: "MI300X-trained policy", body: "Gemma 4 31B · TxGemma → SFT → DPO → GRPO." },
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
      padding: "10px 12px 12px",
      display: "flex",
      flexDirection: "column",
      gap: 10,
      background: "radial-gradient(ellipse at top, rgba(16, 185, 129, 0.06), transparent 55%)",
    }}>
      {/* ────────── Title block (compact) ────────── */}
      <motion.div
        initial={{ opacity: 0, y: 6 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.3 }}
        style={{ textAlign: "center", maxWidth: 560, margin: "0 auto" }}
      >
        <h1 style={{
          fontSize: 18,
          fontWeight: 600,
          letterSpacing: "-0.02em",
          margin: 0,
          marginBottom: 3,
          color: "var(--lys-text)",
          lineHeight: 1.15,
        }}>
          Lysos Workbench
        </h1>
        <p style={{
          fontSize: 11,
          color: "var(--lys-text-dim)",
          margin: 0,
          lineHeight: 1.35,
        }}>
          Generative drug design for AMR — pick a WHO-priority pathogen below.
        </p>
      </motion.div>

      {/* ────────── Pathogen grid: TIGHT 2-col — flex:1 lets it scroll on
          truly-narrow viewports without pushing the feature row offscreen.
          On a normal 600px chat panel, 4 rows × ~46px = 184px fits cleanly. */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, delay: 0.06 }}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: 4,
          maxWidth: 760,
          margin: "0 auto",
          width: "100%",
          minHeight: 0,
        }}
      >
        {sorted.slice(0, 8).map((p, i) => {
          const meta = PATHOGEN_META[p.code];
          return (
            <motion.button
              key={p.code}
              initial={{ opacity: 0, y: 3 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2, delay: 0.06 + i * 0.02 }}
              onClick={() => onPickPathogen(p.code)}
              className="lys-onb-card"
              style={{
                padding: "6px 8px",
                border: 0,
                borderRadius: 7,
                background: "transparent",
                textAlign: "left",
                cursor: "pointer",
                fontFamily: "inherit",
                color: "var(--lys-text)",
                transition: "background 0.12s",
                display: "flex",
                flexDirection: "column",
                gap: 1,
                minWidth: 0,
              }}
            >
              {/* Row 1: code + tier badge (justify-between) */}
              <div style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                justifyContent: "space-between",
                minWidth: 0,
              }}>
                <span style={{
                  fontSize: 11.5,
                  fontWeight: 700,
                  color: "var(--lys-accent)",
                  fontFamily: "var(--lys-font-mono)",
                  letterSpacing: "-0.01em",
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}>{p.code}</span>
                {meta && (
                  <span style={{
                    fontSize: 8,
                    fontFamily: "var(--lys-font-mono)",
                    letterSpacing: "0.06em",
                    padding: "0 4px",
                    borderRadius: 3,
                    background: meta.whoTier === "CRITICAL"
                      ? "rgba(239, 68, 68, 0.10)"
                      : "rgba(245, 158, 11, 0.10)",
                    color: meta.whoTier === "CRITICAL" ? "#b91c1c" : "#92400e",
                    fontWeight: 600,
                    flexShrink: 0,
                  }}>
                    {meta.whoTier}
                  </span>
                )}
              </div>
              {/* Row 2: full name */}
              <div style={{
                fontSize: 10.5,
                color: "var(--lys-text)",
                fontWeight: 500,
                lineHeight: 1.25,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}>
                {meta?.fullName ?? p.name}
              </div>
              {/* Row 3: mech + first-line count (mono) */}
              <div style={{
                fontSize: 9,
                color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}>
                {meta?.mech ?? ""} · {p.first_line_count} drugs
              </div>
            </motion.button>
          );
        })}
      </motion.div>

      {/* ────────── Feature row: 2x2 on narrow, 4-col on wide ────────── */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.3, delay: 0.16 }}
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, 1fr)",
          gap: "8px 12px",
          maxWidth: 760,
          margin: "0 auto",
          width: "100%",
          paddingTop: 8,
          borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
          flexShrink: 0,
        }}
      >
        {FEATURES.map((f) => (
          <div key={f.title} style={{
            display: "flex",
            flexDirection: "column",
            gap: 1,
            minWidth: 0,
          }}>
            <div style={{
              display: "flex",
              alignItems: "center",
              gap: 5,
              color: "var(--lys-accent)",
            }}>
              {f.icon}
              <span style={{
                fontSize: 10.5,
                color: "var(--lys-text)",
                fontWeight: 600,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}>{f.title}</span>
            </div>
            <p style={{
              fontSize: 10,
              color: "var(--lys-text-dim)",
              margin: 0,
              lineHeight: 1.3,
            }}>{f.body}</p>
          </div>
        ))}
      </motion.div>
    </div>
  );
}

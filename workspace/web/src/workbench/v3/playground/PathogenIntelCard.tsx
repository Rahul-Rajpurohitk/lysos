/**
 * PathogenIntelCard — full pathogen profile dashboard.
 *
 * Reads /workbench/pathogens (returns full metadata for the 8 priority
 * pathogens) and renders rich domain intel for the currently-selected one:
 *   - Full name + threat-tier badge
 *   - Intrinsic features (cell-wall composition, common ports, etc.)
 *   - Resistome count with link to ResistanceMapCard
 *   - First-line therapy count
 *   - Common syndromes treated
 *
 * Switches automatically when user changes pathogen in TopHeader.
 * Works standalone — no need for a loaded SMILES candidate.
 */
import { useEffect, useState } from "react";
import { Bug, RefreshCw, AlertCircle, Pill, Stethoscope } from "lucide-react";

interface PathogenInfo {
  code: string;
  name: string;
  intrinsic_features?: string[];
  resistome_count?: number;
  first_line_count?: number;
  common_syndromes?: string[];
}

interface Props {
  apiBase: string;
  pathogen: string;
}

const THREAT_TIER: Record<string, { label: string; color: string }> = {
  MRSA:        { label: "WHO HIGH",     color: "#dc2626" },
  Mtb:         { label: "WHO CRITICAL", color: "#991b1b" },
  "EColi-CRE": { label: "WHO CRITICAL", color: "#991b1b" },
  KpneuCRE:    { label: "WHO CRITICAL", color: "#991b1b" },
  Abaum:       { label: "WHO CRITICAL", color: "#991b1b" },
  Paer:        { label: "WHO CRITICAL", color: "#991b1b" },
  VRE:         { label: "WHO HIGH",     color: "#dc2626" },
  NGono:       { label: "WHO HIGH",     color: "#dc2626" },
};

const FULL_NAMES: Record<string, string> = {
  MRSA:        "Methicillin-resistant Staphylococcus aureus",
  Mtb:         "Mycobacterium tuberculosis",
  "EColi-CRE": "Carbapenem-resistant Escherichia coli",
  KpneuCRE:    "Carbapenem-resistant Klebsiella pneumoniae",
  Abaum:       "Carbapenem-resistant Acinetobacter baumannii",
  Paer:        "Multidrug-resistant Pseudomonas aeruginosa",
  VRE:         "Vancomycin-resistant Enterococcus",
  NGono:       "Multidrug-resistant Neisseria gonorrhoeae",
};

const GRAM_TYPE: Record<string, string> = {
  MRSA: "Gram⁺", Mtb: "acid-fast", "EColi-CRE": "Gram⁻", KpneuCRE: "Gram⁻",
  Abaum: "Gram⁻", Paer: "Gram⁻", VRE: "Gram⁺", NGono: "Gram⁻",
};

export function PathogenIntelCard({ apiBase, pathogen }: Props) {
  const [info, setInfo] = useState<PathogenInfo | null>(null);
  const [loading, setLoading] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/pathogens`);
      if (!r.ok) return;
      const d = await r.json();
      const found = (d.pathogens ?? []).find((p: PathogenInfo) =>
        p.code.toLowerCase() === pathogen.toLowerCase());
      setInfo(found ?? null);
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [pathogen, apiBase]);

  const tier = THREAT_TIER[pathogen] ?? { label: "monitor", color: "#9ca3af" };

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
        <Bug size={11} style={{ color: tier.color }} />
        <span>pathogen · {pathogen}</span>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={refresh} disabled={loading}
          style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 8, display: "flex",
        flexDirection: "column", gap: 8 }}>

        {/* Hero: name + threat tier */}
        <div style={{
          padding: "8px 10px", borderRadius: 6,
          background: `${tier.color}10`, borderLeft: `3px solid ${tier.color}`,
          display: "flex", flexDirection: "column", gap: 4,
        }}>
          <div style={{ display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
            <span style={{ fontSize: 8.5, padding: "1px 6px", borderRadius: 999,
              background: tier.color, color: "white", fontWeight: 700,
              fontFamily: "var(--lys-font-mono)", letterSpacing: "0.04em" }}>
              {tier.label}
            </span>
            <span style={{ fontSize: 8.5, padding: "1px 6px", borderRadius: 999,
              background: "var(--lys-bg-3, rgba(0,0,0,0.04))", color: "var(--lys-text-dim)",
              fontFamily: "var(--lys-font-mono)" }}>
              {GRAM_TYPE[pathogen] ?? "?"}
            </span>
          </div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--lys-text)",
            fontFamily: "var(--lys-font-mono)", lineHeight: 1.25 }}>
            {info?.name || FULL_NAMES[pathogen] || pathogen}
          </div>
          <div style={{ fontSize: 9, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)" }}>
            code · {pathogen}
          </div>
        </div>

        {/* Stat tiles — resistome / first-line / syndromes */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 4 }}>
          <StatTile icon={<AlertCircle size={11} />} label="resistome genes"
            value={info?.resistome_count ?? 0} color="#dc2626" />
          <StatTile icon={<Pill size={11} />} label="first-line drugs"
            value={info?.first_line_count ?? 0} color="#10b981" />
        </div>

        {/* Intrinsic features */}
        {info?.intrinsic_features && info.intrinsic_features.length > 0 && (
          <Section title="intrinsic features" iconColor="#6366f1">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
              {info.intrinsic_features.map((f, i) => (
                <span key={i} style={{
                  fontSize: 9.5, padding: "2px 6px", borderRadius: 4,
                  background: "rgba(99,102,241,0.08)", color: "#4f46e5",
                  fontFamily: "var(--lys-font-mono)",
                }}>{f}</span>
              ))}
            </div>
          </Section>
        )}

        {/* Common syndromes */}
        {info?.common_syndromes && info.common_syndromes.length > 0 && (
          <Section title="common syndromes" iconColor="#0891b2">
            <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
              {info.common_syndromes.map((s, i) => (
                <span key={i} style={{
                  fontSize: 9.5, padding: "2px 6px", borderRadius: 4,
                  background: "rgba(8,145,178,0.08)", color: "#0e7490",
                  fontFamily: "var(--lys-font-mono)",
                  display: "inline-flex", alignItems: "center", gap: 3,
                }}>
                  <Stethoscope size={9} />
                  {s}
                </span>
              ))}
            </div>
          </Section>
        )}

        {/* Quick stats footer */}
        <div style={{ marginTop: "auto", padding: "4px 6px",
          fontSize: 9, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)", textAlign: "center",
          borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        }}>
          design candidates targeting this pathogen will be scored against
          its specific resistome
        </div>
      </div>
    </div>
  );
}

function StatTile({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: number; color: string }) {
  return (
    <div style={{
      padding: "5px 8px", borderRadius: 4,
      background: `${color}08`, border: `1px solid ${color}20`,
      display: "flex", flexDirection: "column", gap: 2,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 4,
        fontSize: 8.5, color: "var(--lys-text-faint)",
        fontFamily: "var(--lys-font-mono)", letterSpacing: "0.04em",
        textTransform: "uppercase" }}>
        <span style={{ color }}>{icon}</span>
        <span>{label}</span>
      </div>
      <div style={{ fontSize: 18, fontWeight: 700, color, lineHeight: 1,
        fontFamily: "var(--lys-font-mono)" }}>{value}</div>
    </div>
  );
}

function Section({ title, iconColor, children }: { title: string; iconColor: string; children: React.ReactNode }) {
  return (
    <div>
      <div style={{
        fontSize: 9, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.04em",
        textTransform: "uppercase", marginBottom: 4,
        display: "flex", alignItems: "center", gap: 4,
        borderLeft: `2px solid ${iconColor}`, paddingLeft: 6,
      }}>{title}</div>
      {children}
    </div>
  );
}

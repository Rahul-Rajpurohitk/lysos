/**
 * KnowledgeNavbar — pathogen + antibiotic-class filters for the Knowledge
 * container's left sidebar.
 *
 * Buttons:
 *   PATHOGEN section — 8 priority pathogens (one click swaps active one)
 *   CLASS section — toggle antibiotic-class filter (β-lactam / quinolone /
 *                   macrolide / aminoglycoside / glycopeptide / etc.)
 *   QUICK section — open AntibioticReference card focus (scroll-to)
 */
import { Bug, Pill, Filter } from "lucide-react";

interface Props {
  pathogen: string;
  onPathogenChange: (code: string) => void;
  drugClassFilter: string;
  onDrugClassChange: (cls: string) => void;
}

const PATHOGENS: Array<{ code: string; short: string; tier: "critical" | "high" }> = [
  { code: "MRSA",        short: "MRSA",  tier: "high"     },
  { code: "Mtb",         short: "Mtb",   tier: "critical" },
  { code: "EColi-CRE",   short: "ECRE",  tier: "critical" },
  { code: "KpneuCRE",    short: "KCRE",  tier: "critical" },
  { code: "Abaum",       short: "Aba",   tier: "critical" },
  { code: "Paer",        short: "Paer",  tier: "critical" },
  { code: "VRE",         short: "VRE",   tier: "high"     },
  { code: "NGono",       short: "NGo",   tier: "high"     },
];

const DRUG_CLASSES: Array<{ key: string; label: string; color: string }> = [
  { key: "β-lactam",        label: "β-Lct",  color: "#10b981" },
  { key: "carbapenem",      label: "Carb",   color: "#7c3aed" },
  { key: "fluoroquinolone", label: "FQ",     color: "#ea580c" },
  { key: "macrolide",       label: "Macr",   color: "#dc2626" },
  { key: "aminoglycoside",  label: "AGly",   color: "#2563eb" },
  { key: "glycopeptide",    label: "GPep",   color: "#a855f7" },
];

export function KnowledgeNavbar(p: Props) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-mono)" }}>
      <Section icon={<Bug size={9} />} label="PATH." />
      {PATHOGENS.map((pg) => {
        const active = p.pathogen === pg.code;
        const c = pg.tier === "critical" ? "#991b1b" : "#dc2626";
        return (
          <NavBtn key={pg.code}
            icon={<Bug size={12} style={{ color: active ? "white" : c }} />}
            label={pg.short}
            title={pg.code + " · " + pg.tier.toUpperCase()}
            onClick={() => p.onPathogenChange(pg.code)}
            accent={c}
            active={active}
          />
        );
      })}

      <Section icon={<Filter size={9} />} label="CLASS" />
      <NavBtn
        icon={<Pill size={12} style={{ color: !p.drugClassFilter ? "white" : "#6b7280" }} />}
        label="all"
        title="No drug class filter"
        onClick={() => p.onDrugClassChange("")}
        accent="#6b7280"
        active={!p.drugClassFilter}
      />
      {DRUG_CLASSES.map((cls) => {
        const active = p.drugClassFilter.toLowerCase() === cls.key.toLowerCase();
        return (
          <NavBtn key={cls.key}
            icon={<Pill size={12} style={{ color: active ? "white" : cls.color }} />}
            label={cls.label}
            title={cls.key}
            onClick={() => p.onDrugClassChange(active ? "" : cls.key)}
            accent={cls.color}
            active={active}
          />
        );
      })}
    </div>
  );
}

function Section({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 3,
      fontSize: 7.5, color: "var(--lys-text-faint)",
      fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.08em", textTransform: "uppercase",
      padding: "3px 0 1px 0", marginTop: 2,
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      justifyContent: "center",
    }}>{icon}<span>{label}</span></div>
  );
}

function NavBtn({ icon, label, title, onClick, accent, active }: {
  icon: React.ReactNode; label: string; title?: string;
  onClick: () => void; accent: string; active?: boolean;
}) {
  return (
    <button
      type="button" onClick={onClick} title={title}
      style={{
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 2,
        padding: "5px 4px", borderRadius: 5,
        border: `1px solid ${active ? accent : "transparent"}`,
        background: active ? accent : "var(--lys-bg-2, #ffffff)",
        cursor: "pointer", fontFamily: "var(--lys-font-mono)",
        transition: "background 100ms, border-color 100ms",
      }}
      onMouseOver={(e) => { if (!active) {
        (e.currentTarget as HTMLElement).style.background = `${accent}10`;
        (e.currentTarget as HTMLElement).style.borderColor = `${accent}40`;
      }}}
      onMouseOut={(e) => { if (!active) {
        (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)";
        (e.currentTarget as HTMLElement).style.borderColor = "transparent";
      }}}
    >
      {icon}
      <span style={{
        fontSize: 8.5, fontWeight: 600,
        color: active ? "white" : "var(--lys-text)",
      }}>{label}</span>
    </button>
  );
}

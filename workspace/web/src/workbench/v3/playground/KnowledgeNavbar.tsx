/**
 * KnowledgeNavbar — pathogen + antibiotic-class filters for the Knowledge
 * container's left sidebar. Self-explanatory labels for non-chem users.
 */
import { Bug, Pill, Filter } from "lucide-react";

interface Props {
  pathogen: string;
  onPathogenChange: (code: string) => void;
  drugClassFilter: string;
  onDrugClassChange: (cls: string) => void;
}

const PATHOGENS: Array<{ code: string; label: string; sub: string; tier: "critical" | "high" }> = [
  { code: "MRSA",        label: "MRSA",        sub: "S. aureus",       tier: "high"     },
  { code: "Mtb",         label: "TB",          sub: "M. tuberculosis", tier: "critical" },
  { code: "EColi-CRE",   label: "E. coli",     sub: "carbapenem-R",   tier: "critical" },
  { code: "KpneuCRE",    label: "Klebsiella",  sub: "carbapenem-R",   tier: "critical" },
  { code: "Abaum",       label: "A. baumannii", sub: "carbapenem-R",  tier: "critical" },
  { code: "Paer",        label: "P. aeruginosa", sub: "multi-drug",   tier: "critical" },
  { code: "VRE",         label: "VRE",         sub: "vanco-R Entero.", tier: "high"    },
  { code: "NGono",       label: "Gonorrhea",   sub: "N. gonorrhoeae",  tier: "high"    },
];

const DRUG_CLASSES: Array<{ key: string; label: string; sub: string; color: string }> = [
  { key: "β-lactam",        label: "β-Lactams",       sub: "penicillins",    color: "#10b981" },
  { key: "carbapenem",      label: "Carbapenems",     sub: "last-line",     color: "#7c3aed" },
  { key: "fluoroquinolone", label: "Fluoroquinolones", sub: "DNA gyrase",   color: "#ea580c" },
  { key: "macrolide",       label: "Macrolides",      sub: "ribosomal",     color: "#dc2626" },
  { key: "aminoglycoside",  label: "Aminoglycosides", sub: "30S inhibit.",  color: "#2563eb" },
  { key: "glycopeptide",    label: "Glycopeptides",   sub: "vancomycin",    color: "#a855f7" },
];

export function KnowledgeNavbar(p: Props) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-body)" }}>
      <Section icon={<Bug size={10} />} label="Target pathogen" />
      {PATHOGENS.map((pg) => {
        const active = p.pathogen === pg.code;
        const c = pg.tier === "critical" ? "#991b1b" : "#dc2626";
        return (
          <NavBtn key={pg.code}
            icon={<Bug size={14} style={{ color: active ? "white" : c }} />}
            label={pg.label} sub={pg.sub}
            title={`${pg.code} · WHO ${pg.tier}`}
            onClick={() => p.onPathogenChange(pg.code)}
            accent={c} active={active}
          />
        );
      })}

      <Section icon={<Filter size={10} />} label="Antibiotic class" />
      <NavBtn
        icon={<Pill size={14} style={{ color: !p.drugClassFilter ? "white" : "#6b7280" }} />}
        label="All classes" title="Show every drug class"
        onClick={() => p.onDrugClassChange("")}
        accent="#6b7280" active={!p.drugClassFilter}
      />
      {DRUG_CLASSES.map((cls) => {
        const active = p.drugClassFilter.toLowerCase() === cls.key.toLowerCase();
        return (
          <NavBtn key={cls.key}
            icon={<Pill size={14} style={{ color: active ? "white" : cls.color }} />}
            label={cls.label} sub={cls.sub}
            title={cls.key + " — filter the antibiotic reference"}
            onClick={() => p.onDrugClassChange(active ? "" : cls.key)}
            accent={cls.color} active={active}
          />
        );
      })}
    </div>
  );
}

function Section({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 4,
      fontSize: 9, color: "var(--lys-text-faint)",
      fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.06em", textTransform: "uppercase",
      padding: "4px 6px 2px 6px", marginTop: 4,
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
      fontWeight: 600,
    }}>{icon}<span>{label}</span></div>
  );
}

function NavBtn({ icon, label, sub, title, onClick, accent, active }: {
  icon: React.ReactNode; label: string; sub?: string; title?: string;
  onClick: () => void; accent: string; active?: boolean;
}) {
  return (
    <button type="button" onClick={onClick} title={title}
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center", gap: 8, padding: "7px 8px",
        borderRadius: 6,
        border: `1px solid ${active ? accent : "var(--lys-border-faint, rgba(0,0,0,0.05))"}`,
        background: active ? accent : "var(--lys-bg-2, #ffffff)",
        cursor: "pointer", fontFamily: "var(--lys-font-body)",
        transition: "background 100ms, border-color 100ms",
        textAlign: "left", width: "100%",
      }}
      onMouseOver={(e) => { if (!active) {
        (e.currentTarget as HTMLElement).style.background = `${accent}10`;
        (e.currentTarget as HTMLElement).style.borderColor = `${accent}40`;
      }}}
      onMouseOut={(e) => { if (!active) {
        (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)";
        (e.currentTarget as HTMLElement).style.borderColor = "var(--lys-border-faint, rgba(0,0,0,0.05))";
      }}}
    >
      <span style={{
        width: 22, height: 22,
        display: "flex", alignItems: "center", justifyContent: "center",
        flexShrink: 0,
      }}>{icon}</span>
      <span style={{ display: "flex", flexDirection: "column",
        gap: 1, minWidth: 0, flex: 1 }}>
        <span style={{
          fontSize: 11, fontWeight: 600,
          color: active ? "white" : "var(--lys-text)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{label}</span>
        {sub && (
          <span style={{
            fontSize: 8.5,
            color: active ? "rgba(255,255,255,0.85)" : "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{sub}</span>
        )}
      </span>
    </button>
  );
}

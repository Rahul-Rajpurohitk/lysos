/**
 * ChemistryNavbar — left sidebar for the Chemistry container.
 *
 * Power-BI-style icon strip with launchers, quick scaffolds, and a
 * pathogen swatch. Lives in the slot:"nav" of PlaygroundGroup. ~96px wide.
 *
 * Buttons:
 *   ✦ Pick scaffold     — opens the dropdown launcher (existing card)
 *   ⌬ Quick: Benzene    — instant load
 *   ⌬ Quick: β-Lactam
 *   ⌬ Quick: Pyridine
 *   ⌬ Quick: Imidazole
 *   ⊘ Empty / start fresh
 *   ───
 *   🦠 active pathogen swatch
 *
 * Each button has icon + tiny label below it.
 */
import { useEffect, useState } from "react";
import { Sparkles, RefreshCw, Trash2, Bug } from "lucide-react";

interface Props {
  apiBase: string;
  pathogen: string;
  onLoadSmiles: (smi: string, name: string) => void;
  onClearCanvas?: () => void;
}

interface Scaffold {
  id: string;
  name: string;
  category: string;
  smiles: string;
  tag: string;
}

// Curated quick-pick set — must match scaffold names from /scaffolds endpoint
const QUICK_PICKS = [
  { name: "Benzene",            label: "Benzene",      sub: "6-ring", symbol: "⌬" },
  { name: "β-Lactam (penam core)", label: "β-Lactam",  sub: "penicillin",  symbol: "□" },
  { name: "Pyridine",           label: "Pyridine",     sub: "6-ring + N", symbol: "⬡" },
  { name: "Imidazole",          label: "Imidazole",    sub: "5-ring + 2N", symbol: "⬠" },
  { name: "Cyclohexane",        label: "Cyclohex.",    sub: "saturated", symbol: "⬢" },
];

export function ChemistryNavbar({ apiBase, pathogen, onLoadSmiles, onClearCanvas }: Props) {
  const [scaffolds, setScaffolds] = useState<Scaffold[]>([]);

  useEffect(() => {
    fetch(`${apiBase}/workbench/playground/scaffolds`)
      .then((r) => r.ok ? r.json() : null)
      .then((d) => { if (d?.scaffolds) setScaffolds(d.scaffolds); })
      .catch(() => {});
  }, [apiBase]);

  function pick(name: string) {
    const s = scaffolds.find((x) => x.name === name);
    if (s) onLoadSmiles(s.smiles, s.name);
  }

  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-mono)",
    }}>
      {/* Section: launcher */}
      <NavSectionHeader icon={<Sparkles size={10} />} label="Library" />
      <NavButton
        icon={<Sparkles size={15} style={{ color: "#10b981" }} />}
        label="All scaffolds"
        sub={`${scaffolds.length} starting points`}
        title="Open the full scaffold library with search — listed below in the cards grid"
        onClick={() => {}}
        accent="#10b981"
      />

      {/* Section: quick picks — top molecular scaffolds */}
      <NavSectionHeader icon={<RefreshCw size={10} />} label="Quick load" />
      {QUICK_PICKS.map((q) => {
        const found = scaffolds.find((s) => s.name === q.name);
        return (
          <NavButton
            key={q.name}
            icon={<span style={{ fontSize: 16, lineHeight: 1, fontFamily: "ui-monospace, monospace" }}>{q.symbol}</span>}
            label={q.label}
            sub={q.sub}
            title={q.name + (found ? ` · ${found.smiles}` : " (loading...)")}
            disabled={!found}
            onClick={() => pick(q.name)}
            accent="#0891b2"
          />
        );
      })}

      {/* Section: tools */}
      <NavSectionHeader icon={<Trash2 size={10} />} label="Tools" />
      <NavButton
        icon={<Trash2 size={14} style={{ color: "#dc2626" }} />}
        label="Clear canvas"
        title="Remove the current molecule from the workspace"
        onClick={() => onClearCanvas?.()}
        accent="#dc2626"
      />

      {/* Section: pathogen context (shown but not editable here — change in Knowledge nav) */}
      <NavSectionHeader icon={<Bug size={10} />} label="Target pathogen" />
      <div title={`Currently designing for: ${pathogen}`}
        style={{
          display: "flex", flexDirection: "column",
          alignItems: "center", gap: 3,
          padding: "6px 4px",
          borderRadius: 5,
          background: "rgba(220,38,38,0.06)",
          border: "1px solid rgba(220,38,38,0.18)",
          fontFamily: "var(--lys-font-mono)",
        }}>
        <Bug size={14} style={{ color: "#dc2626" }} />
        <span style={{
          fontSize: 10, fontWeight: 700,
          color: "#dc2626", letterSpacing: "0.02em",
        }}>{pathogen}</span>
        <span style={{ fontSize: 8, color: "var(--lys-text-faint)" }}>active target</span>
      </div>
    </div>
  );
}

function NavSectionHeader({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 4,
      fontSize: 9, color: "var(--lys-text-faint)",
      fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.06em", textTransform: "uppercase",
      padding: "4px 6px 2px 6px",
      marginTop: 4,
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
      fontWeight: 600,
    }}>
      {icon}
      <span>{label}</span>
    </div>
  );
}

function NavButton({ icon, label, sub, title, onClick, disabled, accent = "#94a3b8" }: {
  icon: React.ReactNode;
  label: string;
  sub?: string;
  title?: string;
  onClick: () => void;
  disabled?: boolean;
  accent?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        display: "flex", flexDirection: "row",
        alignItems: "center", gap: 8,
        padding: "7px 8px",
        borderRadius: 6,
        border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
        background: "var(--lys-bg-2, #ffffff)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 1,
        fontFamily: "var(--lys-font-body)",
        transition: "background 100ms, border-color 100ms",
        textAlign: "left",
        width: "100%",
      }}
      onMouseOver={(e) => {
        if (disabled) return;
        (e.currentTarget as HTMLElement).style.background = `${accent}10`;
        (e.currentTarget as HTMLElement).style.borderColor = `${accent}40`;
      }}
      onMouseOut={(e) => {
        (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)";
        (e.currentTarget as HTMLElement).style.borderColor = "var(--lys-border-faint, rgba(0,0,0,0.05))";
      }}
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
          color: "var(--lys-text)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
        }}>{label}</span>
        {sub && (
          <span style={{
            fontSize: 8.5, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)",
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>{sub}</span>
        )}
      </span>
    </button>
  );
}

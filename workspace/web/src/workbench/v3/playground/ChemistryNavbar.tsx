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
  { name: "Benzene",            label: "Bnz",  symbol: "⌬" },
  { name: "β-Lactam (penam core)", label: "β-L",  symbol: "□" },
  { name: "Pyridine",           label: "Pyr",  symbol: "⬡" },
  { name: "Imidazole",          label: "Imd",  symbol: "⬠" },
  { name: "Cyclohexane",        label: "Cyc",  symbol: "⬢" },
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
      <NavSectionHeader icon={<Sparkles size={9} />} label="LOAD" />
      <NavButton
        icon={<Sparkles size={14} style={{ color: "#10b981" }} />}
        label="scaffold"
        sub={`${scaffolds.length}`}
        title="Open the full scaffold dropdown — listed below in the cards grid"
        onClick={() => {
          // Scroll to / focus the scaffold launcher card. For now, no-op:
          // the existing card has its own opener. This pure-icon version
          // is a hint; user can also click directly on the card body.
        }}
        accent="#10b981"
      />

      {/* Section: quick picks */}
      <NavSectionHeader icon={<RefreshCw size={9} />} label="QUICK" />
      {QUICK_PICKS.map((q) => {
        const found = scaffolds.find((s) => s.name === q.name);
        return (
          <NavButton
            key={q.name}
            icon={<span style={{ fontSize: 14, lineHeight: 1, fontFamily: "ui-monospace, monospace" }}>{q.symbol}</span>}
            label={q.label}
            title={q.name + (found ? ` · ${found.smiles}` : "")}
            disabled={!found}
            onClick={() => pick(q.name)}
            accent="#0891b2"
          />
        );
      })}

      {/* Section: tools */}
      <NavSectionHeader icon={<Trash2 size={9} />} label="TOOLS" />
      <NavButton
        icon={<Trash2 size={13} style={{ color: "#dc2626" }} />}
        label="clear"
        title="Clear current candidate from canvas"
        onClick={() => onClearCanvas?.()}
        accent="#dc2626"
      />

      {/* Section: pathogen context */}
      <NavSectionHeader icon={<Bug size={9} />} label="PATH." />
      <div title={`Active pathogen: ${pathogen}`}
        style={{
          display: "flex", flexDirection: "column",
          alignItems: "center", gap: 2,
          padding: "5px 4px",
          borderRadius: 5,
          background: "rgba(220,38,38,0.06)",
          border: "1px solid rgba(220,38,38,0.18)",
          fontFamily: "var(--lys-font-mono)",
        }}>
        <Bug size={13} style={{ color: "#dc2626" }} />
        <span style={{
          fontSize: 8.5, fontWeight: 700,
          color: "#dc2626", letterSpacing: "0.04em",
        }}>{pathogen}</span>
      </div>
    </div>
  );
}

function NavSectionHeader({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 3,
      fontSize: 7.5, color: "var(--lys-text-faint)",
      fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.08em", textTransform: "uppercase",
      padding: "3px 0 1px 0",
      marginTop: 2,
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      justifyContent: "center",
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
        display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 2,
        padding: "6px 4px",
        borderRadius: 5,
        border: "1px solid transparent",
        background: "var(--lys-bg-2, #ffffff)",
        cursor: disabled ? "not-allowed" : "pointer",
        opacity: disabled ? 0.45 : 1,
        fontFamily: "var(--lys-font-mono)",
        transition: "background 100ms, border-color 100ms",
      }}
      onMouseOver={(e) => {
        if (disabled) return;
        (e.currentTarget as HTMLElement).style.background = `${accent}10`;
        (e.currentTarget as HTMLElement).style.borderColor = `${accent}40`;
      }}
      onMouseOut={(e) => {
        (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)";
        (e.currentTarget as HTMLElement).style.borderColor = "transparent";
      }}
    >
      {icon}
      <span style={{
        fontSize: 8.5, fontWeight: 600,
        color: "var(--lys-text)",
        letterSpacing: "0.02em",
      }}>{label}</span>
      {sub && (
        <span style={{
          fontSize: 7.5, color: "var(--lys-text-faint)",
          fontWeight: 700,
        }}>{sub}</span>
      )}
    </button>
  );
}

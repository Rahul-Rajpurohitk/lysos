/**
 * ScoringNavbar — weight presets + view filters for the Scoring container.
 * Self-explanatory labels.
 */
import { Scale, Bug, Pill, Sparkles, BarChart3, ListChecks, Shield, GitCompare } from "lucide-react";

type Preset = "default" | "mic" | "admet" | "novel";

interface Props {
  preset: Preset;
  onPresetChange: (p: Preset) => void;
  emphasis: "radar" | "bars" | "tox" | "sim";
  onEmphasisChange: (e: "radar" | "bars" | "tox" | "sim") => void;
}

export function ScoringNavbar(p: Props) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-body)" }}>
      <Section label="Weight preset" />
      <NavBtn icon={<Scale size={14} style={{ color: p.preset === "default" ? "white" : "#d97706" }} />}
        label="Balanced" sub="default 12-axis" title="Default balanced weighting across all 12 reward axes"
        active={p.preset === "default"} accent="#d97706"
        onClick={() => p.onPresetChange("default")} />
      <NavBtn icon={<Bug size={14} style={{ color: p.preset === "mic" ? "white" : "#dc2626" }} />}
        label="Potency-first" sub="MIC + spectrum" title="Boost predicted MIC + spectrum_breadth — kill power"
        active={p.preset === "mic"} accent="#dc2626"
        onClick={() => p.onPresetChange("mic")} />
      <NavBtn icon={<Pill size={14} style={{ color: p.preset === "admet" ? "white" : "#10b981" }} />}
        label="Drug-likeness" sub="ADMET + safety" title="Boost QED + Lipinski + hemolysis safety"
        active={p.preset === "admet"} accent="#10b981"
        onClick={() => p.onPresetChange("admet")} />
      <NavBtn icon={<Sparkles size={14} style={{ color: p.preset === "novel" ? "white" : "#a855f7" }} />}
        label="Novelty-first" sub="explore unknown" title="Boost novelty + embedding_novelty — find new chemistry"
        active={p.preset === "novel"} accent="#a855f7"
        onClick={() => p.onPresetChange("novel")} />

      <Section label="View" />
      <NavBtn icon={<BarChart3 size={14} style={{ color: p.emphasis === "radar" ? "white" : "#0891b2" }} />}
        label="Reward radar" sub="all axes at once" title="Polygon view of all 12 reward axes"
        active={p.emphasis === "radar"} accent="#0891b2"
        onClick={() => p.onEmphasisChange("radar")} />
      <NavBtn icon={<ListChecks size={14} style={{ color: p.emphasis === "bars" ? "white" : "#0891b2" }} />}
        label="Score breakdown" sub="ranked by impact" title="Per-axis bar chart sorted by contribution"
        active={p.emphasis === "bars"} accent="#0891b2"
        onClick={() => p.onEmphasisChange("bars")} />
      <NavBtn icon={<Shield size={14} style={{ color: p.emphasis === "tox" ? "white" : "#dc2626" }} />}
        label="Toxicity" sub="ADME-Tox" title="hERG / hepatotoxicity / Ames / skin sensitization"
        active={p.emphasis === "tox"} accent="#dc2626"
        onClick={() => p.onEmphasisChange("tox")} />
      <NavBtn icon={<GitCompare size={14} style={{ color: p.emphasis === "sim" ? "white" : "#7c3aed" }} />}
        label="Similar drugs" sub="Tanimoto vs corpus" title="Top-K similar known antibiotics"
        active={p.emphasis === "sim"} accent="#7c3aed"
        onClick={() => p.onEmphasisChange("sim")} />
    </div>
  );
}

function Section({ label }: { label: string }) {
  return (
    <div style={{
      fontSize: 9, color: "var(--lys-text-faint)",
      fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.06em", textTransform: "uppercase",
      padding: "4px 6px 2px 6px", marginTop: 4,
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
      fontWeight: 600,
    }}>{label}</div>
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
      }}}>
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

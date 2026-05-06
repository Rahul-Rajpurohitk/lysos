/**
 * ScoringNavbar — weight presets + view filters for the Scoring container.
 *
 * Buttons:
 *   PRESET section — load a preset weight scheme
 *     [⚖ Default]   balanced 12-axis defaults
 *     [🦠 MIC]       boost predicted_mic + spectrum_breadth
 *     [💊 ADMET]    boost drug-likeness + safety
 *     [✨ Novel]    boost novelty + embedding_novelty
 *
 *   VIEW section — toggle which Scoring panels are emphasized
 *     [📊 Radar]
 *     [📋 Bars]
 *     [🛡 Tox]
 *     [🔬 Sim]
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
      fontFamily: "var(--lys-font-mono)" }}>
      <Section label="PRESET" />
      <NavBtn icon={<Scale size={13} style={{ color: p.preset === "default" ? "white" : "#d97706" }} />}
        label="Bal" title="Default balanced weights"
        active={p.preset === "default"} accent="#d97706"
        onClick={() => p.onPresetChange("default")} />
      <NavBtn icon={<Bug size={13} style={{ color: p.preset === "mic" ? "white" : "#dc2626" }} />}
        label="MIC" title="Boost predicted_mic + spectrum_breadth"
        active={p.preset === "mic"} accent="#dc2626"
        onClick={() => p.onPresetChange("mic")} />
      <NavBtn icon={<Pill size={13} style={{ color: p.preset === "admet" ? "white" : "#10b981" }} />}
        label="ADMET" title="Boost drug-likeness + hemolysis safety"
        active={p.preset === "admet"} accent="#10b981"
        onClick={() => p.onPresetChange("admet")} />
      <NavBtn icon={<Sparkles size={13} style={{ color: p.preset === "novel" ? "white" : "#a855f7" }} />}
        label="Novel" title="Boost novelty + embedding_novelty"
        active={p.preset === "novel"} accent="#a855f7"
        onClick={() => p.onPresetChange("novel")} />

      <Section label="VIEW" />
      <NavBtn icon={<BarChart3 size={13} style={{ color: p.emphasis === "radar" ? "white" : "#0891b2" }} />}
        label="Radar" title="Reward radar"
        active={p.emphasis === "radar"} accent="#0891b2"
        onClick={() => p.onEmphasisChange("radar")} />
      <NavBtn icon={<ListChecks size={13} style={{ color: p.emphasis === "bars" ? "white" : "#0891b2" }} />}
        label="Bars" title="12-axis breakdown"
        active={p.emphasis === "bars"} accent="#0891b2"
        onClick={() => p.onEmphasisChange("bars")} />
      <NavBtn icon={<Shield size={13} style={{ color: p.emphasis === "tox" ? "white" : "#dc2626" }} />}
        label="Tox" title="Toxicity profile"
        active={p.emphasis === "tox"} accent="#dc2626"
        onClick={() => p.onEmphasisChange("tox")} />
      <NavBtn icon={<GitCompare size={13} style={{ color: p.emphasis === "sim" ? "white" : "#7c3aed" }} />}
        label="Sim" title="Tanimoto similarity"
        active={p.emphasis === "sim"} accent="#7c3aed"
        onClick={() => p.onEmphasisChange("sim")} />
    </div>
  );
}

function Section({ label }: { label: string }) {
  return (
    <div style={{
      fontSize: 7.5, color: "var(--lys-text-faint)",
      fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.08em", textTransform: "uppercase",
      padding: "3px 0 1px 0", marginTop: 2,
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      textAlign: "center",
    }}>{label}</div>
  );
}

function NavBtn({ icon, label, title, onClick, accent, active }: {
  icon: React.ReactNode; label: string; title?: string;
  onClick: () => void; accent: string; active?: boolean;
}) {
  return (
    <button type="button" onClick={onClick} title={title}
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
      }}}>
      {icon}
      <span style={{ fontSize: 8.5, fontWeight: 600,
        color: active ? "white" : "var(--lys-text)" }}>{label}</span>
    </button>
  );
}

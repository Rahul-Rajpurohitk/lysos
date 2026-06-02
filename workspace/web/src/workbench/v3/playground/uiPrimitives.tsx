/**
 * uiPrimitives — the shared, aligned building blocks for every chem card.
 *
 * The "unaligned info" problem comes from each card inventing its own tile /
 * bar / badge markup with slightly different padding, font sizes, and
 * colours. These primitives are the single source of truth so every card
 * shares one rhythm. All sizing is in the --lys-* token system.
 *
 * - StatTile      — a labelled metric in a bordered tile (grids align)
 * - MetricBar     — labelled 0-1 bar with value + band colour
 * - BandPill      — a small uppercase status chip (good/moderate/poor…)
 * - ProvenanceBadge — names the real engine behind a number (trust signal)
 * - SectionLabel  — the mono uppercase section header
 * - EmptyState    — consistent "nothing yet" panel
 */
import type { ReactNode } from "react";

// Canonical band → colour. Every card maps its bands onto these words so the
// colour language is consistent platform-wide.
export const BAND_COLOR: Record<string, string> = {
  // positive
  strong: "#16a34a", good: "#16a34a", advance: "#16a34a", stable: "#16a34a",
  selective: "#16a34a", easy: "#16a34a", low: "#16a34a", headroom: "#16a34a",
  permeable: "#16a34a", active: "#16a34a",
  // mid
  moderate: "#d97706", promising: "#65a30d", borderline: "#d97706",
  pressured: "#d97706", fair: "#d97706", medium: "#d97706", limited: "#d97706",
  // negative
  poor: "#dc2626", weak: "#dc2626", hard: "#dc2626", high: "#dc2626",
  saturated: "#dc2626", vulnerable: "#dc2626", labile: "#dc2626",
  "very hard": "#dc2626", unlikely: "#dc2626", toxic: "#dc2626",
  // neutral
  "n/a": "#94a3b8", unknown: "#94a3b8", "—": "#94a3b8",
};

export function bandColor(band: string | null | undefined): string {
  return BAND_COLOR[(band ?? "").toLowerCase()] ?? "var(--lys-text-faint)";
}

export function StatTile({ label, value, color, sub, title }: {
  label: string; value: ReactNode; color?: string; sub?: string; title?: string;
}) {
  return (
    <div title={title} style={{
      background: "var(--lys-surface)", border: "1px solid var(--lys-border)",
      borderRadius: 6, padding: "5px 7px", textAlign: "center", minWidth: 0,
    }}>
      <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.04em", textTransform: "uppercase",
        color: "var(--lys-text-faint)", whiteSpace: "nowrap",
        overflow: "hidden", textOverflow: "ellipsis" }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
        color: color ?? "var(--lys-text)", lineHeight: 1.25 }}>{value}</div>
      {sub && <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
        color: color ?? "var(--lys-text-faint)" }}>{sub}</div>}
    </div>
  );
}

export function MetricBar({ label, value, band, valueLabel, invert }: {
  label: string; value: number; band?: string; valueLabel?: string;
  invert?: boolean;  // for risk bars: show ↓ and keep colour semantics
}) {
  const col = band ? bandColor(band) : "var(--lys-accent)";
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between",
        fontSize: 8.5, fontFamily: "var(--lys-font-mono)", marginBottom: 2 }}>
        <span style={{ color: "var(--lys-text-faint)", textTransform: "uppercase",
          letterSpacing: "0.03em" }}>{label}{invert ? " ↓" : ""}</span>
        <span style={{ color: col, fontWeight: 700 }}>
          {valueLabel ?? value.toFixed(2)}{band ? ` ${band}` : ""}</span>
      </div>
      <div style={{ height: 6, borderRadius: 3, background: "rgba(0,0,0,0.06)",
        overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: col,
          transition: "width 0.3s" }} />
      </div>
    </div>
  );
}

export function BandPill({ band, children }: { band: string; children?: ReactNode }) {
  const col = bandColor(band);
  return (
    <span style={{
      fontSize: 8.5, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.04em", textTransform: "uppercase",
      padding: "1px 7px", borderRadius: 999,
      background: col + "1f", color: col, border: `1px solid ${col}55`,
    }}>{children ?? band}</span>
  );
}

export function ProvenanceBadge({ real, label }: { real: boolean; label: string }) {
  const col = real ? "#047857" : "#64748b";
  return (
    <span title={real ? "Real model / dataset" : "Heuristic / offline"} style={{
      fontSize: 8, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.03em", padding: "1px 6px", borderRadius: 999,
      background: real ? "rgba(16,185,129,0.12)" : "rgba(148,163,184,0.16)",
      color: col, border: `1px solid ${real ? "rgba(16,185,129,0.4)" : "rgba(148,163,184,0.3)"}`,
      whiteSpace: "nowrap",
    }}>{real ? "● " : "○ "}{label}</span>
  );
}

export function SectionLabel({ children, color }: { children: ReactNode; color?: string }) {
  return (
    <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
      letterSpacing: "0.06em", textTransform: "uppercase",
      color: color ?? "var(--lys-text-faint)", marginBottom: 4 }}>{children}</div>
  );
}

export function EmptyState({ icon, msg }: { icon?: ReactNode; msg: string }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
      alignItems: "center", justifyContent: "center", padding: 20,
      textAlign: "center", color: "var(--lys-text-faint)", fontSize: 11 }}>
      {icon}
      <div style={{ maxWidth: 320, lineHeight: 1.5 }}>{msg}</div>
    </div>
  );
}

/**
 * LiveNavbar — session + event-kind filters for the Live container.
 *
 * Buttons:
 *   EVENT section — toggle which event kinds show in SessionTrace
 *     [⊕ All]
 *     [✎ Edit]
 *     [⊕ Score]
 *     [🤖 Agent]
 *
 *   SESSION section — refresh, scroll-to-latest, clear filters
 *     [↻ Refresh]
 *     [⤓ Latest]
 */
import { Activity, Edit3, Target, Bot, RefreshCw, ChevronsDown } from "lucide-react";

interface Props {
  eventKindFilter: string;
  onEventKindChange: (kind: string) => void;
  onRefresh?: () => void;
  onScrollLatest?: () => void;
}

export function LiveNavbar(p: Props) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-mono)" }}>
      <Section label="EVENT" />
      <NavBtn icon={<Activity size={13} style={{ color: !p.eventKindFilter ? "white" : "#0891b2" }} />}
        label="all" title="All event kinds"
        active={!p.eventKindFilter} accent="#0891b2"
        onClick={() => p.onEventKindChange("")} />
      <NavBtn icon={<Edit3 size={13} style={{ color: p.eventKindFilter === "edit" ? "white" : "#f59e0b" }} />}
        label="Edit" title="Molecule edit events"
        active={p.eventKindFilter === "edit"} accent="#f59e0b"
        onClick={() => p.onEventKindChange(p.eventKindFilter === "edit" ? "" : "edit")} />
      <NavBtn icon={<Target size={13} style={{ color: p.eventKindFilter === "score" ? "white" : "#0891b2" }} />}
        label="Score" title="Score snapshot events"
        active={p.eventKindFilter === "score"} accent="#0891b2"
        onClick={() => p.onEventKindChange(p.eventKindFilter === "score" ? "" : "score")} />
      <NavBtn icon={<Bot size={13} style={{ color: p.eventKindFilter === "agent" ? "white" : "#8b5cf6" }} />}
        label="Agent" title="Agent action events"
        active={p.eventKindFilter === "agent"} accent="#8b5cf6"
        onClick={() => p.onEventKindChange(p.eventKindFilter === "agent" ? "" : "agent")} />

      <Section label="LIVE" />
      <NavBtn icon={<RefreshCw size={13} style={{ color: "#10b981" }} />}
        label="Sync" title="Force refresh"
        accent="#10b981" onClick={() => p.onRefresh?.()} />
      <NavBtn icon={<ChevronsDown size={13} style={{ color: "#6b7280" }} />}
        label="Latest" title="Scroll to most recent event"
        accent="#6b7280" onClick={() => p.onScrollLatest?.()} />
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

/**
 * LiveNavbar — session + event-kind filters for the Live container.
 * Self-explanatory labels.
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
      fontFamily: "var(--lys-font-body)" }}>
      <Section label="Show events" />
      <NavBtn icon={<Activity size={14} style={{ color: !p.eventKindFilter ? "white" : "#0891b2" }} />}
        label="Everything" sub="all event kinds"
        title="No filter — show every event"
        active={!p.eventKindFilter} accent="#0891b2"
        onClick={() => p.onEventKindChange("")} />
      <NavBtn icon={<Edit3 size={14} style={{ color: p.eventKindFilter === "edit" ? "white" : "#f59e0b" }} />}
        label="Edits only" sub="atom + bond changes"
        title="Filter to molecule edits"
        active={p.eventKindFilter === "edit"} accent="#f59e0b"
        onClick={() => p.onEventKindChange(p.eventKindFilter === "edit" ? "" : "edit")} />
      <NavBtn icon={<Target size={14} style={{ color: p.eventKindFilter === "score" ? "white" : "#0891b2" }} />}
        label="Scores only" sub="reward snapshots"
        title="Filter to score events"
        active={p.eventKindFilter === "score"} accent="#0891b2"
        onClick={() => p.onEventKindChange(p.eventKindFilter === "score" ? "" : "score")} />
      <NavBtn icon={<Bot size={14} style={{ color: p.eventKindFilter === "agent" ? "white" : "#8b5cf6" }} />}
        label="Agents only" sub="reasoning + msgs"
        title="Filter to agent events"
        active={p.eventKindFilter === "agent"} accent="#8b5cf6"
        onClick={() => p.onEventKindChange(p.eventKindFilter === "agent" ? "" : "agent")} />

      <Section label="Live controls" />
      <NavBtn icon={<RefreshCw size={14} style={{ color: "#10b981" }} />}
        label="Sync now" sub="force refresh"
        title="Force-refresh all polling cards"
        accent="#10b981" onClick={() => p.onRefresh?.()} />
      <NavBtn icon={<ChevronsDown size={14} style={{ color: "#6b7280" }} />}
        label="Latest" sub="scroll to newest"
        title="Scroll to most recent event"
        accent="#6b7280" onClick={() => p.onScrollLatest?.()} />
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

/**
 * AgentsNavbar — agent + action-type filters for the Agents container.
 * Self-explanatory labels for non-chem users.
 */

interface Props {
  agentFilter: string;
  onAgentChange: (agent: string) => void;
  actionFilter: string;
  onActionChange: (action: string) => void;
}

const AGENTS: Array<{ key: string; label: string; sub: string; emoji: string; color: string }> = [
  { key: "",            label: "All agents",  sub: "show every actor", emoji: "👥", color: "#6b7280" },
  { key: "designer",    label: "Designer",    sub: "creates new mols", emoji: "✏️", color: "#10b981" },
  { key: "critic",      label: "Critic",      sub: "finds weaknesses", emoji: "🔍", color: "#ef4444" },
  { key: "editor",      label: "Editor",      sub: "applies SAR edits", emoji: "✂️", color: "#3b82f6" },
  { key: "strategist",  label: "Strategist",  sub: "directs the loop", emoji: "🎯", color: "#8b5cf6" },
  { key: "orchestrator", label: "Orchestrator", sub: "coordinates all", emoji: "🧠", color: "#f59e0b" },
];

const ACTIONS: Array<{ key: string; label: string; sub: string; color: string }> = [
  { key: "",         label: "All actions",  sub: "every event type", color: "#6b7280" },
  { key: "propose",  label: "Propose",      sub: "new candidate",    color: "#10b981" },
  { key: "critique", label: "Critique",     sub: "weakness flagged", color: "#ef4444" },
  { key: "edit",     label: "Edit",         sub: "atom-level fix",   color: "#3b82f6" },
  { key: "decide",   label: "Decide",       sub: "accept / reject",  color: "#f59e0b" },
  { key: "explain",  label: "Explain",      sub: "rationale dump",   color: "#0891b2" },
  { key: "score",    label: "Score",        sub: "12-axis snapshot", color: "#7c3aed" },
];

export function AgentsNavbar(p: Props) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-body)" }}>
      <Section label="Filter by agent" />
      {AGENTS.map((a) => (
        <NavBtn key={a.key || "all-ag"}
          emoji={a.emoji} label={a.label} sub={a.sub}
          title={a.key || "no filter — show every agent"}
          active={p.agentFilter === a.key} accent={a.color}
          onClick={() => p.onAgentChange(a.key)} />
      ))}

      <Section label="Filter by action" />
      {ACTIONS.map((a) => (
        <NavBtn key={a.key || "all-act"}
          emoji={null} label={a.label} sub={a.sub}
          title={a.key || "no filter — show every action type"}
          active={p.actionFilter === a.key} accent={a.color}
          onClick={() => p.onActionChange(a.key)} />
      ))}
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

function NavBtn({ emoji, label, sub, title, onClick, accent, active }: {
  emoji: string | null; label: string; sub?: string; title?: string;
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
        fontSize: 14, lineHeight: 1, flexShrink: 0,
      }}>{emoji ?? "·"}</span>
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

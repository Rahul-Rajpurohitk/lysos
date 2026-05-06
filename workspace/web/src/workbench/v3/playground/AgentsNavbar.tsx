/**
 * AgentsNavbar — agent + action-type filters for the Agents container.
 *
 * Buttons:
 *   AGENT section — toggle filter to one agent (or "all")
 *     [✏ Designer]
 *     [🔍 Critic]
 *     [✂ Editor]
 *     [🎯 Strategist]
 *     [🧠 Orch]
 *
 *   ACTION section — toggle filter by action type
 *     [+ Propose]
 *     [! Critique]
 *     [↻ Edit]
 *     [✓ Decide]
 */

interface Props {
  agentFilter: string;
  onAgentChange: (agent: string) => void;
  actionFilter: string;
  onActionChange: (action: string) => void;
}

const AGENTS: Array<{ key: string; label: string; emoji: string; color: string }> = [
  { key: "",            label: "all",   emoji: "·", color: "#6b7280" },
  { key: "designer",    label: "Dsgn",  emoji: "✏", color: "#10b981" },
  { key: "critic",      label: "Crit",  emoji: "🔍", color: "#ef4444" },
  { key: "editor",      label: "Edit",  emoji: "✂", color: "#3b82f6" },
  { key: "strategist",  label: "Strat", emoji: "🎯", color: "#8b5cf6" },
  { key: "orchestrator", label: "Orch", emoji: "🧠", color: "#f59e0b" },
];

const ACTIONS: Array<{ key: string; label: string; color: string }> = [
  { key: "",         label: "all",   color: "#6b7280" },
  { key: "propose",  label: "Pro",   color: "#10b981" },
  { key: "critique", label: "Crit",  color: "#ef4444" },
  { key: "edit",     label: "Edt",   color: "#3b82f6" },
  { key: "decide",   label: "Dec",   color: "#f59e0b" },
  { key: "explain",  label: "Exp",   color: "#0891b2" },
  { key: "score",    label: "Scr",   color: "#7c3aed" },
];

export function AgentsNavbar(p: Props) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-mono)" }}>
      <Section label="AGENT" />
      {AGENTS.map((a) => (
        <NavBtn key={a.key || "all"}
          emoji={a.emoji} label={a.label} title={a.key || "all agents"}
          active={p.agentFilter === a.key} accent={a.color}
          onClick={() => p.onAgentChange(a.key)} />
      ))}

      <Section label="ACTION" />
      {ACTIONS.map((a) => (
        <NavBtn key={a.key || "all-act"}
          emoji={null} label={a.label} title={a.key || "all action types"}
          active={p.actionFilter === a.key} accent={a.color}
          onClick={() => p.onActionChange(a.key)} />
      ))}
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

function NavBtn({ emoji, label, title, onClick, accent, active }: {
  emoji: string | null; label: string; title?: string;
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
      {emoji && <span style={{ fontSize: 14, lineHeight: 1 }}>{emoji}</span>}
      <span style={{ fontSize: 8.5, fontWeight: 600,
        color: active ? "white" : "var(--lys-text)" }}>{label}</span>
    </button>
  );
}

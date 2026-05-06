/**
 * AgentFilterStrip — text-only filter chips, 24px tall.
 *
 * Reasoning:
 *  - Replaces the avatar+label+circle chip layout (60px tall, profile-card
 *    feel). Real research/tool products use compact tab-style filters.
 *  - Each chip = colored dot + agent name + count; click toggles filter.
 *  - "all N" is the default state; clicking an agent narrows to that lane.
 *  - SubAgentPicker mounts inline at the end (still a + popover; users
 *    rarely need it but it's discoverable).
 *  - No avatars, no count badges in pill bubbles, no border boxes.
 */
// SubAgentPicker (+ button popover) removed per redesign — dead weight in
// the new flat layout; sub-agent selection now happens via /spawn-* slash
// commands.
import { agentColor } from "./AgentAvatar";

interface AgentFilterStripProps {
  counts: Record<string, number>;
  total: number;
  active: string | null;
  onSelect: (a: string | null) => void;
  speaking: Set<string>;
  subAgents: string[];
  onToggleSubAgent: (id: string) => void;
}

const AGENTS = ["designer", "critic", "editor", "strategist", "user"];

export function AgentFilterStrip(p: AgentFilterStripProps) {
  // Show the row only when there's actually something to filter.
  // The "all" chip + the SubAgentPicker (+) button were dead weight per
  // user feedback — removed.
  const hasActiveAgents = AGENTS.some((a) => (p.counts[a] ?? 0) > 0);
  if (!hasActiveAgents) return null;

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      gap: 2,
      padding: "0 10px",
      height: 22,
      borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      overflowX: "auto",
      flexShrink: 0,
    }}>
      {AGENTS.map((a) => {
        const count = p.counts[a] ?? 0;
        if (count === 0) return null;
        return (
          <FilterChip
            key={a}
            label={a}
            count={count}
            color={agentColor(a)}
            active={p.active === a}
            speaking={p.speaking.has(a)}
            onClick={() => p.onSelect(p.active === a ? null : a)}
          />
        );
      })}
    </div>
  );
}

function FilterChip({ label, count, color, active, speaking, onClick }: {
  label: string;
  count: number;
  color?: string;
  active: boolean;
  speaking?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "0 10px",
        height: 22,
        marginRight: 2,
        border: 0,
        borderRadius: 4,
        background: active ? "var(--lys-surface-2)" : "transparent",
        color: active ? "var(--lys-text)" : "var(--lys-text-dim)",
        fontFamily: "inherit",
        fontSize: 11.5,
        cursor: "pointer",
        transition: "background 0.12s, color 0.12s",
        position: "relative",
      }}
      onMouseEnter={(e) => {
        if (!active) e.currentTarget.style.color = "var(--lys-text)";
      }}
      onMouseLeave={(e) => {
        if (!active) e.currentTarget.style.color = "var(--lys-text-dim)";
      }}
    >
      {color && (
        <span
          style={{
            width: 6,
            height: 6,
            borderRadius: 3,
            background: color,
            display: "inline-block",
            boxShadow: speaking ? `0 0 0 3px ${color}40` : "none",
            transition: "box-shadow 0.2s",
          }}
        />
      )}
      <span>{label}</span>
      <span style={{
        fontSize: 10,
        fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)",
        marginLeft: 1,
      }}>
        {count}
      </span>
    </button>
  );
}

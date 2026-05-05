import { MessageBubble } from "./MessageBubble";

interface AgentColumnsProps {
  events: any[];
  agents?: string[];
}

const AGENTS = ["designer", "critic", "editor", "strategist"] as const;

const AGENT_COLORS: Record<string, string> = {
  designer: "#34d399",
  critic: "#f87171",
  editor: "#60a5fa",
  strategist: "#a78bfa",
  user: "#fbbf24",
  system: "#8b949e",
};

export function MultiAgentColumns({ events, agents }: AgentColumnsProps) {
  const cols = agents ?? [...AGENTS];
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: `repeat(${cols.length}, minmax(200px, 1fr))`,
      gap: 8,
      height: "100%",
      overflow: "hidden",
    }}>
      {cols.map((a) => {
        const agentEvents = events.filter(
          (e) => (e.agent ?? "").toLowerCase() === a.toLowerCase()
        );
        return (
          <div
            key={a}
            style={{
              display: "flex",
              flexDirection: "column",
              borderRight: "1px solid var(--lys-border)",
              minHeight: 0,
            }}
          >
            <div style={{
              padding: "8px 10px",
              borderBottom: "1px solid var(--lys-border)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
            }}>
              <span style={{
                fontSize: 11,
                color: AGENT_COLORS[a] ?? "#888",
                fontWeight: 600,
                textTransform: "uppercase",
                letterSpacing: "0.05em",
              }}>
                {a}
              </span>
              <span style={{
                fontSize: 10,
                color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)",
              }}>
                {agentEvents.length}
              </span>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: 8, display: "flex", flexDirection: "column", gap: 8 }}>
              {agentEvents.length === 0 && (
                <div style={{ padding: 16, fontSize: 11, color: "var(--lys-text-faint)", textAlign: "center" }}>
                  no messages yet
                </div>
              )}
              {agentEvents.map((e, i) => (
                <MessageBubble
                  key={i}
                  agent={a}
                  agentColor={AGENT_COLORS[a] ?? "#888"}
                  ts={e.ts}
                  content={contentFor(e)}
                  thinking={e.thinking}
                />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function contentFor(e: any): string {
  if (e.content) return e.content;
  if (e.type === "tool_call_result") return `→ ${e.tool ?? "tool"}`;
  if (e.type === "candidate_added") return `★ added candidate ${e.smiles ?? ""}`;
  if (e.type === "state_change") return `${e.decision} — ${e.reason ?? ""}`;
  if (e.type === "mol_edit") return `${(e.parent ?? "").slice(0, 24)} → ${(e.candidate ?? "").slice(0, 24)}`;
  return JSON.stringify(e);
}

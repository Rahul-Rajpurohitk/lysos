/**
 * AgentReasoningTraceWindow — 4 sticky-note rectangles, one per agent.
 *
 * Each note shows the agent's latest message + a thinking pulse if that
 * agent is "currently active" (i.e. last message in events stream is
 * from them and timestamp is within 2 seconds).
 *
 * The notes use the agent's color signature (designer green / critic red /
 * editor blue / strategist purple) for the left bar and label.
 */
import { agentColor } from "../components/chat/AgentAvatar";

interface ChatLikeEvent {
  type: string;
  ts: number;
  agent?: string;
  content?: string;
  iteration?: number;
}

interface Props {
  events: ChatLikeEvent[];
}

const AGENTS = ["designer", "critic", "editor", "strategist"] as const;

export function AgentReasoningTraceWindow({ events }: Props) {
  // For each agent: latest message and whether they're "currently active"
  const now = Date.now() / 1000;
  const lastByAgent: Record<string, ChatLikeEvent | undefined> = {};
  for (const e of events) {
    if (!e.agent) continue;
    const a = e.agent.toLowerCase();
    if (!AGENTS.includes(a as any)) continue;
    if (!lastByAgent[a] || (e.ts ?? 0) > (lastByAgent[a]!.ts ?? 0)) {
      lastByAgent[a] = e;
    }
  }
  const lastEverAgent = events.slice().reverse().find((e) => e.agent && AGENTS.includes(e.agent.toLowerCase() as any))?.agent?.toLowerCase();

  return (
    <div style={{
      width: "100%",
      height: "100%",
      overflow: "auto",
      padding: 8,
      display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gap: 8,
      fontFamily: "var(--lys-font-body)",
    }}>
      {AGENTS.map((agent) => {
        const last = lastByAgent[agent];
        const active = lastEverAgent === agent && last && now - last.ts < 2;
        const color = agentColor(agent);
        return (
          <div
            key={agent}
            style={{
              background: "var(--lys-surface, #ffffff)",
              borderRadius: 8,
              padding: "8px 10px",
              borderLeft: `3px solid ${color}`,
              display: "flex",
              flexDirection: "column",
              gap: 4,
              minHeight: 90,
              boxShadow: active
                ? `0 0 0 1px ${color}40, 0 4px 12px ${color}20`
                : "none",
              transition: "box-shadow 0.2s",
            }}
          >
            <div style={{
              display: "flex",
              alignItems: "center",
              gap: 6,
            }}>
              <span style={{
                fontSize: 10,
                fontWeight: 600,
                color,
                textTransform: "lowercase",
              }}>
                {agent}
              </span>
              {active && (
                <span style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 3,
                  fontSize: 8.5,
                  fontFamily: "var(--lys-font-mono)",
                  color,
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}>
                  <span style={{
                    width: 5, height: 5, borderRadius: 5, background: color,
                    animation: "lys-pulse 1.2s infinite",
                  }} />
                  thinking
                </span>
              )}
              <span style={{ flex: 1 }} />
              {last?.iteration != null && last.iteration > 0 && (
                <span style={{
                  fontSize: 8.5,
                  fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)",
                }}>
                  iter {last.iteration}
                </span>
              )}
            </div>
            <div style={{
              fontSize: 11,
              color: "var(--lys-text)",
              lineHeight: 1.4,
              flex: 1,
              overflow: "hidden",
              display: "-webkit-box",
              WebkitLineClamp: 6,
              WebkitBoxOrient: "vertical",
            }}>
              {last?.content || (
                <span style={{ color: "var(--lys-text-faint)", fontStyle: "italic" }}>
                  awaiting first message…
                </span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

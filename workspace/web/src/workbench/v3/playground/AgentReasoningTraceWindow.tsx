/**
 * AgentReasoningTraceWindow — full reasoning chain per agent.
 *
 * Replaces the "latest message only" stub with the actual think → tool-call
 * → result → next-think sequence per agent. The user sees what each
 * specialist actually did, not just their last sentence.
 *
 * Event sources (all already emitted by the harness):
 *   - agent_message       — assistant turn text (agent + content)
 *   - tool_call_result    — tool name + args + result (agent + data)
 *   - best_of_n_explored  — Best-of-N exploration: list of (composite, smiles)
 *
 * Layout: 2×2 grid, one column per agent role. Each column scrolls
 * independently. Newest event auto-scrolls into view.
 */
import { useMemo, useRef, useEffect, useState } from "react";
import { agentColor } from "../components/chat/AgentAvatar";
import { ChevronRight, ChevronDown, Wrench } from "lucide-react";

interface ChatLikeEvent {
  type: string;
  ts: number;
  agent?: string;
  content?: string;
  iteration?: number;
  data?: any;
  // tool_call_result fields:
  // data.tool, data.args, data.result, data.error, data.duration_ms
  // best_of_n_explored fields:
  // n, scores: [{composite, smiles, selected}]
  n?: number;
  scores?: { composite: number; smiles: string; selected: boolean }[];
}

interface Props {
  events: ChatLikeEvent[];
}

const AGENTS = ["designer", "critic", "editor", "strategist"] as const;
type AgentName = typeof AGENTS[number];

// What kinds of events go into a given agent's column.
function eventAgent(e: ChatLikeEvent): string | null {
  if (e.agent) return e.agent.toLowerCase();
  if (e.data?.agent) return String(e.data.agent).toLowerCase();
  return null;
}

interface ChainEntry {
  kind: "think" | "tool" | "boN";
  ts: number;
  text?: string;
  iteration?: number;
  toolName?: string;
  toolArgs?: any;
  toolResult?: any;
  toolError?: string;
  toolDurationMs?: number;
  boNExplored?: { composite: number; smiles: string; selected: boolean }[];
}

function buildChain(events: ChatLikeEvent[], agent: AgentName): ChainEntry[] {
  const out: ChainEntry[] = [];
  for (const e of events) {
    const ag = eventAgent(e);
    if (ag !== agent) continue;
    if (e.type === "agent_message") {
      const text = e.content ?? e.data?.content ?? "";
      if (!text) continue;
      out.push({
        kind: "think",
        ts: e.ts ?? 0,
        text,
        iteration: e.iteration ?? e.data?.iteration,
      });
    } else if (e.type === "tool_call_result") {
      out.push({
        kind: "tool",
        ts: e.ts ?? 0,
        toolName: e.data?.tool ?? "?",
        toolArgs: e.data?.args ?? {},
        toolResult: e.data?.result,
        toolError: e.data?.error,
        toolDurationMs: e.data?.duration_ms,
      });
    } else if (e.type === "best_of_n_explored") {
      out.push({
        kind: "boN",
        ts: e.ts ?? 0,
        boNExplored: e.scores ?? [],
      });
    }
  }
  out.sort((a, b) => a.ts - b.ts);

  // Dedup consecutive identical think-text from the same agent. The
  // workflow re-ran 4 times → the same critic narration appeared 4
  // times in the trace. Collapse them and surface "·×N" so the user
  // knows it happened more than once without scrolling through dups.
  const collapsed: ChainEntry[] = [];
  for (const entry of out) {
    const prev = collapsed[collapsed.length - 1];
    if (
      prev
      && prev.kind === "think"
      && entry.kind === "think"
      && (prev.text || "").trim() === (entry.text || "").trim()
    ) {
      // Collapse — bump a `repeat` counter on the last entry.
      (prev as any).repeat = ((prev as any).repeat ?? 1) + 1;
      // Carry the latest ts so the entry stays "fresh" for auto-scroll.
      prev.ts = entry.ts;
      continue;
    }
    collapsed.push({ ...entry });
  }
  return collapsed;
}

export function AgentReasoningTraceWindow({ events }: Props) {
  const lastEverAgent = useMemo(() => {
    return events.slice().reverse().find((e) => eventAgent(e) && AGENTS.includes(eventAgent(e) as AgentName))?.agent?.toLowerCase();
  }, [events]);

  return (
    <div style={{
      width: "100%", height: "100%", overflow: "hidden",
      padding: 6, display: "grid",
      gridTemplateColumns: "1fr 1fr",
      gridTemplateRows: "1fr 1fr",
      gap: 6, fontFamily: "var(--lys-font-body)",
    }}>
      {AGENTS.map((agent) => (
        <AgentColumn
          key={agent}
          agent={agent}
          events={events}
          isCurrent={lastEverAgent === agent}
        />
      ))}
    </div>
  );
}

function AgentColumn({ agent, events, isCurrent }: {
  agent: AgentName;
  events: ChatLikeEvent[];
  isCurrent: boolean;
}) {
  const chain = useMemo(() => buildChain(events, agent), [events, agent]);
  const c = agentColor(agent);
  const scrollRef = useRef<HTMLDivElement>(null);
  // Auto-scroll to bottom when new entries arrive
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [chain.length]);

  return (
    <div style={{
      background: "var(--lys-surface, #ffffff)",
      borderRadius: 6,
      borderLeft: `3px solid ${c}`,
      display: "flex", flexDirection: "column",
      minHeight: 0, overflow: "hidden",
      boxShadow: isCurrent ? `0 0 0 1px ${c}40, 0 4px 12px ${c}20` : "none",
      transition: "box-shadow 0.2s",
    }}>
      <div style={{
        padding: "5px 8px",
        display: "flex", alignItems: "center", gap: 6,
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        background: `${c}06`,
      }}>
        <span style={{
          fontSize: 10, fontWeight: 700, color: c,
          textTransform: "lowercase",
          fontFamily: "var(--lys-font-mono)", letterSpacing: "0.04em",
        }}>{agent}</span>
        {isCurrent && (
          <>
            <span style={{
              width: 5, height: 5, borderRadius: 5, background: c,
              animation: "lys-pulse 1.2s infinite",
            }} />
            <span style={{ fontSize: 8.5, color: c, fontFamily: "var(--lys-font-mono)",
              letterSpacing: "0.04em", textTransform: "uppercase", fontWeight: 700 }}>
              active
            </span>
          </>
        )}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)" }}>
          {chain.length} step{chain.length === 1 ? "" : "s"}
        </span>
      </div>
      <div ref={scrollRef} style={{
        flex: 1, overflow: "auto", padding: "5px 6px",
        display: "flex", flexDirection: "column", gap: 4,
        minHeight: 0,
      }}>
        {chain.length === 0 && (
          <div style={{
            padding: "8px 4px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 9.5,
            fontFamily: "var(--lys-font-mono)", fontStyle: "italic",
          }}>
            awaiting first action…
          </div>
        )}
        {chain.map((entry, idx) => (
          <ChainEntryCard key={`${agent}-${idx}-${entry.ts}`} entry={entry} accent={c} />
        ))}
      </div>
    </div>
  );
}

function ChainEntryCard({ entry, accent }: { entry: ChainEntry; accent: string }) {
  const [expanded, setExpanded] = useState(false);

  if (entry.kind === "think") {
    return (
      <div style={{
        padding: "4px 6px", borderRadius: 4,
        background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
        fontSize: 10, lineHeight: 1.4, color: "var(--lys-text)",
      }}>
        {entry.iteration != null && entry.iteration > 0 && (
          <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)",
            letterSpacing: "0.04em", textTransform: "uppercase",
            marginBottom: 1, fontWeight: 700 }}>
            iter {entry.iteration}
          </div>
        )}
        {(entry as any).repeat && (entry as any).repeat > 1 && (
          <span style={{
            display: "inline-block",
            padding: "1px 6px",
            background: accent + "20",
            color: accent,
            borderRadius: 999,
            fontSize: 9,
            fontWeight: 700,
            fontFamily: "var(--lys-font-mono)",
            marginBottom: 3,
            letterSpacing: "0.04em",
          }} title="This reasoning fired multiple times — collapsed to keep the trace clean">
            ·×{(entry as any).repeat}
          </span>
        )}
        <div style={{
          display: "-webkit-box",
          WebkitLineClamp: expanded ? undefined : 4,
          WebkitBoxOrient: "vertical",
          overflow: "hidden",
          whiteSpace: "pre-wrap",
        }}>
          {entry.text}
        </div>
        {(entry.text?.length ?? 0) > 200 && (
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              border: 0, background: "transparent", padding: 0, marginTop: 2,
              cursor: "pointer", fontSize: 8.5, color: accent,
              fontFamily: "var(--lys-font-mono)", fontWeight: 700,
            }}>
            {expanded ? "− less" : "+ more"}
          </button>
        )}
      </div>
    );
  }

  if (entry.kind === "tool") {
    const isErr = !!entry.toolError;
    return (
      <div style={{
        padding: "4px 6px", borderRadius: 4,
        background: isErr ? "rgba(220,38,38,0.05)" : "rgba(8,145,178,0.05)",
        borderLeft: `2px solid ${isErr ? "#dc2626" : "#0891b2"}`,
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      }}>
        <div onClick={() => setExpanded(!expanded)}
          style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
          {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
          <Wrench size={9} style={{ color: isErr ? "#dc2626" : "#0891b2" }} />
          <span style={{ fontWeight: 700, color: isErr ? "#dc2626" : "#0891b2" }}>
            {entry.toolName}
          </span>
          {entry.toolDurationMs != null && (
            <span style={{ marginLeft: "auto", fontSize: 8, color: "var(--lys-text-faint)" }}>
              {entry.toolDurationMs}ms
            </span>
          )}
        </div>
        {expanded && (
          <div style={{ marginTop: 3, paddingLeft: 14, fontSize: 9 }}>
            <div style={{ color: "var(--lys-text-faint)", fontWeight: 700, fontSize: 8,
              letterSpacing: "0.04em", textTransform: "uppercase", marginBottom: 1 }}>
              input
            </div>
            <pre style={{
              margin: 0, padding: "3px 5px",
              background: "rgba(0,0,0,0.04)", borderRadius: 3,
              fontSize: 9, maxHeight: 80, overflow: "auto",
              whiteSpace: "pre-wrap", wordBreak: "break-word",
            }}>{JSON.stringify(entry.toolArgs, null, 2)}</pre>
            <div style={{ color: "var(--lys-text-faint)", fontWeight: 700, fontSize: 8,
              letterSpacing: "0.04em", textTransform: "uppercase",
              marginTop: 4, marginBottom: 1 }}>
              {isErr ? "error" : "result"}
            </div>
            <pre style={{
              margin: 0, padding: "3px 5px",
              background: isErr ? "rgba(220,38,38,0.06)" : "rgba(0,0,0,0.04)",
              borderRadius: 3, color: isErr ? "#dc2626" : "var(--lys-text)",
              fontSize: 9, maxHeight: 100, overflow: "auto",
              whiteSpace: "pre-wrap", wordBreak: "break-word",
            }}>{isErr ? entry.toolError : JSON.stringify(entry.toolResult, null, 2)?.slice(0, 800)}</pre>
          </div>
        )}
      </div>
    );
  }

  // boN (best-of-N exploration)
  return (
    <div style={{
      padding: "4px 6px", borderRadius: 4,
      background: "rgba(16,185,129,0.05)",
      borderLeft: "2px solid #10b981",
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
    }}>
      <div onClick={() => setExpanded(!expanded)}
        style={{ display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
        {expanded ? <ChevronDown size={10} /> : <ChevronRight size={10} />}
        <span style={{ fontWeight: 700, color: "#059669" }}>
          best-of-{entry.boNExplored?.length ?? 0}
        </span>
        {entry.boNExplored && entry.boNExplored.length > 0 && (
          <span style={{ marginLeft: "auto", fontSize: 8, color: "var(--lys-text-faint)" }}>
            top {entry.boNExplored[0].composite.toFixed(3)}
          </span>
        )}
      </div>
      {expanded && entry.boNExplored && (
        <div style={{ marginTop: 3, paddingLeft: 14 }}>
          {entry.boNExplored.map((s, i) => (
            <div key={i} style={{
              display: "flex", gap: 4, fontSize: 9, padding: "1px 0",
              color: s.selected ? "#059669" : "var(--lys-text-dim)",
              fontWeight: s.selected ? 700 : 500,
            }}>
              <span style={{ minWidth: 14 }}>{s.selected ? "→" : ""}</span>
              <span style={{ minWidth: 36 }}>{s.composite.toFixed(3)}</span>
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis",
                whiteSpace: "nowrap" }}>{s.smiles.slice(0, 50)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

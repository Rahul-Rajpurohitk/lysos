import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { ArrowDownCircle } from "lucide-react";

import { AgentChipRow } from "./AgentChipRow";
import { MessageCard, ChatMsg } from "./MessageCard";
import { IterationDivider } from "./IterationDivider";
import { TypingIndicator } from "./TypingIndicator";

interface ChatPanelProps {
  events: ChatMsg[];                 // raw event stream — full
  isRunning: boolean;
  showOnboarding: React.ReactNode;    // hero shown when no session
  composer: React.ReactNode;          // composer mounted at the bottom
  modeToggle: React.ReactNode;        // stream/columns toggle
  totalMsgs: number;
  replayBadge?: React.ReactNode;
  onLoadSmiles: (smi: string) => void;
  subAgents: string[];
  onToggleSubAgent: (id: string) => void;
}

export function ChatPanel(p: ChatPanelProps) {
  const [filterAgent, setFilterAgent] = useState<string | null>(null);
  const [autoScroll, setAutoScroll] = useState(true);
  const messagesRef = useRef<HTMLDivElement | null>(null);
  const lastScrollPos = useRef(0);

  // Build the rendered timeline:
  //  - filter out structural events (iteration_start/end go into dividers)
  //  - attach tool_call_result/error to the previous agent_message of same agent
  //  - inject IterationDivider rows between iters
  const timeline = useMemo(() => buildTimeline(p.events), [p.events]);

  const agentCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const e of p.events) {
      const a = (e.agent ?? "").toLowerCase();
      if (!a) continue;
      m[a] = (m[a] ?? 0) + 1;
    }
    return m;
  }, [p.events]);

  // Currently "speaking" agents — those that have a message in the last 1.5s
  const speakingAgents = useMemo(() => {
    const now = Date.now() / 1000;
    const set = new Set<string>();
    for (const e of p.events) {
      if (now - e.ts < 1.5 && e.agent) set.add(e.agent.toLowerCase());
    }
    return set;
  }, [p.events]);

  // Last agent that produced a message — used for typing indicator placement
  const lastAgent = useMemo(() => {
    if (!p.isRunning) return null;
    for (let i = p.events.length - 1; i >= 0; i--) {
      const e = p.events[i];
      if (e.type === "agent_message" && e.agent) return e.agent;
    }
    return null;
  }, [p.events, p.isRunning]);

  // Filtered timeline
  const filtered = useMemo(() => {
    if (!filterAgent) return timeline;
    return timeline.filter((row) => {
      if (row.kind === "iter_divider") return true;
      const a = (row.msg.agent ?? "").toLowerCase();
      return a === filterAgent;
    });
  }, [timeline, filterAgent]);

  // Auto-scroll on new events when user is near bottom
  useEffect(() => {
    const el = messagesRef.current;
    if (!el || !autoScroll) return;
    el.scrollTop = el.scrollHeight;
  }, [filtered.length, autoScroll]);

  function onScroll() {
    const el = messagesRef.current;
    if (!el) return;
    const distFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
    setAutoScroll(distFromBottom < 80);
    lastScrollPos.current = el.scrollTop;
  }

  function jumpToLatest() {
    const el = messagesRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setAutoScroll(true);
  }

  return (
    <div className="lys-chat">
      <div className="lys-chat__head">
        <span className="lys-chat__title">
          Conversation · {p.totalMsgs} msg
          {p.replayBadge}
        </span>
        {p.modeToggle}
      </div>

      <AgentChipRow
        counts={agentCounts}
        active={filterAgent}
        onSelect={setFilterAgent}
        activeSpeaking={speakingAgents}
        subAgents={p.subAgents}
        onToggleSubAgent={p.onToggleSubAgent}
      />

      <div
        ref={messagesRef}
        onScroll={onScroll}
        style={{
          flex: 1,
          overflowY: "auto",
          position: "relative",
          padding: "12px 16px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
          scrollBehavior: "smooth",
        }}
      >
        {p.totalMsgs === 0 && p.showOnboarding}

        {filtered.map((row, i) => {
          if (row.kind === "iter_divider") {
            return (
              <IterationDivider
                key={`div-${row.iter}`}
                iter={row.iter}
                composite={row.composite}
                delta={row.delta}
                candidatesAdded={row.candidatesAdded}
              />
            );
          }
          return (
            <MessageCard
              key={`${row.msg.id ?? i}-${row.msg.ts}`}
              msg={row.msg}
              toolCalls={row.toolCalls}
              onLoadSmiles={p.onLoadSmiles}
            />
          );
        })}

        {p.isRunning && lastAgent && (
          <AnimatePresence>
            <TypingIndicator agent={lastAgent} label={`${lastAgent} is reasoning…`} />
          </AnimatePresence>
        )}

        {!autoScroll && (
          <button
            onClick={jumpToLatest}
            style={{
              position: "absolute",
              bottom: 16,
              right: 16,
              padding: "6px 10px 6px 8px",
              background: "var(--lys-text)",
              color: "white",
              border: 0,
              borderRadius: 999,
              boxShadow: "var(--lys-shadow-md)",
              fontSize: 11,
              fontWeight: 600,
              fontFamily: "inherit",
              cursor: "pointer",
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
            }}
          >
            <ArrowDownCircle size={14} /> Jump to latest
          </button>
        )}
      </div>

      <div className="lys-chat__composer">{p.composer}</div>
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Build timeline rows: messages enriched with attached tool calls,
// interleaved with iteration dividers.
// ──────────────────────────────────────────────────────────────────────

type TimelineRow =
  | { kind: "msg"; msg: ChatMsg; toolCalls: ChatMsg[] }
  | { kind: "iter_divider"; iter: number; composite: number | null; delta: number | null; candidatesAdded: number };

function buildTimeline(events: ChatMsg[]): TimelineRow[] {
  const rows: TimelineRow[] = [];
  const iterEnd = new Map<number, ChatMsg>();
  let prevIterComposite: number | null = null;
  let lastMsgIdx = -1;
  let pendingIter: number | null = null;

  // Collect candidates per iter for the divider summary
  const candByIter: Record<number, number> = {};
  for (const e of events) {
    if (e.type === "candidate_added" && e.iteration != null) {
      candByIter[e.iteration] = (candByIter[e.iteration] ?? 0) + 1;
    }
    if (e.type === "iteration_end" && e.iteration != null) {
      iterEnd.set(e.iteration, e);
    }
  }

  for (const e of events) {
    // Iteration markers → divider rows
    if (e.type === "iteration_start" && e.iteration != null) {
      pendingIter = e.iteration;
      continue;
    }
    if (e.type === "iteration_end") {
      const iter = e.iteration ?? 0;
      const composite = (e.composite as number | null) ?? null;
      const delta = composite != null && prevIterComposite != null
        ? composite - prevIterComposite
        : null;
      rows.push({
        kind: "iter_divider",
        iter,
        composite,
        delta,
        candidatesAdded: candByIter[iter] ?? 0,
      });
      if (composite != null) prevIterComposite = composite;
      pendingIter = null;
      lastMsgIdx = -1;  // reset tool-call attachment
      continue;
    }

    // Tool call → attach to most recent message in same iter+agent
    if (e.type === "tool_call_result" || e.type === "tool_call_error") {
      if (lastMsgIdx >= 0 && rows[lastMsgIdx].kind === "msg") {
        (rows[lastMsgIdx] as { kind: "msg"; msg: ChatMsg; toolCalls: ChatMsg[] })
          .toolCalls.push(e);
      } else {
        rows.push({
          kind: "msg",
          msg: { ...e, type: "agent_message", content: "→ tool call" },
          toolCalls: [e],
        });
        lastMsgIdx = rows.length - 1;
      }
      continue;
    }

    // Skip raw 'score' events — they show up in the radar, not the chat
    if (e.type === "score" || e.type === "ping") continue;

    // Inject the pending iter divider before the first message of that iter
    if (pendingIter != null) {
      rows.push({
        kind: "iter_divider",
        iter: pendingIter,
        composite: null,
        delta: null,
        candidatesAdded: 0,
      });
      pendingIter = null;
    }

    rows.push({ kind: "msg", msg: e, toolCalls: [] });
    lastMsgIdx = rows.length - 1;
  }

  return rows;
}

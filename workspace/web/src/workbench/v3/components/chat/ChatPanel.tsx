/**
 * ChatPanel — research timeline.
 *
 * Layout reasoning (vertical budget on a 500px panel):
 *   header  32px   — Stream/Columns toggle, iter pill, composite pill
 *   filter  32px   — agent filter strip
 *   stream  flex 1 — messages
 *   composer 56px  — input + chips
 *
 * Total chrome before first message: 64px (down from 124px in v0).
 * That's +60px of message area on the same panel size.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { ArrowDownCircle, Activity } from "lucide-react";

import { AgentFilterStrip } from "./AgentFilterStrip";
import { MessageRow, ChatMsg } from "./MessageRow";
import { IterationDivider } from "./IterationDivider";
import { TypingIndicator } from "./TypingIndicator";
import { ChatTabsBar, ChatTab } from "./ChatTabsBar";
import { RunningProcessesTray, type RunningProcess } from "./RunningProcessesTray";

interface ChatPanelProps {
  events: ChatMsg[];
  isRunning: boolean;
  showOnboarding: React.ReactNode;
  composer: React.ReactNode;
  totalMsgs: number;
  composite?: number | null;
  currentIter?: number;
  totalIters?: number;
  replayBadge?: React.ReactNode;
  onLoadSmiles: (smi: string) => void;
  subAgents: string[];
  onToggleSubAgent: (id: string) => void;
  /** Card-level SSE subscriptions push streamed events here so the global
   *  timeline renders them as individual rows. Wired by WorkbenchV3. */
  onIngestEvent?: (event: ChatMsg) => void;
  // ---- agent message tagging (#91) ----
  onReplyToAgent?: (params: {
    text: string;
    targetAgent: string;
    parentMessageId: string;
    threadId: string;
  }) => void;
  // ---- W4 explain → right-pane artifact ----
  onArtifact?: (params: {
    sessionId: string;
    target: string;
    markdown: string;
    chunks: string[];
    complete: boolean;
    error?: string | null;
    groundingCount?: number;
  }) => void;
  // ---- W7+W8: replay past session in a new tab ----
  onReplaySession?: (params: {
    sessionId: string;
    target: string;
    sseUrl: string;
  }) => void;
  // ---- multi-chat tabs (Claude.ai style) ----
  chatTabs?: ChatTab[];
  activeChatId?: string;
  onSelectChat?: (id: string) => void;
  onCloseChat?: (id: string) => void;
  onCreateChat?: () => void;
  onRenameChat?: (id: string, title: string) => void;
  /** In-flight processes derived from the events stream (agent_run /
   *  workflow_run / orchestrator_run with status=running). Drives the
   *  sticky RunningProcessesTray at the top of the chat. */
  runningProcesses?: RunningProcess[];
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

  // Last NON-USER agent that produced a message — used for typing
  // indicator. Without the user filter we'd show "user is reasoning…"
  // right after the user typed something, which is obviously wrong —
  // it should be an assistant/agent role doing the reasoning.
  const lastAgent = useMemo(() => {
    if (!p.isRunning) return null;
    for (let i = p.events.length - 1; i >= 0; i--) {
      const e = p.events[i];
      if (e.type === "agent_message" && e.agent
          && e.agent.toLowerCase() !== "user") return e.agent;
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
      {/* Multi-chat tabs (Claude.ai style) replace the old "session ready"
          header — no more rubbish-filler space. Live iter + composite pill
          is shown only when a session is actively running. */}
      {p.chatTabs && p.activeChatId && p.onSelectChat && p.onCloseChat && p.onCreateChat ? (
        <div style={{
          display: "flex",
          alignItems: "stretch",
          flexShrink: 0,
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        }}>
          <div style={{ flex: 1, minWidth: 0 }}>
            <ChatTabsBar
              tabs={p.chatTabs}
              activeId={p.activeChatId}
              onSelect={p.onSelectChat}
              onClose={p.onCloseChat}
              onCreate={p.onCreateChat}
              onRename={p.onRenameChat}
            />
          </div>
          {(p.currentIter && p.totalIters) ? (
            <span style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              padding: "2px 10px",
              alignSelf: "center",
              background: "var(--lys-surface-2)",
              borderRadius: 4,
              fontSize: 10.5,
              fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-dim)",
              marginRight: 8,
              flexShrink: 0,
            }}>
              <Activity size={10} color={p.isRunning ? "var(--lys-accent)" : "var(--lys-text-faint)"} />
              iter {p.currentIter}/{p.totalIters}
              {p.composite != null && (
                <>
                  <span style={{ color: "var(--lys-text-faint)" }}>·</span>
                  <span style={{ color: "var(--lys-text)", fontWeight: 600 }}>
                    {p.composite.toFixed(3)}
                  </span>
                </>
              )}
            </span>
          ) : null}
          {p.replayBadge && (
            <span style={{ alignSelf: "center", marginRight: 8 }}>
              {p.replayBadge}
            </span>
          )}
        </div>
      ) : null}

      <AgentFilterStrip
        counts={agentCounts}
        total={p.totalMsgs}
        active={filterAgent}
        onSelect={setFilterAgent}
        speaking={speakingAgents}
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
        {/* Sticky strip at top of stream — fades in when there are
         *  in-flight processes (agent / workflow / orchestrator / score),
         *  fades out when nothing is running. Single source of truth for
         *  "what is the system doing right now." */}
        {p.runningProcesses && p.runningProcesses.length > 0 && (
          <RunningProcessesTray processes={p.runningProcesses} />
        )}
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
              <MessageRow
                key={`${row.msg.id ?? i}-${row.msg.ts}`}
                msg={row.msg}
                toolCalls={row.toolCalls}
                onLoadSmiles={p.onLoadSmiles}
                onIngestEvent={p.onIngestEvent}
                onReplyToAgent={p.onReplyToAgent}
                onArtifact={p.onArtifact}
                onReplaySession={p.onReplaySession}
              />
            );
          })}

        {p.isRunning && lastAgent && (
          <AnimatePresence>
            <TypingIndicator agent={lastAgent} label={`${lastAgent} is reasoning…`} />
          </AnimatePresence>
        )}
      </div>

      {/* Jump-to-latest button — pinned ABOVE the composer (outside the
       *  scroll container) so it stays anchored to the visual bottom of
       *  the chat regardless of how far the user scrolled up. The
       *  earlier position-absolute inside the scroll container floated
       *  to the bottom of the scroll CONTENT, which is below view. */}
      {!autoScroll && (
        <div style={{
          position: "relative",
          height: 0,
          pointerEvents: "none",
        }}>
          <button
            onClick={jumpToLatest}
            title="Jump to latest message"
            style={{
              position: "absolute",
              bottom: 6,
              left: "50%",
              transform: "translateX(-50%)",
              width: 28, height: 28,
              padding: 0,
              background: "var(--lys-text)",
              color: "white",
              border: 0,
              borderRadius: 999,
              boxShadow: "0 4px 12px rgba(0,0,0,0.18)",
              cursor: "pointer",
              display: "grid",
              placeItems: "center",
              opacity: 0.92,
              pointerEvents: "auto",
              transition: "opacity 0.15s, transform 0.15s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.opacity = "1";
              e.currentTarget.style.transform = "translateX(-50%) translateY(-1px)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.opacity = "0.85";
              e.currentTarget.style.transform = "translateX(-50%)";
            }}
          >
            <ArrowDownCircle size={15} />
          </button>
        </div>
      )}

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

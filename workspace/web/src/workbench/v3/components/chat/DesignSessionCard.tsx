/**
 * DesignSessionCard — kicks off the W1 multi-agent debate.
 *
 * Rendered when a /design slash command returns card_kind="design_session".
 * Auto-opens an EventSource (SSE) to /workbench/sessions/{id}/events; every
 * server event is forwarded into the chat timeline via onIngestEvent so the
 * existing MessageRow / IterationDivider components render the live debate.
 *
 * The card itself is a static visual receipt — pathogen, objective, and a
 * "live" badge while events are streaming.
 */
import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Activity, Beaker } from "lucide-react";
import { ChatMsg } from "./MessageRow";

interface DesignSessionCardProps {
  msg: ChatMsg;
  /** Push a streamed event into the global chat timeline. */
  onIngestEvent?: (event: ChatMsg) => void;
}

interface DesignData {
  session_id?: string;
  pathogen?: string;
  objective?: string | null;
  sse_url?: string;
  status?: string;
}

// Track which sessions have already been subscribed to (StrictMode + remount-safe).
const SUBSCRIBED = new Set<string>();

export function DesignSessionCard({ msg, onIngestEvent }: DesignSessionCardProps) {
  const data = (msg.data ?? {}) as DesignData;
  const sessionId = data.session_id ?? "";
  const sseUrl = data.sse_url ?? "";

  const [streaming, setStreaming] = useState(true);
  const [eventCount, setEventCount] = useState(0);
  const onIngestRef = useRef(onIngestEvent);
  onIngestRef.current = onIngestEvent;

  useEffect(() => {
    if (!sessionId || !sseUrl) return;
    if (SUBSCRIBED.has(sessionId)) return;
    SUBSCRIBED.add(sessionId);

    const url = sseUrl.startsWith("http") ? sseUrl : `${window.location.origin}${sseUrl}`;
    const es = new EventSource(url);

    const onMessage = (e: MessageEvent) => {
      try {
        const ev = JSON.parse(e.data ?? "{}");
        // Workbench events arrive as { type, data, agent?, iteration?, ... }
        // Translate into the ChatMsg shape MessageRow consumes.
        const chatMsg: ChatMsg = {
          id: ev.id ?? undefined,
          type: ev.type ?? "agent_message",
          ts: Date.now() / 1000,
          agent: ev.agent ?? ev.data?.role ?? undefined,
          content: ev.data?.content ?? ev.content ?? undefined,
          iteration: ev.iteration ?? ev.data?.iteration ?? undefined,
          smiles: ev.data?.smiles ?? ev.smiles ?? undefined,
          composite: ev.data?.composite ?? ev.composite ?? undefined,
          scores: ev.data?.scores ?? undefined,
        };
        onIngestRef.current?.(chatMsg);
        setEventCount((c) => c + 1);
        if (ev.type === "session_complete" || ev.type === "error") {
          setStreaming(false);
          es.close();
          SUBSCRIBED.delete(sessionId);
        }
      } catch (err) {
        // Bad payload — keep the stream alive but don't drop into the chat
        console.warn("design SSE parse error", err);
      }
    };

    // The workbench SSE emits typed events (event: agent_message, candidate_added, …)
    // PLUS the default "message" channel. Subscribe to both so we don't miss any.
    const types = [
      "message", "agent_message", "candidate_added", "iteration_start",
      "iteration_end", "score", "tool_call_result", "tool_call_error",
      "session_complete", "agent_idle", "error", "intervention_queued",
    ];
    types.forEach((t) => es.addEventListener(t, onMessage as EventListener));
    es.onmessage = onMessage; // fallback for un-typed events

    es.onerror = () => {
      // EventSource will retry on its own. We just visually mark the
      // stream as paused after a hard close.
      if (es.readyState === EventSource.CLOSED) {
        setStreaming(false);
        SUBSCRIBED.delete(sessionId);
      }
    };

    return () => {
      es.close();
      SUBSCRIBED.delete(sessionId);
    };
  }, [sessionId, sseUrl]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      style={{
        background: "rgba(16, 185, 129, 0.04)",
        border: "1px solid rgba(16, 185, 129, 0.18)",
        borderRadius: 8,
        padding: "8px 12px",
        display: "flex",
        alignItems: "center",
        gap: 10,
        fontSize: 11.5,
      }}
    >
      <Beaker size={14} style={{ color: "var(--lys-accent)", flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 10,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}>
          design session · {data.pathogen ?? "?"}
        </div>
        {data.objective && (
          <div style={{
            color: "var(--lys-text)",
            fontSize: 11.5,
            lineHeight: 1.35,
            marginTop: 1,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}>
            {data.objective}
          </div>
        )}
      </div>
      <div style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "2px 8px",
        background: streaming
          ? "rgba(16, 185, 129, 0.14)"
          : "var(--lys-surface-2)",
        color: streaming ? "var(--lys-accent)" : "var(--lys-text-faint)",
        borderRadius: 999,
        fontFamily: "var(--lys-font-mono)",
        fontSize: 9.5,
        fontWeight: 600,
        flexShrink: 0,
      }}>
        <Activity size={10} />
        {streaming ? `live · ${eventCount}` : `done · ${eventCount}`}
      </div>
    </motion.div>
  );
}

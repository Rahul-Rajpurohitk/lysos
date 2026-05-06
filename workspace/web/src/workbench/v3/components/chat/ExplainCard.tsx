/**
 * ExplainCard — chat card for W4 (explain) sessions.
 *
 * Mounts when a /explain slash returns card_kind="explain_session".
 * Auto-opens an EventSource on /workbench/sessions/{id}/events and pipes
 * the streaming markdown chunks into the right-pane ArtifactPanel via
 * the onArtifact callback. Visible in the chat as a compact receipt
 * with a live progress chip (chunks-arrived counter).
 */
import { useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { BookOpen, Activity, FileText } from "lucide-react";
import { ChatMsg } from "./MessageRow";

interface ExplainCardProps {
  msg: ChatMsg;
  /** Push streaming markdown to the right-side ArtifactPanel state.
   *  WorkbenchV3 wires this to setArtifactDoc(...). */
  onArtifact?: (params: {
    sessionId: string;
    target: string;
    markdown: string;            // current cumulative markdown
    chunks: string[];            // raw chunk list (for replay)
    complete: boolean;
    error?: string | null;
    groundingCount?: number;
  }) => void;
}

interface ExplainData {
  session_id?: string;
  target?: string;
  sse_url?: string;
  status?: string;
  grounding_count?: number;
}

const SUBSCRIBED = new Set<string>();

export function ExplainCard({ msg, onArtifact }: ExplainCardProps) {
  const data = (msg.data ?? {}) as ExplainData;
  const sessionId = data.session_id ?? "";
  const sseUrl = data.sse_url ?? "";
  const target = data.target ?? "?";
  const groundingCount = data.grounding_count ?? 0;

  const [streaming, setStreaming] = useState(true);
  const [chunks, setChunks] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const onArtifactRef = useRef(onArtifact);
  onArtifactRef.current = onArtifact;

  useEffect(() => {
    if (!sessionId || !sseUrl) return;
    if (SUBSCRIBED.has(sessionId)) return;
    SUBSCRIBED.add(sessionId);

    const url = sseUrl.startsWith("http") ? sseUrl : `${window.location.origin}${sseUrl}`;
    const es = new EventSource(url);

    const collected: string[] = [];

    const onChunk = (e: MessageEvent) => {
      try {
        const ev = JSON.parse(e.data ?? "{}");
        if (ev.type === "explain_chunk") {
          const chunk = ev.data?.chunk ?? "";
          collected.push(chunk);
          setChunks([...collected]);
          onArtifactRef.current?.({
            sessionId,
            target,
            markdown: collected.join(""),
            chunks: [...collected],
            complete: false,
            groundingCount,
          });
        } else if (ev.type === "explain_complete") {
          onArtifactRef.current?.({
            sessionId,
            target,
            markdown: collected.join(""),
            chunks: [...collected],
            complete: true,
            groundingCount: ev.data?.grounding_count ?? groundingCount,
          });
          setStreaming(false);
          es.close();
          SUBSCRIBED.delete(sessionId);
        } else if (ev.type === "explain_error") {
          const errMsg = ev.data?.error ?? "stream error";
          setError(errMsg);
          onArtifactRef.current?.({
            sessionId,
            target,
            markdown: collected.join(""),
            chunks: [...collected],
            complete: true,
            error: errMsg,
            groundingCount,
          });
          setStreaming(false);
          es.close();
          SUBSCRIBED.delete(sessionId);
        }
      } catch (err) {
        console.warn("explain SSE parse error", err);
      }
    };

    ["message", "explain_chunk", "explain_complete", "explain_error", "explain_start"]
      .forEach((t) => es.addEventListener(t, onChunk as EventListener));
    es.onmessage = onChunk;

    es.onerror = () => {
      if (es.readyState === EventSource.CLOSED) {
        setStreaming(false);
        SUBSCRIBED.delete(sessionId);
      }
    };

    return () => {
      es.close();
      SUBSCRIBED.delete(sessionId);
    };
  }, [sessionId, sseUrl, target, groundingCount]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      style={{
        background: "rgba(59, 130, 246, 0.04)",
        border: "1px solid rgba(59, 130, 246, 0.18)",
        borderRadius: 8,
        padding: "8px 12px",
        display: "flex",
        alignItems: "center",
        gap: 10,
        fontSize: 11.5,
      }}
    >
      <BookOpen size={14} style={{ color: "#3b82f6", flexShrink: 0 }} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          fontSize: 10,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}>
          explain · {target}
        </div>
        <div style={{
          color: "var(--lys-text-dim)",
          fontSize: 11,
          marginTop: 1,
        }}>
          {error
            ? <span style={{ color: "#dc2626" }}>error: {error}</span>
            : streaming
              ? <span><FileText size={9} style={{ verticalAlign: "middle" }}/> streaming to artifact pane …</span>
              : <span>brief ready in artifact pane</span>}
        </div>
      </div>
      <div style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 5,
        padding: "2px 8px",
        background: streaming
          ? "rgba(59, 130, 246, 0.14)"
          : "var(--lys-surface-2)",
        color: streaming ? "#1e40af" : "var(--lys-text-faint)",
        borderRadius: 999,
        fontFamily: "var(--lys-font-mono)",
        fontSize: 9.5,
        fontWeight: 600,
        flexShrink: 0,
      }}>
        <Activity size={10} />
        {streaming ? `live · ${chunks.length}` : `${chunks.length} sections`}
        {groundingCount > 0 && <span style={{ opacity: 0.7 }}>· g{groundingCount}</span>}
      </div>
    </motion.div>
  );
}

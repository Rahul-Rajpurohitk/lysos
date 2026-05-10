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
import { BookOpen, Activity } from "lucide-react";
import { ChatMsg } from "./MessageRow";
import { MarkdownText } from "./MarkdownText";

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

  // The streaming markdown — concatenate all chunks. We show this
  // inline in the chat so the user reads the brief WITHOUT having to
  // hunt for an artifact pane.
  const markdown = chunks.join("");

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      style={{
        background: "rgba(59, 130, 246, 0.04)",
        border: "1px solid rgba(59, 130, 246, 0.18)",
        borderLeft: "3px solid #3b82f6",
        borderRadius: 6,
        padding: "8px 12px",
        fontSize: 11.5,
      }}
    >
      {/* Compact status header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: markdown ? 6 : 0 }}>
        <BookOpen size={13} style={{ color: "#3b82f6", flexShrink: 0 }} />
        <div style={{
          flex: 1, minWidth: 0,
          fontSize: 10,
          fontFamily: "var(--lys-font-mono)",
          color: "#1e40af",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          fontWeight: 700,
        }}>
          brief · {target}
        </div>
        <div style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 7px",
          background: streaming ? "rgba(59, 130, 246, 0.14)" : "rgba(0,0,0,0.04)",
          color: streaming ? "#1e40af" : "var(--lys-text-faint)",
          borderRadius: 999,
          fontFamily: "var(--lys-font-mono)",
          fontSize: 9, fontWeight: 700,
        }}>
          <Activity size={9} />
          {streaming
            ? `live · ${chunks.length} chunk${chunks.length === 1 ? "" : "s"}`
            : `done · ${chunks.length} chunks`}
          {groundingCount > 0 && <span style={{ opacity: 0.7 }}>· g{groundingCount}</span>}
        </div>
      </div>

      {/* Inline markdown body — the brief content itself, NOT just a
        * receipt. MarkdownText handles bold / italic / lists / pipe
        * tables / clickable backtick SMILES. */}
      {error ? (
        <div style={{
          fontSize: 11.5, color: "#dc2626",
          padding: "4px 0",
        }}>
          The brief stream errored: {error}. Want me to try a different target or rephrase?
        </div>
      ) : markdown ? (
        <div style={{ color: "var(--lys-text)", paddingTop: 2 }}>
          <MarkdownText text={markdown} fontSize={12.5} />
        </div>
      ) : (
        <div style={{
          fontSize: 11, color: "var(--lys-text-dim)",
          fontStyle: "italic", padding: "4px 0",
        }}>
          {streaming ? "Building the brief…" : "(empty brief — try /explain <target> again)"}
        </div>
      )}
    </motion.div>
  );
}

/**
 * LibraryCard — chat card for W7+W8 (sessions library + replay).
 *
 * Lists past workbench sessions (from GET /workbench/sessions). Each row
 * is click-to-replay: opens a new chat tab and streams the past session's
 * SSE events into it via the same /workbench/sessions/{id}/events route
 * that DesignSessionCard uses (the events are persisted in the in-memory
 * queue + JSONL trace, so replay works as long as the FastAPI process
 * has the session's _sessions entry).
 */
import { motion } from "framer-motion";
import { Library, PlayCircle, CheckCircle2, AlertCircle } from "lucide-react";
import { ChatMsg } from "./MessageRow";

interface LibrarySession {
  session_id: string;
  target_pathogen: string;
  mode: string;
  autonomy: string;
  iteration: number;
  max_iterations: number;
  n_candidates: number;
  n_pareto: number;
  last_composite: number;
  terminated: boolean;
  termination_reason?: string | null;
}

interface LibraryData {
  sessions?: LibrarySession[];
}

interface Props {
  msg: ChatMsg;
  /** Replay request: open a new chat tab named after the session and
   *  start streaming its persisted events. WorkbenchV3 wires this. */
  onReplaySession?: (params: { sessionId: string; target: string; sseUrl: string }) => void;
}

export function LibraryCard({ msg, onReplaySession }: Props) {
  const data = (msg.data ?? {}) as LibraryData;
  const sessions = data.sessions ?? [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22 }}
      style={{
        background: "var(--lys-surface)",
        border: "1px solid var(--lys-border)",
        borderRadius: 8,
        overflow: "hidden",
        fontSize: 11.5,
      }}
    >
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        background: "rgba(139, 92, 246, 0.04)",
        borderBottom: "1px solid var(--lys-border)",
      }}>
        <Library size={13} style={{ color: "#8b5cf6", flexShrink: 0 }} />
        <span style={{
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}>
          library · {sessions.length} session{sessions.length === 1 ? "" : "s"}
        </span>
      </div>

      {sessions.length === 0 ? (
        <div style={{ padding: "12px 14px", color: "var(--lys-text-dim)", fontSize: 11 }}>
          No saved sessions yet. Run `/design &lt;pathogen&gt;` to start one — it will appear here.
        </div>
      ) : (
        <div>
          {sessions.map((s) => {
            const StatusIcon = s.terminated ? CheckCircle2 : PlayCircle;
            const statusColor = s.terminated
              ? (s.termination_reason?.toLowerCase().includes("error") ? "#dc2626" : "var(--lys-text-faint)")
              : "var(--lys-accent)";
            return (
              <button
                key={s.session_id}
                type="button"
                onClick={() => onReplaySession?.({
                  sessionId: s.session_id,
                  target: s.target_pathogen,
                  sseUrl: `/workbench/sessions/${s.session_id}/events`,
                })}
                title={`Replay session ${s.session_id} (${s.iteration}/${s.max_iterations} iters)`}
                style={{
                  display: "grid",
                  gridTemplateColumns: "auto 70px 1fr 80px 70px",
                  gap: 8,
                  alignItems: "center",
                  width: "100%",
                  padding: "6px 12px",
                  border: 0,
                  background: "transparent",
                  textAlign: "left",
                  cursor: "pointer",
                  fontFamily: "inherit",
                  fontSize: 10.5,
                  color: "var(--lys-text)",
                  borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
                  transition: "background 0.12s",
                }}
                onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(139, 92, 246, 0.04)")}
                onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
              >
                <StatusIcon size={12} style={{ color: statusColor }} />
                <span style={{
                  fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-accent)",
                  fontWeight: 600,
                }}>
                  {s.target_pathogen}
                </span>
                <span style={{
                  fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)",
                  fontSize: 9.5,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}>
                  {s.session_id}
                </span>
                <span style={{
                  fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-dim)",
                  fontSize: 10,
                  textAlign: "right",
                }}>
                  iter {s.iteration}/{s.max_iterations}
                </span>
                <span style={{
                  fontFamily: "var(--lys-font-mono)",
                  color: s.last_composite >= 0.5 ? "var(--lys-accent)" : "var(--lys-text-faint)",
                  fontWeight: 600,
                  fontSize: 11,
                  textAlign: "right",
                }}>
                  {s.n_candidates > 0 ? s.last_composite.toFixed(3) : "—"}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {sessions.length > 0 && (
        <div style={{
          padding: "6px 12px",
          background: "var(--lys-surface-2)",
          borderTop: "1px solid var(--lys-border)",
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          display: "flex",
          alignItems: "center",
          gap: 6,
        }}>
          <AlertCircle size={10} />
          Click a row to replay in a new chat tab
        </div>
      )}
    </motion.div>
  );
}

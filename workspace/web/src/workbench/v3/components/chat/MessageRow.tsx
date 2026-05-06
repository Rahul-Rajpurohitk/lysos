/**
 * MessageRow — single timeline row.
 *
 * Design reasoning:
 *  - This is a research timeline, not a messaging app. Agents are roles,
 *    not people; avatars (Slack/LI pattern) burn 38px of left margin per
 *    row without adding info. We use a 3px colored left bar instead — same
 *    role-identifying signal, ~35px reclaimed per row.
 *  - Header is one tight line: AGENT · ITER · TIMESTAMP. 11px mono for
 *    timestamp keeps the eye on content, not chrome.
 *  - Tool calls nest with a 1px left border so the parent → child
 *    relationship reads at a glance, but they don't get their own avatar
 *    or full bubble.
 *  - Specialized rows (candidate_added, mol_edit, state_change) render
 *    as compact event chips, not full bubbles, because they're system
 *    events not "messages".
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { ChevronRight, Star, ArrowRight, Flag, Wrench, BrainCircuit, Reply, X as IconX, ArrowUp } from "lucide-react";
import { agentColor } from "./AgentAvatar";
import { InlineSmilesCard } from "./InlineSmilesCard";
import { RewardCard } from "./RewardCard";
import { DesignSessionCard } from "./DesignSessionCard";
import { ExplainCard } from "./ExplainCard";
import { ScaffoldTreeCard } from "./ScaffoldTreeCard";
import { StressTestCard } from "./StressTestCard";
import { ComparisonCard } from "./ComparisonCard";

export interface ChatMsg {
  id?: string;
  type: string;
  ts: number;
  agent?: string;
  content?: string;
  thinking?: string | null;
  iteration?: number;
  smiles?: string;
  parent?: string;
  candidate?: string;
  scores?: Record<string, number>;
  composite?: number;
  delta?: Record<string, number>;
  decision?: string;
  reason?: string;
  tool?: string;
  args?: any;
  result?: any;
  duration_ms?: number;
  error?: string;
  model?: string;
  tokens?: number;
  latency_ms?: number;
  // structured chat-card payloads (W2+)
  card_kind?: string;
  data?: Record<string, any>;
  // ---- threading / agent-tagging (#91) ----
  thread_id?: string;
  parent_message_id?: string;
  reply_agent?: string;
}

interface MessageRowProps {
  msg: ChatMsg;
  toolCalls?: ChatMsg[];
  onLoadSmiles?: (smi: string) => void;
  /** Push a streamed event (from a card's SSE subscription) into the
   *  parent chat-events array so MessageRow renders it as a row. */
  onIngestEvent?: (event: ChatMsg) => void;
  /** Send a reply scoped to a specific agent. Triggered from the
   *  hover-reveal "↩ Reply to <agent>" action (#91 threading). */
  onReplyToAgent?: (params: {
    text: string;
    targetAgent: string;
    parentMessageId: string;
    threadId: string;
  }) => void;
  /** W4: pipe streaming explain markdown into the right-pane artifact panel. */
  onArtifact?: (params: {
    sessionId: string;
    target: string;
    markdown: string;
    chunks: string[];
    complete: boolean;
    error?: string | null;
    groundingCount?: number;
  }) => void;
}

const REPLYABLE_AGENTS = new Set(["designer", "critic", "editor", "strategist", "orchestrator"]);

export function MessageRow({ msg, toolCalls, onLoadSmiles, onIngestEvent, onReplyToAgent, onArtifact }: MessageRowProps) {
  if (msg.type === "candidate_added") return <CandidateRow msg={msg} onLoadSmiles={onLoadSmiles} />;
  if (msg.type === "mol_edit") return <EditRow msg={msg} onLoadSmiles={onLoadSmiles} />;
  if (msg.type === "state_change") return <StateRow msg={msg} />;
  // Structured chat cards from slash commands (/score, /design, /explain, …)
  if (msg.card_kind === "score" && msg.data) return <RewardCard msg={msg} onLoadSmiles={onLoadSmiles} />;
  if (msg.card_kind === "design_session" && msg.data) return <DesignSessionCard msg={msg} onIngestEvent={onIngestEvent} />;
  if (msg.card_kind === "explain_session" && msg.data) return <ExplainCard msg={msg} onArtifact={onArtifact} />;
  if (msg.card_kind === "sar" && msg.data) return <ScaffoldTreeCard msg={msg} onLoadSmiles={onLoadSmiles} />;
  if (msg.card_kind === "stress" && msg.data) return <StressTestCard msg={msg} onLoadSmiles={onLoadSmiles} />;
  if (msg.card_kind === "compare" && msg.data) return <ComparisonCard msg={msg} onLoadSmiles={onLoadSmiles} />;

  const agent = msg.agent ?? msg.type ?? "system";
  const color = agentColor(agent);
  const { body, embeddedSmiles } = parseBody(msg.content ?? "");
  const canReply = !!onReplyToAgent && REPLYABLE_AGENTS.has(agent.toLowerCase());
  const isThreadedReply = !!msg.thread_id && !!msg.parent_message_id;
  const [hover, setHover] = useState(false);
  const [replyOpen, setReplyOpen] = useState(false);

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.18, ease: "easeOut" }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: "relative",
        paddingLeft: 12,
        // 3px colored bar = role indicator, no avatar required.
        borderLeft: `3px solid ${color}`,
        // Threaded replies indent so they read as a side-thread.
        marginLeft: isThreadedReply ? 22 : 0,
      }}
    >
      <div style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        marginBottom: 2,
        fontSize: 11,
      }}>
        <span style={{
          color,
          fontWeight: 600,
          fontSize: 12,
          textTransform: "lowercase",
          letterSpacing: "0.01em",
        }}>
          {agent}
        </span>
        {msg.iteration != null && msg.iteration > 0 && (
          <span style={{
            fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
            fontSize: 10,
          }}>
            iter {msg.iteration}
          </span>
        )}
        {isThreadedReply && msg.reply_agent && (
          <span style={{
            fontSize: 9.5,
            fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
            background: "var(--lys-surface-2)",
            padding: "1px 5px",
            borderRadius: 3,
          }}>
            ↩ thread → {msg.reply_agent}
          </span>
        )}
        <span style={{ flex: 1 }} />
        {canReply && hover && !replyOpen && (
          <button
            type="button"
            onClick={() => setReplyOpen(true)}
            title={`Reply to ${agent} only (parallel thread)`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 3,
              border: 0,
              background: "transparent",
              color: "var(--lys-text-faint)",
              fontFamily: "inherit",
              fontSize: 10.5,
              padding: "1px 5px",
              borderRadius: 3,
              cursor: "pointer",
              transition: "background 0.12s, color 0.12s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "var(--lys-bg-hover, rgba(0,0,0,0.05))";
              e.currentTarget.style.color = color;
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.color = "var(--lys-text-faint)";
            }}
          >
            <Reply size={10} />
            Reply to {agent}
          </button>
        )}
        <span style={{
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          fontSize: 10,
          opacity: 0.6,
        }}>
          {formatTs(msg.ts)}
        </span>
      </div>

      {msg.thinking && <ThinkingBlock thinking={msg.thinking} />}

      {body && (
        <div style={{
          fontSize: 13.5,
          lineHeight: 1.5,
          color: "var(--lys-text)",
          whiteSpace: "pre-wrap",
          wordBreak: "break-word",
        }}>
          {body}
        </div>
      )}

      {embeddedSmiles && (
        <InlineSmilesCard
          smiles={embeddedSmiles}
          composite={msg.composite}
          scores={msg.scores}
          onLoad={onLoadSmiles}
        />
      )}

      {toolCalls?.map((tc, i) => (
        <ToolCallChip key={tc.id ?? i} tc={tc} />
      ))}

      {(msg.tokens || msg.latency_ms || msg.model) && (
        <div className="lys-msg-meta" style={{
          marginTop: 4,
          fontSize: 10,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          opacity: 0,
        }}>
          {msg.tokens && <span>{msg.tokens} tok</span>}
          {msg.latency_ms && <span> · {msg.latency_ms}ms</span>}
          {msg.model && <span> · {msg.model}</span>}
        </div>
      )}
      {replyOpen && canReply && (
        <InlineReplyComposer
          agent={agent}
          color={color}
          onSubmit={(text) => {
            onReplyToAgent?.({
              text,
              targetAgent: agent.toLowerCase(),
              parentMessageId: msg.id ?? `${msg.ts}-${agent}`,
              threadId: msg.thread_id ?? `t-${msg.id ?? msg.ts}`,
            });
            setReplyOpen(false);
          }}
          onCancel={() => setReplyOpen(false)}
        />
      )}
    </motion.div>
  );
}

// ── Inline reply composer (parallel-thread mini-input) ───────────────

function InlineReplyComposer({ agent, color, onSubmit, onCancel }: {
  agent: string;
  color: string;
  onSubmit: (text: string) => void;
  onCancel: () => void;
}) {
  const [text, setText] = useState("");
  return (
    <div style={{
      marginTop: 6,
      display: "flex",
      alignItems: "flex-end",
      gap: 6,
      padding: "6px 8px",
      background: "var(--lys-surface-2)",
      border: `1px solid ${color}33`,
      borderRadius: 6,
    }}>
      <span style={{
        fontSize: 9.5,
        fontFamily: "var(--lys-font-mono)",
        color,
        fontWeight: 600,
        flexShrink: 0,
        marginBottom: 4,
      }}>
        ↩ {agent}
      </span>
      <textarea
        autoFocus
        rows={1}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            const t = text.trim();
            if (t) onSubmit(t);
          }
          if (e.key === "Escape") onCancel();
        }}
        placeholder={`Reply to ${agent} only…`}
        style={{
          flex: 1,
          border: 0,
          outline: 0,
          background: "transparent",
          fontFamily: "inherit",
          fontSize: 12,
          color: "var(--lys-text)",
          resize: "none",
          padding: 0,
        }}
      />
      <button
        type="button"
        onClick={onCancel}
        title="Cancel (Esc)"
        style={{
          display: "grid",
          placeItems: "center",
          width: 22,
          height: 22,
          border: 0,
          background: "transparent",
          color: "var(--lys-text-faint)",
          borderRadius: 4,
          cursor: "pointer",
          flexShrink: 0,
        }}
      >
        <IconX size={11} />
      </button>
      <button
        type="button"
        onClick={() => {
          const t = text.trim();
          if (t) onSubmit(t);
        }}
        disabled={!text.trim()}
        title={`Send to ${agent} (↵)`}
        style={{
          display: "grid",
          placeItems: "center",
          width: 22,
          height: 22,
          border: 0,
          background: text.trim() ? "var(--lys-text)" : "var(--lys-surface-2)",
          color: text.trim() ? "white" : "var(--lys-text-faint)",
          borderRadius: 4,
          cursor: text.trim() ? "pointer" : "default",
          flexShrink: 0,
        }}
      >
        <ArrowUp size={11} />
      </button>
    </div>
  );
}


// ── Specialized row variants ─────────────────────────────────────────

function CandidateRow({ msg, onLoadSmiles }: { msg: ChatMsg; onLoadSmiles?: (s: string) => void }) {
  const composite = msg.composite ?? 0;
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2 }}
      style={{
        position: "relative",
        paddingLeft: 12,
        borderLeft: "3px solid #10b981",
      }}
    >
      <div style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        marginBottom: 4,
        fontSize: 11,
      }}>
        <Star size={11} fill="#10b981" color="#10b981" style={{ alignSelf: "center" }} />
        <span style={{ color: "#047857", fontWeight: 600, fontSize: 12 }}>
          new candidate
        </span>
        <span style={{
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          fontSize: 10,
        }}>
          composite {composite.toFixed(3)}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          fontSize: 10,
          opacity: 0.6,
        }}>
          {formatTs(msg.ts)}
        </span>
      </div>
      <InlineSmilesCard
        smiles={msg.smiles ?? ""}
        composite={composite}
        scores={msg.scores}
        onLoad={onLoadSmiles}
      />
    </motion.div>
  );
}

function EditRow({ msg, onLoadSmiles }: { msg: ChatMsg; onLoadSmiles?: (s: string) => void }) {
  const sigDelta = msg.delta
    ? Object.entries(msg.delta)
        .filter(([_, v]) => Math.abs(v as number) > 0.02)
        .sort(([, a], [, b]) => Math.abs(b as number) - Math.abs(a as number))
        .slice(0, 3)
    : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        position: "relative",
        paddingLeft: 12,
        borderLeft: "3px solid #3b82f6",
      }}
    >
      <div style={{
        display: "flex",
        alignItems: "baseline",
        gap: 8,
        marginBottom: 4,
        fontSize: 11,
      }}>
        <span style={{ color: "#1d4ed8", fontWeight: 600, fontSize: 12 }}>
          edit
        </span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          fontSize: 10,
        }}>
          {formatTs(msg.ts)}
        </span>
      </div>

      <div style={{
        fontFamily: "var(--lys-font-mono)",
        fontSize: 11,
        color: "var(--lys-text-dim)",
        wordBreak: "break-all",
        lineHeight: 1.5,
      }}>
        {(msg.parent ?? "").slice(0, 36)}{(msg.parent ?? "").length > 36 ? "…" : ""}
        <ArrowRight size={11} style={{
          color: "#3b82f6",
          margin: "0 6px",
          verticalAlign: "middle",
        }} />
        <button
          onClick={() => msg.candidate && onLoadSmiles?.(msg.candidate)}
          style={{
            border: 0,
            background: "transparent",
            color: "#1d4ed8",
            padding: 0,
            font: "inherit",
            cursor: "pointer",
            textDecoration: "underline dotted",
            textUnderlineOffset: 2,
          }}
        >
          {(msg.candidate ?? "").slice(0, 36)}{(msg.candidate ?? "").length > 36 ? "…" : ""}
        </button>
      </div>

      {sigDelta.length > 0 && (
        <div style={{ marginTop: 6, display: "flex", gap: 4, flexWrap: "wrap" }}>
          {sigDelta.map(([k, v]) => {
            const num = v as number;
            const positive = num > 0;
            return (
              <span key={k} style={{
                fontFamily: "var(--lys-font-mono)",
                fontSize: 10,
                padding: "1px 6px",
                color: positive ? "#047857" : "#b91c1c",
                background: positive ? "#d1fae5" : "#fee2e2",
                borderRadius: 4,
              }}>
                {k.split("_")[0].slice(0, 4)} {positive ? "+" : ""}{num.toFixed(2)}
              </span>
            );
          })}
        </div>
      )}
    </motion.div>
  );
}

function StateRow({ msg }: { msg: ChatMsg }) {
  const decision = msg.decision ?? "—";
  const tone =
    decision === "TERMINATE" ? { fg: "#b91c1c" }
    : decision === "BRANCH" ? { fg: "#6d28d9" }
    : { fg: "#1d4ed8" };

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        paddingLeft: 12,
        fontSize: 11,
        color: "var(--lys-text-dim)",
      }}
    >
      <Flag size={10} color={tone.fg} />
      <span style={{
        fontWeight: 600,
        color: tone.fg,
        fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.05em",
      }}>
        {decision.toLowerCase()}
      </span>
      {msg.reason && <span>· {msg.reason}</span>}
      <span style={{ flex: 1 }} />
      <span style={{
        fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)",
        fontSize: 10,
        opacity: 0.6,
      }}>
        {formatTs(msg.ts)}
      </span>
    </motion.div>
  );
}

// ── Tool call chip — collapsible inline ──────────────────────────────

function ToolCallChip({ tc }: { tc: ChatMsg }) {
  const [open, setOpen] = useState(false);
  const dur = tc.duration_ms != null ? `${tc.duration_ms < 1 ? "<1" : tc.duration_ms}ms` : "—";
  const isErr = !!tc.error;

  return (
    <div style={{ marginTop: 4, marginLeft: 0 }}>
      <button
        onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "3px 0",
          border: 0,
          background: "transparent",
          cursor: "pointer",
          font: "inherit",
          fontSize: 11,
          color: "var(--lys-text-dim)",
          fontFamily: "var(--lys-font-mono)",
        }}
      >
        <ChevronRight
          size={11}
          style={{
            transform: open ? "rotate(90deg)" : "none",
            transition: "transform 0.12s",
            color: "var(--lys-text-faint)",
          }}
        />
        <Wrench size={10} color="var(--lys-text-faint)" />
        <span style={{ color: "var(--lys-text)" }}>{tc.tool}</span>
        <span style={{ color: isErr ? "#ef4444" : "var(--lys-text-faint)" }}>
          {isErr ? "error" : "ok"}
        </span>
        <span style={{ marginLeft: "auto", color: "var(--lys-text-faint)" }}>{dur}</span>
      </button>
      {open && (
        <div style={{
          marginTop: 4,
          padding: 8,
          background: "var(--lys-surface-2)",
          border: "1px solid var(--lys-border)",
          borderRadius: 6,
          fontFamily: "var(--lys-font-mono)",
          fontSize: 10.5,
          lineHeight: 1.45,
          color: "var(--lys-text-dim)",
          maxHeight: 200,
          overflow: "auto",
        }}>
          {tc.args && (
            <>
              <div style={{ color: "var(--lys-text-faint)", marginBottom: 2 }}>args</div>
              <pre style={{ margin: 0, font: "inherit", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {JSON.stringify(tc.args, null, 2)}
              </pre>
            </>
          )}
          {tc.result != null && (
            <>
              <div style={{ color: "var(--lys-text-faint)", marginTop: 6, marginBottom: 2 }}>result</div>
              <pre style={{ margin: 0, font: "inherit", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                {typeof tc.result === "string" ? tc.result : JSON.stringify(tc.result, null, 2)}
              </pre>
            </>
          )}
          {tc.error && <div style={{ color: "#b91c1c" }}>error: {tc.error}</div>}
        </div>
      )}
    </div>
  );
}

function ThinkingBlock({ thinking }: { thinking: string }) {
  const [open, setOpen] = useState(false);
  return (
    <button
      onClick={() => setOpen((o) => !o)}
      style={{
        marginBottom: 4,
        padding: "2px 6px",
        background: "transparent",
        border: 0,
        borderLeft: "2px solid #c4b5fd",
        fontSize: 11,
        color: "#5b21b6",
        cursor: "pointer",
        textAlign: "left",
        width: "100%",
        display: "flex",
        alignItems: "center",
        gap: 4,
        font: "inherit",
        opacity: 0.85,
      }}
    >
      <BrainCircuit size={10} />
      {open ? (
        <span style={{
          fontStyle: "italic",
          whiteSpace: "pre-wrap",
          fontSize: 11,
        }}>{thinking}</span>
      ) : (
        <span>reasoning · {thinking.split(/\s+/).length} tokens</span>
      )}
    </button>
  );
}

function parseBody(text: string): { body: string; embeddedSmiles: string | null } {
  if (!text) return { body: "", embeddedSmiles: null };
  const match = text.match(/(?:PROPOSAL|SMILES):\s*([^\s\n]+)/i);
  if (!match) return { body: text, embeddedSmiles: null };
  const smi = match[1];
  const cleaned = text.replace(/(?:PROPOSAL|SMILES):\s*[^\s\n]+/i, "").trim();
  return { body: cleaned, embeddedSmiles: smi };
}

function formatTs(ts: number): string {
  if (!ts) return "";
  const ms = ts < 1e12 ? ts * 1000 : ts;
  const elapsed = (Date.now() - ms) / 1000;
  if (elapsed < 5) return "now";
  if (elapsed < 60) return `${Math.round(elapsed)}s`;
  if (elapsed < 3600) return `${Math.round(elapsed / 60)}m`;
  const d = new Date(ms);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

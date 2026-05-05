import { useState } from "react";
import { motion } from "framer-motion";
import { ChevronDown, BrainCircuit, Star, ArrowRightLeft, Flag } from "lucide-react";
import { AgentAvatar, agentColor } from "./AgentAvatar";
import { InlineSmilesCard } from "./InlineSmilesCard";
import { ToolCallCard } from "./ToolCallCard";

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
}

interface MessageCardProps {
  msg: ChatMsg;
  toolCalls?: ChatMsg[];
  onLoadSmiles?: (smi: string) => void;
}

export function MessageCard({ msg, toolCalls, onLoadSmiles }: MessageCardProps) {
  if (msg.type === "candidate_added") return <CandidateAddedCard msg={msg} onLoadSmiles={onLoadSmiles} />;
  if (msg.type === "mol_edit") return <MolEditCard msg={msg} onLoadSmiles={onLoadSmiles} />;
  if (msg.type === "state_change") return <StateChangeCard msg={msg} />;

  const agent = msg.agent ?? msg.type ?? "system";
  const color = agentColor(agent);
  const { body, embeddedSmiles } = parseBody(msg.content ?? "");

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.2, ease: "easeOut" }}
      style={{ display: "flex", gap: 10, alignItems: "flex-start" }}
    >
      <AgentAvatar agent={agent} size={28} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 8, marginBottom: 2, fontSize: 11,
        }}>
          <span style={{ color, fontWeight: 600, textTransform: "capitalize", fontSize: 13 }}>
            {agent}
          </span>
          {msg.iteration != null && msg.iteration > 0 && (
            <span style={{ fontFamily: "var(--lys-font-mono)", color: "var(--lys-text-faint)", fontSize: 10 }}>
              · iter {msg.iteration}
            </span>
          )}
          <span style={{
            marginLeft: "auto", fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)", fontSize: 10,
          }}>
            {formatTs(msg.ts)}
          </span>
        </div>

        {msg.thinking && <ThinkingBlock thinking={msg.thinking} />}

        {body && (
          <div style={{
            fontSize: 14, lineHeight: 1.5, color: "var(--lys-text)",
            wordBreak: "break-word", whiteSpace: "pre-wrap",
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
          <ToolCallCard
            key={tc.id ?? i}
            name={tc.tool ?? "tool"}
            agent={tc.agent ?? agent}
            status={tc.error ? "err" : "ok"}
            duration_ms={tc.duration_ms}
            args={tc.args}
            result={tc.result}
            error={tc.error}
          />
        ))}

        {(msg.tokens || msg.latency_ms || msg.model) && (
          <div className="lys-msg-meta" style={{
            marginTop: 4, fontSize: 10, fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
          }}>
            {msg.tokens && <span>{msg.tokens} tok</span>}
            {msg.latency_ms && <span> · {msg.latency_ms}ms</span>}
            {msg.model && <span> · {msg.model}</span>}
          </div>
        )}
      </div>
    </motion.div>
  );
}

function CandidateAddedCard({ msg, onLoadSmiles }: { msg: ChatMsg; onLoadSmiles?: (s: string) => void }) {
  const composite = msg.composite ?? 0;
  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.25 }}
      style={{ display: "flex", gap: 10, alignItems: "flex-start" }}
    >
      <div style={{
        width: 28, height: 28, borderRadius: 14, background: "var(--lys-accent-soft)",
        color: "#10b981", display: "grid", placeItems: "center", flexShrink: 0,
        border: "1.5px solid #10b981",
      }}>
        <Star size={14} fill="#10b981" />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6, fontSize: 12,
          color: "#047857", fontWeight: 600,
        }}>
          New candidate
          <span style={{ color: "var(--lys-text-faint)", fontWeight: 400 }}>
            · composite {composite.toFixed(3)}
          </span>
          <span style={{
            marginLeft: "auto", fontFamily: "var(--lys-font-mono)",
            fontSize: 10, color: "var(--lys-text-faint)",
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
      </div>
    </motion.div>
  );
}

function MolEditCard({ msg, onLoadSmiles }: { msg: ChatMsg; onLoadSmiles?: (s: string) => void }) {
  const sigDelta = msg.delta
    ? Object.entries(msg.delta)
        .filter(([_, v]) => Math.abs(v as number) > 0.02)
        .sort(([, a], [, b]) => Math.abs(b as number) - Math.abs(a as number))
    : [];

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      style={{ display: "flex", gap: 10, alignItems: "flex-start" }}
    >
      <div style={{
        width: 28, height: 28, borderRadius: 14, background: "#dbeafe",
        color: "#3b82f6", display: "grid", placeItems: "center", flexShrink: 0,
        border: "1.5px solid #3b82f6",
      }}>
        <ArrowRightLeft size={13} />
      </div>
      <div style={{
        flex: 1, minWidth: 0, padding: 10, background: "white",
        border: "1px solid var(--lys-border)", borderRadius: 10,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 8, fontSize: 12,
          color: "var(--lys-text-dim)",
        }}>
          <span style={{ color: "#1d4ed8", fontWeight: 600 }}>Edit applied</span>
          <span style={{
            marginLeft: "auto", fontFamily: "var(--lys-font-mono)",
            fontSize: 10, color: "var(--lys-text-faint)",
          }}>
            {formatTs(msg.ts)}
          </span>
        </div>
        <div style={{
          marginTop: 6, fontFamily: "var(--lys-font-mono)", fontSize: 11,
          color: "var(--lys-text)", wordBreak: "break-all",
        }}>
          {(msg.parent ?? "").slice(0, 40)}
          {(msg.parent ?? "").length > 40 ? "…" : ""}
          <span style={{ color: "#3b82f6", margin: "0 6px" }}>→</span>
          <button
            onClick={() => msg.candidate && onLoadSmiles?.(msg.candidate)}
            style={{
              border: 0, background: "transparent", color: "#1d4ed8",
              padding: 0, fontFamily: "inherit", fontSize: "inherit",
              cursor: "pointer", textDecoration: "underline", textUnderlineOffset: 2,
            }}
          >
            {(msg.candidate ?? "").slice(0, 40)}
            {(msg.candidate ?? "").length > 40 ? "…" : ""}
          </button>
        </div>

        {sigDelta.length > 0 && (
          <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
            {sigDelta.slice(0, 4).map(([k, v]) => {
              const num = v as number;
              const positive = num > 0;
              return (
                <span key={k} style={{
                  fontFamily: "var(--lys-font-mono)", fontSize: 10,
                  padding: "2px 8px",
                  background: positive ? "#d1fae5" : "#fee2e2",
                  color: positive ? "#047857" : "#b91c1c",
                  borderRadius: 999,
                  border: `1px solid ${positive ? "#a7f3d0" : "#fecaca"}`,
                }}>
                  {k.split("_")[0].slice(0, 4)} {positive ? "+" : ""}{num.toFixed(2)}
                </span>
              );
            })}
          </div>
        )}
      </div>
    </motion.div>
  );
}

function StateChangeCard({ msg }: { msg: ChatMsg }) {
  const decision = msg.decision ?? "—";
  const tone =
    decision === "TERMINATE"
      ? { bg: "#fee2e2", fg: "#b91c1c", border: "#fecaca" }
      : decision === "BRANCH"
      ? { bg: "#ede9fe", fg: "#6d28d9", border: "#c4b5fd" }
      : { bg: "#dbeafe", fg: "#1d4ed8", border: "#bfdbfe" };

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      style={{
        display: "flex", alignItems: "center", gap: 8, padding: "6px 10px",
        background: tone.bg, border: `1px solid ${tone.border}`,
        borderRadius: 999, marginLeft: 38, alignSelf: "flex-start",
      }}
    >
      <Flag size={11} color={tone.fg} />
      <span style={{
        fontSize: 11, fontWeight: 600, color: tone.fg,
        textTransform: "uppercase", letterSpacing: "0.05em",
      }}>
        {decision}
      </span>
      {msg.reason && (
        <span style={{ fontSize: 11, color: "var(--lys-text-dim)" }}>
          · {msg.reason}
        </span>
      )}
    </motion.div>
  );
}

function ThinkingBlock({ thinking }: { thinking: string }) {
  const [open, setOpen] = useState(false);
  return (
    <button
      onClick={() => setOpen((o) => !o)}
      style={{
        marginBottom: 4, padding: "4px 8px",
        background: "rgba(139, 92, 246, 0.08)",
        border: "1px solid rgba(139, 92, 246, 0.18)",
        borderRadius: 6, fontSize: 11, color: "#5b21b6",
        cursor: "pointer", textAlign: "left", width: "100%",
        display: "flex", alignItems: "center", gap: 6,
        fontFamily: "inherit",
      }}
    >
      <BrainCircuit size={11} />
      {open ? (
        <span style={{ fontStyle: "italic", whiteSpace: "pre-wrap" }}>{thinking}</span>
      ) : (
        <span>reasoning ({thinking.split(/\s+/).length} tokens)</span>
      )}
      <ChevronDown
        size={11}
        style={{
          marginLeft: "auto",
          transform: open ? "rotate(180deg)" : "none",
          transition: "transform 0.15s",
        }}
      />
    </button>
  );
}

function parseBody(text: string): { body: string; embeddedSmiles: string | null } {
  if (!text) return { body: "", embeddedSmiles: null };
  // Match SMILES/PROPOSAL prefix → extract the SMILES + strip the prefix line.
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
  if (elapsed < 5) return "just now";
  if (elapsed < 60) return `${Math.round(elapsed)}s ago`;
  if (elapsed < 3600) return `${Math.round(elapsed / 60)}m ago`;
  const d = new Date(ms);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

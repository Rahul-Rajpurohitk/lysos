import { useState } from "react";
import clsx from "clsx";
import { ChevronDown, Copy } from "lucide-react";

interface ToolCall {
  id: string;
  name: string;
  agent: string;
  duration_ms?: number;
  status: "ok" | "err" | "running";
  args?: any;
  result?: any;
}

interface MessageBubbleV3Props {
  agent: string;
  agentColor: string;
  ts: number;
  content: string;
  thinking?: string | null;
  toolCalls?: ToolCall[];
  tokens?: number;
  latencyMs?: number;
  model?: string;
}

export function MessageBubble(p: MessageBubbleV3Props) {
  const [thinkingOpen, setThinkingOpen] = useState(false);
  return (
    <div className="lys-msg" style={{ borderLeftColor: p.agentColor }}>
      <div className="lys-msg__head">
        <span className="lys-msg__agent" style={{ color: p.agentColor }}>{p.agent}</span>
        <span className="lys-msg__time">{formatTs(p.ts)}</span>
        {p.model && (
          <span className="lys-msg__time" style={{ marginLeft: "auto" }}>
            {p.model}
          </span>
        )}
      </div>

      {p.thinking && (
        <div
          className={clsx("lys-msg__thinking", !thinkingOpen && "lys-msg__thinking--collapsed")}
          onClick={() => setThinkingOpen((o) => !o)}
          title="agent reasoning trace — click to expand"
        >
          {!thinkingOpen ? (
            <span><ChevronDown size={10} style={{ display: "inline", verticalAlign: "middle" }} /> reasoning ({p.thinking.split(/\s+/).length} tokens)</span>
          ) : (
            <span>{p.thinking}</span>
          )}
        </div>
      )}

      <div className="lys-msg__body">{renderBody(p.content)}</div>

      {p.toolCalls && p.toolCalls.length > 0 && (
        <div style={{ display: "flex", flexDirection: "column", gap: 4, marginTop: 6 }}>
          {p.toolCalls.map((tc) => (
            <ToolCallCardV3 key={tc.id} call={tc} />
          ))}
        </div>
      )}

      <div className="lys-msg__footer">
        {p.tokens != null ? `${p.tokens} tokens` : ""}
        {p.latencyMs != null ? ` · ${p.latencyMs}ms` : ""}
      </div>
    </div>
  );
}

function ToolCallCardV3({ call }: { call: ToolCall }) {
  const [open, setOpen] = useState(false);
  const dur = call.duration_ms != null ? `${call.duration_ms}ms` : "—";
  return (
    <div className="lys-toolcall">
      <div className="lys-toolcall__head" onClick={() => setOpen((o) => !o)}>
        <span className={`lys-toolcall__pip lys-toolcall__pip--${call.status}`} />
        <span className="lys-toolcall__name">{call.name}</span>
        <span className="lys-toolcall__agent" style={{
          background: agentBgFor(call.agent),
          color: agentFgFor(call.agent),
        }}>
          {call.agent}
        </span>
        <span className="lys-toolcall__dur">{dur}</span>
        <ChevronDown size={12} style={{
          marginLeft: "auto",
          transform: open ? "rotate(180deg)" : "none",
          transition: "transform 0.15s",
        }} />
      </div>
      {open && (
        <div className="lys-toolcall__body">
          {call.args && (
            <>
              <div style={{ color: "var(--lys-text-faint)", marginBottom: 4 }}>args</div>
              <div>{JSON.stringify(call.args, null, 2)}</div>
            </>
          )}
          {call.result && (
            <>
              <div style={{ color: "var(--lys-text-faint)", marginTop: 6, marginBottom: 4 }}>result</div>
              <div>{typeof call.result === "string" ? call.result : JSON.stringify(call.result, null, 2)}</div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function renderBody(text: string): (string | JSX.Element)[] {
  const parts: (string | JSX.Element)[] = [];
  const proposalRe = /(PROPOSAL: |SMILES: )([^\s\n]+)/g;
  let lastIdx = 0;
  let i = 0;
  for (const m of text.matchAll(proposalRe)) {
    if (m.index === undefined) continue;
    parts.push(text.slice(lastIdx, m.index));
    parts.push(
      <span key={`p${i++}`} style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
        <strong style={{ color: "var(--lys-accent)" }}>{m[1]}</strong>
        <code>{m[2]}</code>
        <CopyBtn text={m[2]} />
      </span>
    );
    lastIdx = m.index + m[0].length;
  }
  parts.push(text.slice(lastIdx));
  return parts;
}

function CopyBtn({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1200);
      }}
      style={{
        background: "transparent",
        border: 0,
        cursor: "pointer",
        color: done ? "var(--lys-accent)" : "var(--lys-text-faint)",
        padding: 2,
      }}
      title="copy"
    >
      <Copy size={12} />
    </button>
  );
}

function formatTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

const AGENT_BG: Record<string, string> = {
  designer: "rgba(52, 211, 153, 0.15)",
  critic: "rgba(248, 113, 113, 0.15)",
  editor: "rgba(96, 165, 250, 0.15)",
  strategist: "rgba(167, 139, 250, 0.15)",
  user: "rgba(251, 191, 36, 0.15)",
  system: "rgba(255, 255, 255, 0.05)",
};
const AGENT_FG: Record<string, string> = {
  designer: "#86efac",
  critic: "#fca5a5",
  editor: "#93c5fd",
  strategist: "#c4b5fd",
  user: "#fcd34d",
  system: "var(--lys-text-dim)",
};

function agentBgFor(a: string) {
  return AGENT_BG[a.toLowerCase()] ?? AGENT_BG.system;
}
function agentFgFor(a: string) {
  return AGENT_FG[a.toLowerCase()] ?? AGENT_FG.system;
}

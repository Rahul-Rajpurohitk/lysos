/**
 * AgentMessageCard — Claude-style live agent message renderer.
 *
 * Renders one agent run from useAgentStream's AgentState in order:
 *   • Reasoning blocks (collapsible, italic-mute)
 *   • Tool-call blocks (badge + status + elapsed; click to expand
 *     args + result JSON)
 *   • Final assistant text (streams as it arrives)
 *
 * Visual language: lavender-glass background, mono labels, soft
 * bordered card per step. Same design tokens as the rest of the
 * workbench. No external dependencies.
 */
import { useState } from "react";
import { ChevronRight, ChevronDown, Wrench, Lightbulb, Loader2,
         CheckCircle2, AlertCircle, Sparkles } from "lucide-react";
import type { AgentState, AgentStep } from "../../hooks/useAgentStream";
import { MarkdownText } from "./MarkdownText";

const LAV = {
  bg: "rgba(174, 158, 244, 0.08)",
  bgStrong: "rgba(174, 158, 244, 0.14)",
  border: "rgba(174, 158, 244, 0.30)",
  borderStrong: "rgba(174, 158, 244, 0.45)",
  fg: "#7c63d8",
  fgDeep: "#6041d0",
} as const;

const GREEN = { bg: "rgba(16,185,129,0.10)", border: "rgba(16,185,129,0.30)", fg: "#10b981" };
const RED   = { bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)",  fg: "#dc2626" };
const AMBER = { bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.30)",  fg: "#ca8a04" };

interface Props {
  state: AgentState;
}

export function AgentMessageCard({ state }: Props) {
  // Lean outer wrapper — Claude Desktop-style. No lavender card box,
  // just a thin left rule for the agent column. Steps stack vertically
  // with whitespace as separator, not borders.
  return (
    <div style={{
      paddingLeft: 10,
      borderLeft: `2px solid ${LAV.border}`,
      display: "flex", flexDirection: "column", gap: 8,
      fontFamily: "var(--lys-font-body)",
    }}>
      <Header state={state} />

      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {state.steps.map((step, i) => (
          <StepBlock key={i} step={step} />
        ))}
        {state.status === "running" && state.steps.length === 0 && (
          <div style={{
            display: "flex", alignItems: "center", gap: 6,
            fontSize: 12, color: LAV.fg, fontFamily: "var(--lys-font-body)",
          }}>
            <Loader2 size={11} className="lys-spin" />
            <span style={{ fontStyle: "italic" }}>thinking…</span>
          </div>
        )}
      </div>

      {state.status === "error" && state.error && (
        <div style={{
          padding: "4px 8px",
          background: RED.bg, border: `1px solid ${RED.border}`,
          borderRadius: 4, fontSize: 11, color: RED.fg,
          fontFamily: "var(--lys-font-mono)",
        }}>
          ⚠ {state.error}
        </div>
      )}
    </div>
  );
}


function Header({ state }: { state: AgentState }) {
  const running = state.status === "running";
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6,
      fontSize: 11.5, color: LAV.fg, fontWeight: 600,
      fontFamily: "var(--lys-font-body)",
    }}>
      <Sparkles size={12} />
      <span>assistant</span>
      <span style={{ flex: 1 }} />
      {running ? (
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 4,
          fontSize: 11, color: LAV.fg,
          fontFamily: "var(--lys-font-mono)",
        }}>
          <Loader2 size={10} className="lys-spin" /> thinking
        </span>
      ) : (
        <span style={{
          fontSize: 10.5, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)",
        }}>
          {state.n_tool_calls > 0 && `${state.n_tool_calls} tool${state.n_tool_calls === 1 ? "" : "s"}`}
          {state.n_tool_calls > 0 && state.elapsed_ms != null && " · "}
          {state.elapsed_ms != null && `${(state.elapsed_ms / 1000).toFixed(1)}s`}
        </span>
      )}
      <style>{`@keyframes lys-spin {0%{transform:rotate(0)}100%{transform:rotate(360deg)}}
        .lys-spin{animation:lys-spin 0.9s linear infinite}`}</style>
    </div>
  );
}


function StepBlock({ step }: { step: AgentStep }) {
  if (step.kind === "thinking") return <ThinkingBlock text={step.text} />;
  if (step.kind === "tool_call") return <ToolCallBlock step={step} />;
  return <TextBlock text={step.text} />;
}


function ThinkingBlock({ text }: { text: string }) {
  // Collapsed by default — like Claude Desktop's "Searched the web"
  // disclosure. Preview is just a fade hint, no quotation. Open state
  // renders FULL markdown so **bold** is bold, not literal asterisks.
  const [open, setOpen] = useState(false);
  const preview = text.replace(/[*`#_]/g, "").replace(/\s+/g, " ").trim().slice(0, 90);
  return (
    <div>
      <button onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%", textAlign: "left",
          display: "flex", alignItems: "center", gap: 5,
          background: "transparent", border: 0, cursor: "pointer", padding: "1px 0",
          fontFamily: "var(--lys-font-body)",
        }}>
        {open ? <ChevronDown size={11} color="var(--lys-text-faint)" />
              : <ChevronRight size={11} color="var(--lys-text-faint)" />}
        <Lightbulb size={11} style={{ color: LAV.fg, flexShrink: 0 }} />
        <span style={{
          fontFamily: "var(--lys-font-mono)", fontWeight: 700,
          color: LAV.fg, fontSize: 9.5, letterSpacing: "0.04em",
          textTransform: "uppercase",
        }}>thinking</span>
        {!open && (
          <span style={{
            color: "var(--lys-text-faint)", whiteSpace: "nowrap",
            overflow: "hidden", textOverflow: "ellipsis", flex: 1,
            fontSize: 11.5, fontStyle: "italic",
          }}>{preview}{preview.length >= 90 ? "…" : ""}</span>
        )}
      </button>
      {open && (
        <div style={{
          marginTop: 4, marginLeft: 16,
          paddingLeft: 8,
          borderLeft: `1px solid ${LAV.border}`,
          color: "var(--lys-text-dim)", fontStyle: "italic",
        }}>
          <MarkdownText text={text} fontSize={12} />
        </div>
      )}
    </div>
  );
}


function ToolCallBlock({ step }: { step: Extract<AgentStep, { kind: "tool_call" }> }) {
  const [open, setOpen] = useState(false);
  const tier = step.status === "ok" ? GREEN : step.status === "error" ? RED : AMBER;
  const Icon = step.status === "ok" ? CheckCircle2
             : step.status === "error" ? AlertCircle
             : Loader2;
  const elapsed = step.elapsed_ms != null
    ? step.elapsed_ms < 1000 ? `${step.elapsed_ms}ms` : `${(step.elapsed_ms / 1000).toFixed(1)}s`
    : null;
  // One-line by default — Claude Desktop's "Used tool xyz" pattern.
  // Click to peek the args + a SUMMARY of the result (not raw JSON).
  // The full JSON is hidden behind a second-level toggle.
  return (
    <div>
      <button onClick={() => setOpen((o) => !o)}
        style={{
          width: "100%", textAlign: "left",
          display: "flex", alignItems: "center", gap: 6,
          background: "transparent", border: 0, cursor: "pointer", padding: "1px 0",
          fontFamily: "var(--lys-font-body)",
        }}>
        {open ? <ChevronDown size={11} color="var(--lys-text-faint)" />
              : <ChevronRight size={11} color="var(--lys-text-faint)" />}
        <Icon size={11} style={{
          color: tier.fg,
          ...(step.status === "running" ? { animation: "lys-spin 0.9s linear infinite" } : {}),
          flexShrink: 0,
        }} />
        <Wrench size={10} style={{ color: tier.fg, flexShrink: 0 }} />
        <span style={{
          fontFamily: "var(--lys-font-mono)", fontWeight: 700,
          color: tier.fg, fontSize: 11.5,
        }}>{step.tool}</span>
        <span style={{
          fontFamily: "var(--lys-font-mono)", fontSize: 10.5,
          color: "var(--lys-text-faint)",
          whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          flex: 1,
        }}>
          {summarizeArgs(step.args)}
        </span>
        {elapsed && (
          <span style={{
            fontFamily: "var(--lys-font-mono)", fontSize: 10,
            color: "var(--lys-text-faint)", flexShrink: 0,
          }}>{elapsed}</span>
        )}
      </button>
      {open && (
        <div style={{
          marginTop: 3, marginLeft: 17,
          paddingLeft: 8,
          borderLeft: `1px solid ${tier.border}`,
          display: "flex", flexDirection: "column", gap: 4,
        }}>
          {step.status === "ok" && step.result !== undefined && (
            <ResultPreview result={step.result} />
          )}
          {step.status === "error" && step.error && (
            <div style={{
              fontFamily: "var(--lys-font-mono)", fontSize: 11, color: RED.fg,
              wordBreak: "break-word",
            }}>{step.error}</div>
          )}
          <RawJsonToggle args={step.args} result={step.result} />
        </div>
      )}
    </div>
  );
}

/** Show a HUMAN-readable summary of the tool result instead of raw JSON.
 *  Recognizes scoring shapes (composite + components), resistance shapes
 *  (robustness_score + vulnerable_atoms), and falls back to a count of
 *  keys for unknown shapes. The full JSON lives behind RawJsonToggle. */
function ResultPreview({ result }: { result: any }) {
  if (result == null) return null;
  if (typeof result === "string") {
    return <div style={{ fontSize: 12, lineHeight: 1.5 }}>{result.slice(0, 200)}</div>;
  }
  if (typeof result !== "object") {
    return <div style={{ fontSize: 12, fontFamily: "var(--lys-font-mono)" }}>{String(result)}</div>;
  }
  // Scoring shape
  if (typeof result.composite === "number") {
    return (
      <div style={{ fontSize: 12, fontFamily: "var(--lys-font-body)", lineHeight: 1.5 }}>
        composite{" "}
        <strong style={{ color: LAV.fgDeep }}>{result.composite.toFixed(3)}</strong>
        {result.weakest && <> · weakest <strong>{result.weakest}</strong></>}
        {Array.isArray(result.components) && (
          <div style={{
            marginTop: 3, display: "flex", flexWrap: "wrap", gap: 4,
            fontFamily: "var(--lys-font-mono)", fontSize: 10,
          }}>
            {result.components.slice(0, 6).map((c: any, i: number) => (
              <span key={i} style={{
                padding: "1px 5px", borderRadius: 2,
                background: "rgba(0,0,0,0.04)", color: "var(--lys-text-dim)",
              }}>
                {c.name}={typeof c.value === "number" ? c.value.toFixed(2) : String(c.value)}
              </span>
            ))}
          </div>
        )}
      </div>
    );
  }
  // Resistance shape
  if (typeof result.robustness_score === "number") {
    return (
      <div style={{ fontSize: 12, fontFamily: "var(--lys-font-body)", lineHeight: 1.5 }}>
        robustness{" "}
        <strong style={{ color: LAV.fgDeep }}>{result.robustness_score.toFixed(3)}</strong>
        {" · "}n_escape <strong>{result.n_escape_vectors ?? 0}</strong>
        {Array.isArray(result.vulnerable_atoms) && result.vulnerable_atoms.length > 0 && (
          <div style={{
            marginTop: 3, fontFamily: "var(--lys-font-mono)", fontSize: 10,
            color: "var(--lys-text-faint)",
          }}>
            vulnerable atoms: {result.vulnerable_atoms.slice(0, 5).map((v: any) => `#${v.atom_idx}(${v.escape_score?.toFixed(2)})`).join(", ")}
          </div>
        )}
      </div>
    );
  }
  // Generic fallback — show top-level keys
  const keys = Object.keys(result).slice(0, 6);
  return (
    <div style={{
      fontFamily: "var(--lys-font-mono)", fontSize: 10.5,
      color: "var(--lys-text-dim)",
    }}>
      {keys.map((k) => `${k}`).join(" · ")}{Object.keys(result).length > 6 ? " · …" : ""}
    </div>
  );
}

function RawJsonToggle({ args, result }: { args: any; result: any }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button onClick={() => setOpen((o) => !o)}
        style={{
          background: "transparent", border: 0, padding: 0,
          color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)",
          fontSize: 10, cursor: "pointer",
          display: "inline-flex", alignItems: "center", gap: 3,
        }}>
        {open ? <ChevronDown size={9} /> : <ChevronRight size={9} />}
        raw json
      </button>
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 3 }}>
          <JsonBlock label="args" obj={args} />
          {result !== undefined && <JsonBlock label="result" obj={result} />}
        </div>
      )}
    </div>
  );
}


function TextBlock({ text }: { text: string }) {
  // Final assistant text — render markdown so **bold** / `code` /
  // headers / lists / SMILES-in-backticks display correctly. SMILES
  // wrapped in backticks become clickable load buttons via the
  // markdown renderer's onLoadSmiles hook.
  return (
    <div style={{ padding: "2px 0" }}>
      <MarkdownText text={text} fontSize={13.5} />
    </div>
  );
}


function JsonBlock({ label, obj }: { label: string; obj: any }) {
  let pretty = "";
  try { pretty = JSON.stringify(obj, null, 2); }
  catch { pretty = String(obj); }
  // Clamp to keep tool-result blocks from blowing up the chat
  const clamp = pretty.length > 4000 ? pretty.slice(0, 4000) + "\n…(truncated)" : pretty;
  return (
    <div>
      <div style={{
        fontSize: 8, color: "var(--lys-text-faint)",
        fontFamily: "var(--lys-font-mono)", fontWeight: 700,
        letterSpacing: "0.04em", textTransform: "uppercase",
        marginBottom: 1,
      }}>{label}</div>
      <pre style={{
        margin: 0, padding: "4px 6px",
        background: "rgba(0,0,0,0.04)",
        border: "1px solid rgba(0,0,0,0.06)",
        borderRadius: 3,
        fontFamily: "var(--lys-font-mono)", fontSize: 9, lineHeight: 1.45,
        whiteSpace: "pre-wrap", wordBreak: "break-word",
        maxHeight: 240, overflow: "auto",
        color: "var(--lys-text-dim)",
      }}>{clamp}</pre>
    </div>
  );
}


function summarizeArgs(args: any): string {
  try {
    if (!args || typeof args !== "object") return "";
    const entries = Object.entries(args).slice(0, 3);
    return entries.map(([k, v]) => {
      const vs = typeof v === "string"
        ? (v.length > 24 ? v.slice(0, 24) + "…" : v)
        : Array.isArray(v) ? `[${v.length}]` : JSON.stringify(v);
      return `${k}=${vs}`;
    }).join(" · ");
  } catch { return ""; }
}

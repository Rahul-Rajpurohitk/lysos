/**
 * MarkdownText — tiny zero-dependency markdown renderer for chat
 * surfaces (agent text, workflow summaries, orchestrator answers).
 *
 * Supports the subset the agent actually emits: **bold**, *italic*,
 * `inline code`, ```code blocks```, # headers, - / 1. lists,
 * [text](url), and clickable SMILES inside backticks (calls
 * onLoadSmiles when the SMILES looks valid).
 *
 * Anti-feature: no HTML pass-through, no XSS surface — every node
 * is created via React text nodes.
 */
import { useMemo } from "react";

interface Props {
  text: string;
  onLoadSmiles?: (smi: string) => void;
  fontSize?: number;
}

const RE_SMILES = /^[A-Za-z0-9@+\-\[\]\(\)=#$\/\\.%*]{4,}$/;

export function MarkdownText({ text, onLoadSmiles, fontSize = 13.5 }: Props) {
  const blocks = useMemo(() => parseBlocks(text ?? ""), [text]);
  return (
    <div style={{
      fontSize,
      lineHeight: 1.55,
      color: "var(--lys-text)",
      fontFamily: "var(--lys-font-body)",
      wordBreak: "break-word",
    }}>
      {blocks.map((b, i) => renderBlock(b, i, onLoadSmiles))}
    </div>
  );
}

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "code"; text: string; lang?: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "hr" }
  | { kind: "p"; text: string }
  | { kind: "blank" };

const TABLE_RE = /^\s*\|.+\|\s*$/;
const TABLE_SEP_RE = /^\s*\|?\s*[:\-]{3,}/;

function parseTableLine(line: string): string[] {
  // Split on `|`, drop leading/trailing empties.
  const cells = line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  return cells;
}

function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const out: Block[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (/^```/.test(line)) {
      const lang = line.replace(/^```/, "").trim() || undefined;
      const buf: string[] = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) {
        buf.push(lines[i]); i++;
      }
      if (i < lines.length) i++;
      out.push({ kind: "code", text: buf.join("\n"), lang });
      continue;
    }
    // Horizontal rule (--- or ***)
    if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) {
      out.push({ kind: "hr" });
      i++;
      continue;
    }
    const h = line.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      out.push({ kind: "heading", level: h[1].length, text: h[2].trim() });
      i++;
      continue;
    }
    // Pipe-table: header line + separator + body rows
    if (TABLE_RE.test(line) && i + 1 < lines.length && TABLE_SEP_RE.test(lines[i + 1])) {
      const header = parseTableLine(line);
      i += 2;  // skip header + separator
      const rows: string[][] = [];
      while (i < lines.length && TABLE_RE.test(lines[i])) {
        rows.push(parseTableLine(lines[i]));
        i++;
      }
      out.push({ kind: "table", header, rows });
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*]\s+/, ""));
        i++;
      }
      out.push({ kind: "ul", items });
      continue;
    }
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i++;
      }
      out.push({ kind: "ol", items });
      continue;
    }
    if (line.trim() === "") {
      out.push({ kind: "blank" });
      i++;
      continue;
    }
    const buf: string[] = [line];
    i++;
    while (i < lines.length && lines[i].trim() !== ""
        && !/^(#{1,4}\s|\s*[-*]\s|\s*\d+[.)]\s|```|\|)/.test(lines[i])
        && !/^\s*(-{3,}|\*{3,})\s*$/.test(lines[i])) {
      buf.push(lines[i]); i++;
    }
    out.push({ kind: "p", text: buf.join(" ") });
  }
  return out;
}

function renderBlock(b: Block, i: number, onLoadSmiles?: (smi: string) => void): React.ReactNode {
  if (b.kind === "blank") return <div key={i} style={{ height: 4 }} />;
  if (b.kind === "heading") {
    const sizes: Record<number, number> = { 1: 17, 2: 15.5, 3: 14, 4: 13 };
    return (
      <div key={i} style={{
        fontSize: sizes[b.level] ?? 13,
        fontWeight: 700,
        color: "var(--lys-text)",
        marginTop: i === 0 ? 0 : 6,
        marginBottom: 3,
        lineHeight: 1.3,
      }}>{renderInline(b.text, onLoadSmiles)}</div>
    );
  }
  if (b.kind === "code") {
    return (
      <pre key={i} style={{
        margin: "4px 0",
        padding: "6px 9px",
        background: "rgba(0,0,0,0.04)",
        border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
        borderRadius: 4,
        fontFamily: "var(--lys-font-mono)",
        fontSize: 11.5,
        lineHeight: 1.45,
        color: "var(--lys-text)",
        whiteSpace: "pre-wrap",
        overflowX: "auto",
      }}>{b.text}</pre>
    );
  }
  if (b.kind === "ul") {
    return (
      <ul key={i} style={{
        margin: "2px 0", paddingLeft: 18,
        display: "flex", flexDirection: "column", gap: 1,
      }}>
        {b.items.map((it, j) => (
          <li key={j} style={{ lineHeight: 1.5 }}>{renderInline(it, onLoadSmiles)}</li>
        ))}
      </ul>
    );
  }
  if (b.kind === "ol") {
    return (
      <ol key={i} style={{
        margin: "2px 0", paddingLeft: 22,
        display: "flex", flexDirection: "column", gap: 1,
      }}>
        {b.items.map((it, j) => (
          <li key={j} style={{ lineHeight: 1.5 }}>{renderInline(it, onLoadSmiles)}</li>
        ))}
      </ol>
    );
  }
  if (b.kind === "hr") {
    return <hr key={i} style={{
      margin: "8px 0", border: 0,
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
    }} />;
  }
  if (b.kind === "table") {
    return (
      <div key={i} style={{
        margin: "6px 0",
        overflowX: "auto",
        border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
        borderRadius: 4,
      }}>
        <table style={{
          width: "100%", borderCollapse: "collapse",
          fontSize: 12, fontFamily: "var(--lys-font-body)",
        }}>
          <thead>
            <tr>
              {b.header.map((h, j) => (
                <th key={j} style={{
                  padding: "5px 8px", textAlign: "left",
                  background: "rgba(0,0,0,0.04)",
                  borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
                  fontWeight: 700, color: "var(--lys-text)",
                }}>{renderInline(h, onLoadSmiles)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {b.rows.map((row, ri) => (
              <tr key={ri}>
                {row.map((cell, ci) => (
                  <td key={ci} style={{
                    padding: "4px 8px",
                    borderBottom: ri < b.rows.length - 1
                      ? "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))"
                      : "none",
                    color: "var(--lys-text-dim)",
                    verticalAlign: "top",
                  }}>{renderInline(cell, onLoadSmiles)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (b.kind === "p") {
    return (
      <p key={i} style={{
        margin: i === 0 ? "0 0 4px 0" : "4px 0",
        lineHeight: 1.55,
      }}>{renderInline(b.text, onLoadSmiles)}</p>
    );
  }
  return null;
}

type Span =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "italic"; text: string }
  | { kind: "code"; text: string; clickable: boolean }
  // Slash command embedded inside backticks (e.g. `/wf harden_candidate {...}`)
  // — clicking fires it through the composer's lysos:auto-slash channel.
  | { kind: "slash"; text: string }
  | { kind: "link"; text: string; href: string };

// Matches a slash command like:
//   /wf harden_candidate {"smiles": "..."}
//   /wf design_with_debate
//   /explain mecA
//   /score CCO
//   /harden CCO pdb=1VQQ
//   /champion
// Anything that starts with / + an alphanumeric command name + optional args.
const RE_SLASH = /^\/[a-z][a-z0-9_-]*(?:\s+.+)?$/i;

function renderInline(text: string, onLoadSmiles?: (smi: string) => void): React.ReactNode {
  const spans = parseInline(text);
  return (
    <>
      {spans.map((s, i) => {
        if (s.kind === "text") return <span key={i}>{s.text}</span>;
        if (s.kind === "bold") return <strong key={i} style={{ fontWeight: 700 }}>{s.text}</strong>;
        if (s.kind === "italic") return <em key={i} style={{ fontStyle: "italic" }}>{s.text}</em>;
        if (s.kind === "link") {
          return (
            <a key={i} href={s.href} target="_blank" rel="noreferrer"
              style={{ color: "var(--lys-accent, #6041d0)", textDecoration: "underline" }}>
              {s.text}
            </a>
          );
        }
        // Slash command chip — clicking re-fires it through the composer
        // pipeline so `/wf harden_candidate {…}` actually streams the
        // workflow instead of being inert text. CHECK FIRST so the
        // narrower discriminant is selected before s.clickable below.
        if (s.kind === "slash") {
          return (
            <button
              key={i}
              type="button"
              onClick={() => {
                window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
                  detail: { text: s.text },
                }));
              }}
              title={`Click to fire: ${s.text}`}
              style={{
                fontFamily: "var(--lys-font-mono)", fontSize: "0.92em",
                padding: "2px 7px",
                background: "linear-gradient(135deg, rgba(132,88,255,0.14), rgba(93,138,255,0.10))",
                border: "1px solid rgba(132,88,255,0.40)",
                borderRadius: 4,
                color: "#7c63d8", fontWeight: 700,
                cursor: "pointer",
                margin: "0 2px",
                display: "inline-flex", alignItems: "center", gap: 3,
                lineHeight: 1.3,
              }}>
              <span style={{ opacity: 0.7 }}>▸</span>
              {s.text.length > 60 ? s.text.slice(0, 57) + "…" : s.text}
            </button>
          );
        }
        // Below this point: s.kind === "code". Inline SMILES clickable
        // for load-in-3D, otherwise plain inline code.
        if (s.clickable && onLoadSmiles) {
          return (
            <button
              key={i}
              type="button"
              onClick={() => onLoadSmiles(s.text)}
              title="Load this SMILES into the 2D + 3D canvas"
              style={{
                fontFamily: "var(--lys-font-mono)", fontSize: "0.92em",
                padding: "1px 5px",
                background: "rgba(174,158,244,0.10)",
                border: "1px solid rgba(174,158,244,0.32)",
                borderRadius: 3,
                color: "#6041d0", fontWeight: 600,
                cursor: "pointer",
                margin: "0 1px",
                display: "inline",
                lineHeight: 1.3,
              }}>{s.text}</button>
          );
        }
        return (
          <code key={i} style={{
            fontFamily: "var(--lys-font-mono)", fontSize: "0.92em",
            padding: "1px 5px",
            background: "rgba(0,0,0,0.05)",
            borderRadius: 3,
            color: "var(--lys-text)",
          }}>{s.text}</code>
        );
      })}
    </>
  );
}

function parseInline(text: string): Span[] {
  // Greedy left-to-right scan for the next markdown token in priority
  // order: `code`, [link](url), **bold**, *italic*. Plain text fills
  // gaps. We use match() rather than the regex literal's exec to keep
  // the scanner stateless across iterations.
  const out: Span[] = [];
  let rest = text;
  const re = /(`[^`]+`)|(\[[^\]]+\]\([^)]+\))|(\*\*[^*]+\*\*)|(\*[^*\n]+\*)/;
  while (rest.length > 0) {
    const m = rest.match(re);
    if (!m || m.index == null) {
      if (rest) out.push({ kind: "text", text: rest });
      break;
    }
    const idx = m.index;
    if (idx > 0) out.push({ kind: "text", text: rest.slice(0, idx) });
    const tok = m[0];
    if (tok.startsWith("**")) {
      out.push({ kind: "bold", text: tok.slice(2, -2) });
    } else if (tok.startsWith("*")) {
      out.push({ kind: "italic", text: tok.slice(1, -1) });
    } else if (tok.startsWith("`")) {
      const inner = tok.slice(1, -1);
      // Priority: a slash command beats a SMILES match (so `/wf X` doesn't
      // get mistaken for a SMILES). Pure SMILES (no leading "/") still
      // becomes the load-in-3D clickable.
      if (RE_SLASH.test(inner)) {
        out.push({ kind: "slash", text: inner });
      } else {
        out.push({ kind: "code", text: inner, clickable: RE_SMILES.test(inner) });
      }
    } else if (tok.startsWith("[")) {
      const lm = tok.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (lm) out.push({ kind: "link", text: lm[1], href: lm[2] });
      else out.push({ kind: "text", text: tok });
    }
    rest = rest.slice(idx + tok.length);
  }
  return out;
}

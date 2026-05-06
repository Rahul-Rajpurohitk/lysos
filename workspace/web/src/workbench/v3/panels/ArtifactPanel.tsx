/**
 * ArtifactPanel — the right-hand "session document" view.
 *
 * Renders the active session as one continuous Claude.ai-style artifact
 * document: a markdown header (active candidate / target / score), then
 * an ordered stream of "blocks":
 *
 *   - markdown_text  — narrative/explanation from /explain, /similar, etc.
 *   - sandbox_cell   — code + stdout + stderr in a Jupyter-style block
 *   - scene_3d       — embedded 3D viewer (py3Dmol or Mol*)
 *   - score_table    — composite + per-axis breakdown bars
 *   - structure_2d   — RDKit 2D rendering
 *
 * Less boxy than the previous workbench: blocks separated by whitespace,
 * not borders. No card backgrounds. Top of the panel uses a sticky lite
 * meta header so context is always visible.
 */
import { Fragment, useEffect, useMemo, useRef } from "react";

export type ArtifactBlock =
  | { kind: "markdown_text"; text: string; source?: string }
  | { kind: "sandbox_cell"; code: string; stdout: string; stderr: string;
      elapsed_ms: number; status: "done" | "error" | "running" | "timeout" }
  | { kind: "scene_3d"; scene_id: string; pdb_text?: string;
      ligand_smiles?: string; highlights?: { residue: string; color?: string }[] }
  | { kind: "score_table"; smiles: string; composite: number;
      breakdown: { name: string; value: number; weight: number; source?: string }[] }
  | { kind: "structure_2d"; smiles: string; svg?: string; label?: string };

export interface ArtifactDoc {
  session_id: string;
  active_smiles: string | null;
  active_target: string | null;
  active_score: number | null;
  blocks: ArtifactBlock[];
}

interface Props {
  doc: ArtifactDoc;
  onRunCell?: (code: string) => void;
  onForkBlock?: (idx: number) => void;
}

export function ArtifactPanel({ doc, onRunCell, onForkBlock }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [doc.blocks.length]);

  return (
    <div className="lys-artifact" ref={scrollRef}>
      <div className="lys-artifact-head">
        <div className="lys-artifact-head-left">
          <div className="lys-artifact-target">
            {doc.active_target ?? <span className="lys-artifact-empty">no target</span>}
          </div>
          <div className="lys-artifact-smiles">
            {doc.active_smiles ? (
              <code>{truncSmiles(doc.active_smiles)}</code>
            ) : (
              <span className="lys-artifact-empty">no candidate</span>
            )}
          </div>
        </div>
        <div className="lys-artifact-head-right">
          {doc.active_score !== null && <ScoreChip value={doc.active_score} />}
        </div>
      </div>

      <div className="lys-artifact-body">
        {doc.blocks.length === 0 && (
          <div className="lys-artifact-placeholder">
            <p>Workspace empty.</p>
            <p>
              Type <code>/design MRSA</code> or <code>/explain amoxicillin</code> to begin.
              Results land here as a runnable document.
            </p>
          </div>
        )}
        {doc.blocks.map((block, i) => (
          <ArtifactBlockView
            key={i}
            block={block}
            index={i}
            onRunCell={onRunCell}
            onForkBlock={onForkBlock}
          />
        ))}
      </div>
    </div>
  );
}

function ArtifactBlockView({
  block, onRunCell,
}: { block: ArtifactBlock; index: number;
     onRunCell?: (code: string) => void;
     onForkBlock?: (idx: number) => void }) {
  const k = block.kind;

  if (k === "markdown_text") {
    return (
      <section className="lys-artifact-block lys-artifact-md">
        {block.source && (
          <div className="lys-artifact-source">{block.source}</div>
        )}
        <SimpleMarkdown text={block.text} />
      </section>
    );
  }

  if (k === "sandbox_cell") {
    return (
      <section className={`lys-artifact-block lys-artifact-cell lys-artifact-cell-${block.status}`}>
        <div className="lys-artifact-cell-head">
          <span className="lys-artifact-cell-status">{block.status}</span>
          <span className="lys-artifact-cell-elapsed">{block.elapsed_ms} ms</span>
          <button
            className="lys-artifact-rerun"
            onClick={() => onRunCell?.(block.code)}
            title="Re-run this cell"
          >re-run</button>
        </div>
        <pre className="lys-artifact-code"><code>{block.code}</code></pre>
        {block.stdout && (
          <pre className="lys-artifact-stdout">{block.stdout}</pre>
        )}
        {block.stderr && (
          <pre className="lys-artifact-stderr">{block.stderr}</pre>
        )}
      </section>
    );
  }

  if (k === "scene_3d") {
    return (
      <section className="lys-artifact-block lys-artifact-scene">
        <div className="lys-artifact-scene-head">
          <span>3D Scene · {block.scene_id.slice(0, 8)}</span>
        </div>
        <div className="lys-artifact-scene-body">
          <Scene3DPlaceholder pdb={block.pdb_text} ligand={block.ligand_smiles}
                              highlights={block.highlights} />
        </div>
      </section>
    );
  }

  if (k === "score_table") {
    return (
      <section className="lys-artifact-block lys-artifact-score">
        <div className="lys-artifact-score-head">
          <code>{truncSmiles(block.smiles)}</code>
          <span className="lys-artifact-composite">{block.composite.toFixed(3)}</span>
        </div>
        <table className="lys-artifact-score-tbl">
          <tbody>
            {block.breakdown.map((b) => (
              <tr key={b.name}>
                <td className="lys-axis-name">{b.name}</td>
                <td className="lys-axis-bar">
                  <div
                    className="lys-axis-fill"
                    style={{ width: `${Math.min(100, Math.abs(b.value) * 100)}%` }}
                  />
                </td>
                <td className="lys-axis-value">{b.value.toFixed(3)}</td>
                <td className="lys-axis-weight">×{b.weight.toFixed(2)}</td>
                {b.source && <td className="lys-axis-source">{b.source}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    );
  }

  if (k === "structure_2d") {
    return (
      <section className="lys-artifact-block lys-artifact-2d">
        {block.label && <div className="lys-artifact-2d-label">{block.label}</div>}
        {block.svg ? (
          <img
            className="lys-artifact-2d-svg"
            alt={block.label ?? block.smiles}
            src={`data:image/svg+xml;utf8,${encodeURIComponent(block.svg)}`}
          />
        ) : (
          <code className="lys-artifact-2d-fallback">{block.smiles}</code>
        )}
      </section>
    );
  }

  return null;
}

// ---------- helpers ----------

function truncSmiles(s: string, n = 40): string {
  if (s.length <= n) return s;
  return s.slice(0, n) + "…";
}

function ScoreChip({ value }: { value: number }) {
  let cls = "lys-score-mid";
  if (value >= 1.0) cls = "lys-score-high";
  else if (value < 0.0) cls = "lys-score-low";
  return (
    <span className={`lys-score-chip ${cls}`}>
      {value.toFixed(2)}
    </span>
  );
}

// Minimal safe markdown — paragraphs, headings, fenced code, plus inline
// `code`, **bold**, _italic_. Renders entirely via React nodes (no
// innerHTML, no XSS surface).
function SimpleMarkdown({ text }: { text: string }) {
  const blocks = useMemo(() => text.split(/\n{2,}/), [text]);
  return (
    <>
      {blocks.map((b, i) => {
        if (b.startsWith("```") && b.endsWith("```")) {
          const lines = b.split("\n");
          return (
            <pre key={i} className="lys-artifact-code-inline">
              <code>{lines.slice(1, -1).join("\n")}</code>
            </pre>
          );
        }
        if (b.startsWith("### ")) return <h3 key={i}><InlineSpans text={b.slice(4)} /></h3>;
        if (b.startsWith("## ")) return <h2 key={i}><InlineSpans text={b.slice(3)} /></h2>;
        if (b.startsWith("# ")) return <h1 key={i}><InlineSpans text={b.slice(2)} /></h1>;
        return <p key={i}><InlineSpans text={b} /></p>;
      })}
    </>
  );
}

function InlineSpans({ text }: { text: string }) {
  // Tokenize into segments: code (`...`), bold (**...**), ital (_..._), or plain.
  // Uses String.matchAll for safety (no shared regex state, no innerHTML).
  const segments: { type: "plain" | "code" | "bold" | "ital"; text: string }[] = [];
  const matchPattern = /`[^`]+`|\*\*[^*]+\*\*|_[^_]+_/g;
  const matches = Array.from(text.matchAll(matchPattern));
  let last = 0;
  for (const m of matches) {
    const idx = m.index ?? 0;
    if (idx > last) segments.push({ type: "plain", text: text.slice(last, idx) });
    const tok = m[0];
    if (tok.startsWith("`")) segments.push({ type: "code", text: tok.slice(1, -1) });
    else if (tok.startsWith("**")) segments.push({ type: "bold", text: tok.slice(2, -2) });
    else segments.push({ type: "ital", text: tok.slice(1, -1) });
    last = idx + tok.length;
  }
  if (last < text.length) segments.push({ type: "plain", text: text.slice(last) });
  return (
    <>
      {segments.map((seg, i) => {
        if (seg.type === "code") return <code key={i}>{seg.text}</code>;
        if (seg.type === "bold") return <strong key={i}>{seg.text}</strong>;
        if (seg.type === "ital") return <em key={i}>{seg.text}</em>;
        return <Fragment key={i}>{seg.text}</Fragment>;
      })}
    </>
  );
}

function Scene3DPlaceholder({
  pdb, ligand, highlights,
}: { pdb?: string; ligand?: string;
     highlights?: { residue: string; color?: string }[] }) {
  return (
    <div className="lys-scene-placeholder">
      <div className="lys-scene-placeholder-icon">⌬</div>
      <div className="lys-scene-placeholder-body">
        {pdb && <div>PDB: {pdb.slice(0, 80)}{pdb.length > 80 ? "…" : ""}</div>}
        {ligand && <div>Ligand: <code>{ligand}</code></div>}
        {highlights && highlights.length > 0 && (
          <div>Highlights: {highlights.map((h) => h.residue).join(", ")}</div>
        )}
        <div className="lys-scene-todo">
          (3D viewer wires up to py3Dmol once the live scene events stream)
        </div>
      </div>
    </div>
  );
}

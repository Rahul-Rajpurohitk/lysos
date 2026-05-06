/**
 * ScaffoldTreeCard — chat card for W3 (SAR exploration) results.
 *
 * Renders the response from POST /workbench/sar/expand: parent SMILES at
 * top, children laid out as a horizontal tree below sorted by delta.
 * Each child row is click-to-load: hits the parent's onLoadSmiles handler
 * so the 3D viewer + radar update with the selected mutant.
 *
 * Visual model:
 *
 *   ┌─ SAR · 5 mutants · best Δ+0.025 ────────────────────┐
 *   │ parent  CC(=O)Oc1ccccc1C(=O)O    composite 0.548    │
 *   ├──────────────────────────────────────────────────────┤
 *   │ ↑ Δ+0.025  +F (aromatic)  composite 0.573  ▶ load   │  ← green delta
 *   │ ↑ Δ+0.019  C→N at idx 6   composite 0.567  ▶ load   │
 *   │ ↑ Δ+0.011  +OH at idx 7   composite 0.559  ▶ load   │
 *   │ ↑ Δ+0.006  +CH₃ at idx 12 composite 0.554  ▶ load   │
 *   │ ↓ Δ-0.014  +OH at idx 0   composite 0.534  ▶ load   │  ← red delta
 *   └──────────────────────────────────────────────────────┘
 */
import { motion } from "framer-motion";
import { TreePine, ArrowUpRight, ArrowDownRight, ArrowRight } from "lucide-react";
import { ChatMsg } from "./MessageRow";

interface SARData {
  parent?: { smiles?: string; composite?: number; weakest?: string; strongest?: string };
  children?: SARChild[];
  n_accepted?: number;
  n_proposed?: number;
  elapsed_ms?: number;
}

interface SARChild {
  smiles: string;
  op: string;
  op_label: string;
  composite: number;
  delta_vs_parent: number;
  weakest?: string;
  strongest?: string;
  error?: string;
}

interface Props {
  msg: ChatMsg;
  onLoadSmiles?: (smiles: string) => void;
}

function deltaColor(d: number): string {
  if (d > 0.005) return "var(--lys-accent)";       // gain
  if (d < -0.005) return "#dc2626";                  // loss
  return "var(--lys-text-faint)";                   // ~zero
}

function deltaArrow(d: number) {
  if (d > 0.005) return <ArrowUpRight size={11} />;
  if (d < -0.005) return <ArrowDownRight size={11} />;
  return <ArrowRight size={11} />;
}

export function ScaffoldTreeCard({ msg, onLoadSmiles }: Props) {
  const data = (msg.data ?? {}) as SARData;
  const parent = data.parent ?? {};
  const children = (data.children ?? []) as SARChild[];
  const bestDelta = children.length
    ? Math.max(...children.map((c) => c.delta_vs_parent))
    : 0;

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
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        background: "rgba(16, 185, 129, 0.05)",
        borderBottom: "1px solid var(--lys-border)",
      }}>
        <TreePine size={13} style={{ color: "var(--lys-accent)", flexShrink: 0 }} />
        <span style={{
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}>
          SAR · {data.n_accepted ?? children.length} mutants ·
        </span>
        <span style={{
          fontSize: 11,
          fontFamily: "var(--lys-font-mono)",
          color: deltaColor(bestDelta),
          fontWeight: 600,
        }}>
          best Δ{bestDelta >= 0 ? "+" : ""}{bestDelta.toFixed(3)}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
        }}>
          {data.elapsed_ms ?? 0}ms
        </span>
      </div>

      {/* Parent row */}
      <button
        type="button"
        onClick={() => parent.smiles && onLoadSmiles?.(parent.smiles)}
        title="Load parent SMILES into viewer"
        style={{
          display: "grid",
          gridTemplateColumns: "1fr auto",
          gap: 12,
          alignItems: "center",
          width: "100%",
          padding: "6px 12px",
          border: 0,
          background: "transparent",
          textAlign: "left",
          cursor: parent.smiles ? "pointer" : "default",
          fontFamily: "inherit",
          color: "var(--lys-text)",
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        }}
      >
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 9,
            fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}>
            parent
          </div>
          <div style={{
            fontFamily: "var(--lys-font-mono)",
            fontSize: 11,
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}>
            {parent.smiles ?? "—"}
          </div>
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <div style={{
            fontSize: 9,
            fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}>
            composite
          </div>
          <div style={{
            fontSize: 14,
            fontWeight: 700,
            fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text)",
          }}>
            {(parent.composite ?? 0).toFixed(3)}
          </div>
        </div>
      </button>

      {/* Children rows */}
      <div>
        {children.map((c, i) => {
          const dColor = deltaColor(c.delta_vs_parent);
          return (
            <button
              key={i}
              type="button"
              onClick={() => !c.error && onLoadSmiles?.(c.smiles)}
              disabled={!!c.error}
              title={c.error ? `error: ${c.error}` : "Load mutant into viewer"}
              className="lys-sar-row"
              style={{
                display: "grid",
                gridTemplateColumns: "auto 80px 1fr 70px",
                gap: 8,
                alignItems: "center",
                width: "100%",
                padding: "5px 12px",
                border: 0,
                background: "transparent",
                textAlign: "left",
                cursor: c.error ? "not-allowed" : "pointer",
                fontFamily: "inherit",
                fontSize: 10.5,
                color: c.error ? "var(--lys-text-faint)" : "var(--lys-text)",
                borderTop: i === 0 ? 0 : "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
                opacity: c.error ? 0.5 : 1,
                transition: "background 0.12s",
              }}
            >
              <span style={{ display: "inline-flex", alignItems: "center", gap: 3, color: dColor }}>
                {deltaArrow(c.delta_vs_parent)}
                <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 600 }}>
                  {c.delta_vs_parent >= 0 ? "+" : ""}{c.delta_vs_parent.toFixed(3)}
                </span>
              </span>
              <span style={{
                fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-dim)",
                fontSize: 10.5,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}>
                {c.op_label || c.op}
              </span>
              <span style={{
                fontFamily: "var(--lys-font-mono)",
                fontSize: 10,
                color: "var(--lys-text-faint)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}>
                {c.error ? c.error : c.smiles}
              </span>
              <span style={{
                fontFamily: "var(--lys-font-mono)",
                fontSize: 11,
                fontWeight: 600,
                textAlign: "right",
                color: dColor,
              }}>
                {c.composite.toFixed(3)}
              </span>
            </button>
          );
        })}
      </div>
    </motion.div>
  );
}

/**
 * StressTestCard — chat card for W5 (red-team Critic) results.
 *
 * Renders POST /workbench/stress: a structured list of attack vectors
 * with severity-coded chips. Each attack has a one-line mode header,
 * 1-3 sentence "why_fails", an optional mitigation, and an optional
 * smiles_variant the user can click to load into the 3D viewer.
 *
 * Layout:
 *   ┌─ red-team · 6 attacks · 2 high-severity ────────────────┐
 *   │ <2-sentence summary verdict>                              │
 *   ├──────────────────────────────────────────────────────────┤
 *   │ 🔴 KPC β-lactamase hydrolysis            HIGH            │
 *   │    The β-lactam core has a carbonyl exposed to KPC's…    │
 *   │    Mitigation: introduce a steric block at C-7 …          │
 *   │    [▶ load CC(=O)Oc...]                                  │
 *   ├──────────────────────────────────────────────────────────┤
 *   │ 🟠 PAINS aromatic substitution           MEDIUM          │
 *   │    …                                                     │
 *   └──────────────────────────────────────────────────────────┘
 */
import { useState } from "react";
import { motion } from "framer-motion";
import { ShieldAlert, ChevronDown, ChevronRight, ArrowRight } from "lucide-react";
import { ChatMsg } from "./MessageRow";

interface Attack {
  mode: string;
  severity: "high" | "medium" | "low";
  why_fails: string;
  mitigation?: string;
  smiles_variant?: string;
}

interface StressData {
  smiles?: string;
  target_pathogen?: string;
  summary?: string;
  attacks?: Attack[];
  model?: string;
  elapsed_ms?: number;
}

interface Props {
  msg: ChatMsg;
  onLoadSmiles?: (smiles: string) => void;
}

const SEVERITY_COLOR: Record<string, string> = {
  high: "#dc2626",
  medium: "#d97706",
  low: "#65a30d",
};
const SEVERITY_DOT: Record<string, string> = {
  high: "🔴", medium: "🟠", low: "🟡",
};

export function StressTestCard({ msg, onLoadSmiles }: Props) {
  const data = (msg.data ?? {}) as StressData;
  const attacks: Attack[] = data.attacks ?? [];
  const nHigh = attacks.filter((a) => a.severity === "high").length;

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
        background: "rgba(220, 38, 38, 0.04)",
        borderBottom: "1px solid var(--lys-border)",
      }}>
        <ShieldAlert size={14} style={{ color: "#dc2626", flexShrink: 0 }} />
        <span style={{
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}>
          red-team · {attacks.length} attacks
        </span>
        {nHigh > 0 && (
          <span style={{
            fontSize: 10,
            fontFamily: "var(--lys-font-mono)",
            color: "#dc2626",
            fontWeight: 600,
          }}>
            · {nHigh} high
          </span>
        )}
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
        }}>
          {data.elapsed_ms ?? 0}ms · {data.model ?? "—"}
        </span>
      </div>

      {/* Verdict */}
      {data.summary && (
        <div style={{
          padding: "8px 12px",
          color: "var(--lys-text-dim)",
          fontStyle: "italic",
          lineHeight: 1.45,
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
          fontSize: 11.5,
        }}>
          {data.summary}
        </div>
      )}

      {/* Attack list */}
      <div>
        {attacks.map((a, i) => (
          <AttackRow key={i} attack={a} onLoadSmiles={onLoadSmiles} />
        ))}
      </div>
    </motion.div>
  );
}

function AttackRow({ attack, onLoadSmiles }: { attack: Attack; onLoadSmiles?: (s: string) => void }) {
  const [open, setOpen] = useState(true);
  const sevColor = SEVERITY_COLOR[attack.severity] ?? "#9ca3af";
  return (
    <div style={{
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
    }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          width: "100%",
          padding: "6px 12px",
          border: 0,
          background: "transparent",
          textAlign: "left",
          cursor: "pointer",
          fontFamily: "inherit",
          fontSize: 11.5,
          color: "var(--lys-text)",
        }}
      >
        <span style={{ fontSize: 10 }}>{SEVERITY_DOT[attack.severity]}</span>
        <span style={{
          flex: 1,
          fontWeight: 500,
          minWidth: 0,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {attack.mode}
        </span>
        <span style={{
          fontSize: 8.5,
          fontFamily: "var(--lys-font-mono)",
          letterSpacing: "0.06em",
          padding: "1px 5px",
          borderRadius: 3,
          background: `${sevColor}15`,
          color: sevColor,
          fontWeight: 600,
          flexShrink: 0,
        }}>
          {attack.severity.toUpperCase()}
        </span>
        <span style={{ color: "var(--lys-text-faint)", flexShrink: 0 }}>
          {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        </span>
      </button>
      {open && (
        <div style={{
          padding: "0 12px 8px 30px",
          fontSize: 10.5,
          color: "var(--lys-text-dim)",
          lineHeight: 1.5,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        }}>
          <p style={{ margin: 0 }}>{attack.why_fails}</p>
          {attack.mitigation && (
            <p style={{ margin: 0 }}>
              <span style={{
                fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-accent)",
                fontWeight: 600,
                marginRight: 4,
              }}>
                fix:
              </span>
              {attack.mitigation}
            </p>
          )}
          {attack.smiles_variant && (
            <button
              type="button"
              onClick={() => onLoadSmiles?.(attack.smiles_variant!)}
              style={{
                alignSelf: "flex-start",
                marginTop: 2,
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                padding: "2px 8px",
                border: 0,
                borderRadius: 999,
                background: "var(--lys-bg-hover, rgba(16, 185, 129, 0.08))",
                color: "var(--lys-accent)",
                fontFamily: "var(--lys-font-mono)",
                fontSize: 10,
                fontWeight: 600,
                cursor: "pointer",
              }}
              title={`Load ${attack.smiles_variant}`}
            >
              <ArrowRight size={10} />
              load variant
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * RewardCard — chat card for /score results (W2).
 *
 * Renders the 12-component reward breakdown returned by
 * POST /workbench/score. Layout:
 *
 *   ┌─ score ───────────────────────────┬──────────────┐
 *   │ CCO                               │ composite    │
 *   │ MRSA target                       │   0.645      │
 *   ├───────────────────────────────────┴──────────────┤
 *   │ predicted_mic       ████████░░░░░ 0.41 · w 0.30 │
 *   │ drug_likeness_qed   ██████░░░░░░░ 0.55 · w 0.15 │
 *   │ hemolysis_safety    █████████████ 1.00 · w 0.15 │
 *   │ ...                                              │
 *   ├──────────────────────────────────────────────────┤
 *   │ weakest: embedding_novelty   strongest: novelty │
 *   └──────────────────────────────────────────────────┘
 *
 * Per-component bar shows raw value × weight, color-coded by tier:
 *   ≥0.7 accent green · 0.4-0.7 amber · <0.4 muted-red.
 */
import { motion } from "framer-motion";
import { ChatMsg } from "./MessageRow";

interface RewardCardProps {
  msg: ChatMsg;
  onLoadSmiles?: (smi: string) => void;
}

interface ComponentScore {
  name: string;
  value: number;
  weight: number;
  contribution: number;
}

interface RewardBreakdown {
  smiles?: string;
  target_pathogen?: string;
  composite?: number;
  components?: ComponentScore[];
  weakest?: string;
  strongest?: string;
}

function tierColor(value: number): string {
  if (value >= 0.7) return "var(--lys-accent)";
  if (value >= 0.4) return "#d97706";  // amber
  return "#9ca3af";                    // muted
}

export function RewardCard({ msg, onLoadSmiles }: RewardCardProps) {
  const data = (msg.data ?? {}) as RewardBreakdown;
  const composite = data.composite ?? 0;
  const components = data.components ?? [];
  const sortedComponents = [...components].sort(
    (a, b) => b.contribution - a.contribution
  );

  const compositePct = Math.round(composite * 100);

  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.22, ease: "easeOut" }}
      style={{
        background: "var(--lys-surface)",
        borderRadius: 8,
        border: "1px solid var(--lys-border)",
        // overflow:visible so the per-axis bar list doesn't clip when
        // a parent flex container computes a shorter natural height
        // than the card's content (user saw 4 of 8 axes truncated).
        overflow: "visible",
        fontSize: 11.5,
        // Don't let the card collapse below its natural content height.
        flex: "0 0 auto",
      }}
    >
      {/* Header: smiles + target  |  big composite */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "1fr auto",
        gap: 10,
        padding: "8px 12px",
        background: "rgba(16, 185, 129, 0.05)",
        borderBottom: "1px solid var(--lys-border)",
        alignItems: "center",
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontSize: 9.5,
            fontFamily: "var(--lys-font-mono)",
            color: "var(--lys-text-faint)",
            letterSpacing: "0.06em",
            textTransform: "uppercase",
            marginBottom: 1,
          }}>
            score · {data.target_pathogen ?? "MRSA"}
          </div>
          <button
            type="button"
            onClick={() => data.smiles && onLoadSmiles?.(data.smiles)}
            title={data.smiles ? "Load this SMILES into the 3D viewer" : ""}
            style={{
              all: "unset",
              cursor: onLoadSmiles ? "pointer" : "default",
              fontFamily: "var(--lys-font-mono)",
              fontSize: 12,
              fontWeight: 600,
              color: "var(--lys-text)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
              display: "block",
              maxWidth: "100%",
            }}
          >
            {data.smiles ?? "—"}
          </button>
        </div>
        <div style={{ textAlign: "right" }}>
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
            fontSize: 22,
            fontWeight: 700,
            color: tierColor(composite),
            lineHeight: 1.1,
            fontFamily: "var(--lys-font-mono)",
          }}>
            {composite.toFixed(3)}
            <span style={{
              fontSize: 11,
              color: "var(--lys-text-faint)",
              fontWeight: 400,
              marginLeft: 4,
            }}>
              {compositePct}%
            </span>
          </div>
        </div>
      </div>

      {/* Per-component bars */}
      <div style={{
        padding: "8px 12px 10px 12px",
        display: "flex",
        flexDirection: "column",
        gap: 4,
      }}>
        {sortedComponents.map((c) => {
          const valuePct = Math.round(c.value * 100);
          return (
            <div key={c.name} style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr 70px",
              gap: 8,
              alignItems: "center",
              fontSize: 10.5,
            }}>
              <span style={{
                color: "var(--lys-text-dim)",
                fontFamily: "var(--lys-font-mono)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}>
                {c.name}
              </span>
              <div style={{
                position: "relative",
                height: 5,
                background: "var(--lys-surface-2)",
                borderRadius: 3,
                overflow: "hidden",
              }}>
                <div style={{
                  position: "absolute",
                  left: 0,
                  top: 0,
                  bottom: 0,
                  width: `${valuePct}%`,
                  background: tierColor(c.value),
                  borderRadius: 3,
                  transition: "width 0.3s ease",
                }} />
              </div>
              <span style={{
                fontSize: 10,
                fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)",
                textAlign: "right",
                whiteSpace: "nowrap",
              }}>
                {c.value.toFixed(2)} · w{c.weight.toFixed(2)}
              </span>
            </div>
          );
        })}
      </div>

      {/* Footer: weakest / strongest */}
      {(data.weakest || data.strongest) && (
        <div style={{
          padding: "6px 12px",
          background: "var(--lys-surface-2)",
          borderTop: "1px solid var(--lys-border)",
          display: "flex",
          gap: 12,
          fontSize: 10,
          color: "var(--lys-text-dim)",
          fontFamily: "var(--lys-font-mono)",
        }}>
          {data.weakest && (
            <span>
              <span style={{ color: "var(--lys-text-faint)" }}>weakest </span>
              <span style={{ color: "#dc2626" }}>{data.weakest}</span>
            </span>
          )}
          {data.strongest && (
            <span>
              <span style={{ color: "var(--lys-text-faint)" }}>strongest </span>
              <span style={{ color: "var(--lys-accent)" }}>{data.strongest}</span>
            </span>
          )}
        </div>
      )}
    </motion.div>
  );
}

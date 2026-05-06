/**
 * ComparisonCard — chat card for W6 (N-candidate side-by-side).
 *
 * POST /workbench/compare returns scored breakdowns for each candidate
 * + a component-winner map. We render:
 *   - Header strip: target pathogen, candidate count, elapsed
 *   - Candidate columns at the top: rank · composite · click-to-load
 *   - Per-component rows below: bars per candidate, with a 👑 chip on
 *     the component winner
 */
import { motion } from "framer-motion";
import { GitCompareArrows, Crown } from "lucide-react";
import { ChatMsg } from "./MessageRow";

interface ComponentScore {
  name: string;
  value: number;
  weight: number;
  contribution?: number;
}

interface CompareEntry {
  smiles: string;
  composite: number;
  weakest?: string;
  strongest?: string;
  components: ComponentScore[];
  rank: number;
  error?: string;
}

interface CompareData {
  target_pathogen?: string;
  entries?: CompareEntry[];
  component_winners?: Record<string, string>;
  elapsed_ms?: number;
}

interface Props {
  msg: ChatMsg;
  onLoadSmiles?: (smiles: string) => void;
}

function tierColor(value: number): string {
  if (value >= 0.7) return "var(--lys-accent)";
  if (value >= 0.4) return "#d97706";
  return "#9ca3af";
}

export function ComparisonCard({ msg, onLoadSmiles }: Props) {
  const data = (msg.data ?? {}) as CompareData;
  const entries: CompareEntry[] = data.entries ?? [];
  const valid = entries.filter((e) => !e.error);
  const winners = data.component_winners ?? {};

  // Build column ordering: rank ascending so columns mirror leaderboard
  const ordered = [...valid].sort((a, b) => a.rank - b.rank);
  // Component name list (use first valid entry's components as canonical order)
  const componentNames: string[] = ordered[0]?.components.map((c) => c.name) ?? [];

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
        background: "rgba(59, 130, 246, 0.04)",
        borderBottom: "1px solid var(--lys-border)",
      }}>
        <GitCompareArrows size={14} style={{ color: "#3b82f6", flexShrink: 0 }} />
        <span style={{
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}>
          compare · {entries.length} candidates · {data.target_pathogen ?? "MRSA"}
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

      {/* Candidate columns at top */}
      <div style={{
        display: "grid",
        gridTemplateColumns: `120px repeat(${ordered.length}, 1fr)`,
        gap: 6,
        padding: "8px 12px",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      }}>
        <div style={{
          fontSize: 9,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          alignSelf: "end",
        }}>
          component
        </div>
        {ordered.map((e) => (
          <button
            key={e.smiles}
            type="button"
            onClick={() => onLoadSmiles?.(e.smiles)}
            title={`Load ${e.smiles} into viewer`}
            style={{
              border: 0,
              background: "transparent",
              padding: 4,
              cursor: "pointer",
              textAlign: "left",
              display: "flex",
              flexDirection: "column",
              gap: 2,
              minWidth: 0,
              borderRadius: 4,
              transition: "background 0.12s",
            }}
            onMouseEnter={(ev) => (ev.currentTarget.style.background = "rgba(59,130,246,0.06)")}
            onMouseLeave={(ev) => (ev.currentTarget.style.background = "transparent")}
          >
            <div style={{
              fontSize: 9.5,
              fontFamily: "var(--lys-font-mono)",
              color: e.rank === 1 ? "var(--lys-accent)" : "var(--lys-text-faint)",
              fontWeight: 600,
            }}>
              #{e.rank}
            </div>
            <div style={{
              fontSize: 14,
              fontFamily: "var(--lys-font-mono)",
              fontWeight: 700,
              color: tierColor(e.composite),
            }}>
              {e.composite.toFixed(3)}
            </div>
            <div style={{
              fontSize: 9.5,
              fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-dim)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}>
              {e.smiles}
            </div>
          </button>
        ))}
      </div>

      {/* Per-component rows */}
      <div style={{ padding: "6px 12px" }}>
        {componentNames.map((name) => (
          <div key={name} style={{
            display: "grid",
            gridTemplateColumns: `120px repeat(${ordered.length}, 1fr)`,
            gap: 6,
            alignItems: "center",
            padding: "3px 0",
            fontSize: 10.5,
          }}>
            <span style={{
              fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-dim)",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}>
              {name}
            </span>
            {ordered.map((e) => {
              const c = e.components.find((x) => x.name === name);
              const v = c?.value ?? 0;
              const isWinner = winners[name] === e.smiles;
              return (
                <div key={e.smiles} style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 4,
                  position: "relative",
                  height: 18,
                  background: "var(--lys-surface-2)",
                  borderRadius: 3,
                  overflow: "hidden",
                  paddingLeft: 4,
                  paddingRight: 4,
                }}>
                  <div style={{
                    position: "absolute",
                    left: 0,
                    top: 0,
                    bottom: 0,
                    width: `${Math.round(v * 100)}%`,
                    background: tierColor(v),
                    opacity: 0.18,
                  }} />
                  <span style={{
                    position: "relative",
                    fontFamily: "var(--lys-font-mono)",
                    fontSize: 10,
                    color: "var(--lys-text)",
                    fontWeight: isWinner ? 600 : 400,
                  }}>
                    {v.toFixed(2)}
                  </span>
                  {isWinner && (
                    <Crown size={9} style={{
                      position: "relative",
                      color: "var(--lys-accent)",
                      marginLeft: "auto",
                    }} />
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </div>

      {/* Errored entries footer (if any) */}
      {entries.filter((e) => e.error).length > 0 && (
        <div style={{
          padding: "6px 12px",
          background: "var(--lys-surface-2)",
          borderTop: "1px solid var(--lys-border)",
          fontSize: 10,
          color: "#dc2626",
          fontFamily: "var(--lys-font-mono)",
        }}>
          {entries.filter((e) => e.error).length} candidate(s) failed to score:
          {entries.filter((e) => e.error).map((e, i) => (
            <span key={i}> {e.smiles} ({e.error?.slice(0, 60)})</span>
          ))}
        </div>
      )}
    </motion.div>
  );
}

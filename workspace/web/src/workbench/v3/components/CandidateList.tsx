import { Star, Copy } from "lucide-react";
import { useState } from "react";

interface CandidateListItem {
  id: string;
  smiles: string;
  composite: number;
  isPareto: boolean;
  scores?: Record<string, number>;
}

interface CandidateListProps {
  items: CandidateListItem[];
  onSelect?: (id: string) => void;
}

export function CandidateList({ items, onSelect }: CandidateListProps) {
  const [copied, setCopied] = useState<string | null>(null);
  const sorted = [...items].sort((a, b) => b.composite - a.composite);
  const paretoCount = sorted.filter((i) => i.isPareto).length;

  if (items.length === 0) {
    return (
      <div style={{
        padding: 12, fontSize: 11, color: "var(--lys-text-faint)",
        borderTop: "1px solid var(--lys-border)",
      }}>
        no candidates yet
      </div>
    );
  }

  return (
    <div style={{
      borderTop: "1px solid var(--lys-border)",
      maxHeight: 260,
      display: "flex",
      flexDirection: "column",
    }}>
      <div style={{
        padding: "8px 12px",
        fontSize: 11,
        color: "var(--lys-text-faint)",
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        display: "flex",
        justifyContent: "space-between",
        position: "sticky",
        top: 0,
        background: "var(--lys-bg-2)",
      }}>
        <span>candidates</span>
        <span>{items.length} · {paretoCount} Pareto</span>
      </div>
      <div style={{ overflowY: "auto", flex: 1 }}>
        {sorted.map((c, i) => (
          <button
            key={c.id}
            onClick={() => onSelect?.(c.id)}
            style={{
              width: "100%",
              padding: "8px 12px",
              border: 0,
              borderTop: i > 0 ? "1px solid var(--lys-border)" : "none",
              background: c.isPareto ? "rgba(52,211,153,0.06)" : "transparent",
              textAlign: "left",
              cursor: "pointer",
              fontFamily: "inherit",
              color: "var(--lys-text)",
              transition: "background 0.1s",
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = c.isPareto
                ? "rgba(52,211,153,0.12)"
                : "var(--lys-surface-2)";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = c.isPareto
                ? "rgba(52,211,153,0.06)"
                : "transparent";
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 11, fontFamily: "var(--lys-font-mono)", color: "var(--lys-text-faint)" }}>
                #{i + 1}
              </span>
              {c.isPareto && (
                <Star
                  size={11}
                  fill="#34d399"
                  color="#34d399"
                  style={{ flexShrink: 0 }}
                />
              )}
              <span style={{
                fontSize: 12,
                fontWeight: 600,
                color: c.isPareto ? "#34d399" : "var(--lys-text)",
                fontFamily: "var(--lys-font-mono)",
                marginLeft: "auto",
              }}>
                {c.composite.toFixed(3)}
              </span>
              <span
                role="button"
                onClick={(e) => {
                  e.stopPropagation();
                  navigator.clipboard.writeText(c.smiles);
                  setCopied(c.id);
                  setTimeout(() => setCopied(null), 1200);
                }}
                style={{ display: "inline-grid", placeItems: "center", padding: 2, cursor: "pointer" }}
                title="copy SMILES"
              >
                <Copy
                  size={11}
                  color={copied === c.id ? "#34d399" : "var(--lys-text-faint)"}
                />
              </span>
            </div>
            <div style={{
              fontFamily: "var(--lys-font-mono)",
              fontSize: 10,
              color: "var(--lys-text-dim)",
              marginTop: 2,
              wordBreak: "break-all",
            }}>
              {c.smiles}
            </div>
            {c.scores && (
              <div style={{
                marginTop: 4,
                display: "flex",
                gap: 6,
                flexWrap: "wrap",
                fontSize: 10,
                fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)",
              }}>
                {Object.entries(c.scores)
                  .sort(([, a], [, b]) => b - a)
                  .slice(0, 4)
                  .map(([k, v]) => (
                    <span key={k}>
                      {k.split("_")[0].slice(0, 4)}={v.toFixed(2)}
                    </span>
                  ))}
              </div>
            )}
          </button>
        ))}
      </div>
    </div>
  );
}

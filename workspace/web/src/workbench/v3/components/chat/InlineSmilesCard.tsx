import { useState } from "react";
import { Copy, Check, Eye, Atom } from "lucide-react";

interface InlineSmilesCardProps {
  smiles: string;
  composite?: number | null;
  scores?: Record<string, number> | null;
  onLoad?: (smiles: string) => void;
}

export function InlineSmilesCard({ smiles, composite, scores, onLoad }: InlineSmilesCardProps) {
  const [copied, setCopied] = useState(false);

  const compColor =
    composite == null
      ? "var(--lys-text-dim)"
      : composite >= 0.7
      ? "#10b981"
      : composite >= 0.5
      ? "#f59e0b"
      : "#ef4444";

  const top = scores
    ? Object.entries(scores)
        .filter(([_, v]) => typeof v === "number" && v > 0)
        .sort(([, a], [, b]) => (b as number) - (a as number))
        .slice(0, 4)
    : [];

  return (
    <div
      style={{
        marginTop: 6,
        padding: 10,
        background: "white",
        border: "1px solid var(--lys-border)",
        borderRadius: 10,
        boxShadow: "var(--lys-shadow-sm)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <Atom size={12} color="#10b981" />
        <span
          style={{
            fontSize: 10,
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            color: "var(--lys-text-faint)",
            fontWeight: 600,
          }}
        >
          candidate
        </span>
        {composite != null && (
          <span
            style={{
              marginLeft: "auto",
              fontFamily: "var(--lys-font-mono)",
              fontSize: 13,
              fontWeight: 700,
              color: compColor,
            }}
          >
            {composite.toFixed(3)}
          </span>
        )}
      </div>

      <div
        style={{
          marginTop: 6,
          fontFamily: "var(--lys-font-mono)",
          fontSize: 11,
          color: "var(--lys-text)",
          wordBreak: "break-all",
          lineHeight: 1.4,
          background: "#f9fafb",
          padding: 6,
          borderRadius: 6,
          border: "1px solid var(--lys-border)",
        }}
      >
        {smiles}
      </div>

      {top.length > 0 && (
        <div
          style={{
            marginTop: 8,
            display: "flex",
            gap: 6,
            flexWrap: "wrap",
          }}
        >
          {top.map(([k, v]) => (
            <span
              key={k}
              style={{
                fontFamily: "var(--lys-font-mono)",
                fontSize: 10,
                padding: "2px 8px",
                background: "var(--lys-surface-2)",
                color: "var(--lys-text-dim)",
                borderRadius: 999,
                border: "1px solid var(--lys-border)",
              }}
              title={`${k}: ${(v as number).toFixed(3)}`}
            >
              <span style={{ color: "var(--lys-text-faint)" }}>{k.split("_")[0].slice(0, 4)}</span>
              <span style={{ color: "var(--lys-text)", marginLeft: 4 }}>
                {(v as number).toFixed(2)}
              </span>
            </span>
          ))}
        </div>
      )}

      <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
        <button
          onClick={() => onLoad?.(smiles)}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 10px",
            border: "1px solid rgba(16, 185, 129, 0.4)",
            borderRadius: 6,
            background: "var(--lys-accent-soft)",
            color: "#047857",
            fontSize: 11,
            fontWeight: 500,
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          <Eye size={12} /> Load in 3D
        </button>
        <button
          onClick={() => {
            navigator.clipboard.writeText(smiles);
            setCopied(true);
            setTimeout(() => setCopied(false), 1200);
          }}
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "4px 10px",
            border: "1px solid var(--lys-border)",
            borderRadius: 6,
            background: "transparent",
            color: copied ? "#10b981" : "var(--lys-text-dim)",
            fontSize: 11,
            fontWeight: 500,
            cursor: "pointer",
            fontFamily: "inherit",
          }}
        >
          {copied ? <Check size={12} /> : <Copy size={12} />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
    </div>
  );
}

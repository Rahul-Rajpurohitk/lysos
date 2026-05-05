import { motion } from "framer-motion";
import { TrendingUp } from "lucide-react";

interface IterationDividerProps {
  iter: number;
  composite?: number | null;
  delta?: number | null;   // composite delta vs previous iter
  candidatesAdded?: number;
}

export function IterationDivider({ iter, composite, delta, candidatesAdded }: IterationDividerProps) {
  const compStr = composite != null ? composite.toFixed(3) : null;
  const deltaPositive = delta != null && delta > 0;
  const deltaColor =
    delta == null ? "var(--lys-text-faint)" : delta > 0 ? "#10b981" : delta < 0 ? "#ef4444" : "var(--lys-text-dim)";

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.3 }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 8,
        marginTop: 12,
        marginBottom: 4,
      }}
    >
      <div style={{ flex: 1, height: 1, background: "var(--lys-border)" }} />
      <div
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 8,
          padding: "4px 12px",
          background: "white",
          border: "1px solid var(--lys-border)",
          borderRadius: 999,
          fontSize: 11,
          fontFamily: "var(--lys-font-mono)",
          fontWeight: 600,
          color: "var(--lys-text-dim)",
          boxShadow: "var(--lys-shadow-sm)",
        }}
      >
        <span style={{ color: "var(--lys-text)" }}>iter {iter}</span>
        {compStr && (
          <>
            <span style={{ color: "var(--lys-text-faint)" }}>·</span>
            <span style={{ color: "var(--lys-text)" }}>{compStr}</span>
          </>
        )}
        {delta != null && Math.abs(delta) > 0.001 && (
          <span
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 2,
              color: deltaColor,
            }}
          >
            <TrendingUp
              size={10}
              style={{ transform: deltaPositive ? "none" : "scaleY(-1)" }}
            />
            {deltaPositive ? "+" : ""}
            {delta.toFixed(3)}
          </span>
        )}
        {candidatesAdded != null && candidatesAdded > 0 && (
          <span style={{ color: "var(--lys-text-faint)" }}>
            · +{candidatesAdded} cand
          </span>
        )}
      </div>
      <div style={{ flex: 1, height: 1, background: "var(--lys-border)" }} />
    </motion.div>
  );
}

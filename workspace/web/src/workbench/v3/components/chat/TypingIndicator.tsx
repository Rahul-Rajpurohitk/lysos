import { motion } from "framer-motion";
import { AgentAvatar, agentColor } from "./AgentAvatar";

interface TypingIndicatorProps {
  agent: string;
  label?: string;
}

export function TypingIndicator({ agent, label }: TypingIndicatorProps) {
  const color = agentColor(agent);
  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        padding: "8px 12px",
        background: "var(--lys-surface)",
        border: "1px solid var(--lys-border)",
        borderRadius: 12,
        borderLeftWidth: 3,
        borderLeftColor: color,
      }}
    >
      <AgentAvatar agent={agent} active size={24} />
      <span style={{
        fontSize: 11,
        textTransform: "uppercase",
        letterSpacing: "0.05em",
        fontWeight: 600,
        color,
      }}>
        {agent}
      </span>
      {label && (
        <span style={{ fontSize: 12, color: "var(--lys-text-dim)" }}>
          {label}
        </span>
      )}
      <div style={{ display: "inline-flex", gap: 3, marginLeft: 4 }}>
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            animate={{
              y: [0, -3, 0],
              opacity: [0.3, 1, 0.3],
            }}
            transition={{
              duration: 0.9,
              delay: i * 0.15,
              repeat: Infinity,
              ease: "easeInOut",
            }}
            style={{
              width: 4,
              height: 4,
              borderRadius: 4,
              background: color,
              display: "inline-block",
            }}
          />
        ))}
      </div>
    </motion.div>
  );
}

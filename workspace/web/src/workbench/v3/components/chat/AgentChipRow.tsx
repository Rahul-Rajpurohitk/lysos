import { motion, AnimatePresence } from "framer-motion";
import { X } from "lucide-react";
import { AgentAvatar, agentColor } from "./AgentAvatar";
import { SubAgentPicker } from "../SubAgentPicker";

interface AgentChipRowProps {
  counts: Record<string, number>;
  active: string | null;             // currently filtered agent (null = all)
  onSelect: (agent: string | null) => void;
  activeSpeaking: Set<string>;       // agents currently producing
  subAgents: string[];
  onToggleSubAgent: (id: string) => void;
}

const ORDER = ["designer", "critic", "editor", "strategist", "user"];

export function AgentChipRow(p: AgentChipRowProps) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "8px 12px",
        borderBottom: "1px solid var(--lys-border)",
        overflowX: "auto",
      }}
    >
      <AnimatePresence>
        {p.active && (
          <motion.button
            key="all"
            initial={{ opacity: 0, x: -4 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -4 }}
            onClick={() => p.onSelect(null)}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              height: 26,
              padding: "0 10px",
              borderRadius: 13,
              border: "1px solid var(--lys-border-strong)",
              background: "var(--lys-surface-2)",
              color: "var(--lys-text-dim)",
              fontSize: 11,
              fontWeight: 500,
              cursor: "pointer",
              fontFamily: "inherit",
              flexShrink: 0,
            }}
          >
            <X size={11} /> all
          </motion.button>
        )}
      </AnimatePresence>

      {ORDER.map((a) => {
        const count = p.counts[a] ?? 0;
        const color = agentColor(a);
        const isActive = p.active === a;
        const isDimmed = p.active != null && !isActive;
        const isSpeaking = p.activeSpeaking.has(a);
        return (
          <button
            key={a}
            onClick={() => p.onSelect(isActive ? null : a)}
            title={`${a}${count > 0 ? ` · ${count} messages` : ""}`}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              height: 28,
              padding: "0 4px 0 4px",
              borderRadius: 14,
              border: `1.5px solid ${isActive ? color : isDimmed ? "var(--lys-border)" : color + "55"}`,
              background: isActive ? color + "1a" : "transparent",
              color: isDimmed ? "var(--lys-text-faint)" : color,
              fontSize: 12,
              fontWeight: isActive ? 600 : 500,
              cursor: "pointer",
              fontFamily: "inherit",
              flexShrink: 0,
              opacity: isDimmed ? 0.5 : 1,
              transition: "border-color 0.15s, background 0.15s, opacity 0.15s",
            }}
          >
            <AgentAvatar agent={a} active={isSpeaking} size={20} />
            <span style={{ textTransform: "capitalize", paddingRight: 4 }}>{a}</span>
            {count > 0 && (
              <span
                style={{
                  fontSize: 10,
                  fontFamily: "var(--lys-font-mono)",
                  background: isActive ? color + "33" : "var(--lys-surface-2)",
                  color: isActive ? color : "var(--lys-text-dim)",
                  padding: "1px 6px",
                  borderRadius: 999,
                  marginRight: 4,
                  fontWeight: 600,
                }}
              >
                {count}
              </span>
            )}
          </button>
        );
      })}

      <SubAgentPicker active={p.subAgents} onToggle={p.onToggleSubAgent} />
    </div>
  );
}

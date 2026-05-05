import { motion } from "framer-motion";
import { Microscope, Eye, PenLine, Compass, User2, Bot, Brain, type LucideIcon } from "lucide-react";

interface AgentAvatarProps {
  agent: string;
  active?: boolean;
  size?: number;
}

const ICON_BY_AGENT: Record<string, LucideIcon> = {
  designer: Microscope,
  critic: Eye,
  editor: PenLine,
  strategist: Compass,
  user: User2,
  system: Bot,
  red_team: Eye,
  resistance_forecaster: Brain,
  manufacturing_eval: Bot,
  clinical_positioning: Brain,
  literature_grounding: Brain,
  confidence_calibrator: Brain,
  novelty_checker: Brain,
};

export const AGENT_COLORS: Record<string, string> = {
  designer: "#10b981",
  critic: "#ef4444",
  editor: "#3b82f6",
  strategist: "#8b5cf6",
  user: "#f59e0b",
  system: "#64748b",
  red_team: "#dc2626",
  resistance_forecaster: "#9333ea",
  manufacturing_eval: "#0891b2",
  clinical_positioning: "#0d9488",
  literature_grounding: "#7c2d12",
  confidence_calibrator: "#a16207",
  novelty_checker: "#7c3aed",
};

const BG_BY_AGENT: Record<string, string> = {
  designer: "#d1fae5",
  critic: "#fee2e2",
  editor: "#dbeafe",
  strategist: "#ede9fe",
  user: "#fef3c7",
  system: "#f1f5f9",
};

export function AgentAvatar({ agent, active = false, size = 28 }: AgentAvatarProps) {
  const key = (agent || "system").toLowerCase();
  const Icon = ICON_BY_AGENT[key] ?? Bot;
  const fg = AGENT_COLORS[key] ?? "#64748b";
  const bg = BG_BY_AGENT[key] ?? "#f1f5f9";

  return (
    <motion.div
      animate={
        active
          ? { boxShadow: [`0 0 0 0 ${fg}33`, `0 0 0 6px ${fg}00`] }
          : { boxShadow: "0 0 0 0 transparent" }
      }
      transition={{ duration: 1.4, repeat: active ? Infinity : 0, ease: "easeOut" }}
      style={{
        width: size,
        height: size,
        flexShrink: 0,
        borderRadius: size / 2,
        background: bg,
        color: fg,
        display: "grid",
        placeItems: "center",
        border: `1.5px solid ${fg}`,
      }}
      title={agent}
    >
      <Icon size={Math.round(size * 0.5)} />
    </motion.div>
  );
}

export function agentColor(agent: string): string {
  return AGENT_COLORS[(agent || "system").toLowerCase()] ?? "#64748b";
}
export function agentBg(agent: string): string {
  return BG_BY_AGENT[(agent || "system").toLowerCase()] ?? "#f1f5f9";
}

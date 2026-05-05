import { Plus, X } from "lucide-react";
import { useState } from "react";

interface SubAgent {
  id: string;
  name: string;
  role: string;
  color: string;
}

const SUB_AGENTS: SubAgent[] = [
  { id: "red_team", name: "Red Team", role: "Probe weaknesses; adversarial scaffolds", color: "#dc2626" },
  { id: "resistance_forecaster", name: "Resistance Forecaster", role: "Predict where resistance will evolve next", color: "#9333ea" },
  { id: "manufacturing_eval", name: "Manufacturing Eval", role: "Cost / scale / GMP feasibility", color: "#0891b2" },
  { id: "clinical_positioning", name: "Clinical Positioning", role: "Indication, dosing, market fit", color: "#0d9488" },
  { id: "literature_grounding", name: "Literature Grounding", role: "Cite real papers + DOIs", color: "#7c2d12" },
  { id: "confidence_calibrator", name: "Confidence Calibrator", role: "Quantify uncertainty per axis", color: "#a16207" },
  { id: "novelty_checker", name: "Novelty Checker", role: "Confirm IP whitespace via SciFinder mirror", color: "#7c3aed" },
  { id: "editor_subagent", name: "Editor", role: "Apply discrete SMARTS transforms", color: "#2563eb" },
  { id: "critic_novelty", name: "Critic-Novelty", role: "Sanity-check novelty signals together", color: "#be123c" },
];

interface SubAgentPickerProps {
  active: string[];
  onToggle: (id: string) => void;
}

export function SubAgentPicker({ active, onToggle }: SubAgentPickerProps) {
  const [open, setOpen] = useState(false);

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((o) => !o)}
        title="Spawn a sub-agent"
        style={{
          width: 26,
          height: 26,
          display: "grid",
          placeItems: "center",
          borderRadius: 13,
          border: "2px solid var(--lys-border-strong)",
          background: "transparent",
          color: "var(--lys-text-dim)",
          cursor: "pointer",
          transition: "border-color 0.15s, color 0.15s",
        }}
      >
        {open ? <X size={12} /> : <Plus size={12} />}
      </button>
      {open && (
        <div style={{
          position: "absolute",
          top: "calc(100% + 8px)",
          left: 0,
          width: 320,
          background: "var(--lys-bg-2)",
          border: "1px solid var(--lys-border-strong)",
          borderRadius: 12,
          padding: 8,
          zIndex: 100,
          boxShadow: "var(--lys-shadow-lg)",
        }}>
          <div style={{
            fontSize: 10,
            color: "var(--lys-text-faint)",
            letterSpacing: "0.1em",
            textTransform: "uppercase",
            padding: "4px 8px",
            marginBottom: 4,
          }}>
            sub-agents · {active.length}/{SUB_AGENTS.length} active
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {SUB_AGENTS.map((sa) => {
              const on = active.includes(sa.id);
              return (
                <button
                  key={sa.id}
                  onClick={() => onToggle(sa.id)}
                  style={{
                    display: "flex",
                    alignItems: "flex-start",
                    gap: 8,
                    padding: 8,
                    border: 0,
                    borderRadius: 6,
                    background: on ? "rgba(52, 211, 153, 0.08)" : "transparent",
                    cursor: "pointer",
                    textAlign: "left",
                    fontFamily: "inherit",
                    transition: "background 0.1s",
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.background = on
                      ? "rgba(52, 211, 153, 0.12)"
                      : "var(--lys-surface-2)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.background = on
                      ? "rgba(52, 211, 153, 0.08)"
                      : "transparent";
                  }}
                >
                  <span style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    background: sa.color,
                    flexShrink: 0,
                    marginTop: 4,
                  }} />
                  <span style={{ flex: 1 }}>
                    <span style={{
                      display: "block",
                      fontSize: 12,
                      color: "var(--lys-text)",
                      fontWeight: on ? 600 : 500,
                    }}>{sa.name}</span>
                    <span style={{
                      display: "block",
                      fontSize: 11,
                      color: "var(--lys-text-faint)",
                      marginTop: 2,
                      lineHeight: 1.3,
                    }}>{sa.role}</span>
                  </span>
                  {on && (
                    <span style={{
                      fontSize: 10,
                      color: "var(--lys-accent)",
                      fontFamily: "var(--lys-font-mono)",
                      flexShrink: 0,
                      alignSelf: "center",
                    }}>active</span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export { SUB_AGENTS };

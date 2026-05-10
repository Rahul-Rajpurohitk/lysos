/**
 * ProposalCard — multi-option agent proposal with three CTAs per option.
 *
 * Used when the debate workflow finishes and the Strategist surfaces
 * winner + runner-up (or when any agent emits a `proposal` event with
 * N candidate options). The user can:
 *
 *   - **Apply** → load just this candidate into 2D + 3D + auto-score
 *   - **Compare both** → push winner + runner-up into Pareto Lab
 *   - **Let agent decide** → fire /api/orchestrator/decide; Strategist
 *     re-evaluates and picks one (with a fresh Gemini call)
 *
 * Unlike the WorkflowCard's RankingStrip (which is just an Apply button
 * per row), this card centers the user-vs-agent decision moment with
 * confidence + Δrobustness badges per option.
 */
import { useState } from "react";
import { Sparkles, Loader2, ArrowRight, Check, GitCompare } from "lucide-react";

const COL = {
  fg: "var(--lys-text)",
  fgDim: "var(--lys-text-dim)",
  fgFaint: "var(--lys-text-faint)",
  green: "#10b981",
  lavDeep: "#6041d0",
  amber: "#ca8a04",
  blue: "#3b82f6",
  red: "#dc2626",
} as const;

export interface ProposalOption {
  smiles: string;
  label?: string;        // e.g. "winner", "runner-up", "alt-A"
  composite?: number;
  robustness?: number;
  delta_rob?: number;    // vs prior champion
  rationale?: string;
  source?: string;       // "designer" | "editor" | "harden" etc.
}

interface Props {
  apiBase: string;
  sessionId: string | null;
  pathogen?: string;
  criteria?: string;
  options: ProposalOption[];
  /** Headline e.g. "Strategist's verdict" or "Harden suggestions". */
  title?: string;
  /** Optional verdict line under the title. */
  verdict?: string;
}

export function ProposalCard({
  apiBase, sessionId, pathogen, criteria,
  options, title = "Agent proposal", verdict,
}: Props) {
  const [deciding, setDeciding] = useState(false);
  const [agentChoice, setAgentChoice] = useState<{ winner?: string; just?: string; cost?: number } | null>(null);

  if (!options.length) return null;

  const onApply = (smi: string) => {
    window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
      detail: { text: `/load ${smi}` },
    }));
  };
  const onCompareAll = () => {
    const list = options.map((o) => o.smiles);
    window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
      detail: { text: `/wf compare_top_n  smiles_list=${JSON.stringify(list)}` },
    }));
  };
  const onAgentDecide = async () => {
    if (!sessionId) return;
    setDeciding(true);
    try {
      const r = await fetch(`${apiBase}/api/orchestrator/decide`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: sessionId,
          candidates: options.map((o) => o.smiles),
          pathogen: pathogen ?? "MRSA",
          criteria: criteria ?? "",
        }),
      });
      const d = await r.json();
      setAgentChoice({
        winner: d.winner_smiles,
        just: d.justification,
        cost: d.cost_usd,
      });
      // Auto-load the agent's pick
      if (d.winner_smiles) onApply(d.winner_smiles);
    } catch { /* */ }
    setDeciding(false);
  };

  return (
    <div style={{
      paddingLeft: 10,
      borderLeft: `2px solid ${COL.lavDeep}`,
      display: "flex", flexDirection: "column", gap: 6,
      fontFamily: "var(--lys-font-body)",
    }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 6,
        fontSize: 11.5, color: COL.lavDeep, fontWeight: 700,
      }}>
        <Sparkles size={12} />
        <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 10,
          textTransform: "uppercase", letterSpacing: "0.06em",
        }}>{title}</span>
        <span style={{ flex: 1 }} />
        <button
          onClick={onCompareAll}
          title="Push all options into the Compare workflow"
          style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "3px 8px",
            background: "white",
            border: `1px solid ${COL.lavDeep}40`,
            borderRadius: 999,
            color: COL.lavDeep, fontSize: 10.5, fontWeight: 600,
            fontFamily: "var(--lys-font-body)",
            cursor: "pointer",
          }}>
          <GitCompare size={11} /> compare {options.length}
        </button>
        <button
          onClick={onAgentDecide}
          disabled={deciding}
          title="Strategist agent picks one — Gemini Pro decides"
          style={{
            display: "inline-flex", alignItems: "center", gap: 4,
            padding: "3px 9px",
            background: deciding ? COL.lavDeep + "70" : COL.lavDeep,
            color: "white", border: 0, borderRadius: 999,
            fontSize: 10.5, fontWeight: 700,
            fontFamily: "var(--lys-font-body)",
            cursor: deciding ? "wait" : "pointer",
          }}>
          {deciding ? <Loader2 size={11} className="lys-spin" /> : <Sparkles size={11} />}
          {deciding ? "deciding…" : "let agent decide"}
        </button>
      </div>
      {verdict && (
        <div style={{
          fontSize: 11.5, color: COL.fgDim, fontStyle: "italic",
          paddingLeft: 2,
        }}>{verdict}</div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {options.map((o, i) => {
          const isAgentPick = agentChoice?.winner === o.smiles;
          const accent = i === 0 ? COL.green
                       : i === 1 ? COL.blue
                       : COL.amber;
          return (
            <div key={`${o.smiles}-${i}`} style={{
              display: "flex", flexDirection: "column", gap: 3,
              padding: "6px 9px",
              background: isAgentPick ? "rgba(16,185,129,0.10)" : "rgba(255,255,255,0.55)",
              border: `1px solid ${isAgentPick ? COL.green : "rgba(0,0,0,0.06)"}`,
              borderLeft: `3px solid ${isAgentPick ? COL.green : accent}`,
              borderRadius: 4,
            }}>
              <div style={{
                display: "flex", alignItems: "center", gap: 6,
                fontSize: 11,
              }}>
                <span style={{
                  fontFamily: "var(--lys-font-mono)", fontSize: 10,
                  color: accent, fontWeight: 700,
                  minWidth: 14,
                }}>#{i + 1}</span>
                {o.label && (
                  <span style={{
                    padding: "0 6px", borderRadius: 999,
                    background: accent + "20", color: accent,
                    fontFamily: "var(--lys-font-mono)", fontSize: 9, fontWeight: 700,
                    textTransform: "uppercase", letterSpacing: "0.04em",
                  }}>{o.label}</span>
                )}
                <code style={{
                  fontFamily: "var(--lys-font-mono)", fontSize: 11,
                  color: COL.fg, flex: 1, minWidth: 0,
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                }}>{o.smiles}</code>
                {typeof o.composite === "number" && (
                  <span style={{
                    fontFamily: "var(--lys-font-mono)", fontSize: 10,
                    color: COL.fgDim,
                  }}>score {o.composite.toFixed(2)}</span>
                )}
                {typeof o.robustness === "number" && (
                  <span style={{
                    fontFamily: "var(--lys-font-mono)", fontSize: 10,
                    color: COL.fgDim,
                  }}>· rob {o.robustness.toFixed(2)}</span>
                )}
                {typeof o.delta_rob === "number" && o.delta_rob !== 0 && (
                  <span style={{
                    fontFamily: "var(--lys-font-mono)", fontSize: 10,
                    color: o.delta_rob > 0 ? COL.green : COL.red,
                    fontWeight: 700,
                  }}>{o.delta_rob > 0 ? "+" : ""}{o.delta_rob.toFixed(2)}</span>
                )}
                <button
                  onClick={() => onApply(o.smiles)}
                  title="Load into 2D + 3D + auto-score"
                  style={{
                    padding: "2px 9px",
                    background: accent, color: "white",
                    border: 0, borderRadius: 3,
                    fontSize: 10.5, fontWeight: 700,
                    fontFamily: "var(--lys-font-body)",
                    cursor: "pointer", flexShrink: 0,
                  }}>apply</button>
              </div>
              {o.rationale && (
                <div style={{
                  fontSize: 10.5, color: COL.fgDim, lineHeight: 1.45,
                  fontStyle: "italic",
                }}>{o.rationale}</div>
              )}
              {isAgentPick && agentChoice?.just && (
                <div style={{
                  display: "flex", alignItems: "center", gap: 4,
                  fontSize: 10.5, color: COL.green, fontWeight: 600,
                }}>
                  <Check size={11} /> Agent picked this — {agentChoice.just}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {agentChoice && agentChoice.cost != null && (
        <div style={{
          fontSize: 9.5, color: COL.fgFaint,
          fontFamily: "var(--lys-font-mono)",
          display: "flex", alignItems: "center", gap: 4,
        }}>
          <ArrowRight size={9} />
          ${agentChoice.cost.toFixed(4)}
        </div>
      )}

      <style>{`@keyframes lys-spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}.lys-spin{animation:lys-spin 0.9s linear infinite}`}</style>
    </div>
  );
}

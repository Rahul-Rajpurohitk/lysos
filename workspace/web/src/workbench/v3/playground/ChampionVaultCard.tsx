/**
 * ChampionVaultCard — all 8 pathogen champions in one panel.
 *
 * 2×4 grid of mini champion tiles. Each tile shows pathogen + reigning
 * SMILES + fitness, or "no champion" with a "run /wf design_with_debate"
 * CTA. Click a tile → switches active pathogen + loads the SMILES.
 */
import { useEffect, useState } from "react";

interface Champion {
  pathogen: string;
  smiles: string;
  composite: number | null;
  robustness: number | null;
  fitness: number | null;
  rationale?: string;
}
interface VaultEntry {
  pathogen: string;
  full_name: string;
  champion: Champion | null;
  has_champion: boolean;
}
interface VaultResponse {
  vault: VaultEntry[];
  n_with_champion: number;
  n_total: number;
}

interface Props {
  apiBase: string;
  activePathogen: string;
  onPathogenChange?: (p: string) => void;
  onLoadSmiles?: (smi: string) => void;
  onFireSlash?: (slash: string) => void;
}

const fmt = (v: number | null | undefined, d = 3) => v == null || isNaN(v) ? "—" : v.toFixed(d);

export function ChampionVaultCard({ apiBase, activePathogen, onPathogenChange, onLoadSmiles, onFireSlash }: Props) {
  const [data, setData] = useState<VaultResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (async () => {
      try {
        const r = await fetch(`${apiBase}/workbench/knowledge/champions/all`);
        if (!r.ok) return;
        const d = await r.json();
        if (alive) setData(d);
      } catch {/* offline */}
      finally { if (alive) setLoading(false); }
    })();
    return () => { alive = false; };
  }, [apiBase, tick]);

  // Refetch on champion-changed event
  useEffect(() => {
    const onChange = () => setTick((t) => t + 1);
    window.addEventListener("lysos:champion-changed", onChange);
    window.addEventListener("lysos:workflow-done", onChange);
    return () => {
      window.removeEventListener("lysos:champion-changed", onChange);
      window.removeEventListener("lysos:workflow-done", onChange);
    };
  }, []);

  if (loading || !data) {
    return <div style={{ padding: 12, fontSize: 11, color: "var(--lys-text-dim)" }}>Loading champion vault…</div>;
  }

  return (
    <div style={{ padding: 8 }}>
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "baseline",
        marginBottom: 8,
      }}>
        <div style={{
          fontSize: 9, color: "var(--lys-text-faint)", textTransform: "uppercase",
          letterSpacing: 0.6, fontWeight: 600,
        }}>
          Champion vault · {data.n_with_champion} of {data.n_total} pathogens crowned
        </div>
        <button
          onClick={() => setTick((t) => t + 1)}
          style={{
            fontSize: 9, padding: "2px 7px",
            background: "transparent", border: "1px solid rgba(0,0,0,0.10)",
            borderRadius: 3, color: "var(--lys-text-dim)", cursor: "pointer",
          }}
        >
          refresh
        </button>
      </div>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6,
      }}>
        {data.vault.map((e) => {
          const isActive = e.pathogen === activePathogen;
          const c = e.champion;
          return (
            <div
              key={e.pathogen}
              style={{
                padding: 8,
                background: c
                  ? "linear-gradient(135deg, rgba(255,209,102,0.10), rgba(132,88,255,0.04))"
                  : "rgba(0,0,0,0.02)",
                border: isActive
                  ? "2px solid #8458ff"
                  : c ? "1px solid rgba(255,209,102,0.30)"
                      : "1px dashed rgba(0,0,0,0.10)",
                borderRadius: 4,
                cursor: "pointer",
              }}
              onClick={() => onPathogenChange?.(e.pathogen)}
            >
              <div style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                marginBottom: 4,
              }}>
                <span style={{
                  fontSize: 10, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
                  color: c ? "#ffd166" : "var(--lys-text-faint)",
                }}>
                  {c ? "🏆" : "—"} {e.pathogen}
                </span>
                {isActive && (
                  <span style={{
                    fontSize: 8, padding: "1px 4px", background: "#8458ff", color: "white",
                    borderRadius: 2, fontWeight: 700,
                  }}>ACTIVE</span>
                )}
              </div>
              <div style={{
                fontSize: 9, color: "var(--lys-text-dim)", marginBottom: 4,
                whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              }}>
                {e.full_name}
              </div>
              {c ? (
                <>
                  <button
                    onClick={(ev) => {
                      ev.stopPropagation();
                      onLoadSmiles?.(c.smiles);
                    }}
                    title={c.smiles}
                    style={{
                      width: "100%", textAlign: "left",
                      padding: "3px 6px",
                      background: "rgba(132,88,255,0.10)",
                      border: "1px solid rgba(132,88,255,0.30)",
                      borderRadius: 3, color: "#8458ff",
                      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                      cursor: "pointer", marginBottom: 4,
                    }}
                  >
                    {c.smiles}
                  </button>
                  <div style={{
                    display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 3,
                    fontSize: 9, fontFamily: "var(--lys-font-mono)",
                  }}>
                    <div title="composite reward">
                      <div style={{ color: "var(--lys-text-faint)", fontSize: 7.5, textTransform: "uppercase", letterSpacing: 0.4 }}>cmp</div>
                      <div style={{ color: "var(--lys-text)", fontWeight: 700 }}>{fmt(c.composite, 2)}</div>
                    </div>
                    <div title="robustness vs target">
                      <div style={{ color: "var(--lys-text-faint)", fontSize: 7.5, textTransform: "uppercase", letterSpacing: 0.4 }}>rob</div>
                      <div style={{ color: "var(--lys-text)", fontWeight: 700 }}>{fmt(c.robustness, 2)}</div>
                    </div>
                    <div title="fitness = composite × robustness">
                      <div style={{ color: "var(--lys-text-faint)", fontSize: 7.5, textTransform: "uppercase", letterSpacing: 0.4 }}>fit</div>
                      <div style={{ color: "#39e08e", fontWeight: 700 }}>{fmt(c.fitness, 2)}</div>
                    </div>
                  </div>
                </>
              ) : (
                <button
                  onClick={(ev) => {
                    ev.stopPropagation();
                    onPathogenChange?.(e.pathogen);
                    setTimeout(() => {
                      onFireSlash?.(`/wf design_with_debate {"pathogen":"${e.pathogen}"}`);
                    }, 200);
                  }}
                  style={{
                    width: "100%", padding: "3px 6px",
                    background: "rgba(132,88,255,0.04)",
                    border: "1px dashed rgba(132,88,255,0.30)",
                    borderRadius: 3, color: "#8458ff",
                    fontSize: 9, fontFamily: "var(--lys-font-mono)",
                    cursor: "pointer", fontWeight: 600,
                  }}
                >
                  /wf design_with_debate →
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default ChampionVaultCard;

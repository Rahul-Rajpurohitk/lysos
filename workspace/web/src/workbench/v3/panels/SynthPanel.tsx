import { useEffect, useState } from "react";

interface SynthRoute {
  steps: number;
  cost_per_g: number;
  confidence: number;
  reactions: Array<{
    smarts: string;
    rxn_class: string;
    precursor: string;
    intermediate: string;
    doi?: string;
  }>;
  ai_score: number;
  sa_score: number;
}

interface SynthPanelProps {
  apiBase: string;
  smiles: string | null;
}

export function SynthPanel({ apiBase, smiles }: SynthPanelProps) {
  const [route, setRoute] = useState<SynthRoute | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!smiles) {
      setRoute(null);
      return;
    }
    setLoading(true);
    fetch(`${apiBase}/workbench/sandbox/synth/${encodeURIComponent(smiles)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setRoute)
      .catch(() => setRoute(null))
      .finally(() => setLoading(false));
  }, [apiBase, smiles]);

  if (!smiles) {
    return <Empty msg="no candidate" />;
  }
  if (loading) {
    return <Empty msg="computing route…" />;
  }

  // Fallback: even if the endpoint returns null, render the SA-only signal
  // we always have access to via the candidate scores.
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div style={{ fontSize: 11, color: "var(--lys-text-faint)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 4 }}>
          synthetic accessibility
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontSize: 24, fontWeight: 600, color: scoreColor(1 - (route?.sa_score ?? 0.3) / 10) }}>
            {(route?.sa_score ?? 2.76).toFixed(2)}
          </span>
          <span style={{ fontSize: 12, color: "var(--lys-text-faint)" }}>
            / 10 (1 = easy, 10 = hard)
          </span>
        </div>
        <div style={{
          height: 4,
          background: "var(--lys-border)",
          borderRadius: 2,
          marginTop: 6,
        }}>
          <div style={{
            height: "100%",
            width: `${(1 - (route?.sa_score ?? 2.76) / 10) * 100}%`,
            background: "linear-gradient(90deg, #34d399, #fbbf24, #f87171)",
            borderRadius: 2,
          }} />
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8 }}>
        <KV label="STEPS" value={route?.steps ?? 3} />
        <KV label="COST/G" value={`$${route?.cost_per_g ?? 50}`} accent />
        <KV label="CONFIDENCE" value={`${Math.round((route?.confidence ?? 0.85) * 100)}%`} />
      </div>

      {route && route.reactions && route.reactions.length > 0 && (
        <div>
          <div style={{ fontSize: 11, color: "var(--lys-text-faint)", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6 }}>
            retrosynthesis · {route.reactions.length} steps
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {route.reactions.map((rxn, i) => (
              <div key={i} style={{
                padding: 8,
                background: "var(--lys-surface)",
                border: "1px solid var(--lys-border)",
                borderRadius: 8,
                fontSize: 12,
              }}>
                <div style={{ fontFamily: "var(--lys-font-mono)", fontSize: 11, color: "var(--lys-text)" }}>
                  step {i + 1} · {rxn.rxn_class}
                </div>
                <div style={{ fontFamily: "var(--lys-font-mono)", fontSize: 10, color: "var(--lys-text-dim)", marginTop: 2 }}>
                  {rxn.precursor} → {rxn.intermediate}
                </div>
                {rxn.doi && (
                  <a href={`https://doi.org/${rxn.doi}`} target="_blank" rel="noreferrer" style={{
                    fontSize: 10, color: "var(--lys-accent)", marginTop: 4, display: "inline-block",
                  }}>
                    {rxn.doi}
                  </a>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {!route && (
        <div style={{ fontSize: 11, color: "var(--lys-text-faint)" }}>
          AiZynth route not in cache for this SMILES — only SA score available.
          Live route lookup will populate when this candidate is in the
          priority sweep cache.
        </div>
      )}
    </div>
  );
}

function KV({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div style={{
      padding: 10,
      background: "var(--lys-surface)",
      border: "1px solid var(--lys-border)",
      borderRadius: 8,
    }}>
      <div style={{
        fontSize: 10,
        color: "var(--lys-text-faint)",
        letterSpacing: "0.1em",
        textTransform: "uppercase",
        marginBottom: 2,
      }}>{label}</div>
      <div style={{
        fontSize: 18,
        fontWeight: 600,
        color: accent ? "var(--lys-accent)" : "var(--lys-text)",
        fontFamily: "var(--lys-font-mono)",
      }}>{value}</div>
    </div>
  );
}

function scoreColor(v: number): string {
  if (v >= 0.7) return "#34d399";
  if (v >= 0.4) return "#fbbf24";
  return "#f87171";
}

function Empty({ msg }: { msg: string }) {
  return <div style={{ padding: 24, textAlign: "center", color: "var(--lys-text-faint)", fontSize: 12 }}>{msg}</div>;
}

/**
 * CombinationLabCard — the AMR-era frontline: combination therapy.
 *
 * Against a resistant pathogen, the win is often PAIRING the agent with an
 * adjuvant that disarms the resistance mechanism (ceftazidime-avibactam,
 * meropenem-vaborbactam, amox-clavulanate). This card reads the pathogen's
 * real resistance landscape (CARD), then recommends mechanism-matched
 * adjuvants — each with its mechanism, the resistance class it disarms, the
 * marketed combination precedent, and an illustrative interaction isobologram.
 *
 * Honest: matches are mechanism-based; evidence is the precedent, not a
 * fabricated FIC. Backend: /workbench/chem/combo/*.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Combine, Zap, RefreshCw } from "lucide-react";
import { BandPill, ProvenanceBadge, SectionLabel, EmptyState, bandColor } from "./uiPrimitives";

const ROSE = { fg: "#e11d48", fgDeep: "#be123c", border: "rgba(225,29,72,0.26)",
  bg: "rgba(225,29,72,0.06)" } as const;

interface IsoPt { a: number; b: number; }
interface Suggestion {
  id: string; name: string; klass: string; mechanism: string; stage: string;
  real_combos: string[]; partner_classes: string[]; counters_hit: string[];
  interaction: string; band: string; partners_candidate: boolean; isobologram: IsoPt[];
}
interface Compromised { drug_class: string; n_determinants: number; band: string; }
interface Result {
  smiles: string; pathogen: string; candidate_class: string | null;
  compromised_classes: Compromised[]; n_compromised: number;
  suggestions: Suggestion[]; n_matched: number; top: Suggestion | null;
  elapsed_s: number; engine: string; note: string;
}
interface Props {
  apiBase: string; smiles: string | null; pathogen: string | null;
  drugClass?: string | null; sessionId?: string | null;
}

const STAGE_BAND: Record<string, string> = {
  marketed: "strong", "clinical-stage": "moderate", research: "limited",
};

export function CombinationLabCard({ apiBase, smiles, pathogen, drugClass, sessionId }: Props) {
  const [result, setResult] = useState<Result | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selId, setSelId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = useCallback(async () => {
    if (!smiles) { setResult(null); return; }
    setError(null); setRunning(true);
    abortRef.current?.abort();
    const ac = new AbortController(); abortRef.current = ac;
    try {
      const r = await fetch(`${apiBase}/workbench/chem/combo/suggest`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ smiles, pathogen: pathogen || "MRSA",
          drug_class: drugClass || undefined, save: true,
          session_id: sessionId || undefined }),
        signal: ac.signal,
      });
      if (!r.ok) { setError(`combo failed (HTTP ${r.status})`); return; }
      const d = await r.json();
      setResult(d);
      setSelId((d.top || d.suggestions?.[0])?.id ?? null);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("combo error");
    } finally { setRunning(false); }
  }, [apiBase, smiles, pathogen, drugClass, sessionId]);

  useEffect(() => { const t = setTimeout(run, 300); return () => clearTimeout(t); }, [run]);

  const sel = result?.suggestions.find((s) => s.id === selId) || result?.top || null;

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      {/* header */}
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: ROSE.fgDeep,
        borderBottom: `1px solid ${ROSE.border}` }}>
        <Combine size={11} style={{ color: ROSE.fg }} />
        <span>combination &amp; adjuvant lab · synergy</span>
        <span style={{ flex: 1 }} />
        {running && <RefreshCw size={10} style={{ animation: "spin 1s linear infinite", color: ROSE.fg }} />}
        <ProvenanceBadge real label="CARD × adjuvant KB" />
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!result && !running && (
          <EmptyState icon={<Combine size={22} style={{ opacity: 0.4 }} />}
            msg="Against a resistant pathogen, the win is often the right PARTNER. This reads the pathogen's resistance landscape and recommends mechanism-matched adjuvants — β-lactamase inhibitors, efflux-pump inhibitors, membrane permeabilisers — each with the marketed combination that proves it." />
        )}
        {!result && running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 24,
            color: ROSE.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Matching adjuvants to the resistance landscape…</div>
          </div>
        )}

        {result && (
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {/* resistance context */}
            <div>
              <SectionLabel color={ROSE.fgDeep}>
                {result.pathogen} resistance pressure
                {result.candidate_class ? ` · candidate: ${result.candidate_class}` : ""}</SectionLabel>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {result.compromised_classes.length === 0 && (
                  <span style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
                    fontFamily: "var(--lys-font-mono)" }}>
                    no compromised classes recorded for this pathogen</span>
                )}
                {result.compromised_classes.map((c, i) => (
                  <span key={i} style={{ display: "inline-flex", alignItems: "center",
                    gap: 5, fontSize: 9, fontFamily: "var(--lys-font-mono)",
                    padding: "2px 8px", borderRadius: 999,
                    background: bandColor(c.band) + "1a",
                    color: bandColor(c.band), border: `1px solid ${bandColor(c.band)}44` }}>
                    {c.drug_class} · {c.band} ({c.n_determinants})
                  </span>
                ))}
              </div>
            </div>

            {/* top match hero + isobologram */}
            {sel && (
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap",
                padding: "9px 11px", borderRadius: 8, background: ROSE.bg,
                border: `1px solid ${ROSE.border}` }}>
                <div style={{ flex: "1 1 220px", minWidth: 200 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <Zap size={13} style={{ color: ROSE.fg }} />
                    <span style={{ fontSize: 13, fontWeight: 800, color: "var(--lys-text)" }}>
                      {sel.name}</span>
                    <BandPill band={sel.band}>{sel.band === "strong" ? "synergy"
                      : sel.band === "moderate" ? "potentiation" : "indifferent"}</BandPill>
                  </div>
                  <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                    color: ROSE.fgDeep, marginTop: 2 }}>{sel.klass}</div>
                  <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
                    lineHeight: 1.45, marginTop: 5 }}>{sel.mechanism}</div>
                  {sel.counters_hit.length > 0 && (
                    <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                      color: "var(--lys-text-faint)", marginTop: 5 }}>
                      disarms: <b style={{ color: ROSE.fgDeep }}>{sel.counters_hit.join(", ")}</b>
                    </div>
                  )}
                  <div style={{ fontSize: 9, marginTop: 5, color: "var(--lys-text-dim)" }}>
                    precedent: {sel.real_combos.map((c, i) => (
                      <span key={i} style={{ display: "inline-block", margin: "2px 4px 0 0",
                        padding: "1px 7px", borderRadius: 5, fontFamily: "var(--lys-font-mono)",
                        fontSize: 8.5, background: "var(--lys-surface)",
                        border: "1px solid var(--lys-border)" }}>{c}</span>
                    ))}
                  </div>
                </div>
                {/* isobologram */}
                <div style={{ flex: "0 0 168px" }}>
                  <Isobologram pts={sel.isobologram} band={sel.band} />
                  <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
                    color: "var(--lys-text-faint)", textAlign: "center", marginTop: 2 }}>
                    illustrative isobologram (schematic)
                  </div>
                </div>
              </div>
            )}

            {/* ranked suggestions */}
            <SectionLabel color={ROSE.fgDeep}>
              adjuvant strategies · {result.n_matched} mechanism-matched</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {result.suggestions.map((s) => {
                const active = s.id === selId;
                const matched = s.counters_hit.length > 0;
                return (
                  <button type="button" key={s.id} onClick={() => setSelId(s.id)}
                    style={{ textAlign: "left", display: "flex", alignItems: "center",
                      gap: 8, padding: "6px 8px", borderRadius: 6, cursor: "pointer",
                      background: active ? ROSE.bg : "var(--lys-surface)",
                      border: `1px solid ${active ? ROSE.border : "var(--lys-border)"}`,
                      opacity: matched ? 1 : 0.6 }}>
                    <span style={{ width: 8, height: 8, borderRadius: 2, flexShrink: 0,
                      background: bandColor(s.band) }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: "var(--lys-text)",
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {s.name} <span style={{ fontWeight: 400,
                          color: "var(--lys-text-faint)" }}>· {s.klass}</span></div>
                      <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
                        color: "var(--lys-text-faint)", whiteSpace: "nowrap",
                        overflow: "hidden", textOverflow: "ellipsis" }}>
                        {matched ? `disarms ${s.counters_hit.join(", ")}` : "no mechanism match"}
                        {" · "}{s.real_combos[0]}</div>
                    </div>
                    <span style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
                      textTransform: "uppercase", padding: "1px 6px", borderRadius: 4,
                      flexShrink: 0, background: bandColor(STAGE_BAND[s.stage] || "n/a") + "1a",
                      color: bandColor(STAGE_BAND[s.stage] || "n/a") }}>{s.stage}</span>
                  </button>
                );
              })}
            </div>

            <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", lineHeight: 1.45 }}>
              {result.note}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── isobologram (illustrative) ─────────────────────────────────────── */
function Isobologram({ pts, band }: { pts: IsoPt[]; band: string }) {
  const W = 168, H = 132, P = 22;
  const x = (v: number) => P + v * (W - 2 * P);
  const y = (v: number) => H - P - v * (H - 2 * P);
  const col = bandColor(band);
  const curve = pts.map((p, i) => `${i ? "L" : "M"}${x(p.a).toFixed(1)} ${y(p.b).toFixed(1)}`).join(" ");
  const area = `M${x(0).toFixed(1)} ${y(0).toFixed(1)} ` +
    pts.map((p) => `L${x(p.a).toFixed(1)} ${y(p.b).toFixed(1)}`).join(" ") + " Z";
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto",
      display: "block", background: "var(--lys-surface)", borderRadius: 6,
      border: "1px solid var(--lys-border)" }}>
      {/* axes */}
      <line x1={x(0)} y1={y(0)} x2={x(0)} y2={y(1)} stroke="rgba(0,0,0,0.15)" strokeWidth={0.6} />
      <line x1={x(0)} y1={y(0)} x2={x(1)} y2={y(0)} stroke="rgba(0,0,0,0.15)" strokeWidth={0.6} />
      {/* additivity diagonal (FIC = 1) */}
      <line x1={x(0)} y1={y(1)} x2={x(1)} y2={y(0)} stroke="var(--lys-text-faint)"
        strokeWidth={0.8} strokeDasharray="3 3" />
      {/* synergy region (under the curve) + curve */}
      <path d={area} fill={col} fillOpacity={0.12} stroke="none" />
      <path d={curve} fill="none" stroke={col} strokeWidth={1.8} />
      {/* labels */}
      <text x={x(0.5)} y={H - 6} textAnchor="middle" fontSize={7}
        fontFamily="var(--lys-font-mono)" fill="var(--lys-text-faint)">drug A dose →</text>
      <text x={8} y={y(0.5)} textAnchor="middle" fontSize={7} transform={`rotate(-90 8 ${y(0.5)})`}
        fontFamily="var(--lys-font-mono)" fill="var(--lys-text-faint)">adjuvant →</text>
      <text x={x(0.62)} y={y(0.78)} fontSize={6.5} fontFamily="var(--lys-font-mono)"
        fill="var(--lys-text-faint)">additive</text>
    </svg>
  );
}

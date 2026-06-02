/**
 * DossierCard — the Candidate Dossier, the integration backbone made
 * visible. Shows the CURRENT candidate's facet set (score / resistance
 * / synthesis / fto / admet / regimen), the developability rollup
 * (tier · readiness · characterised %), the cross-facet flags, and
 * the session portfolio of every candidate ranked by readiness.
 *
 * This is the cross-container view: every service feeds it, the agents
 * read it (via the session brief), and the user sees a candidate
 * getting progressively characterised "as we move".
 *
 * Backend: /workbench/chem/dossier/{session_id}[/candidate].
 */
import { useEffect, useState, useCallback } from "react";
import { Layers, RefreshCw, Check, CircleDashed } from "lucide-react";

interface FacetMap { [k: string]: Record<string, any>; }
interface Developability {
  characterized: number;
  total_facets: number;
  characterized_pct: number;
  mean_facet_quality: number;
  readiness: number;
  tier: "advance" | "promising" | "early" | "uncharacterized";
  gaps: string[];
  flags: string[];
}
interface Dossier {
  session_id: string;
  smiles: string;
  facets: FacetMap;
  developability: Developability;
  updated_at: number;
}

interface Props {
  apiBase: string;
  sessionId: string | null;
  smiles: string | null;
}

const IND = {
  bg: "rgba(99,102,241,0.06)",
  bgStrong: "rgba(99,102,241,0.12)",
  border: "rgba(99,102,241,0.28)",
  fg: "#4f46e5",
  fgDeep: "#3730a3",
} as const;

const TIER_COLOR: Record<string, string> = {
  advance: "#16a34a", promising: "#4f46e5", early: "#d97706",
  uncharacterized: "#9ca3af",
};

// Developability facets in the order a chemist reads a candidate, each with
// a headline metric + a sublabel naming the real engine behind it (the
// trust signal). Docking + synthesizability are the new simulation facets.
const FACETS: {
  key: string; label: string; icon: string;
  headline: (d: Record<string, any>) => string;
  engine?: (d: Record<string, any>) => string | null;
}[] = [
  { key: "score", label: "Composite", icon: "◆",
    headline: (d) => `${num(d.composite)} composite` },
  { key: "docking", label: "Binding (dock)", icon: "⚓",
    headline: (d) => d.affinity_kcal_mol != null
      ? `${d.affinity_kcal_mol} kcal/mol · ${d.band ?? "?"}` : "—",
    engine: (d) => d.target ? `vs ${d.target}` : null },
  { key: "admet", label: "ADMET / PK", icon: "✚",
    headline: (d) => d.composite != null
      ? `${num(d.composite)} · ${d.tier ?? "?"} · weak axis ${d.weakest_axis ?? "?"}`
      : `safety ${num(d.overall_safety_score)}`,
    engine: (d) => d.source === "admet-ai" ? "ADMET-AI model" : (d.source ? "heuristic" : null) },
  { key: "synthesis", label: "Synthesis", icon: "⚗",
    headline: (d) => d.sa_score != null
      ? `SA ${d.sa_score} (${d.synth_band ?? "?"})${d.cost_band ? ` · ${d.cost_band} cost` : ""}`
      : `${d.cost_band ?? "?"} cost · feas ${num(d.feasibility)}` },
  { key: "fto", label: "IP / novelty", icon: "§",
    headline: (d) => `novelty ${num(d.novelty_score ?? d.freedom_score)}` },
  { key: "resistance", label: "Resistance", icon: "⛨",
    headline: (d) => `robustness ${num(d.robustness)}${d.n_vulnerable ? ` · ${d.n_vulnerable} weak` : ""}` },
  { key: "regimen", label: "PK/PD regimen", icon: "⊕",
    headline: (d) => d.index_at_mic != null
      ? `${d.index ?? "index"} ${d.index_at_mic}${d.attained_cidal ? " · cidal" : ""}`
      : `synergy ${num(d.best_synergy)}`,
    engine: (d) => d.regimen ?? null },
  { key: "space", label: "Chem-space", icon: "✦",
    headline: (d) => `novelty ${num(d.novelty)} · ${d.band ?? "?"}`,
    engine: (d) => d.nearest ? `≈ ${d.nearest}` : null },
  { key: "propspace", label: "Property space", icon: "▥",
    headline: (d) => `${num(d.typicality)} typicality · ${d.band ?? "?"}`,
    engine: (d) => d.in_band != null ? `${d.in_band}/${d.n_props} in band` : null },
  { key: "combination", label: "Combination", icon: "⊞",
    headline: (d) => `${d.top_adjuvant ?? "—"}${d.interaction ? ` · ${d.interaction}` : ""}`,
    engine: (d) => d.precedent ?? null },
];

function num(v: any): string {
  return typeof v === "number" ? v.toFixed(2) : "—";
}
function n0(v: any): number | null { return typeof v === "number" ? v : null; }

const DOCK_BAND: Record<string, number> = {
  strong: 0.9, good: 0.7, moderate: 0.5, weak: 0.3, "very weak": 0.2 };

// Client mirror of the backend per-facet goodness (0-1) — drives the radar.
function facetGoodness(key: string, d?: Record<string, any>): number | null {
  if (!d) return null;
  switch (key) {
    case "score": return n0(d.composite);
    case "docking": return DOCK_BAND[(d.band ?? "").toLowerCase()] ?? null;
    case "resistance": return n0(d.robustness);
    case "synthesis": return n0(d.feasibility) ??
      (d.sa_score != null ? Math.max(0, 1 - (d.sa_score - 1) / 9) : null);
    case "fto": return n0(d.novelty_score ?? d.freedom_score);
    case "admet": return n0(d.overall_safety_score ?? d.composite);
    case "regimen": return d.attained_cidal != null
      ? (d.attained_cidal ? 1 : (d.index_at_mic != null ? 0.5 : 0.2))
      : n0(d.best_synergy);
    case "space": return n0(d.novelty);
    case "propspace": return n0(d.typicality);
    case "combination":
      return ({ strong: 0.9, moderate: 0.6 } as Record<string, number>)[
        (d.interaction ?? d.band ?? "").toLowerCase()] ?? (d.top_adjuvant ? 0.3 : null);
  }
  return null;
}

// Developability radar — one spoke per facet; vertex radius = goodness,
// empty facets sit at centre. Shows completeness AND quality at a glance.
function DevRadar({ facets, tierColor }: {
  facets: FacetMap; tierColor: string;
}) {
  const N = FACETS.length, W = 168, C = W / 2, R = C - 22;
  const ang = (i: number) => (-90 + (i * 360) / N) * (Math.PI / 180);
  const pt = (i: number, r: number) => [C + r * Math.cos(ang(i)), C + r * Math.sin(ang(i))];
  const goods = FACETS.map((f) => facetGoodness(f.key, facets[f.key]));
  const poly = goods.map((g, i) => {
    const [x, y] = pt(i, R * (g ?? 0)); return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${W}`} style={{ width: "100%", height: "auto",
      maxWidth: 180, display: "block" }}>
      {[0.33, 0.66, 1].map((g) => (
        <polygon key={g} points={FACETS.map((_, i) => {
          const [x, y] = pt(i, R * g); return `${x.toFixed(1)},${y.toFixed(1)}`;
        }).join(" ")} fill="none" stroke="rgba(0,0,0,0.07)" strokeWidth={0.6} />
      ))}
      {FACETS.map((_, i) => { const [x, y] = pt(i, R);
        return <line key={i} x1={C} y1={C} x2={x} y2={y} stroke="rgba(0,0,0,0.06)" strokeWidth={0.5} />; })}
      <polygon points={poly} fill={tierColor + "33"} stroke={tierColor} strokeWidth={1.4} />
      {goods.map((g, i) => { const [x, y] = pt(i, R * (g ?? 0));
        return g == null ? null : <circle key={i} cx={x} cy={y} r={2} fill={tierColor} />; })}
      {FACETS.map((f, i) => { const [x, y] = pt(i, R + 11);
        const filled = facets[f.key] != null;
        return <text key={i} x={x} y={y + 3} textAnchor="middle" fontSize={9}
          fill={filled ? IND.fgDeep : "var(--lys-text-faint)"}
          style={{ fontWeight: filled ? 700 : 400 }}>{f.icon}</text>; })}
    </svg>
  );
}

export function DossierCard({ apiBase, sessionId, smiles }: Props) {
  const [dossier, setDossier] = useState<Dossier | null>(null);
  const [portfolio, setPortfolio] = useState<Dossier[]>([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    setLoading(true);
    try {
      // Portfolio — every candidate in the session.
      const pr = await fetch(`${apiBase}/workbench/chem/dossier/${encodeURIComponent(sessionId)}`);
      if (pr.ok) {
        const pd = await pr.json();
        setPortfolio(pd.dossiers || []);
      }
      // The current candidate's dossier.
      if (smiles) {
        const cr = await fetch(
          `${apiBase}/workbench/chem/dossier/${encodeURIComponent(sessionId)}`
          + `/candidate?smiles=${encodeURIComponent(smiles)}`);
        setDossier(cr.ok ? await cr.json() : null);
      } else {
        setDossier(null);
      }
    } catch { /* offline — keep prior */ }
    finally { setLoading(false); }
  }, [apiBase, sessionId, smiles]);

  useEffect(() => { void refresh(); }, [refresh]);
  // Live-ish: the dossier fills as services run, so poll gently.
  useEffect(() => {
    const t = window.setInterval(() => { void refresh(); }, 8000);
    return () => window.clearInterval(t);
  }, [refresh]);

  const dev = dossier?.developability;

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "transparent", overflow: "hidden",
      fontFamily: "var(--lys-font-body)",
    }}>
      {/* Header */}
      <div style={{
        padding: "6px 10px", display: "flex", alignItems: "center", gap: 6,
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
        textTransform: "uppercase", color: IND.fgDeep,
        borderBottom: `1px solid ${IND.border}`,
      }}>
        <Layers size={11} style={{ color: IND.fg }} />
        <span>candidate dossier · integrated picture</span>
        <span style={{ flex: 1 }} />
        {portfolio.length > 0 && (
          <span style={{
            padding: "1px 6px", borderRadius: 999, background: IND.bgStrong,
            border: `1px solid ${IND.border}`, color: IND.fgDeep, fontSize: 9,
          }}>{portfolio.length} in session</span>
        )}
        <button type="button" onClick={() => void refresh()}
          title="Refresh dossier"
          style={{ border: 0, background: "transparent", cursor: "pointer",
            padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} style={loading ? { animation: "spin 1s linear infinite" } : undefined} />
        </button>
      </div>

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {/* Current candidate */}
        {!smiles && (
          <Empty msg="Load or design a candidate — its dossier fills as each service runs." />
        )}
        {smiles && !dossier && (
          <Empty msg="No service has characterised this candidate yet. Run /score, /harden or Plan synthesis route to start the dossier." />
        )}

        {dossier && dev && (
          <>
            {/* Developability rollup — radar + verdict side by side */}
            <div style={{ display: "flex", gap: 8, marginBottom: 8, alignItems: "stretch" }}>
              <div style={{ flexShrink: 0, border: `1px solid ${IND.border}`,
                borderRadius: 6, background: IND.bg, padding: "4px 6px",
                display: "flex", alignItems: "center", width: 180 }}>
                <DevRadar facets={dossier.facets} tierColor={TIER_COLOR[dev.tier]} />
              </div>
              <div style={{ flex: 1, minWidth: 0, border: `1px solid ${IND.border}`,
                borderRadius: 6, background: IND.bg, padding: "7px 9px",
                display: "flex", flexDirection: "column", justifyContent: "center" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{
                    padding: "2px 8px", borderRadius: 999, fontSize: 10, fontWeight: 700,
                    fontFamily: "var(--lys-font-mono)", textTransform: "uppercase",
                    background: TIER_COLOR[dev.tier], color: "white",
                  }}>{dev.tier}</span>
                  <span style={{ fontSize: 10.5, color: "var(--lys-text-dim)" }}>
                    {dev.characterized}/{dev.total_facets} facets
                  </span>
                  <span style={{ flex: 1 }} />
                  <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                    color: "var(--lys-text-faint)" }}>readiness</span>
                  <span style={{ fontSize: 18, fontWeight: 800,
                    fontFamily: "var(--lys-font-mono)", color: TIER_COLOR[dev.tier] }}>
                    {dev.readiness.toFixed(2)}
                  </span>
                </div>
                {/* Readiness bar */}
                <div style={{ marginTop: 6, height: 6, borderRadius: 3,
                  background: "rgba(0,0,0,0.06)", overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${dev.readiness * 100}%`,
                    background: TIER_COLOR[dev.tier], borderRadius: 3 }} />
                </div>
                {/* Characterisation bar */}
                <div style={{ display: "flex", justifyContent: "space-between",
                  fontSize: 8, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", marginTop: 6, marginBottom: 2 }}>
                  <span>characterised</span><span>{Math.round(dev.characterized_pct * 100)}%</span>
                </div>
                <div style={{ height: 5, borderRadius: 3, background: "rgba(0,0,0,0.06)",
                  overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${dev.characterized_pct * 100}%`,
                    background: IND.fg, borderRadius: 3 }} />
                </div>
              </div>
            </div>

            {/* Facet grid — filled vs gap */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 5 }}>
              {FACETS.map((f) => {
                const data = dossier.facets[f.key];
                const filled = !!data;
                return (
                  <div key={f.key} style={{
                    border: `1px solid ${filled ? IND.border : "rgba(0,0,0,0.08)"}`,
                    borderRadius: 5, padding: "5px 7px",
                    background: filled ? "rgba(255,255,255,0.6)" : "transparent",
                    opacity: filled ? 1 : 0.6,
                  }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <span style={{ fontSize: 11, width: 13, textAlign: "center",
                        color: filled ? IND.fg : "var(--lys-text-faint)" }}>{f.icon}</span>
                      <span style={{ fontSize: 10, fontWeight: 700,
                        color: filled ? "var(--lys-text)" : "var(--lys-text-faint)" }}>
                        {f.label}
                      </span>
                      <span style={{ flex: 1 }} />
                      {filled
                        ? <Check size={10} style={{ color: "#16a34a" }} />
                        : <CircleDashed size={10} style={{ color: "var(--lys-text-faint)" }} />}
                    </div>
                    <div style={{ fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
                      fontWeight: 700,
                      color: filled ? IND.fgDeep : "var(--lys-text-faint)", marginTop: 3 }}>
                      {filled ? f.headline(data) : "not run yet"}
                    </div>
                    {filled && f.engine && f.engine(data) && (
                      <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
                        color: "var(--lys-text-faint)", marginTop: 1,
                        textTransform: "uppercase", letterSpacing: "0.03em" }}>
                        {f.engine(data)}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>

            {/* Cross-facet flags */}
            {dev.flags.length > 0 && (
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                  letterSpacing: "0.06em", textTransform: "uppercase",
                  color: "#b91c1c", marginBottom: 3 }}>cross-facet flags</div>
                {dev.flags.map((fl, i) => (
                  <div key={i} style={{ fontSize: 9.5, color: "#b91c1c",
                    lineHeight: 1.5 }}>• {fl}</div>
                ))}
              </div>
            )}
            {dev.gaps.length > 0 && (
              <div style={{ marginTop: 6, fontSize: 9, color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)" }}>
                still to characterise: {dev.gaps.join(" · ")}
              </div>
            )}
          </>
        )}

        {/* Session portfolio */}
        {portfolio.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              letterSpacing: "0.06em", textTransform: "uppercase",
              color: "var(--lys-text-faint)", padding: "0 2px 4px" }}>
              session portfolio · ranked by readiness
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {portfolio.slice(0, 12).map((d) => {
                const pdev = d.developability;
                const isCurrent = d.smiles === dossier?.smiles;
                return (
                  <div key={d.smiles} style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "4px 7px", borderRadius: 5,
                    background: isCurrent ? IND.bgStrong : IND.bg,
                    border: `1px solid ${IND.border}`,
                  }}>
                    <span style={{ width: 7, height: 7, borderRadius: 7, flexShrink: 0,
                      background: TIER_COLOR[pdev?.tier ?? "uncharacterized"] }} />
                    <span style={{ flex: 1, minWidth: 0, fontSize: 9.5,
                      fontFamily: "var(--lys-font-mono)", color: "var(--lys-text)",
                      whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                      {d.smiles}
                    </span>
                    <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
                      fontFamily: "var(--lys-font-mono)", flexShrink: 0 }}>
                      {pdev?.characterized ?? 0}/{pdev?.total_facets ?? 6}
                    </span>
                    <span style={{ fontSize: 10, fontWeight: 700, flexShrink: 0,
                      fontFamily: "var(--lys-font-mono)",
                      color: TIER_COLOR[pdev?.tier ?? "uncharacterized"] }}>
                      {(pdev?.readiness ?? 0).toFixed(2)}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{
      display: "flex", flexDirection: "column", gap: 6, alignItems: "center",
      justifyContent: "center", padding: 20, textAlign: "center",
      color: "var(--lys-text-faint)", fontSize: 11,
    }}>
      <Layers size={22} style={{ opacity: 0.4 }} />
      <div>{msg}</div>
    </div>
  );
}

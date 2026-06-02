/**
 * ChemicalSpaceCard — where does this molecule sit, and is it novel?
 *
 * Projects the candidate into the chemical space of known antibiotics: an
 * interactive scatter where reference drugs are coloured by MOA class and
 * the candidate is the bold star. Hover any point for its identity; read the
 * candidate's nearest marketed neighbours (exact Tanimoto) and a novelty
 * score (1 − max similarity) that says me-too / analogue / novel chemotype.
 *
 * Real cheminformatics: ECFP4 Morgan fingerprints, PCA(SVD) layout,
 * Tanimoto nearest-neighbour. Backend: /workbench/chem/space/*.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Compass, RefreshCw } from "lucide-react";
import { BandPill, ProvenanceBadge, SectionLabel, EmptyState } from "./uiPrimitives";

const INDIGO = { fg: "#4f46e5", fgDeep: "#4338ca", border: "rgba(79,70,229,0.28)",
  bg: "rgba(79,70,229,0.06)" } as const;

const CLASS_COLORS: Record<string, string> = {
  "β-lactam": "#2563eb", "fluoroquinolone": "#db2777", "tetracycline": "#d97706",
  "sulfonamide": "#7c3aed", "DHFR inhibitor": "#0891b2", "oxazolidinone": "#16a34a",
  "nitroimidazole": "#ca8a04", "nitrofuran": "#ef4444", "amphenicol": "#6b7280",
  "anti-mycobacterial": "#0d9488", "macrolide": "#9333ea", "phosphonic acid": "#65a30d",
  "ansamycin": "#e11d48",
};
const classColor = (k?: string) => (k && CLASS_COLORS[k]) || "#94a3b8";

interface Neighbour { name: string; klass: string; tanimoto: number; }
interface Point {
  kind: "candidate" | "reference"; label: string; klass?: string; smiles: string;
  x: number; y: number; novelty?: number; novelty_band?: string; nearest?: Neighbour[];
}
interface MapResult {
  pathogen: string; n_reference: number; n_candidates: number; classes: string[];
  points: Point[]; primary_novelty: number; primary_novelty_band: string;
  primary_nearest: Neighbour[]; elapsed_s: number; engine: string; note: string;
}
interface Props {
  apiBase: string; smiles: string | null; pathogen: string | null;
  sessionId?: string | null;
}

const BAND_WORD: Record<string, string> = {
  novel: "strong", analogue: "moderate", "me-too": "poor",
};

export function ChemicalSpaceCard({ apiBase, smiles, pathogen, sessionId }: Props) {
  const [result, setResult] = useState<MapResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hover, setHover] = useState<Point | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = useCallback(async () => {
    if (!smiles) { setResult(null); return; }
    setError(null); setRunning(true);
    abortRef.current?.abort();
    const ac = new AbortController(); abortRef.current = ac;
    try {
      const r = await fetch(`${apiBase}/workbench/chem/space/map`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ smiles, pathogen: pathogen || "MRSA",
          save: true, session_id: sessionId || undefined }),
        signal: ac.signal,
      });
      if (!r.ok) { setError(`map failed (HTTP ${r.status})`); return; }
      setResult(await r.json());
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("navigator error");
    } finally { setRunning(false); }
  }, [apiBase, smiles, pathogen, sessionId]);

  useEffect(() => { const t = setTimeout(run, 300); return () => clearTimeout(t); }, [run]);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      {/* header */}
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: INDIGO.fgDeep,
        borderBottom: `1px solid ${INDIGO.border}` }}>
        <Compass size={11} style={{ color: INDIGO.fg }} />
        <span>chemical-space navigator · novelty</span>
        <span style={{ flex: 1 }} />
        {running && <RefreshCw size={10} style={{ animation: "spin 1s linear infinite", color: INDIGO.fg }} />}
        <ProvenanceBadge real label="ECFP4 · Tanimoto" />
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!result && !running && (
          <EmptyState icon={<Compass size={22} style={{ opacity: 0.4 }} />}
            msg="Project the candidate into the chemical space of marketed antibiotics. See its nearest known neighbours and a novelty score — a fresh chemotype, an analogue, or a me-too — computed from ECFP4 fingerprints and exact Tanimoto similarity." />
        )}
        {!result && running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 24,
            color: INDIGO.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Fingerprinting + projecting…</div>
          </div>
        )}

        {result && (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {/* scatter */}
            <div style={{ flex: "2 1 420px", minWidth: 360 }}>
              <SectionLabel color={INDIGO.fgDeep}>
                antibiotic chemical space · {result.n_reference} references</SectionLabel>
              <Scatter points={result.points} hover={hover} setHover={setHover} />
              {/* legend */}
              <div style={{ display: "flex", flexWrap: "wrap", gap: "3px 10px",
                marginTop: 6 }}>
                {result.classes.map((k) => (
                  <span key={k} style={{ display: "inline-flex", alignItems: "center",
                    gap: 4, fontSize: 8, fontFamily: "var(--lys-font-mono)",
                    color: "var(--lys-text-dim)" }}>
                    <span style={{ width: 7, height: 7, borderRadius: 2,
                      background: classColor(k) }} />{k}
                  </span>
                ))}
              </div>
            </div>

            {/* novelty + nearest */}
            <div style={{ flex: "1 1 220px", minWidth: 200, display: "flex",
              flexDirection: "column", gap: 8 }}>
              <div style={{ padding: "9px 11px", borderRadius: 8,
                background: INDIGO.bg, border: `1px solid ${INDIGO.border}` }}>
                <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", textTransform: "uppercase",
                  letterSpacing: "0.05em" }}>novelty score</div>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginTop: 1 }}>
                  <span style={{ fontSize: 30, fontWeight: 800,
                    fontFamily: "var(--lys-font-mono)", color: INDIGO.fgDeep, lineHeight: 1 }}>
                    {(result.primary_novelty * 100).toFixed(0)}<span style={{ fontSize: 14 }}>%</span>
                  </span>
                  <BandPill band={BAND_WORD[result.primary_novelty_band] || "n/a"}>
                    {result.primary_novelty_band}
                  </BandPill>
                </div>
                <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", marginTop: 3 }}>
                  1 − max Tanimoto to any marketed antibiotic
                </div>
              </div>

              <SectionLabel color={INDIGO.fgDeep}>nearest known antibiotics</SectionLabel>
              <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
                {result.primary_nearest.map((n, i) => (
                  <div key={i} style={{ display: "flex", alignItems: "center", gap: 7,
                    padding: "5px 7px", borderRadius: 6, background: "var(--lys-surface)",
                    border: "1px solid var(--lys-border)" }}>
                    <span style={{ width: 8, height: 8, borderRadius: 2,
                      background: classColor(n.klass), flexShrink: 0 }} />
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: "var(--lys-text)",
                        whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                        {n.name}</div>
                      <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
                        color: "var(--lys-text-faint)" }}>{n.klass}</div>
                    </div>
                    <div style={{ width: 60, flexShrink: 0 }}>
                      <div style={{ height: 5, borderRadius: 3, background: "rgba(0,0,0,0.06)",
                        overflow: "hidden" }}>
                        <div style={{ width: `${Math.round(n.tanimoto * 100)}%`, height: "100%",
                          background: classColor(n.klass) }} />
                      </div>
                      <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
                        color: "var(--lys-text-faint)", textAlign: "right", marginTop: 1 }}>
                        T {n.tanimoto.toFixed(2)}</div>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div style={{ flexBasis: "100%", fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", lineHeight: 1.45 }}>
              {result.note}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── scatter plot ───────────────────────────────────────────────────── */
function Scatter({ points, hover, setHover }: {
  points: Point[]; hover: Point | null; setHover: (p: Point | null) => void;
}) {
  const W = 440, H = 300, P = 14;
  const x = (v: number) => P + ((v + 1) / 2) * (W - 2 * P);
  const y = (v: number) => P + ((1 - v) / 2) * (H - 2 * P);   // flip y
  const refs = points.filter((p) => p.kind === "reference");
  const cands = points.filter((p) => p.kind === "candidate");
  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto",
        display: "block", background: "var(--lys-surface)", borderRadius: 6,
        border: "1px solid var(--lys-border)" }}
        onMouseLeave={() => setHover(null)}>
        {/* faint axes cross */}
        <line x1={x(0)} y1={P} x2={x(0)} y2={H - P} stroke="rgba(0,0,0,0.05)" strokeWidth={0.5} />
        <line x1={P} y1={y(0)} x2={W - P} y2={y(0)} stroke="rgba(0,0,0,0.05)" strokeWidth={0.5} />
        {/* reference points */}
        {refs.map((p, i) => (
          <circle key={i} cx={x(p.x)} cy={y(p.y)} r={hover === p ? 6 : 4}
            fill={classColor(p.klass)} fillOpacity={0.78} stroke="white" strokeWidth={0.8}
            style={{ cursor: "pointer", transition: "r 0.1s" }}
            onMouseEnter={() => setHover(p)} />
        ))}
        {/* candidate star markers (drawn last = on top) */}
        {cands.map((p, i) => (
          <g key={`c${i}`} onMouseEnter={() => setHover(p)} style={{ cursor: "pointer" }}>
            <circle cx={x(p.x)} cy={y(p.y)} r={9} fill="none"
              stroke={INDIGO.fg} strokeWidth={1.5} strokeDasharray="3 2" />
            <circle cx={x(p.x)} cy={y(p.y)} r={5.5} fill={INDIGO.fg} stroke="white" strokeWidth={1.5} />
          </g>
        ))}
      </svg>
      {/* tooltip */}
      {hover && (
        <div style={{ position: "absolute", left: `${(x(hover.x) / W) * 100}%`,
          top: `${(y(hover.y) / H) * 100}%`, transform: "translate(-50%,-130%)",
          pointerEvents: "none", background: "var(--lys-text, #0f172a)", color: "white",
          fontSize: 9, fontFamily: "var(--lys-font-mono)", padding: "3px 7px",
          borderRadius: 5, whiteSpace: "nowrap", zIndex: 5,
          boxShadow: "0 2px 8px rgba(0,0,0,0.25)" }}>
          {hover.kind === "candidate" ? "★ candidate" : hover.label}
          {hover.klass ? ` · ${hover.klass}` : ""}
          {hover.kind === "candidate" && hover.novelty != null
            ? ` · novelty ${(hover.novelty * 100).toFixed(0)}%` : ""}
        </div>
      )}
    </div>
  );
}

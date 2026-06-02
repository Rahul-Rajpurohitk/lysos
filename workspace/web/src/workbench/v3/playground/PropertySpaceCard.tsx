/**
 * PropertySpaceCard — is this shaped like an antibiotic? (visual, not a table)
 *
 * Eight small-multiple histograms, one per physicochemical property, each
 * showing the DISTRIBUTION of 30k+ known antibiotics with the candidate
 * positioned on it: a marker line, its percentile-in-antibiotic-space, and
 * the classical drug-like band shaded for reference. A typicality verdict
 * rolls it up. Real RDKit descriptors vs empirical distributions.
 *
 * Backend: /workbench/chem/propspace/*.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { BarChart3, RefreshCw } from "lucide-react";
import { BandPill, ProvenanceBadge, EmptyState } from "./uiPrimitives";

const SKY = { fg: "#0284c7", fgDeep: "#0369a1", border: "rgba(2,132,199,0.26)",
  bg: "rgba(2,132,199,0.06)" } as const;

interface Prop {
  key: string; label: string; unit: string; value: number; percentile: number;
  drug_like_lo: number; drug_like_hi: number; within: boolean;
  median: number; p10: number; p90: number;
  counts: number[]; edges: number[]; cand_bin: number;
}
interface Profile {
  smiles: string; n_reference: number; properties: Prop[];
  in_band: number; n_props: number; typicality: number; band: string;
  engine: string; note: string;
}
interface Props { apiBase: string; smiles: string | null; sessionId?: string | null; }

const BAND_WORD: Record<string, string> = {
  "antibiotic-like": "strong", atypical: "moderate", outlier: "poor",
};

export function PropertySpaceCard({ apiBase, smiles, sessionId }: Props) {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = useCallback(async () => {
    if (!smiles) { setProfile(null); return; }
    setError(null); setRunning(true);
    abortRef.current?.abort();
    const ac = new AbortController(); abortRef.current = ac;
    try {
      const r = await fetch(`${apiBase}/workbench/chem/propspace/profile`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ smiles, save: true, session_id: sessionId || undefined }),
        signal: ac.signal,
      });
      if (!r.ok) { setError(`profile failed (HTTP ${r.status})`); return; }
      setProfile(await r.json());
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("property-space error");
    } finally { setRunning(false); }
  }, [apiBase, smiles, sessionId]);

  useEffect(() => { const t = setTimeout(run, 300); return () => clearTimeout(t); }, [run]);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      {/* header */}
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: SKY.fgDeep,
        borderBottom: `1px solid ${SKY.border}` }}>
        <BarChart3 size={11} style={{ color: SKY.fg }} />
        <span>property space · vs known antibiotics</span>
        <span style={{ flex: 1 }} />
        {running && <RefreshCw size={10} style={{ animation: "spin 1s linear infinite", color: SKY.fg }} />}
        <ProvenanceBadge real label="30k antibiotic dist." />
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!profile && !running && (
          <EmptyState icon={<BarChart3 size={22} style={{ opacity: 0.4 }} />}
            msg="See where the candidate sits in real antibiotic property space — eight distributions of 30,000+ known antibiotics with your molecule positioned, its percentile, and the classical drug-like band for reference." />
        )}
        {!profile && running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 24,
            color: SKY.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Positioning in antibiotic property space…</div>
          </div>
        )}

        {profile && (
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {/* verdict bar */}
            <div style={{ display: "flex", alignItems: "center", gap: 10,
              padding: "8px 11px", borderRadius: 8, background: SKY.bg,
              border: `1px solid ${SKY.border}` }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontSize: 24, fontWeight: 800,
                  fontFamily: "var(--lys-font-mono)", color: SKY.fgDeep, lineHeight: 1 }}>
                  {profile.in_band}<span style={{ fontSize: 13,
                    color: "var(--lys-text-faint)" }}>/{profile.n_props}</span>
                </span>
                <BandPill band={BAND_WORD[profile.band] || "n/a"}>{profile.band}</BandPill>
              </div>
              <div style={{ flex: 1, fontSize: 9, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)" }}>
                properties inside the classical drug-like band · benchmarked
                against {profile.n_reference.toLocaleString()} known antibiotics
              </div>
            </div>

            {/* small-multiple histograms */}
            <div style={{ display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 8 }}>
              {profile.properties.map((p) => <HistTile key={p.key} p={p} />)}
            </div>

            <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", lineHeight: 1.45 }}>
              {profile.note}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── one property distribution tile ─────────────────────────────────── */
function HistTile({ p }: { p: Prop }) {
  const W = 196, H = 92, PL = 6, PR = 6, PT = 16, PB = 16;
  const iw = W - PL - PR, ih = H - PT - PB;
  const e0 = p.edges[0], e1 = p.edges[p.edges.length - 1];
  const span = e1 - e0 || 1;
  const maxC = Math.max(...p.counts, 1);
  const xv = (v: number) => PL + ((Math.max(e0, Math.min(e1, v)) - e0) / span) * iw;
  const barW = iw / p.counts.length;
  const col = p.within ? "#16a34a" : "#d97706";
  // drug-like band rect
  const bandX0 = xv(p.drug_like_lo), bandX1 = xv(p.drug_like_hi);
  return (
    <div style={{ border: "1px solid var(--lys-border)", borderRadius: 6,
      background: "var(--lys-surface)", padding: "5px 7px 4px" }}>
      <div style={{ display: "flex", justifyContent: "space-between",
        alignItems: "baseline" }}>
        <span style={{ fontSize: 9, fontWeight: 700, color: "var(--lys-text)" }}>
          {p.label}</span>
        <span style={{ fontSize: 10, fontWeight: 800, fontFamily: "var(--lys-font-mono)",
          color: col }}>{p.value}{p.unit ? ` ${p.unit}` : ""}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {/* drug-like band shading */}
        <rect x={bandX0} y={PT} width={Math.max(0, bandX1 - bandX0)} height={ih}
          fill="rgba(16,163,74,0.07)" />
        <line x1={bandX0} y1={PT} x2={bandX0} y2={PT + ih} stroke="rgba(16,163,74,0.3)"
          strokeWidth={0.6} strokeDasharray="2 2" />
        <line x1={bandX1} y1={PT} x2={bandX1} y2={PT + ih} stroke="rgba(16,163,74,0.3)"
          strokeWidth={0.6} strokeDasharray="2 2" />
        {/* histogram bars */}
        {p.counts.map((c, i) => {
          const h = (c / maxC) * ih;
          const isCand = i === p.cand_bin;
          return <rect key={i} x={PL + i * barW + 0.4} y={PT + ih - h}
            width={Math.max(0.6, barW - 0.8)} height={h}
            fill={isCand ? col : "rgba(2,132,199,0.34)"} />;
        })}
        {/* candidate marker line */}
        <line x1={xv(p.value)} y1={PT - 3} x2={xv(p.value)} y2={PT + ih}
          stroke={col} strokeWidth={1.4} />
        <circle cx={xv(p.value)} cy={PT - 3} r={2.4} fill={col} />
        {/* median tick */}
        <line x1={xv(p.median)} y1={PT + ih} x2={xv(p.median)} y2={PT + ih + 3}
          stroke="var(--lys-text-faint)" strokeWidth={0.8} />
        {/* axis labels */}
        <text x={PL} y={H - 4} fontSize={6.5} fontFamily="var(--lys-font-mono)"
          fill="var(--lys-text-faint)">{e0}</text>
        <text x={W - PR} y={H - 4} textAnchor="end" fontSize={6.5}
          fontFamily="var(--lys-font-mono)" fill="var(--lys-text-faint)">{e1}</text>
        <text x={xv(p.median)} y={H - 4} textAnchor="middle" fontSize={6}
          fontFamily="var(--lys-font-mono)" fill="var(--lys-text-faint)">med {p.median}</text>
      </svg>
      <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", textAlign: "center", marginTop: 1 }}>
        {p.percentile}ᵗʰ pct · {p.within ? "in drug-like band" : "outside band"}
      </div>
    </div>
  );
}

/**
 * ShapeExplorerCard — the molecule's 3D form on the PMI shape triangle.
 *
 * Embeds a conformer ensemble and plots it on the canonical rod ↔ disc ↔
 * sphere triangle (normalised principal-moment ratios). The spread of the
 * ensemble is the flexibility; the lowest-energy conformer is the marker.
 * Plus radius of gyration, asphericity, globularity, Fsp3. For antibiotics
 * this matters: Gram-negative entry favours small, rigid, planar shapes.
 *
 * Backend: /workbench/chem/shape/*.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Box, RefreshCw } from "lucide-react";
import { StatTile, MetricBar, BandPill, ProvenanceBadge, SectionLabel, EmptyState } from "./uiPrimitives";

const PUR = { fg: "#7e22ce", fgDeep: "#6b21a8", border: "rgba(126,34,206,0.26)",
  bg: "rgba(126,34,206,0.06)" } as const;
const SHAPE_COLOR: Record<string, string> = {
  "rod-like": "#0891b2", "disc-like": "#16a34a", "spherical": "#d97706" };

interface Conf { npr1: number; npr2: number; rg: number; energy: number; shape: string; }
interface Profile {
  smiles: string; n_conformers: number; conformers: Conf[]; representative: Conf;
  mean_npr1: number; mean_npr2: number; shape_class: string;
  flexibility: number; flexibility_band: string; rg: number;
  asphericity: number | null; eccentricity: number | null; spherocity: number | null;
  rotatable_bonds: number; fsp3: number; engine: string; note: string;
}
interface Props { apiBase: string; smiles: string | null; sessionId?: string | null; }

const FLEX_BAND: Record<string, string> = {
  rigid: "strong", moderate: "moderate", flexible: "poor" };

export function ShapeExplorerCard({ apiBase, smiles, sessionId }: Props) {
  const [p, setP] = useState<Profile | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = useCallback(async () => {
    if (!smiles) { setP(null); return; }
    setError(null); setRunning(true);
    abortRef.current?.abort();
    const ac = new AbortController(); abortRef.current = ac;
    try {
      const r = await fetch(`${apiBase}/workbench/chem/shape/profile`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ smiles, n_conformers: 16, save: true,
          session_id: sessionId || undefined }),
        signal: ac.signal,
      });
      if (!r.ok) { setError(`shape failed (HTTP ${r.status})`); return; }
      setP(await r.json());
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("shape error");
    } finally { setRunning(false); }
  }, [apiBase, smiles, sessionId]);

  useEffect(() => { const t = setTimeout(run, 350); return () => clearTimeout(t); }, [run]);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: PUR.fgDeep,
        borderBottom: `1px solid ${PUR.border}` }}>
        <Box size={11} style={{ color: PUR.fg }} />
        <span>3D shape &amp; flexibility · PMI</span>
        <span style={{ flex: 1 }} />
        {running && <RefreshCw size={10} style={{ animation: "spin 1s linear infinite", color: PUR.fg }} />}
        <ProvenanceBadge real label="ETKDGv3 conformers" />
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!p && !running && (
          <EmptyState icon={<Box size={22} style={{ opacity: 0.4 }} />}
            msg="Embed a conformer ensemble and see the molecule's 3D form on the rod ↔ disc ↔ sphere triangle, with flexibility and globularity. Gram-negative entry favours small, rigid, planar shapes." />
        )}
        {!p && running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 24,
            color: PUR.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Embedding conformers + computing 3D shape…</div>
          </div>
        )}

        {p && (
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {/* triangle */}
            <div style={{ flex: "1 1 240px", minWidth: 220 }}>
              <SectionLabel color={PUR.fgDeep}>
                PMI shape triangle · {p.n_conformers} conformers</SectionLabel>
              <PMITriangle confs={p.conformers} rep={p.representative} />
            </div>
            {/* metrics */}
            <div style={{ flex: "1 1 200px", minWidth: 190, display: "flex",
              flexDirection: "column", gap: 8 }}>
              <div style={{ padding: "8px 11px", borderRadius: 8, background: PUR.bg,
                border: `1px solid ${PUR.border}` }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <span style={{ fontSize: 16, fontWeight: 800, color: SHAPE_COLOR[p.shape_class] ?? PUR.fgDeep,
                    fontFamily: "var(--lys-font-mono)" }}>{p.shape_class}</span>
                  <BandPill band={FLEX_BAND[p.flexibility_band] || "n/a"}>
                    {p.flexibility_band}</BandPill>
                </div>
                <div style={{ marginTop: 6 }}>
                  <MetricBar label="flexibility" value={p.flexibility}
                    band={FLEX_BAND[p.flexibility_band]} invert
                    valueLabel={p.flexibility.toFixed(2)} />
                </div>
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 6 }}>
                <StatTile label="Radius gyr." value={p.rg} sub="Å" color={PUR.fgDeep} />
                <StatTile label="Asphericity" value={p.asphericity ?? "—"} color={PUR.fgDeep} />
                <StatTile label="Fsp³" value={p.fsp3} color={PUR.fgDeep}
                  title="fraction of sp3 carbons — 3D character" />
                <StatTile label="Rot. bonds" value={p.rotatable_bonds} color={PUR.fgDeep} />
              </div>
            </div>
            <div style={{ flexBasis: "100%", fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", lineHeight: 1.45 }}>{p.note}</div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ── PMI triangle: rod (0,1) · disc (0.5,0.5) · sphere (1,1) ─────────── */
function PMITriangle({ confs, rep }: { confs: Conf[]; rep: Conf }) {
  const W = 250, H = 230, PL = 14, PR = 14, PT = 22, PB = 22;
  const iw = W - PL - PR, ih = H - PT - PB;
  // x = NPR1 [0,1]; y = NPR2 [0.5,1] (1 at top)
  const x = (n1: number) => PL + Math.max(0, Math.min(1, n1)) * iw;
  const y = (n2: number) => PT + (1 - (Math.max(0.5, Math.min(1, n2)) - 0.5) / 0.5) * ih;
  const rod = [x(0), y(1)], disc = [x(0.5), y(0.5)], sph = [x(1), y(1)];
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto",
      maxWidth: 280, display: "block", background: "var(--lys-surface)",
      borderRadius: 6, border: "1px solid var(--lys-border)" }}>
      {/* triangle */}
      <polygon points={`${rod[0]},${rod[1]} ${sph[0]},${sph[1]} ${disc[0]},${disc[1]}`}
        fill="rgba(126,34,206,0.04)" stroke="rgba(126,34,206,0.25)" strokeWidth={1} />
      {/* vertex labels */}
      <text x={rod[0]} y={rod[1] - 7} textAnchor="middle" fontSize={9} fontWeight={700}
        fontFamily="var(--lys-font-mono)" fill={SHAPE_COLOR["rod-like"]}>rod</text>
      <text x={sph[0]} y={sph[1] - 7} textAnchor="middle" fontSize={9} fontWeight={700}
        fontFamily="var(--lys-font-mono)" fill={SHAPE_COLOR["spherical"]}>sphere</text>
      <text x={disc[0]} y={disc[1] + 13} textAnchor="middle" fontSize={9} fontWeight={700}
        fontFamily="var(--lys-font-mono)" fill={SHAPE_COLOR["disc-like"]}>disc</text>
      {/* conformer cloud */}
      {confs.map((c, i) => (
        <circle key={i} cx={x(c.npr1)} cy={y(c.npr2)} r={2.4}
          fill={SHAPE_COLOR[c.shape] ?? "#7e22ce"} fillOpacity={0.45} />
      ))}
      {/* representative (lowest-energy) */}
      <circle cx={x(rep.npr1)} cy={y(rep.npr2)} r={5} fill="none"
        stroke={PUR.fg} strokeWidth={1.6} />
      <circle cx={x(rep.npr1)} cy={y(rep.npr2)} r={3} fill={PUR.fg} />
    </svg>
  );
}

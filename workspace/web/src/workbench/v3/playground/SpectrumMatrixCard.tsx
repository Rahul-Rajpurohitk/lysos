/**
 * SpectrumMatrixCard — narrow or broad? Real per-pathogen binding coverage.
 *
 * Spectrum is THE defining antibiotic property and the one thing the
 * molecule-intrinsic score can't show (it's identical for every pathogen).
 * This docks the candidate into each of the 8 priority pathogens' validated
 * targets and renders the coverage matrix: a per-pathogen binding bar
 * (ΔG, coloured by band), a covered/not call, and a narrow/moderate/broad
 * classification. Manual-triggered (8 real docks, ~20s).
 *
 * Backend: /workbench/chem/spectrum/*.
 */
import { useState, useCallback, useRef, useEffect } from "react";
import { Radar, RefreshCw, Crosshair } from "lucide-react";
import { BandPill, ProvenanceBadge, SectionLabel, EmptyState } from "./uiPrimitives";

const EM = { fg: "#047857", fgDeep: "#065f46", border: "rgba(4,120,87,0.26)",
  bg: "rgba(4,120,87,0.06)" } as const;
const DOCK_BAND_COLOR: Record<string, string> = {
  strong: "#16a34a", good: "#65a30d", moderate: "#d97706", weak: "#dc2626",
  "very weak": "#dc2626" };
const SPECTRUM_BAND: Record<string, string> = {
  broad: "strong", moderate: "moderate", narrow: "limited", "no-coverage": "poor" };

interface Row {
  pathogen: string; target: string; target_full: string; pdb_id: string;
  affinity_kcal_mol: number | null; band: string | null;
  n_interactions: number | null; covered: boolean;
}
interface Result {
  smiles: string; rows: Row[]; n_covered: number; n_pathogens: number;
  spectrum: string; best: Row | null; mean_affinity: number | null;
  covered_threshold: number; elapsed_s: number; engine: string; note: string;
}
interface Props { apiBase: string; smiles: string | null; sessionId?: string | null; }

export function SpectrumMatrixCard({ apiBase, smiles, sessionId }: Props) {
  const [result, setResult] = useState<Result | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);
  // Clear stale result when the candidate changes (don't auto-run — it's slow).
  useEffect(() => { setResult(null); setError(null); }, [smiles]);

  const run = useCallback(async () => {
    if (!smiles) return;
    setError(null); setRunning(true);
    abortRef.current?.abort();
    const ac = new AbortController(); abortRef.current = ac;
    try {
      const r = await fetch(`${apiBase}/workbench/chem/spectrum/run`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ smiles, save: true, session_id: sessionId || undefined }),
        signal: ac.signal,
      });
      if (!r.ok) { setError(`spectrum failed (HTTP ${r.status})`); return; }
      setResult(await r.json());
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("spectrum error");
    } finally { setRunning(false); }
  }, [apiBase, smiles, sessionId]);

  // worst |ΔG| for bar scaling
  const maxMag = result ? Math.max(6, ...result.rows.map(
    (r) => Math.abs(r.affinity_kcal_mol ?? 0))) : 6;

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: EM.fgDeep,
        borderBottom: `1px solid ${EM.border}` }}>
        <Radar size={11} style={{ color: EM.fg }} />
        <span>spectrum coverage · 8 pathogens</span>
        <span style={{ flex: 1 }} />
        <ProvenanceBadge real label="Vina · per-target dock" />
      </div>

      {/* action */}
      <div style={{ padding: "8px 10px", display: "flex", alignItems: "center",
        gap: 8, borderBottom: "1px solid rgba(0,0,0,0.05)" }}>
        <button type="button" onClick={run} disabled={running || !smiles}
          style={{ display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 11px", borderRadius: 6, border: 0,
            background: !smiles ? "rgba(0,0,0,0.05)" : EM.fg,
            color: !smiles ? "var(--lys-text-faint)" : "white",
            fontSize: 11, fontWeight: 700, cursor: running || !smiles ? "not-allowed" : "pointer" }}>
          <Crosshair size={12} />
          {running ? "Docking 8 targets…" : "Run spectrum"}
        </button>
        <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)" }}>
          {smiles ? "real dock into each pathogen's target · ~20s" : "load a candidate"}
        </span>
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!result && !running && (
          <EmptyState icon={<Radar size={22} style={{ opacity: 0.4 }} />}
            msg="Dock the candidate into all eight priority pathogens' validated targets to see its true coverage — narrow vs broad spectrum. Real binding ΔG per pathogen, the one signal the composite score can't give you." />
        )}
        {running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 28,
            color: EM.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Docking into 8 pathogen targets…</div>
            <div style={{ fontSize: 9, color: "var(--lys-text-faint)" }}>
              PBP2a · InhA · KPC-2 · NDM-1 · OXA-23 · GyrB · PBP5 · PBP2</div>
          </div>
        )}

        {result && !running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {/* verdict */}
            <div style={{ display: "flex", alignItems: "center", gap: 10,
              padding: "8px 11px", borderRadius: 8, background: EM.bg,
              border: `1px solid ${EM.border}` }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontSize: 24, fontWeight: 800,
                  fontFamily: "var(--lys-font-mono)", color: EM.fgDeep, lineHeight: 1 }}>
                  {result.n_covered}<span style={{ fontSize: 13,
                    color: "var(--lys-text-faint)" }}>/{result.n_pathogens}</span>
                </span>
                <BandPill band={SPECTRUM_BAND[result.spectrum] || "n/a"}>
                  {result.spectrum}-spectrum</BandPill>
              </div>
              <div style={{ flex: 1, fontSize: 9, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)" }}>
                pathogens covered (ΔG ≤ {result.covered_threshold}) · mean ΔG
                {" "}{result.mean_affinity} kcal/mol
              </div>
            </div>

            {/* coverage matrix */}
            <SectionLabel color={EM.fgDeep}>per-pathogen binding · strongest first</SectionLabel>
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {result.rows.map((r) => {
                const mag = Math.abs(r.affinity_kcal_mol ?? 0);
                const pct = Math.round((mag / maxMag) * 100);
                const col = DOCK_BAND_COLOR[(r.band ?? "").toLowerCase()] ?? "#94a3b8";
                return (
                  <div key={r.pathogen} title={r.target_full}
                    style={{ display: "flex", alignItems: "center", gap: 8,
                      padding: "5px 8px", borderRadius: 6,
                      background: r.covered ? EM.bg : "var(--lys-surface)",
                      border: `1px solid ${r.covered ? EM.border : "var(--lys-border)"}` }}>
                    <div style={{ width: 78, flexShrink: 0 }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: "var(--lys-text)" }}>
                        {r.pathogen}</div>
                      <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
                        color: "var(--lys-text-faint)" }}>{r.target}</div>
                    </div>
                    {/* bar */}
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ height: 12, borderRadius: 3, background: "rgba(0,0,0,0.05)",
                        overflow: "hidden" }}>
                        <div style={{ width: `${pct}%`, height: "100%", background: col,
                          transition: "width 0.4s" }} />
                      </div>
                    </div>
                    <span style={{ width: 48, flexShrink: 0, textAlign: "right",
                      fontSize: 10, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
                      color: col }}>
                      {r.affinity_kcal_mol ?? "—"}</span>
                    <span style={{ width: 60, flexShrink: 0, fontSize: 8,
                      fontFamily: "var(--lys-font-mono)", textTransform: "uppercase",
                      color: col }}>{r.band ?? "—"}</span>
                    <span style={{ width: 14, flexShrink: 0, textAlign: "center",
                      fontSize: 11, color: r.covered ? "#16a34a" : "var(--lys-text-faint)" }}>
                      {r.covered ? "✓" : "·"}</span>
                  </div>
                );
              })}
            </div>
            <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", lineHeight: 1.45 }}>{result.note}</div>
          </div>
        )}
      </div>
    </div>
  );
}

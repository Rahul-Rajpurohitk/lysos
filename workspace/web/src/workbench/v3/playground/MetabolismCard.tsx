/**
 * MetabolismCard — where will this molecule get metabolised, and how to fix it.
 *
 * Flags labile sites (N-/O-dealkylation, aromatic & benzylic oxidation,
 * ester/amide hydrolysis, S-oxidation, ω-oxidation, glucuronidation handles,
 * bioactivation alerts) with the enzyme pathway, the affected atoms, and the
 * standard medicinal-chemistry mitigation. A metabolic-stability gauge rolls
 * it up. Pairs with the Bioisostere Studio, which makes the fix.
 *
 * Transparent rule-based site-of-metabolism. Backend: /workbench/chem/metabolism/*.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { Flame, RefreshCw } from "lucide-react";
import { Mol2DThumb } from "./Mol2DThumb";
import { MetricBar, BandPill, ProvenanceBadge, SectionLabel, EmptyState } from "./uiPrimitives";

const AMB = { fg: "#c2410c", fgDeep: "#9a3412", border: "rgba(194,65,12,0.26)",
  bg: "rgba(194,65,12,0.05)" } as const;
const SEV_COLOR = ["#94a3b8", "#65a30d", "#d97706", "#dc2626"]; // idx by severity 1-3
const STAB_BAND: Record<string, string> = {
  stable: "strong", moderate: "moderate", labile: "poor" };

interface SoftSpot {
  id: string; label: string; pathway: string; severity: number; fix: string;
  atoms: number[]; count: number;
}
interface Scan {
  smiles: string; soft_spots: SoftSpot[]; n_soft_spots: number;
  n_high_severity: number; flagged_atoms: number[];
  metabolic_stability: number; band: string; engine: string; note: string;
}
interface Props { apiBase: string; smiles: string | null; sessionId?: string | null; }

export function MetabolismCard({ apiBase, smiles, sessionId }: Props) {
  const [scan, setScan] = useState<Scan | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = useCallback(async () => {
    if (!smiles) { setScan(null); return; }
    setError(null); setRunning(true);
    abortRef.current?.abort();
    const ac = new AbortController(); abortRef.current = ac;
    try {
      const r = await fetch(`${apiBase}/workbench/chem/metabolism/scan`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ smiles, save: true, session_id: sessionId || undefined }),
        signal: ac.signal,
      });
      if (!r.ok) { setError(`scan failed (HTTP ${r.status})`); return; }
      setScan(await r.json());
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("metabolism error");
    } finally { setRunning(false); }
  }, [apiBase, smiles, sessionId]);

  useEffect(() => { const t = setTimeout(run, 300); return () => clearTimeout(t); }, [run]);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: AMB.fgDeep,
        borderBottom: `1px solid ${AMB.border}` }}>
        <Flame size={11} style={{ color: AMB.fg }} />
        <span>metabolic soft-spots · site of metabolism</span>
        <span style={{ flex: 1 }} />
        {running && <RefreshCw size={10} style={{ animation: "spin 1s linear infinite", color: AMB.fg }} />}
        <ProvenanceBadge real label="rule-based SoM" />
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!scan && !running && (
          <EmptyState icon={<Flame size={22} style={{ opacity: 0.4 }} />}
            msg="Flag the metabolically labile sites — dealkylation, ring oxidation, ester/amide hydrolysis, glucuronidation handles, bioactivation alerts — each with the enzyme pathway and the medchem fix. Where the molecule gets chewed up, and how to harden it." />
        )}
        {!scan && running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 24,
            color: AMB.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Scanning for labile motifs…</div>
          </div>
        )}

        {scan && (
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {/* stability hero + structure */}
            <div style={{ display: "flex", gap: 10, alignItems: "center",
              padding: "8px 11px", borderRadius: 8, background: AMB.bg,
              border: `1px solid ${AMB.border}` }}>
              <Mol2DThumb apiBase={apiBase} smiles={scan.smiles} w={96} h={74}
                accent={AMB.fg} caption="candidate" />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                    color: "var(--lys-text-faint)", textTransform: "uppercase" }}>
                    metabolic stability</span>
                  <BandPill band={STAB_BAND[scan.band] || "n/a"}>{scan.band}</BandPill>
                </div>
                <div style={{ marginTop: 4 }}>
                  <MetricBar label="stability" value={scan.metabolic_stability}
                    band={STAB_BAND[scan.band]}
                    valueLabel={scan.metabolic_stability.toFixed(2)} />
                </div>
                <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", marginTop: 5 }}>
                  {scan.n_soft_spots} soft spot{scan.n_soft_spots === 1 ? "" : "s"}
                  {scan.n_high_severity > 0
                    ? ` · ${scan.n_high_severity} high-severity` : ""}
                </div>
              </div>
            </div>

            {/* soft-spot list */}
            <SectionLabel color={AMB.fgDeep}>labile sites · pathway · fix</SectionLabel>
            {scan.soft_spots.length === 0 && (
              <div style={{ fontSize: 10, color: "#16a34a", fontFamily: "var(--lys-font-mono)" }}>
                ✓ no common labile motifs flagged
              </div>
            )}
            <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
              {scan.soft_spots.map((s) => (
                <div key={s.id} style={{ padding: "6px 8px", borderRadius: 6,
                  background: "var(--lys-surface)", border: "1px solid var(--lys-border)",
                  borderLeft: `3px solid ${SEV_COLOR[s.severity]}` }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    {/* severity dots */}
                    <span style={{ display: "inline-flex", gap: 2, flexShrink: 0 }}>
                      {[1, 2, 3].map((lvl) => (
                        <span key={lvl} style={{ width: 5, height: 5, borderRadius: 5,
                          background: lvl <= s.severity ? SEV_COLOR[s.severity] : "rgba(0,0,0,0.1)" }} />
                      ))}
                    </span>
                    <span style={{ fontSize: 10, fontWeight: 700, color: "var(--lys-text)" }}>
                      {s.label}</span>
                    <span style={{ flex: 1 }} />
                    <span style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
                      color: "var(--lys-text-faint)", flexShrink: 0 }}>
                      atom{s.atoms.length === 1 ? "" : "s"} {s.atoms.join(",")}</span>
                  </div>
                  <div style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                    color: "var(--lys-text-faint)", marginTop: 2 }}>{s.pathway}</div>
                  <div style={{ fontSize: 9, color: AMB.fgDeep, marginTop: 3 }}>
                    <b>fix:</b> {s.fix}</div>
                </div>
              ))}
            </div>
            <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", lineHeight: 1.45 }}>{scan.note}</div>
          </div>
        )}
      </div>
    </div>
  );
}

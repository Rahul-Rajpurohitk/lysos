/**
 * GramEntryCard — will the molecule even get into a Gram-negative? (eNTRy rules)
 *
 * The biggest filter for Gram-negative antibiotics (E. coli, Klebsiella,
 * Acinetobacter, Pseudomonas). Scores the candidate against the published
 * eNTRy rules (Richter & Hergenrother, Nature 2017): ionizable Nitrogen +
 * low globularity (Three-D flat) + Rigidity. Three big criterion tiles with
 * pass/fail, an entry verdict, the gated Gram-negative targets, and fixes.
 *
 * Backend: /workbench/chem/entry/*.
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { DoorOpen, RefreshCw, Check, X } from "lucide-react";
import { BandPill, ProvenanceBadge, SectionLabel, EmptyState } from "./uiPrimitives";

const BLU = { fg: "#1d4ed8", fgDeep: "#1e40af", border: "rgba(29,78,216,0.26)",
  bg: "rgba(29,78,216,0.06)" } as const;

interface Crit { key: string; label: string; pass: boolean; detail: string; weight: number; }
interface Result {
  smiles: string; criteria: Crit[]; n_pass: number; entry_score: number; band: string;
  has_primary_amine: boolean; globularity: number | null; rotatable_bonds: number;
  gram_negative_targets: string[]; gated: boolean; tips: string[];
  engine: string; note: string;
}
interface Props { apiBase: string; smiles: string | null; sessionId?: string | null; }

const BAND_WORD: Record<string, string> = {
  "likely-accumulator": "strong", borderline: "moderate", unlikely: "poor" };
const BAND_LABEL: Record<string, string> = {
  "likely-accumulator": "likely entry", borderline: "borderline", unlikely: "blocked" };

export function GramEntryCard({ apiBase, smiles, sessionId }: Props) {
  const [r, setR] = useState<Result | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => () => abortRef.current?.abort(), []);

  const run = useCallback(async () => {
    if (!smiles) { setR(null); return; }
    setError(null); setRunning(true);
    abortRef.current?.abort();
    const ac = new AbortController(); abortRef.current = ac;
    try {
      const res = await fetch(`${apiBase}/workbench/chem/entry/predict`, {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ smiles, save: true, session_id: sessionId || undefined }),
        signal: ac.signal,
      });
      if (!res.ok) { setError(`entry failed (HTTP ${res.status})`); return; }
      setR(await res.json());
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError("entry error");
    } finally { setRunning(false); }
  }, [apiBase, smiles, sessionId]);

  useEffect(() => { const t = setTimeout(run, 350); return () => clearTimeout(t); }, [run]);

  return (
    <div style={{ width: "100%", height: "100%", display: "flex",
      flexDirection: "column", overflow: "hidden", fontFamily: "var(--lys-font-body)" }}>
      <div style={{ padding: "6px 10px", display: "flex", alignItems: "center",
        gap: 6, fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.06em", textTransform: "uppercase", color: BLU.fgDeep,
        borderBottom: `1px solid ${BLU.border}` }}>
        <DoorOpen size={11} style={{ color: BLU.fg }} />
        <span>gram-negative entry · eNTRy rules</span>
        <span style={{ flex: 1 }} />
        {running && <RefreshCw size={10} style={{ animation: "spin 1s linear infinite", color: BLU.fg }} />}
        <ProvenanceBadge real label="Hergenrother 2017" />
      </div>

      {error && <div style={{ padding: "6px 10px", fontSize: 10, color: "#b91c1c" }}>{error}</div>}

      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!r && !running && (
          <EmptyState icon={<DoorOpen size={22} style={{ opacity: 0.4 }} />}
            msg="The biggest filter for Gram-negative antibiotics. Scores the candidate against the eNTRy rules — ionizable amine, flat shape, rigid — that predict accumulation inside E. coli & friends." />
        )}
        {!r && running && (
          <div style={{ display: "flex", flexDirection: "column", gap: 6,
            alignItems: "center", justifyContent: "center", padding: 24,
            color: BLU.fgDeep, fontSize: 11 }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Embedding 3D + scoring eNTRy rules…</div>
          </div>
        )}

        {r && (
          <div style={{ display: "flex", flexDirection: "column", gap: 9 }}>
            {/* verdict */}
            <div style={{ display: "flex", alignItems: "center", gap: 10,
              padding: "8px 11px", borderRadius: 8, background: BLU.bg,
              border: `1px solid ${BLU.border}` }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                <span style={{ fontSize: 24, fontWeight: 800,
                  fontFamily: "var(--lys-font-mono)", color: BLU.fgDeep, lineHeight: 1 }}>
                  {r.n_pass}<span style={{ fontSize: 13, color: "var(--lys-text-faint)" }}>/3</span>
                </span>
                <BandPill band={BAND_WORD[r.band] || "n/a"}>{BAND_LABEL[r.band] || r.band}</BandPill>
              </div>
              <div style={{ flex: 1, fontSize: 9, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)" }}>
                eNTRy rules met · entry score {r.entry_score}
              </div>
            </div>

            {/* 3 criterion tiles: N · T · R */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3,1fr)", gap: 6 }}>
              {r.criteria.map((c) => (
                <div key={c.key} style={{ border: `1px solid ${c.pass ? "rgba(22,163,74,0.4)" : "rgba(220,38,38,0.3)"}`,
                  borderRadius: 7, padding: "7px 8px", textAlign: "center",
                  background: c.pass ? "rgba(22,163,74,0.06)" : "rgba(220,38,38,0.04)" }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 4 }}>
                    <span style={{ fontSize: 18, fontWeight: 800, fontFamily: "var(--lys-font-mono)",
                      color: c.pass ? "#16a34a" : "#dc2626" }}>{c.key}</span>
                    {c.pass ? <Check size={13} style={{ color: "#16a34a" }} />
                      : <X size={13} style={{ color: "#dc2626" }} />}
                  </div>
                  <div style={{ fontSize: 8.5, fontWeight: 700, color: "var(--lys-text)", marginTop: 2 }}>
                    {c.label}</div>
                  <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
                    color: "var(--lys-text-faint)", marginTop: 2 }}>{c.detail}</div>
                </div>
              ))}
            </div>

            {/* gated Gram-negative targets */}
            <div>
              <SectionLabel color={BLU.fgDeep}>gates these Gram-negative targets</SectionLabel>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
                {r.gram_negative_targets.map((t) => (
                  <span key={t} style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                    padding: "2px 8px", borderRadius: 999,
                    background: r.gated ? "rgba(220,38,38,0.08)" : "rgba(22,163,74,0.08)",
                    color: r.gated ? "#b91c1c" : "#15803d",
                    border: `1px solid ${r.gated ? "rgba(220,38,38,0.3)" : "rgba(22,163,74,0.3)"}` }}>
                    {t}{r.gated ? " · gated" : " · reachable"}</span>
                ))}
              </div>
            </div>

            {/* tips */}
            <div>
              <SectionLabel color={BLU.fgDeep}>to improve entry</SectionLabel>
              {r.tips.map((t, i) => (
                <div key={i} style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
                  lineHeight: 1.5 }}>• {t}</div>
              ))}
            </div>
            <div style={{ fontSize: 8, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", lineHeight: 1.45 }}>{r.note}</div>
          </div>
        )}
      </div>
    </div>
  );
}

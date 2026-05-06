/**
 * ToxicityProfileCard — ADME-Tox prediction dashboard.
 *
 * Reads /workbench/molecule/toxicity?smiles=… (QSAR-rule predictions).
 * 4 risk panels with risk-level color tiles + rationales:
 *   - hERG (cardiotoxicity)
 *   - Hepatotoxicity
 *   - Mutagenicity (Ames)
 *   - Skin sensitization
 * Plus an overall safety composite score with traffic-light tile.
 */
import { useEffect, useState } from "react";
import { Skull, Heart, Activity, AlertTriangle, RefreshCw, Shield } from "lucide-react";

interface Tox {
  smiles: string;
  canonical_smiles: string;
  herg_risk: string;
  herg_score: number;
  herg_rationale: string;
  hepatotox_risk: string;
  hepatotox_score: number;
  hepatotox_rationale: string;
  ames_risk: string;
  ames_score: number;
  ames_rationale: string;
  skin_sens_risk: string;
  skin_sens_rationale: string;
  overall_safety_score: number;
}

interface Props {
  apiBase: string;
  smiles: string | null;
}

const RISK_COLOR: Record<string, string> = {
  low: "#10b981", medium: "#d97706", high: "#dc2626",
};

export function ToxicityProfileCard({ apiBase, smiles }: Props) {
  const [data, setData] = useState<Tox | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  async function refresh() {
    if (!smiles) { setData(null); return; }
    setLoading(true); setError("");
    try {
      const r = await fetch(`${apiBase}/workbench/molecule/toxicity?smiles=${encodeURIComponent(smiles)}`);
      if (!r.ok) throw new Error(`http ${r.status}`);
      setData(await r.json());
    } catch (e: any) { setError(String(e?.message ?? e)); }
    finally { setLoading(false); }
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [smiles, apiBase]);

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      <div style={{
        padding: "5px 10px",
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.06em",
        textTransform: "uppercase",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <Skull size={11} style={{ color: data ? (data.overall_safety_score >= 0.7 ? "#10b981" : "#dc2626") : "#9ca3af" }} />
        <span>toxicity · {data ? `safety ${(data.overall_safety_score*100).toFixed(0)}%` : "ADME-Tox"}</span>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={refresh} disabled={loading}
          style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      <div style={{ flex: 1, overflow: "auto", padding: 8, display: "flex",
        flexDirection: "column", gap: 6 }}>
        {!smiles && <Empty msg="pick or design a candidate to run ADME-Tox" />}
        {smiles && loading && !data && <Empty msg="computing toxicity profile…" />}
        {smiles && error && <div style={{ color: "#dc2626", fontSize: 10, padding: 8 }}>{error}</div>}
        {smiles && data && (
          <>
            {/* Overall safety */}
            <SafetyTile value={data.overall_safety_score} />

            {/* 4 risk panels */}
            <RiskPanel
              icon={<Heart size={11} />}
              title="hERG (cardiotox)"
              risk={data.herg_risk}
              score={data.herg_score}
              rationale={data.herg_rationale}
            />
            <RiskPanel
              icon={<Activity size={11} />}
              title="hepatotoxicity"
              risk={data.hepatotox_risk}
              score={data.hepatotox_score}
              rationale={data.hepatotox_rationale}
            />
            <RiskPanel
              icon={<AlertTriangle size={11} />}
              title="mutagenicity (Ames)"
              risk={data.ames_risk}
              score={data.ames_score}
              rationale={data.ames_rationale}
            />
            <RiskPanel
              icon={<Shield size={11} />}
              title="skin sensitization"
              risk={data.skin_sens_risk}
              rationale={data.skin_sens_rationale}
            />

            <div style={{ fontSize: 9, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", textAlign: "center",
              marginTop: 4, padding: "3px 6px",
              borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
            }}>
              QSAR-rule predictions · Aronov 2005 · Kazius 2005
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function Empty({ msg }: { msg: string }) {
  return (
    <div style={{ flex: 1, display: "grid", placeItems: "center",
      color: "var(--lys-text-faint)", fontSize: 10.5,
      fontFamily: "var(--lys-font-mono)", textAlign: "center" }}>{msg}</div>
  );
}

function SafetyTile({ value }: { value: number }) {
  const color = value >= 0.7 ? "#10b981" : value >= 0.4 ? "#d97706" : "#dc2626";
  const label = value >= 0.7 ? "CLEAN" : value >= 0.4 ? "CAUTION" : "FLAG";
  return (
    <div style={{
      padding: "8px 10px", borderRadius: 6,
      background: `${color}10`, borderLeft: `3px solid ${color}`,
      display: "flex", alignItems: "center", gap: 10,
    }}>
      <div style={{ fontSize: 24, fontWeight: 700, color, lineHeight: 1,
        fontFamily: "var(--lys-font-mono)" }}>
        {(value * 100).toFixed(0)}<span style={{ fontSize: 14 }}>%</span>
      </div>
      <div>
        <div style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
          letterSpacing: "0.06em", fontFamily: "var(--lys-font-mono)" }}>OVERALL SAFETY</div>
        <div style={{ fontSize: 11, fontWeight: 700, color,
          fontFamily: "var(--lys-font-mono)", letterSpacing: "0.04em" }}>{label}</div>
      </div>
    </div>
  );
}

function RiskPanel({ icon, title, risk, score, rationale }: {
  icon: React.ReactNode; title: string; risk: string;
  score?: number; rationale: string;
}) {
  const color = RISK_COLOR[risk] ?? "#9ca3af";
  return (
    <div style={{
      padding: "5px 8px", borderRadius: 4,
      background: `${color}06`,
      borderLeft: `3px solid ${color}`,
      display: "flex", flexDirection: "column", gap: 2,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5,
        fontSize: 10, fontFamily: "var(--lys-font-mono)" }}>
        <span style={{ color }}>{icon}</span>
        <span style={{ fontWeight: 600, color: "var(--lys-text)" }}>{title}</span>
        <span style={{ flex: 1 }} />
        <span style={{
          fontSize: 8.5, fontWeight: 700, padding: "1px 6px",
          borderRadius: 999, background: color, color: "white",
          letterSpacing: "0.04em", textTransform: "uppercase",
        }}>{risk}</span>
        {score !== undefined && (
          <span style={{ color, fontWeight: 700, fontSize: 9.5 }}>
            {(score*100).toFixed(0)}%
          </span>
        )}
      </div>
      <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
        fontFamily: "var(--lys-font-mono)", lineHeight: 1.3 }}>
        {rationale}
      </div>
    </div>
  );
}

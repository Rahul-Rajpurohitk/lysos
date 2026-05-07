/**
 * PropertiesCard — live medchem property dashboard.
 *
 * Computes the full RDKit descriptor stack for the current SMILES via
 * GET /workbench/molecule/properties?smiles=… and renders it as
 * scannable medchem-grade panels:
 *
 *   1. Hero — MW · logP · TPSA · QED  (4 big tiles)
 *   2. Lipinski Ro5 — 4-component check (MW < 500, logP < 5, HBD ≤ 5, HBA ≤ 10)
 *   3. Veber rules — rot. bonds ≤ 10 AND TPSA ≤ 140
 *   4. Atom composition — element counts (C / N / O / S / F / Cl / etc.)
 *   5. Rings + sp3 fraction
 *   6. Drug-class detector — SMARTS-matched class hints (β-lactam, quinolone, etc.)
 *
 * Auto-refreshes whenever the SMILES prop changes.
 */
import { useEffect, useState } from "react";
import { FlaskConical, RefreshCw } from "lucide-react";

interface MolProps {
  smiles: string;
  canonical_smiles: string;
  inchi_key: string;
  n_atoms: number;
  n_heavy_atoms: number;
  n_bonds: number;
  n_rings: number;
  n_aromatic_rings: number;
  n_rotatable_bonds: number;
  molecular_weight: number;
  logp: number;
  h_bond_donors: number;
  h_bond_acceptors: number;
  lipinski_violations: number;
  lipinski_pass: boolean;
  qed: number;
  sa_score: number;
  tpsa: number;
  fsp3: number;
  formal_charge: number;
  element_counts: Record<string, number>;
  veber_pass: boolean;
  detected_classes: string[];
}

interface Props {
  apiBase: string;
  smiles: string | null;
}

const ELEMENT_COLOR: Record<string, string> = {
  C: "#374151", N: "#2563eb", O: "#dc2626", S: "#ca8a04",
  F: "#16a34a", Cl: "#16a34a", Br: "#9a3412", I: "#7c3aed",
  P: "#ea580c", H: "#9ca3af",
};

export function PropertiesCard({ apiBase, smiles }: Props) {
  const [data, setData] = useState<MolProps | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  async function refresh() {
    if (!smiles) {
      setData(null);
      return;
    }
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/workbench/molecule/properties?smiles=${encodeURIComponent(smiles)}`);
      if (!r.ok) throw new Error(`http ${r.status}`);
      const d = await r.json();
      setData(d);
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [smiles, apiBase]);

  if (!smiles) {
    return (
      <div style={containerStyle}>
        <Header title="properties · live medchem stack" iconColor="#9ca3af" onRefresh={refresh} loading={false} />
        <div style={emptyStateStyle}>
          <FlaskConical size={20} style={{ opacity: 0.4 }} />
          <div>Pick or design a candidate to see Lipinski / QED / TPSA live</div>
        </div>
      </div>
    );
  }

  if (loading && !data) {
    return (
      <div style={containerStyle}>
        <Header title="properties · computing..." iconColor="#9ca3af" onRefresh={refresh} loading={true} />
        <div style={emptyStateStyle}>computing descriptors…</div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div style={containerStyle}>
        <Header title="properties · error" iconColor="#dc2626" onRefresh={refresh} loading={false} />
        <div style={{ padding: 12, fontSize: 10, color: "#dc2626" }}>{error}</div>
      </div>
    );
  }

  // Lipinski Rule of 5 criteria — clean format: NAME: VALUE (with the
  // threshold encoded in the tooltip rather than the chip text). Avoids
  // the awkward "MW < 500 78Da" string that previous renders produced.
  const lipChecks = [
    { name: "MW", pass: data.molecular_weight < 500, value: data.molecular_weight.toFixed(0), unit: "Da", threshold: "< 500 Da", explain: "Molecular weight — drug-like under 500 Da" },
    { name: "logP", pass: data.logp < 5, value: data.logp.toFixed(2), unit: "", threshold: "< 5", explain: "Partition coefficient — too high → poor solubility" },
    { name: "HBD", pass: data.h_bond_donors <= 5, value: String(data.h_bond_donors), unit: "", threshold: "≤ 5", explain: "H-bond donors (NH, OH) — too many → low membrane permeability" },
    { name: "HBA", pass: data.h_bond_acceptors <= 10, value: String(data.h_bond_acceptors), unit: "", threshold: "≤ 10", explain: "H-bond acceptors (N, O) — too many → low membrane permeability" },
  ];

  return (
    <div style={containerStyle}>
      <Header
        title={`properties · ${data.n_heavy_atoms} heavy · ${data.n_bonds} bonds`}
        iconColor={data.lipinski_pass ? "var(--lys-accent, #10b981)" : "#d97706"}
        onRefresh={refresh}
        loading={loading}
      />
      <div style={{ flex: 1, overflow: "auto", padding: 6, display: "flex",
        flexDirection: "column", gap: 5 }}>

        {/* HERO row — 4 inline mini-tiles, single horizontal strip */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 4 }}>
          <MiniTile label="MW" value={data.molecular_weight.toFixed(0)} unit="Da"
            color={data.molecular_weight < 500 ? "#10b981" : "#d97706"} />
          <MiniTile label="logP" value={data.logp.toFixed(2)} unit=""
            color={data.logp < 5 && data.logp > -2 ? "#10b981" : "#d97706"} />
          <MiniTile label="TPSA" value={data.tpsa.toFixed(0)} unit="Å²"
            color={data.tpsa <= 140 ? "#10b981" : "#d97706"} />
          <MiniTile label="QED" value={data.qed.toFixed(2)} unit=""
            color={data.qed >= 0.67 ? "#10b981" : data.qed >= 0.4 ? "#d97706" : "#dc2626"} />
        </div>

        {/* Rules row — Lipinski + Veber as inline chips */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
          <RulePill label="Lipinski" pass={data.lipinski_pass} sub={data.lipinski_pass ? "pass" : `${data.lipinski_violations} viol`} />
          <RulePill label="Veber" pass={data.veber_pass} sub={data.veber_pass ? "pass" : "fail"} />
          {lipChecks.map((c) => (
            <InlineRuleCheck key={c.name} {...c} />
          ))}
        </div>

        {/* Composition row — element pills + ring/fsp3/charge inline */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
          {Object.entries(data.element_counts).map(([sym, n]) => {
            const c = ELEMENT_COLOR[sym] ?? "#374151";
            return (
              <span key={sym} style={{
                padding: "1px 6px", borderRadius: 999,
                background: `${c}10`, border: `1px solid ${c}30`,
                fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
              }}>
                <span style={{ fontWeight: 700, color: c }}>{sym}</span>
                <span style={{ color: "var(--lys-text-faint)" }}>·{n}</span>
              </span>
            );
          })}
          <span style={{ width: 1, height: 14, background: "var(--lys-border-faint, rgba(0,0,0,0.08))", margin: "0 2px" }} />
          <InlineStat label="rings" value={`${data.n_rings}/${data.n_aromatic_rings}ar`} />
          <InlineStat label="fsp3" value={data.fsp3.toFixed(2)} />
          <InlineStat label="charge" value={data.formal_charge === 0 ? "0" : String(data.formal_charge)} />
          <InlineStat label="rot" value={String(data.n_rotatable_bonds)} />
        </div>

        {/* Drug-class detector — only renders when matches exist */}
        {data.detected_classes.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 3, alignItems: "center" }}>
            <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)",
              letterSpacing: "0.04em", textTransform: "uppercase",
              fontWeight: 600 }}>matches</span>
            {data.detected_classes.map((c) => (
              <span key={c} style={{
                padding: "1px 6px", borderRadius: 999,
                background: "rgba(168,85,247,0.10)",
                color: "#a855f7", fontSize: 9.5,
                fontFamily: "var(--lys-font-mono)", fontWeight: 600,
              }}>{c}</span>
            ))}
          </div>
        )}

        {/* Identifiers — single compact line, truncated SMILES + InChIKey */}
        <div style={{
          fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-dim)",
          padding: "3px 6px", borderRadius: 4,
          background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
          display: "flex", flexWrap: "wrap", gap: 8, alignItems: "baseline",
        }}>
          <span style={{ color: "var(--lys-text-faint)", fontSize: 8.5,
            letterSpacing: "0.04em", textTransform: "uppercase" }}>SMILES</span>
          <span style={{ wordBreak: "break-all", flex: 1, minWidth: 0,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
            color: "var(--lys-text)" }} title={data.canonical_smiles}>
            {data.canonical_smiles}
          </span>
          {data.sa_score > 0 && (
            <span style={{ flexShrink: 0, color: "var(--lys-text-faint)" }}>
              SA <span style={{ color: data.sa_score < 4 ? "#10b981" : data.sa_score < 6 ? "#d97706" : "#dc2626", fontWeight: 600 }}>
                {data.sa_score.toFixed(2)}
              </span>
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

const containerStyle: React.CSSProperties = {
  width: "100%", height: "100%", display: "flex", flexDirection: "column",
  background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
};

const emptyStateStyle: React.CSSProperties = {
  flex: 1, display: "flex", flexDirection: "column", gap: 6,
  alignItems: "center", justifyContent: "center",
  padding: 16, textAlign: "center",
  color: "var(--lys-text-faint)", fontSize: 11, fontFamily: "var(--lys-font-mono)",
};

function Header({ title, iconColor, onRefresh, loading }: { title: string; iconColor: string; onRefresh: () => void; loading: boolean }) {
  return (
    <div style={{
      padding: "5px 10px",
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      color: "var(--lys-text-faint)", letterSpacing: "0.06em",
      textTransform: "uppercase",
      borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      display: "flex", alignItems: "center", gap: 6,
    }}>
      <FlaskConical size={11} style={{ color: iconColor }} />
      <span>{title}</span>
      <span style={{ flex: 1 }} />
      <button type="button" onClick={onRefresh} disabled={loading}
        style={{ border: 0, background: "transparent", cursor: loading ? "wait" : "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
        <RefreshCw size={11} />
      </button>
    </div>
  );
}

// (legacy Tile/Section/RuleCheck/Stat helpers removed — replaced by
//  MiniTile/RulePill/InlineRuleCheck/InlineStat below for compact layout.)

// Compact in-line stat (single horizontal pill style)
function InlineStat({ label, value }: { label: string; value: string }) {
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 4,
      background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
      border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      display: "inline-flex", gap: 3, alignItems: "baseline",
    }}>
      <span style={{ color: "var(--lys-text-faint)", textTransform: "uppercase",
        letterSpacing: "0.04em", fontSize: 8.5 }}>{label}</span>
      <span style={{ color: "var(--lys-text)", fontWeight: 600 }}>{value}</span>
    </span>
  );
}

// Compact mini-tile for hero row (smaller than full Tile)
function MiniTile({ label, value, unit, color }: { label: string; value: string; unit: string; color: string }) {
  return (
    <div style={{
      padding: "5px 7px", borderRadius: 5,
      background: `${color}10`, borderLeft: `3px solid ${color}`,
      display: "flex", flexDirection: "column", gap: 0,
    }}>
      <div style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
        fontFamily: "var(--lys-font-mono)", letterSpacing: "0.04em",
        textTransform: "uppercase", lineHeight: 1.2 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, color, lineHeight: 1.2,
        fontFamily: "var(--lys-font-mono)" }}>
        {value}
        {unit && <span style={{ fontSize: 8, fontWeight: 500,
          color: "var(--lys-text-faint)", marginLeft: 2 }}>{unit}</span>}
      </div>
    </div>
  );
}

// Single-line rule-pass pill
function RulePill({ label, pass, sub }: { label: string; pass: boolean; sub?: string }) {
  const c = pass ? "#10b981" : "#d97706";
  return (
    <span style={{
      padding: "2px 7px", borderRadius: 999,
      background: `${c}12`, border: `1px solid ${c}40`,
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      color: c, fontWeight: 700,
      display: "inline-flex", alignItems: "center", gap: 3,
    }}>
      {pass ? "✓" : "⚠"} {label}
      {sub && <span style={{ fontWeight: 500, opacity: 0.85 }}>· {sub}</span>}
    </span>
  );
}

// Compact inline rule-check chip — tooltip carries the threshold + the
// medchem-grade explanation; chip itself stays tight: NAME · VALUE · ✓/⚠.
function InlineRuleCheck({ name, pass, value, unit, threshold, explain }: {
  name: string; pass: boolean; value: string; unit: string;
  threshold?: string; explain?: string;
}) {
  const c = pass ? "#10b981" : "#d97706";
  const title = explain
    ? `${explain}\nThreshold: ${threshold ?? ""}\nCurrent: ${value}${unit} — ${pass ? "passes" : "violates"} Lipinski.`
    : undefined;
  return (
    <span title={title} style={{
      padding: "2px 7px", borderRadius: 4,
      background: `${c}10`, border: `1px solid ${c}30`,
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      display: "inline-flex", alignItems: "center", gap: 4,
    }}>
      <span style={{ color: "var(--lys-text-dim)", fontWeight: 600 }}>{name}</span>
      <span style={{ color: c, fontWeight: 700 }}>{value}{unit}</span>
      <span style={{ color: c, fontSize: 9 }}>{pass ? "✓" : "⚠"}</span>
    </span>
  );
}

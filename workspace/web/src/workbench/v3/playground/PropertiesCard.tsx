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

// Element color palette — shared with AtomsRail and BottomPropertiesStrip.
// Composition rendering moved out of this component into the strip's
// Build-State column; keeping the constant here for future reuse.
// @ts-expect-error — kept for future reuse, currently unused.
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
      <div style={{ flex: 1, overflow: "hidden", display: "flex",
        flexDirection: "column" }}>

        {/* SECTION 1 · DRUG-LIKENESS · 4 hero KPI tiles with rule status
            baked into the tile color (green = passes Lipinski threshold,
            amber = violation, red = severe). Tooltip per tile shows the
            threshold + medchem rationale. */}
        <PropSection label="drug-likeness" subtitle="Lipinski Ro5 KPIs">
          {/* `auto-fit, minmax(64px, 1fr)` lets the 4 hero tiles wrap
              into 2×2 (or any other arrangement) when the parent column
              shrinks — instead of crushing each tile below the readable
              width or pushing the row off-screen. Each tile floors at
              64px so the value text stays legible. */}
          <div style={{ display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(64px, 1fr))",
            gap: 4, padding: "0 6px 4px" }}>
            <MiniTile label="MW" value={data.molecular_weight.toFixed(0)} unit="Da"
              color={data.molecular_weight < 500 ? "#10b981" : "#d97706"}
              tip={`Molecular weight (Daltons). Lipinski Ro5: < 500 Da. Currently ${data.molecular_weight.toFixed(1)} Da · ${data.molecular_weight < 500 ? "passes" : "fails"}.`} />
            <MiniTile label="logP" value={data.logp.toFixed(2)} unit=""
              color={data.logp < 5 && data.logp > -2 ? "#10b981" : "#d97706"}
              tip={`Octanol-water partition coefficient. Lipinski Ro5: < 5. Higher = more lipophilic / poorer solubility. Currently ${data.logp.toFixed(2)} · ${data.logp < 5 && data.logp > -2 ? "passes" : "fails"}.`} />
            <MiniTile label="TPSA" value={data.tpsa.toFixed(0)} unit="Å²"
              color={data.tpsa <= 140 ? "#10b981" : "#d97706"}
              tip={`Topological polar surface area. Veber: ≤ 140 Å² for oral bioavailability. Currently ${data.tpsa.toFixed(0)} Å² · ${data.tpsa <= 140 ? "passes" : "fails"}.`} />
            <MiniTile label="QED" value={data.qed.toFixed(2)} unit=""
              color={data.qed >= 0.67 ? "#10b981" : data.qed >= 0.4 ? "#d97706" : "#dc2626"}
              tip={`Quantitative Estimate of Drug-likeness (Bickerton 2012). Range [0,1]. ≥0.67 = drug-like, 0.4-0.67 = passable, <0.4 = poor. Currently ${data.qed.toFixed(2)}.`} />
          </div>
        </PropSection>

        {/* SECTION 2 · RULE COMPLIANCE · explicit pass/fail summary for
            Lipinski + Veber + per-rule breakdown (only shown if any
            violation exists, to keep clean state minimal). */}
        <PropSection
          label="rule compliance"
          subtitle={
            data.lipinski_pass && data.veber_pass
              ? "Lipinski Ro5 + Veber · all pass"
              : `${data.lipinski_violations} Lipinski viol${data.lipinski_violations === 1 ? "" : "s"}${data.veber_pass ? "" : " · Veber fail"}`
          }>
          <div style={{ padding: "0 6px 4px",
            display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
            <RulePill label="Lipinski Ro5" pass={data.lipinski_pass}
              sub={data.lipinski_pass ? `4/4 pass` : `${4 - data.lipinski_violations}/4 pass`} />
            <RulePill label="Veber" pass={data.veber_pass}
              sub={data.veber_pass ? "rotB ≤ 10 · TPSA ≤ 140" : "rotB or TPSA fail"} />
            {/* Per-rule chips — only rendered when there's a Lipinski
                violation, so the clean state stays minimal. */}
            {!data.lipinski_pass && lipChecks.map((c) => (
              <InlineRuleCheck key={c.name} {...c} />
            ))}
          </div>
        </PropSection>

        {/* COMPOSITION moved to the BUILD STATE column of the parent
            BottomPropertiesStrip — small content (1-3 element chips) sits
            better next to the Build State counts than as its own row in
            the main properties column. Frees vertical space here so
            DRUG-LIKENESS + RULE COMPLIANCE + STRUCTURE + IDENTIFIERS
            all fit one-shot without internal scroll. */}

        {/* SECTION 4 · STRUCTURE · structural / topological metrics. */}
        <PropSection label="structure" subtitle="rings · sp³ · charge · rotatable">
          <div style={{ padding: "0 6px 4px",
            display: "flex", flexWrap: "wrap", gap: 4, alignItems: "center" }}>
            <InlineStat label="rings"
              value={`${data.n_rings}/${data.n_aromatic_rings}ar`}
              tip={`${data.n_rings} ring${data.n_rings === 1 ? "" : "s"} total · ${data.n_aromatic_rings} aromatic`} />
            <InlineStat label="fsp3" value={data.fsp3.toFixed(2)}
              tip={`Fraction of sp³-hybridized carbons. Higher = more 3D / less flat. Drug-like ≥ 0.25.`} />
            <InlineStat label="charge"
              value={data.formal_charge === 0 ? "0" : (data.formal_charge > 0 ? `+${data.formal_charge}` : String(data.formal_charge))}
              tip={data.formal_charge === 0
                ? "Net-neutral · most drugs"
                : `Net formal charge ${data.formal_charge > 0 ? "+" : ""}${data.formal_charge} · ionizable / counterion needed`} />
            <InlineStat label="rot" value={String(data.n_rotatable_bonds)}
              tip={`${data.n_rotatable_bonds} rotatable bond${data.n_rotatable_bonds === 1 ? "" : "s"}. Veber: ≤ 10 for oral bioavailability.`} />
          </div>
        </PropSection>

        {/* SECTION 5 · DRUG-CLASS MATCHES · only renders when matches exist. */}
        {data.detected_classes.length > 0 && (
          <PropSection label="drug-class matches"
            subtitle={`${data.detected_classes.length} SMARTS pattern hit${data.detected_classes.length === 1 ? "" : "s"}`}>
            <div style={{ padding: "0 6px 4px",
              display: "flex", flexWrap: "wrap", gap: 3, alignItems: "center" }}>
              {data.detected_classes.map((c) => (
                <span key={c}
                  title={`Substructure of class "${c}" detected — likely contributes to mechanism / SAR profile.`}
                  style={{
                  padding: "1px 7px", borderRadius: 999,
                  background: "rgba(168,85,247,0.12)",
                  border: "1px solid rgba(168,85,247,0.32)",
                  color: "#a855f7", fontSize: 10,
                  fontFamily: "var(--lys-font-mono)", fontWeight: 600,
                }}>{c}</span>
              ))}
            </div>
          </PropSection>
        )}

        {/* SECTION 6 · IDENTIFIERS · canonical SMILES + SA score.
            SMILES wraps on long strings (break-all on this monospace
            string so it never overflows its parent column).  Click to
            copy. SA score sits below to keep the row compact. */}
        <PropSection label="identifiers" subtitle="canonical · synth-access">
          <div style={{ padding: "2px 6px 6px",
            display: "flex", flexDirection: "column", gap: 4,
            fontSize: 10, fontFamily: "var(--lys-font-mono)" }}>
            <div style={{ display: "flex", gap: 8, alignItems: "baseline" }}>
              <span style={{ color: "var(--lys-text-faint)", fontSize: 8.5,
                letterSpacing: "0.04em", textTransform: "uppercase",
                flexShrink: 0 }}>SMILES</span>
              <button
                type="button"
                title={`${data.canonical_smiles} — click to copy`}
                onClick={() => {
                  try { void navigator.clipboard.writeText(data.canonical_smiles); } catch {/*noop*/}
                }}
                style={{
                  flex: 1, minWidth: 0,
                  textAlign: "left",
                  border: 0, padding: 0, background: "transparent",
                  cursor: "pointer", color: "var(--lys-text)",
                  fontFamily: "inherit", fontSize: 10,
                  // Wrap long SMILES instead of clipping. Important
                  // for real candidates which can hit 80+ chars.
                  wordBreak: "break-all", whiteSpace: "normal",
                  lineHeight: 1.35,
                }}>
                {data.canonical_smiles}
              </button>
            </div>
            {data.sa_score > 0 && (
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <span title={`Synthetic Accessibility Score (Ertl 2009). 1=easy, 10=hard. ${data.sa_score < 4 ? "Easy synthesis." : data.sa_score < 6 ? "Moderate." : "Difficult."}`}
                  style={{ flexShrink: 0, color: "var(--lys-text-faint)",
                    fontSize: 9 }}>
                  SA <span style={{ color: data.sa_score < 4 ? "#10b981" : data.sa_score < 6 ? "#d97706" : "#dc2626", fontWeight: 700 }}>
                    {data.sa_score.toFixed(2)}
                  </span>
                </span>
              </div>
            )}
          </div>
        </PropSection>
      </div>
    </div>
  );
}

// Section header with mono uppercase label + faint subtitle. Same
// vocabulary as the right-rail BondsRail / atoms-rail section headers.
// Click the header to toggle open/closed. Default open. Each section
// remembers its state in localStorage scoped by its `label` so the user
// can collapse Build State once and have it stay collapsed across
// reloads.
function PropSection({ label, subtitle, children, defaultOpen = true }: {
  label: string; subtitle?: string; children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const storageKey = `lys-prop-section:${label}`;
  const [open, setOpen] = useState<boolean>(() => {
    try {
      const v = localStorage.getItem(storageKey);
      if (v === "0") return false;
      if (v === "1") return true;
    } catch {/*noop*/}
    return defaultOpen;
  });
  const toggle = () => {
    setOpen((o) => {
      const next = !o;
      try { localStorage.setItem(storageKey, next ? "1" : "0"); } catch {/*noop*/}
      return next;
    });
  };
  return (
    <div style={{ display: "flex", flexDirection: "column" }}>
      <button
        type="button"
        onClick={toggle}
        title={`${open ? "Collapse" : "Expand"} ${label}`}
        style={{
          all: "unset", cursor: "pointer",
          padding: "5px 8px 3px",
          fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em", textTransform: "uppercase",
          display: "flex", alignItems: "center", gap: 5,
          background: "var(--lys-bg, #fafafa)",
        }}
        onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--lys-text)"; }}
        onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.color = "var(--lys-text-faint)"; }}
      >
        <span style={{ fontSize: 7, opacity: 0.6, width: 7 }}>{open ? "▼" : "▶"}</span>
        <span style={{ fontWeight: 700 }}>{label}</span>
        {subtitle && (
          <>
            <span style={{ flex: 1 }} />
            <span style={{ opacity: 0.65, textTransform: "none",
              letterSpacing: 0, fontFamily: "var(--lys-font-body)" }}>
              {subtitle}
            </span>
          </>
        )}
      </button>
      {open && children}
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
function InlineStat({ label, value, tip }: { label: string; value: string; tip?: string }) {
  return (
    <span title={tip} style={{
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
function MiniTile({ label, value, unit, color, tip }: {
  label: string; value: string; unit: string; color: string; tip?: string;
}) {
  return (
    <div title={tip} style={{
      padding: "5px 7px", borderRadius: 5,
      background: `${color}10`, borderLeft: `3px solid ${color}`,
      display: "flex", flexDirection: "column", gap: 0,
      cursor: tip ? "help" : "default",
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

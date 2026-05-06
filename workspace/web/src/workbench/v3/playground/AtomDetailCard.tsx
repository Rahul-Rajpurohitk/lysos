/**
 * AtomDetailCard — beautiful atom inspector that LIVES on the dashboard.
 *
 * Distinct from ChemKnowledgeCard (which appears as a popover on click).
 * This card subscribes to whichever atom is currently HOVERED in the
 * 2D builder and shows its full chemistry context, always-on.
 *
 * Sections:
 *   1. Header — element symbol (big, element-color) + atom_idx + ring/aromatic badges
 *   2. Valence — explicit / implicit / free-H slots (visual bar)
 *   3. Neighbors — list of bonded atoms with bond order pills
 *   4. SAR notes — curated drug-corpus hits keyed off the element
 *   5. Allowed edits — quick-edit buttons (mirrors ChemKnowledgeCard)
 *
 * Empty state: gentle prompt to hover an atom in the 2D builder.
 */
import { useEffect, useState } from "react";
import { Atom, Sparkles } from "lucide-react";

interface AtomNeighbor {
  idx: number;
  element: string;
  bond: string;
}

interface AllowedAttachment {
  label: string;
  op: string;
  new_element?: string;
  functional_group?: string;
  note?: string;
}

interface SARNote {
  drug: string;
  position: string;
  effect: string;
}

interface AtomContext {
  smiles: string;
  atom_idx: number;
  element: string;
  formal_charge: number;
  is_aromatic: boolean;
  in_ring: boolean;
  ring_size: number;
  explicit_valence: number;
  implicit_valence: number;
  n_hydrogens: number;
  neighbors: AtomNeighbor[];
  allowed_attachments: AllowedAttachment[];
  sar_notes: SARNote[];
}

interface Props {
  apiBase: string;
  smiles: string | null;
  atomIdx: number | null;
  pathogen?: string;
  onApplyEdit?: (op: string, params: { new_element?: string; functional_group?: string; label: string }) => void;
}

const ELEMENT_COLOR: Record<string, string> = {
  C: "#374151",
  N: "#2563eb",
  O: "#dc2626",
  S: "#ca8a04",
  F: "#16a34a",
  Cl: "#16a34a",
  Br: "#9a3412",
  I: "#7c3aed",
  P: "#ea580c",
  H: "#9ca3af",
};

const BOND_GLYPH: Record<string, string> = {
  single: "—",
  double: "=",
  triple: "≡",
  aromatic: "⤴",
};

function smilesToB64(s: string): string {
  if (typeof window === "undefined") return "";
  return window.btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function AtomDetailCard({ apiBase, smiles, atomIdx, pathogen, onApplyEdit }: Props) {
  const [ctx, setCtx] = useState<AtomContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>("");

  useEffect(() => {
    if (!smiles || atomIdx == null) {
      setCtx(null);
      setError("");
      return;
    }
    const b64 = smilesToB64(smiles);
    let cancelled = false;
    setLoading(true);
    setError("");
    const target = pathogen ? `?target=${encodeURIComponent(pathogen)}` : "";
    fetch(`${apiBase}/workbench/chem/atom/${b64}/${atomIdx}${target}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(`http ${r.status}`)))
      .then((d: AtomContext) => { if (!cancelled) setCtx(d); })
      .catch((err) => { if (!cancelled) setError(String(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [apiBase, smiles, atomIdx, pathogen]);

  // ── empty state
  if (!smiles || atomIdx == null) {
    return (
      <div style={{
        width: "100%", height: "100%",
        display: "flex", flexDirection: "column",
        background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
      }}>
        <Header label="atom · hover one in 2D builder" iconColor="#9ca3af" />
        <div style={{
          flex: 1, display: "grid", placeItems: "center",
          color: "var(--lys-text-faint)", fontSize: 11, padding: 16,
          fontFamily: "var(--lys-font-mono)", textAlign: "center",
        }}>
          <div>
            <div style={{ fontSize: 24, marginBottom: 6, opacity: 0.4 }}>⚛</div>
            <div>Hover any atom in the 2D builder<br />→ details appear here live</div>
          </div>
        </div>
      </div>
    );
  }

  if (loading && !ctx) {
    return (
      <div style={{ width: "100%", height: "100%",
        display: "flex", flexDirection: "column",
        background: "var(--lys-bg-2, #ffffff)" }}>
        <Header label={`atom ${atomIdx} · loading...`} iconColor="#9ca3af" />
        <div style={{ flex: 1, display: "grid", placeItems: "center",
          fontSize: 10, color: "var(--lys-text-faint)" }}>fetching context...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ width: "100%", height: "100%",
        display: "flex", flexDirection: "column",
        background: "var(--lys-bg-2, #ffffff)" }}>
        <Header label={`atom ${atomIdx} · error`} iconColor="#dc2626" />
        <div style={{ flex: 1, padding: 12, fontSize: 10, color: "#dc2626",
          fontFamily: "var(--lys-font-mono)" }}>{error}</div>
      </div>
    );
  }

  if (!ctx) return null;

  const elColor = ELEMENT_COLOR[ctx.element] ?? "#374151";
  const totalDeg = ctx.neighbors.length + ctx.n_hydrogens;
  const valencePct = ctx.n_hydrogens > 0 ? (ctx.n_hydrogens / Math.max(1, totalDeg)) * 100 : 0;

  return (
    <div style={{
      width: "100%", height: "100%",
      display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      <Header label={`atom ${atomIdx} · ${ctx.neighbors.length} bonds · ${ctx.n_hydrogens} H`} iconColor={elColor} />

      <div style={{ flex: 1, overflow: "auto", padding: 8, display: "flex",
        flexDirection: "column", gap: 8 }}>

        {/* ── 1. Element + badges */}
        <div style={{ display: "flex", alignItems: "center", gap: 10,
          padding: "8px 10px", background: `${elColor}10`,
          borderRadius: 6, borderLeft: `3px solid ${elColor}` }}>
          <div style={{
            width: 44, height: 44, borderRadius: "50%",
            background: elColor, color: "white",
            display: "grid", placeItems: "center",
            fontWeight: 700, fontSize: 22, fontFamily: "var(--lys-font-mono)",
          }}>{ctx.element}</div>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 2 }}>
            <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
              {ctx.is_aromatic && <Badge color="#a855f7">aromatic</Badge>}
              {ctx.in_ring && <Badge color="#0891b2">ring · {ctx.ring_size}</Badge>}
              {ctx.formal_charge !== 0 && (
                <Badge color="#dc2626">{ctx.formal_charge > 0 ? "+" : ""}{ctx.formal_charge} charge</Badge>
              )}
              {ctx.n_hydrogens === 0 && <Badge color="#6b7280">saturated</Badge>}
            </div>
            <div style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)" }}>
              valence: explicit={ctx.explicit_valence} · implicit={ctx.implicit_valence}
            </div>
          </div>
        </div>

        {/* ── 2. Free-H bar */}
        {ctx.n_hydrogens > 0 && (
          <div>
            <div style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", marginBottom: 3,
              display: "flex", justifyContent: "space-between" }}>
              <span>FREE-H slots (attach points)</span>
              <span style={{ color: "var(--lys-accent)", fontWeight: 600 }}>
                {ctx.n_hydrogens} of {totalDeg}
              </span>
            </div>
            <div style={{ height: 6, borderRadius: 3, background: "var(--lys-border-faint, rgba(0,0,0,0.05))",
              overflow: "hidden" }}>
              <div style={{
                height: "100%", width: `${valencePct}%`,
                background: "var(--lys-accent, #10b981)",
                transition: "width 200ms ease",
              }} />
            </div>
          </div>
        )}

        {/* ── 3. Neighbors */}
        {ctx.neighbors.length > 0 && (
          <div>
            <div style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", marginBottom: 3,
              letterSpacing: "0.04em", textTransform: "uppercase" }}>
              neighbors ({ctx.neighbors.length})
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {ctx.neighbors.map((n) => {
                const nc = ELEMENT_COLOR[n.element] ?? "#374151";
                return (
                  <div key={n.idx} style={{
                    display: "flex", alignItems: "center", gap: 4,
                    padding: "2px 6px", borderRadius: 999,
                    border: `1px solid ${nc}40`, background: `${nc}08`,
                    fontFamily: "var(--lys-font-mono)", fontSize: 10,
                  }}>
                    <span style={{ color: "var(--lys-text-faint)", fontSize: 9 }}>
                      {BOND_GLYPH[n.bond] ?? "—"}
                    </span>
                    <span style={{ fontWeight: 700, color: nc }}>{n.element}</span>
                    <span style={{ color: "var(--lys-text-faint)", fontSize: 9 }}>#{n.idx}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* ── 4. SAR notes */}
        {ctx.sar_notes.length > 0 && (
          <div>
            <div style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", marginBottom: 3,
              letterSpacing: "0.04em", textTransform: "uppercase",
              display: "flex", alignItems: "center", gap: 4 }}>
              <Sparkles size={10} style={{ color: "#a855f7" }} />
              SAR · {ctx.sar_notes.length} drug{ctx.sar_notes.length !== 1 ? "s" : ""}
            </div>
            {ctx.sar_notes.slice(0, 3).map((s, i) => (
              <div key={i} style={{
                padding: "4px 8px", marginBottom: 3,
                background: "rgba(168,85,247,0.06)", borderRadius: 4,
                borderLeft: "2px solid #a855f7",
                fontSize: 10, lineHeight: 1.35,
              }}>
                <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 1 }}>
                  <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                    color: "#a855f7", fontSize: 10.5 }}>{s.drug}</span>
                  <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 9,
                    color: "var(--lys-text-faint)" }}>@{s.position}</span>
                </div>
                <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)" }}>
                  {s.effect}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── 5. Quick-edit buttons */}
        {onApplyEdit && ctx.allowed_attachments.length > 0 && (
          <div>
            <div style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", marginBottom: 3,
              letterSpacing: "0.04em", textTransform: "uppercase" }}>
              quick edits ({ctx.allowed_attachments.length})
            </div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
              {ctx.allowed_attachments.slice(0, 8).map((a, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => onApplyEdit(a.op, {
                    new_element: a.new_element,
                    functional_group: a.functional_group,
                    label: a.label,
                  })}
                  style={{
                    border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
                    background: "var(--lys-bg-3, rgba(0,0,0,0.02))",
                    color: "var(--lys-text)", padding: "3px 8px",
                    borderRadius: 4, fontSize: 10,
                    fontFamily: "var(--lys-font-mono)", cursor: "pointer",
                    transition: "background 100ms",
                  }}
                  title={a.note}
                  onMouseOver={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--lys-accent, #10b981)20"; }}
                  onMouseOut={(e) => { (e.currentTarget as HTMLElement).style.background = "var(--lys-bg-3, rgba(0,0,0,0.02))"; }}
                >
                  {a.label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Header({ label, iconColor }: { label: string; iconColor: string }) {
  return (
    <div style={{
      padding: "5px 10px",
      fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
      color: "var(--lys-text-faint)", letterSpacing: "0.06em",
      textTransform: "uppercase",
      borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      display: "flex", alignItems: "center", gap: 6,
    }}>
      <Atom size={11} style={{ color: iconColor }} />
      <span>{label}</span>
    </div>
  );
}

function Badge({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span style={{
      fontSize: 8.5, padding: "1px 5px", borderRadius: 999,
      background: `${color}18`, color, fontWeight: 700,
      fontFamily: "var(--lys-font-mono)", letterSpacing: "0.04em",
      textTransform: "uppercase",
    }}>{children}</span>
  );
}

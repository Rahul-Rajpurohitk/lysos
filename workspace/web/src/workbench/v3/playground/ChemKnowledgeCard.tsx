/**
 * ChemKnowledgeCard — popover for an atom in the 2D builder.
 *
 * GET /workbench/chem/atom/{smi64}/{atom_idx} returns:
 *   element, valence, neighbours, allowed_attachments[], sar_notes[]
 *
 * We render a compact card with three sections:
 *   - Atom header: element, ring/aromatic flags, valence + free-H
 *   - Allowed attachments: clickable chips (pick to apply)
 *   - SAR notes: bullet list with drug + position + effect
 */
import { useEffect, useState } from "react";
import { X as IconX, Atom } from "lucide-react";

interface AllowedAttachment {
  label: string;
  op: string;
  new_element?: string;
  functional_group?: string;
  note?: string;
}

interface AtomNeighbor {
  idx: number;
  element: string;
  bond: string;
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
  smiles: string;
  atomIdx: number;
  onApply: (op: string, params: { new_element?: string; functional_group?: string; label: string }) => void;
  onClose: () => void;
}

function smilesToB64(s: string): string {
  return window.btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function ChemKnowledgeCard({ apiBase, smiles, atomIdx, onApply, onClose }: Props) {
  const [ctx, setCtx] = useState<AtomContext | null>(null);
  const [err, setErr] = useState<string>("");

  useEffect(() => {
    setCtx(null);
    setErr("");
    const b64 = smilesToB64(smiles);
    fetch(`${apiBase}/workbench/chem/atom/${b64}/${atomIdx}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setCtx)
      .catch((e) => setErr(`load failed: ${e}`));
  }, [smiles, atomIdx, apiBase]);

  return (
    <div style={{
      width: 280,
      maxHeight: 380,
      overflow: "auto",
      background: "var(--lys-bg-2, #ffffff)",
      borderRadius: 8,
      boxShadow: "0 8px 24px rgba(15,23,42,0.18), 0 1px 3px rgba(15,23,42,0.10)",
      fontSize: 11,
      fontFamily: "var(--lys-font-body)",
      color: "var(--lys-text)",
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "6px 10px",
        background: "var(--lys-bg, #fafafa)",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      }}>
        <Atom size={12} style={{ color: "var(--lys-accent)" }} />
        <span style={{
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em",
          textTransform: "uppercase",
        }}>
          atom · idx {atomIdx}
        </span>
        <span style={{ flex: 1 }} />
        <button
          type="button"
          onClick={onClose}
          style={{
            border: 0, background: "transparent", cursor: "pointer",
            padding: 0, color: "var(--lys-text-faint)",
            display: "grid", placeItems: "center",
          }}
        >
          <IconX size={11} />
        </button>
      </div>

      {!ctx && !err && (
        <div style={{ padding: 10, color: "var(--lys-text-faint)", fontSize: 10.5 }}>loading…</div>
      )}
      {err && (
        <div style={{ padding: 10, color: "#dc2626", fontSize: 10.5, fontFamily: "var(--lys-font-mono)" }}>{err}</div>
      )}

      {ctx && (
        <>
          {/* Atom info */}
          <div style={{ padding: "8px 10px", display: "flex", flexDirection: "column", gap: 3 }}>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
              <span style={{
                fontFamily: "var(--lys-font-mono)",
                fontSize: 16,
                fontWeight: 700,
                color: "var(--lys-accent)",
              }}>
                {ctx.element}
              </span>
              {ctx.is_aromatic && (
                <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)", padding: "1px 4px", borderRadius: 3, background: "rgba(16,185,129,0.10)", color: "var(--lys-accent)" }}>arom</span>
              )}
              {ctx.in_ring && (
                <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)", padding: "1px 4px", borderRadius: 3, background: "rgba(59,130,246,0.10)", color: "#1e40af" }}>ring{ctx.ring_size}</span>
              )}
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)", color: "var(--lys-text-faint)" }}>
                val {ctx.explicit_valence} · H {ctx.n_hydrogens}
              </span>
            </div>
            <div style={{
              fontSize: 9.5,
              fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-faint)",
            }}>
              neighbors: {ctx.neighbors.map((n) => `${n.element}@${n.idx}(${n.bond[0]})`).join(" · ") || "none"}
            </div>
          </div>

          {/* Allowed attachments */}
          {ctx.allowed_attachments.length > 0 ? (
            <div style={{
              padding: "0 10px 8px",
              borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
            }}>
              <div style={{
                fontSize: 9,
                fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)",
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                margin: "6px 0 4px",
              }}>
                allowed attachments · {ctx.allowed_attachments.length}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                {ctx.allowed_attachments.map((a, i) => (
                  <button
                    key={i}
                    type="button"
                    title={a.note}
                    onClick={() => onApply(a.op, {
                      new_element: a.new_element,
                      functional_group: a.functional_group,
                      label: a.label,
                    })}
                    style={{
                      border: 0,
                      background: "rgba(16, 185, 129, 0.08)",
                      color: "var(--lys-accent)",
                      fontFamily: "var(--lys-font-mono)",
                      fontSize: 10,
                      fontWeight: 600,
                      padding: "3px 7px",
                      borderRadius: 999,
                      cursor: "pointer",
                      transition: "background 0.12s, transform 0.12s",
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.background = "rgba(16, 185, 129, 0.18)";
                      e.currentTarget.style.transform = "translateY(-1px)";
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.background = "rgba(16, 185, 129, 0.08)";
                      e.currentTarget.style.transform = "translateY(0)";
                    }}
                  >
                    {a.label}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div style={{
              padding: "6px 10px",
              fontSize: 10,
              color: "var(--lys-text-faint)",
              borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
            }}>
              No free attachment site (atom is fully bonded).
            </div>
          )}

          {/* SAR notes */}
          {ctx.sar_notes.length > 0 && (
            <div style={{
              padding: "0 10px 8px",
              borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
            }}>
              <div style={{
                fontSize: 9,
                fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)",
                letterSpacing: "0.06em",
                textTransform: "uppercase",
                margin: "6px 0 4px",
              }}>
                SAR notes · curated corpus
              </div>
              <ul style={{ margin: 0, padding: "0 0 0 14px", listStyle: "disc", color: "var(--lys-text-dim)", fontSize: 10 }}>
                {ctx.sar_notes.map((n, i) => (
                  <li key={i}>
                    <span style={{ color: "var(--lys-accent)", fontFamily: "var(--lys-font-mono)" }}>{n.drug}</span>
                    <span> @ {n.position}: </span>
                    <span style={{ fontStyle: "italic" }}>{n.effect}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </div>
  );
}

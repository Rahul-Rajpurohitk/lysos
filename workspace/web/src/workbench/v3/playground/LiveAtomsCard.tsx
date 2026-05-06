/**
 * LiveAtomsCard — atom-level CRUD list backed by /workbench/playground.
 *
 * Reads:
 *   GET /workbench/playground/molecule/{mid}/state
 *   → { molecule, atoms[], bonds[], score }
 *
 * Each atom row is a tiny inspector + edit chip:
 *   [idx] [element] [valence/H] [arom·ring badge] [+CH₃] [→N] [→O]
 *
 * Edits go through the WebSocket via sendEdit so they're persisted to
 * the SQLite edit log + broadcast to all subscribers (other clients +
 * agents).
 */
import { useEffect, useState } from "react";
import { Atom as AtomIcon, RefreshCw } from "lucide-react";

interface AtomRecord {
  atom_idx: number;
  element: string;
  formal_charge: number;
  n_hydrogens: number;
  free_valence: number;
  is_aromatic: number | boolean;
  in_ring: number | boolean;
  ring_size: number;
  x: number; y: number; z: number;
}

interface MoleculeRecord {
  id: string;
  smiles: string;
  canonical_smiles: string;
  formula: string;
  mw: number;
  composite_score: number;
}

interface Props {
  apiBase: string;
  moleculeId: string | null;
  smiles: string | null;
  onApplyEdit?: (edit: any) => void;   // delegates to live ws
  onSelectAtom?: (idx: number) => void; // hover sync
}

const QUICK_OPS = [
  { label: "+CH₃", op: "add_methyl" },
  { label: "→N",   op: "swap_element", new_element: "N" },
  { label: "→O",   op: "swap_element", new_element: "O" },
  { label: "→F",   op: "swap_element", new_element: "F" },
];

export function LiveAtomsCard({ apiBase, moleculeId, smiles, onApplyEdit, onSelectAtom }: Props) {
  const [mol, setMol] = useState<MoleculeRecord | null>(null);
  const [atoms, setAtoms] = useState<AtomRecord[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  async function refresh() {
    if (!moleculeId) {
      setMol(null); setAtoms([]); return;
    }
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/playground/molecule/${moleculeId}/state`);
      if (!r.ok) throw new Error(`http ${r.status}`);
      const d = await r.json();
      setMol(d.molecule);
      setAtoms(d.atoms ?? []);
      setErr("");
    } catch (e: any) {
      setErr(`load failed: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }

  // Auto-materialize from SMILES if no moleculeId yet
  async function materialize() {
    if (!smiles) return;
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/playground/sessions/active/molecule`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ smiles, created_by: "user" }),
      });
      if (!r.ok) throw new Error(`http ${r.status}`);
      const d = await r.json();
      // Now load full state
      const r2 = await fetch(`${apiBase}/workbench/playground/molecule/${d.molecule_id}/state`);
      if (r2.ok) {
        const dd = await r2.json();
        setMol(dd.molecule); setAtoms(dd.atoms ?? []);
      }
    } catch (e: any) {
      setErr(`materialize failed: ${e?.message ?? e}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    if (moleculeId) refresh();
    else if (smiles) materialize();
    else { setMol(null); setAtoms([]); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [moleculeId, smiles]);

  const elementColor = (e: string) => {
    if (e === "C") return "var(--lys-text)";
    if (e === "N") return "#3b82f6";
    if (e === "O") return "#dc2626";
    if (e === "F") return "#10b981";
    if (e === "Cl") return "#16a34a";
    if (e === "S") return "#d97706";
    if (e === "P") return "#a855f7";
    return "var(--lys-text-dim)";
  };

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      <div style={{
        padding: "5px 10px",
        fontSize: 9.5,
        fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)",
        letterSpacing: "0.06em",
        textTransform: "uppercase",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <AtomIcon size={11} />
        <span>atoms · {atoms.length}</span>
        {mol && (
          <span style={{ color: "var(--lys-text-dim)", textTransform: "none", letterSpacing: 0 }}>
            · {mol.formula} · {mol.mw.toFixed(1)} Da
          </span>
        )}
        <span style={{ flex: 1 }} />
        <button
          type="button" onClick={refresh}
          disabled={loading}
          title="Refresh"
          style={{
            border: 0, background: "transparent", cursor: "pointer",
            padding: 2, color: "var(--lys-text-faint)",
          }}
        >
          <RefreshCw size={11} className={loading ? "lys-spin" : ""} />
        </button>
      </div>

      {err && (
        <div style={{ padding: "6px 10px", color: "#dc2626", fontSize: 10, fontFamily: "var(--lys-font-mono)" }}>{err}</div>
      )}

      {!atoms.length && !loading && (
        <div style={{
          flex: 1, display: "grid", placeItems: "center",
          color: "var(--lys-text-faint)", fontSize: 11, fontFamily: "var(--lys-font-mono)",
          padding: 12, textAlign: "center",
        }}>
          {smiles ? "materializing…" : "no molecule yet · /design or pick a candidate"}
        </div>
      )}

      <div style={{ flex: 1, overflow: "auto" }}>
        {atoms.map((a) => {
          const isAromatic = !!a.is_aromatic;
          const inRing = !!a.in_ring;
          const eltColor = elementColor(a.element);
          return (
            <div
              key={a.atom_idx}
              onMouseEnter={() => { setHoverIdx(a.atom_idx); onSelectAtom?.(a.atom_idx); }}
              onMouseLeave={() => setHoverIdx(null)}
              style={{
                display: "grid",
                gridTemplateColumns: "32px 28px 1fr auto",
                gap: 6,
                alignItems: "center",
                padding: "4px 10px",
                background: hoverIdx === a.atom_idx ? "rgba(16,185,129,0.06)" : "transparent",
                borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
                fontSize: 10.5,
                fontFamily: "var(--lys-font-mono)",
              }}
            >
              <span style={{ color: "var(--lys-text-faint)", fontWeight: 600 }}>{a.atom_idx}</span>
              <span style={{ color: eltColor, fontWeight: 700, fontSize: 12 }}>{a.element}</span>
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 4,
                color: "var(--lys-text-dim)", fontSize: 9.5,
              }}>
                {a.n_hydrogens > 0 && <span>H{a.n_hydrogens}</span>}
                {isAromatic && (
                  <span style={{
                    fontSize: 8, padding: "1px 3px", borderRadius: 2,
                    background: "rgba(16,185,129,0.10)", color: "var(--lys-accent)",
                  }}>arom</span>
                )}
                {inRing && (
                  <span style={{
                    fontSize: 8, padding: "1px 3px", borderRadius: 2,
                    background: "rgba(59,130,246,0.10)", color: "#1e40af",
                  }}>r{a.ring_size}</span>
                )}
                {a.formal_charge !== 0 && (
                  <span style={{
                    fontSize: 8, padding: "1px 3px", borderRadius: 2,
                    background: "rgba(220,38,38,0.10)", color: "#dc2626",
                  }}>{a.formal_charge > 0 ? `+${a.formal_charge}` : a.formal_charge}</span>
                )}
              </span>
              {a.n_hydrogens > 0 && hoverIdx === a.atom_idx && (
                <span style={{ display: "flex", gap: 2 }}>
                  {QUICK_OPS.map((q) => (
                    <button
                      key={q.label}
                      type="button"
                      title={q.label}
                      onClick={() => onApplyEdit?.({
                        kind: q.op,
                        atom_idx: a.atom_idx,
                        new_element: q.new_element,
                      })}
                      style={{
                        border: 0,
                        background: "rgba(16,185,129,0.08)",
                        color: "var(--lys-accent)",
                        padding: "1px 5px",
                        borderRadius: 3,
                        fontFamily: "inherit",
                        fontSize: 9,
                        fontWeight: 600,
                        cursor: "pointer",
                      }}
                    >
                      {q.label}
                    </button>
                  ))}
                </span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

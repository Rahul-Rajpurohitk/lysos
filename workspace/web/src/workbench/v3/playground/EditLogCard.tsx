/**
 * EditLogCard — DB-backed live view of every MoleculeEdit row.
 *
 * Reads /workbench/playground/sessions/{sid}/edits. Each row is a
 * persisted SQLite record with ts, actor, op, atom_idx, result_smiles.
 * Auto-refreshes when the parent feeds new rows.
 *
 * This is the proof-of-life for the system: every click in the canvas
 * appears here as a row, persisted permanently, replay-friendly.
 */
import { Clock, ArrowRight, RefreshCw } from "lucide-react";

interface EditRow {
  id: string;
  ts: number;
  session_id: string;
  parent_molecule_id?: string | null;
  child_molecule_id?: string | null;
  actor: string;
  actor_kind: string;
  op: string;
  atom_idx?: number | null;
  bond_idx?: number | null;
  params?: Record<string, any>;
  result_smiles?: string | null;
  delta?: number | null;
}

interface Props {
  edits: EditRow[];
  onRefresh?: () => void;
  onLoadSmiles?: (smi: string) => void;
}

const ACTOR_COLOR: Record<string, string> = {
  designer: "#10b981",
  critic: "#ef4444",
  editor: "#3b82f6",
  strategist: "#8b5cf6",
  user: "#f59e0b",
  system: "#94a3b8",
};

function fmtTs(ts: number): string {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

export function EditLogCard({ edits, onRefresh, onLoadSmiles }: Props) {
  const sorted = [...edits].sort((a, b) => b.ts - a.ts);

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
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
        letterSpacing: "0.06em", textTransform: "uppercase",
      }}>
        <Clock size={11} />
        <span>edit log · sqlite · {sorted.length} rows</span>
        <span style={{ flex: 1 }} />
        {onRefresh && (
          <button
            type="button"
            onClick={onRefresh}
            title="Refresh"
            style={{
              border: 0, background: "transparent", cursor: "pointer",
              padding: 2, color: "var(--lys-text-faint)",
            }}
          >
            <RefreshCw size={11} />
          </button>
        )}
      </div>

      {sorted.length === 0 ? (
        <div style={{
          flex: 1, display: "grid", placeItems: "center",
          color: "var(--lys-text-faint)", fontSize: 11, padding: 12, textAlign: "center",
          fontFamily: "var(--lys-font-mono)",
        }}>
          no edits yet · pick a scaffold or click an atom to begin
        </div>
      ) : (
        <div style={{ flex: 1, overflow: "auto" }}>
          {sorted.map((e) => {
            const color = ACTOR_COLOR[e.actor.toLowerCase()] ?? "#94a3b8";
            return (
              <button
                key={e.id}
                type="button"
                onClick={() => e.result_smiles && onLoadSmiles?.(e.result_smiles)}
                title={e.result_smiles || ""}
                style={{
                  display: "grid",
                  gridTemplateColumns: "60px 70px 80px 1fr",
                  gap: 6,
                  alignItems: "center",
                  width: "100%",
                  padding: "4px 10px",
                  background: "transparent",
                  border: 0,
                  borderLeft: `3px solid ${color}`,
                  borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
                  textAlign: "left",
                  cursor: e.result_smiles ? "pointer" : "default",
                  fontFamily: "var(--lys-font-mono)",
                  fontSize: 10,
                  color: "var(--lys-text)",
                }}
              >
                <span style={{ color: "var(--lys-text-faint)", fontSize: 9 }}>
                  {fmtTs(e.ts)}
                </span>
                <span style={{ color, fontWeight: 700 }}>
                  {e.actor}
                </span>
                <span style={{
                  color: "var(--lys-text-dim)",
                  whiteSpace: "nowrap",
                  overflow: "hidden", textOverflow: "ellipsis",
                }}>
                  {e.op}
                  {e.atom_idx != null && <span style={{ color: "var(--lys-text-faint)" }}>@{e.atom_idx}</span>}
                </span>
                <span style={{
                  display: "flex", alignItems: "center", gap: 4, minWidth: 0,
                  color: "var(--lys-text-dim)",
                  whiteSpace: "nowrap",
                  overflow: "hidden", textOverflow: "ellipsis",
                  fontSize: 9.5,
                }}>
                  <ArrowRight size={9} style={{ color: "var(--lys-text-faint)", flexShrink: 0 }} />
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
                    {e.result_smiles ?? "(no smi)"}
                  </span>
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

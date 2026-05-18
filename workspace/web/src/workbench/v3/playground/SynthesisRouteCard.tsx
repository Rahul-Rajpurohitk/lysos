/**
 * SynthesisRouteCard — Service 1 frontend: Synthesis Make-Route.
 *
 * Turns the abstract `synthesizability` score into a real plan. Shows
 * a retrosynthetic route (named steps · reagents · conditions ·
 * building blocks) with a server-computed cost / lead-time /
 * feasibility header, and a full CRUD shelf of saved routes (plan /
 * open / star / delete) shared by users and agents.
 *
 * Backend: /workbench/chem/synthesis/plan + /routes (chem_synthesis.py).
 */
import { useEffect, useState, useCallback } from "react";
import { FlaskConical, RefreshCw, Star, Trash2, Beaker, ChevronRight } from "lucide-react";

interface RouteStep {
  step: number;
  name: string;
  reaction_class: string;
  reagents: string[];
  conditions: string;
  product_smiles: string;
  product_valid: boolean;
  rationale: string;
}
interface StartingMaterial {
  name: string;
  smiles: string;
  smiles_valid: boolean;
  availability: "in_stock" | "catalog" | "custom";
  est_cost_usd: number;
}
interface SynthRoute {
  smiles: string;
  n_steps: number;
  steps: RouteStep[];
  starting_materials: StartingMaterial[];
  route_reaches_target: boolean;
  n_invalid_intermediates: number;
  estimated_cost_usd: number;
  cost_band: "low" | "moderate" | "high";
  lead_time_days: number;
  feasibility: number;
  feasibility_band: "ready" | "workable" | "hard";
  overall_notes: string;
  model: string;
  artifact_id?: string | null;
  starred?: boolean;
}
interface SavedRoute {
  id: string;
  smiles: string | null;
  title: string | null;
  updated_at: number;
  payload: SynthRoute;
}

interface Props {
  apiBase: string;
  sessionId: string | null;
  smiles: string | null;
  onLoad?: (smiles: string) => void;
}

// Amber "forge / make" accent — distinguishes the synthesis service
// from the cyan chemistry panels + lavender resistance/pareto cards.
const AMBER = {
  bg: "rgba(217,119,6,0.06)",
  bgStrong: "rgba(217,119,6,0.12)",
  border: "rgba(217,119,6,0.28)",
  borderStrong: "rgba(217,119,6,0.42)",
  fg: "#b45309",
  fgDeep: "#92400e",
} as const;

const AVAIL_COLOR: Record<string, string> = {
  in_stock: "#16a34a",
  catalog: "#d97706",
  custom: "#dc2626",
};
const BAND_COLOR: Record<string, string> = {
  low: "#16a34a", moderate: "#d97706", high: "#dc2626",
  ready: "#16a34a", workable: "#d97706", hard: "#dc2626",
};

export function SynthesisRouteCard({ apiBase, sessionId, smiles, onLoad }: Props) {
  const [route, setRoute] = useState<SynthRoute | null>(null);
  const [saved, setSaved] = useState<SavedRoute[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const refreshSaved = useCallback(async () => {
    try {
      const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
      const r = await fetch(`${apiBase}/workbench/chem/synthesis/routes${qs}`);
      if (!r.ok) return;
      const d = await r.json();
      setSaved(d.routes || []);
    } catch { /* offline — keep prior list */ }
  }, [apiBase, sessionId]);

  useEffect(() => { void refreshSaved(); }, [refreshSaved]);

  async function planRoute() {
    if (!smiles) { setError("Pick or design a candidate first."); return; }
    setLoading(true);
    setError("");
    try {
      const r = await fetch(`${apiBase}/workbench/chem/synthesis/plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ smiles, session_id: sessionId, save: true }),
      });
      if (!r.ok) throw new Error(`plan failed (http ${r.status})`);
      const d = (await r.json()) as SynthRoute;
      setRoute(d);
      await refreshSaved();
    } catch (e: any) {
      setError(String(e?.message ?? e));
    } finally {
      setLoading(false);
    }
  }

  async function deleteRoute(id: string) {
    try {
      await fetch(`${apiBase}/workbench/chem/synthesis/routes/${id}`, { method: "DELETE" });
      setSaved((s) => s.filter((x) => x.id !== id));
      if (route?.artifact_id === id) setRoute(null);
    } catch { /* noop */ }
  }

  async function toggleStar(rt: SavedRoute) {
    try {
      const r = await fetch(`${apiBase}/workbench/chem/synthesis/routes/${rt.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ starred: !rt.payload.starred }),
      });
      if (r.ok) await refreshSaved();
    } catch { /* noop */ }
  }

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "transparent", overflow: "hidden",
      fontFamily: "var(--lys-font-body)",
    }}>
      {/* Header */}
      <div style={{
        padding: "6px 10px", display: "flex", alignItems: "center", gap: 6,
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
        textTransform: "uppercase", color: AMBER.fgDeep,
        borderBottom: `1px solid ${AMBER.border}`,
      }}>
        <FlaskConical size={11} style={{ color: AMBER.fg }} />
        <span>synthesis route · make + cost</span>
        <span style={{ flex: 1 }} />
        {saved.length > 0 && (
          <span style={{
            padding: "1px 6px", borderRadius: 999, background: AMBER.bgStrong,
            border: `1px solid ${AMBER.border}`, color: AMBER.fgDeep, fontSize: 9,
          }}>{saved.length} saved</span>
        )}
        <button type="button" onClick={() => void refreshSaved()}
          title="Refresh saved routes"
          style={{ border: 0, background: "transparent", cursor: "pointer",
            padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Plan action */}
      <div style={{
        padding: "8px 10px", display: "flex", alignItems: "center", gap: 8,
        borderBottom: "1px solid rgba(0,0,0,0.05)",
      }}>
        <button type="button" onClick={() => void planRoute()} disabled={loading || !smiles}
          style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 11px", borderRadius: 5, border: 0,
            background: !smiles ? "rgba(0,0,0,0.05)" : AMBER.fg,
            color: !smiles ? "var(--lys-text-faint)" : "white",
            fontSize: 11, fontWeight: 600, fontFamily: "var(--lys-font-body)",
            cursor: !smiles || loading ? "not-allowed" : "pointer",
          }}>
          <Beaker size={12} />
          {loading ? "Planning route…" : "Plan synthesis route"}
        </button>
        <span style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {smiles ? smiles : "no candidate loaded"}
        </span>
      </div>

      {error && (
        <div style={{ padding: "6px 10px", fontSize: 10, color: "#dc2626" }}>{error}</div>
      )}

      {/* Body */}
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!route && !loading && (
          <div style={{
            display: "flex", flexDirection: "column", gap: 6, alignItems: "center",
            justifyContent: "center", padding: 20, textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 11,
          }}>
            <FlaskConical size={22} style={{ opacity: 0.4 }} />
            <div>Plan a route to turn the synthesizability score into real
              steps, reagents, building blocks and a cost estimate.</div>
          </div>
        )}

        {route && <RouteView route={route} onLoad={onLoad} />}

        {/* Saved routes shelf (CRUD) */}
        {saved.length > 0 && (
          <div style={{ marginTop: 12 }}>
            <div style={{
              fontSize: 9, fontFamily: "var(--lys-font-mono)", letterSpacing: "0.06em",
              textTransform: "uppercase", color: "var(--lys-text-faint)",
              padding: "0 2px 4px",
            }}>saved routes</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              {saved.map((rt) => (
                <div key={rt.id}
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    padding: "5px 7px", borderRadius: 5,
                    background: route?.artifact_id === rt.id ? AMBER.bgStrong : AMBER.bg,
                    border: `1px solid ${AMBER.border}`,
                  }}>
                  <button type="button" onClick={() => void toggleStar(rt)}
                    title={rt.payload.starred ? "Unstar" : "Star"}
                    style={{ border: 0, background: "transparent", cursor: "pointer",
                      padding: 0, color: rt.payload.starred ? "#d97706" : "var(--lys-text-faint)" }}>
                    <Star size={12} fill={rt.payload.starred ? "#d97706" : "none"} />
                  </button>
                  <button type="button" onClick={() => setRoute(rt.payload)}
                    style={{
                      flex: 1, minWidth: 0, textAlign: "left", border: 0,
                      background: "transparent", cursor: "pointer", padding: 0,
                      display: "flex", alignItems: "baseline", gap: 6,
                    }}>
                    <span style={{ fontSize: 10.5, fontWeight: 600,
                      color: "var(--lys-text)", whiteSpace: "nowrap",
                      overflow: "hidden", textOverflow: "ellipsis" }}>
                      {rt.title || "route"}
                    </span>
                    <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                      color: "var(--lys-text-faint)", flexShrink: 0 }}>
                      {rt.payload.n_steps}st · ${Math.round(rt.payload.estimated_cost_usd)}
                    </span>
                  </button>
                  <button type="button" onClick={() => void deleteRoute(rt.id)}
                    title="Delete route"
                    style={{ border: 0, background: "transparent", cursor: "pointer",
                      padding: 0, color: "var(--lys-text-faint)" }}>
                    <Trash2 size={11} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/** The route detail — header stats strip + per-step blocks + building blocks. */
function RouteView({ route, onLoad }: { route: SynthRoute; onLoad?: (s: string) => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Stats strip */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 6,
      }}>
        <Stat label="steps" value={String(route.n_steps)} />
        <Stat label="cost" value={`$${Math.round(route.estimated_cost_usd)}`}
          color={BAND_COLOR[route.cost_band]} sub={route.cost_band} />
        <Stat label="lead time" value={`${route.lead_time_days}d`} />
        <Stat label="feasibility" value={route.feasibility.toFixed(2)}
          color={BAND_COLOR[route.feasibility_band]} sub={route.feasibility_band} />
      </div>

      {!route.route_reaches_target && (
        <div style={{
          fontSize: 9.5, color: "#92400e", background: "rgba(217,119,6,0.10)",
          border: "1px solid rgba(217,119,6,0.28)", borderRadius: 4,
          padding: "4px 7px",
        }}>
          The proposed final step did not cleanly close on the target —
          treat the last disconnection as approximate.
        </div>
      )}

      {/* Per-step blocks */}
      {route.steps.map((s) => (
        <div key={s.step} style={{
          border: `1px solid ${AMBER.border}`, borderRadius: 6,
          background: AMBER.bg, padding: "6px 8px",
        }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
            <span style={{
              width: 16, height: 16, borderRadius: 4, background: AMBER.fg,
              color: "white", fontSize: 9.5, fontWeight: 700,
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0, fontFamily: "var(--lys-font-mono)",
            }}>{s.step}</span>
            <span style={{ fontSize: 11.5, fontWeight: 700, color: "var(--lys-text)" }}>
              {s.name}
            </span>
            {s.reaction_class && (
              <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                color: AMBER.fgDeep, background: AMBER.bgStrong,
                padding: "1px 5px", borderRadius: 3 }}>
                {s.reaction_class}
              </span>
            )}
          </div>
          {s.reagents.length > 0 && (
            <Line label="reagents" value={s.reagents.join(", ")} />
          )}
          {s.conditions && <Line label="conditions" value={s.conditions} />}
          {s.product_smiles && (
            <div style={{ marginTop: 3, display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)", textTransform: "uppercase" }}>→</span>
              <button type="button"
                onClick={() => { if (onLoad) onLoad(s.product_smiles); }}
                title="Load this intermediate into the canvas"
                disabled={!s.product_valid}
                style={{
                  fontFamily: "var(--lys-font-mono)", fontSize: 9.5,
                  padding: "1px 5px", borderRadius: 3,
                  border: `1px solid ${s.product_valid ? AMBER.border : "rgba(220,38,38,0.3)"}`,
                  background: s.product_valid ? "rgba(255,255,255,0.6)" : "rgba(220,38,38,0.06)",
                  color: s.product_valid ? AMBER.fgDeep : "#dc2626",
                  cursor: s.product_valid ? "pointer" : "not-allowed",
                  wordBreak: "break-all", textAlign: "left", lineHeight: 1.3,
                }}>
                {s.product_smiles}
              </button>
            </div>
          )}
          {s.rationale && (
            <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
              marginTop: 3, lineHeight: 1.4 }}>{s.rationale}</div>
          )}
        </div>
      ))}

      {/* Building blocks */}
      {route.starting_materials.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
            letterSpacing: "0.06em", textTransform: "uppercase",
            color: "var(--lys-text-faint)", padding: "2px 2px 4px" }}>
            building blocks
          </div>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
            {route.starting_materials.map((sm, i) => (
              <span key={i}
                title={`${sm.smiles}${sm.smiles_valid ? "" : " (unparseable)"} · ~$${sm.est_cost_usd}`}
                style={{
                  display: "inline-flex", alignItems: "center", gap: 4,
                  padding: "2px 7px", borderRadius: 999, fontSize: 9.5,
                  background: "rgba(255,255,255,0.6)",
                  border: `1px solid ${AMBER.border}`,
                }}>
                <span style={{ width: 6, height: 6, borderRadius: 6,
                  background: AVAIL_COLOR[sm.availability] }} />
                <span style={{ fontWeight: 600, color: "var(--lys-text)" }}>{sm.name}</span>
                <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
                  fontFamily: "var(--lys-font-mono)" }}>{sm.availability}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {route.overall_notes && (
        <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
          fontStyle: "italic", lineHeight: 1.4, display: "flex", gap: 4 }}>
          <ChevronRight size={11} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{route.overall_notes}</span>
        </div>
      )}
      <div style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
        fontFamily: "var(--lys-font-mono)", textAlign: "right" }}>
        planned by {route.model}
      </div>
    </div>
  );
}

function Stat({ label, value, color, sub }: {
  label: string; value: string; color?: string; sub?: string;
}) {
  return (
    <div style={{
      background: "rgba(255,255,255,0.55)", border: `1px solid ${AMBER.border}`,
      borderRadius: 5, padding: "4px 6px", textAlign: "center",
    }}>
      <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.04em", textTransform: "uppercase",
        color: "var(--lys-text-faint)" }}>{label}</div>
      <div style={{ fontSize: 14, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
        color: color ?? "var(--lys-text)", lineHeight: 1.2 }}>{value}</div>
      {sub && (
        <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
          color: color ?? "var(--lys-text-faint)" }}>{sub}</div>
      )}
    </div>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", gap: 5, marginTop: 2, fontSize: 9.5 }}>
      <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 8.5,
        color: "var(--lys-text-faint)", textTransform: "uppercase",
        flexShrink: 0, width: 56 }}>{label}</span>
      <span style={{ color: "var(--lys-text-dim)", lineHeight: 1.4 }}>{value}</span>
    </div>
  );
}

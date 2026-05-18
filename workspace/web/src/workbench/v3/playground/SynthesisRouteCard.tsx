/**
 * SynthesisRouteCard — Service 1 frontend: Synthesis Make-Route.
 *
 * "Plan synthesis route" dispatches the `plan_synthesis` WORKFLOW (not a
 * blocking POST) — so the agent is visibly working in the chat: editor
 * proposes the route → server validates + costs it → critic reviews it.
 * The card polls for the persisted artifact and opens it when the
 * workflow lands.
 *
 * Renders the full reasoned route: strategy, per-step yield + risk +
 * reaction-class cost, structure-derived building-block availability,
 * cumulative yield, and the critic verdict — plus a CRUD shelf of
 * saved routes.
 *
 * Backend: /workbench/chem/synthesis/* (chem_synthesis.py).
 */
import { useEffect, useState, useCallback, useRef } from "react";
import { FlaskConical, RefreshCw, Star, Trash2, Beaker, ChevronRight, AlertTriangle } from "lucide-react";

interface RouteStep {
  step: number;
  name: string;
  reaction_class: string;
  reagents: string[];
  conditions: string;
  product_smiles: string;
  product_valid: boolean;
  yield_pct: number;
  risk: "low" | "moderate" | "high";
  est_cost_usd: number;
  cost_driver: string;
  rationale: string;
}
interface StartingMaterial {
  name: string;
  smiles: string;
  smiles_valid: boolean;
  availability: "in_stock" | "catalog" | "custom";
  availability_reason: string;
  est_cost_usd: number;
  heavy_atoms: number;
}
interface Critique {
  riskiest_step: number | null;
  risk_reason: string;
  scale_up_concern: string;
  confidence: number;
  verdict: string;
  model: string;
}
interface SynthRoute {
  smiles: string;
  strategy: string;
  n_steps: number;
  steps: RouteStep[];
  starting_materials: StartingMaterial[];
  route_reaches_target: boolean;
  n_invalid_intermediates: number;
  estimated_cost_usd: number;
  step_cost_usd: number;
  materials_cost_usd: number;
  cost_band: "low" | "moderate" | "high";
  overall_yield_pct: number;
  lead_time_days: number;
  feasibility: number;
  feasibility_band: "ready" | "workable" | "hard";
  overall_notes: string;
  model: string;
  critique?: Critique;
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
  fg: "#b45309",
  fgDeep: "#92400e",
} as const;

const AVAIL_COLOR: Record<string, string> = {
  in_stock: "#16a34a", catalog: "#d97706", custom: "#dc2626",
};
const RISK_COLOR: Record<string, string> = {
  low: "#16a34a", moderate: "#d97706", high: "#dc2626",
};
const BAND_COLOR: Record<string, string> = {
  low: "#16a34a", moderate: "#d97706", high: "#dc2626",
  ready: "#16a34a", workable: "#d97706", hard: "#dc2626",
};

export function SynthesisRouteCard({ apiBase, sessionId, smiles, onLoad }: Props) {
  const [route, setRoute] = useState<SynthRoute | null>(null);
  const [saved, setSaved] = useState<SavedRoute[]>([]);
  const [planning, setPlanning] = useState(false);
  const [error, setError] = useState("");
  const pollRef = useRef<number | undefined>(undefined);

  const refreshSaved = useCallback(async (): Promise<SavedRoute[]> => {
    try {
      const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
      const r = await fetch(`${apiBase}/workbench/chem/synthesis/routes${qs}`);
      if (!r.ok) return [];
      const d = await r.json();
      const rows: SavedRoute[] = d.routes || [];
      setSaved(rows);
      return rows;
    } catch { return []; }
  }, [apiBase, sessionId]);

  useEffect(() => { void refreshSaved(); }, [refreshSaved]);
  // Stop polling if the card unmounts.
  useEffect(() => () => { if (pollRef.current) window.clearTimeout(pollRef.current); }, []);

  /**
   * Plan a route — dispatches the `plan_synthesis` workflow so the
   * agent streams visibly in the chat (editor → validate → critic),
   * then polls for the persisted artifact. NOT a blocking POST.
   */
  function planRoute() {
    if (!smiles) { setError("Pick or design a candidate first."); return; }
    setError("");
    setPlanning(true);
    const beforeIds = new Set(saved.map((s) => s.id));

    window.dispatchEvent(new CustomEvent("lysos:auto-slash", {
      detail: {
        text: `/wf plan_synthesis ${JSON.stringify({
          smiles, session_id: sessionId,
        })}`,
      },
    }));

    const deadline = Date.now() + 70000;
    const poll = async () => {
      if (Date.now() > deadline) {
        setPlanning(false);
        setError("Route is still streaming in the chat workflow — "
          + "it'll appear here once the critic finishes.");
        return;
      }
      const rows = await refreshSaved();
      const fresh = rows.find((x) => !beforeIds.has(x.id));
      if (fresh) {
        setRoute({ ...fresh.payload, artifact_id: fresh.id });
        setPlanning(false);
        return;
      }
      pollRef.current = window.setTimeout(() => { void poll(); }, 2800);
    };
    pollRef.current = window.setTimeout(() => { void poll(); }, 3500);
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
        <button type="button" onClick={planRoute} disabled={planning || !smiles}
          style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "5px 11px", borderRadius: 5, border: 0,
            background: !smiles ? "rgba(0,0,0,0.05)" : AMBER.fg,
            color: !smiles ? "var(--lys-text-faint)" : "white",
            fontSize: 11, fontWeight: 600, fontFamily: "var(--lys-font-body)",
            cursor: !smiles || planning ? "not-allowed" : "pointer",
          }}>
          <Beaker size={12} />
          {planning ? "Agent planning route…" : "Plan synthesis route"}
        </button>
        <span style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-mono)", overflow: "hidden",
          textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
          {planning ? "editor → validate → critic, streaming in chat"
            : smiles ? smiles : "no candidate loaded"}
        </span>
      </div>

      {error && (
        <div style={{ padding: "6px 10px", fontSize: 10, color: "#b45309" }}>{error}</div>
      )}

      {/* Body */}
      <div style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 8 }}>
        {!route && !planning && (
          <div style={{
            display: "flex", flexDirection: "column", gap: 6, alignItems: "center",
            justifyContent: "center", padding: 20, textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 11,
          }}>
            <FlaskConical size={22} style={{ opacity: 0.4 }} />
            <div>Plan a route — the editor agent proposes named steps with
              yields + risk, the server validates every intermediate and
              costs each step by reaction class, and a critic reviews it.</div>
          </div>
        )}

        {planning && !route && (
          <div style={{
            display: "flex", flexDirection: "column", gap: 6, alignItems: "center",
            justifyContent: "center", padding: 20, textAlign: "center",
            color: AMBER.fgDeep, fontSize: 11,
          }}>
            <RefreshCw size={20} style={{ animation: "spin 1s linear infinite" }} />
            <div>Agent is planning the route — watch it stream step-by-step
              in the chat. The result lands here when the critic finishes.</div>
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
                  <button type="button" onClick={() => setRoute({ ...rt.payload, artifact_id: rt.id })}
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

/** Route detail — stats strip, strategy, per-step blocks, building
 *  blocks with derived availability, and the critic review. */
function RouteView({ route, onLoad }: { route: SynthRoute; onLoad?: (s: string) => void }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {/* Stats strip */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 5 }}>
        <Stat label="steps" value={String(route.n_steps)} />
        <Stat label="cost" value={`$${Math.round(route.estimated_cost_usd)}`}
          color={BAND_COLOR[route.cost_band]} sub={route.cost_band} />
        <Stat label="yield" value={`${route.overall_yield_pct}%`}
          color={route.overall_yield_pct >= 45 ? "#16a34a" : "#d97706"} />
        <Stat label="lead" value={`${route.lead_time_days}d`} />
        <Stat label="feasibility" value={route.feasibility.toFixed(2)}
          color={BAND_COLOR[route.feasibility_band]} sub={route.feasibility_band} />
      </div>

      {route.strategy && (
        <div style={{ fontSize: 10, color: "var(--lys-text-dim)",
          fontStyle: "italic", lineHeight: 1.4 }}>
          <strong style={{ fontStyle: "normal", color: AMBER.fgDeep }}>Strategy:</strong>{" "}
          {route.strategy}
        </div>
      )}

      {!route.route_reaches_target && (
        <div style={{
          fontSize: 9.5, color: "#92400e", background: "rgba(217,119,6,0.10)",
          border: "1px solid rgba(217,119,6,0.28)", borderRadius: 4,
          padding: "4px 7px",
        }}>
          The final step did not cleanly close on the target — treat the
          last disconnection as approximate.
        </div>
      )}

      {/* Per-step blocks */}
      {route.steps.map((s) => (
        <div key={s.step} style={{
          border: `1px solid ${AMBER.border}`, borderRadius: 6,
          background: AMBER.bg, padding: "6px 8px",
        }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}>
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
          {/* Per-step metrics row — yield · risk · cost (real, computed) */}
          <div style={{ display: "flex", gap: 8, marginTop: 3, flexWrap: "wrap",
            fontSize: 9, fontFamily: "var(--lys-font-mono)" }}>
            <span style={{ color: s.yield_pct >= 70 ? "#16a34a" : "#d97706" }}>
              yield {s.yield_pct}%
            </span>
            <span style={{ color: RISK_COLOR[s.risk] }}>{s.risk} risk</span>
            <span style={{ color: AMBER.fgDeep }} title={s.cost_driver}>
              ${s.est_cost_usd} · {s.cost_driver}
            </span>
          </div>
          {s.reagents.length > 0 && <Line label="reagents" value={s.reagents.join(", ")} />}
          {s.conditions && <Line label="conditions" value={s.conditions} />}
          {s.product_smiles && (
            <div style={{ marginTop: 3, display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)" }}>→</span>
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

      {/* Building blocks — availability derived from structure */}
      {route.starting_materials.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
            letterSpacing: "0.06em", textTransform: "uppercase",
            color: "var(--lys-text-faint)", padding: "2px 2px 4px" }}>
            building blocks · availability derived from structure
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {route.starting_materials.map((sm, i) => (
              <div key={i}
                title={sm.smiles}
                style={{
                  display: "flex", alignItems: "baseline", gap: 6,
                  padding: "3px 7px", borderRadius: 4,
                  background: "rgba(255,255,255,0.6)",
                  border: `1px solid ${AMBER.border}`, fontSize: 9.5,
                }}>
                <span style={{ width: 6, height: 6, borderRadius: 6, flexShrink: 0,
                  background: AVAIL_COLOR[sm.availability] }} />
                <span style={{ fontWeight: 600, color: "var(--lys-text)" }}>{sm.name}</span>
                <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                  color: AVAIL_COLOR[sm.availability] }}>{sm.availability}</span>
                <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)" }}>${sm.est_cost_usd}</span>
                <span style={{ flex: 1 }} />
                <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  maxWidth: "55%" }}>{sm.availability_reason}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Critic review */}
      {route.critique && (
        <div style={{
          border: `1px solid rgba(220,38,38,0.28)`, borderRadius: 6,
          background: "rgba(220,38,38,0.05)", padding: "6px 8px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5,
            fontSize: 10, fontWeight: 700, color: "#b91c1c" }}>
            <AlertTriangle size={11} />
            <span>Critic review</span>
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              color: route.critique.confidence >= 0.6 ? "#16a34a" : "#d97706" }}>
              confidence {route.critique.confidence}
            </span>
          </div>
          <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
            marginTop: 3, lineHeight: 1.45 }}>
            <strong>Riskiest:</strong> step {route.critique.riskiest_step ?? "—"} —{" "}
            {route.critique.risk_reason}
          </div>
          <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
            marginTop: 2, lineHeight: 1.45 }}>
            <strong>Scale-up:</strong> {route.critique.scale_up_concern}
          </div>
          <div style={{ fontSize: 9.5, color: "#b91c1c", marginTop: 2,
            lineHeight: 1.45, fontWeight: 600 }}>
            Verdict: {route.critique.verdict}
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
        editor: {route.model} · critic: {route.critique?.model ?? "—"}
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
      borderRadius: 5, padding: "4px 4px", textAlign: "center",
    }}>
      <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
        letterSpacing: "0.03em", textTransform: "uppercase",
        color: "var(--lys-text-faint)" }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
        color: color ?? "var(--lys-text)", lineHeight: 1.2 }}>{value}</div>
      {sub && (
        <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
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

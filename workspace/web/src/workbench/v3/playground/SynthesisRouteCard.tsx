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
import { FlaskConical, RefreshCw, Star, Trash2, Beaker, ChevronRight, AlertTriangle, ArrowRight } from "lucide-react";
import { Mol2DThumb } from "./Mol2DThumb";

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
interface EasierAnalog {
  analog_smiles: string;
  simplification: string;
  rationale: string;
  steps_before: number; steps_after: number;
  cost_before: number; cost_after: number;
  feasibility_before: number; feasibility_after: number;
  yield_before: number; yield_after: number;
  improved: boolean;
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
  easier_analog?: EasierAnalog | null;
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

        {route && <RouteView apiBase={apiBase} route={route} onLoad={onLoad} />}

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

/** Route detail — stats strip, structure-flow strip (SMs → step products
 *  → target), compact per-step ribbon, building-block availability,
 *  critic verdict. Structures replace text walls. */
function RouteView({ apiBase, route, onLoad }: {
  apiBase: string; route: SynthRoute; onLoad?: (s: string) => void;
}) {
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

      {/* THE AGENT ACTION — original ↔ analog structures, the payoff */}
      {route.easier_analog && route.easier_analog.improved && (
        <EasierAnalogBlock apiBase={apiBase} candidateSmiles={route.smiles}
          analog={route.easier_analog} onLoad={onLoad} />
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

      {/* ROUTE FLOW — horizontal strip: SMs → step products → target */}
      <RouteFlowStrip apiBase={apiBase} route={route} onLoad={onLoad} />

      {/* Compact per-step ribbon (1 row per step, no text walls) */}
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {route.steps.map((s) => (
          <div key={s.step}
            title={[
              s.reagents.length ? `reagents: ${s.reagents.join(", ")}` : "",
              s.conditions ? `conditions: ${s.conditions}` : "",
              s.rationale ? s.rationale : "",
            ].filter(Boolean).join("\n")}
            style={{
              display: "flex", alignItems: "center", gap: 7,
              padding: "4px 7px", borderRadius: 5,
              background: AMBER.bg, border: `1px solid ${AMBER.border}`,
              fontSize: 10,
            }}>
            <span style={{
              width: 16, height: 16, borderRadius: 4, background: AMBER.fg,
              color: "white", fontSize: 9, fontWeight: 700,
              display: "inline-flex", alignItems: "center", justifyContent: "center",
              flexShrink: 0, fontFamily: "var(--lys-font-mono)",
            }}>{s.step}</span>
            <span style={{ fontWeight: 600, color: "var(--lys-text)",
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              maxWidth: 160 }}>{s.name}</span>
            {s.reaction_class && (
              <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                color: AMBER.fgDeep, background: AMBER.bgStrong,
                padding: "1px 5px", borderRadius: 3, flexShrink: 0 }}>
                {s.reaction_class}
              </span>
            )}
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              color: s.yield_pct >= 70 ? "#16a34a" : "#d97706" }}>{s.yield_pct}%</span>
            <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              color: RISK_COLOR[s.risk] }}>{s.risk}</span>
            <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              color: AMBER.fgDeep }}>${s.est_cost_usd}</span>
          </div>
        ))}
      </div>

      {/* Building blocks — tight row with availability dot */}
      {route.starting_materials.length > 0 && (
        <div>
          <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
            letterSpacing: "0.06em", textTransform: "uppercase",
            color: "var(--lys-text-faint)", padding: "2px 2px 4px" }}>
            building blocks
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
            {route.starting_materials.map((sm, i) => (
              <div key={i}
                title={`${sm.smiles}\n${sm.availability_reason}`}
                style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "3px 7px", borderRadius: 4,
                  background: "rgba(255,255,255,0.6)",
                  border: `1px solid ${AMBER.border}`, fontSize: 9.5,
                }}>
                <span style={{ width: 6, height: 6, borderRadius: 6, flexShrink: 0,
                  background: AVAIL_COLOR[sm.availability] }} />
                <span style={{ fontWeight: 600, color: "var(--lys-text)",
                  whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
                  flex: 1 }}>{sm.name}</span>
                <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                  color: AVAIL_COLOR[sm.availability], flexShrink: 0 }}>{sm.availability}</span>
                <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                  color: "var(--lys-text-faint)", flexShrink: 0 }}>${sm.est_cost_usd}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Critic verdict — compact */}
      {route.critique && (
        <div style={{
          border: `1px solid rgba(220,38,38,0.28)`, borderRadius: 6,
          background: "rgba(220,38,38,0.05)", padding: "5px 8px",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5,
            fontSize: 10, fontWeight: 700, color: "#b91c1c" }}>
            <AlertTriangle size={11} />
            <span>Critic</span>
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
              color: route.critique.confidence >= 0.6 ? "#16a34a" : "#d97706" }}>
              conf {route.critique.confidence}
            </span>
          </div>
          <div style={{ fontSize: 9.5, color: "#b91c1c", marginTop: 2,
            lineHeight: 1.4, fontWeight: 600 }}>{route.critique.verdict}</div>
          {(route.critique.risk_reason || route.critique.scale_up_concern) && (
            <div style={{ fontSize: 9, color: "var(--lys-text-dim)",
              marginTop: 2, lineHeight: 1.4 }}>
              step {route.critique.riskiest_step ?? "—"}: {route.critique.risk_reason}
              {route.critique.scale_up_concern && (
                <> · scale-up: {route.critique.scale_up_concern}</>
              )}
            </div>
          )}
        </div>
      )}

      {route.overall_notes && (
        <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)",
          fontStyle: "italic", lineHeight: 1.4, display: "flex", gap: 4 }}>
          <ChevronRight size={11} style={{ flexShrink: 0, marginTop: 1 }} />
          <span>{route.overall_notes}</span>
        </div>
      )}
    </div>
  );
}

/** Horizontal route-flow strip: building blocks → step product
 *  thumbnails → target. Each thumb is clickable to load the
 *  intermediate into the canvas. Compact sizing so 3-step routes
 *  fit in a 420px card without horizontal scrolling. */
function RouteFlowStrip({ apiBase, route, onLoad }: {
  apiBase: string; route: SynthRoute; onLoad?: (s: string) => void;
}) {
  const sms = route.starting_materials;
  const steps = route.steps;
  if (!sms.length && !steps.length) return null;
  const smShown = sms.slice(0, 2);
  // Adaptive sizing — narrower thumbs for longer routes so the strip
  // doesn't clip the target.
  const n = steps.length;
  const stepW = n >= 4 ? 56 : n >= 3 ? 64 : 78;
  const stepH = Math.round(stepW * 0.78);
  return (
    <div style={{
      border: `1px solid ${AMBER.border}`, borderRadius: 7,
      background: "rgba(255,255,255,0.5)", padding: 7, minWidth: 0,
    }}>
      <div style={{ display: "flex", alignItems: "baseline",
        justifyContent: "space-between", marginBottom: 5 }}>
        <div style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
          letterSpacing: "0.06em", textTransform: "uppercase",
          color: AMBER.fgDeep }}>route flow</div>
        <div style={{ fontSize: 8, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)" }}>
          scroll →
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 4,
        overflowX: "auto", paddingBottom: 4 }}>
        {/* Starting materials column */}
        {smShown.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 3,
            flexShrink: 0 }}>
            {smShown.map((sm, i) => (
              <Mol2DThumb key={i} apiBase={apiBase} smiles={sm.smiles}
                w={stepW} h={Math.round(stepH * 0.85)}
                caption={sm.name.length > 12 ? sm.name.slice(0, 11) + "…" : sm.name}
                accent={AVAIL_COLOR[sm.availability]}
                onClick={onLoad ? () => onLoad(sm.smiles) : undefined}
                title={`${sm.name} (${sm.availability}, $${sm.est_cost_usd})`} />
            ))}
            {sms.length > smShown.length && (
              <div style={{ fontSize: 8, textAlign: "center",
                color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)" }}>
                +{sms.length - smShown.length}
              </div>
            )}
          </div>
        )}
        {/* Step product chain */}
        {steps.map((s, idx) => {
          const isTarget = idx === steps.length - 1;
          return (
            <div key={s.step} style={{ display: "flex", alignItems: "center",
              gap: 2, flexShrink: 0 }}>
              <div style={{ display: "flex", flexDirection: "column",
                alignItems: "center", gap: 1, minWidth: 40 }}>
                <ArrowRight size={12} style={{ color: AMBER.fg }} />
                {s.reaction_class && (
                  <span style={{ fontSize: 7, fontFamily: "var(--lys-font-mono)",
                    color: AMBER.fgDeep, fontWeight: 700,
                    maxWidth: 50, textAlign: "center", lineHeight: 1.1 }}>
                    {s.reaction_class.replace(/_/g, " ")}
                  </span>
                )}
              </div>
              <Mol2DThumb apiBase={apiBase} smiles={s.product_smiles}
                w={isTarget ? Math.round(stepW * 1.1) : stepW}
                h={isTarget ? Math.round(stepH * 1.1) : stepH}
                caption={isTarget ? "target" : `step ${s.step}`}
                accent={isTarget ? "#16a34a" : (s.product_valid ? AMBER.fg : "#dc2626")}
                onClick={onLoad && s.product_valid
                  ? () => onLoad(s.product_smiles) : undefined}
                title={s.product_smiles} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** The agentic payoff — the agent's easier-to-make analog with
 *  side-by-side ORIGINAL ↔ ANALOG structures. Emerald accent: action,
 *  not readout. */
function EasierAnalogBlock({ apiBase, candidateSmiles, analog, onLoad }: {
  apiBase: string;
  candidateSmiles: string;
  analog: EasierAnalog;
  onLoad?: (s: string) => void;
}) {
  const ACT = { bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.4)",
    fg: "#059669", fgDeep: "#047857" };
  const Delta = ({ label, before, after, better }: {
    label: string; before: string | number; after: string | number; better: boolean;
  }) => (
    <div style={{ textAlign: "center", flex: 1 }}>
      <div style={{ fontSize: 7.5, fontFamily: "var(--lys-font-mono)",
        textTransform: "uppercase", color: "var(--lys-text-faint)" }}>{label}</div>
      <div style={{ fontSize: 9.5, fontFamily: "var(--lys-font-mono)" }}>
        <span style={{ color: "var(--lys-text-faint)" }}>{before}</span>
        <span style={{ color: ACT.fg, margin: "0 2px" }}>→</span>
        <span style={{ color: better ? ACT.fgDeep : "#d97706", fontWeight: 700 }}>{after}</span>
      </div>
    </div>
  );
  return (
    <div style={{ border: `1.5px solid ${ACT.border}`, borderRadius: 7,
      background: ACT.bg, padding: "8px 9px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 5,
        fontSize: 10, fontWeight: 700, color: ACT.fgDeep, marginBottom: 6 }}>
        <Beaker size={12} />
        <span>Agent designed an easier-to-make analog</span>
      </div>
      {/* Side-by-side structures — the visual story */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center",
        gap: 6, padding: "2px 0 6px" }}>
        <Mol2DThumb apiBase={apiBase} smiles={candidateSmiles} w={130} h={100}
          caption="original" accent="rgba(180,83,9,0.55)" />
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center",
          gap: 2 }}>
          <ArrowRight size={18} style={{ color: ACT.fg }} />
          <span style={{ fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
            color: ACT.fg, fontWeight: 700 }}>
            {analog.steps_before}→{analog.steps_after}st
          </span>
        </div>
        <Mol2DThumb apiBase={apiBase} smiles={analog.analog_smiles} w={130} h={100}
          caption="analog" accent={ACT.fg} />
      </div>
      {/* 4-up delta strip */}
      <div style={{ display: "flex", gap: 4, margin: "4px 0 6px" }}>
        <Delta label="steps" before={analog.steps_before} after={analog.steps_after}
          better={analog.steps_after <= analog.steps_before} />
        <Delta label="cost" before={`$${Math.round(analog.cost_before)}`}
          after={`$${Math.round(analog.cost_after)}`}
          better={analog.cost_after <= analog.cost_before} />
        <Delta label="feasibility" before={analog.feasibility_before.toFixed(2)}
          after={analog.feasibility_after.toFixed(2)}
          better={analog.feasibility_after >= analog.feasibility_before} />
        <Delta label="yield" before={`${analog.yield_before}%`}
          after={`${analog.yield_after}%`}
          better={analog.yield_after >= analog.yield_before} />
      </div>
      {/* One-line simplification */}
      <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)", lineHeight: 1.4,
        textAlign: "center" }}>
        <strong style={{ color: ACT.fgDeep }}>{analog.simplification}</strong>
      </div>
      <button type="button"
        onClick={() => {
          if (onLoad) onLoad(analog.analog_smiles);
          else window.dispatchEvent(new CustomEvent("lysos:auto-slash",
            { detail: { text: `/load ${analog.analog_smiles}` } }));
        }}
        style={{ marginTop: 6, width: "100%", padding: "6px 0", border: 0,
          borderRadius: 5, background: ACT.fg, color: "white",
          fontSize: 10.5, fontWeight: 700, cursor: "pointer" }}>
        Apply this analog → load + re-score
      </button>
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


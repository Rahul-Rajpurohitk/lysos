/**
 * Mol3DTheaterWindow — Service 1: 3D Target-Ligand Theater.
 *
 * The biology side of the chem container. Lets the user (and agent) pick a
 * specific pathogen target from the curated PATHOGEN_TARGETS map, see the
 * candidate molecule placed in that target's active site, and read back
 * which atoms make binding contacts vs which clash. Halos (binding =
 * green, clashing = red) get bubbled up to the 2D builder so the user
 * sees the same atom-level signal in both views.
 *
 * Layout (overlays on top of the NGL stage):
 *   ┌──────────────────────────────────────────────────────┐
 *   │ [Target picker dropdown]      [pose 0.72] [n=8 contacts] │
 *   │                                                      │
 *   │              N G L   3 D   S T A G E                 │
 *   │      (protein cartoon + ligand ball-and-stick)        │
 *   │                                                      │
 *   │                            ┌─ Contacts panel ─┐      │
 *   │                            │ SER365 1.84Å 🟢 │      │
 *   │                            │ LYS247 1.6Å  🟢 │      │
 *   │                            │ TYR337 1.75Å 🟢 │      │
 *   │                            └────────────────┘       │
 *   │ [closest known antibiotic match overlay (kept)]      │
 *   └──────────────────────────────────────────────────────┘
 *
 * Wiring:
 *   /workbench/chem/targets/{pathogen}     → list of targets for picker
 *   /workbench/chem/place-in-pocket        → on SMILES + selectedTarget change
 *   onPoseChange(binding[], clashing[])    → bubble up to WorkbenchV3 → 2D
 */
import { useEffect, useState, useRef } from "react";
import { Target, RefreshCw } from "lucide-react";
import { Mol3D } from "../components/Mol3D";

interface CuratedTarget {
  pdb_id: string;
  name: string;
  short_name: string;
  mechanism: string;
  clinical_note: string;
  drug_class_examples: string[];
  preferred_default: boolean;
}

interface KeyContact {
  residue: string;
  chain: string;
  ligand_atom_idx: number;
  ligand_element: string;
  distance_a: number;
}

interface PoseResult {
  pdb_id: string;
  smiles: string;
  pose_score: number;
  n_contacts: number;
  n_clashes: number;
  binding_atoms: number[];
  clashing_atoms: number[];
  key_contacts: KeyContact[];
}

interface Props {
  apiBase: string;
  smiles: string | null;
  pathogen: string;
  onMoleculeEdit?: (newSmiles: string, op: any) => void;
  /** When a new pose is computed, bubble the binding/clashing atom indices
   *  up so the 2D builder can paint matching halos on those same atoms. */
  onPoseChange?: (poseData: PoseResult | null) => void;
  /** When the user picks a different target via the picker dropdown, bubble
   *  the new PDB ID upstream — the Resistance Escape Map card consumes it
   *  to know which target to predict mutations against. */
  onTargetChange?: (pdbId: string | null) => void;
}

interface MatchResult {
  matches: { name: string; drug_class: string; mechanism: string; targets: string[]; year: number; similarity: number; is_exact: boolean }[];
  best: { name: string; drug_class: string; mechanism: string; targets: string[]; year: number; similarity: number; is_exact: boolean } | null;
  is_known: boolean;
}

export function Mol3DTheaterWindow(p: Props) {
  // ─── Curated target picker ─────────────────────────────────────────
  const [targets, setTargets] = useState<CuratedTarget[]>([]);
  const [selectedTargetId, setSelectedTargetId] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Fetch curated targets when pathogen changes
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${p.apiBase}/workbench/chem/targets/${encodeURIComponent(p.pathogen)}`);
        if (!r.ok) { setTargets([]); return; }
        const d = await r.json();
        if (cancelled) return;
        const ts: CuratedTarget[] = d.targets || [];
        setTargets(ts);
        // Pick the preferred_default if no selection yet, else first.
        const preferred = ts.find((t) => t.preferred_default) || ts[0];
        if (preferred) setSelectedTargetId(preferred.pdb_id);
      } catch {
        if (!cancelled) setTargets([]);
      }
    })();
    return () => { cancelled = true; };
  }, [p.pathogen, p.apiBase]);

  const selectedTarget = targets.find((t) => t.pdb_id === selectedTargetId) || null;

  // Bubble target change upstream so sibling cards (resistance map, scoring)
  // can use the same selected target.
  useEffect(() => {
    p.onTargetChange?.(selectedTargetId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedTargetId]);

  // ─── Pose: place-in-pocket on SMILES + target change ───────────────
  const [pose, setPose] = useState<PoseResult | null>(null);
  const [poseLoading, setPoseLoading] = useState(false);
  const [poseError, setPoseError] = useState<string>("");
  const lastSmilesRef = useRef<string>("");
  const lastTargetRef = useRef<string>("");

  useEffect(() => {
    if (!p.smiles || !selectedTargetId) {
      setPose(null);
      p.onPoseChange?.(null);
      return;
    }
    if (p.smiles === lastSmilesRef.current && selectedTargetId === lastTargetRef.current) return;
    lastSmilesRef.current = p.smiles;
    lastTargetRef.current = selectedTargetId;
    let cancelled = false;
    setPoseLoading(true);
    setPoseError("");
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${p.apiBase}/workbench/chem/place-in-pocket`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ smiles: p.smiles, pdb_id: selectedTargetId }),
        });
        if (!r.ok) {
          const err = await r.text();
          if (!cancelled) {
            setPoseError(err.slice(0, 100));
            setPose(null);
            p.onPoseChange?.(null);
          }
          return;
        }
        const d: PoseResult = await r.json();
        if (cancelled) return;
        setPose(d);
        p.onPoseChange?.(d);
      } catch (e: any) {
        if (!cancelled) {
          setPoseError(String(e?.message ?? e).slice(0, 100));
          setPose(null);
        }
      } finally {
        if (!cancelled) setPoseLoading(false);
      }
    }, 300);
    return () => { cancelled = true; clearTimeout(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [p.smiles, selectedTargetId, p.apiBase]);

  // ─── Closest-known overlay (kept from prior version) ───────────────
  const [match, setMatch] = useState<MatchResult | null>(null);
  useEffect(() => {
    if (!p.smiles) { setMatch(null); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${p.apiBase}/workbench/molecule/match-known?smiles=${encodeURIComponent(p.smiles!)}&top_k=3`);
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setMatch(d);
      } catch {/*noop*/}
    }, 250);
    return () => { cancelled = true; clearTimeout(t); };
  }, [p.smiles, p.apiBase]);

  const sim = match?.best?.similarity ?? 0;
  const tier = sim >= 0.95 ? "exact" : sim >= 0.65 ? "close" : sim >= 0.30 ? "weak" : "novel";
  const TIER_COLORS = {
    exact:  { fg: "#10b981", bg: "rgba(16,185,129,0.10)", border: "rgba(16,185,129,0.35)", label: "EXACT" },
    close:  { fg: "#0891b2", bg: "rgba(8,145,178,0.10)",  border: "rgba(8,145,178,0.35)",  label: "CLOSE" },
    weak:   { fg: "#ca8a04", bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.35)",  label: "WEAK" },
    novel:  { fg: "#7c3aed", bg: "rgba(124,58,237,0.10)", border: "rgba(124,58,237,0.35)", label: "NOVEL" },
  } as const;
  const tc = TIER_COLORS[tier];

  // Pose-score color tier
  const poseScore = pose?.pose_score ?? 0;
  const poseTier = poseScore >= 0.5 ? "good" : poseScore >= 0.2 ? "fair" : "poor";
  const POSE_COLORS = {
    good: { fg: "#10b981", bg: "rgba(16,185,129,0.12)", border: "rgba(16,185,129,0.40)" },
    fair: { fg: "#ca8a04", bg: "rgba(202,138,4,0.12)",  border: "rgba(202,138,4,0.40)"  },
    poor: { fg: "#dc2626", bg: "rgba(220,38,38,0.12)",  border: "rgba(220,38,38,0.40)"  },
  } as const;
  const pc = POSE_COLORS[poseTier];

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <Mol3D
        apiBase={p.apiBase}
        smiles={p.smiles}
        pathogen={p.pathogen}
        onMoleculeEdit={p.onMoleculeEdit}
        pdbOverride={selectedTargetId}
      />

      {/* ─── TOP-LEFT: Target picker dropdown ──────────────────────── */}
      <div style={{
        position: "absolute", top: 8, left: 8, zIndex: 60,
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <button
          type="button"
          onClick={() => setPickerOpen((o) => !o)}
          title="Pick the validated target this candidate is designed against"
          style={{
            padding: "5px 10px",
            background: "rgba(255,255,255,0.92)",
            border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
            borderRadius: 6,
            backdropFilter: "blur(8px)",
            display: "inline-flex", alignItems: "center", gap: 6,
            fontFamily: "var(--lys-font-mono)", fontSize: 10.5,
            cursor: "pointer", boxShadow: "0 4px 12px rgba(15,23,42,0.10)",
          }}>
          <Target size={12} style={{ color: "#0891b2" }} />
          <span style={{ fontWeight: 700 }}>
            {selectedTarget?.short_name ?? "pick target"}
          </span>
          {selectedTarget && (
            <span style={{ fontSize: 9, opacity: 0.6 }}>
              · {selectedTarget.pdb_id}
            </span>
          )}
        </button>
        {pickerOpen && targets.length > 0 && (
          <div style={{
            position: "absolute", top: "100%", left: 0, marginTop: 4,
            background: "white",
            border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
            borderRadius: 6,
            boxShadow: "0 8px 24px rgba(15,23,42,0.18)",
            minWidth: 320, maxWidth: 460, padding: 4,
            zIndex: 61, fontFamily: "var(--lys-font-body)",
          }}>
            <div style={{
              padding: "4px 8px", fontSize: 9, fontFamily: "var(--lys-font-mono)",
              color: "var(--lys-text-faint)", letterSpacing: "0.06em",
              textTransform: "uppercase", fontWeight: 700,
              borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
            }}>
              Validated targets · {p.pathogen}
            </div>
            {targets.map((t) => (
              <button
                key={t.pdb_id}
                type="button"
                onClick={() => { setSelectedTargetId(t.pdb_id); setPickerOpen(false); }}
                title={t.clinical_note}
                style={{
                  width: "100%", textAlign: "left",
                  padding: "6px 8px", border: 0, background: "transparent",
                  cursor: "pointer", borderRadius: 4,
                  display: "flex", flexDirection: "column", gap: 2,
                  borderLeft: `3px solid ${t.pdb_id === selectedTargetId ? "#0891b2" : "transparent"}`,
                }}
                onMouseOver={(e) => { (e.currentTarget as HTMLElement).style.background = "rgba(8,145,178,0.05)"; }}
                onMouseOut={(e) => { (e.currentTarget as HTMLElement).style.background = "transparent"; }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
                  <span style={{ fontWeight: 700, fontSize: 11 }}>{t.short_name}</span>
                  <span style={{ fontFamily: "var(--lys-font-mono)", fontSize: 9, opacity: 0.6 }}>
                    {t.pdb_id}
                  </span>
                  {t.preferred_default && (
                    <span style={{
                      fontSize: 8, padding: "0 5px", borderRadius: 999,
                      background: "rgba(16,185,129,0.10)", color: "#059669",
                      fontWeight: 700,
                    }}>default</span>
                  )}
                </div>
                <div style={{ fontSize: 9.5, color: "var(--lys-text-dim)" }}>
                  {t.mechanism}
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ─── BELOW-TOOLBAR-RIGHT: Pose score + contacts/clashes ─────
          Sits underneath the Mol3D toolbar's right edge instead of
          fighting it for the same row. Floats over the viewer. */}
      {pose && (
        <div
          title="Pose quality from /chem/place-in-pocket — geometric placement of the candidate in the active site (no rotation search). Uses 4Å contact / 1.5Å clash thresholds."
          style={{
            position: "absolute", top: 44, right: 8, zIndex: 60,
            padding: "4px 9px",
            background: pc.bg, border: `1px solid ${pc.border}`,
            borderRadius: 5, backdropFilter: "blur(8px)",
            display: "inline-flex", alignItems: "center", gap: 7,
            fontFamily: "var(--lys-font-mono)", fontSize: 10,
            color: pc.fg, fontWeight: 700,
          }}>
          <span>pose {poseScore.toFixed(2)}</span>
          <span style={{ opacity: 0.55, fontWeight: 500 }}>·</span>
          <span title="contacts within 4Å">{pose.n_contacts} contacts</span>
          {pose.n_clashes > 0 && (
            <>
              <span style={{ opacity: 0.55, fontWeight: 500 }}>·</span>
              <span style={{ color: "#dc2626" }} title="clashes within 1.5Å">{pose.n_clashes} clashes</span>
            </>
          )}
        </div>
      )}
      {poseLoading && (
        <div style={{
          position: "absolute", top: 8, right: 8, zIndex: 60,
          padding: "5px 10px",
          background: "rgba(255,255,255,0.92)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 6, backdropFilter: "blur(8px)",
          display: "inline-flex", alignItems: "center", gap: 6,
          fontFamily: "var(--lys-font-mono)", fontSize: 10,
          color: "var(--lys-text-faint)",
        }}>
          <RefreshCw size={11} style={{ animation: "spin 1s linear infinite" }} />
          placing in pocket...
        </div>
      )}
      {poseError && (
        <div style={{
          position: "absolute", top: 8, right: 8, zIndex: 60,
          padding: "5px 10px",
          background: "rgba(220,38,38,0.10)",
          border: "1px solid rgba(220,38,38,0.30)",
          borderRadius: 6, backdropFilter: "blur(8px)",
          fontSize: 10, color: "#dc2626",
        }}>pose error: {poseError}</div>
      )}

      {/* ─── BOTTOM-RIGHT: Key contacts panel (top 8 residues) ─────
          Laid out as a 4-column grid (residue | atom | tier | distance)
          so values line up vertically across rows. Fixed column widths
          stop the longest residue/distance from shifting the layout. */}
      {pose && pose.key_contacts.length > 0 && (
        <div style={{
          position: "absolute", bottom: 8, right: 8, zIndex: 50,
          padding: "8px 10px 6px",
          background: "rgba(255,255,255,0.95)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 6, backdropFilter: "blur(8px)",
          width: 300, maxHeight: 220, overflow: "auto",
          fontFamily: "var(--lys-font-mono)", fontSize: 10,
          boxShadow: "0 4px 12px rgba(15,23,42,0.10)",
        }}>
          <div style={{
            fontSize: 8.5, color: "var(--lys-text-faint)",
            letterSpacing: "0.06em", textTransform: "uppercase",
            fontWeight: 700, marginBottom: 6,
          }}>
            Key contacts · top 8
          </div>
          <div style={{
            // Vertical stack of rows. Each row is its own flex
            // container with continuous bg tint — the previous CSS-
            // grid attempt produced 4 disconnected segments because
            // the grid columnGap interrupts the row background.
            display: "flex", flexDirection: "column", gap: 2,
          }}>
          {pose.key_contacts.slice(0, 8).map((c) => {
            // Classify each contact by biology, not by simple "closer = better".
            // Backend thresholds: clash < 1.5Å, contact ≤ 4.0Å.
            //   < 1.5Å        → clash (red) — atoms colliding, repulsive
            //   1.5–2.5Å      → tight (deep green) — strong H-bond / salt bridge
            //   2.5–3.5Å      → good  (green) — standard H-bond / vdW
            //   3.5–4.0Å      → weak  (amber) — peripheral, low contribution
            //   ≥ 4.0Å        → none  (grey)
            // Atoms flagged in pose.clashing_atoms[] win over distance —
            // they're authoritative since the backend resolved any
            // distance ties.
            const isClashAtom = pose.clashing_atoms.includes(c.ligand_atom_idx);
            const tier =
              isClashAtom || c.distance_a < 1.5 ? "clash"
              : c.distance_a < 2.5 ? "tight"
              : c.distance_a < 3.5 ? "good"
              : c.distance_a < 4.0 ? "weak"
              : "none";
            const TIER = {
              clash: { fg: "#dc2626", bg: "rgba(220,38,38,0.10)", label: "CLASH" },
              tight: { fg: "#047857", bg: "rgba(5,150,105,0.10)",  label: "TIGHT" },
              good:  { fg: "#10b981", bg: "rgba(16,185,129,0.08)", label: "GOOD"  },
              weak:  { fg: "#ca8a04", bg: "rgba(202,138,4,0.10)",  label: "WEAK"  },
              none:  { fg: "var(--lys-text-faint)", bg: "transparent", label: "—" },
            } as const;
            const t = TIER[tier];
            const title = `Ligand atom ${c.ligand_atom_idx} (${c.ligand_element}) → ${c.residue} at ${c.distance_a}Å — ${t.label}`;
            return (
              <div
                key={`${c.residue}-${c.ligand_atom_idx}`}
                title={title}
                style={{
                  display: "flex", alignItems: "center",
                  gap: 8,
                  padding: "4px 8px",
                  background: t.bg,
                  borderRadius: 4,
                  // Vertical accent stripe on the left in the tier
                  // colour — it's the strongest signal because the
                  // eye scans the leftmost column first.
                  borderLeft: `3px solid ${t.fg}`,
                }}>
                <span style={{
                  fontWeight: 700, color: "#0891b2",
                  width: 56, flexShrink: 0,
                }}>
                  {c.residue}
                </span>
                <span style={{
                  width: 50, flexShrink: 0,
                  color: "var(--lys-text-dim)", fontSize: 9.5,
                }}>
                  a{c.ligand_atom_idx}({c.ligand_element})
                </span>
                <span style={{
                  width: 40, flexShrink: 0,
                  fontSize: 8, fontWeight: 700, letterSpacing: "0.05em",
                  color: t.fg,
                }}>
                  {t.label}
                </span>
                <span style={{
                  flex: 1, textAlign: "right",
                  color: t.fg, fontWeight: 700,
                }}>
                  {c.distance_a}Å
                </span>
              </div>
            );
          })}
          </div>
          {pose.binding_atoms.length > 0 && (
            <div style={{
              fontSize: 8.5, color: "var(--lys-text-faint)",
              marginTop: 4, paddingTop: 4,
              borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
            }}>
              <span style={{ color: "#10b981", fontWeight: 700 }}>{pose.binding_atoms.length}</span> binding atoms
              {pose.clashing_atoms.length > 0 && (
                <> · <span style={{ color: "#dc2626", fontWeight: 700 }}>{pose.clashing_atoms.length}</span> clashing</>
              )}
            </div>
          )}
        </div>
      )}

      {/* ─── BOTTOM-LEFT: Closest known antibiotic match (kept) ──── */}
      {p.smiles && match?.best && (
        <div
          title="Top-K closest known antibiotic by Morgan-2 Tanimoto similarity"
          style={{
            position: "absolute", bottom: 8, left: 8,
            padding: "5px 10px",
            background: tc.bg,
            border: `1px solid ${tc.border}`,
            borderRadius: 6,
            display: "flex", flexDirection: "column", gap: 2,
            fontFamily: "var(--lys-font-body)", fontSize: 10.5,
            color: tc.fg, backdropFilter: "blur(8px)",
            zIndex: 50, maxWidth: 230,
            boxShadow: "0 4px 12px rgba(15,23,42,0.10)",
          }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{
              fontFamily: "var(--lys-font-mono)", fontWeight: 800,
              fontSize: 8.5, letterSpacing: "0.08em",
              padding: "1px 4px", borderRadius: 2,
              background: tc.fg, color: "white",
            }}>{tc.label}</span>
            <span style={{ fontWeight: 700 }}>≈ {match.best.name}</span>
            <span style={{ marginLeft: "auto", fontFamily: "var(--lys-font-mono)", fontWeight: 700 }}>
              {(sim * 100).toFixed(0)}%
            </span>
          </div>
          <div style={{ fontSize: 9, opacity: 0.85 }}>
            {match.best.drug_class}
          </div>
        </div>
      )}
    </div>
  );
}

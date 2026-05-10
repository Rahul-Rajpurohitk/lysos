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
import { useEffect, useState, useRef, useMemo } from "react";
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
  /** Backend-curated active-site residue numbers + chain. Used to
   *  drive the Pocket toggle (filter view to these residues) and the
   *  pocket highlight overlay (color them green on the cartoon). */
  active_site_chain?: string;
  active_site_residues?: number[];
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
  /** Cross-link from the Resistance Escape Map (or any sibling card): a
   *  residue position to flash as the active contact in 3D. We treat it
   *  as a higher-priority pinned contact than the local hover/click —
   *  external focus wins. */
  externalFocusedResidue?: number | null;
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
  // Key Contacts panel — collapses to a single button at bottom-right
  // until the user clicks to expand. Default closed so the protein
  // ribbon has the whole canvas; the binding-atom counter on the button
  // gives at-a-glance status without consuming layout space.
  const [contactsOpen, setContactsOpen] = useState<boolean>(false);
  // Closest-known antibiotic badge — collapsed (compact pill) by
  // default; click expands into a detail panel with mechanism,
  // targets, year, top-3 matches, and a reading guide.
  const [matchOpen, setMatchOpen] = useState<boolean>(false);
  // Key Contacts → 3D viewer cross-link.
  //   hoverContact   — fleeting (mouseenter/mouseleave). Lights up
  //                    the matching residue while the cursor's on the row.
  //   pinnedContact  — sticky (single click on a row). Stays highlighted
  //                    until you click the same row again or click another.
  // Pinned wins over hover for the displayed highlight.
  const [hoverContact, setHoverContact] = useState<{ resi: number; chain: string } | null>(null);
  const [pinnedContact, setPinnedContact] = useState<{ resi: number; chain: string } | null>(null);
  // External focus from the Resistance Escape Map card overrides local
  // hover/pinned state — when the user clicks a heatmap cell we want the
  // 3D viewer to flash that exact residue, regardless of where the cursor is.
  const externalFocus = p.externalFocusedResidue;
  const externalContact = useMemo(() => {
    if (externalFocus == null) return null;
    const chain = selectedTarget?.active_site_chain ?? "A";
    return { resi: externalFocus, chain };
  }, [externalFocus, selectedTarget?.active_site_chain]);
  const activeContact = externalContact ?? pinnedContact ?? hoverContact;
  // Resistance robustness — fetched from /chem/resistance/predict
  // when SMILES + target are set. Same backend Service 2 uses; we
  // surface the headline robustness score as a chip on the viewer
  // so the user sees clinical-resistance risk at a glance without
  // opening the resistance escape map.
  const [robustness, setRobustness] = useState<{ score: number; nEscape: number; nTotal: number } | null>(null);
  useEffect(() => {
    if (!p.smiles || !selectedTargetId) { setRobustness(null); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${p.apiBase}/workbench/chem/resistance/predict`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ smiles: p.smiles, pdb_id: selectedTargetId }),
        });
        if (!r.ok) return;
        const d = await r.json();
        if (cancelled) return;
        setRobustness({
          score: d.robustness_score ?? 0,
          nEscape: d.n_escape_vectors ?? 0,
          nTotal: d.n_total_known_mutations ?? 0,
        });
      } catch {/*noop*/}
    }, 350);
    return () => { cancelled = true; clearTimeout(t); };
  }, [p.smiles, selectedTargetId, p.apiBase]);
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

  // Target picker — rendered as a button injected into Mol3D's
  // toolbar via the leftToolbarSlot prop. Same JSX, just lives in
  // the toolbar row now instead of a floating canvas overlay.
  const targetPickerSlot = (
    <div style={{
      position: "relative",
      display: "flex", alignItems: "center", gap: 6,
    }}>
      <button
        type="button"
        onClick={() => setPickerOpen((o) => !o)}
        title="Pick the validated target this candidate is designed against"
        style={{
          padding: "2px 7px", height: 22,
          // Match 2D builder's navBtnStyle active treatment — 10%
          // accent tint + accent border + accent text. No solid-dark
          // fill (the design system doesn't use harsh black anywhere).
          background: pickerOpen ? "rgba(8,145,178,0.10)" : "transparent",
          color: pickerOpen ? "#0891b2" : "var(--lys-text-dim)",
          border: `1px solid ${pickerOpen ? "#0891b2" : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
          borderRadius: 4,
          display: "inline-flex", alignItems: "center", gap: 4,
          fontFamily: "inherit", fontSize: 9.5,
          cursor: "pointer",
          fontWeight: 500,
        }}>
        <Target size={11} style={{ color: "#0891b2" }} />
        <span>{selectedTarget?.short_name ?? "pick target"}</span>
        {selectedTarget && (
          <span style={{ fontSize: 8.5, opacity: 0.6 }}>
            · {selectedTarget.pdb_id}
          </span>
        )}
      </button>
      {pickerOpen && targets.length > 0 && (
        <div style={{
          position: "absolute", top: "calc(100% + 6px)", left: 0,
          background: "white",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 6,
          boxShadow: "0 8px 24px rgba(15,23,42,0.18)",
          minWidth: 320, maxWidth: 460, padding: 4,
          zIndex: 100, fontFamily: "var(--lys-font-body)",
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
  );

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <Mol3D
        apiBase={p.apiBase}
        smiles={p.smiles}
        pathogen={p.pathogen}
        onMoleculeEdit={p.onMoleculeEdit}
        pdbOverride={selectedTargetId}
        pocketResidues={(() => {
          // Pocket = union of curated active-site residues + the residues
          // actually contacted by the docked ligand. Without the union,
          // hovering a Key Contact (e.g. TYR337) highlighted a residue
          // that wasn't in the rendered pocket — visually disconnected
          // from the green sticks. With the union, every Key Contact
          // residue IS rendered, so the hover highlight always lands on
          // a visible stick. Curated set is the fallback when no pose
          // exists yet.
          const curated = selectedTarget?.active_site_residues ?? [];
          const fromPose = pose?.key_contacts
            ?.map((c) => parseInt(c.residue.match(/(\d+)/)?.[1] ?? "0", 10))
            .filter((n) => n > 0) ?? [];
          return Array.from(new Set([...curated, ...fromPose]));
        })()}
        pocketChain={selectedTarget?.active_site_chain ?? "A"}
        leftToolbarSlot={targetPickerSlot}
        hoverResidue={activeContact}
      />

      {/* ─── (legacy floating target picker — now in the toolbar) ─── */}
      <div style={{
        position: "absolute", top: -9999, left: -9999, zIndex: 60,
        display: "none",
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

      {/* ─── BELOW-TOOLBAR-LEFT: Pocket info chip ─────────────────
          Reads the curated active-site list for the selected target
          and reports residue count + character (hydrophobic / polar /
          mixed). Tells the user at a glance what kind of binding
          environment the pocket offers without opening Key Contacts. */}
      {selectedTarget?.active_site_residues && selectedTarget.active_site_residues.length > 0 && pose && (() => {
        // Hydrophobic vs polar character — derived from the residues
        // we know are in the pocket (key_contacts overlap with the
        // curated active-site list). Hydrophobic: ALA, VAL, LEU, ILE,
        // PHE, MET, TRP, PRO, GLY (loosely). Polar: SER, THR, TYR,
        // ASN, GLN, HIS. Charged: LYS, ARG, ASP, GLU.
        const HYDRO = new Set(["ALA","VAL","LEU","ILE","PHE","MET","TRP","PRO","GLY","CYS"]);
        const POLAR = new Set(["SER","THR","TYR","ASN","GLN","HIS"]);
        const CHARGED = new Set(["LYS","ARG","ASP","GLU"]);
        let h = 0, p = 0, c = 0;
        for (const k of pose.key_contacts.slice(0, 8)) {
          const code = k.residue.slice(0, 3).toUpperCase();
          if (HYDRO.has(code)) h++;
          else if (POLAR.has(code)) p++;
          else if (CHARGED.has(code)) c++;
        }
        const total = Math.max(1, h + p + c);
        const character = h / total > 0.5 ? "hydrophobic" : c / total > 0.4 ? "charged" : p / total > 0.4 ? "polar" : "mixed";
        const charColor = character === "hydrophobic" ? "#a16207" : character === "charged" ? "#7c3aed" : character === "polar" ? "#0891b2" : "#475569";
        return (
          <div
            title={`Pocket character — ${h} hydrophobic · ${p} polar · ${c} charged residues among the top contacts. '${character}' tells you what kind of drug fits best (hydrophobic pocket → lipophilic drugs; polar pocket → H-bond rich drugs; charged → ionic drugs).`}
            style={{
              position: "absolute", top: 44, left: 8, zIndex: 60,
              padding: "4px 9px",
              background: "rgba(16,185,129,0.10)",
              border: "1px solid rgba(16,185,129,0.30)",
              borderRadius: 5, backdropFilter: "blur(8px)",
              display: "inline-flex", alignItems: "center", gap: 7,
              fontFamily: "var(--lys-font-mono)", fontSize: 10,
              color: "#047857", fontWeight: 700,
            }}>
            <span>pocket {selectedTarget.active_site_residues.length}res</span>
            <span style={{ opacity: 0.5, fontWeight: 500 }}>·</span>
            <span style={{ color: charColor }}>{character}</span>
          </div>
        );
      })()}

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

      {/* ─── BELOW-POSE-CHIP: Resistance robustness chip ─────────────
          Pulls /chem/resistance/predict for the current candidate +
          target. Shows tier (ROBUST / WEAK / VULNERABLE) + score so
          the user can see clinical-resistance risk at a glance —
          without opening the full Resistance Escape Map. Click the
          icon for the full breakdown (the resistance map sub-card). */}
      {robustness && pose && (() => {
        const r = robustness.score;
        const tier = r >= 0.7 ? "robust" : r >= 0.4 ? "moderate" : "vulnerable";
        const RC = {
          robust:     { fg: "#10b981", bg: "rgba(16,185,129,0.10)", border: "rgba(16,185,129,0.40)" },
          moderate:   { fg: "#ca8a04", bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.40)"  },
          vulnerable: { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.40)"  },
        }[tier];
        return (
          <div
            title={`Resistance robustness vs ${robustness.nTotal} curated CARD clinical mutations for this target. ${robustness.nEscape > 0 ? `${robustness.nEscape} atom${robustness.nEscape === 1 ? "" : "s"} above the 0.30 escape threshold.` : "No atoms above the escape threshold — this candidate's contact pattern doesn't overlap with known clinical mutations."}`}
            style={{
              position: "absolute", top: 80, right: 8, zIndex: 60,
              padding: "4px 9px",
              background: RC.bg, border: `1px solid ${RC.border}`,
              borderRadius: 5, backdropFilter: "blur(8px)",
              display: "inline-flex", alignItems: "center", gap: 7,
              fontFamily: "var(--lys-font-mono)", fontSize: 10,
              color: RC.fg, fontWeight: 700,
            }}>
            <span style={{ textTransform: "uppercase", letterSpacing: "0.04em" }}>{tier}</span>
            <span style={{ opacity: 0.55, fontWeight: 500 }}>·</span>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>{r.toFixed(2)}</span>
            {robustness.nEscape > 0 && (
              <>
                <span style={{ opacity: 0.55, fontWeight: 500 }}>·</span>
                <span title="atoms above escape threshold">{robustness.nEscape} esc</span>
              </>
            )}
          </div>
        );
      })()}
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

      {/* ─── BOTTOM-RIGHT: Key contacts panel ─────────────────────
          Collapsible. Default: collapsed to a single button with the
          binding-atoms count + a clash counter. Click to expand into
          the full top-8 residue table. Click the header to collapse
          back. Same affordance pattern as the 2D builder's Properties/
          Build dock buttons. */}
      {pose && pose.key_contacts.length > 0 && (() => {
        if (!contactsOpen) {
          return (
            <button
              type="button"
              onClick={() => setContactsOpen(true)}
              title={`Show top ${Math.min(8, pose.key_contacts.length)} residue contacts · ${pose.binding_atoms.length} binding atoms${pose.clashing_atoms.length > 0 ? ` · ${pose.clashing_atoms.length} clashing` : ""}`}
              style={{
                position: "absolute", bottom: 8, right: 8, zIndex: 50,
                padding: "5px 10px",
                background: "rgba(255,255,255,0.95)",
                border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
                borderRadius: 5, backdropFilter: "blur(8px)",
                boxShadow: "0 1px 4px rgba(15,23,42,0.06)",
                fontFamily: "var(--lys-font-mono)", fontSize: 9.5, fontWeight: 700,
                letterSpacing: "0.04em", textTransform: "uppercase",
                color: "var(--lys-text)",
                cursor: "pointer",
                display: "inline-flex", alignItems: "center", gap: 6,
              }}>
              <span style={{ fontSize: 7, opacity: 0.7 }}>▶</span>
              key contacts
              <span style={{
                color: "#10b981", fontWeight: 700,
              }}>{pose.binding_atoms.length}</span>
              {pose.clashing_atoms.length > 0 && (
                <span style={{ color: "#dc2626", fontWeight: 700 }}>
                  · {pose.clashing_atoms.length} clash
                </span>
              )}
            </button>
          );
        }
        return (
        <div style={{
          position: "absolute", bottom: 8, right: 8, zIndex: 50,
          padding: "0 0 6px",
          background: "rgba(255,255,255,0.95)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 6, backdropFilter: "blur(8px)",
          width: 300, maxHeight: 240, overflow: "auto",
          fontFamily: "var(--lys-font-mono)", fontSize: 10,
          boxShadow: "0 4px 12px rgba(15,23,42,0.10)",
        }}>
          <div
            onClick={() => setContactsOpen(false)}
            title="Click to collapse"
            style={{
              padding: "8px 10px 6px",
              fontSize: 8.5, color: "var(--lys-text-faint)",
              letterSpacing: "0.06em", textTransform: "uppercase",
              fontWeight: 700,
              display: "flex", alignItems: "center", gap: 5,
              cursor: "pointer", userSelect: "none",
              borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
              marginBottom: 6,
            }}>
            <span style={{ fontSize: 7, opacity: 0.7 }}>▼</span>
            Key contacts · top 8
            <span style={{ flex: 1 }} />
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
            // Parse "SER365" → 365 + chain "A" (default); chain
            // override could come from the contact data later.
            const resiMatch = c.residue.match(/(\d+)/);
            const resi = resiMatch ? parseInt(resiMatch[1], 10) : 0;
            const chain = c.chain || "A";
            const isHover = hoverContact?.resi === resi && hoverContact?.chain === chain;
            const isPinned = pinnedContact?.resi === resi && pinnedContact?.chain === chain;
            const isActive = isHover || isPinned;
            return (
              <div
                key={`${c.residue}-${c.ligand_atom_idx}`}
                title={isPinned
                  ? `${title}  (pinned — click again to unpin)`
                  : `${title}  (click to pin highlight)`}
                onMouseEnter={() => setHoverContact({ resi, chain })}
                onMouseLeave={() => setHoverContact(null)}
                onClick={() => {
                  // Click toggles pinned state: same row → unpin,
                  // different row → switch the pin.
                  setPinnedContact((cur) => (
                    cur?.resi === resi && cur?.chain === chain
                      ? null
                      : { resi, chain }
                  ));
                }}
                style={{
                  display: "flex", alignItems: "center",
                  gap: 8,
                  padding: "4px 8px",
                  background: isActive ? "rgba(245,158,11,0.12)" : t.bg,
                  borderRadius: 4,
                  // Pinned rows get a thicker, fully-saturated amber
                  // bar so they read as 'sticky-active' even when the
                  // cursor moves away. Hover-only rows get the same
                  // amber but at the normal stripe width.
                  borderLeft: `${isPinned ? 4 : 3}px solid ${isActive ? "#f59e0b" : t.fg}`,
                  boxShadow: isPinned ? "inset 0 0 0 1px rgba(245,158,11,0.20)" : "none",
                  cursor: "pointer",
                  transition: "background 0.10s, border-left-color 0.10s, border-left-width 0.10s",
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
              <span style={{ color: "#10b981", fontWeight: 700, paddingLeft: 10 }}>{pose.binding_atoms.length}</span>
              <span style={{ paddingLeft: 4 }}>binding atoms</span>
              {pose.clashing_atoms.length > 0 && (
                <> · <span style={{ color: "#dc2626", fontWeight: 700 }}>{pose.clashing_atoms.length}</span> clashing</>
              )}
            </div>
          )}
        </div>
        );
      })()}

      {/* ─── BOTTOM-LEFT: Closest known antibiotic match.
            Compact pill by default, click to expand into a detail
            panel with mechanism + targets + year + top-3 matches list. */}
      {p.smiles && match?.best && (
        <div
          style={{
            position: "absolute", bottom: 8, left: 8,
            zIndex: 50, maxWidth: 320,
          }}>
          {/* Compact pill — only when collapsed. When the user expands
              the detail card we hide this pill so the card carries
              the whole identity (avoids 'name shown twice' issue). */}
          {!matchOpen && (
            <button
              type="button"
              onClick={() => setMatchOpen(true)}
              title="Click to see full match info"
              style={{
                padding: "5px 10px",
                background: tc.bg,
                border: `1px solid ${tc.border}`,
                borderRadius: 6,
                display: "flex", flexDirection: "column", gap: 2,
                fontFamily: "var(--lys-font-body)", fontSize: 10.5,
                color: tc.fg, backdropFilter: "blur(8px)",
                boxShadow: "0 4px 12px rgba(15,23,42,0.10)",
                cursor: "pointer",
                textAlign: "left", width: "100%",
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
            </button>
          )}

          {matchOpen && (
            <div style={{
              padding: "10px 12px",
              background: tc.bg,
              border: `1px solid ${tc.border}`,
              borderRadius: 6,
              boxShadow: "0 8px 24px rgba(15,23,42,0.12)",
              backdropFilter: "blur(10px)",
              WebkitBackdropFilter: "blur(10px)",
              fontFamily: "var(--lys-font-body)", fontSize: 10,
              color: "var(--lys-text)",
              display: "flex", flexDirection: "column", gap: 10,
            }}>
              {/* Best match details — two-col grid: label | value.
                  The whole header row is the click-to-collapse target;
                  no separate × button. Chevron ▼ indicates the
                  affordance. */}
              <div>
                <div
                  onClick={() => setMatchOpen(false)}
                  title="Click to collapse"
                  style={{
                    display: "flex", alignItems: "center", gap: 6,
                    marginBottom: 6,
                    cursor: "pointer", userSelect: "none",
                  }}>
                  <span style={{
                    fontFamily: "var(--lys-font-mono)", fontWeight: 800,
                    fontSize: 8.5, letterSpacing: "0.08em",
                    padding: "1px 4px", borderRadius: 2,
                    background: tc.fg, color: "white",
                  }}>{tc.label}</span>
                  <span style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
                    letterSpacing: "0.06em", textTransform: "uppercase",
                    fontFamily: "var(--lys-font-mono)", fontWeight: 700 }}>
                    best match
                  </span>
                  <span style={{ flex: 1 }} />
                  <span style={{ fontSize: 9, color: tc.fg, opacity: 0.7 }}>▼</span>
                </div>
                {/* Header row: name + similarity */}
                <div style={{
                  display: "flex", alignItems: "baseline", gap: 6,
                  marginBottom: 5,
                }}>
                  <span style={{ fontWeight: 700, fontSize: 12, color: tc.fg }}>
                    {match.best.name}
                  </span>
                  <span style={{ flex: 1 }} />
                  <span style={{
                    fontFamily: "var(--lys-font-mono)",
                    fontSize: 9.5, fontWeight: 700, color: tc.fg,
                    fontVariantNumeric: "tabular-nums",
                  }}>
                    {(sim * 100).toFixed(0)}% similar
                  </span>
                </div>
                {/* Details grid */}
                <div style={{
                  display: "grid",
                  gridTemplateColumns: "60px 1fr",
                  rowGap: 3, columnGap: 8,
                  fontSize: 9.5,
                }}>
                  <span style={{ color: "var(--lys-text-faint)",
                    fontFamily: "var(--lys-font-mono)",
                    textAlign: "right" }}>class</span>
                  <span style={{ color: "var(--lys-text)" }}>{match.best.drug_class}</span>

                  <span style={{ color: "var(--lys-text-faint)",
                    fontFamily: "var(--lys-font-mono)",
                    textAlign: "right" }}>mechanism</span>
                  <span style={{ color: "var(--lys-text)" }}>{match.best.mechanism}</span>

                  {match.best.targets && match.best.targets.length > 0 && (
                    <>
                      <span style={{ color: "var(--lys-text-faint)",
                        fontFamily: "var(--lys-font-mono)",
                        textAlign: "right" }}>targets</span>
                      <span style={{ color: "var(--lys-text)" }}>{match.best.targets.join(", ")}</span>
                    </>
                  )}
                  {match.best.year > 0 && (
                    <>
                      <span style={{ color: "var(--lys-text-faint)",
                        fontFamily: "var(--lys-font-mono)",
                        textAlign: "right" }}>year</span>
                      <span style={{ color: "var(--lys-text)" }}>{match.best.year}</span>
                    </>
                  )}
                </div>
              </div>

              {/* Top-3 matches as a neat ranked list — circular rank
                  badge, drug name, percentage right-aligned. */}
              {match.matches && match.matches.length > 1 && (
                <div>
                  <div style={{ fontSize: 8.5, color: "var(--lys-text-faint)",
                    letterSpacing: "0.06em", textTransform: "uppercase",
                    fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                    marginBottom: 6 }}>
                    top {Math.min(3, match.matches.length)} matches
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
                    {match.matches.slice(0, 3).map((m, i) => (
                      <div key={i} style={{
                        display: "flex", alignItems: "center", gap: 7,
                        fontSize: 10.5,
                        padding: "1px 0",
                      }}>
                        <span style={{
                          width: 16, height: 16, flexShrink: 0,
                          borderRadius: "50%",
                          background: i === 0 ? tc.bg : "rgba(0,0,0,0.04)",
                          color: i === 0 ? tc.fg : "var(--lys-text-faint)",
                          display: "grid", placeItems: "center",
                          fontFamily: "var(--lys-font-mono)",
                          fontSize: 8.5, fontWeight: 700,
                        }}>
                          {i + 1}
                        </span>
                        <span style={{
                          fontWeight: i === 0 ? 700 : 500,
                          flex: 1,
                          color: i === 0 ? tc.fg : "var(--lys-text)",
                        }}>
                          {m.name}
                        </span>
                        <span style={{ fontFamily: "var(--lys-font-mono)",
                          fontSize: 9.5,
                          color: i === 0 ? tc.fg : "var(--lys-text-dim)",
                          fontWeight: i === 0 ? 700 : 500,
                          fontVariantNumeric: "tabular-nums",
                          width: 32, textAlign: "right",
                        }}>
                          {(m.similarity * 100).toFixed(0)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Reading guide — accented tip block instead of a bare
                  hairline'd footer line. */}
              <div style={{
                fontSize: 9.5, lineHeight: 1.45,
                padding: "6px 9px",
                borderRadius: 4,
                background: tc.bg,
                color: tc.fg,
                display: "flex", alignItems: "flex-start", gap: 6,
              }}>
                <span style={{ fontWeight: 700, flexShrink: 0 }}>↳</span>
                <span>
                  {sim < 0.30 ? <><b>Novel scaffold.</b> Fresh design space — not a known-drug clone, patentability looks promising.</>
                   : sim < 0.70 ? <><b>Moderate analog.</b> Shares chemistry with a known drug — watch for cross-resistance and freedom-to-operate.</>
                   : <><b>Near-known.</b> Effectively a clone of an existing drug — patentability concern.</>}
                </span>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

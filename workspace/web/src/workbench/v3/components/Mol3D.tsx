import { useEffect, useRef, useState } from "react";
import { ChevronDown, Eye, EyeOff, RefreshCw, Layers } from "lucide-react";
import clsx from "clsx";

interface Mol3DProps {
  apiBase: string;
  smiles: string | null;
  pathogen: string;
  /** When the user clicks an atom on the ligand AND has an edit-op armed,
   *  Mol3D POSTs to /workbench/molecule/edit and bubbles the new canonical
   *  SMILES upward via this callback. WorkbenchV3 then injects it as a
   *  `candidate_added` event so the agents debate the user's edit.  */
  onMoleculeEdit?: (newSmiles: string, op: EditOp) => void;
  /** Override the pathogen-default PDB. Used by Mol3DTheaterWindow when
   *  the user picks a specific target from the curated PATHOGEN_TARGETS
   *  map (e.g. PBP2a vs MurA for MRSA). When set, takes precedence over
   *  the legacy PATHOGEN_PDB default. */
  pdbOverride?: string | null;
  /** Active-site residue numbers (PDB-numbered). When set, the Pocket
   *  toggle filters the rendered protein to just these residues + the
   *  ligand. Always rendered as a green highlight overlay so the
   *  pocket is visible even in full-protein view. */
  pocketResidues?: number[];
  /** PDB chain identifier the active site lives on. NGL selection
   *  qualifier — without this we'd match the residue numbers across
   *  every chain. */
  pocketChain?: string;
  /** Slot rendered at the LEFT of the toolbar — used by Mol3DTheaterWindow
   *  to inject the target picker into the toolbar row instead of as a
   *  floating overlay on the canvas. */
  leftToolbarSlot?: React.ReactNode;
  /** Residue to flash a hover-highlight on. Set by the parent when the
   *  user hovers a row in the Key Contacts panel — the matching
   *  residue in the 3D viewer pulses orange so the user can see WHERE
   *  that contact lives in space. Cleared on mouseleave. */
  hoverResidue?: { resi: number; chain: string } | null;
}

type EditOp =
  | { kind: "swap"; element: string }
  | { kind: "methyl" }
  | { kind: "break" };

// ARMED_OPS removed — atom edits live in the 2D builder; the 3D
// theater is a pure viewer now. EditOp type kept because the shared
// onMoleculeEdit callback signature still references it (other 3D
// integrations may bring back inline edits later).

type Representation = "Cartoon" | "Surface" | "Sticks" | "Spheres";

// Pathogen → canonical PDB id.
const PATHOGEN_PDB: Record<string, string> = {
  MRSA: "1MWT",
  Mtb: "5DPX",
  "EColi-CRE": "1ERK",
  KpneuCRE: "5OZH",
  Abaum: "5KFP",
  Paer: "4U5G",
  VRE: "1NKW",
  NGono: "3FIH",
};

export function Mol3D({ apiBase, smiles, pathogen, onMoleculeEdit, pdbOverride, pocketResidues, pocketChain, leftToolbarSlot, hoverResidue }: Mol3DProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const stageObj = useRef<any>(null);
  const proteinComp = useRef<any>(null);
  const ligandComp = useRef<any>(null);
  // Tracks the click-to-focus camera mode. 'overview' = both visible
  // (autoView on stage). 'protein' = zoomed on protein. 'ligand' =
  // zoomed on ligand. Re-clicking the focused component returns to
  // 'overview'. Lives in a ref (not state) because the click handler
  // is registered once at NGL stage init and we don't want to tear it
  // down on every re-render.
  const focusedRef = useRef<"overview" | "protein" | "ligand">("overview");

  const [representation, setRepresentation] = useState<Representation>("Cartoon");
  // Wireframe + Spin removed from the toolbar (pure viewer). Locked to
  // false; if a future feature wants them back, restore the toggles
  // and re-introduce the setters.
  const wireframe = false;
  const [pocketOnly, setPocketOnly] = useState(true);
  const spin = false;
  const [error, setError] = useState<string | null>(null);
  const [pdb, setPdb] = useState<string>(PATHOGEN_PDB[pathogen] ?? "5DPX");
  const [armedOpId, setArmedOpId] = useState<string | null>(null);
  const armedOpRef = useRef<EditOp | null>(null);
  const [editStatus, setEditStatus] = useState<string | null>(null);

  // Initialize stage + wire pick handler for drag-edit chemistry.
  useEffect(() => {
    if (!stageRef.current) return;
    let stage: any = null;
    let resizeObs: ResizeObserver | null = null;
    let cancelled = false;

    // Wait for the stage container to have real dimensions before
    // initializing NGL. If we init at 0×0, NGL caches a broken WebGL
    // context that handleResize/autoView can't fully recover from.
    // This is the root cause of the empty-viewer bug in tab mode.
    const waitForSize = (): Promise<void> => new Promise((resolve) => {
      const check = () => {
        if (cancelled) return resolve();
        const r = stageRef.current?.getBoundingClientRect();
        if (r && r.width >= 50 && r.height >= 50) return resolve();
        requestAnimationFrame(check);
      };
      check();
    });

    (async () => {
      try {
        await waitForSize();
        if (cancelled) return;
        const NGL = await import("ngl");
        if (cancelled) return;
        stage = new NGL.Stage(stageRef.current!, {
          backgroundColor: "#ffffff",
          quality: "medium",
        });
        stageObj.current = stage;
        stage.setSpin(spin);

        // Click handler — two roles:
        //   1. Edit mode (op armed): click ligand atom → apply edit
        //      [legacy path; kept for future re-enabling. ARMED_OPS
        //       removed from toolbar so this branch is currently
        //       inert in normal use.]
        //   2. Focus toggle (no op armed): click protein → zoom on
        //      protein. Click ligand → zoom on ligand. Click empty
        //      space OR re-click the currently-focused component →
        //      zoom back out to fit both. NGL's `clicked` signal only
        //      fires on a clean click (mouse didn't drag) so it
        //      doesn't fight rotation.
        stage.signals.clicked.add((pick: any) => {
          // Edit branch — preserved for future use.
          const op = armedOpRef.current;
          if (op && smilesRef.current && pick?.atom && ligandComp.current
              && pick.component === ligandComp.current) {
            handleAtomEdit(op, pick.atom.index, pick.bond?.index);
            return;
          }

          // Focus-toggle branch.
          const target = pick?.component ?? null;
          const focused = focusedRef.current;
          if (!target) {
            // Clicked background → reset to overview.
            focusedRef.current = "overview";
            try { stage.autoView?.(400); } catch {/*noop*/}
            return;
          }
          // Re-click on currently-focused component → zoom out.
          const isProtein = target === proteinComp.current;
          const isLigand = target === ligandComp.current;
          if ((isProtein && focused === "protein")
              || (isLigand && focused === "ligand")) {
            focusedRef.current = "overview";
            try { stage.autoView?.(400); } catch {/*noop*/}
            return;
          }
          // Otherwise focus on the clicked component.
          if (isProtein) {
            focusedRef.current = "protein";
            try { proteinComp.current?.autoView?.(400); } catch {/*noop*/}
          } else if (isLigand) {
            focusedRef.current = "ligand";
            try { ligandComp.current?.autoView?.(400); } catch {/*noop*/}
          }
        });

        // ResizeObserver — handles parent resizes after init (Allotment
        // drag, whiteboard ↔ tabs switch, viewport resize).
        if (stageRef.current) {
          let resizeRaf = 0;
          resizeObs = new ResizeObserver(() => {
            if (resizeRaf) cancelAnimationFrame(resizeRaf);
            resizeRaf = requestAnimationFrame(() => {
              try {
                stage?.handleResize?.();
                stage?.autoView?.(300);
              } catch { /* noop */ }
            });
          });
          resizeObs.observe(stageRef.current);
        }
      } catch (e: any) {
        setError(`NGL init failed: ${e.message}`);
      }
    })();
    return () => {
      cancelled = true;
      try { resizeObs?.disconnect(); } catch { /* noop */ }
      if (stage) stage.dispose();
    };
  }, []);

  // Keep a ref to current SMILES so the click handler (closed over at stage
  // init time) always reads the latest value.
  const smilesRef = useRef<string | null>(smiles);
  useEffect(() => { smilesRef.current = smiles; }, [smiles]);

  // Apply an edit op to the ligand. POSTs to the backend RDKit editor.
  async function handleAtomEdit(op: EditOp, atomIdx: number, bondIdx?: number) {
    const cur = smilesRef.current;
    if (!cur) return;
    setEditStatus(`editing: ${describeOp(op)} on atom ${atomIdx}…`);
    try {
      const body: any = { smiles: cur };
      if (op.kind === "swap") {
        body.op = "swap_element";
        body.atom_index = atomIdx;
        body.new_element = op.element;
      } else if (op.kind === "methyl") {
        body.op = "add_methyl_at";
        body.atom_index = atomIdx;
      } else if (op.kind === "break") {
        if (bondIdx == null) {
          setEditStatus("click on a bond, not an atom, to break");
          setTimeout(() => setEditStatus(null), 1500);
          return;
        }
        body.op = "break_bond";
        body.bond_index = bondIdx;
      }
      const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.text();
        setEditStatus(`reject: ${err.slice(0, 60)}`);
        setTimeout(() => setEditStatus(null), 2200);
        return;
      }
      const d = await r.json();
      setEditStatus(`✓ ${cur} → ${d.smiles}`);
      setTimeout(() => setEditStatus(null), 2000);
      onMoleculeEdit?.(d.smiles, op);
      // Disarm after a successful edit — user re-arms for the next edit.
      setArmedOpId(null);
      armedOpRef.current = null;
    } catch (e: any) {
      setEditStatus(`error: ${e.message}`);
      setTimeout(() => setEditStatus(null), 2000);
    }
  }

  function describeOp(op: EditOp): string {
    if (op.kind === "swap") return `→${op.element}`;
    if (op.kind === "methyl") return "+CH₃";
    return "✂ bond";
  }

  // Update PDB when pathogen OR explicit override changes.
  // Override wins — Mol3DTheaterWindow's target picker uses this to drive
  // which curated target (PBP2a vs MurA for MRSA, InhA vs DprE1 for Mtb,
  // etc.) the chemistry agent reasons against.
  useEffect(() => {
    if (pdbOverride) {
      setPdb(pdbOverride);
    } else {
      setPdb(PATHOGEN_PDB[pathogen] ?? "5DPX");
    }
  }, [pathogen, pdbOverride]);

  // Load protein
  useEffect(() => {
    const stage = stageObj.current;
    if (!stage || !pdb) return;
    if (proteinComp.current) {
      stage.removeComponent(proteinComp.current);
      proteinComp.current = null;
    }
    setError(null);
    stage.loadFile(`https://files.rcsb.org/download/${pdb}.pdb`)
      .then((comp: any) => {
        proteinComp.current = comp;
        applyRepresentation(comp, representation, wireframe);
        // Use STAGE-level autoView so the camera fits all loaded
        // components (protein + any ligand). With an animated duration
        // — autoView(0) sometimes no-ops; an animated transition forces
        // the renderer to recompute the camera. The double-call (now
        // + 250ms) handles the case where the canvas was 0-sized at
        // init: by 250ms the Allotment pane has resized and the
        // ResizeObserver has fired, so handleResize+autoView lands on
        // a real canvas.
        stage.handleResize?.();
        stage.autoView?.(400);
        setTimeout(() => {
          try { stage.handleResize?.(); stage.autoView?.(400); } catch {/*noop*/}
        }, 250);
        setTimeout(() => {
          try { stage.handleResize?.(); stage.autoView?.(400); } catch {/*noop*/}
        }, 800);
      })
      .catch((e: any) => setError(`PDB ${pdb} load failed: ${e.message}`));
  }, [pdb]);

  // Update representation when toggles change
  useEffect(() => {
    const protein = proteinComp.current;
    const stage = stageObj.current;
    if (!protein || !stage) return;
    applyRepresentation(protein, representation, wireframe);
    // Camera refit:
    //   Pocket OFF → stage.autoView (full protein + ligand together)
    //   Pocket ON  → centre on the LIGAND, which is positioned in the
    //                pocket by chem/place-in-pocket. The pocket
    //                residues drawn nearby fall into the same tight
    //                frame, so the user doesn't have to hunt around.
    const refit = () => {
      try {
        stage.handleResize?.();
        if (pocketOnly && ligandComp.current) {
          ligandComp.current.autoView?.(400);
          focusedRef.current = "ligand";
        } else {
          stage.autoView?.(400);
          focusedRef.current = "overview";
        }
      } catch {/*noop*/}
    };
    refit();
    setTimeout(refit, 280);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [representation, wireframe, pocketOnly, pocketResidues?.join(","), pocketChain]);

  // Update spin
  useEffect(() => {
    stageObj.current?.setSpin(spin);
  }, [spin]);

  // Hover-highlight a single residue (driven by Key Contacts panel
  // hover from Mol3DTheaterWindow). Adds an orange ball+stick + halo
  // surface that flashes while hovered, removed on leave. The
  // representations are tagged with reprList refs we hold ourselves
  // so we can dispose them cleanly without disturbing the main reps.
  const hoverRepsRef = useRef<any[]>([]);
  useEffect(() => {
    const protein = proteinComp.current;
    if (!protein) return;
    // Tear down any previous hover highlight reps.
    for (const r of hoverRepsRef.current) {
      try { protein.removeRepresentation(r); } catch {/*noop*/}
    }
    hoverRepsRef.current = [];
    if (!hoverResidue) return;
    const sel = `${hoverResidue.resi} and :${hoverResidue.chain}`;
    try {
      const lic = protein.addRepresentation("licorice", {
        sele: sel, color: "#f59e0b", opacity: 1,
      });
      const sur = protein.addRepresentation("surface", {
        sele: sel, color: "#f59e0b", opacity: 0.30, useWorker: false,
      });
      hoverRepsRef.current = [lic, sur];
    } catch {/*noop*/}
  }, [hoverResidue?.resi, hoverResidue?.chain]);

  // Load ligand from our /workbench/molecule/3d endpoint.
  // Stage may not be initialized yet on first SMILES change — poll briefly.
  useEffect(() => {
    if (!smiles) return;
    let cancelled = false;
    let attempts = 0;
    const tryLoad = async () => {
      const stage = stageObj.current;
      if (!stage) {
        if (cancelled) return;
        attempts++;
        if (attempts > 30) {  // ~3s timeout waiting for NGL init
          setError("3D viewer init timeout — refresh the page");
          return;
        }
        setTimeout(tryLoad, 100);
        return;
      }
      // Stage ready — clear old ligand + fetch new SDF
      if (ligandComp.current) {
        try { stage.removeComponent(ligandComp.current); } catch {/*noop*/}
        ligandComp.current = null;
      }
      try {
        const r = await fetch(`${apiBase}/workbench/molecule/3d`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ smiles, optimize: true, add_hydrogens: false }),
        });
        if (!r.ok) {
          setError(`SDF fetch failed: ${r.status}`);
          return;
        }
        const d = await r.json();
        if (!d?.sdf) {
          setError("no SDF returned");
          return;
        }
        if (cancelled) return;
        const blob = new Blob([d.sdf], { type: "text/plain" });
        const comp = await stage.loadFile(blob, { ext: "sdf" });
        if (cancelled) return;
        ligandComp.current = comp;
        comp.addRepresentation("ball+stick", { multipleBond: true });
        // Stage-level autoView fits BOTH protein + ligand together.
        // Per-component autoView() on just the ligand would zoom to
        // the tiny ligand and lose the protein context.
        stage.handleResize?.();
        stage.autoView?.(400);
        setTimeout(() => {
          try { stage.handleResize?.(); stage.autoView?.(400); } catch {/*noop*/}
        }, 200);
        setError(null);
      } catch (e: any) {
        if (!cancelled) setError(`load error: ${e?.message ?? e}`);
      }
    };
    tryLoad();
    return () => { cancelled = true; };
  }, [smiles, apiBase]);

  function applyRepresentation(comp: any, rep: Representation, wire: boolean) {
    comp.removeAllRepresentations();
    const chain = pocketChain || "A";
    const pocketSel = pocketResidues && pocketResidues.length
      ? `(${pocketResidues.join(" or ")}) and :${chain}`
      : "polymer";

    // Pocket OFF — apply the rep dropdown to the FULL polymer so the
    // user sees what they picked. Cartoon is the default and reads
    // cleanly; Sticks/Spheres on 800 residues is dense but it's what
    // the dropdown promised. Pocket residues always overlaid in green
    // ball+stick so the binding site is visible regardless of rep.
    if (!pocketOnly) {
      const sel = "polymer";
      if (rep === "Cartoon") {
        comp.addRepresentation("cartoon", {
          sele: sel, colorScheme: "chainid", quality: "medium",
        });
      } else if (rep === "Surface") {
        comp.addRepresentation("surface", {
          sele: sel, opacity: 0.55, colorScheme: "electrostatic",
        });
      } else if (rep === "Sticks") {
        // CPK / element colouring — carbon grey, oxygen red, nitrogen
        // blue, sulfur yellow. Was 'chainid' which painted the entire
        // single-chain protein uniform red — chemically meaningless
        // and visually overwhelming.
        comp.addRepresentation("licorice", {
          sele: sel, colorScheme: "element",
        });
      } else {
        // Same CPK reasoning for spacefill view.
        comp.addRepresentation("spacefill", {
          sele: sel, colorScheme: "element",
        });
      }
      if (pocketResidues && pocketResidues.length) {
        comp.addRepresentation("licorice", {
          sele: pocketSel, color: "#10b981", opacity: 0.95,
        });
      }
    } else {
      // Pocket-only view — render JUST the active-site residues, no
      // grey context backbone (user found it visually noisy and
      // distracting). The ligand is the spatial anchor; pocket
      // residues sit nearby in tight frame.
      //
      // Colouring: 'element' (CPK) so carbons are grey, nitrogens
      // blue, oxygens red, sulfurs yellow. Way more readable than
      // uniform green when the user is doing close-up inspection.
      const sel = pocketSel;
      if (rep === "Cartoon") {
        comp.addRepresentation("cartoon", {
          sele: sel, colorScheme: "residueindex", quality: "high",
        });
        comp.addRepresentation("licorice", {
          sele: sel, colorScheme: "element",
        });
      } else if (rep === "Surface") {
        comp.addRepresentation("surface", { sele: sel, opacity: 0.55, colorScheme: "electrostatic" });
      } else if (rep === "Sticks") {
        comp.addRepresentation("licorice", { sele: sel, colorScheme: "element" });
      } else {
        comp.addRepresentation("spacefill", { sele: sel, colorScheme: "element" });
      }
    }

    if (wire) {
      comp.addRepresentation("backbone", { sele: "polymer", colorScheme: "uniform", color: "#8b949e" });
    }
  }

  function recenter() {
    // Stage-level autoView fits all loaded components together — better
    // than per-component autoView when both protein + ligand are loaded.
    stageObj.current?.handleResize?.();
    stageObj.current?.autoView?.(600);
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      {/* Toolbar — focused viewer controls only.
          Removed (per user UX pass):
            - Atom edit ops (→N/→O/→F/→Cl/+CH₃/✂ bond): editing happens in
              the 2D builder; the 3D theater is for VIEWING the docked
              pose. Editing here was confusing chrome with no clear benefit.
            - Wireframe toggle: niche overlay representation that mostly
              clutters the cartoon view.
            - Spin toggle: decorative, not core to the viewer's job.
          Kept:
            - Cartoon/Surface/Sticks/Spheres dropdown — meaningful
              representation choice for the protein.
            - Pocket: focuses on the active site, the part that actually
              matters for binding analysis.
            - Recenter: re-fits the camera if the user pans/zooms away. */}
      <div style={{
        padding: "0 10px",
        height: 32,
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
        display: "flex",
        alignItems: "center",
        gap: 5,
        fontFamily: "var(--lys-font-body)",
        fontSize: 9.5,
        color: "var(--lys-text-dim)",
        background: "var(--lys-bg-2)",
      }}>
        {/* Left slot — target picker, injected by Mol3DTheaterWindow */}
        {leftToolbarSlot}
        <span style={{ flex: 1 }} />
        <RepSelect value={representation} onChange={setRepresentation} />
        <ToggleBtn icon={pocketOnly ? <Eye size={11} /> : <EyeOff size={11} />} label="Pocket" active={pocketOnly} onClick={() => setPocketOnly((p) => !p)} />
        <button onClick={recenter} className="lys-3d-btn" title="Recenter — re-fit the camera around the loaded protein + ligand">
          <RefreshCw size={11} /> Recenter
        </button>
      </div>
      <div ref={stageRef} style={{
        flex: 1,
        minHeight: 200,
        position: "relative",
        background: "var(--lys-bg-2)",
        cursor: armedOpId ? "crosshair" : "default",
        overflow: "hidden",
      }}>
        {/* Empty / loading / error state — only shown when there's no
            ligand component yet, or when error is set. */}
        {!smiles && (
          <div style={{
            position: "absolute", inset: 0,
            display: "flex", flexDirection: "column",
            alignItems: "center", justifyContent: "center",
            color: "var(--lys-text-faint)", fontSize: 12,
            textAlign: "center", padding: 16, gap: 4,
            pointerEvents: "none",
          }}>
            <span style={{ fontSize: 20, opacity: 0.4 }}>⊕</span>
            <span>no candidate yet</span>
            <span style={{ fontSize: 10, fontFamily: "var(--lys-font-mono)" }}>
              pick a scaffold or run /design
            </span>
          </div>
        )}
        {error && (
          <div style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            color: "#dc2626",
            fontSize: 11,
            fontFamily: "var(--lys-font-mono)",
            textAlign: "center",
            background: "rgba(255,255,255,0.95)",
            padding: "6px 10px",
            borderRadius: 4,
            border: "1px solid rgba(220,38,38,0.3)",
            zIndex: 10,
          }}>
            ⚠ {error}
          </div>
        )}
        {editStatus && (
          <div style={{
            position: "absolute",
            bottom: 10,
            left: "50%",
            transform: "translateX(-50%)",
            padding: "4px 10px",
            background: "rgba(15, 23, 42, 0.88)",
            color: "white",
            fontSize: 11,
            fontFamily: "var(--lys-font-mono)",
            borderRadius: 6,
            pointerEvents: "none",
            maxWidth: "90%",
            whiteSpace: "nowrap",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}>
            {editStatus}
          </div>
        )}
      </div>
    </div>
  );
}

function RepSelect({ value, onChange }: { value: Representation; onChange: (v: Representation) => void }) {
  const [open, setOpen] = useState(false);
  const opts: Representation[] = ["Cartoon", "Surface", "Sticks", "Spheres"];
  return (
    <div style={{ position: "relative" }}>
      <button className="lys-3d-btn" onClick={() => setOpen((o) => !o)}>
        <Layers size={11} /> {value} <ChevronDown size={11} />
      </button>
      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 4px)", right: 0,
          background: "var(--lys-bg-2, #ffffff)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
          borderRadius: 6, padding: 3, zIndex: 100, minWidth: 110,
          boxShadow: "0 8px 20px rgba(15,23,42,0.08)",
        }}>
          {opts.map((o) => {
            const active = o === value;
            return (
              <button
                key={o}
                onClick={() => { onChange(o); setOpen(false); }}
                style={{
                  display: "block", width: "100%",
                  padding: "6px 10px",
                  border: 0,
                  background: active ? "var(--lys-accent-soft, rgba(16,185,129,0.10))" : "transparent",
                  color: active ? "#047857" : "var(--lys-text)",
                  fontSize: 11.5, fontFamily: "inherit",
                  textAlign: "left",
                  borderRadius: 4,
                  cursor: "pointer",
                  fontWeight: active ? 600 : 400,
                }}
                onMouseEnter={(e) => {
                  if (!active) (e.currentTarget as HTMLElement).style.background = "rgba(0,0,0,0.04)";
                }}
                onMouseLeave={(e) => {
                  if (!active) (e.currentTarget as HTMLElement).style.background = "transparent";
                }}
              >
                {o}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function ToggleBtn({ icon, label, active, onClick }: { icon: React.ReactNode; label: string; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={clsx("lys-3d-btn", active && "lys-3d-btn--active")}
      title={`${label} ${active ? "on" : "off"}`}
    >
      {icon} {label}
    </button>
  );
}

import { useEffect, useRef, useState } from "react";
import {
  ChevronDown, Eye, EyeOff, RotateCw, RefreshCw, Layers, Grid3x3,
} from "lucide-react";
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
}

type EditOp =
  | { kind: "swap"; element: string }
  | { kind: "methyl" }
  | { kind: "break" };

const ARMED_OPS: { id: string; label: string; op: EditOp }[] = [
  { id: "swap-N",  label: "→N",   op: { kind: "swap", element: "N" } },
  { id: "swap-O",  label: "→O",   op: { kind: "swap", element: "O" } },
  { id: "swap-F",  label: "→F",   op: { kind: "swap", element: "F" } },
  { id: "swap-Cl", label: "→Cl",  op: { kind: "swap", element: "Cl" } },
  { id: "methyl",  label: "+CH₃", op: { kind: "methyl" } },
  { id: "break",   label: "✂ bond", op: { kind: "break" } },
];

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

export function Mol3D({ apiBase, smiles, pathogen, onMoleculeEdit, pdbOverride }: Mol3DProps) {
  const stageRef = useRef<HTMLDivElement | null>(null);
  const stageObj = useRef<any>(null);
  const proteinComp = useRef<any>(null);
  const ligandComp = useRef<any>(null);

  const [representation, setRepresentation] = useState<Representation>("Cartoon");
  const [wireframe, setWireframe] = useState(false);
  const [pocketOnly, setPocketOnly] = useState(true);
  const [spin, setSpin] = useState(false);
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
    (async () => {
      try {
        const NGL = await import("ngl");
        stage = new NGL.Stage(stageRef.current!, {
          backgroundColor: "#ffffff",
          quality: "medium",
        });
        stageObj.current = stage;
        stage.setSpin(spin);

        // Click-to-edit: when an op is armed AND the user clicks an atom on
        // the ligand component, POST /workbench/molecule/edit and bubble the
        // new canonical SMILES up. NGL's PickingProxy resolves click → atom.
        stage.signals.clicked.add((pick: any) => {
          const op = armedOpRef.current;
          if (!op || !smilesRef.current) return;
          // Only accept clicks on the ligand component (not the protein)
          if (!pick || !pick.atom || !ligandComp.current) return;
          if (pick.component !== ligandComp.current) {
            setEditStatus("click on the ligand atoms only");
            setTimeout(() => setEditStatus(null), 1500);
            return;
          }
          const atomIdx = pick.atom.index;
          handleAtomEdit(op, atomIdx, pick.bond?.index);
        });

        // Resize observer — when the parent container's dimensions change
        // (e.g. switching whiteboard ↔ tabs, the pane being resized via
        // Allotment, etc.) NGL needs handleResize() to read the new
        // canvas bounds. Without this the viewer renders at its initial
        // 0×0 / stale dimensions and looks empty.
        if (stageRef.current) {
          resizeObs = new ResizeObserver(() => {
            try { stage?.handleResize?.(); } catch { /* noop */ }
          });
          resizeObs.observe(stageRef.current);
        }
      } catch (e: any) {
        setError(`NGL init failed: ${e.message}`);
      }
    })();
    return () => {
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
        comp.autoView();
      })
      .catch((e: any) => setError(`PDB ${pdb} load failed: ${e.message}`));
  }, [pdb]);

  // Update representation when toggles change
  useEffect(() => {
    if (proteinComp.current) {
      applyRepresentation(proteinComp.current, representation, wireframe);
    }
  }, [representation, wireframe]);

  // Update spin
  useEffect(() => {
    stageObj.current?.setSpin(spin);
  }, [spin]);

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
        comp.autoView();
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
    const sel = pocketOnly ? "polymer" : "polymer";
    if (rep === "Cartoon") {
      comp.addRepresentation("cartoon", { sele: sel, colorScheme: "chainid", quality: "medium" });
    } else if (rep === "Surface") {
      comp.addRepresentation("surface", { sele: sel, opacity: 0.5, colorScheme: "electrostatic" });
    } else if (rep === "Sticks") {
      comp.addRepresentation("licorice", { sele: sel });
    } else {
      comp.addRepresentation("spacefill", { sele: sel });
    }
    if (wire) {
      comp.addRepresentation("backbone", { sele: sel, colorScheme: "uniform", color: "#8b949e" });
    }
  }

  function recenter() {
    proteinComp.current?.autoView(800);
    ligandComp.current?.autoView(800);
  }

  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <div style={{
        padding: "6px 12px",
        borderBottom: "1px solid var(--lys-border)",
        display: "flex",
        alignItems: "center",
        gap: 8,
        fontSize: 11,
        color: "var(--lys-text-dim)",
      }}>
        <span style={{
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-accent)",
          fontWeight: 600,
        }}>3D</span>
        <span style={{ fontFamily: "var(--lys-font-mono)" }}>{pdb}</span>
        <ChevronDown size={12} />
        <span style={{
          fontFamily: "var(--lys-font-mono)",
          fontSize: 10,
          color: "var(--lys-text-faint)",
          maxWidth: 200,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {smiles ?? "—"}
        </span>
        <div style={{ flex: 1 }} />

        {/* Drag-edit chemistry palette: arm an op then click a ligand atom.
            Greyed out until a SMILES is loaded. */}
        <div style={{
          display: "flex",
          alignItems: "center",
          gap: 2,
          marginRight: 6,
          padding: "0 4px",
          opacity: smiles ? 1 : 0.45,
        }} aria-disabled={!smiles}>
          {ARMED_OPS.map((o) => {
            const active = armedOpId === o.id;
            return (
              <button
                key={o.id}
                disabled={!smiles}
                onClick={() => {
                  if (active) {
                    setArmedOpId(null);
                    armedOpRef.current = null;
                  } else {
                    setArmedOpId(o.id);
                    armedOpRef.current = o.op;
                    setEditStatus(`armed: ${o.label}. Click a ligand atom.`);
                  }
                }}
                title={`${o.label} — click to arm, then click a ligand atom`}
                style={{
                  border: 0,
                  background: active ? "var(--lys-accent)" : "transparent",
                  color: active ? "white" : "var(--lys-text-dim)",
                  fontFamily: "var(--lys-font-mono)",
                  fontSize: 10.5,
                  padding: "3px 6px",
                  borderRadius: 5,
                  cursor: smiles ? "pointer" : "not-allowed",
                  transition: "background 0.12s, color 0.12s",
                }}
                onMouseEnter={(e) => {
                  if (!active && smiles) e.currentTarget.style.background = "var(--lys-bg-hover, rgba(0,0,0,0.05))";
                }}
                onMouseLeave={(e) => {
                  if (!active) e.currentTarget.style.background = "transparent";
                }}
              >
                {o.label}
              </button>
            );
          })}
        </div>

        <RepSelect value={representation} onChange={setRepresentation} />
        <ToggleBtn icon={<Grid3x3 size={11} />} label="Wireframe" active={wireframe} onClick={() => setWireframe((w) => !w)} />
        <ToggleBtn icon={pocketOnly ? <Eye size={11} /> : <EyeOff size={11} />} label="Pocket" active={pocketOnly} onClick={() => setPocketOnly((p) => !p)} />
        <ToggleBtn icon={<RotateCw size={11} />} label="Spin" active={spin} onClick={() => setSpin((s) => !s)} />
        <button onClick={recenter} className="lys-3d-btn" title="Recenter">
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
          position: "absolute", top: "100%", right: 0, marginTop: 4,
          background: "var(--lys-bg-2)",
          border: "1px solid var(--lys-border-strong)",
          borderRadius: 8, padding: 4, zIndex: 100,
          boxShadow: "var(--lys-shadow-lg)",
        }}>
          {opts.map((o) => (
            <button
              key={o}
              className={clsx("lys-3d-btn", o === value && "lys-3d-btn--active")}
              style={{ display: "flex", width: 100 }}
              onClick={() => { onChange(o); setOpen(false); }}
            >
              {o}
            </button>
          ))}
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

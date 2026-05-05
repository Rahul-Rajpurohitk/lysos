import { useEffect, useRef, useState } from "react";
import {
  ChevronDown, Eye, EyeOff, RotateCw, RefreshCw, Layers, Grid3x3,
} from "lucide-react";
import clsx from "clsx";

interface Mol3DProps {
  apiBase: string;
  smiles: string | null;
  pathogen: string;
}

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

export function Mol3D({ apiBase, smiles, pathogen }: Mol3DProps) {
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

  // Initialize stage
  useEffect(() => {
    if (!stageRef.current) return;
    let stage: any = null;
    (async () => {
      try {
        const NGL = await import("ngl");
        stage = new NGL.Stage(stageRef.current!, {
          backgroundColor: "#161b22",
          quality: "medium",
        });
        stageObj.current = stage;
        stage.setSpin(spin);
      } catch (e: any) {
        setError(`NGL init failed: ${e.message}`);
      }
    })();
    return () => {
      if (stage) stage.dispose();
    };
  }, []);

  // Update PDB when pathogen changes
  useEffect(() => {
    setPdb(PATHOGEN_PDB[pathogen] ?? "5DPX");
  }, [pathogen]);

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

  // Load ligand from our /workbench/molecule/3d endpoint
  useEffect(() => {
    const stage = stageObj.current;
    if (!stage || !smiles) return;
    if (ligandComp.current) {
      stage.removeComponent(ligandComp.current);
      ligandComp.current = null;
    }
    fetch(`${apiBase}/workbench/molecule/3d`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ smiles, optimize: true, add_hydrogens: false }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then(async (d) => {
        if (!d?.sdf) return;
        const blob = new Blob([d.sdf], { type: "text/plain" });
        const comp = await stage.loadFile(blob, { ext: "sdf" });
        ligandComp.current = comp;
        comp.addRepresentation("ball+stick", { multipleBond: true });
        comp.autoView();
      })
      .catch(() => {});
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
      }}>
        {error && (
          <div style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -50%)",
            color: "var(--lys-text-faint)",
            fontSize: 12,
            textAlign: "center",
          }}>
            {error}
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

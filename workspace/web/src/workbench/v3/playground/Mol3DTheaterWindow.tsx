/**
 * Mol3DTheaterWindow — wraps the existing Mol3D viewer as a playground
 * window. The chrome (title, drag, resize, close) is provided by the
 * parent <PlaygroundWindow>; this component just owns the body.
 *
 * Sources its `smiles` + `pathogen` from canvas-shared state passed in,
 * not from local Mol3D state. Atom-edit ops bubble up to the parent so
 * the 2D builder window stays in sync (single source of truth = canvas).
 */
import { Mol3D } from "../components/Mol3D";

interface Props {
  apiBase: string;
  smiles: string | null;
  pathogen: string;
  onMoleculeEdit?: (newSmiles: string, op: any) => void;
}

export function Mol3DTheaterWindow(p: Props) {
  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <Mol3D
        apiBase={p.apiBase}
        smiles={p.smiles}
        pathogen={p.pathogen}
        onMoleculeEdit={p.onMoleculeEdit}
      />
    </div>
  );
}

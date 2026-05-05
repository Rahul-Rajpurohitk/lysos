import { useEffect, useState } from "react";
import { Wand2 } from "lucide-react";

interface ChipDef {
  id: string;
  label: string;
  rationale: string;
  expected_delta: Record<string, string>;
}

interface ChipsResponse {
  groups: { add: ChipDef[]; swap: ChipDef[]; remove: ChipDef[]; ring: ChipDef[] };
  total: number;
}

interface DragEditChipsProps {
  apiBase: string;
  currentSmiles: string | null;
  pathogen: string;
  onTransformResult: (payload: any) => void;
}

const GROUP_ORDER: Array<"add" | "swap" | "remove" | "ring"> = [
  "add",
  "swap",
  "remove",
  "ring",
];

export function DragEditChips(p: DragEditChipsProps) {
  const [chips, setChips] = useState<ChipsResponse | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [customRxn, setCustomRxn] = useState("");

  useEffect(() => {
    fetch(`${p.apiBase}/workbench/sandbox/transforms`)
      .then((r) => r.json())
      .then(setChips)
      .catch(() => setChips({ groups: { add: [], swap: [], remove: [], ring: [] }, total: 0 }));
  }, [p.apiBase]);

  async function applyTransform(transform: string | null, custom?: string) {
    if (!p.currentSmiles) return;
    const body: any = { smiles: p.currentSmiles, target_pathogen: p.pathogen, score: true };
    if (transform) body.transform = transform;
    else if (custom) body.custom_smarts_rxn = custom;
    else return;
    setBusy(transform ?? "custom");
    try {
      const r = await fetch(`${p.apiBase}/workbench/sandbox/transform`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await r.json();
      p.onTransformResult(payload);
    } finally {
      setBusy(null);
    }
  }

  if (!chips) return null;

  return (
    <div className="lys-chip-groups">
      {GROUP_ORDER.map((g) => {
        const items = chips.groups[g] ?? [];
        if (items.length === 0) return null;
        return (
          <div key={g} className="lys-chip-group">
            <span className="lys-chip-group__label">{g}</span>
            {items.map((c) => (
              <button
                key={c.id}
                className="lys-chip-tx"
                data-group={g}
                title={`${c.rationale}\n\nExpected: ${Object.entries(c.expected_delta || {})
                  .map(([k, v]) => `${k}=${v}`)
                  .join(", ")}`}
                onClick={() => applyTransform(c.id)}
                disabled={busy !== null || !p.currentSmiles}
              >
                {busy === c.id ? "…" : c.label}
              </button>
            ))}
          </div>
        );
      })}
      <div className="lys-chip-group">
        <span className="lys-chip-group__label">custom</span>
        <input
          className="lys-chip-tx"
          style={{
            flex: 1,
            cursor: "text",
            fontFamily: "var(--lys-font-mono)",
            fontSize: 11,
            padding: "0 10px",
          }}
          placeholder="SMARTS reaction (e.g. [c:1][H:2]>>[c:1]Br)"
          value={customRxn}
          onChange={(e) => setCustomRxn(e.target.value)}
        />
        <button
          className="lys-chip-tx"
          data-group="add"
          onClick={() => customRxn && applyTransform(null, customRxn)}
          disabled={!customRxn || busy !== null}
          title="apply custom SMARTS"
        >
          <Wand2 size={12} style={{ display: "inline" }} /> apply
        </button>
      </div>
    </div>
  );
}

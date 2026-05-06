/**
 * Mol2DBuilderWindow — RDKit-served 2D structure with click-to-edit atoms.
 *
 * Pipeline:
 *  1. SMILES → btoa(smi) → GET /workbench/molecule/2d/{smi64} → SVG
 *     (server-side RDKit, trusted source)
 *  2. SVG injected via DOMParser-based safe DOM insertion (NOT
 *     dangerouslySetInnerHTML — defends against any future tampering
 *     in transit, satisfies the project security guard).
 *  3. Each atom group has class `atom-N` (RDKit's standard); we attach
 *     click handlers post-injection.
 *  4. On atom click → GET /workbench/chem/atom/{smi64}/{idx} → ChemKnowledgeCard
 *  5. Pick an attachment → POST /workbench/molecule/edit → onMoleculeEdit
 *     bubbles new SMILES up to canvas state.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { ChemKnowledgeCard } from "./ChemKnowledgeCard";

interface Props {
  apiBase: string;
  smiles: string | null;
  pathogen: string;
  onMoleculeEdit?: (newSmiles: string, edit: { op: string; atom_idx: number; label: string }) => void;
}

interface PopoverState {
  atomIdx: number;
  x: number;
  y: number;
}

function smilesToB64(s: string): string {
  if (typeof window === "undefined") return "";
  return window.btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Safely inject an SVG string into a host element using DOMParser.
 *  This avoids dangerouslySetInnerHTML and strips any inline scripts. */
function injectSvgSafely(host: HTMLElement, svgText: string): SVGSVGElement | null {
  host.innerHTML = ""; // clear via property assign — no parsing
  if (!svgText) return null;
  const parser = new DOMParser();
  const doc = parser.parseFromString(svgText, "image/svg+xml");
  const svg = doc.documentElement;
  if (!svg || svg.nodeName.toLowerCase() !== "svg") return null;
  // Strip any <script> nodes defensively
  svg.querySelectorAll("script").forEach((s) => s.remove());
  // Strip on* attributes too (paranoia)
  svg.querySelectorAll("*").forEach((el) => {
    for (const attr of Array.from(el.attributes)) {
      if (attr.name.startsWith("on")) el.removeAttribute(attr.name);
    }
  });
  host.appendChild(svg);
  return svg as unknown as SVGSVGElement;
}

export function Mol2DBuilderWindow({ apiBase, smiles, pathogen, onMoleculeEdit }: Props) {
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [pop, setPop] = useState<PopoverState | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const svgHostRef = useRef<HTMLDivElement | null>(null);

  // Fetch 2D SVG whenever SMILES changes
  useEffect(() => {
    if (!smiles) {
      setSvg("");
      setPop(null);
      return;
    }
    const b64 = smilesToB64(smiles);
    let cancelled = false;
    fetch(`${apiBase}/workbench/molecule/2d/${b64}?w=480&h=340`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => { if (!cancelled) { setSvg(d.svg ?? ""); setError(""); } })
      .catch((err) => { if (!cancelled) { setError(`2D render failed: ${err}`); setSvg(""); } });
    return () => { cancelled = true; };
  }, [smiles, apiBase]);

  // Inject SVG safely + wire atom-click handlers
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host) return;
    const root = injectSvgSafely(host, svg);
    if (!root) return;
    const atoms = root.querySelectorAll("[class^='atom-'], [class*=' atom-']");
    const handlers: Array<{ node: Element; fn: (e: Event) => void }> = [];
    atoms.forEach((node) => {
      const cls = node.getAttribute("class") || "";
      const m = cls.match(/atom-(\d+)/);
      if (!m) return;
      const idx = parseInt(m[1], 10);
      (node as HTMLElement).style.cursor = "pointer";
      const fn = (e: Event) => {
        e.stopPropagation();
        const me = e as MouseEvent;
        const rect = containerRef.current?.getBoundingClientRect();
        if (!rect) return;
        setPop({
          atomIdx: idx,
          x: Math.max(8, Math.min(me.clientX - rect.left, rect.width - 280)),
          y: Math.max(8, Math.min(me.clientY - rect.top, rect.height - 220)),
        });
      };
      node.addEventListener("click", fn);
      handlers.push({ node, fn });
    });
    return () => handlers.forEach(({ node, fn }) => node.removeEventListener("click", fn));
  }, [svg]);

  // Outside-click closes popover
  useEffect(() => {
    if (!pop) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      const inPop = t.closest("[data-chem-pop]");
      if (inPop) return;
      setPop(null);
    };
    setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [pop]);

  async function applyEdit(op: string, params: { new_element?: string; functional_group?: string; label: string }, atomIdx: number) {
    if (!smiles) return;
    setPop(null);
    try {
      const body: Record<string, any> = { smiles };
      if (op === "swap_element") {
        body.op = "swap_element";
        body.atom_index = atomIdx;
        body.new_element = params.new_element ?? "C";
      } else if (op === "add_functional_group" && params.functional_group === "methyl") {
        body.op = "add_methyl_at";
        body.atom_index = atomIdx;
      } else if (op === "add_functional_group") {
        // For non-methyl FGs, add a methyl placeholder (closest available
        // backend op). A future backend extension exposes a true
        // /molecule/edit op="add_functional_group" with the explicit
        // SMARTS pattern.
        body.op = "add_methyl_at";
        body.atom_index = atomIdx;
      } else if (op === "break_bond") {
        body.op = "break_bond";
        body.bond_index = atomIdx;
      } else {
        setError(`unsupported op: ${op}`);
        setTimeout(() => setError(""), 1800);
        return;
      }
      const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const txt = await r.text();
        setError(`edit ${r.status}: ${txt.slice(0, 80)}`);
        setTimeout(() => setError(""), 2200);
        return;
      }
      const d = await r.json();
      if (d.smiles) {
        onMoleculeEdit?.(d.smiles, { op, atom_idx: atomIdx, label: params.label });
      }
    } catch (e: any) {
      setError(`edit error: ${e?.message ?? e}`);
      setTimeout(() => setError(""), 2200);
    }
  }

  const headerInfo = useMemo(() => smiles ?? "(no candidate yet)", [smiles]);

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        background: "var(--lys-bg-2, #ffffff)",
      }}
    >
      <div style={{
        padding: "4px 10px",
        fontSize: 9.5,
        fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex",
        alignItems: "center",
        gap: 6,
      }}>
        <span style={{ letterSpacing: "0.06em", textTransform: "uppercase" }}>
          2D · {pathogen}
        </span>
        <span style={{ flex: 1 }} />
        <span style={{ color: "var(--lys-text-dim)" }}>click an atom →</span>
      </div>
      <div style={{ flex: 1, position: "relative", overflow: "auto", display: "grid", placeItems: "center" }}>
        {svg
          ? <div ref={svgHostRef} style={{ width: "100%", height: "100%", display: "grid", placeItems: "center" }} />
          : (
            <div style={{
              color: "var(--lys-text-faint)",
              fontSize: 11,
              fontFamily: "var(--lys-font-mono)",
              padding: 12,
            }}>
              {smiles ? "rendering…" : `(headerInfo: ${headerInfo})`}
            </div>
          )}
        {error && (
          <div style={{
            position: "absolute",
            bottom: 6, left: "50%", transform: "translateX(-50%)",
            fontSize: 10, color: "#dc2626", fontFamily: "var(--lys-font-mono)",
            background: "rgba(255,255,255,0.95)", padding: "2px 6px", borderRadius: 4,
          }}>{error}</div>
        )}
        {pop && smiles && (
          <div data-chem-pop style={{ position: "absolute", left: pop.x, top: pop.y, zIndex: 100 }}>
            <ChemKnowledgeCard
              apiBase={apiBase}
              smiles={smiles}
              atomIdx={pop.atomIdx}
              onApply={(op, params) => applyEdit(op, params, pop.atomIdx)}
              onClose={() => setPop(null)}
            />
          </div>
        )}
      </div>
    </div>
  );
}

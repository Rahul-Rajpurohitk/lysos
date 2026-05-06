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
import { createPortal } from "react-dom";
import { ChemKnowledgeCard } from "./ChemKnowledgeCard";

interface Props {
  apiBase: string;
  smiles: string | null;
  pathogen: string;
  onMoleculeEdit?: (newSmiles: string, edit: { op: string; atom_idx: number; label: string }) => void;
  /** Other actors' cursors keyed by actor name (designer/critic/editor/strategist).
   *  Each cursor has a target atom_idx — we render a colored halo on that atom. */
  cursors?: Record<string, { actor: string; atom_idx?: number; ts: number }>;
  /** Called when the user hovers an atom — fires cursor.move + atom.hover via WS. */
  onCursorHover?: (atomIdx: number | null) => void;
  /** Optional external highlight (rare — SMARTS match is now handled internally) */
  highlightAtoms?: number[] | null;
  /** Open the user's saved-molecules library popover. Implemented by parent
   *  via portal so we can share the same library state across cards. */
  onLoadFromLibrary?: (smi: string, name: string) => void;
}

const SMARTS_PRESETS = [
  { label: "aromatic-N", pattern: "[n]" },
  { label: "carbonyl", pattern: "[CX3]=[OX1]" },
  { label: "amide", pattern: "[NX3][CX3](=[OX1])" },
  { label: "ester", pattern: "[#6][CX3](=O)O[#6]" },
  { label: "carboxylic", pattern: "C(=O)[OH]" },
  { label: "β-lactam", pattern: "[#7]1[#6](=O)[#6]([#6]1)" },
  { label: "sulfonamide", pattern: "[#16](=O)(=O)[#7]" },
  { label: "peptide", pattern: "[NX3][CX3](=O)[CX3]" },
  { label: "halogen", pattern: "[F,Cl,Br,I]" },
  { label: "phenol", pattern: "c[OH]" },
];

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
 *  This avoids dangerouslySetInnerHTML and strips any inline scripts.
 *  ALSO: forces width/height to 100% with preserveAspectRatio so the
 *  SVG scales to fit the host (RDKit serves at fixed 480×340; we let
 *  the viewBox handle responsive scaling). */
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
  // Force responsive scaling — drop any fixed pixel dimensions, ensure
  // a viewBox exists, set 100%/100% so the SVG fits the host element.
  const svgEl = svg as unknown as SVGSVGElement;
  // If viewBox is missing, synthesize from width/height attributes
  if (!svgEl.hasAttribute("viewBox")) {
    const w = svgEl.getAttribute("width") || "480";
    const h = svgEl.getAttribute("height") || "340";
    const wn = parseFloat(w);
    const hn = parseFloat(h);
    if (!isNaN(wn) && !isNaN(hn)) {
      svgEl.setAttribute("viewBox", `0 0 ${wn} ${hn}`);
    }
  }
  svgEl.setAttribute("width", "100%");
  svgEl.setAttribute("height", "100%");
  svgEl.setAttribute("preserveAspectRatio", "xMidYMid meet");
  svgEl.style.width = "100%";
  svgEl.style.height = "100%";
  svgEl.style.display = "block";
  host.appendChild(svg);
  return svgEl;
}

// Per-actor halo color (matches AgentAvatar palette).
const ACTOR_COLOR: Record<string, string> = {
  designer: "#10b981",
  critic: "#ef4444",
  editor: "#3b82f6",
  strategist: "#8b5cf6",
  user: "#f59e0b",
};

export function Mol2DBuilderWindow({ apiBase, smiles, pathogen, onMoleculeEdit, cursors, onCursorHover, highlightAtoms: externalHighlight, onLoadFromLibrary }: Props) {
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [pop, setPop] = useState<PopoverState | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  // Internal SMARTS state — replaces standalone SMARTSMatchCard
  const [smarts, setSmarts] = useState<string>("");
  const [smartsHits, setSmartsHits] = useState<number[]>([]);
  const [smartsError, setSmartsError] = useState<string>("");
  const [smartsLoading, setSmartsLoading] = useState(false);
  // Library popover state
  const [libraryOpen, setLibraryOpen] = useState(false);
  const libraryBtnRef = useRef<HTMLButtonElement | null>(null);
  // Drag-to-bond state — mousedown on atom A, drag to atom B → add_bond
  const [dragStart, setDragStart] = useState<number | null>(null);
  const [dragHover, setDragHover] = useState<number | null>(null);
  // Combined highlight: internal SMARTS hits OR external (from agent loop)
  const highlightAtoms = smartsHits.length > 0 ? smartsHits : externalHighlight;
  const containerRef = useRef<HTMLDivElement | null>(null);
  const svgHostRef = useRef<HTMLDivElement | null>(null);

  async function runSmartsMatch(pattern: string) {
    if (!smiles || !pattern.trim()) {
      setSmartsHits([]);
      setSmartsError("");
      return;
    }
    setSmartsLoading(true);
    setSmartsError("");
    try {
      const r = await fetch(`${apiBase}/workbench/molecule/smarts-match`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ smiles, smarts: pattern }),
      });
      if (!r.ok) {
        setSmartsError(`http ${r.status}`);
        setSmartsHits([]);
        return;
      }
      const d = await r.json();
      if (!d.valid_smarts) {
        setSmartsError(d.error || "invalid SMARTS");
        setSmartsHits([]);
        return;
      }
      // Flatten all match indices into one set for highlighting
      const all = new Set<number>();
      (d.matches || []).forEach((m: { atom_indices: number[] }) =>
        m.atom_indices.forEach((i) => all.add(i)));
      setSmartsHits(Array.from(all));
    } catch (e: any) {
      setSmartsError(String(e?.message ?? e));
      setSmartsHits([]);
    } finally {
      setSmartsLoading(false);
    }
  }

  // Re-run match on SMILES change if a pattern is set
  useEffect(() => {
    if (smarts.trim()) runSmartsMatch(smarts);
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [smiles]);

  // Drag-to-bond — mousedown on atom A, drag to atom B, mouseup → add_bond
  async function commitDragBond(a: number, b: number) {
    if (!smiles || a === b) return;
    try {
      const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          smiles, op: "add_bond", atom_index_a: a, atom_index_b: b,
          bond_order: "single",
        }),
      });
      if (!r.ok) {
        const txt = await r.text();
        setError(`bond ${r.status}: ${txt.slice(0, 80)}`);
        setTimeout(() => setError(""), 2200);
        return;
      }
      const d = await r.json();
      if (d.smiles) {
        onMoleculeEdit?.(d.smiles, {
          op: "add_bond", atom_idx: a,
          label: `drag-bond ${a}–${b}`,
        });
      }
    } catch (e: any) {
      setError(`drag-bond error: ${e?.message ?? e}`);
      setTimeout(() => setError(""), 2200);
    }
  }

  // Reset selection when SMILES changes (atom indices reshuffle)
  useEffect(() => { setSelected(new Set()); }, [smiles]);

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

  // Inject SVG safely + wire atom-click + atom-hover handlers
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host) return;
    const root = injectSvgSafely(host, svg);
    if (!root) return;
    const atoms = root.querySelectorAll("[class^='atom-'], [class*=' atom-']");
    const handlers: Array<{ node: Element; type: string; fn: (e: Event) => void }> = [];
    atoms.forEach((node) => {
      const cls = node.getAttribute("class") || "";
      const m = cls.match(/atom-(\d+)/);
      if (!m) return;
      const idx = parseInt(m[1], 10);
      (node as HTMLElement).style.cursor = "grab";

      const onMouseDown = (e: Event) => {
        const me = e as MouseEvent;
        if (me.shiftKey || me.button !== 0) return;
        e.stopPropagation();
        e.preventDefault();
        setDragStart(idx);
        (node as HTMLElement).style.cursor = "grabbing";
      };

      const onClick = (e: Event) => {
        e.stopPropagation();
        const me = e as MouseEvent;
        // Shift-click toggles multi-select (for bond creation between two atoms)
        if (me.shiftKey) {
          setSelected((cur) => {
            const next = new Set(cur);
            if (next.has(idx)) next.delete(idx);
            else next.add(idx);
            return next;
          });
          return;
        }
        const rect = containerRef.current?.getBoundingClientRect();
        if (!rect) return;
        setPop({
          atomIdx: idx,
          x: Math.max(8, Math.min(me.clientX - rect.left, rect.width - 280)),
          y: Math.max(8, Math.min(me.clientY - rect.top, rect.height - 220)),
        });
      };
      const onEnter = () => onCursorHover?.(idx);
      const onLeave = () => onCursorHover?.(null);
      node.addEventListener("mousedown", onMouseDown);
      node.addEventListener("click", onClick);
      node.addEventListener("mouseenter", onEnter);
      node.addEventListener("mouseleave", onLeave);
      handlers.push({ node, type: "mousedown", fn: onMouseDown });
      handlers.push({ node, type: "click", fn: onClick });
      handlers.push({ node, type: "mouseenter", fn: onEnter });
      handlers.push({ node, type: "mouseleave", fn: onLeave });
    });
    return () => handlers.forEach(({ node, type, fn }) => node.removeEventListener(type, fn));
  }, [svg, onCursorHover]);

  // Drag-to-bond — global mousemove tracks which atom is under cursor;
  // mouseup commits add_bond if started on atom A and released on atom B.
  useEffect(() => {
    if (dragStart == null) return;
    const host = svgHostRef.current;
    if (!host) return;
    const svgEl = host.querySelector("svg") as SVGSVGElement | null;
    if (!svgEl) return;
    let lastHover: number | null = null;
    const onMove = (ev: MouseEvent) => {
      const t = document.elementFromPoint(ev.clientX, ev.clientY);
      let foundIdx: number | null = null;
      let n: Element | null = t;
      while (n && n !== svgEl) {
        const cls = n.getAttribute?.("class") || "";
        const m = /atom-(\d+)/.exec(cls);
        if (m) { foundIdx = parseInt(m[1], 10); break; }
        n = n.parentElement;
      }
      lastHover = foundIdx;
      setDragHover(foundIdx);
    };
    const onUp = () => {
      svgEl.querySelectorAll("[class^='atom-'], [class*=' atom-']").forEach(
        (n) => { (n as HTMLElement).style.cursor = "grab"; });
      const a = dragStart;
      const b = lastHover;
      if (a != null && b != null && a !== b) {
        void commitDragBond(a, b);
      }
      setDragStart(null);
      setDragHover(null);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [dragStart]);

  // Render selection rings + ghost-line preview between consecutively-selected atoms.
  // The ghost line is a dashed cyan stroke between the bbox centers of the
  // first two selected atoms — a live preview of the bond that will be drawn
  // when the user clicks "+ single/double/triple bond" in the toolbar.
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host) return;
    const svgEl = host.querySelector("svg");
    if (!svgEl) return;
    svgEl.querySelectorAll('[data-sel="1"], [data-ghost="1"]').forEach((n) => n.remove());

    const centers: Array<{ idx: number; cx: number; cy: number }> = [];
    selected.forEach((idx) => {
      const target = svgEl.querySelector(`[class*="atom-${idx}"]`);
      if (!target) return;
      const bbox = (target as SVGGraphicsElement).getBBox?.();
      if (!bbox) return;
      const cx = bbox.x + bbox.width / 2;
      const cy = bbox.y + bbox.height / 2;
      centers.push({ idx, cx, cy });

      // Selection ring
      const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      ring.setAttribute("data-sel", "1");
      ring.setAttribute("cx", String(cx));
      ring.setAttribute("cy", String(cy));
      ring.setAttribute("r", "10");
      ring.setAttribute("fill", "rgba(245,158,11,0.10)");
      ring.setAttribute("stroke", "#f59e0b");
      ring.setAttribute("stroke-width", "2");
      ring.style.pointerEvents = "none";
      svgEl.appendChild(ring);

      // Order badge (1, 2, 3...) showing the atom's position in the bond chain
      const badge = document.createElementNS("http://www.w3.org/2000/svg", "text");
      badge.setAttribute("data-sel", "1");
      badge.setAttribute("x", String(cx + 12));
      badge.setAttribute("y", String(cy - 12));
      badge.setAttribute("font-size", "10");
      badge.setAttribute("font-family", "SF Mono, monospace");
      badge.setAttribute("font-weight", "700");
      badge.setAttribute("fill", "#92400e");
      badge.style.pointerEvents = "none";
      badge.textContent = String(centers.length);
      svgEl.appendChild(badge);
    });

    // Ghost-line preview: connect the first two selected atoms with a dashed line
    if (centers.length >= 2) {
      const a = centers[0];
      const b = centers[1];
      const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
      line.setAttribute("data-ghost", "1");
      line.setAttribute("x1", String(a.cx));
      line.setAttribute("y1", String(a.cy));
      line.setAttribute("x2", String(b.cx));
      line.setAttribute("y2", String(b.cy));
      line.setAttribute("stroke", "#06b6d4");          // cyan = preview
      line.setAttribute("stroke-width", "3");
      line.setAttribute("stroke-dasharray", "5,3");
      line.setAttribute("stroke-linecap", "round");
      line.setAttribute("opacity", "0.85");
      line.style.pointerEvents = "none";
      // Animate dasharray for "marching ants" effect
      const anim = document.createElementNS("http://www.w3.org/2000/svg", "animate");
      anim.setAttribute("attributeName", "stroke-dashoffset");
      anim.setAttribute("from", "0");
      anim.setAttribute("to", "16");
      anim.setAttribute("dur", "0.6s");
      anim.setAttribute("repeatCount", "indefinite");
      line.appendChild(anim);
      // Insert ghost line BEFORE the rings so atoms render on top
      svgEl.insertBefore(line, svgEl.firstChild);

      // Distance label at midpoint
      const mx = (a.cx + b.cx) / 2;
      const my = (a.cy + b.cy) / 2;
      const dist = Math.sqrt((b.cx - a.cx) ** 2 + (b.cy - a.cy) ** 2).toFixed(1);
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("data-ghost", "1");
      label.setAttribute("x", String(mx));
      label.setAttribute("y", String(my - 6));
      label.setAttribute("font-size", "9");
      label.setAttribute("font-family", "SF Mono, monospace");
      label.setAttribute("fill", "#0e7490");
      label.setAttribute("text-anchor", "middle");
      label.style.pointerEvents = "none";
      label.textContent = `preview · ${dist}u`;
      svgEl.appendChild(label);
    }
  }, [selected, svg]);

  // Apply cursor halos for non-self actors. Each cursors[actor].atom_idx
  // gets a colored ring drawn over its atom group via SVG <circle>.
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host || !cursors) return;
    const svgEl = host.querySelector("svg");
    if (!svgEl) return;
    // Clean previous halo overlays
    svgEl.querySelectorAll('[data-halo="1"]').forEach((n) => n.remove());
    for (const [actor, cur] of Object.entries(cursors)) {
      if (cur.atom_idx == null) continue;
      const target = svgEl.querySelector(`[class*="atom-${cur.atom_idx}"]`);
      if (!target) continue;
      const bbox = (target as SVGGraphicsElement).getBBox?.();
      if (!bbox) continue;
      const cx = bbox.x + bbox.width / 2;
      const cy = bbox.y + bbox.height / 2;
      const color = ACTOR_COLOR[actor.toLowerCase()] ?? "#9ca3af";
      const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      ring.setAttribute("data-halo", "1");
      ring.setAttribute("cx", String(cx));
      ring.setAttribute("cy", String(cy));
      ring.setAttribute("r", "12");
      ring.setAttribute("fill", "none");
      ring.setAttribute("stroke", color);
      ring.setAttribute("stroke-width", "2");
      ring.setAttribute("opacity", "0.7");
      ring.style.pointerEvents = "none";
      svgEl.appendChild(ring);
      // Small label tag next to the halo
      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("data-halo", "1");
      label.setAttribute("x", String(cx + 14));
      label.setAttribute("y", String(cy - 8));
      label.setAttribute("font-size", "9");
      label.setAttribute("font-family", "SF Mono, monospace");
      label.setAttribute("fill", color);
      label.style.pointerEvents = "none";
      label.textContent = actor;
      svgEl.appendChild(label);
    }
  }, [cursors, svg]);

  // SMARTS pattern match overlay — green pulse halos on matched atoms.
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host) return;
    const svgEl = host.querySelector("svg");
    if (!svgEl) return;
    svgEl.querySelectorAll('[data-smarts="1"]').forEach((n) => n.remove());
    if (!highlightAtoms || highlightAtoms.length === 0) return;
    highlightAtoms.forEach((idx) => {
      const target = svgEl.querySelector(`[class*="atom-${idx}"]`);
      if (!target) return;
      const bbox = (target as SVGGraphicsElement).getBBox?.();
      if (!bbox) return;
      const cx = bbox.x + bbox.width / 2;
      const cy = bbox.y + bbox.height / 2;
      const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      ring.setAttribute("data-smarts", "1");
      ring.setAttribute("cx", String(cx));
      ring.setAttribute("cy", String(cy));
      ring.setAttribute("r", "12");
      ring.setAttribute("fill", "rgba(16,185,129,0.18)");
      ring.setAttribute("stroke", "#10b981");
      ring.setAttribute("stroke-width", "2.5");
      ring.style.pointerEvents = "none";
      // Pulse animation
      const anim = document.createElementNS("http://www.w3.org/2000/svg", "animate");
      anim.setAttribute("attributeName", "r");
      anim.setAttribute("from", "12");
      anim.setAttribute("to", "16");
      anim.setAttribute("dur", "1.1s");
      anim.setAttribute("repeatCount", "indefinite");
      anim.setAttribute("values", "12;16;12");
      ring.appendChild(anim);
      svgEl.appendChild(ring);
    });
  }, [highlightAtoms, svg]);

  // Drag-to-bond visual overlay — cyan source ring + dashed line to current
  // hover position + cyan target ring on the hovered atom. Animated.
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host) return;
    const svgEl = host.querySelector("svg") as SVGSVGElement | null;
    if (!svgEl) return;
    svgEl.querySelectorAll('[data-drag="1"]').forEach((n) => n.remove());
    if (dragStart == null) return;
    const a = svgEl.querySelector(`[class*="atom-${dragStart}"]`);
    if (!a) return;
    const ab = (a as SVGGraphicsElement).getBBox?.();
    if (!ab) return;
    const ax = ab.x + ab.width / 2;
    const ay = ab.y + ab.height / 2;
    // Source ring (cyan, solid)
    const srcRing = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    srcRing.setAttribute("data-drag", "1");
    srcRing.setAttribute("cx", String(ax));
    srcRing.setAttribute("cy", String(ay));
    srcRing.setAttribute("r", "12");
    srcRing.setAttribute("fill", "rgba(6,182,212,0.15)");
    srcRing.setAttribute("stroke", "#06b6d4");
    srcRing.setAttribute("stroke-width", "2.5");
    srcRing.style.pointerEvents = "none";
    svgEl.appendChild(srcRing);
    // Target ring + line if hovering another atom
    if (dragHover != null && dragHover !== dragStart) {
      const b = svgEl.querySelector(`[class*="atom-${dragHover}"]`);
      if (b) {
        const bb = (b as SVGGraphicsElement).getBBox?.();
        if (bb) {
          const bx = bb.x + bb.width / 2;
          const by = bb.y + bb.height / 2;
          // Target halo (green, pulsing)
          const tgtRing = document.createElementNS("http://www.w3.org/2000/svg", "circle");
          tgtRing.setAttribute("data-drag", "1");
          tgtRing.setAttribute("cx", String(bx));
          tgtRing.setAttribute("cy", String(by));
          tgtRing.setAttribute("r", "14");
          tgtRing.setAttribute("fill", "rgba(16,185,129,0.20)");
          tgtRing.setAttribute("stroke", "#10b981");
          tgtRing.setAttribute("stroke-width", "3");
          tgtRing.style.pointerEvents = "none";
          const anim = document.createElementNS("http://www.w3.org/2000/svg", "animate");
          anim.setAttribute("attributeName", "r");
          anim.setAttribute("values", "14;17;14");
          anim.setAttribute("dur", "0.7s");
          anim.setAttribute("repeatCount", "indefinite");
          tgtRing.appendChild(anim);
          svgEl.appendChild(tgtRing);
          // Ghost bond line (dashed, animated)
          const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
          line.setAttribute("data-drag", "1");
          line.setAttribute("x1", String(ax));
          line.setAttribute("y1", String(ay));
          line.setAttribute("x2", String(bx));
          line.setAttribute("y2", String(by));
          line.setAttribute("stroke", "#10b981");
          line.setAttribute("stroke-width", "3");
          line.setAttribute("stroke-dasharray", "5,3");
          line.setAttribute("stroke-linecap", "round");
          line.setAttribute("opacity", "0.85");
          line.style.pointerEvents = "none";
          const lineAnim = document.createElementNS("http://www.w3.org/2000/svg", "animate");
          lineAnim.setAttribute("attributeName", "stroke-dashoffset");
          lineAnim.setAttribute("from", "0");
          lineAnim.setAttribute("to", "16");
          lineAnim.setAttribute("dur", "0.5s");
          lineAnim.setAttribute("repeatCount", "indefinite");
          line.appendChild(lineAnim);
          svgEl.insertBefore(line, svgEl.firstChild);
        }
      }
    }
  }, [dragStart, dragHover, svg]);

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
      } else if (op === "delete_atom") {
        body.op = "delete_atom";
        body.atom_index = atomIdx;
      } else if (op === "break_bond") {
        body.op = "break_bond";
        body.bond_index = atomIdx;
      } else if (op === "add_atom_at") {
        body.op = "add_atom_at";
        body.atom_index = atomIdx;
        body.new_element = params.new_element ?? "C";
        body.bond_order = "single";
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
      <div
        style={{
          padding: "4px 10px",
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
          display: "flex", alignItems: "center", gap: 6,
        }}
        title="Click an atom to edit · shift-click for multi-select · click-and-drag from atom to atom to add a bond"
      >
        <span style={{ letterSpacing: "0.06em", textTransform: "uppercase" }}>
          2D · {pathogen}
        </span>
        {/* Library trigger — opens portal popover with saved molecules */}
        {onLoadFromLibrary && (
          <button
            ref={libraryBtnRef}
            type="button"
            onClick={() => setLibraryOpen((o) => !o)}
            title="Saved molecules · search & load"
            style={{
              display: "inline-flex", alignItems: "center", gap: 4,
              padding: "2px 7px", borderRadius: 4,
              border: `1px solid ${libraryOpen ? "#10b981" : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
              background: libraryOpen ? "rgba(16,185,129,0.08)" : "transparent",
              cursor: "pointer", fontFamily: "inherit",
              fontSize: 9.5, color: "var(--lys-text-dim)",
              fontWeight: 500,
            }}>
            <span style={{ fontSize: 10, lineHeight: 1 }}>📚</span>
            <span style={{ textTransform: "none", letterSpacing: 0 }}>Library</span>
          </button>
        )}
        <span style={{ flex: 1 }} />
        {selected.size > 0 && (
          <span style={{ color: "#f59e0b", fontWeight: 600 }}>{selected.size} selected</span>
        )}
        {dragStart != null && (
          <span style={{ color: "#06b6d4", fontWeight: 600 }}>
            drag → {dragHover != null ? `atom ${dragHover}` : "release on atom to bond"}
          </span>
        )}
      </div>

      {/* SMARTS strip — embedded inside 2D viewer (NOT a separate card).
          Single inline row with input, match button, preset chips, and
          live hit count. Match results highlight directly on the SVG below. */}
      <div style={{
        padding: "4px 8px",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
        background: "var(--lys-bg-3, rgba(0,0,0,0.015))",
        flexWrap: "wrap", minHeight: 28,
      }}>
        <span style={{
          fontSize: 9, fontFamily: "var(--lys-font-mono)",
          color: smartsHits.length > 0 ? "#10b981" : "var(--lys-text-faint)",
          letterSpacing: "0.06em", textTransform: "uppercase",
          fontWeight: 700,
        }}>
          SMARTS{smartsHits.length > 0 ? ` · ${smartsHits.length} hits` : ""}
        </span>
        <input
          value={smarts}
          onChange={(e) => setSmarts(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") runSmartsMatch(smarts); }}
          placeholder="pattern · e.g. c1ccccc1 — Enter to match"
          disabled={!smiles}
          style={{
            flex: 1, minWidth: 120,
            fontSize: 10.5, fontFamily: "var(--lys-font-mono)",
            padding: "2px 6px", borderRadius: 4,
            border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
            background: "var(--lys-bg-1, #ffffff)",
            color: "var(--lys-text)",
            outline: "none",
          }} />
        <button type="button"
          onClick={() => runSmartsMatch(smarts)}
          disabled={!smiles || !smarts || smartsLoading}
          style={{
            padding: "2px 9px", borderRadius: 4, fontSize: 10,
            fontFamily: "var(--lys-font-mono)", fontWeight: 600,
            background: "#0891b2", color: "white", border: 0,
            cursor: smiles && smarts ? "pointer" : "not-allowed",
            opacity: smiles && smarts ? 1 : 0.5,
          }}>{smartsLoading ? "…" : "match"}</button>
        {smartsHits.length > 0 && (
          <button type="button"
            onClick={() => { setSmarts(""); setSmartsHits([]); setSmartsError(""); }}
            title="Clear match" style={{
              border: 0, background: "transparent",
              color: "var(--lys-text-faint)",
              cursor: "pointer", padding: "2px 4px", fontSize: 11,
            }}>✕</button>
        )}
        {smartsError && (
          <span style={{ fontSize: 9, color: "#dc2626",
            fontFamily: "var(--lys-font-mono)" }}>{smartsError}</span>
        )}
        {/* Inline preset chips — scrollable horizontally if too many */}
        <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
          {SMARTS_PRESETS.map((p) => (
            <button key={p.label} type="button"
              onClick={() => { setSmarts(p.pattern); runSmartsMatch(p.pattern); }}
              title={p.pattern}
              disabled={!smiles}
              style={{
                fontSize: 9, padding: "1px 6px", borderRadius: 999,
                border: `1px solid ${smarts === p.pattern ? "#0891b2" : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
                background: smarts === p.pattern ? "rgba(8,145,178,0.10)" : "var(--lys-bg-2, #ffffff)",
                color: smarts === p.pattern ? "#0891b2" : "var(--lys-text-dim)",
                cursor: smiles ? "pointer" : "not-allowed",
                opacity: smiles ? 1 : 0.5,
                fontFamily: "var(--lys-font-mono)",
                fontWeight: smarts === p.pattern ? 700 : 400,
              }}>{p.label}</button>
          ))}
        </div>
      </div>
      {/* Body row: SVG viewer (flex 1) + atoms rail (260 px).
          position: relative so the popover + multi-select toolbar (children
          with position: absolute) anchor here. */}
      <div style={{ flex: 1, display: "flex", flexDirection: "row", overflow: "hidden", minHeight: 0, position: "relative" }}>
        {/* SVG area — molecule scales to fit, never scrolls, never clips */}
        <div style={{ flex: 1, position: "relative", overflow: "hidden", display: "grid", placeItems: "center", padding: 8 }}>
          {svg
            ? <div ref={svgHostRef} style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }} />
            : (
              <div style={{
                color: "var(--lys-text-faint)", fontSize: 11,
                fontFamily: "var(--lys-font-mono)", padding: 12, textAlign: "center",
              }}>
                {smiles ? "rendering…" : "no candidate yet · pick a scaffold"}
              </div>
            )}
          {error && (
            <div style={{
              position: "absolute", bottom: 6, left: "50%", transform: "translateX(-50%)",
              fontSize: 10, color: "#dc2626", fontFamily: "var(--lys-font-mono)",
              background: "rgba(255,255,255,0.95)", padding: "2px 6px", borderRadius: 4,
            }}>{error}</div>
          )}
        </div>
        {/* Atoms rail — embedded list of all atoms with element + valence + edit chips */}
        <AtomsRail
          apiBase={apiBase}
          smiles={smiles}
          selected={selected}
          hoverIdx={null}
          onSelectAtom={(idx) => {
            setSelected((cur) => {
              const next = new Set(cur);
              if (next.has(idx)) next.delete(idx); else next.add(idx);
              return next;
            });
          }}
          onHoverAtom={(idx) => onCursorHover?.(idx)}
          onDeleteAtom={async (idx) => {
            if (!smiles) return;
            try {
              const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ smiles, op: "delete_atom", atom_index: idx }),
              });
              if (!r.ok) {
                const txt = await r.text();
                setError(`delete ${r.status}: ${txt.slice(0, 60)}`);
                setTimeout(() => setError(""), 2200);
                return;
              }
              const d = await r.json();
              if (d.smiles) {
                onMoleculeEdit?.(d.smiles, { op: "delete_atom", atom_idx: idx, label: `delete atom ${idx}` });
              }
            } catch {/*noop*/}
          }}
          onAddAtom={async () => {
            if (!smiles) return;
            // Anchor on first atom (idx 0) and add carbon — user can swap element via popover.
            try {
              const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  smiles, op: "add_atom_at", atom_index: 0,
                  new_element: "C", bond_order: "single",
                }),
              });
              if (!r.ok) {
                const txt = await r.text();
                setError(`add ${r.status}: ${txt.slice(0, 60)}`);
                setTimeout(() => setError(""), 2200);
                return;
              }
              const d = await r.json();
              if (d.smiles) {
                onMoleculeEdit?.(d.smiles, { op: "add_atom_at", atom_idx: 0, label: "+C atom" });
              }
            } catch {/*noop*/}
          }}
        />
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
        {/* Multi-select toolbar — appears when ≥2 atoms shift-clicked.
            Lets the user join the selection with a bond of any order. */}
        {selected.size >= 2 && smiles && (
          <div style={{
            position: "absolute",
            bottom: 8, left: "50%", transform: "translateX(-50%)",
            display: "flex", alignItems: "center", gap: 6,
            padding: "4px 8px",
            background: "rgba(245, 158, 11, 0.10)",
            border: "1px solid rgba(245, 158, 11, 0.35)",
            borderRadius: 999,
            fontSize: 10,
            fontFamily: "var(--lys-font-mono)",
            color: "#92400e",
            zIndex: 50,
          }}>
            <span>selected: {Array.from(selected).slice(0, 4).join(",")}</span>
            <span style={{ opacity: 0.6 }}>·</span>
            {(["single", "double", "triple"] as const).map((bo) => (
              <button
                key={bo}
                type="button"
                onClick={async () => {
                  const ids = Array.from(selected);
                  if (ids.length < 2) return;
                  // Bond first two; user can iterate for chains
                  try {
                    const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                      method: "POST",
                      headers: { "Content-Type": "application/json" },
                      body: JSON.stringify({
                        smiles,
                        op: "add_bond",
                        atom_index_a: ids[0],
                        atom_index_b: ids[1],
                        bond_order: bo,
                      }),
                    });
                    if (!r.ok) {
                      const txt = await r.text();
                      setError(`bond ${r.status}: ${txt.slice(0, 80)}`);
                      setTimeout(() => setError(""), 2200);
                      return;
                    }
                    const d = await r.json();
                    if (d.smiles) {
                      onMoleculeEdit?.(d.smiles, {
                        op: "add_bond",
                        atom_idx: ids[0],
                        label: `${bo} bond ${ids[0]}–${ids[1]}`,
                      });
                      setSelected(new Set());
                    }
                  } catch (exc: any) {
                    setError(`bond error: ${exc?.message ?? exc}`);
                    setTimeout(() => setError(""), 2200);
                  }
                }}
                style={{
                  border: 0, background: "rgba(245,158,11,0.25)", color: "#92400e",
                  padding: "2px 8px", borderRadius: 999,
                  fontFamily: "inherit", fontSize: 10, fontWeight: 700,
                  cursor: "pointer",
                }}
              >
                + {bo} bond
              </button>
            ))}
            <button
              type="button"
              onClick={() => setSelected(new Set())}
              title="Clear selection"
              style={{
                border: 0, background: "transparent", color: "#92400e",
                padding: "2px 6px", borderRadius: 4,
                cursor: "pointer", fontFamily: "inherit", fontSize: 10,
              }}
            >
              clear
            </button>
          </div>
        )}
      </div>
      {libraryOpen && libraryBtnRef.current && onLoadFromLibrary && (
        <LibraryPopover
          apiBase={apiBase}
          currentSmiles={smiles}
          anchor={libraryBtnRef.current}
          onClose={() => setLibraryOpen(false)}
          onLoad={(smi, name) => { onLoadFromLibrary(smi, name); setLibraryOpen(false); }}
        />
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
   LibraryPopover — portal-rendered saved-molecules panel.
   Lives next to the 2D viewer's "Library" button. Combines search +
   tag chips + entry list in a compact 460×500 popover. Saves and loads
   route through the same /workbench/library/molecules backend.
   ───────────────────────────────────────────────────────────────────── */
interface LibraryEntry {
  id: number;
  smiles: string;
  canonical_smiles: string;
  name: string;
  tags: string[];
  qed: number;
  mw: number;
  lipinski_pass: boolean;
}

function LibraryPopover({ apiBase, currentSmiles, anchor, onClose, onLoad }: {
  apiBase: string;
  currentSmiles: string | null;
  anchor: HTMLElement;
  onClose: () => void;
  onLoad: (smi: string, name: string) => void;
}) {
  const [entries, setEntries] = useState<LibraryEntry[]>([]);
  const [tags, setTags] = useState<Array<{ tag: string; count: number }>>([]);
  const [activeTag, setActiveTag] = useState("");
  const [query, setQuery] = useState("");
  const [showSave, setShowSave] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveTags, setSaveTags] = useState("");
  const [pos, setPos] = useState<{ left: number; top: number } | null>(null);

  useEffect(() => {
    const r = anchor.getBoundingClientRect();
    setPos({ left: r.left, top: r.bottom + 4 });
  }, [anchor]);

  async function refresh() {
    const params = new URLSearchParams();
    if (activeTag) params.set("tag", activeTag);
    if (query) params.set("q", query);
    try {
      const r = await fetch(`${apiBase}/workbench/library/molecules?${params}`);
      if (r.ok) {
        const d = await r.json();
        setEntries(d.entries ?? []);
      }
      const r2 = await fetch(`${apiBase}/workbench/library/tags`);
      if (r2.ok) {
        const d2 = await r2.json();
        setTags(d2.tags ?? []);
      }
    } catch {/*noop*/}
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [activeTag, query]);

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("[data-library-pop]")) return;
      if (anchor.contains(t)) return;
      onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [anchor, onClose]);

  const visible = useMemo(() => entries, [entries]);

  async function saveCurrent() {
    if (!currentSmiles) return;
    const tagsArr = saveTags.split(",").map((t) => t.trim()).filter(Boolean);
    try {
      await fetch(`${apiBase}/workbench/library/molecules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          smiles: currentSmiles,
          name: saveName || "(unnamed)",
          tags: tagsArr,
        }),
      });
      setShowSave(false); setSaveName(""); setSaveTags("");
      refresh();
    } catch {/*noop*/}
  }

  async function deleteEntry(id: number) {
    try {
      await fetch(`${apiBase}/workbench/library/molecules/${id}`, { method: "DELETE" });
      refresh();
    } catch {/*noop*/}
  }

  if (!pos) return null;
  return createPortal(
    <div data-library-pop style={{
      position: "fixed", left: pos.left, top: pos.top,
      width: 460, maxHeight: "60vh",
      background: "var(--lys-bg-2, #ffffff)",
      border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
      borderRadius: 10,
      boxShadow: "0 14px 40px rgba(15,23,42,0.18), 0 2px 8px rgba(15,23,42,0.10)",
      zIndex: 5000, display: "flex", flexDirection: "column",
      overflow: "hidden", fontFamily: "var(--lys-font-body)",
    }}>
      {/* Header — search + save trigger */}
      <div style={{ padding: "8px 10px",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
        display: "flex", flexDirection: "column", gap: 6,
        background: "var(--lys-bg, #fafafa)" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: "var(--lys-text)" }}>
            📚 Library · {entries.length}
          </span>
          <span style={{ flex: 1 }} />
          {currentSmiles && (
            <button type="button" onClick={() => setShowSave((s) => !s)}
              title="Save current candidate"
              style={{
                border: 0, background: "#10b981", color: "white",
                padding: "3px 9px", borderRadius: 4,
                fontSize: 10, fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                cursor: "pointer",
              }}>+ save</button>
          )}
          <button type="button" onClick={onClose}
            style={{ border: 0, background: "transparent", cursor: "pointer",
              padding: 4, color: "var(--lys-text-faint)" }}>✕</button>
        </div>
        {showSave && currentSmiles && (
          <div style={{ display: "flex", flexDirection: "column", gap: 3,
            padding: 6, borderRadius: 4,
            background: "rgba(16,185,129,0.06)" }}>
            <input value={saveName} onChange={(e) => setSaveName(e.target.value)}
              placeholder="name (optional)"
              style={popInput} />
            <input value={saveTags} onChange={(e) => setSaveTags(e.target.value)}
              placeholder="tags · comma-separated"
              style={popInput} />
            <div style={{ display: "flex", gap: 4 }}>
              <button type="button" onClick={saveCurrent}
                style={{ flex: 1, padding: "3px 8px", borderRadius: 4,
                  fontSize: 10, fontFamily: "var(--lys-font-mono)",
                  background: "#10b981", color: "white", border: 0,
                  cursor: "pointer", fontWeight: 700 }}>save</button>
              <button type="button" onClick={() => setShowSave(false)}
                style={{ padding: "3px 8px", borderRadius: 4,
                  fontSize: 10, fontFamily: "var(--lys-font-mono)",
                  background: "transparent", color: "var(--lys-text-faint)",
                  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
                  cursor: "pointer" }}>cancel</button>
            </div>
          </div>
        )}
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <input value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="search · name, note, SMILES"
            style={{ ...popInput, flex: 1 }} />
        </div>
        {tags.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
            <button type="button" onClick={() => setActiveTag("")}
              style={tagChip(!activeTag, "#10b981")}>all · {entries.length}</button>
            {tags.map((t) => (
              <button key={t.tag} type="button"
                onClick={() => setActiveTag(t.tag === activeTag ? "" : t.tag)}
                style={tagChip(t.tag === activeTag, "#10b981")}>{t.tag} · {t.count}</button>
            ))}
          </div>
        )}
      </div>
      {/* Entries */}
      <div className="lys-card-body" style={{ flex: 1, overflow: "auto" }}>
        {visible.length === 0 && (
          <div style={{ padding: 20, textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 11,
            fontFamily: "var(--lys-font-mono)" }}>
            empty · save the current candidate with +
          </div>
        )}
        {visible.map((e) => (
          <div key={e.id} style={{
            padding: "5px 10px",
            borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
            borderLeft: e.lipinski_pass ? "3px solid #10b981" : "3px solid #d97706",
            cursor: "pointer", display: "flex", flexDirection: "column", gap: 2,
          }}
          onClick={() => onLoad(e.smiles, e.name)}
          onMouseOver={(ev) => { (ev.currentTarget as HTMLElement).style.background = "var(--lys-bg-3, rgba(0,0,0,0.02))"; }}
          onMouseOut={(ev) => { (ev.currentTarget as HTMLElement).style.background = "transparent"; }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 700,
                color: "var(--lys-text)",
                fontFamily: "var(--lys-font-mono)" }}>{e.name || `#${e.id}`}</span>
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)" }}>
                QED <span style={{ color: e.qed >= 0.67 ? "#10b981" : e.qed >= 0.4 ? "#d97706" : "#dc2626", fontWeight: 700 }}>
                  {e.qed.toFixed(2)}
                </span>
              </span>
              <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-mono)" }}>MW {e.mw.toFixed(0)}</span>
              <button type="button"
                onClick={(ev) => { ev.stopPropagation(); deleteEntry(e.id); }}
                title="Delete entry"
                style={{ border: 0, background: "transparent",
                  cursor: "pointer", padding: "0 3px",
                  color: "#dc2626", opacity: 0.5,
                  fontSize: 11, fontWeight: 700 }}
                onMouseOver={(ev) => { (ev.currentTarget as HTMLElement).style.opacity = "1"; }}
                onMouseOut={(ev) => { (ev.currentTarget as HTMLElement).style.opacity = "0.5"; }}>×</button>
            </div>
            {e.tags.length > 0 && (
              <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                {e.tags.map((t) => (
                  <span key={t} style={{
                    fontSize: 8.5, padding: "0px 5px", borderRadius: 999,
                    background: "rgba(16,185,129,0.10)", color: "#10b981",
                    fontFamily: "var(--lys-font-mono)" }}>{t}</span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>,
    document.body,
  );
}

const popInput: React.CSSProperties = {
  fontSize: 11, fontFamily: "var(--lys-font-mono)",
  padding: "3px 7px", borderRadius: 4,
  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
  background: "var(--lys-bg-2, #ffffff)",
  color: "var(--lys-text)", outline: "none",
};

function tagChip(active: boolean, color: string): React.CSSProperties {
  return {
    padding: "1px 6px", borderRadius: 999, fontSize: 9,
    fontFamily: "var(--lys-font-mono)",
    border: `1px solid ${active ? color : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
    background: active ? `${color}15` : "var(--lys-bg-2, #ffffff)",
    color: active ? color : "var(--lys-text-dim)",
    cursor: "pointer", fontWeight: active ? 700 : 400,
  };
}

/* ─────────────────────────────────────────────────────────────────────
   AtomsRail — embedded list of atoms inside the 2D builder.
   Replaces the standalone "Live atoms · CRUD" card.

   Each row: idx · element badge · valence · aromatic chip · ring chip.
   Click row → toggles selection in the SVG (mirrors shift-click).
   Hover row → fires onHoverAtom which broadcasts cursor presence.
   ───────────────────────────────────────────────────────────────────── */
interface AtomsRailProps {
  apiBase: string;
  smiles: string | null;
  selected: Set<number>;
  hoverIdx: number | null;
  onSelectAtom: (idx: number) => void;
  onHoverAtom: (idx: number | null) => void;
  onDeleteAtom?: (idx: number) => void;
  onAddAtom?: () => void;
}

interface AtomRow {
  idx: number;
  element: string;
  is_aromatic: boolean;
  in_ring: boolean;
  ring_size: number;
  n_hydrogens: number;
  formal_charge: number;
  n_neighbors: number;
}

function AtomsRail(p: AtomsRailProps) {
  const [atoms, setAtoms] = useState<AtomRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!p.smiles) { setAtoms([]); return; }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const b64 = smilesToB64(p.smiles!);
        // Get atom count from the 2D endpoint, then fetch each atom in parallel
        const r = await fetch(`${p.apiBase}/workbench/molecule/2d/${b64}?w=200&h=200`);
        if (!r.ok) { setAtoms([]); return; }
        const meta = await r.json();
        const n = meta.n_atoms ?? 0;
        // Parallel atom fetches — much faster than sequential
        const promises = Array.from({ length: n }, (_, i) =>
          fetch(`${p.apiBase}/workbench/chem/atom/${b64}/${i}`)
            .then((ar) => ar.ok ? ar.json() : null)
            .catch(() => null));
        const results = await Promise.all(promises);
        if (cancelled) return;
        const rows: AtomRow[] = results.map((a, i) => a ? ({
          idx: i,
          element: a.element,
          is_aromatic: a.is_aromatic,
          in_ring: a.in_ring,
          ring_size: a.ring_size,
          n_hydrogens: a.n_hydrogens,
          formal_charge: a.formal_charge,
          n_neighbors: (a.neighbors || []).length,
        }) : null).filter((x): x is AtomRow => x !== null);
        if (!cancelled) setAtoms(rows);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [p.smiles, p.apiBase]);

  const ELEMENT_COLOR: Record<string, string> = {
    C: "#374151", N: "#2563eb", O: "#dc2626", S: "#ca8a04",
    F: "#16a34a", Cl: "#16a34a", Br: "#9a3412", I: "#7c3aed",
    P: "#ea580c", H: "#9ca3af",
  };

  return (
    <div style={{
      width: 220, flexShrink: 0,
      borderLeft: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
      background: "var(--lys-bg, #fafafa)",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      <div
        title="Click row to select an atom · click × to delete · click + to add"
        style={{
          padding: "3px 8px",
          fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em", textTransform: "uppercase",
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
          display: "flex", alignItems: "center", gap: 5,
          minHeight: 24,
        }}>
        <span>atoms</span>
        <span style={{ fontFamily: "inherit", color: "#10b981", fontWeight: 700 }}>
          {atoms.length}
        </span>
        <span style={{ flex: 1 }} />
        {p.smiles && p.onAddAtom && (
          <button type="button" onClick={p.onAddAtom}
            title="Add a new atom (carbon by default)"
            style={{
              border: 0, background: "transparent",
              cursor: "pointer", padding: "1px 4px",
              color: "#10b981", fontSize: 13, fontWeight: 700, lineHeight: 1,
            }}>+</button>
        )}
      </div>
      <div className="lys-card-body" style={{ flex: 1, overflow: "auto" }}>
        {!p.smiles && (
          <div style={{
            padding: "16px 10px", textAlign: "center",
            fontSize: 10, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)",
          }}>no candidate</div>
        )}
        {p.smiles && loading && atoms.length === 0 && (
          <div style={{ padding: "16px 10px", textAlign: "center",
            fontSize: 10, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)" }}>loading atoms…</div>
        )}
        {atoms.map((a) => {
          const c = ELEMENT_COLOR[a.element] ?? "#374151";
          const isSelected = p.selected.has(a.idx);
          const isHover = p.hoverIdx === a.idx;
          return (
            <div key={a.idx}
              onClick={() => p.onSelectAtom(a.idx)}
              onMouseEnter={() => p.onHoverAtom(a.idx)}
              onMouseLeave={() => p.onHoverAtom(null)}
              style={{
                display: "flex", alignItems: "center", gap: 4,
                padding: "2px 6px",
                borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.025))",
                borderLeft: isSelected ? `2px solid #f59e0b` : "2px solid transparent",
                background: isSelected ? "rgba(245,158,11,0.08)"
                          : isHover ? "rgba(0,0,0,0.025)" : "transparent",
                cursor: "pointer",
                fontSize: 9.5,
                fontFamily: "var(--lys-font-mono)",
                minHeight: 22,
              }}>
              <span style={{
                fontSize: 8, color: "var(--lys-text-faint)",
                minWidth: 12, textAlign: "right",
              }}>{a.idx}</span>
              <span style={{
                width: 15, height: 15, borderRadius: "50%",
                background: c, color: "white",
                display: "grid", placeItems: "center",
                fontSize: 8.5, fontWeight: 700, flexShrink: 0,
              }}>{a.element}</span>
              {a.n_hydrogens > 0 && (
                <span style={{ color: "var(--lys-text-faint)", fontSize: 8 }}>H{a.n_hydrogens}</span>
              )}
              {a.is_aromatic && (
                <span style={{
                  fontSize: 7, padding: "0 3px", borderRadius: 2,
                  background: "rgba(168,85,247,0.10)", color: "#a855f7",
                  fontWeight: 700, letterSpacing: "0.04em",
                }}>arom</span>
              )}
              {a.in_ring && !a.is_aromatic && (
                <span style={{
                  fontSize: 7, padding: "0 3px", borderRadius: 2,
                  background: "rgba(8,145,178,0.10)", color: "#0891b2",
                  fontWeight: 700,
                }}>r{a.ring_size}</span>
              )}
              {a.formal_charge !== 0 && (
                <span style={{
                  fontSize: 7, padding: "0 3px", borderRadius: 2,
                  background: "rgba(220,38,38,0.10)", color: "#dc2626",
                  fontWeight: 700,
                }}>{a.formal_charge > 0 ? "+" : ""}{a.formal_charge}</span>
              )}
              <span style={{ flex: 1 }} />
              <span style={{ color: "var(--lys-text-faint)", fontSize: 8 }}>
                ·{a.n_neighbors}
              </span>
              {p.onDeleteAtom && (
                <button type="button"
                  onClick={(e) => { e.stopPropagation(); p.onDeleteAtom!(a.idx); }}
                  title={`Delete atom ${a.idx}`}
                  style={{
                    border: 0, background: "transparent",
                    cursor: "pointer", padding: "0 3px",
                    color: "#dc2626", opacity: 0.5,
                    fontSize: 11, lineHeight: 1, fontWeight: 700,
                  }}
                  onMouseOver={(e) => { (e.currentTarget as HTMLElement).style.opacity = "1"; }}
                  onMouseOut={(e) => { (e.currentTarget as HTMLElement).style.opacity = "0.5"; }}
                >×</button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

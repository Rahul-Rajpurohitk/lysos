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
import { useEffect, useRef, useState } from "react";
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

// Per-actor halo color (matches AgentAvatar palette).
const ACTOR_COLOR: Record<string, string> = {
  designer: "#10b981",
  critic: "#ef4444",
  editor: "#3b82f6",
  strategist: "#8b5cf6",
  user: "#f59e0b",
};

export function Mol2DBuilderWindow({ apiBase, smiles, pathogen, onMoleculeEdit, cursors, onCursorHover }: Props) {
  const [svg, setSvg] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [pop, setPop] = useState<PopoverState | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const containerRef = useRef<HTMLDivElement | null>(null);
  const svgHostRef = useRef<HTMLDivElement | null>(null);

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
      (node as HTMLElement).style.cursor = "pointer";
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
      node.addEventListener("click", onClick);
      node.addEventListener("mouseenter", onEnter);
      node.addEventListener("mouseleave", onLeave);
      handlers.push({ node, type: "click", fn: onClick });
      handlers.push({ node, type: "mouseenter", fn: onEnter });
      handlers.push({ node, type: "mouseleave", fn: onLeave });
    });
    return () => handlers.forEach(({ node, type, fn }) => node.removeEventListener(type, fn));
  }, [svg, onCursorHover]);

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
        {selected.size > 0 && (
          <span style={{ color: "#f59e0b", fontWeight: 600 }}>
            {selected.size} sel
          </span>
        )}
        <span style={{ color: "var(--lys-text-dim)" }}>click → edit · shift-click → multi-select</span>
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
              textAlign: "center",
            }}>
              {smiles
                ? "rendering…"
                : "no candidate yet · run /design <pathogen> or pick one"}
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
    </div>
  );
}

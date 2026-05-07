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

function navBtnStyle(active: boolean, accent: string): React.CSSProperties {
  return {
    display: "inline-flex", alignItems: "center", gap: 4,
    padding: "2px 7px", borderRadius: 4,
    border: `1px solid ${active ? accent : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
    background: active ? `${accent}10` : "transparent",
    cursor: "pointer", fontFamily: "inherit",
    fontSize: 9.5, color: active ? accent : "var(--lys-text-dim)",
    fontWeight: 500,
  };
}

const SMARTS_PRESETS = [
  // Antibiotic-class warheads
  { label: "β-lactam",          pattern: "[#7]1[#6](=O)[#6]([#6]1)" },
  { label: "thiazolidine",      pattern: "C1SCNC1" },
  { label: "fluoroquinolone",   pattern: "c1cc2N(C)cc(C(=O)O)c(=O)c2cc1F" },
  { label: "aminoglycoside-NH₂",pattern: "[CH]([NH2])[CH]([OH])[CH][CH]([OH])" },
  { label: "tetracycline core", pattern: "C1=CC=C2C(=O)C3=C(C(=C(C=C3)O)O)C(=O)C2=C1" },
  { label: "oxazolidinone",     pattern: "O=C1OCCN1" },
  // Functional groups (acid / base / H-bond)
  { label: "carboxylic acid",   pattern: "C(=O)[OH]" },
  { label: "ester",             pattern: "[#6][CX3](=O)O[#6]" },
  { label: "amide",             pattern: "[NX3][CX3](=[OX1])" },
  { label: "peptide bond",      pattern: "[NX3][CX3](=O)[CX3]" },
  { label: "carbonyl",          pattern: "[CX3]=[OX1]" },
  { label: "aldehyde",          pattern: "[CX3H1](=O)[#6]" },
  { label: "ketone",            pattern: "[#6][CX3](=O)[#6]" },
  { label: "ether",             pattern: "[OD2]([#6])[#6]" },
  { label: "alcohol -OH",       pattern: "[OX2H][CX4]" },
  { label: "phenol",            pattern: "c[OH]" },
  { label: "primary amine",     pattern: "[NX3;H2;!$(NC=O)]" },
  { label: "secondary amine",   pattern: "[NX3;H1;!$(NC=O)]" },
  { label: "tertiary amine",    pattern: "[NX3;H0;!$(NC=O);!$(N=*)]" },
  { label: "thiol -SH",         pattern: "[#16X2H]" },
  { label: "sulfonamide",       pattern: "[#16](=O)(=O)[#7]" },
  { label: "sulfonyl",          pattern: "[#16X4](=[OX1])(=[OX1])" },
  { label: "phosphate",         pattern: "P(=O)(O)(O)O" },
  { label: "nitro",             pattern: "[N+](=O)[O-]" },
  { label: "nitrile -CN",       pattern: "C#N" },
  { label: "azide",             pattern: "N=[N+]=[N-]" },
  // Halogens
  { label: "halogen",           pattern: "[F,Cl,Br,I]" },
  { label: "trifluoromethyl",   pattern: "C(F)(F)F" },
  { label: "aryl halide",       pattern: "[c][F,Cl,Br,I]" },
  // Aromatic / heteroaryl
  { label: "aromatic-N",        pattern: "[n]" },
  { label: "benzene",           pattern: "c1ccccc1" },
  { label: "pyridine",          pattern: "c1ccncc1" },
  { label: "imidazole",         pattern: "c1cnc[nH]1" },
  { label: "thiazole",          pattern: "c1cscn1" },
  { label: "indole",            pattern: "c1ccc2[nH]ccc2c1" },
  { label: "quinoline",         pattern: "c1ccc2ncccc2c1" },
  // Drug-likeness motifs
  { label: "Michael acceptor",  pattern: "[#6]=[#6][CX3](=O)" },
  { label: "epoxide",           pattern: "C1OC1" },
  { label: "Mannich base",      pattern: "[NX3]C[CX4]C(=O)" },
  { label: "guanidine",         pattern: "NC(=N)N" },
  { label: "urea",              pattern: "[NX3][CX3](=[OX1])[NX3]" },
];

interface PopoverState {
  atomIdx: number;
  // Viewport-fixed coordinates (clientX/clientY at click). Renderer
  // clamps these to keep the popover inside the viewport.
  x: number;
  y: number;
}

const CHEM_POP_W = 280;
const CHEM_POP_H = 380;

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

/* ─────────────────────────────────────────────────────────────────────
   Structured violation type — matches the backend's `_violation`
   shape from workbench.py. The frontend renders these in a single
   ViolationToast component (replaces the old plain string `error`),
   so every chemistry-law violation, missing-arg error, and over-
   valence message has the same readable look + suggested fix.
   ───────────────────────────────────────────────────────────────────── */
interface Violation {
  code: string;          // machine code, e.g. "valence_violation"
  message: string;       // raw RDKit / backend message
  hint?: string;         // human-readable explanation
  atom_idx?: number | null;
  bond_idx?: number | null;
  suggested_fix?: string;  // free-form remediation text
}

/**
 * Parse a fetch Response (assumed not-ok) into a structured Violation.
 * Backend returns `{detail: {code, message, hint, atom_idx?, bond_idx?,
 * suggested_fix?}}` on /molecule/edit failures; older endpoints still
 * return plain strings, which we wrap into a generic violation.
 */
async function parseError(r: Response, fallbackCode = "request_failed"): Promise<Violation> {
  try {
    const j = await r.json();
    const d = j?.detail ?? j;
    if (typeof d === "object" && d !== null && typeof d.code === "string") {
      return d as Violation;
    }
    return {
      code: fallbackCode,
      message: typeof d === "string" ? d : `${r.status} ${r.statusText}`,
    };
  } catch {
    return {
      code: fallbackCode,
      message: `${r.status} ${r.statusText}`,
    };
  }
}

// Severity colors for the toast — keep red = block, amber = warn,
// blue = info. Matches the rest of the workbench palette.
const VIOLATION_TIER: Record<string, { fg: string; bg: string; border: string; icon: string; tier: "block" | "warn" | "info" }> = {
  valence_violation:        { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" },
  aromaticity_violation:    { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" },
  non_ring_aromatic_atom:   { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" },
  chemistry_violation:      { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" },
  bond_already_exists:      { fg: "#ca8a04", bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.30)", icon: "ⓘ", tier: "warn"  },
  swap_element_undervalent: { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" },
  fg_no_free_valence:       { fg: "#ca8a04", bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.30)", icon: "ⓘ", tier: "warn"  },
  ring_no_free_valence:     { fg: "#ca8a04", bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.30)", icon: "ⓘ", tier: "warn"  },
  atom_under_valent:        { fg: "#ca8a04", bg: "rgba(202,138,4,0.10)",  border: "rgba(202,138,4,0.30)", icon: "⚠", tier: "warn"  },
  unparseable_smiles:       { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" },
  missing_args:             { fg: "#0891b2", bg: "rgba(8,145,178,0.10)",  border: "rgba(8,145,178,0.30)", icon: "ⓘ", tier: "info"  },
  atom_index_out_of_range:  { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" },
  bond_index_out_of_range:  { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" },
  unsupported_element:      { fg: "#dc2626", bg: "rgba(220,38,38,0.10)",  border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" },
};
const VIOLATION_DEFAULT = { fg: "#dc2626", bg: "rgba(220,38,38,0.10)", border: "rgba(220,38,38,0.30)", icon: "⚠", tier: "block" as const };

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
  const [violation, setViolation] = useState<Violation | null>(null);
  // Whole-molecule diagnostics (incomplete atoms after a bond-break, etc).
  // Polled whenever SMILES changes; the rail + SVG highlight from this.
  const [diagnostics, setDiagnostics] = useState<{
    is_valid: boolean;
    incomplete_atoms: Violation[];
    all_violations: Violation[];
    n_fragments: number;
    total_formal_charge: number;
  } | null>(null);
  const showViolation = (v: Violation, autoDismissMs: number = 4000) => {
    setViolation(v);
    if (autoDismissMs > 0) {
      setTimeout(() => setViolation((cur) => (cur === v ? null : cur)), autoDismissMs);
    }
  };
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
  // SMARTS popover state (top-nav button → portal popover)
  const [smartsOpen, setSmartsOpen] = useState(false);
  const [smartsPopPos, setSmartsPopPos] = useState<{ left: number; top: number } | null>(null);
  const smartsBtnRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!smartsOpen) { setSmartsPopPos(null); return; }
    const update = () => {
      if (!smartsBtnRef.current) return;
      const r = smartsBtnRef.current.getBoundingClientRect();
      setSmartsPopPos({ left: r.left, top: r.bottom + 4 });
    };
    update();
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [smartsOpen]);

  useEffect(() => {
    if (!smartsOpen) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (t.closest("[data-smarts-pop]")) return;
      if (smartsBtnRef.current?.contains(t)) return;
      setSmartsOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setSmartsOpen(false); };
    setTimeout(() => document.addEventListener("mousedown", onDoc), 0);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [smartsOpen]);
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
        showViolation(await parseError(r, "drag_bond_failed"));
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
      showViolation({ code: "network_error", message: `drag-bond network error: ${e?.message ?? e}` });
    }
  }

  // Reset selection when SMILES changes (atom indices reshuffle)
  useEffect(() => { setSelected(new Set()); }, [smiles]);

  // Poll /chem/diagnostics whenever SMILES changes — debounced 200ms.
  // Used to highlight incomplete atoms (red pulse) after a bond-break.
  useEffect(() => {
    if (!smiles) { setDiagnostics(null); return; }
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const b64 = smilesToB64(smiles);
        const r = await fetch(`${apiBase}/workbench/chem/diagnostics/${b64}`);
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setDiagnostics(d);
      } catch {/*noop*/}
    }, 200);
    return () => { cancelled = true; clearTimeout(t); };
  }, [smiles, apiBase]);

  // Poll /chem/bonds whenever SMILES changes — needed to map a bond
  // click on the SVG back to a bond_index for /molecule/edit break_bond.
  const [bondList, setBondList] = useState<BondMeta[]>([]);
  const [hoveredBondIdx, setHoveredBondIdx] = useState<number | null>(null);
  const [recentlyBroken, setRecentlyBroken] = useState<Set<number>>(new Set());
  useEffect(() => {
    if (!smiles) { setBondList([]); return; }
    let cancelled = false;
    (async () => {
      try {
        const b64 = smilesToB64(smiles);
        const r = await fetch(`${apiBase}/workbench/chem/bonds/${b64}`);
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled) setBondList(d.bonds || []);
      } catch {/*noop*/}
    })();
    return () => { cancelled = true; };
  }, [smiles, apiBase]);

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
      .then((d) => { if (!cancelled) { setSvg(d.svg ?? ""); setViolation(null); } })
      .catch((err) => {
        if (cancelled) return;
        setSvg("");
        showViolation({ code: "render_failed",
          message: `2D render failed (status ${err})`,
          hint: "RDKit could not draw this structure. Check for unbalanced rings or invalid chirality.",
          suggested_fix: "undo last edit",
        });
      });
    return () => { cancelled = true; };
  }, [smiles, apiBase]);

  // Inject SVG safely + wire atom-click + atom-hover handlers
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host) return;
    const root = injectSvgSafely(host, svg);
    if (!root) return;
    // RDKit emits class="bond-0 atom-0 atom-1" on BOND paths — they share
    // the "atom-" substring with real atom elements. We need both gestures:
    //   • atom labels (no bond- class) → mousedown (drag-start) + click (select)
    //   • bond paths (has bond- class) → mousedown (drag-start using first atom-N)
    //                                  + bond-click (break) — handled in second loop
    // This way pure-carbon atoms (which RDKit doesn't draw as separate text
    // elements) remain draggable through their bond paths, and clicking a
    // bond breaks it without also opening the atom popover.
    const atoms = root.querySelectorAll("[class^='atom-'], [class*=' atom-']");
    const handlers: Array<{ node: Element; type: string; fn: (e: Event) => void }> = [];
    atoms.forEach((node) => {
      const cls = node.getAttribute("class") || "";
      const isBondPath = /(^|\s)bond-/.test(cls);
      const m = cls.match(/atom-(\d+)/);
      if (!m) return;
      const idx = parseInt(m[1], 10);
      (node as HTMLElement).style.cursor = "grab";

      // mousedown — always wired, lets the user drag-to-bond from any atom
      // (heteroatom label or carbon via bond path).
      const onMouseDown = (e: Event) => {
        const me = e as MouseEvent;
        if (me.shiftKey || me.button !== 0) return;
        e.stopPropagation();
        e.preventDefault();
        setDragStart(idx);
        (node as HTMLElement).style.cursor = "grabbing";
      };
      node.addEventListener("mousedown", onMouseDown);
      handlers.push({ node, type: "mousedown", fn: onMouseDown });

      // click — only on REAL atom labels (heteroatoms). On bond paths the
      // click is handled by the bond-click handler below (break_bond).
      if (!isBondPath) {
        const onClick = (e: Event) => {
          e.stopPropagation();
          const me = e as MouseEvent;
          if (me.shiftKey) {
            setSelected((cur) => {
              const next = new Set(cur);
              if (next.has(idx)) next.delete(idx);
              else next.add(idx);
              return next;
            });
            return;
          }
          setPop({ atomIdx: idx, x: me.clientX, y: me.clientY });
        };
        node.addEventListener("click", onClick);
        handlers.push({ node, type: "click", fn: onClick });
      }

      const onEnter = () => onCursorHover?.(idx);
      const onLeave = () => onCursorHover?.(null);
      node.addEventListener("mouseenter", onEnter);
      node.addEventListener("mouseleave", onLeave);
      handlers.push({ node, type: "mouseenter", fn: onEnter });
      handlers.push({ node, type: "mouseleave", fn: onLeave });
    });
    // Bond click → break_bond. RDKit emits class="bond-N" on each bond.
    // Click highlights the bond, then calls /molecule/edit op:break_bond.
    const bonds = root.querySelectorAll("[class^='bond-'], [class*=' bond-']");
    bonds.forEach((node) => {
      const cls = node.getAttribute("class") || "";
      const m = cls.match(/bond-(\d+)/);
      if (!m) return;
      const bondIdx = parseInt(m[1], 10);
      (node as HTMLElement).style.cursor = "pointer";
      // SVG bond hover → drive the central hoveredBondIdx state. That state
      // is the single source of truth for ALL bond hover affordances —
      // both the SVG glow (via the hoveredBondIdx useEffect) and the
      // BondsRail row highlight react to it.
      const onBondHover = () => { setHoveredBondIdx(bondIdx); };
      const onBondLeave = () => { setHoveredBondIdx((cur) => cur === bondIdx ? null : cur); };
      const onBondClick = (e: Event) => {
        e.stopPropagation();
        const me = e as MouseEvent;
        if (me.shiftKey || me.altKey) return;  // reserved for future modifiers
        // Don't break aromatic ring bonds — would shatter the ring.
        const meta = bondList.find((b) => b.bond_idx === bondIdx);
        if (meta?.in_ring && meta.order === "aromatic") {
          showViolation({
            code: "aromatic_ring_break",
            message: `Bond ${bondIdx} is part of an aromatic ring`,
            hint: "Breaking aromatic ring bonds destroys aromaticity. Try a non-aromatic bond instead.",
            bond_idx: bondIdx,
            suggested_fix: "delete an atom from the ring instead",
          });
          return;
        }
        void breakBond(bondIdx);
      };
      node.addEventListener("mouseenter", onBondHover);
      node.addEventListener("mouseleave", onBondLeave);
      node.addEventListener("click", onBondClick);
      handlers.push({ node, type: "mouseenter", fn: onBondHover });
      handlers.push({ node, type: "mouseleave", fn: onBondLeave });
      handlers.push({ node, type: "click", fn: onBondClick });
    });
    return () => handlers.forEach(({ node, type, fn }) => node.removeEventListener(type, fn));
  }, [svg, onCursorHover, bondList]);

  // Break a bond via /molecule/edit op:break_bond. Used by SVG bond clicks
  // AND by the AtomsRail bond row delete button. Captures the bond's two
  // endpoint atoms BEFORE deletion, then pulses them for 4s on the SVG so
  // the user sees exactly which atoms just lost a bond. RDKit auto-fills
  // implicit H, so the diagnostics-driven incomplete-atom highlight rarely
  // fires after a break — this client-side recently-broken pulse is the
  // primary visual feedback.
  const breakBond = async (bondIdx: number) => {
    if (!smiles) return;
    const bondMeta = bondList.find((b) => b.bond_idx === bondIdx);
    try {
      const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ smiles, op: "break_bond", bond_index: bondIdx }),
      });
      if (!r.ok) {
        showViolation(await parseError(r, "break_bond_failed"));
        return;
      }
      const d = await r.json();
      if (d.smiles) {
        // Mark the two endpoints as recently broken — they'll pulse amber
        // on the new SVG until the timeout clears them.
        if (bondMeta) {
          const endpoints = new Set<number>([bondMeta.atom_a, bondMeta.atom_b]);
          setRecentlyBroken(endpoints);
          setTimeout(() => setRecentlyBroken((cur) => {
            const next = new Set(cur);
            for (const idx of endpoints) next.delete(idx);
            return next;
          }), 4000);
        }
        onMoleculeEdit?.(d.smiles, {
          op: "break_bond", atom_idx: bondMeta?.atom_a ?? 0,
          label: `break bond ${bondIdx} (atoms ${bondMeta?.atom_a}–${bondMeta?.atom_b})`,
        });
      }
    } catch (exc: any) {
      showViolation({
        code: "network_error",
        message: `bond-break network error: ${exc?.message ?? exc}`,
      });
    }
  };

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

  // Incomplete-atom overlay — pulse red ring on atoms violating valence
  // (e.g. carbon with 3 bonds after a bond break). Uses /chem/diagnostics.
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host) return;
    const svgEl = host.querySelector("svg");
    if (!svgEl) return;
    svgEl.querySelectorAll('[data-incomplete="1"]').forEach((n) => n.remove());
    if (!diagnostics?.incomplete_atoms?.length) return;
    for (const v of diagnostics.incomplete_atoms) {
      if (v.atom_idx == null) continue;
      const target = svgEl.querySelector(`[class*="atom-${v.atom_idx}"]`);
      if (!target) continue;
      const bbox = (target as SVGGraphicsElement).getBBox?.();
      if (!bbox) continue;
      const cx = bbox.x + bbox.width / 2;
      const cy = bbox.y + bbox.height / 2;
      const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      ring.setAttribute("data-incomplete", "1");
      ring.setAttribute("cx", String(cx));
      ring.setAttribute("cy", String(cy));
      ring.setAttribute("r", "13");
      ring.setAttribute("fill", "none");
      ring.setAttribute("stroke", "#dc2626");
      ring.setAttribute("stroke-width", "2");
      ring.setAttribute("stroke-dasharray", "3,2");
      ring.setAttribute("opacity", "0.9");
      ring.style.pointerEvents = "none";
      // Pulse animation
      const anim = document.createElementNS("http://www.w3.org/2000/svg", "animate");
      anim.setAttribute("attributeName", "r");
      anim.setAttribute("values", "13;16;13");
      anim.setAttribute("dur", "1.2s");
      anim.setAttribute("repeatCount", "indefinite");
      ring.appendChild(anim);
      const animO = document.createElementNS("http://www.w3.org/2000/svg", "animate");
      animO.setAttribute("attributeName", "opacity");
      animO.setAttribute("values", "0.9;0.45;0.9");
      animO.setAttribute("dur", "1.2s");
      animO.setAttribute("repeatCount", "indefinite");
      ring.appendChild(animO);
      svgEl.appendChild(ring);
    }
  }, [diagnostics, svg]);

  // Recently-broken-bond endpoint pulse — amber dashed ring on the two
  // atoms whose bond was just severed. Fires immediately on break_bond,
  // clears after 4s. Complements the diagnostics-driven red pulse for
  // cases where RDKit auto-fills implicit H (most carbon-carbon breaks).
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host) return;
    const svgEl = host.querySelector("svg");
    if (!svgEl) return;
    svgEl.querySelectorAll('[data-recent-break="1"]').forEach((n) => n.remove());
    if (!recentlyBroken.size) return;
    for (const idx of recentlyBroken) {
      const target = svgEl.querySelector(`[class*="atom-${idx}"]`);
      if (!target) continue;
      const bbox = (target as SVGGraphicsElement).getBBox?.();
      if (!bbox) continue;
      const cx = bbox.x + bbox.width / 2;
      const cy = bbox.y + bbox.height / 2;
      const ring = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      ring.setAttribute("data-recent-break", "1");
      ring.setAttribute("cx", String(cx));
      ring.setAttribute("cy", String(cy));
      ring.setAttribute("r", "13");
      ring.setAttribute("fill", "none");
      ring.setAttribute("stroke", "#f59e0b");
      ring.setAttribute("stroke-width", "2");
      ring.setAttribute("stroke-dasharray", "3,2");
      ring.setAttribute("opacity", "0.95");
      ring.style.pointerEvents = "none";
      const animR = document.createElementNS("http://www.w3.org/2000/svg", "animate");
      animR.setAttribute("attributeName", "r");
      animR.setAttribute("values", "10;16;10");
      animR.setAttribute("dur", "0.9s");
      animR.setAttribute("repeatCount", "indefinite");
      ring.appendChild(animR);
      svgEl.appendChild(ring);
    }
  }, [recentlyBroken, svg]);

  // Hovered-bond glow — driven by hoveredBondIdx (set from rail row hover).
  // The SVG bond-mouseenter handler also sets this directly via onHoverBond
  // wiring, so glow appears on both rail-hover and SVG-hover.
  useEffect(() => {
    const host = svgHostRef.current;
    if (!host) return;
    const svgEl = host.querySelector("svg");
    if (!svgEl) return;
    svgEl.querySelectorAll("[class^='bond-'], [class*=' bond-']").forEach((n) => {
      const cls = n.getAttribute("class") || "";
      const m = cls.match(/bond-(\d+)/);
      if (!m) return;
      const idx = parseInt(m[1], 10);
      const el = n as SVGElement & { style: CSSStyleDeclaration };
      el.style.filter = (idx === hoveredBondIdx)
        ? "drop-shadow(0 0 4px #dc2626) drop-shadow(0 0 2px #dc2626)"
        : "";
    });
  }, [hoveredBondIdx, svg, bondList]);

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
        showViolation({
          code: "unsupported_op",
          message: `unsupported op: ${op}`,
          hint: "ChemKnowledgeCard sent an op the dispatcher doesn't recognize.",
        }, 2400);
        return;
      }
      const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        showViolation(await parseError(r, "edit_failed"));
        return;
      }
      const d = await r.json();
      if (d.smiles) {
        onMoleculeEdit?.(d.smiles, { op, atom_idx: atomIdx, label: params.label });
      }
    } catch (e: any) {
      showViolation({ code: "network_error", message: `edit network error: ${e?.message ?? e}` });
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
        {/* Library trigger — mutually exclusive with SMARTS popover */}
        {onLoadFromLibrary && (
          <button
            ref={libraryBtnRef}
            type="button"
            onClick={() => {
              setSmartsOpen(false);  // close sibling first
              setLibraryOpen((o) => !o);
            }}
            title="Library — saved candidates from prior sessions. Search by name/tag/SMILES, click any row to load it into the 2D viewer."
            style={navBtnStyle(libraryOpen, "#10b981")}>
            <span style={{ fontSize: 10, lineHeight: 1 }}>📚</span>
            <span style={{ textTransform: "none", letterSpacing: 0 }}>Library</span>
          </button>
        )}
        {/* SMARTS trigger — mutually exclusive with Library popover */}
        <button
          ref={smartsBtnRef}
          type="button"
          onClick={() => {
            setLibraryOpen(false);  // close sibling first
            setSmartsOpen((o) => !o);
          }}
          title="SMARTS — substructure pattern search. Type a pattern (or pick a preset) to highlight matching atoms in the 2D structure (e.g. β-lactam ring, amide, halogen)."
          style={navBtnStyle(smartsOpen, "#0891b2")}>
          <span style={{ fontSize: 10, lineHeight: 1 }}>🔍</span>
          <span style={{ textTransform: "none", letterSpacing: 0 }}>
            SMARTS{smartsHits.length > 0 ? ` · ${smartsHits.length}` : ""}
          </span>
        </button>
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

      {/* SMARTS-strip ELIMINATED — moved to top-nav button (popover render at end of component). */}
      {false && <div style={{
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
      </div>}
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
          {/* Violation toast — structured, replaces simple `error` string.
              Shows code + message + hint + suggested fix as an action button. */}
          {violation && (() => {
            const tier = VIOLATION_TIER[violation.code] ?? VIOLATION_DEFAULT;
            return (
              <div style={{
                position: "absolute", bottom: 8, left: "50%",
                transform: "translateX(-50%)",
                maxWidth: "84%",
                background: tier.bg,
                border: `1px solid ${tier.border}`,
                borderRadius: 6,
                backdropFilter: "blur(8px)",
                padding: "6px 10px",
                fontFamily: "var(--lys-font-body)",
                fontSize: 10.5,
                color: tier.fg,
                display: "flex", flexDirection: "column", gap: 2,
                boxShadow: "0 4px 14px rgba(15,23,42,0.10)",
                zIndex: 200,
              }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{
                    fontSize: 11, fontWeight: 800,
                    width: 16, height: 16, borderRadius: "50%",
                    background: tier.fg, color: "white",
                    display: "grid", placeItems: "center",
                  }}>{tier.icon}</span>
                  <span style={{ fontWeight: 700 }}>{violation.message}</span>
                  <span style={{ flex: 1 }} />
                  <button type="button"
                    onClick={() => setViolation(null)}
                    style={{
                      border: 0, background: "transparent", cursor: "pointer",
                      color: tier.fg, opacity: 0.6, padding: 0,
                      fontSize: 12, lineHeight: 1,
                    }}>✕</button>
                </div>
                {violation.hint && (
                  <div style={{ fontSize: 9.5, opacity: 0.85, lineHeight: 1.4,
                    paddingLeft: 22 }}>
                    {violation.hint}
                  </div>
                )}
                {violation.suggested_fix && (
                  <div style={{ fontSize: 9, paddingLeft: 22, opacity: 0.75,
                    fontFamily: "var(--lys-font-mono)" }}>
                    <span style={{ fontWeight: 700,
                      letterSpacing: "0.04em", textTransform: "uppercase" }}>
                      try:
                    </span>{" "}
                    {violation.suggested_fix}
                  </div>
                )}
                {(violation.atom_idx != null || violation.bond_idx != null) && (
                  <div style={{
                    fontSize: 8.5, paddingLeft: 22,
                    fontFamily: "var(--lys-font-mono)", opacity: 0.65,
                  }}>
                    {violation.atom_idx != null && `atom ${violation.atom_idx}`}
                    {violation.bond_idx != null && `bond ${violation.bond_idx}`}
                    {" · "}{violation.code}
                  </div>
                )}
              </div>
            );
          })()}
          {/* Diagnostics banner — when molecule has incomplete atoms after
              a bond-break, show a sticky banner so the user knows. */}
          {diagnostics && !diagnostics.is_valid && diagnostics.incomplete_atoms.length > 0 && !violation && (
            <div style={{
              position: "absolute", top: 8, left: "50%", transform: "translateX(-50%)",
              padding: "4px 10px",
              background: "rgba(220,38,38,0.10)",
              border: "1px solid rgba(220,38,38,0.35)",
              borderRadius: 6,
              fontSize: 10, fontFamily: "var(--lys-font-body)",
              color: "#dc2626", fontWeight: 600,
              zIndex: 60,
              backdropFilter: "blur(8px)",
              boxShadow: "0 2px 8px rgba(220,38,38,0.10)",
            }}>
              ⚠ {diagnostics.incomplete_atoms.length} incomplete atom{diagnostics.incomplete_atoms.length === 1 ? "" : "s"} · pulsing red — needs reconnection
            </div>
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
                showViolation(await parseError(r, "delete_atom_failed"));
                return;
              }
              const d = await r.json();
              if (d.smiles) {
                onMoleculeEdit?.(d.smiles, { op: "delete_atom", atom_idx: idx, label: `delete atom ${idx}` });
              }
            } catch (exc: any) {
              showViolation({ code: "network_error", message: `delete failed: ${exc?.message ?? exc}` });
            }
          }}
          onAddAtom={async (element?: string) => {
            if (!smiles) return;
            const elt = element ?? "C";
            try {
              const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  smiles, op: "add_atom_at", atom_index: 0,
                  new_element: elt, bond_order: "single",
                }),
              });
              if (!r.ok) {
                showViolation(await parseError(r, "add_atom_failed"));
                return;
              }
              const d = await r.json();
              if (d.smiles) {
                onMoleculeEdit?.(d.smiles, { op: "add_atom_at", atom_idx: 0, label: `+${elt} atom` });
              }
            } catch (exc: any) {
              showViolation({ code: "network_error", message: `add atom failed: ${exc?.message ?? exc}` });
            }
          }}
          onSwapElement={async (idx, newElement) => {
            if (!smiles) return;
            try {
              const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  smiles, op: "swap_element", atom_index: idx,
                  new_element: newElement,
                }),
              });
              if (!r.ok) {
                showViolation(await parseError(r, "swap_element_failed"));
                return;
              }
              const d = await r.json();
              if (d.smiles) {
                onMoleculeEdit?.(d.smiles, {
                  op: "swap_element", atom_idx: idx,
                  label: `swap ${idx} → ${newElement}`,
                });
              }
            } catch (exc: any) {
              showViolation({ code: "network_error", message: `swap failed: ${exc?.message ?? exc}` });
            }
          }}
          onAddNeighbor={async (anchorIdx, element, bondOrder) => {
            if (!smiles) return;
            try {
              const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  smiles, op: "add_atom_at", atom_index: anchorIdx,
                  new_element: element, bond_order: bondOrder,
                }),
              });
              if (!r.ok) {
                showViolation(await parseError(r, "add_neighbor_failed"));
                return;
              }
              const d = await r.json();
              if (d.smiles) {
                onMoleculeEdit?.(d.smiles, {
                  op: "add_atom_at", atom_idx: anchorIdx,
                  label: `+${element} (${bondOrder}) on ${anchorIdx}`,
                });
              }
            } catch (exc: any) {
              showViolation({ code: "network_error", message: `neighbor failed: ${exc?.message ?? exc}` });
            }
          }}
          onAttachFG={async (anchorIdx, fgName, label) => {
            if (!smiles) return;
            try {
              const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  smiles, op: "add_functional_group_at",
                  atom_index: anchorIdx, functional_group: fgName,
                }),
              });
              if (!r.ok) {
                showViolation(await parseError(r, "attach_fg_failed"));
                return;
              }
              const d = await r.json();
              if (d.smiles) {
                onMoleculeEdit?.(d.smiles, {
                  op: "add_functional_group_at", atom_idx: anchorIdx,
                  label: `${label} on atom ${anchorIdx}`,
                });
              }
            } catch (exc: any) {
              showViolation({ code: "network_error", message: `${label} failed: ${exc?.message ?? exc}` });
            }
          }}
          onAttachFragment={async (anchorIdx, fragmentSmiles, label, bondOrder = "single") => {
            if (!smiles) return;
            try {
              const r = await fetch(`${apiBase}/workbench/molecule/edit`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  smiles, op: "attach_fragment",
                  atom_index: anchorIdx,
                  fragment_smiles: fragmentSmiles,
                  fragment_anchor_idx: 0,
                  bond_order: bondOrder,
                }),
              });
              if (!r.ok) {
                showViolation(await parseError(r, "attach_fragment_failed"));
                return;
              }
              const d = await r.json();
              if (d.smiles) {
                onMoleculeEdit?.(d.smiles, {
                  op: "attach_fragment", atom_idx: anchorIdx,
                  label: `${label} on atom ${anchorIdx}`,
                });
              }
            } catch (exc: any) {
              showViolation({ code: "network_error", message: `${label} failed: ${exc?.message ?? exc}` });
            }
          }}
          onReplaceSmiles={async (newSmiles, label) => {
            try {
              const r = await fetch(`${apiBase}/workbench/molecule/replace`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ smiles: newSmiles }),
              });
              if (!r.ok) {
                showViolation(await parseError(r, "replace_smiles_failed"));
                return;
              }
              const d = await r.json();
              if (d.smiles) {
                onMoleculeEdit?.(d.smiles, {
                  op: "replace_smiles", atom_idx: 0,
                  label,
                });
              }
            } catch (exc: any) {
              showViolation({ code: "network_error", message: `replace failed: ${exc?.message ?? exc}` });
            }
          }}
          bonds={bondList}
          hoveredBondIdx={hoveredBondIdx}
          onHoverBond={(idx) => setHoveredBondIdx(idx)}
          onBreakBond={(idx) => { void breakBond(idx); }}
          incompleteAtomIdxs={new Set((diagnostics?.incomplete_atoms || [])
            .map((v) => v.atom_idx).filter((x): x is number => x != null))}
          recentlyBrokenAtomIdxs={recentlyBroken}
        />
        {pop && smiles && createPortal(
          <div data-chem-pop style={{
            position: "fixed",
            left: Math.max(8, Math.min(pop.x + 12, window.innerWidth - CHEM_POP_W - 8)),
            top: Math.max(8, Math.min(pop.y + 12, window.innerHeight - CHEM_POP_H - 8)),
            zIndex: 6000,
            width: CHEM_POP_W,
            maxHeight: CHEM_POP_H,
          }}>
            <ChemKnowledgeCard
              apiBase={apiBase}
              smiles={smiles}
              atomIdx={pop.atomIdx}
              onApply={(op, params) => applyEdit(op, params, pop.atomIdx)}
              onClose={() => setPop(null)}
            />
          </div>, document.body)}
      </div>
      {/* Multi-select bond toolbar — sibling row BELOW the body row so it
          never overlaps the molecule SVG. Animates in only when ≥2 atoms
          are shift-clicked. Chemistry-rules-aware: bond orders limited by
          remaining valence on both endpoints. */}
      {selected.size >= 2 && smiles && (
        <div style={{
          flexShrink: 0,
          display: "flex", alignItems: "center", gap: 10,
          padding: "6px 12px",
          background: "linear-gradient(180deg, rgba(245,158,11,0.06), rgba(245,158,11,0.10))",
          borderTop: "1px solid rgba(245, 158, 11, 0.32)",
          fontSize: 10.5,
          fontFamily: "var(--lys-font-mono)",
          color: "#92400e",
        }}>
          <span style={{ fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase" }}>
            bond
          </span>
          <span style={{ opacity: 0.7 }}>
            atom {Array.from(selected).slice(0, 2).join(" ↔ atom ")}
            {selected.size > 2 ? ` +${selected.size - 2}` : ""}
          </span>
          <span style={{ flex: 1 }} />
          {(["single", "double", "triple"] as const).map((bo) => (
            <button
              key={bo}
              type="button"
              onClick={async () => {
                const ids = Array.from(selected);
                if (ids.length < 2) return;
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
                    showViolation(await parseError(r, "add_bond_failed"));
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
                  showViolation({ code: "network_error", message: `bond network error: ${exc?.message ?? exc}` });
                }
              }}
              style={{
                border: "1px solid rgba(245,158,11,0.45)",
                background: "rgba(245,158,11,0.18)",
                color: "#92400e",
                padding: "3px 10px", borderRadius: 999,
                fontFamily: "inherit", fontSize: 10, fontWeight: 700,
                cursor: "pointer",
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "rgba(245,158,11,0.32)"; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = "rgba(245,158,11,0.18)"; }}
            >
              + {bo}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setSelected(new Set())}
            title="Clear selection"
            style={{
              border: 0, background: "transparent", color: "#92400e",
              padding: "3px 8px", borderRadius: 4,
              cursor: "pointer", fontFamily: "inherit", fontSize: 10,
            }}
          >
            clear
          </button>
        </div>
      )}
      {libraryOpen && libraryBtnRef.current && onLoadFromLibrary && (
        <LibraryPopover
          apiBase={apiBase}
          currentSmiles={smiles}
          anchor={libraryBtnRef.current}
          onClose={() => setLibraryOpen(false)}
          onLoad={(smi, name) => { onLoadFromLibrary(smi, name); setLibraryOpen(false); }}
        />
      )}
      {smartsOpen && smartsPopPos && createPortal(
        <div data-smarts-pop style={{
          position: "fixed", left: smartsPopPos.left, top: smartsPopPos.top,
          width: 460, maxHeight: "60vh",
          background: "var(--lys-bg-2, #ffffff)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 10,
          boxShadow: "0 14px 40px rgba(15,23,42,0.18), 0 2px 8px rgba(15,23,42,0.10)",
          zIndex: 5000, display: "flex", flexDirection: "column",
          overflow: "hidden", fontFamily: "var(--lys-font-body)",
        }}>
          <div style={{ padding: "8px 10px",
            borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
            display: "flex", flexDirection: "column", gap: 6,
            background: "var(--lys-bg, #fafafa)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--lys-text)" }}>
                🔍 SMARTS{smartsHits.length > 0 ? ` · ${smartsHits.length} hits` : ""}
              </span>
              <span style={{ flex: 1 }} />
              <button type="button" onClick={() => setSmartsOpen(false)}
                style={{ border: 0, background: "transparent", cursor: "pointer",
                  padding: 4, color: "var(--lys-text-faint)" }}>✕</button>
            </div>
            {/* One-line context — what is this and how does it relate to 2D */}
            <div style={{
              fontSize: 9.5, lineHeight: 1.35,
              color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-body)",
            }}>
              Substructure pattern search — type a SMARTS pattern (or pick a
              preset) to highlight matching atoms in the 2D structure. Useful
              for spotting motifs like β-lactam, amide, halogens, aromatic rings.
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <input
                value={smarts}
                onChange={(e) => setSmarts(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") runSmartsMatch(smarts); }}
                placeholder="pattern · e.g. c1ccccc1 — Enter to match"
                disabled={!smiles}
                autoFocus
                style={{
                  flex: 1, fontSize: 11, fontFamily: "var(--lys-font-mono)",
                  padding: "4px 8px", borderRadius: 4,
                  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
                  background: "var(--lys-bg-2, #ffffff)",
                  color: "var(--lys-text)", outline: "none",
                }} />
              <button type="button"
                onClick={() => runSmartsMatch(smarts)}
                disabled={!smiles || !smarts || smartsLoading}
                style={{
                  padding: "4px 11px", borderRadius: 4,
                  fontSize: 10, fontFamily: "var(--lys-font-mono)", fontWeight: 700,
                  background: "#0891b2", color: "white", border: 0,
                  cursor: smiles && smarts ? "pointer" : "not-allowed",
                  opacity: smiles && smarts ? 1 : 0.5,
                }}>{smartsLoading ? "…" : "match"}</button>
              {smartsHits.length > 0 && (
                <button type="button"
                  onClick={() => { setSmarts(""); setSmartsHits([]); setSmartsError(""); }}
                  title="Clear match"
                  style={{ border: 0, background: "transparent",
                    color: "var(--lys-text-faint)",
                    cursor: "pointer", padding: 4, fontSize: 12 }}>✕</button>
              )}
            </div>
            {smartsError && (
              <span style={{ fontSize: 9.5, color: "#dc2626",
                fontFamily: "var(--lys-font-mono)" }}>⚠ {smartsError}</span>
            )}
          </div>
          <div className="lys-card-body" style={{
            flex: 1, overflow: "auto", padding: 8,
            display: "flex", flexWrap: "wrap", gap: 4,
          }}>
            <span style={{ fontSize: 9, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)",
              letterSpacing: "0.06em", textTransform: "uppercase",
              fontWeight: 700, alignSelf: "center", marginRight: 4,
            }}>presets</span>
            {SMARTS_PRESETS.map((p) => (
              <button key={p.label} type="button"
                onClick={() => { setSmarts(p.pattern); runSmartsMatch(p.pattern); }}
                title={p.pattern}
                disabled={!smiles}
                style={{
                  fontSize: 10, padding: "3px 9px", borderRadius: 999,
                  border: `1px solid ${smarts === p.pattern ? "#0891b2" : "var(--lys-border-faint, rgba(0,0,0,0.10))"}`,
                  background: smarts === p.pattern ? "rgba(8,145,178,0.10)" : "var(--lys-bg-2, #ffffff)",
                  color: smarts === p.pattern ? "#0891b2" : "var(--lys-text-dim)",
                  cursor: smiles ? "pointer" : "not-allowed",
                  opacity: smiles ? 1 : 0.5,
                  fontFamily: "var(--lys-font-body)",
                  fontWeight: smarts === p.pattern ? 700 : 500,
                }}>{p.label}</button>
            ))}
          </div>
        </div>, document.body)}
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
        {/* One-line context — what is this and how does it relate to 2D */}
        <div style={{
          fontSize: 9.5, lineHeight: 1.35,
          color: "var(--lys-text-faint)",
          fontFamily: "var(--lys-font-body)",
        }}>
          Saved candidates from prior sessions. Click any row to load it
          into the 2D viewer · save the current structure with custom tags.
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
interface BondMeta {
  bond_idx: number;
  atom_a: number;
  atom_b: number;
  order: string;
  in_ring: boolean;
  is_aromatic?: boolean;
}

interface AtomsRailProps {
  apiBase: string;
  smiles: string | null;
  selected: Set<number>;
  hoverIdx: number | null;
  onSelectAtom: (idx: number) => void;
  onHoverAtom: (idx: number | null) => void;
  onDeleteAtom?: (idx: number) => void;
  onAddAtom?: (element?: string) => void;
  onSwapElement?: (idx: number, newElement: string) => void;
  onAddNeighbor?: (anchorIdx: number, element: string, bondOrder: "single" | "double" | "triple") => void;
  onAttachFragment?: (anchorIdx: number, fragmentSmiles: string, label: string, bondOrder?: "single" | "double" | "aromatic") => void;
  onAttachFG?: (anchorIdx: number, fgName: string, label: string) => void;
  onReplaceSmiles?: (newSmiles: string, label: string) => void;
  // Bonds — passed in from parent (lifted state, single source of truth).
  bonds?: BondMeta[];
  hoveredBondIdx?: number | null;
  incompleteAtomIdxs?: Set<number>;
  recentlyBrokenAtomIdxs?: Set<number>;
  onHoverBond?: (idx: number | null) => void;
  onBreakBond?: (bondIdx: number) => void;
}

interface ElementInfo {
  sym: string;
  Z: number;
  valences: number[];
  name: string;
  group: string;
}

interface AtomRow {
  idx: number;
  element: string;
  atomic_number: number;
  atomic_mass: number;
  is_aromatic: boolean;
  in_ring: boolean;
  ring_size: number;
  n_hydrogens: number;
  formal_charge: number;
  n_neighbors: number;
  hybridization: string;
  degree: number;            // heavy-atom bond count
  free_valence: number;       // open slots remaining
  is_chiral: boolean;
  cip_code: string;
  bonds: { order: string; count: number }[];   // bond-order summary (single/double/triple/aromatic)
}

// Element name lookup for tooltips
const ELEMENT_NAMES: Record<string, string> = {
  H: "Hydrogen", C: "Carbon", N: "Nitrogen", O: "Oxygen", F: "Fluorine",
  Cl: "Chlorine", Br: "Bromine", I: "Iodine", S: "Sulfur", P: "Phosphorus",
  Na: "Sodium", K: "Potassium", Mg: "Magnesium", Ca: "Calcium",
  Fe: "Iron", Cu: "Copper", Zn: "Zinc", Pt: "Platinum", Pd: "Palladium",
  Au: "Gold", Ag: "Silver", Hg: "Mercury", As: "Arsenic", Se: "Selenium",
  B: "Boron", Si: "Silicon", Al: "Aluminum", Ti: "Titanium", V: "Vanadium",
  Cr: "Chromium", Mn: "Manganese", Co: "Cobalt", Ni: "Nickel",
  Mo: "Molybdenum", Ru: "Ruthenium",
};

const BOND_GLYPH: Record<string, string> = {
  single: "—",
  double: "=",
  triple: "≡",
  aromatic: "⌬",
};

function AtomsRail(p: AtomsRailProps) {
  const [atoms, setAtoms] = useState<AtomRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [palette, setPalette] = useState<ElementInfo[]>([]);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [palettePos, setPalettePos] = useState<{ left: number; top: number } | null>(null);
  const addBtnRef = useRef<HTMLButtonElement | null>(null);

  // Fetch element palette once — backend is source of truth
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const r = await fetch(`${p.apiBase}/workbench/chem/elements`);
        if (!r.ok) return;
        const d = await r.json();
        if (!cancelled && Array.isArray(d.elements)) setPalette(d.elements);
      } catch {/*noop*/}
    })();
    return () => { cancelled = true; };
  }, [p.apiBase]);

  // Position the palette popover anchored under the + button
  useEffect(() => {
    if (!paletteOpen) { setPalettePos(null); return; }
    const update = () => {
      if (!addBtnRef.current) return;
      const r = addBtnRef.current.getBoundingClientRect();
      setPalettePos({ left: r.right - 320, top: r.bottom + 4 });
    };
    update();
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Element | null;
      if (t && t.closest && t.closest("[data-element-pop]")) return;
      if (addBtnRef.current && t && addBtnRef.current.contains(t as Node)) return;
      setPaletteOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setPaletteOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    window.addEventListener("scroll", update, true);
    window.addEventListener("resize", update);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", update, true);
      window.removeEventListener("resize", update);
    };
  }, [paletteOpen]);

  useEffect(() => {
    if (!p.smiles) { setAtoms([]); return; }
    let cancelled = false;
    setLoading(true);
    (async () => {
      try {
        const b64 = smilesToB64(p.smiles!);
        const r = await fetch(`${p.apiBase}/workbench/molecule/2d/${b64}?w=200&h=200`);
        if (!r.ok) { setAtoms([]); return; }
        const meta = await r.json();
        const n = meta.n_atoms ?? 0;
        const promises = Array.from({ length: n }, (_, i) =>
          fetch(`${p.apiBase}/workbench/chem/atom/${b64}/${i}`)
            .then((ar) => ar.ok ? ar.json() : null)
            .catch(() => null));
        const results = await Promise.all(promises);
        if (cancelled) return;
        const rows: AtomRow[] = results.map((a, i) => {
          if (!a) return null;
          // Bond-order distribution
          const bondMap: Record<string, number> = {};
          for (const nb of a.neighbors || []) {
            bondMap[nb.bond] = (bondMap[nb.bond] || 0) + 1;
          }
          const bonds = Object.entries(bondMap).map(([order, count]) => ({
            order, count: count as number,
          }));
          return {
            idx: i,
            element: a.element,
            atomic_number: a.atomic_number ?? 0,
            atomic_mass: a.atomic_mass ?? 0,
            is_aromatic: a.is_aromatic,
            in_ring: a.in_ring,
            ring_size: a.ring_size,
            n_hydrogens: a.n_hydrogens,
            formal_charge: a.formal_charge,
            n_neighbors: (a.neighbors || []).length,
            hybridization: a.hybridization ?? "",
            degree: a.degree ?? (a.neighbors || []).length,
            free_valence: a.free_valence ?? a.n_hydrogens,
            is_chiral: a.is_chiral ?? false,
            cip_code: a.cip_code ?? "",
            bonds,
          };
        }).filter((x): x is AtomRow => x !== null);
        if (!cancelled) setAtoms(rows);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [p.smiles, p.apiBase]);

  // Filter bar — chips of unique elements present, click to filter
  const [elementFilter, setElementFilter] = useState<string>("");
  const uniqueElements = Array.from(new Set(atoms.map((a) => a.element)));
  const visibleAtoms = elementFilter ? atoms.filter((a) => a.element === elementFilter) : atoms;

  // Per-row inline action menu state
  const [actionRowIdx, setActionRowIdx] = useState<number | null>(null);
  const [actionMode, setActionMode] = useState<"swap" | "neighbor" | null>(null);
  const [actionPos, setActionPos] = useState<{ left: number; top: number } | null>(null);
  const [neighborBondOrder, setNeighborBondOrder] = useState<"single" | "double" | "triple">("single");
  const actionRowRef = useRef<HTMLElement | null>(null);

  const openRowAction = (idx: number, mode: "swap" | "neighbor", anchor: HTMLElement) => {
    actionRowRef.current = anchor;
    setActionRowIdx(idx);
    setActionMode(mode);
    const r = anchor.getBoundingClientRect();
    setActionPos({ left: Math.max(8, r.right - 320), top: r.bottom + 4 });
  };
  useEffect(() => {
    if (actionRowIdx == null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { setActionRowIdx(null); setActionMode(null); setActionPos(null); }
    };
    const onDoc = (e: MouseEvent) => {
      const t = e.target as Element | null;
      if (t && t.closest && t.closest("[data-row-action-pop]")) return;
      if (actionRowRef.current && t && actionRowRef.current.contains(t as Node)) return;
      setActionRowIdx(null); setActionMode(null); setActionPos(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDoc);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDoc);
    };
  }, [actionRowIdx]);

  // Aggregate stats summary
  const stats = {
    heavy: atoms.length,
    rings: new Set(atoms.filter((a) => a.in_ring).map((a) => a.ring_size)).size > 0
      ? atoms.filter((a) => a.in_ring).length / Math.max(1, Math.min(...atoms.filter((a) => a.in_ring).map((a) => a.ring_size) || [1]))
      : 0,
    aromaticAtoms: atoms.filter((a) => a.is_aromatic).length,
    charged: atoms.filter((a) => a.formal_charge !== 0).length,
    chiral: atoms.filter((a) => a.is_chiral).length,
  };

  const ELEMENT_COLOR: Record<string, string> = {
    C: "#374151", N: "#2563eb", O: "#dc2626", S: "#ca8a04",
    F: "#16a34a", Cl: "#16a34a", Br: "#9a3412", I: "#7c3aed",
    P: "#ea580c", H: "#9ca3af",
    Fe: "#b45309", Cu: "#c2410c", Zn: "#737373", Pt: "#475569",
    Pd: "#475569", Au: "#ca8a04", Ag: "#71717a", Hg: "#737373",
    As: "#7c3aed", Se: "#a16207", B: "#16a34a", Si: "#525252",
    Na: "#a855f7", Mg: "#c084fc", Ca: "#c084fc", K: "#a855f7",
  };

  return (
    <div style={{
      width: 320, flexShrink: 0,
      borderLeft: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
      background: "var(--lys-bg, #fafafa)",
      display: "flex", flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* Header — title + count + add. Tooltip-driven help. */}
      <div
        title="Atom inventory · click any row to select & highlight in 2D · hover row to see actions (swap element, add neighbor, delete)"
        style={{
          padding: "5px 8px 4px",
          fontSize: 9, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em", textTransform: "uppercase",
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
          display: "flex", alignItems: "center", gap: 5,
        }}>
        <span style={{ fontWeight: 700 }}>atoms</span>
        <span style={{ color: "#10b981", fontWeight: 700 }}>{atoms.length}</span>
        <span style={{ flex: 1 }} />
        {p.smiles && p.onAddAtom && (
          <button type="button"
            ref={addBtnRef}
            onClick={() => setPaletteOpen((o) => !o)}
            title="Add new atom · pick element from periodic table"
            style={{
              border: `1px solid ${paletteOpen ? "#059669" : "rgba(16,185,129,0.30)"}`,
              background: paletteOpen ? "rgba(16,185,129,0.15)" : "rgba(16,185,129,0.06)",
              cursor: "pointer", padding: "1px 8px",
              color: paletteOpen ? "#059669" : "#10b981",
              borderRadius: 4,
              fontSize: 10, fontWeight: 700, lineHeight: 1.4,
            }}>+ atom</button>
        )}
      </div>
      {/* Sub-line description removed — folded into the header `title`
          tooltip. The header itself ("ATOMS · N · + atom") is enough
          identifier; explanatory text only on hover. */}
      {/* Stats band — quick chemistry summary */}
      {atoms.length > 0 && (
        <div style={{
          padding: "4px 8px",
          display: "flex", flexWrap: "wrap", gap: 4,
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
          fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
          background: "rgba(0,0,0,0.015)",
        }}>
          <RailStat label="atoms" value={String(atoms.length)} color="#374151" tip="Heavy atoms (excludes implicit H)" />
          <RailStat label="aromatic" value={String(stats.aromaticAtoms)} color="#a855f7" tip="Atoms in aromatic systems" />
          <RailStat label="charged" value={String(stats.charged)} color="#dc2626" tip="Atoms with non-zero formal charge" />
          {stats.chiral > 0 && (
            <RailStat label="chiral" value={String(stats.chiral)} color="#0891b2" tip="Stereocenters with assigned chirality" />
          )}
        </div>
      )}
      {/* Element filter chips */}
      {uniqueElements.length > 1 && (
        <div style={{
          padding: "4px 8px",
          display: "flex", flexWrap: "wrap", gap: 3,
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
          background: "var(--lys-bg-2, #ffffff)",
        }}>
          <FilterChip label={`all · ${atoms.length}`} active={!elementFilter} onClick={() => setElementFilter("")} color="#6b7280" />
          {uniqueElements.map((el) => {
            const cnt = atoms.filter((a) => a.element === el).length;
            return (
              <FilterChip key={el}
                label={`${el} · ${cnt}`}
                active={elementFilter === el}
                onClick={() => setElementFilter(elementFilter === el ? "" : el)}
                color={ELEMENT_COLOR[el] ?? "#374151"}
                tip={ELEMENT_NAMES[el] ?? el}
              />
            );
          })}
        </div>
      )}
      {/* Atoms list — flex:1 lets it grow but BuildTools below claims its share */}
      <div className="lys-card-body" style={{ flex: "1 1 0", minHeight: 80, overflow: "auto" }}>
        {!p.smiles && (
          <div style={{
            padding: "20px 12px", textAlign: "center",
            fontSize: 10, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-body)", lineHeight: 1.4,
          }}>
            <div style={{ fontSize: 16, marginBottom: 4, opacity: 0.4 }}>⚛</div>
            <div style={{ fontWeight: 600 }}>No candidate yet</div>
            <div style={{ fontSize: 9, marginTop: 3 }}>Pick a scaffold from the top nav, or load a saved molecule from Library.</div>
          </div>
        )}
        {p.smiles && loading && atoms.length === 0 && (
          <div style={{ padding: "16px 10px", textAlign: "center",
            fontSize: 10, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)" }}>loading atoms…</div>
        )}
        {visibleAtoms.map((a) => {
          const c = ELEMENT_COLOR[a.element] ?? "#374151";
          const isSelected = p.selected.has(a.idx);
          const isHover = p.hoverIdx === a.idx;
          const fullName = ELEMENT_NAMES[a.element] ?? a.element;
          const isIncomplete = p.incompleteAtomIdxs?.has(a.idx) ?? false;
          const isRecentlyBroken = p.recentlyBrokenAtomIdxs?.has(a.idx) ?? false;
          // Border color priority: incomplete > recently-broken > selected
          const borderColor = isIncomplete ? "#dc2626"
                            : isRecentlyBroken ? "#f59e0b"
                            : isSelected ? "#f59e0b"
                            : "transparent";
          const rowBg = isIncomplete ? "rgba(220,38,38,0.06)"
                      : isRecentlyBroken ? "rgba(245,158,11,0.06)"
                      : isSelected ? "rgba(245,158,11,0.08)"
                      : isHover ? "rgba(16,185,129,0.04)"
                      : "transparent";
          return (
            <div key={a.idx}
              data-row-idx={a.idx}
              onClick={() => p.onSelectAtom(a.idx)}
              onMouseEnter={() => p.onHoverAtom(a.idx)}
              onMouseLeave={() => p.onHoverAtom(null)}
              title={`Atom ${a.idx} · ${fullName} (Z=${a.atomic_number}, ${a.atomic_mass} g/mol) · ${a.hybridization || "—"} · ${a.degree} heavy bonds + ${a.n_hydrogens} H · ${a.free_valence} free slot${a.free_valence === 1 ? "" : "s"}${isIncomplete ? " · ⚠ incomplete (under-valent)" : ""}${isRecentlyBroken ? " · recently broken" : ""}`}
              style={{
                position: "relative",
                display: "flex", flexDirection: "column", gap: 2,
                padding: "4px 8px",
                borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.025))",
                borderLeft: `3px solid ${borderColor}`,
                background: rowBg,
                cursor: "pointer",
                fontFamily: "var(--lys-font-mono)",
                transition: "background 0.10s",
              }}>
              {/* Row 1 — index + element badge + chips */}
              <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{
                  fontSize: 9, color: "var(--lys-text-faint)",
                  minWidth: 16, textAlign: "right", fontWeight: 600,
                }}>{a.idx}</span>
                {/* Element badge — bigger, with charge superscript */}
                <span style={{
                  position: "relative",
                  width: 20, height: 20, borderRadius: "50%",
                  background: c, color: "white",
                  display: "grid", placeItems: "center",
                  fontSize: 10.5, fontWeight: 700, flexShrink: 0,
                  boxShadow: isSelected ? "0 0 0 2px rgba(245,158,11,0.35)" : "none",
                  fontFamily: "var(--lys-font-body)",
                }}>
                  {a.element}
                  {a.formal_charge !== 0 && (
                    <span style={{
                      position: "absolute", top: -3, right: -4,
                      fontSize: 8, fontWeight: 800,
                      background: "#dc2626", color: "white",
                      width: 12, height: 12, borderRadius: "50%",
                      display: "grid", placeItems: "center",
                      fontFamily: "var(--lys-font-mono)",
                      lineHeight: 1,
                    }}>{a.formal_charge > 0 ? "+" : "−"}</span>
                  )}
                </span>
                {/* Hybridization chip */}
                {a.hybridization && a.hybridization !== "unspecified" && (
                  <span style={{
                    fontSize: 8, padding: "1px 4px", borderRadius: 3,
                    background: "rgba(99,102,241,0.10)", color: "#6366f1",
                    fontWeight: 700, letterSpacing: "0.02em",
                  }}>{a.hybridization}</span>
                )}
                {/* Aromatic / ring */}
                {a.is_aromatic && (
                  <span style={{
                    fontSize: 8, padding: "1px 4px", borderRadius: 3,
                    background: "rgba(168,85,247,0.10)", color: "#a855f7",
                    fontWeight: 700,
                  }}>arom</span>
                )}
                {a.in_ring && !a.is_aromatic && (
                  <span style={{
                    fontSize: 8, padding: "1px 4px", borderRadius: 3,
                    background: "rgba(8,145,178,0.10)", color: "#0891b2",
                    fontWeight: 700,
                  }}>ring{a.ring_size}</span>
                )}
                {a.is_chiral && (
                  <span style={{
                    fontSize: 8, padding: "1px 4px", borderRadius: 3,
                    background: "rgba(234,88,12,0.10)", color: "#ea580c",
                    fontWeight: 700,
                  }}>{a.cip_code || "★"}</span>
                )}
                <span style={{ flex: 1 }} />
                {/* Per-row action buttons — visible on hover/select */}
                {(isHover || isSelected) && p.onSwapElement && (
                  <button type="button"
                    title="Swap element"
                    onClick={(e) => {
                      e.stopPropagation();
                      openRowAction(a.idx, "swap", e.currentTarget as HTMLElement);
                    }}
                    style={iconBtnStyle("#6366f1")}>⇆</button>
                )}
                {(isHover || isSelected) && p.onAddNeighbor && a.free_valence > 0 && (
                  <button type="button"
                    title={`Add neighbor (${a.free_valence} slot${a.free_valence === 1 ? "" : "s"} free)`}
                    onClick={(e) => {
                      e.stopPropagation();
                      openRowAction(a.idx, "neighbor", e.currentTarget as HTMLElement);
                    }}
                    style={iconBtnStyle("#10b981")}>+</button>
                )}
                {p.onDeleteAtom && (
                  <button type="button"
                    onClick={(e) => { e.stopPropagation(); p.onDeleteAtom!(a.idx); }}
                    title={`Delete atom ${a.idx}`}
                    style={iconBtnStyle("#dc2626", isHover || isSelected ? 1 : 0.4)}>×</button>
                )}
              </div>
              {/* Row 2 — bond profile + free valence */}
              <div style={{ display: "flex", alignItems: "center", gap: 6,
                fontSize: 8.5, color: "var(--lys-text-faint)",
                paddingLeft: 26 }}>
                <span title="Heavy-atom bond count">⌈{a.degree}⌋</span>
                {a.n_hydrogens > 0 && (
                  <span title={`${a.n_hydrogens} implicit hydrogen${a.n_hydrogens === 1 ? "" : "s"}`}
                    style={{ color: "#9ca3af" }}>H{a.n_hydrogens}</span>
                )}
                {a.bonds.length > 0 && (
                  <span title="Bond-order profile" style={{ display: "flex", gap: 2 }}>
                    {a.bonds.map((b, i) => (
                      <span key={i} style={{ color: "var(--lys-text-dim)" }}>
                        {BOND_GLYPH[b.order] || b.order}{b.count > 1 ? `×${b.count}` : ""}
                      </span>
                    ))}
                  </span>
                )}
                <span style={{ flex: 1 }} />
                {a.free_valence > 0 && (
                  <span title={`${a.free_valence} open bond slot${a.free_valence === 1 ? "" : "s"} (can attach more atoms)`}
                    style={{ color: "#10b981", fontWeight: 600 }}>
                    {a.free_valence}◦
                  </span>
                )}
              </div>
            </div>
          );
        })}
        {atoms.length > 0 && visibleAtoms.length === 0 && (
          <div style={{ padding: "12px 10px", textAlign: "center",
            fontSize: 9.5, color: "var(--lys-text-faint)",
            fontFamily: "var(--lys-font-mono)" }}>
            no {elementFilter} atoms · clear filter
          </div>
        )}
      </div>
      {/* BONDS section — every bond is a row, click × to break, click row
          to highlight in the SVG. Bonds are shared between two atoms; the
          row visualizes that as `atom_a — glyph — atom_b`. Same actions
          available to the agent through /molecule/edit op:break_bond. */}
      <BondsRail
        bonds={p.bonds || []}
        hoveredBondIdx={p.hoveredBondIdx ?? null}
        onHoverBond={p.onHoverBond}
        onBreakBond={p.onBreakBond}
        elementColor={ELEMENT_COLOR}
        atoms={atoms}
      />
      {/* Build Tools — fills the bottom space of the rail with concrete
          building blocks the user (and the agent) can attach to the
          currently-selected atom. Three tabs: Fragments, Rings, SMILES. */}
      <BuildTools
        apiBase={p.apiBase}
        smiles={p.smiles}
        selected={p.selected}
        atoms={atoms}
        onAttachFragment={p.onAttachFragment}
        onAttachFG={p.onAttachFG}
        onReplaceSmiles={p.onReplaceSmiles}
      />
      {paletteOpen && palettePos && palette.length > 0 && createPortal(
        <div data-element-pop style={{
          position: "fixed", left: palettePos.left, top: palettePos.top,
          width: 320, maxHeight: "60vh",
          background: "var(--lys-bg-2, #ffffff)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 10,
          boxShadow: "0 14px 40px rgba(15,23,42,0.18), 0 2px 8px rgba(15,23,42,0.10)",
          zIndex: 5000, display: "flex", flexDirection: "column",
          overflow: "hidden", fontFamily: "var(--lys-font-body)",
        }}>
          <div style={{ padding: "8px 10px",
            borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
            display: "flex", alignItems: "center", gap: 6,
            background: "var(--lys-bg, #fafafa)" }}>
            <span style={{ fontSize: 11, fontWeight: 700, color: "var(--lys-text)" }}>
              ⚛ Add atom
            </span>
            <span style={{ fontSize: 9.5, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)" }}>
              · {palette.length} elements · attaches to atom 0 with single bond
            </span>
            <span style={{ flex: 1 }} />
            <button type="button" onClick={() => setPaletteOpen(false)}
              style={{ border: 0, background: "transparent", cursor: "pointer",
                padding: 4, color: "var(--lys-text-faint)" }}>✕</button>
          </div>
          <div style={{ padding: 8, overflow: "auto",
            display: "grid", gridTemplateColumns: "repeat(8, 1fr)", gap: 4 }}>
            {palette.map((el) => {
              const groupColor: Record<string, string> = {
                "halogen": "#16a34a",
                "alkali": "#a855f7",
                "alkaline-earth": "#c084fc",
                "transition": "#0891b2",
                "post-transition": "#06b6d4",
                "metalloid": "#ca8a04",
                "nonmetal": "#374151",
              };
              const c = groupColor[el.group] ?? "#6b7280";
              return (
                <button key={el.sym} type="button"
                  onClick={() => { p.onAddAtom?.(el.sym); setPaletteOpen(false); }}
                  title={`${el.name} · Z=${el.Z} · valence ${el.valences.join("/")}`}
                  style={{
                    aspectRatio: "1 / 1",
                    border: `1px solid ${c}40`,
                    background: `${c}10`,
                    color: c,
                    borderRadius: 6,
                    fontFamily: "var(--lys-font-mono)",
                    fontWeight: 700, fontSize: 11,
                    cursor: "pointer",
                    display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center",
                    gap: 1, padding: 0,
                    transition: "background 0.12s, transform 0.12s",
                  }}
                  onMouseEnter={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = `${c}25`;
                    (e.currentTarget as HTMLButtonElement).style.transform = "scale(1.06)";
                  }}
                  onMouseLeave={(e) => {
                    (e.currentTarget as HTMLButtonElement).style.background = `${c}10`;
                    (e.currentTarget as HTMLButtonElement).style.transform = "scale(1.0)";
                  }}>
                  <span style={{ fontSize: 8, opacity: 0.7, lineHeight: 1 }}>{el.Z}</span>
                  <span style={{ lineHeight: 1 }}>{el.sym}</span>
                  <span style={{ fontSize: 7, opacity: 0.6, lineHeight: 1,
                    fontFamily: "var(--lys-font-body)", fontWeight: 500 }}>
                    {el.valences[0]}{el.valences.length > 1 ? "+" : ""}
                  </span>
                </button>
              );
            })}
          </div>
        </div>, document.body)}
      {/* Row-action popover — swap element OR add neighbor.
          Reuses the periodic-table palette but scoped to a target atom. */}
      {actionRowIdx != null && actionMode && actionPos && palette.length > 0 && createPortal(
        <div data-row-action-pop style={{
          position: "fixed", left: actionPos.left, top: actionPos.top,
          width: 320, maxHeight: "60vh",
          background: "var(--lys-bg-2, #ffffff)",
          border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
          borderRadius: 10,
          boxShadow: "0 14px 40px rgba(15,23,42,0.18), 0 2px 8px rgba(15,23,42,0.10)",
          zIndex: 5500, display: "flex", flexDirection: "column",
          overflow: "hidden", fontFamily: "var(--lys-font-body)",
        }}>
          <div style={{ padding: "8px 10px",
            borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
            display: "flex", flexDirection: "column", gap: 4,
            background: "var(--lys-bg, #fafafa)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--lys-text)" }}>
                {actionMode === "swap" ? "⇆ Swap element" : "+ Add neighbor"}
                <span style={{ fontFamily: "var(--lys-font-mono)", fontWeight: 500,
                  fontSize: 10, color: "var(--lys-text-faint)", marginLeft: 4 }}>
                  · atom {actionRowIdx}
                </span>
              </span>
              <span style={{ flex: 1 }} />
              <button type="button" onClick={() => {
                  setActionRowIdx(null); setActionMode(null); setActionPos(null);
                }}
                style={{ border: 0, background: "transparent", cursor: "pointer",
                  padding: 4, color: "var(--lys-text-faint)" }}>✕</button>
            </div>
            <div style={{ fontSize: 9.5, color: "var(--lys-text-faint)", lineHeight: 1.35 }}>
              {actionMode === "swap"
                ? "Pick a new element. The atom keeps its bonds; valence rules apply server-side."
                : "Pick an element to attach to atom " + actionRowIdx + ". Choose bond order below."}
            </div>
            {actionMode === "neighbor" && (
              <div style={{ display: "flex", gap: 4, marginTop: 2 }}>
                {(["single", "double", "triple"] as const).map((bo) => (
                  <button key={bo} type="button"
                    onClick={() => setNeighborBondOrder(bo)}
                    style={{
                      padding: "2px 8px", borderRadius: 4,
                      fontSize: 10, fontFamily: "var(--lys-font-mono)",
                      fontWeight: neighborBondOrder === bo ? 700 : 500,
                      border: `1px solid ${neighborBondOrder === bo ? "#10b981" : "rgba(0,0,0,0.10)"}`,
                      background: neighborBondOrder === bo ? "rgba(16,185,129,0.10)" : "var(--lys-bg-2, #ffffff)",
                      color: neighborBondOrder === bo ? "#10b981" : "var(--lys-text-dim)",
                      cursor: "pointer",
                    }}>{BOND_GLYPH[bo]} {bo}</button>
                ))}
              </div>
            )}
          </div>
          <div style={{ padding: 8, overflow: "auto",
            display: "grid", gridTemplateColumns: "repeat(8, 1fr)", gap: 4 }}>
            {palette.map((el) => {
              const groupColor: Record<string, string> = {
                "halogen": "#16a34a",
                "alkali": "#a855f7",
                "alkaline-earth": "#c084fc",
                "transition": "#0891b2",
                "post-transition": "#06b6d4",
                "metalloid": "#ca8a04",
                "nonmetal": "#374151",
              };
              const c = groupColor[el.group] ?? "#6b7280";
              return (
                <button key={el.sym} type="button"
                  onClick={() => {
                    if (actionMode === "swap") {
                      p.onSwapElement?.(actionRowIdx, el.sym);
                    } else {
                      p.onAddNeighbor?.(actionRowIdx, el.sym, neighborBondOrder);
                    }
                    setActionRowIdx(null); setActionMode(null); setActionPos(null);
                  }}
                  title={`${el.name} · Z=${el.Z} · valence ${el.valences.join("/")}`}
                  style={{
                    aspectRatio: "1 / 1",
                    border: `1px solid ${c}40`,
                    background: `${c}10`,
                    color: c,
                    borderRadius: 6,
                    fontFamily: "var(--lys-font-mono)",
                    fontWeight: 700, fontSize: 11,
                    cursor: "pointer",
                    display: "flex", flexDirection: "column",
                    alignItems: "center", justifyContent: "center",
                    gap: 1, padding: 0,
                  }}>
                  <span style={{ fontSize: 8, opacity: 0.7, lineHeight: 1 }}>{el.Z}</span>
                  <span style={{ lineHeight: 1 }}>{el.sym}</span>
                  <span style={{ fontSize: 7, opacity: 0.6, lineHeight: 1,
                    fontFamily: "var(--lys-font-body)", fontWeight: 500 }}>
                    {el.valences[0]}{el.valences.length > 1 ? "+" : ""}
                  </span>
                </button>
              );
            })}
          </div>
        </div>, document.body)}
    </div>
  );
}

/* Helpers for AtomsRail */
function RailStat({ label, value, color, tip }: {
  label: string; value: string; color: string; tip?: string;
}) {
  return (
    <span title={tip} style={{
      display: "inline-flex", alignItems: "center", gap: 3,
      padding: "1px 5px", borderRadius: 3,
      background: `${color}10`,
      fontSize: 8.5,
    }}>
      <span style={{ color, fontWeight: 700 }}>{value}</span>
      <span style={{ color: "var(--lys-text-faint)" }}>{label}</span>
    </span>
  );
}

function FilterChip({ label, active, onClick, color, tip }: {
  label: string; active: boolean; onClick: () => void; color: string; tip?: string;
}) {
  return (
    <button type="button" onClick={onClick} title={tip}
      style={{
        fontSize: 9, padding: "2px 7px", borderRadius: 999,
        border: `1px solid ${active ? color : "rgba(0,0,0,0.10)"}`,
        background: active ? `${color}15` : "transparent",
        color: active ? color : "var(--lys-text-dim)",
        cursor: "pointer",
        fontFamily: "var(--lys-font-mono)",
        fontWeight: active ? 700 : 500,
      }}>{label}</button>
  );
}

function iconBtnStyle(color: string, opacity: number = 1): React.CSSProperties {
  return {
    border: `1px solid ${color}40`,
    background: "transparent",
    cursor: "pointer", padding: "0 5px",
    color, opacity,
    fontSize: 11, lineHeight: 1.4, fontWeight: 700,
    borderRadius: 3, minWidth: 18,
    fontFamily: "var(--lys-font-mono)",
    transition: "background 0.10s, opacity 0.10s",
  };
}

/* ─────────────────────────────────────────────────────────────────────
   BondsRail — collapsible list of every bond in the molecule. Lives
   below the AtomsRail in the right panel.

   Each row visualizes the shared-between-atoms nature of bonds:
   `[idx] [atom_a element]——atom_b · glyph · ring? aromatic? × break`

   Click × to break the bond (same /molecule/edit op:break_bond used by
   the SVG bond-click). Hover row to glow the bond on the SVG (the parent
   wires hoveredBondIdx ↔ SVG via useEffect).

   The row click is the click-based path the user prefers: even for
   atom selection, click row → highlights both endpoints visually.
   ───────────────────────────────────────────────────────────────────── */
interface BondsRailProps {
  bonds: BondMeta[];
  hoveredBondIdx: number | null;
  onHoverBond?: (idx: number | null) => void;
  onBreakBond?: (idx: number) => void;
  elementColor: Record<string, string>;
  atoms: AtomRow[];
}

const BOND_GLYPH_RAIL: Record<string, string> = {
  single:   "—",
  double:   "=",
  triple:   "≡",
  aromatic: "⌬",
};

function BondsRail(p: BondsRailProps) {
  const [collapsed, setCollapsed] = useState(false);
  const ringCount = p.bonds.filter((b) => b.in_ring).length;
  const aromCount = p.bonds.filter((b) => b.is_aromatic).length;
  return (
    <div style={{
      flex: "0 0 auto",
      maxHeight: 240,
      display: "flex", flexDirection: "column",
      borderTop: "1px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
      background: "var(--lys-bg, #fafafa)",
      overflow: "hidden",
    }}>
      {/* Header — collapsible, shows bond count + ring/aromatic counts */}
      <div
        title="Bonds in the current candidate · click any row to highlight in 2D · × to break · click bond in SVG to break too"
        onClick={() => setCollapsed((c) => !c)}
        style={{
          padding: "5px 8px",
          fontSize: 9, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          letterSpacing: "0.06em", textTransform: "uppercase",
          borderBottom: collapsed ? "none" : "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
          display: "flex", alignItems: "center", gap: 5,
          cursor: "pointer",
          userSelect: "none",
        }}>
        <span style={{ fontSize: 9, opacity: 0.6 }}>{collapsed ? "▶" : "▼"}</span>
        <span style={{ fontWeight: 700 }}>bonds</span>
        <span style={{ color: "#0891b2", fontWeight: 700 }}>{p.bonds.length}</span>
        <span style={{ flex: 1 }} />
        {ringCount > 0 && (
          <span style={{ padding: "0 5px", borderRadius: 3,
            background: "rgba(8,145,178,0.10)", color: "#0891b2", fontWeight: 700 }}>
            {ringCount} ring
          </span>
        )}
        {aromCount > 0 && (
          <span style={{ padding: "0 5px", borderRadius: 3,
            background: "rgba(168,85,247,0.10)", color: "#a855f7", fontWeight: 700 }}>
            {aromCount} arom
          </span>
        )}
      </div>
      {!collapsed && (
        <div style={{ flex: 1, overflow: "auto" }}>
          {p.bonds.length === 0 ? (
            <div style={{ padding: "10px 8px", textAlign: "center",
              fontSize: 9.5, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)" }}>
              no bonds
            </div>
          ) : p.bonds.map((b) => {
            const aEl = p.atoms.find((a) => a.idx === b.atom_a)?.element ?? "?";
            const bEl = p.atoms.find((a) => a.idx === b.atom_b)?.element ?? "?";
            const aColor = p.elementColor[aEl] ?? "#374151";
            const bColor = p.elementColor[bEl] ?? "#374151";
            const isHover = p.hoveredBondIdx === b.bond_idx;
            const orderColor = b.is_aromatic ? "#a855f7"
                             : b.order === "double" ? "#dc2626"
                             : b.order === "triple" ? "#ea580c"
                             : "#374151";
            return (
              <div key={b.bond_idx}
                onMouseEnter={() => p.onHoverBond?.(b.bond_idx)}
                onMouseLeave={() => p.onHoverBond?.(null)}
                title={`Bond ${b.bond_idx} · atom ${b.atom_a}(${aEl}) ${BOND_GLYPH_RAIL[b.order] ?? b.order} atom ${b.atom_b}(${bEl})${b.in_ring ? " · in ring" : ""}${b.is_aromatic ? " · aromatic" : ""}`}
                style={{
                  display: "flex", alignItems: "center", gap: 4,
                  padding: "3px 8px",
                  fontSize: 10, fontFamily: "var(--lys-font-mono)",
                  borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.025))",
                  background: isHover ? "rgba(220,38,38,0.06)" : "transparent",
                  cursor: "pointer",
                  transition: "background 0.10s",
                }}>
                <span style={{ fontSize: 8, color: "var(--lys-text-faint)",
                  minWidth: 14, textAlign: "right", fontWeight: 600 }}>
                  {b.bond_idx}
                </span>
                {/* atom_a element bubble */}
                <span style={{
                  width: 14, height: 14, borderRadius: "50%",
                  background: aColor, color: "white",
                  display: "grid", placeItems: "center",
                  fontSize: 8, fontWeight: 700, flexShrink: 0,
                }}>{aEl}</span>
                <span style={{ fontSize: 8, color: "var(--lys-text-faint)" }}>
                  {b.atom_a}
                </span>
                {/* bond glyph */}
                <span style={{
                  fontSize: 13, fontWeight: 800,
                  color: orderColor, lineHeight: 1,
                  padding: "0 2px",
                }}>{BOND_GLYPH_RAIL[b.order] ?? b.order}</span>
                {/* atom_b element bubble */}
                <span style={{
                  width: 14, height: 14, borderRadius: "50%",
                  background: bColor, color: "white",
                  display: "grid", placeItems: "center",
                  fontSize: 8, fontWeight: 700, flexShrink: 0,
                }}>{bEl}</span>
                <span style={{ fontSize: 8, color: "var(--lys-text-faint)" }}>
                  {b.atom_b}
                </span>
                {b.in_ring && (
                  <span style={{ fontSize: 7, padding: "0 3px", borderRadius: 2,
                    background: "rgba(8,145,178,0.10)", color: "#0891b2",
                    fontWeight: 700 }}>r</span>
                )}
                <span style={{ flex: 1 }} />
                {/* break-bond × — disable for aromatic ring bonds (would shatter the ring) */}
                <button type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    if (b.is_aromatic && b.in_ring) return;
                    p.onBreakBond?.(b.bond_idx);
                  }}
                  disabled={b.is_aromatic && b.in_ring}
                  title={b.is_aromatic && b.in_ring
                    ? `Cannot break aromatic ring bond — would shatter the ring`
                    : `Break bond ${b.bond_idx} (atoms ${b.atom_a}↔${b.atom_b})`}
                  style={{
                    border: 0, background: "transparent",
                    cursor: (b.is_aromatic && b.in_ring) ? "not-allowed" : "pointer",
                    padding: "0 5px",
                    color: "#dc2626",
                    opacity: (b.is_aromatic && b.in_ring) ? 0.25 : (isHover ? 1 : 0.55),
                    fontSize: 12, lineHeight: 1, fontWeight: 700,
                    transition: "opacity 0.10s",
                  }}>×</button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────
   BuildTools — bottom panel of the AtomsRail. Three tabs:

   1. Fragments  · clickable functional-group chips (–OH, –NH₂, –COOH,
                   –CN, –CF₃, –SO₂NH₂, –C(=O)O–CH₃ etc.). Attaches to
                   the selected atom via /molecule/edit op:
                   add_functional_group_at.
   2. Rings      · clickable ring/heterocycle chips (benzene, pyridine,
                   furan, imidazole, thiazole, pyrazine, cyclohexane,
                   cyclopropane). Uses /molecule/edit op:attach_fragment.
   3. SMILES     · paste/type a full SMILES, validate via
                   /molecule/replace, and replace the current candidate.
                   This is the agent's fast-path: it can write a whole
                   structure in one shot rather than atom-by-atom.

   The panel is the user-and-agent-shared toolbox (workbench-as-
   simulation). Every action goes through the same backend endpoint
   the agent tool registry calls.
   ───────────────────────────────────────────────────────────────────── */
interface BuildToolsProps {
  apiBase: string;
  smiles: string | null;
  selected: Set<number>;
  atoms: AtomRow[];
  onAttachFragment?: (anchorIdx: number, fragmentSmiles: string, label: string, bondOrder?: "single" | "double" | "aromatic") => void;
  onAttachFG?: (anchorIdx: number, fgName: string, label: string) => void;
  onReplaceSmiles?: (newSmiles: string, label: string) => void;
  onShowViolation?: (v: Violation) => void;
}

const FRAGMENT_PALETTE: { name: string; label: string; tip: string; color: string }[] = [
  { name: "hydroxyl",   label: "–OH",     tip: "Hydroxyl · adds polarity, H-bond donor",                 color: "#dc2626" },
  { name: "amine",      label: "–NH₂",    tip: "Primary amine · base, H-bond donor",                     color: "#2563eb" },
  { name: "methyl",     label: "–CH₃",    tip: "Methyl · adds lipophilicity",                            color: "#374151" },
  { name: "fluorine",   label: "–F",      tip: "Fluorine · metabolic blocker",                           color: "#16a34a" },
  { name: "chlorine",   label: "–Cl",     tip: "Chlorine · steric + electronic modulation",              color: "#16a34a" },
  { name: "bromine",    label: "–Br",     tip: "Bromine · halogen bond, lipophilic",                     color: "#9a3412" },
  { name: "iodine",     label: "–I",      tip: "Iodine · halogen bond, large halogen",                   color: "#7c3aed" },
  { name: "thiol",      label: "–SH",     tip: "Thiol · soft nucleophile",                               color: "#ca8a04" },
  { name: "carbonyl",   label: "–C(=O)–", tip: "Carbonyl · ketone-like, H-bond acceptor",                color: "#374151" },
  { name: "carboxyl",   label: "–COOH",   tip: "Carboxylic acid · ionizable",                            color: "#dc2626" },
  { name: "amide",      label: "–CONH₂",  tip: "Amide · planar, H-bond donor+acceptor",                  color: "#2563eb" },
  { name: "ester",      label: "–OC(=O)–",tip: "Ester · prodrug handle",                                 color: "#374151" },
  { name: "nitro",      label: "–NO₂",    tip: "Nitro · strong EWG, sometimes prodrug",                  color: "#dc2626" },
  { name: "cyano",      label: "–CN",     tip: "Cyano · linear, isostere of carboxylic acid",            color: "#374151" },
  { name: "trifluoromethyl", label: "–CF₃", tip: "Trifluoromethyl · metabolic shield",                   color: "#16a34a" },
  { name: "sulfonyl",   label: "–SO₂–",   tip: "Sulfonyl · strong EWG, polar",                           color: "#ca8a04" },
  { name: "sulfonamide",label: "–SO₂NH₂", tip: "Sulfonamide · classic antibiotic warhead",               color: "#ca8a04" },
  { name: "phosphate",  label: "–OPO(OH)₂", tip: "Phosphate · prodrug solubilizer / mimetic",            color: "#ea580c" },
  { name: "methoxy",    label: "–OCH₃",   tip: "Methoxy · weak EDG",                                     color: "#374151" },
  { name: "ethyl",      label: "–CH₂CH₃", tip: "Ethyl · slightly more lipophilic than methyl",           color: "#374151" },
  { name: "vinyl",      label: "–CH=CH₂", tip: "Vinyl · unsaturation, Michael acceptor when activated",  color: "#374151" },
  { name: "ethynyl",    label: "–C≡CH",   tip: "Ethynyl · linear, click-chemistry handle",               color: "#374151" },
  { name: "azido",      label: "–N₃",     tip: "Azide · click-chemistry handle, photoaffinity",          color: "#2563eb" },
  { name: "tert-butyl", label: "–C(CH₃)₃",tip: "tert-Butyl · steric block",                              color: "#374151" },
  { name: "phenyl",     label: "–C₆H₅",   tip: "Phenyl · π-stacking handle",                             color: "#a855f7" },
];

const RING_PALETTE: { name: string; smiles: string; label: string; tip: string; color: string; aromatic: boolean }[] = [
  { name: "benzene",      smiles: "c1ccccc1",      label: "⌬ Benzene",       tip: "Aromatic 6-ring · π-stacking, lipophilic",            color: "#a855f7", aromatic: true  },
  { name: "pyridine",     smiles: "c1ccncc1",      label: "⌬ Pyridine",      tip: "Aromatic N-6-ring · weakly basic",                    color: "#2563eb", aromatic: true  },
  { name: "pyrimidine",   smiles: "c1cncnc1",      label: "⌬ Pyrimidine",    tip: "Aromatic 1,3-diaza · base in nucleotides",            color: "#2563eb", aromatic: true  },
  { name: "pyrazine",     smiles: "c1cnccn1",      label: "⌬ Pyrazine",      tip: "Aromatic 1,4-diaza · pyrazinamide core",              color: "#2563eb", aromatic: true  },
  { name: "imidazole",    smiles: "c1cnc[nH]1",    label: "⌬ Imidazole",     tip: "Aromatic 1,3-diaza-5-ring · histidine, metronidazole",color: "#2563eb", aromatic: true  },
  { name: "thiazole",     smiles: "c1cscn1",       label: "⌬ Thiazole",      tip: "Aromatic S/N-5-ring · cefiderocol/sulfa-class",       color: "#ca8a04", aromatic: true  },
  { name: "oxazole",      smiles: "c1ocnc1",       label: "⌬ Oxazole",       tip: "Aromatic O/N-5-ring · linezolid core",                color: "#dc2626", aromatic: true  },
  { name: "furan",        smiles: "c1ccoc1",       label: "⌬ Furan",         tip: "Aromatic O-5-ring · oxidative liability",             color: "#dc2626", aromatic: true  },
  { name: "thiophene",    smiles: "c1ccsc1",       label: "⌬ Thiophene",     tip: "Aromatic S-5-ring · benzene bioisostere",             color: "#ca8a04", aromatic: true  },
  { name: "pyrrole",      smiles: "c1cc[nH]c1",    label: "⌬ Pyrrole",       tip: "Aromatic N-5-ring · porphyrin building block",        color: "#2563eb", aromatic: true  },
  { name: "indole",       smiles: "c1ccc2[nH]ccc2c1", label: "⌬ Indole",     tip: "Bicyclic aromatic · tryptophan, tryptamine",          color: "#a855f7", aromatic: true  },
  { name: "benzimidazole",smiles: "c1ccc2nc[nH]c2c1", label: "⌬ Benzimidazole", tip: "Bicyclic aromatic · proton-pump inhibitors",     color: "#2563eb", aromatic: true  },
  { name: "quinoline",    smiles: "c1ccc2ncccc2c1", label: "⌬ Quinoline",   tip: "Bicyclic aromatic · fluoroquinolone, antimalarials",   color: "#2563eb", aromatic: true  },
  { name: "cyclopropane", smiles: "C1CC1",          label: "△ Cyclopropane",   tip: "Strained 3-ring · bioisostere, conformational lock",  color: "#374151", aromatic: false },
  { name: "cyclobutane",  smiles: "C1CCC1",         label: "□ Cyclobutane",    tip: "4-ring · puckered, modest strain",                    color: "#374151", aromatic: false },
  { name: "cyclopentane", smiles: "C1CCCC1",        label: "⬠ Cyclopentane",   tip: "5-ring · ribose-like",                                color: "#374151", aromatic: false },
  { name: "cyclohexane",  smiles: "C1CCCCC1",       label: "⬡ Cyclohexane",    tip: "6-ring · chair conformation",                         color: "#374151", aromatic: false },
  { name: "piperidine",   smiles: "C1CCNCC1",       label: "⬡ Piperidine",     tip: "Saturated N-6-ring · basic amine handle",             color: "#2563eb", aromatic: false },
  { name: "piperazine",   smiles: "C1CNCCN1",       label: "⬡ Piperazine",     tip: "Saturated 1,4-diaza-6 · fluoroquinolone tail",        color: "#2563eb", aromatic: false },
  { name: "morpholine",   smiles: "C1COCCN1",       label: "⬡ Morpholine",     tip: "Saturated O/N-6-ring · solubility booster",           color: "#dc2626", aromatic: false },
  { name: "tetrahydrofuran", smiles: "C1CCOC1",     label: "⬠ THF",            tip: "Saturated O-5-ring · sugar-like",                     color: "#dc2626", aromatic: false },
  { name: "pyrrolidine",  smiles: "C1CCNC1",        label: "⬠ Pyrrolidine",    tip: "Saturated N-5-ring · proline core",                   color: "#2563eb", aromatic: false },
];

function BuildTools(p: BuildToolsProps) {
  const [tab, setTab] = useState<"fragments" | "rings" | "smiles">("fragments");
  const [smilesInput, setSmilesInput] = useState("");
  const [smilesErr, setSmilesErr] = useState("");

  const selectedArr = Array.from(p.selected);
  const anchorIdx = selectedArr.length === 1 ? selectedArr[0] : null;
  const anchorAtom = anchorIdx != null ? p.atoms.find((a) => a.idx === anchorIdx) : null;
  const canAttach = anchorIdx != null && anchorAtom != null && anchorAtom.free_valence > 0;

  // Pre-filter palettes by chemistry rules — fetch /chem/valid-actions
  // for the current anchor, hide invalid options BEFORE rendering them.
  const [validFGs, setValidFGs] = useState<Set<string> | null>(null);
  const [validRings, setValidRings] = useState<boolean>(true);
  useEffect(() => {
    if (anchorIdx == null || !p.smiles) { setValidFGs(null); setValidRings(true); return; }
    let cancelled = false;
    (async () => {
      try {
        const b64 = smilesToB64(p.smiles!);
        const r = await fetch(`${p.apiBase}/workbench/chem/valid-actions/${b64}/${anchorIdx}`);
        if (!r.ok) return;
        const d = await r.json();
        if (cancelled) return;
        setValidFGs(new Set(d.valid_functional_groups || []));
        setValidRings(!!d.valid_rings);
      } catch {/*noop*/}
    })();
    return () => { cancelled = true; };
  }, [anchorIdx, p.smiles, p.apiBase]);

  // Visible palettes — pre-filtered by valid-actions response.
  const visibleFGs = canAttach && validFGs != null
    ? FRAGMENT_PALETTE.filter((fg) => validFGs.has(fg.name))
    : (canAttach ? FRAGMENT_PALETTE : []);
  const hiddenFGCount = (canAttach && validFGs != null)
    ? FRAGMENT_PALETTE.length - visibleFGs.length : 0;
  const visibleRings = canAttach && validRings ? RING_PALETTE : [];

  const tabBtnStyle = (active: boolean): React.CSSProperties => ({
    flex: 1,
    padding: "5px 6px",
    fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
    fontWeight: active ? 700 : 500,
    border: 0,
    borderBottom: `2px solid ${active ? "#10b981" : "transparent"}`,
    background: active ? "rgba(16,185,129,0.06)" : "transparent",
    color: active ? "#10b981" : "var(--lys-text-dim)",
    cursor: "pointer",
    letterSpacing: "0.04em",
    textTransform: "uppercase",
    transition: "all 0.10s",
  });

  return (
    <div style={{
      flex: "1 1 0", minHeight: 100,
      display: "flex", flexDirection: "column",
      borderTop: "2px solid var(--lys-border-faint, rgba(0,0,0,0.06))",
      background: "var(--lys-bg-2, #ffffff)",
      overflow: "hidden",
    }}>
      {/* Sticky header — title + selection-aware status line */}
      <div
        title="Build tools — compose with chemistry blocks. Fragments + rings attach to the selected atom (only chemistry-valid options shown). SMILES replaces the entire structure."
        style={{
          padding: "5px 8px",
          fontSize: 9, fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))",
          display: "flex", alignItems: "center", gap: 5,
        }}>
        <span style={{ fontWeight: 700, letterSpacing: "0.06em", textTransform: "uppercase" }}>
          build
        </span>
        <span style={{ flex: 1 }} />
        {anchorIdx != null && anchorAtom ? (
          <span style={{
            padding: "1px 6px", borderRadius: 3,
            background: canAttach ? "rgba(16,185,129,0.10)" : "rgba(220,38,38,0.10)",
            color: canAttach ? "#059669" : "#dc2626",
            fontWeight: 700,
          }}>
            anchor: atom {anchorIdx} ({anchorAtom.element}){canAttach ? ` · ${anchorAtom.free_valence}◦` : " · no slots"}
          </span>
        ) : selectedArr.length > 1 ? (
          <span style={{
            padding: "1px 6px", borderRadius: 3,
            background: "rgba(220,38,38,0.10)", color: "#dc2626", fontWeight: 700,
          }}>{selectedArr.length} selected · pick 1</span>
        ) : (
          <span style={{
            padding: "1px 6px", borderRadius: 3,
            background: "rgba(0,0,0,0.04)", color: "var(--lys-text-faint)",
          }}>select 1 atom →</span>
        )}
      </div>
      {/* Tab switcher */}
      <div style={{ display: "flex", borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.05))" }}>
        <button type="button" onClick={() => setTab("fragments")} style={tabBtnStyle(tab === "fragments")}>
          Fragments
        </button>
        <button type="button" onClick={() => setTab("rings")} style={tabBtnStyle(tab === "rings")}>
          Rings
        </button>
        <button type="button" onClick={() => setTab("smiles")} style={tabBtnStyle(tab === "smiles")}>
          SMILES
        </button>
      </div>
      {/* Tab content */}
      <div style={{ flex: 1, overflow: "auto", padding: 6 }}>
        {tab === "fragments" && (
          <div>
            {!canAttach && (
              <div style={{
                padding: "8px 6px", textAlign: "center",
                fontSize: 9.5, color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-body)", lineHeight: 1.4,
              }}>
                {anchorIdx == null
                  ? "Pick exactly one atom in the structure above to see only the fragments you can legally attach to it."
                  : `Atom ${anchorIdx} has no free bond slots. Break a bond first.`}
              </div>
            )}
            {canAttach && (
              <>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                  {visibleFGs.map((fg) => (
                    <button key={fg.name} type="button"
                      onClick={() => p.onAttachFG?.(anchorIdx!, fg.name, fg.label)}
                      title={fg.tip}
                      style={{
                        fontSize: 10, padding: "3px 7px", borderRadius: 999,
                        border: `1px solid ${fg.color}50`,
                        background: `${fg.color}10`,
                        color: fg.color,
                        fontFamily: "var(--lys-font-mono)",
                        fontWeight: 600,
                        cursor: "pointer",
                        transition: "background 0.10s",
                      }}
                      onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.background = `${fg.color}22`; }}
                      onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.background = `${fg.color}10`; }}
                    >{fg.label}</button>
                  ))}
                </div>
                {hiddenFGCount > 0 && (
                  <div style={{
                    marginTop: 4, padding: "3px 6px",
                    fontSize: 8.5, color: "var(--lys-text-faint)",
                    fontFamily: "var(--lys-font-mono)",
                    background: "rgba(0,0,0,0.025)",
                    borderRadius: 3, lineHeight: 1.4,
                  }}>
                    {hiddenFGCount} more hidden — needs ≥2 free bond slots
                  </div>
                )}
              </>
            )}
          </div>
        )}
        {tab === "rings" && (
          <div>
            {!canAttach && (
              <div style={{
                padding: "8px 6px", textAlign: "center",
                fontSize: 9.5, color: "var(--lys-text-faint)",
                fontFamily: "var(--lys-font-body)", lineHeight: 1.4,
              }}>
                {anchorIdx == null
                  ? "Pick exactly one atom in the structure above to see only the rings you can legally attach to it."
                  : `Atom ${anchorIdx} has no free bond slots. Break a bond first.`}
              </div>
            )}
            {canAttach && (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 4 }}>
            {visibleRings.map((r) => (
              <button key={r.name} type="button"
                onClick={() => {
                  if (anchorIdx == null || !canAttach) return;
                  p.onAttachFragment?.(anchorIdx, r.smiles, r.label,
                    r.aromatic ? "single" : "single");
                }}
                title={r.tip}
                disabled={!canAttach}
                style={{
                  fontSize: 10, padding: "4px 8px", borderRadius: 5,
                  border: `1px solid ${canAttach ? `${r.color}50` : "rgba(0,0,0,0.08)"}`,
                  background: canAttach ? `${r.color}10` : "transparent",
                  color: canAttach ? r.color : "var(--lys-text-faint)",
                  fontFamily: "var(--lys-font-body)",
                  fontWeight: 600,
                  cursor: canAttach ? "pointer" : "not-allowed",
                  opacity: canAttach ? 1 : 0.45,
                  textAlign: "left",
                  transition: "background 0.10s, transform 0.10s",
                }}
                onMouseEnter={(e) => {
                  if (canAttach) {
                    (e.currentTarget as HTMLButtonElement).style.background = `${r.color}22`;
                    (e.currentTarget as HTMLButtonElement).style.transform = "translateY(-1px)";
                  }
                }}
                onMouseLeave={(e) => {
                  if (canAttach) {
                    (e.currentTarget as HTMLButtonElement).style.background = `${r.color}10`;
                    (e.currentTarget as HTMLButtonElement).style.transform = "translateY(0)";
                  }
                }}
              >{r.label}</button>
            ))}
            </div>
            )}
          </div>
        )}
        {tab === "smiles" && (
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            <div style={{ fontSize: 9, color: "var(--lys-text-faint)", lineHeight: 1.4,
              fontFamily: "var(--lys-font-body)" }}>
              Paste a complete SMILES to replace the candidate. The agent
              uses this fast-path to write structures in one shot.
            </div>
            <textarea
              value={smilesInput}
              onChange={(e) => { setSmilesInput(e.target.value); setSmilesErr(""); }}
              placeholder="e.g. CC1(C)S[C@@H]2[C@H](NC(=O)Cc3ccccc3)C(=O)N2[C@H]1C(=O)O"
              rows={3}
              style={{
                fontSize: 10, fontFamily: "var(--lys-font-mono)",
                padding: 5, borderRadius: 4,
                border: smilesErr
                  ? "1px solid #dc2626"
                  : "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
                background: "var(--lys-bg-2, #ffffff)",
                color: "var(--lys-text)", outline: "none",
                resize: "vertical",
                minHeight: 50,
              }} />
            {smilesErr && (
              <div style={{ fontSize: 9, color: "#dc2626",
                fontFamily: "var(--lys-font-mono)" }}>{smilesErr}</div>
            )}
            <div style={{ display: "flex", gap: 4 }}>
              <button type="button"
                onClick={async () => {
                  if (!smilesInput.trim()) return;
                  // The parent owns /molecule/replace; we ask it to apply.
                  if (p.onReplaceSmiles) {
                    p.onReplaceSmiles(smilesInput.trim(), `replace SMILES (${smilesInput.length} chars)`);
                    setSmilesInput("");
                  }
                }}
                disabled={!smilesInput.trim()}
                style={{
                  flex: 1, padding: "4px 9px", borderRadius: 4,
                  fontSize: 10, fontFamily: "var(--lys-font-mono)",
                  background: smilesInput.trim() ? "#10b981" : "rgba(16,185,129,0.30)",
                  color: "white", border: 0,
                  cursor: smilesInput.trim() ? "pointer" : "not-allowed",
                  fontWeight: 700,
                }}>apply</button>
              <button type="button"
                onClick={() => { setSmilesInput(p.smiles ?? ""); setSmilesErr(""); }}
                disabled={!p.smiles}
                style={{
                  padding: "4px 9px", borderRadius: 4,
                  fontSize: 10, fontFamily: "var(--lys-font-mono)",
                  background: "var(--lys-bg-2, #ffffff)",
                  color: "var(--lys-text-dim)",
                  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.10))",
                  cursor: p.smiles ? "pointer" : "not-allowed",
                  opacity: p.smiles ? 1 : 0.5,
                }}>copy current</button>
            </div>
            {p.smiles && (
              <div style={{
                fontSize: 8.5, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)", padding: "3px 5px",
                borderRadius: 3, background: "rgba(0,0,0,0.025)",
                wordBreak: "break-all", lineHeight: 1.3,
              }}>
                <span style={{ color: "#10b981", fontWeight: 700 }}>now:</span> {p.smiles}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

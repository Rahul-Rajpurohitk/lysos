/**
 * Mol2DThumb — clean 2D structure thumbnail for a SMILES.
 *
 * Replaces text-heavy descriptions in service cards with the actual
 * chemistry. SVG is parsed via DOMParser and inserted as a real DOM
 * subtree (no dangerouslySetInnerHTML — any inline scripts are
 * stripped on the way through).
 *
 * Module-level SVG cache so the same SMILES never refetches.
 */
import { useEffect, useRef, useState } from "react";

const _SVG_CACHE = new Map<string, string>();

interface Props {
  apiBase: string;
  smiles: string | null;
  w?: number;
  h?: number;
  caption?: string;
  /** Accent the border + caption (before/after comparisons). */
  accent?: string;
  onClick?: () => void;
  title?: string;
}

function smilesToB64(s: string): string {
  if (typeof window === "undefined") return "";
  try {
    return window.btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
  } catch {
    return "";
  }
}

/** Inject SVG markup safely via DOMParser. Strips <script> and any
 *  on* event attributes; forces width/height to 100% so the structure
 *  scales to the host container. */
function injectSvg(host: HTMLDivElement | null, svgText: string): boolean {
  if (!host) return false;
  host.replaceChildren();
  try {
    const doc = new DOMParser().parseFromString(svgText, "image/svg+xml");
    const svg = doc.documentElement;
    // The parser uses tagName "svg" for SVG roots; instanceof SVGElement
    // is unreliable across iframes/edge browsers, tagName is the
    // canonical check.
    if (!svg || svg.tagName.toLowerCase() !== "svg") return false;
    // Bail if the parser inserted an error element (malformed XML).
    if (doc.getElementsByTagName("parsererror").length) return false;
    svg.querySelectorAll("script").forEach((n) => n.remove());
    svg.querySelectorAll<SVGElement>("*").forEach((el) => {
      for (const attr of Array.from(el.attributes)) {
        if (attr.name.toLowerCase().startsWith("on")) el.removeAttribute(attr.name);
      }
    });
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    (svg as unknown as HTMLElement).style.display = "block";
    host.appendChild(svg);
    return true;
  } catch {
    return false;
  }
}

export function Mol2DThumb({
  apiBase, smiles, w = 180, h = 140, caption, accent, onClick, title,
}: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ok" | "err">("idle");

  useEffect(() => {
    if (!smiles) {
      if (hostRef.current) hostRef.current.replaceChildren();
      setState("idle");
      return;
    }
    const key = `${smiles}|${w}x${h}`;
    const cached = _SVG_CACHE.get(key);
    if (cached) {
      const ok = injectSvg(hostRef.current, cached);
      setState(ok ? "ok" : "err");
      return;
    }
    setState("loading");
    let cancelled = false;
    const b64 = smilesToB64(smiles);
    if (!b64) { setState("err"); return; }
    fetch(`${apiBase}/workbench/molecule/2d/${b64}?w=${w}&h=${h}&indices=0`)
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then((d) => {
        if (cancelled) return;
        const s = String(d.svg || "");
        const ok = injectSvg(hostRef.current, s);
        if (ok) _SVG_CACHE.set(key, s);  // only cache valid SVGs
        setState(ok ? "ok" : "err");
      })
      .catch(() => { if (!cancelled) setState("err"); });
    return () => { cancelled = true; };
  }, [apiBase, smiles, w, h]);

  const accentCol = accent || "rgba(15,23,42,0.12)";
  const interactive = !!onClick;
  return (
    <div
      onClick={onClick}
      title={title || smiles || undefined}
      style={{
        display: "inline-flex", flexDirection: "column", alignItems: "center",
        gap: 3, padding: 4, borderRadius: 6,
        background: "white", border: `1px solid ${accentCol}`,
        cursor: interactive ? "pointer" : "default",
        transition: "box-shadow 0.12s",
      }}
      onMouseEnter={(e) => {
        if (interactive) {
          (e.currentTarget as HTMLDivElement).style.boxShadow = "0 2px 8px rgba(15,23,42,0.10)";
        }
      }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.boxShadow = ""; }}>
      {/* The ref'd host MUST have no React children. If JSX puts text
       *  here, React's reconciliation will wipe our imperatively-injected
       *  SVG on the next render — the structure goes blank but the
       *  caption stays. Keep the placeholder as a sibling overlay. */}
      <div style={{ position: "relative", width: w, height: h }}>
        <div
          ref={hostRef}
          style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0 }}
        />
        {state !== "ok" && (
          <div style={{
            position: "absolute", top: 0, left: 0, right: 0, bottom: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
            color: "var(--lys-text-faint)", fontSize: 10,
            fontFamily: "var(--lys-font-mono)", pointerEvents: "none",
            textAlign: "center", padding: 4,
          }}>
            {state === "err" ? "× unparseable" : smiles ? "rendering…" : "—"}
          </div>
        )}
      </div>
      {caption && (
        <div style={{
          fontSize: 9, fontWeight: 700, fontFamily: "var(--lys-font-mono)",
          letterSpacing: "0.04em", textTransform: "uppercase",
          color: accent ?? "var(--lys-text-faint)",
        }}>{caption}</div>
      )}
    </div>
  );
}

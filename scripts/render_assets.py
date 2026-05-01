"""Render all SVG files in a directory to PNG.

Picks the first available tool, in order of preference:
  1. rsvg-convert (cleanest, deterministic)
  2. inkscape    (best fidelity)
  3. headless chrome / chromium (works everywhere)

Usage:
    python scripts/render_assets.py docs/assets/
    python scripts/render_assets.py docs/assets/ --width 1920

Output PNGs land next to each SVG with the same basename:
    docs/assets/cover-1920.svg → docs/assets/cover-1920.png
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path


_VIEWBOX_RE = re.compile(r'viewBox="([\d.\s-]+)"')
_WIDTH_RE = re.compile(r'\bwidth="(\d+)"')
_HEIGHT_RE = re.compile(r'\bheight="(\d+)"')


def svg_size(svg: Path) -> tuple[int, int]:
    """Return (width, height) of the SVG's natural canvas size."""
    text = svg.read_text(errors="ignore")[:1500]
    m = _VIEWBOX_RE.search(text)
    if m:
        parts = m.group(1).split()
        if len(parts) == 4:
            return int(float(parts[2])), int(float(parts[3]))
    w = _WIDTH_RE.search(text)
    h = _HEIGHT_RE.search(text)
    if w and h:
        return int(w.group(1)), int(h.group(1))
    return 1920, 1080


def has(tool: str) -> bool:
    return shutil.which(tool) is not None


def render_with_rsvg(svg: Path, png: Path, width: int) -> None:
    subprocess.run(
        ["rsvg-convert", "-w", str(width), str(svg), "-o", str(png)],
        check=True,
    )


def render_with_inkscape(svg: Path, png: Path, width: int) -> None:
    subprocess.run(
        [
            "inkscape",
            str(svg),
            f"--export-filename={png}",
            f"--export-width={width}",
        ],
        check=True,
    )


def render_with_chrome(svg: Path, png: Path, width: int) -> None:
    chrome = (
        shutil.which("chromium")
        or shutil.which("google-chrome")
        or shutil.which("chrome")
        or "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    )
    if not Path(chrome).exists() and not shutil.which(chrome):
        raise RuntimeError("no chrome / chromium binary found")

    nat_w, nat_h = svg_size(svg)
    out_w = width
    out_h = int(round(nat_h * (width / nat_w)))

    import tempfile
    html = f"""<!doctype html>
<html><head><meta charset=utf-8>
<style>
  html,body {{ margin:0; padding:0; background:transparent; }}
  body {{ display:flex; align-items:flex-start; justify-content:flex-start; }}
  object {{ width:100vw; height:100vh; display:block; }}
</style>
</head><body>
<object type="image/svg+xml" data="{svg.resolve()}"></object>
</body></html>
"""
    with tempfile.NamedTemporaryFile(
        "w", suffix=".html", delete=False, encoding="utf-8"
    ) as fh:
        fh.write(html)
        wrapper = Path(fh.name)
    try:
        subprocess.run(
            [
                chrome,
                "--headless",
                "--disable-gpu",
                "--hide-scrollbars",
                "--default-background-color=00000000",
                f"--screenshot={png}",
                f"--window-size={out_w},{out_h}",
                f"file://{wrapper}",
            ],
            check=True,
        )
    finally:
        wrapper.unlink(missing_ok=True)


def pick_renderer():
    if has("rsvg-convert"):
        return "rsvg-convert", render_with_rsvg
    if has("inkscape"):
        return "inkscape", render_with_inkscape
    chrome = (
        shutil.which("chromium")
        or shutil.which("google-chrome")
        or shutil.which("chrome")
    )
    if chrome or Path(
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    ).exists():
        return "chrome", render_with_chrome
    return None, None


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("dir", type=Path)
    p.add_argument("--width", type=int, default=1920)
    args = p.parse_args()

    if not args.dir.is_dir():
        print(f"not a directory: {args.dir}", file=sys.stderr)
        return 1

    name, renderer = pick_renderer()
    if renderer is None:
        print(
            "no SVG renderer found.\n"
            "install one of:\n"
            "  brew install librsvg     # rsvg-convert\n"
            "  brew install inkscape    # inkscape\n"
            "  (or have Google Chrome / Chromium in PATH)",
            file=sys.stderr,
        )
        return 2

    print(f"using: {name}")
    svgs = sorted(args.dir.glob("*.svg"))
    for svg in svgs:
        png = svg.with_suffix(".png")
        try:
            renderer(svg, png, args.width)
            print(f"  ✓ {svg.name} → {png.name}")
        except subprocess.CalledProcessError as e:
            print(f"  ✗ {svg.name}: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

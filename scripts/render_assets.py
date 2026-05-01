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
import shutil
import subprocess
import sys
from pathlib import Path


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

    height = int(width * 9 / 16)
    subprocess.run(
        [
            chrome,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            "--default-background-color=00000000",
            f"--screenshot={png}",
            f"--window-size={width},{height}",
            f"file://{svg.resolve()}",
        ],
        check=True,
    )


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

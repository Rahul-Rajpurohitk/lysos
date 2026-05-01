# Lysos visual assets

All assets are 16:9 SVGs (resolution-independent). Convert to PNG with any
modern toolchain when needed for the lablab submission, pitch deck, or
demo video.

## Files

| Asset | Purpose | Used in |
|---|---|---|
| `cover-1920.svg` | Brand-mark hero · 1920×1080 | Slide 1 of pitch deck · lablab submission cover |
| `thumbnail-square.svg` | 1024×1024 square thumbnail | HF Space + social previews |
| `architecture.svg` | Full pipeline · MI300X memory budget | Pitch deck slide 5 · video Section 4 |
| `data-flow.svg` | 10 sources → loaders → HF Hub | Pitch deck slide 6 |
| `reward-curves.svg` | Per-component RL reward (projected mockup) | Pitch deck slide 6 · video Section 7 — swap for real wandb when training completes |
| `rocm-smi-mockup.svg` | Terminal-style 152/192 GB callout | Video Section 6 · pitch deck side-rail |
| `workspace-screenshot.png` | Live React UI screenshot (real, not a mockup) | Pitch deck slide 4 · video Section 5 (Beat 1) |

## Style system

- Background: `#06121a` (dark biomedical)
- Accent (generation / success): `#00e6b9` (Lysos teal)
- Accent (RL / training): `#e066a8` (magenta)
- Accent (embedding / RAG): `#3a86c0` (blue)
- Accent (data / known antibiotics): `#88c552` (green)
- Mono font: JetBrains Mono
- Sans font: Inter

## SVG → PNG conversion

Any of these work — pick what's installed:

```bash
# Inkscape (best fidelity)
inkscape cover-1920.svg --export-filename=cover-1920.png --export-dpi=192

# rsvg-convert (fast)
rsvg-convert -w 1920 cover-1920.svg -o cover-1920.png

# headless Chrome
chrome --headless --screenshot=cover-1920.png --window-size=1920,1080 cover-1920.svg
```

## Editing

Open the `.svg` directly in any editor — it's hand-authored XML. The
typography is system-resolved (no embedded fonts), so the rendering machine
needs JetBrains Mono and Inter installed for exact match. Otherwise the
fallback (`ui-monospace, monospace` and `system-ui, sans-serif`) renders fine.

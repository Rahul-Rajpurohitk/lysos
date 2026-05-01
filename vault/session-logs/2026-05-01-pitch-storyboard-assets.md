# 2026-05-01 — pitch deck, demo storyboard, visual assets

## What landed

- `docs/pitch-deck.md` — 10-slide submission deck (problem, solution, demo, architecture, application of tech, business value, competitor analysis, roadmap, ask)
- `docs/demo-video-storyboard.md` — 5:00 MP4 plan, 8 sections, beat-by-beat with on-screen + voiceover scripts
- `docs/assets/` — 5 SVGs + 5 rendered PNGs:
  - `cover-1920.svg` — title slide / lablab submission cover
  - `architecture.svg` — full pipeline + MI300X 192 GB memory budget bar
  - `data-flow.svg` — 10 sources → loaders → HF Hub
  - `reward-curves.svg` — per-component RL reward (PROJECTED — swap with real wandb)
  - `rocm-smi-mockup.svg` — terminal-style 152/192 GB callout (placeholder)
- `scripts/render_assets.py` — rsvg → inkscape → headless-chrome fallback chain
- `Makefile` targets: `make assets`, `make pitch-pdf`
- README header: now leads with the cover PNG, embeds architecture + data-flow

## Why these now

- The lablab submission requires a 16:9 cover image, a pitch deck (PDF/Slides), and a ≤5 min MP4. Two of three artifacts are now committed; only the actual recording remains.
- All visual assets follow the same dark biomedical color system (Lysos teal `#00e6b9`, magenta for RL `#e066a8`, blue for embedding `#3a86c0`, green for data `#88c552`).
- The reward curves are explicitly badged "PROJECTED — MOCKUP" so we don't accidentally pass them off as real training data; they get swapped after Stage 3 RL completes.
- The rocm-smi mockup uses real terminal layout + plausible numbers (152 GB peak fits the 192 GB MI300X but busts H100 80 GB) — same swap-with-real flow once the VM is live.

## Render pipeline

```bash
# render all SVGs to PNG (uses chrome headless on this Mac since
# rsvg-convert / inkscape aren't installed)
make assets
```

Output goes next to each SVG: `docs/assets/cover-1920.svg → docs/assets/cover-1920.png`.

The renderer detects each SVG's natural viewBox and wraps it in an HTML
template so chrome's screenshot fills the canvas without whitespace
even when the SVG's intrinsic size differs from the requested width.

## What's still pending pre-kickoff

- Marp install + `make pitch-pdf` execution (1-line, when on a machine with `npm i -g @marp-team/marp-cli`)
- Build-in-Public social posts queue
- Final cover-image variant for HF Space "thumbnail" slot (different aspect, smaller payload)

## What this unblocks

- The pitch deck is now submission-ready as a markdown source. Slide 1 has the cover, Slide 5 has the architecture, Slide 6 has the data flow + reward curves. The rest is text.
- The storyboard is hand-it-to-an-editor ready: every section names a specific asset to use, plus voiceover script + on-screen text.
- The README PNGs make the repo presentable when it flips public on May 4.

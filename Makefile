# Lysos developer Makefile.
#
# All targets work from the repo root with /usr/bin/python3 (3.9 with pandas
# + requests installed) on macOS, or any Python 3.10+ with pyproject.toml
# deps installed.

PYTHON ?= /usr/bin/python3

# ---- meta ----------------------------------------------------------------
.PHONY: help
help:
	@echo "Lysos — generative drug designer for AMR"
	@echo
	@echo "Common targets:"
	@echo "  make verify        Smoke-import all 23 modules"
	@echo "  make test          Run unit tests"
	@echo
	@echo "Data:"
	@echo "  make fetch         Run all 10 data loaders (cap 200/pathogen)"
	@echo "  make fetch-full    Run all loaders, no cap (~1-2 GB; SLOW)"
	@echo "  make refresh       Re-run loaders with --refresh (force)"
	@echo "  make inventory     Report on-disk data sizes + counts"
	@echo
	@echo "Build:"
	@echo "  make web-install   Install workspace/web Node deps"
	@echo "  make web-build     Build the React frontend → workspace/web/dist"
	@echo "  make docker        Build the workspace Docker image"
	@echo
	@echo "Misc:"
	@echo "  make clean-data    Delete data/raw/ + data/processed/"
	@echo "  make commit-push   Run git add + commit + push (interactive)"

# ---- verification --------------------------------------------------------
.PHONY: verify
verify:
	@$(PYTHON) scripts/verify_loaders.py

.PHONY: test
test:
	@$(PYTHON) tests/test_rewards.py

# ---- data ----------------------------------------------------------------
.PHONY: fetch
fetch:
	@$(PYTHON) scripts/fetch_all_data.py --max-per-pathogen 200 --no-process

.PHONY: fetch-full
fetch-full:
	@$(PYTHON) scripts/fetch_all_data.py --max-per-pathogen 5000

.PHONY: refresh
refresh:
	@$(PYTHON) scripts/fetch_all_data.py --max-per-pathogen 200 --refresh --no-process

.PHONY: inventory
inventory:
	@$(PYTHON) scripts/data_inventory.py --root data/

.PHONY: chembl
chembl:
	@$(PYTHON) -m src.data.chembl --output data/raw/chembl_antibiotics.csv

.PHONY: dbaasp
dbaasp:
	@$(PYTHON) -m src.data.dbaasp --output data/raw/dbaasp_amps.csv \
		--max-per-pathogen 500

.PHONY: bindingdb
bindingdb:
	@$(PYTHON) -m src.data.bindingdb --output data/raw/bindingdb_antibacterial.csv

.PHONY: zinc
zinc:
	@$(PYTHON) -m src.data.zinc --output data/raw/zinc_drug_like.csv

# ---- workspace -----------------------------------------------------------
.PHONY: web-install
web-install:
	cd workspace/web && npm ci || npm install

.PHONY: web-build
web-build:
	cd workspace/web && npm run build

.PHONY: web-dev
web-dev:
	cd workspace/web && npm run dev

.PHONY: api-dev
api-dev:
	uvicorn workspace.api.server:app --reload --port 7860

.PHONY: docker
docker:
	cd workspace && docker build -t lysos-workspace .

# ---- training ------------------------------------------------------------
.PHONY: stage1-dry
stage1-dry:
	@$(PYTHON) -m src.training.stage1_txgemma4 \
		--config configs/stage1_txgemma4.yaml --dry-run

.PHONY: stage2-dry
stage2-dry:
	@$(PYTHON) -m src.training.stage2_amr_sft \
		--config configs/stage2_amr_sft.yaml --dry-run

.PHONY: stage3-dry
stage3-dry:
	@$(PYTHON) -m src.training.stage3_rl_grpo \
		--config configs/stage3_rl_grpo.yaml --dry-run

# ---- cleanup -------------------------------------------------------------
.PHONY: clean-data
clean-data:
	rm -rf data/raw data/processed

.PHONY: clean-cache
clean-cache:
	rm -rf data/raw/*_cache

.PHONY: build-index
build-index:
	@$(PYTHON) scripts/build_known_antibiotics_index.py

# ---- visual assets (SVG → PNG) -------------------------------------------
# Picks the first available tool: rsvg-convert > inkscape > headless chrome.
.PHONY: assets
assets:
	@$(PYTHON) scripts/render_assets.py docs/assets/

.PHONY: pitch-pdf
pitch-pdf:
	@which marp >/dev/null 2>&1 || (echo 'marp not installed: npm i -g @marp-team/marp-cli' && exit 1)
	@marp docs/pitch-deck.md --pdf --output docs/lysos-pitch.pdf
	@echo "wrote docs/lysos-pitch.pdf"

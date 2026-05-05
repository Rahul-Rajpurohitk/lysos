# Bias Audit — Lysos AMR Dataset

Documented biases in the corpus, their origin, impact on training, and
mitigations applied or planned. Required for HF dataset card transparency
and for the methods paper limitations section.

## 1. Pathogen distribution bias

**Bias**: ChEMBL submission patterns over-represent Mtb (4,236 records)
vs NGono (591). Reflects TB-Alliance + Bill & Melinda Gates Foundation
funding focus on TB drug discovery; NGono receives less industry attention
(despite WHO high-priority status).

**Per-pathogen ChEMBL distribution**:
| Pathogen | Records | Bias direction |
|----------|---------|----------------|
| Mtb | 4,236 | Over-represented (~7× expected) |
| EColi-CRE | 3,955 | Over-represented |
| MRSA | 3,091 | Slightly over |
| Paer | 2,807 | At expected level |
| KpneuCRE | 2,559 | Slightly under |
| VRE | 2,426 | At level |
| Abaum | 1,618 | Under-represented |
| NGono | 591 | Severely under-represented (~14% of expected) |

**Impact**: Stage-2 SFT will be biased toward Mtb-shaped reasoning (rpoB,
katG, InhA mechanisms). NGono knowledge will be thinner.

**Mitigation applied**:
- Pathogen primer adds NGono context to generic-chemistry rows (~5,300 rows
  now have NGono context via primer)
- Multi-pathogen spectrum traces explicitly include NGono in mix
- Per-pathogen targeted distillation: NGono-PBP2 has 313 traces, NGono-GyrB
  has 323 traces (close to other pathogens)
- Eval tracks per-pathogen accuracy separately

**Mitigation planned**:
- Hard-negative mining will surface NGono prediction failures for re-training
- Future pro-v13+ should add COADD NGono-specific data when available

## 2. PK panel demographic bias

**Bias**: PK panel rows (~75 antibiotics × 6 row types = 468 rows) reflect
adult-male PK predominantly. Pediatric, geriatric, pregnant women, obese,
and renal-impaired populations have sparse coverage.

**Impact**: Lysos clinical positioning + dose recommendations may be more
accurate for typical-adult-male than special populations.

**Mitigation applied**:
- Special-populations distillation layer (1 of 20 in edge_clinical layer):
  pediatric, pregnancy, geriatric, renal/hepatic dosing
- Confidence convention encourages uncertainty when out-of-distribution

**Mitigation planned**:
- DrugBank Open contains pharmacology section with pediatric notes —
  expand pro-v13 with pediatric-specific PK rows

## 3. ChEMBL submission bias

**Bias**: ChEMBL only contains compounds that have been tested + reported.
Negative results (compounds that failed in trials, were never published)
are absent. Standardized assays from a few large pharma + academic groups
dominate.

**Impact**: Model may be systematically over-confident (only sees
publishable compounds → believes everything is "drug-like enough to test").

**Mitigation applied**:
- DUD-E decoys (~13K active-decoy pairs in pro-v4+): property-matched
  non-actives counter the publication-positive bias
- Failure narrative distillation: 500 traces about failed clinical agents
  (cethromycin, solithromycin, iclaprim, plazomicin) explain why drugs
  fail
- Negative-example traces in agentic data

**Mitigation planned**:
- Patent literature (USPTO via SureChEMBL) would add ~80% of medicinal
  chemistry knowledge — currently zero
- ClinicalTrials.gov failed-trial mining (post-hackathon)

## 4. Source language bias

**Bias**: Corpus is English-only. Surveillance / clinical literature in
non-English languages excluded. Pathogen incidence + resistance patterns
in Asia, Africa, Latin America are under-documented.

**Impact**: Model will reflect Western (US/EU) AMR landscape. Pathogen
resistance patterns in low-resource settings less accurate.

**Mitigation applied**:
- WHO surveillance data integrated (global scope)
- WHO priority pathogen lists (not US-only) drive 8-pathogen selection

**Mitigation planned**:
- Multilingual literature ingestion (post-hackathon; needs translation pipeline)

## 5. Single-author teacher distillation bias

**Bias**: 78,150 teacher distillation traces authored by one developer +
Claude in-session. Reflects the author's mental model + Claude's training
distribution.

**Impact**: Ideological / framing bias toward a particular AMR worldview.
Specific scaffold preferences (5GC, DBO inhibitors, peptide-based
antibiotics) over-represented.

**Mitigation applied**:
- Cross-checked claims against canonical references (Telenti 1993, Walsh
  1993, Bugg 1991, Murray 2022)
- Eval-aligned distillation includes "reasoning faithfulness" with
  explicit citation patterns

**Mitigation planned**:
- Open-source release for community review
- Multi-author distillation in future iterations

## 6. NPAtlas natural product origin bias

**Bias**: NPAtlas entries skew toward soil-derived bacteria
(Streptomyces especially — ~40% of NPs). Marine, plant, fungal, gut-
microbiome NPs under-represented.

**Impact**: "natural_product_origin" task biased toward Streptomyces.

**Mitigation applied**:
- Genus diversification in distillation: explicit traces for Aspergillus,
  Penicillium, Bacillus, Pseudomonas, Micromonospora, Actinomyces,
  Saccharomyces, etc.

**Mitigation planned**:
- MarinLit / SymPDB integration (marine NPs) post-hackathon

## 7. Time bias

**Bias**: Corpus reflects pre-2025 surveillance + clinical practice. New
drugs approved in 2024-2025 (aztreonam-avibactam) appear primarily in
teacher distillation (which was authored with 2024 knowledge) but not in
ChEMBL pre-2024 dumps.

**Impact**: Model may know pre-2024 well but struggle with 2024+
drugs/resistance patterns.

**Mitigation applied**:
- Time-aware split eval (8 prompts) tests whether model can predict
  emerging resistance from earlier data
- Surveillance citations from 2024 included in teacher distillation

**Mitigation planned**:
- Update corpus quarterly (post-hackathon)

## 8. Stereo / tautomer state bias

**Bias**: ChEMBL deposits compounds in arbitrary stereo + tautomer states.
~20% have undefined stereo. Pre-cleanup, training would have learned
spurious tautomer-invariance.

**Impact**: Pre-cleanup data was noisy on stereochemistry-critical
relationships (e.g., D-Ala-D-Ala vs D-Ala-D-Lac in vancomycin-VRE).

**Mitigation applied**:
- Stereo classification: achiral / defined / partial / undefined / peptide / racemic
- Tautomer canonicalization via MolVS (skip if >80 heavy atoms)
- Stereo-state column allows downstream filtering / weighting
- Vancomycin-VRE story explicitly in distillation as canonical "stereo
  matters" example

**Mitigation planned**:
- Per-stereo-class evaluation (separate accuracy on chiral vs achiral)

## 9. ChEMBL standard_type heterogeneity bias

**Bias**: ChEMBL records mix MIC, MIC50, MIC90, IC50, EC50, Ki, Kd. We
combined 8 standard_types. These are NOT interchangeable; mixing them
without unit normalization introduces systematic error.

**Impact**: MIC predictor trained on heterogeneous endpoints may have
~0.6+ log RMSE on actual MIC values.

**Mitigation applied**:
- Log-transform to log10(MIC_µM) when possible
- standard_type tracked in row metadata
- Confidence calibration: predictor's confidence reflects input-distribution
  match

**Mitigation planned**:
- Per-standard-type calibration sweep
- Filter to MIC-only for the highest-confidence Tier 1 evaluations

## 10. Tool/API availability bias

**Bias**: 25 tools in workspace/tools/ assumed available. In practice,
Boltz-2 + AizynthFinder require GPUs not always available. Cache fallbacks
exist but performance degrades.

**Impact**: Reward components like `boltz2_pose_conf` use proxy data when
real Boltz-2 unavailable.

**Mitigation applied**:
- Boltz-2 proxy cache (30K entries) covers training distribution
- AizynthFinder priority sweep (1000 candidates) in progress
- Reward component reads cache; fallback for cache miss

**Mitigation planned**:
- Real Boltz-2 + AizynthFinder execution post-hackathon
- Update proxy → measured cache when GPU available

## Cross-cutting summary

| Bias category | Severity | Mitigation status |
|---------------|----------|-------------------|
| Pathogen distribution | HIGH | Partial (primer + targeted distill) |
| PK panel demographics | MED | Partial (special-pop distill) |
| ChEMBL publication bias | MED | Partial (DUD-E decoys + failure narratives) |
| Source language | LOW | Documented; deferred |
| Author distillation | MED | Documented; cross-checked |
| NPAtlas genus | LOW | Mitigated (genus diversification) |
| Time | MED | Mitigated (time-aware eval) |
| Stereo / tautomer | HIGH | Mitigated (cleanup pipeline) |
| Standard_type heterogeneity | MED | Documented; deferred |
| Tool availability | LOW | Mitigated (cache fallbacks) |

## Action

Bias-mitigation status will be tracked in `MANIFEST.json` and surfaced in
the model card. Methods paper limitations section explicitly cites this
bias audit.

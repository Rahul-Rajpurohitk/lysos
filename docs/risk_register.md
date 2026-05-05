# Lysos Risk Register

Stage 0 strategy doc. Each risk has a likelihood, impact, mitigation, and
backup plan. Reviewed at every sprint start.

## Format

| Risk | Likelihood | Impact | Mitigation | Backup |
|------|-----------|--------|------------|--------|

## Stage 1 (TxGemma-4 base SFT)

| Risk | Lik | Imp | Mitigation | Backup |
|------|-----|-----|------------|--------|
| TxGemma replication fails to converge on Gemma 4 | LOW | HIGH | Use Google's published TxGemma checkpoint as baseline; replicate post-hackathon | Skip Stage 1; start Stage 2 SFT directly from Gemma 4 base |
| 8× MI300X allocation unavailable | MED | HIGH | Pre-reserve via AMD Dev Cloud queue | Stage-1 on 1× MI300X with smaller batch + LoRA; ~24h instead of 6h |
| Gemma 4 weights gated, no access | LOW | CRIT | Pre-request access via HuggingFace 1 week before training | Use Gemma 2 27B (smaller, less capable) + downscale eval |
| TDC tasks fail to instruction-tune | LOW | MED | Use TDC's reference implementation + checkpoints | Skip TDC; rely on Stage 2 SFT alone |

## Stage 2 (Lysos AMR-spec SFT)

| Risk | Lik | Imp | Mitigation | Backup |
|------|-----|-----|------------|--------|
| Loss masking misalignment (response_template not found) | LOW | CRIT | Verified via smoke test (4/4 PASS) | If discovered: re-format dataset with explicit `<start_of_turn>model\n` tag |
| Sequence packing inefficiency (tokens wasted) | MED | LOW | Audit script in `scripts/audit_packing.py` | Disable packing; accept 2-3× longer training |
| Catastrophic forgetting of TDC ADMET tasks | MED | MED | LoRA + base-model freezing layers 0-15 | Mix TDC tasks back into Stage 2 corpus |
| Memory OOM on 1× MI300X (192GB) | LOW | HIGH | LoRA rank 32; gradient checkpointing | Reduce batch size; gradient accumulation |
| Convergence too slow (>12h budget) | MED | MED | Mid-training eval at 1h, 4h, 8h marks; halt if no improvement | Reduce training data to 100K rows |

## Stage 3 (GRPO RL)

| Risk | Lik | Imp | Mitigation | Backup |
|------|-----|-----|------------|--------|
| Reward hacking (model gaming one component) | MED | HIGH | Reward hacking probe (12 cases); calibrated weights | Re-weight components; add penalty terms |
| KL divergence explodes from reference model | MED | HIGH | β=0.04 KL coefficient; sweep at 0.02, 0.04, 0.08 | Increase β; or do PPO instead of GRPO |
| Reference model staleness (drift from initial state) | LOW | MED | Refresh reference every 500 steps | Hot-restart with fresh reference |
| Synthesizability cache empty for novel candidates | MED | LOW | SAscore proxy fallback in reward component | Use only structural alerts + drug-likeness for synth signal |
| Boltz-2 cache miss rate too high | HIGH | LOW | Proxy cache covers 30K (smiles, pathogen, pdb) entries; new candidates fall back to predict_binding_affinity | Disable boltz2_pose_conf reward component; redistribute weight |
| RL collapse (mode collapse to one scaffold) | MED | HIGH | Pareto entry reward + novelty reward + group_size 8 | Increase exploration via temperature; reduce KL coefficient |

## Stage 4 (Evaluation)

| Risk | Lik | Imp | Mitigation | Backup |
|------|-----|-----|------------|--------|
| Pre-train baseline disagrees with published Gemma 4 numbers | LOW | MED | Use Google's released eval suite as cross-check | Note discrepancy in methods paper; include both |
| Test set leakage discovered post-train | LOW | CRIT | 0 leakage verified in cross-split audit | If found: clean dataset; re-train |
| OOD generalization fails (Salmonella + S. pneumoniae) | MED | LOW | Expected behavior is graceful refuse-with-redirect; not predictive | Document as "out-of-scope" in paper |
| Adversarial robustness <95% | MED | MED | Refusal training already extensive (1.5K + 18 jailbreak templates) | Add more adversarial training rows; second SFT round |
| Time-aware split shows no signal | HIGH | LOW | Strong claim if works; null result is acceptable | Document as "did not generalize temporally"; fall back to in-distribution claims |

## Stage 5 (Deployment)

| Risk | Lik | Imp | Mitigation | Backup |
|------|-----|-----|------------|--------|
| vLLM rocm container unstable | MED | HIGH | Pin rocm/vllm:latest at first stable tag pre-launch | Fall back to CPU-only inference for demo (slow but works) |
| Workbench frontend fails | LOW | MED | Test on local stack pre-demo | Skip Workbench; show CLI demo only |
| HF Space upload fails | LOW | LOW | Test upload path 1 day before submission | Submit GitHub-only |
| API rate limits hit during eval | MED | LOW | Local vLLM serving avoids API | Reduce eval prompt count |

## Cross-cutting / business

| Risk | Lik | Imp | Mitigation | Backup |
|------|-----|-----|------------|--------|
| AMD credits don't land before deadline | MED | CRIT | Apply early (done); follow up daily | Submit data-prep + methods-paper-only as Track 1 (not Track 2 GPU-trained) |
| AMD credit budget overrun | LOW | HIGH | Monitor spend; kill VM at $200 threshold | Pre-approved $300 ceiling |
| Hackathon submission deadline missed | LOW | CRIT | Submit early (May 9) with placeholder for final eval | Continuous submission updates allowed pre-deadline |
| Methods paper missing sections | LOW | MED | Outline complete; results section is the only gap | Submit as preprint without results; update post-deadline |
| HuggingFace dataset/model access controls | LOW | LOW | Datasets currently private; flip to public on submission day | Manual download links in repo |

## Action items

- [x] Risk register documented
- [ ] Re-review every 2 days during hackathon
- [ ] Update mitigations as work proceeds
- [ ] Document any new risks that emerge

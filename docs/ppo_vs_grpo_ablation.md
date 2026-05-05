# PPO vs GRPO Ablation — Experiment Design

We default to GRPO for Stage-3 RL. This doc designs an ablation to verify
GRPO is the right choice (vs PPO) for our 12-component reward stack +
LoRA-tuned base model.

## Background

- **PPO** (Proximal Policy Optimization, Schulman 2017): single-trajectory
  policy gradient with clipped surrogate. Standard for RL fine-tuning.
- **GRPO** (Group-Relative PPO, Shao 2024 DeepSeekMath): instead of
  computing advantages from a value function, GRPO samples a group of N
  responses per prompt and uses group-relative rewards. Cuts compute (no
  value model needed) + works well on reasoning tasks.

## Why GRPO might be better for Lysos

- Drug-design has a clear "good response" vs "bad response" within a single
  prompt — group sampling is natural fit
- The 12-component reward stack is computed per-response, no value-model
  fitting needed
- DeepSeekMath shows GRPO ≈ PPO with less compute on reasoning tasks
- Group_size 8 gives diversity → useful for exploration

## Why PPO might be better for Lysos

- More mature code (more battle-tested in TRL)
- Works well with LoRA / PEFT
- Established hyperparameters (KL=0.04, clip=0.2, lr=5e-7)
- Less prone to mode collapse with diverse rewards

## Ablation design

Train two parallel models for 1000 steps each:
- **Model A**: GRPO, group_size=8, β=0.04, lr=5e-7
- **Model B**: PPO, β=0.04, lr=5e-7, clip_range=0.2

## Compute budget

- Each: 1× MI300X, ~3h, ~$10-12
- Total: ~$25 (~8% of budget)

## Eval

After 1000 steps, both models evaluated on:
- 7-metric harness
- 100-prompt subset (cheaper than full eval)
- Same seed for fair comparison

## Decision rule

- If GRPO ≥ PPO on ≥4/7 metrics → continue with GRPO
- If PPO ≥ GRPO on ≥4/7 metrics → switch to PPO for full Stage-3
- If equivalent → stick with GRPO (TRL has better GRPO support)

## Hyperparameter notes

GRPO config:
```yaml
rl:
  algorithm: grpo
  group_size: 8
  num_generations: 8
  temperature: 1.0
  top_p: 0.95
  generation_batch_size: 16
  use_vllm: false  # set true if rocm/vllm-grpo integration ready
  reward_clip:
    enabled: true
    min: -1.0
    max: 2.0
  advantage:
    normalize: true
    type: group
```

PPO config (for ablation):
```yaml
rl:
  algorithm: ppo
  clip_range: 0.2
  vf_coef: 0.5
  c1: 1.0
  c2: 0.01  # entropy coefficient
  generation_batch_size: 16
  use_vllm: false
  advantage:
    type: gae
    gamma: 1.0
    lambda: 0.95
```

## Status

DEFERRED post-hackathon. Defaulting to GRPO for first run; ablation in
follow-up sprint.

## References

- Schulman et al. 2017. Proximal Policy Optimization Algorithms. arXiv:1707.06347.
- Shao et al. 2024. DeepSeekMath: Pushing the Limits of Mathematical Reasoning. arXiv:2402.03300.

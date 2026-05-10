# Lysos — 90-second demo script

Total: ~90s. Three beats: training story (15s) → live system (60s) → close (15s).
Each line is what you SAY. The `▶` lines are what you DO on-screen.

---

## 0:00 → 0:15 · The training story

> "Lysos is an antimicrobial drug-discovery agent we built on AMD MI300X.
> We took **Gemma 4 31B** and fine-tuned it three times — Stage 1 was
> continued pretraining for therapeutics, Stage 2 was supervised
> fine-tuning on 222 thousand AMR examples, and Stage 2.5 was DPO
> alignment on hard-negative Pareto pairs. The merged model is live
> on Hugging Face right now, serving from this MI300X behind me."

▶ Open `huggingface.co/rahul24raj/lysos-base-dpo` — show the adapter
▶ Cut to terminal: `ssh lysos-vm 'rocm-smi --showuse'` — MI300X loaded

---

## 0:15 → 1:15 · The system, live

> "MRSA is the target. **mecA** is the gene we have to escape."

▶ Open the app at `localhost:5173` — Knowledge tab
▶ Point at the Knowledge hub card → 4 resistance threats, drug-class pressure heatmap
▶ Click **mecA** in the resistance network → fires `/explain mecA`
> "The agent pulls a grounded brief on mecA in real-time."

▶ Switch to Chemistry tab. Type `/wf design_with_debate` in chat.
> "I trigger the multi-agent debate. Four Gemini Pro calls — Designer
> drafts candidates, Critic challenges them, Editor refines, Strategist
> picks a winner. You can watch them in the Agents tab."

▶ Open Agents tab while debate runs → live cost meter, flow graph, latency p95s
▶ Back to Chemistry. Workflow card shows the winner SMILES.

> "The strategist crowns one. It auto-loads to the 2D builder, the
> 3D pocket renders the docked pose, and the resistance escape map
> shows which atoms are still vulnerable to mecA mutations."

▶ Click the **HARDEN** tab on the resistance card.
> "AI-bespoke swaps with confidence + delta-robustness. I send one to
> the agent."

▶ Click **send to agent →** on the top suggestion.
> "Agent reasons about the swap, applies it if chemistry checks out,
> and the canvas updates live. The score panel re-runs on every change."

▶ Switch to Scoring tab — composite jumps from 0.59 → 0.67.

> "Then `/wf pareto_explore` to see the trade-off frontier, and the
> Critic narrates: advance THIS, A/B THAT, drop the dominated one."

▶ Run `/wf pareto_explore` — show the markdown table + critic verdict.

---

## 1:15 → 1:30 · Close

> "The reigning champion auto-promotes per pathogen. Eight pathogens,
> one merged Lysos model, MI300X serving inference, Gemini Pro
> orchestrating the agents. Built for the AMD Developer Hackathon."

▶ Open Knowledge tab, scroll to **Champion vault** — 1 of 8 crowned
▶ Final frame: GitHub `Rahul-Rajpurohitk/lysos` URL on screen

---

## On-screen quick reference (cheat card)

| key beat | slash / click |
|---|---|
| explain a gene | click in Resistance Network |
| start design | `/wf design_with_debate` |
| see agents | Agents tab → flow graph |
| harden a candidate | resistance card → HARDEN → send to agent |
| trade-off view | `/wf pareto_explore` |
| champion lookup | `/champion` |

## Rules during shoot

- ONE pathogen end-to-end (MRSA). Don't switch.
- Type slash commands letter-by-letter — palette pops, looks agentic.
- Pause 1s after each agent message lands so the viewer reads it.
- If `/wf` errors, just retry — backend is live.
- Backend `:7860` and Vite `:5173` already up.
- VM endpoint `http://165.245.141.167:8000/v1/models` will return 200
  when vllm finishes loading — you can show that as proof of live serve.

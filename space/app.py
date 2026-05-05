"""Lysos HF Space — public Workbench demo.

Gradio app for the AMD Hackathon submission. Judges + reviewers click
through the Designer agent loop without needing local infrastructure.

Architecture:
  - Gradio UI (8 priority pathogens + design panel + tool log)
  - Lysos-RL hosted via HF Inference Endpoint (Pro accelerated)
  - Reward stack runs locally in Space (CPU is fine for scoring)
  - Resistome briefing + PDB structures statically loaded
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import gradio as gr

INFERENCE_ENDPOINT = os.environ.get(
    "LYSOS_INFERENCE_URL",
    "https://api-inference.huggingface.co/models/rahul24raj/lysos-rl",
)
HF_TOKEN = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

PATHOGEN_INFO = {
    "MRSA": {
        "full_name": "Methicillin-Resistant Staphylococcus aureus",
        "tier": "WHO High Priority",
        "first_line": "vancomycin (IV 15-20 mg/kg q12h, trough 15-20 µg/mL); ceftaroline (IV 600 mg q12h) for vancomycin failure",
        "primary_target": "PBP2a (PDB 1VQQ, 5M18)",
        "key_resistance": "mecA → PBP2a (low-affinity transpeptidase); blaZ; vanA-acquired in resistant lineages",
    },
    "Mtb": {
        "full_name": "Mycobacterium tuberculosis",
        "tier": "WHO Critical Priority",
        "first_line": "RIPE 2 mo: rifampin 10 mg/kg + isoniazid 5 mg/kg + pyrazinamide 25 mg/kg + ethambutol 15 mg/kg, then RI for 4 mo",
        "primary_target": "InhA (PDB 2NSD), KatG, RpoB",
        "key_resistance": "rpoB-S531L (rifampin); katG-S315T (INH); inhA promoter -15; gyrA-A90V (FQ)",
    },
    "EColi-CRE": {
        "full_name": "Carbapenem-Resistant Escherichia coli",
        "tier": "WHO Critical Priority",
        "first_line": "ceftazidime-avibactam (KPC); meropenem-vaborbactam; cefiderocol (universal); aztreonam-avibactam (MBL+)",
        "primary_target": "KPC-2 (PDB 6Q9B), NDM-1 (3SPU), OXA-48 (3HBR)",
        "key_resistance": "KPC-2/3 carbapenemases; NDM-1 metallo-β-lactamase; OXA-48; porin loss",
    },
    "KpneuCRE": {
        "full_name": "Carbapenem-Resistant Klebsiella pneumoniae",
        "tier": "WHO Critical Priority",
        "first_line": "ceftaz-avi (KPC-3); aztreonam-avi (MBL+); cefiderocol (pan-R)",
        "primary_target": "KPC-3 (PDB 5VFA)",
        "key_resistance": "KPC-3 D179Y (avibactam-R, emerging); OXA-48; NDM",
    },
    "Abaum": {
        "full_name": "Acinetobacter baumannii",
        "tier": "WHO Critical Priority",
        "first_line": "sulbactam-durlobactam (FDA 2023); polymyxin B + minocycline; cefiderocol",
        "primary_target": "OXA-23 (PDB 4JF6)",
        "key_resistance": "OXA-23/24/58 carbapenemases; OmpA loss; AdeABC efflux",
    },
    "Paer": {
        "full_name": "Pseudomonas aeruginosa",
        "tier": "WHO High Priority",
        "first_line": "ceftolozane-tazobactam (MDR); cefiderocol; aztreonam-avi (MBL+); inhaled tobramycin (CF)",
        "primary_target": "PBP3 (PDB 3OG7), MexAB-OprM (5O8R)",
        "key_resistance": "AmpC-derepression; MexAB-OprM efflux; VIM/IMP MBLs",
    },
    "VRE": {
        "full_name": "Vancomycin-Resistant Enterococcus",
        "tier": "WHO High Priority",
        "first_line": "linezolid (PO/IV 600 mg q12h); daptomycin (IV 8-12 mg/kg endocarditis); tigecycline",
        "primary_target": "VanA D-Ala:D-Lac ligase (PDB 1IOG)",
        "key_resistance": "vanA (D-Ala-D-Lac); vanB; 23S G2576T linezolid-R; cfr",
    },
    "NGono": {
        "full_name": "Neisseria gonorrhoeae",
        "tier": "WHO High Priority",
        "first_line": "ceftriaxone IM 500 mg single (1g for cfx-R); zoliflodacin oral 3g single (FDA 2025)",
        "primary_target": "PBP2-penA mosaic (PDB 6P58), GyrB (5N6S)",
        "key_resistance": "penA mosaic XXXIV/XXXV; gyrA-S91F + parC-D86N (FQ-R); mtrR-up",
    },
}


def call_lysos(prompt: str) -> str:
    """Call Lysos-RL via HF Inference Endpoint."""
    if not HF_TOKEN:
        return "⚠ HF_TOKEN not set. Set in Space secrets."
    try:
        import requests
        r = requests.post(
            INFERENCE_ENDPOINT,
            headers={"Authorization": f"Bearer {HF_TOKEN}"},
            json={
                "inputs": prompt,
                "parameters": {"max_new_tokens": 768, "temperature": 0.0},
            },
            timeout=60,
        )
        r.raise_for_status()
        out = r.json()
        if isinstance(out, list) and out:
            return out[0].get("generated_text", str(out))
        return str(out)
    except Exception as exc:
        return f"⚠ Inference error: {exc}"


def design_candidate(pathogen: str, constraint: str) -> tuple[str, str]:
    """Run a Designer-agent loop for the picked pathogen."""
    info = PATHOGEN_INFO.get(pathogen, {})
    briefing = (
        f"# Lysos Workbench — {info.get('full_name', pathogen)}\n\n"
        f"**Priority tier**: {info.get('tier', '?')}\n"
        f"**Primary target**: {info.get('primary_target', '?')}\n"
        f"**First-line therapy**: {info.get('first_line', '?')}\n"
        f"**Key resistance**: {info.get('key_resistance', '?')}\n\n"
        f"**Constraint profile**: {constraint}\n\n"
        f"---\n\n"
    )

    prompt = (
        f"You are the Lysos Designer agent. Design an antibacterial candidate "
        f"against {info.get('full_name', pathogen)} ({pathogen}). "
        f"Constraint profile: {constraint}. "
        f"Pivot AROUND the first-line therapy class to evade "
        f"{info.get('key_resistance', 'resistance')}. "
        f"Output:\n"
        f"  PROPOSAL: <SMILES>\n"
        f"  RATIONALE: 2-3 sentences citing the resistome briefing\n"
        f"  EXPECTED MIC: <log10 MIC + confidence>\n"
        f"  NEXT: which tool to call next"
    )

    response = call_lysos(prompt)
    return briefing + response, prompt


with gr.Blocks(theme=gr.themes.Soft(), title="Lysos — Antimicrobial Drug-Design") as demo:
    gr.Markdown("""
    # Lysos — Antimicrobial Drug-Design Workbench
    
    **Open-source generative drug-design system** specialized for antimicrobial
    resistance, built on Gemma 4 with manually-authored teacher distillation
    across 7 layers + 12-component GRPO reward stack on AMD MI300X.
    
    Targets the 8 WHO-priority pathogens. Pivots AROUND first-line therapy
    classes to reduce cross-resistance pressure.
    
    *AMD Developer Hackathon submission — May 2026*
    """)

    with gr.Row():
        with gr.Column(scale=1):
            pathogen = gr.Dropdown(
                choices=list(PATHOGEN_INFO.keys()),
                value="MRSA",
                label="Pathogen",
                info="WHO-priority bacterial target",
            )
            constraint = gr.Dropdown(
                choices=[
                    "lead-like (MW≤500, logP≤4)",
                    "fragment-extension (MW≤350)",
                    "macrocycle (MW 600-1500)",
                    "AMP-derived (peptide 8-25 residues)",
                    "siderophore-conjugate (Trojan-horse entry)",
                    "GMP-friendly (≤2 chiral centers, ≤6 steps)",
                ],
                value="lead-like (MW≤500, logP≤4)",
                label="Constraint profile",
            )
            run_btn = gr.Button("🧬 Design candidate", variant="primary")

        with gr.Column(scale=2):
            output = gr.Markdown(label="Designer output", value="*Click 'Design candidate' to begin.*")

    with gr.Accordion("Inference prompt sent to Lysos-RL", open=False):
        prompt_view = gr.Textbox(label="Prompt", lines=10)

    gr.Markdown("""
    ---
    
    ### Architecture (full system)
    
    **4 first-class agents**: Designer, Critic, Strategist, Editor + 9 scoped sub-agents (Red-Team, Resistance-Forecaster, Manufacturing-Eval, Clinical-Positioning, Literature-Grounding, Confidence-Calibrator, Novelty-Checker, Editor, Critic-Novelty)
    
    **25-tool Workbench**: amr (5) + scoring (6) + structural (3) + generative (4) + knowledge (5) + sandbox (2)
    
    **12-component GRPO reward**: validity, structural_alerts, predicted_mic, drug_likeness_qed, synthesizability, hemolysis_safety, novelty, embedding_novelty, boltz2_pose_conf, spectrum_breadth, resistance_robustness, pareto_entry
    
    **Eval harness**: chem_validity, novelty_tanimoto, mic_rmse_holdout, admet_pass_rate, tool_call_accuracy, refusal_robustness, reasoning_faithfulness
    
    [GitHub](https://github.com/Rahul-Rajpurohitk/lysos) · [Methods Paper](https://github.com/Rahul-Rajpurohitk/lysos/blob/main/docs/methods_paper.md) · [Datasheet](https://github.com/Rahul-Rajpurohitk/lysos/blob/main/docs/datasheet.md)
    
    *Out-of-scope use prohibited: cannot design Chemical weapons, controlled substances, or biological agents.*
    """)

    run_btn.click(fn=design_candidate, inputs=[pathogen, constraint], outputs=[output, prompt_view])


if __name__ == "__main__":
    demo.launch()

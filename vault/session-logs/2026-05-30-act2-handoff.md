# Act II — session handoff (2026-05-30, context ran out)

## Verified shipped + pushed earlier this session (all green, tested)
1. **Act II master plan** — vault/plans/active/2026-05-30-act2-master-plan.md
2. **Real ADMET-AI model** — model_services/admet_service.py (:7920) +
   chem_admet.py real-model bridge w/ provenance. 104 endpoints. Fixed
   negative-half-life via approved-percentile scoring. source=admet-ai.
3. **Campaign backbone** — campaign.py, full CRUD + lifecycle. Mounted.
4. **Real generation (Service 4 backend)** — chem_generate.py, BRICS engine
   (GenMol-on-MI300X contract ready). Mounted /workbench/chem/generate.
5. **Autonomous campaign harness** — campaign_harness.py, campaign_run
   workflow (11th). VERIFIED: 2 full MRSA campaigns → CHAMPION, 3/3 gates.
All of the above: 43/43 tests pass, committed, pushed to origin/main.
Last verified commit: 71a4dc5.

## UNVERIFIED (context/output died mid-step — CHECK THESE FIRST next session)
- **GeneratorCard.tsx** written (workspace/web/.../playground/GeneratorCard.tsx)
  — complete, standalone, NOT yet wired into WorkbenchV3 card list.
- WorkbenchV3.tsx: deduped 3 duplicated imports (SynthesisRouteCard,
  ADMETObservatoryCard, IPSentinelCard were each imported twice at L48-53).
  The GeneratorCard import was ADDED then REVERTED (to keep tsc green since
  the card body wasn't wired). So GeneratorCard is currently an unwired file.
- A commit "GeneratorCard.tsx — Service 4 frontend..." was ATTEMPTED but I
  could not confirm it landed (bash output suppressed). **Run `git status`
  + `git log -3` first to see if it committed.**

## DO FIRST next session
1. `git status` / `git log --oneline -5` — confirm GeneratorCard commit state.
2. `cd workspace/web && npx tsc --noEmit` — confirm frontend is green
   (the import dedupe + revert should leave it clean).
3. If clean: wire GeneratorCard into WorkbenchV3 Chemistry group:
   - add `import { GeneratorCard } from "./playground/GeneratorCard";`
   - add card object near the synthesis card (id "synthesis"), e.g.:
     `{ id: "generator", title: "Generator · de-novo + lead-opt", size: 2,
        expandedH: 480, body: <GeneratorCard apiBase={apiBase}
        sessionId={activeChatId} smiles={currentSmiles}
        pathogen={selectedPathogen}
        onLoad={(smi)=>loadSmilesIntoCanvas(smi,{createdBy:"user",
        parentId:null,logLabel:"[generator · apply]"})} /> }`
   - tsc, commit, push.

## Remaining Act II backlog (tasks #198-204)
- GenMol real service on MI300X (BRICS is the stand-in now)
- Chemprop antibacterial-activity head + SyntheMol synthesizability
- Peptide (AMP) modality — ApexAmphion/LLAMP + Amphorium 2.1M library
- Campaign board card (frontend for campaign.py) + autonomous-run viz
- Productization: design system + global card states (useArtifact hook)
- Trust layer: retrospective validation enrichment curve + MI300X benchmark
- Fresh Vercel deploy (atikan.vercel.app = DEPLOYMENT_NOT_FOUND) for the
  live-link submission requirement.

## Services running locally
- backend uvicorn :7860 (.venv-cli)
- ADMET model service :7920 (.venv-models) — scripts/run_admet_service.sh
- frontend vite :5173

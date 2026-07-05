# Phase 1 -> Phase 2.1 Merge Readiness Report

Status: Phase 2.1.1 evidence closure in progress. This report is no-model/readiness only; it does not authorize clean project regression or live chapter generation.

## Scope Guard
- Did not start backend/frontend dev server, runner, or page.goto.
- Did not run formal chapter generation/finalization chain.
- Did not write real DB data or execute migrations/cleanup.
- Did not restore LongformBrowser or run #98/#99/#50.
- Did not save model output as project正文、小纲、beat plan, or DB state.
- Did not enter Phase 3 provider/model adapter work.
- Did not enter clean project/live canary.

## Change Groups

### Platform State / Context Contract
- `frontend/src/utils/contextPackV2.js`
- `frontend/src/utils/contextBuilder.js`
- `frontend/src/prompts/chapter.js`
- `frontend/src/prompts/chapterDraftPrompt.js`
- `frontend/src/stores/writerStore.js`
- `frontend/src/stores/memoryStore.js`
- `frontend/src/stores/settingStore.js`
- `frontend/src/stores/volumeStore.js`
- `frontend/src/views/WriterView.vue`
- `frontend/src/api/db/client.js`

Purpose: split creative context into state authority, creative stage contract, narrative voice contract, and guard-only snapshots; keep guard/roadmap material out of prompt-facing creative projection.

### Provenance / Health Check / Finalization Protocol
- `backend/routers/provenance_support.py`
- `backend/routers/chapters.py`
- `backend/routers/helpers.py`
- `backend/routers/novel.py`
- `backend/routers/settings_library.py`
- `backend/routers/volumes.py`
- `backend/migrations/`
- `frontend/src/utils/stateProvenance.js`
- `frontend/src/utils/projectHealthCheck.js`
- `frontend/src/utils/finalizationProtocol.js`
- `frontend/src/utils/finalizationGuard.js`
- `tmp/test_state_provenance_phase1_2_contract.mjs`
- `tmp/test_finalization_guard.mjs`
- `tmp/test_finalization_postprocess_contract.mjs`
- `tmp/test_finalization_retry_contract.mjs`
- `tmp/test_finalize_endpoint_contract.mjs`

Purpose: persist/audit provenance metadata, expose deterministic project health checks, and represent finalization staged/validated/committed/failed-after-commit states without touching real project DB data.

### Writing Quality Architecture
- `frontend/src/utils/narrativeVoiceContract.js`
- `frontend/src/utils/sceneExecutionContract.js`
- `frontend/src/utils/literaryQualityEvaluator.js`
- `frontend/src/prompts/audit.js`
- `tmp/run_narrative_voice_phase2_model_validation.mjs`
- `tmp/test_narrative_voice_scene_contract_phase2.mjs`
- `tmp/test_narrative_voice_phase2_evidence_contract.mjs`

Purpose: move正文 generation preparation toward NarrativeVoiceContract and SceneExecutionCard, reduce thick rule-list pressure, and add deterministic quality/evidence contracts for style, stage, fact, and guard boundaries.

### Offline Regression / QA Reports
- `tmp/run_offline_narrative_quality_regression_phase2_1.mjs`
- `tmp/test_offline_narrative_quality_regression_phase2_1.mjs`
- `tmp/test_context_pack_v2_phase1_contract.mjs`
- `tmp/test_quality_chain_contract.mjs`
- `tmp/test_quality_first_generation_contract.mjs`
- `tmp/test_prompt_boundary_modules.mjs`
- `tmp/test_writer_store_prompt_boundaries.mjs`
- `tmp/test_writing_style_standards_contract.mjs`
- `tmp/test_ai_trace_review_prompt.mjs`
- `tmp/test_audit_ai_trace_contract.mjs`
- `tmp/realistic-flow-qa/contextpack-v2-phase1-report.md`
- `tmp/realistic-flow-qa/state-provenance-phase1-2-report.md`
- `tmp/realistic-flow-qa/narrative-voice-scene-contract-phase2-report.md`
- `tmp/realistic-flow-qa/narrative-voice-phase2-model-validation.json`
- `tmp/realistic-flow-qa/offline-narrative-quality-regression-phase2-1-report.md`
- `tmp/realistic-flow-qa/offline-narrative-quality-regression-phase2-1.json`

Purpose: provide no-model contract coverage, offline model QA summaries, strict JSON/report alignment, stale evidence rejection, and merge/readiness audit trail.

## Phase 2.1 Evidence Summary
- Fixtures: 6 synthetic short scenes.
- Current JSON/report summary: `oldPromptPasses=4`, `newPromptPasses=6`, `oldPromptFutureLeaks=0`, `newPromptFutureLeaks=0`, `newPromptRegressions=0`, `averageOldScore=93`, `averageNewScore=100`, `newPromptOverallNonRegression=true`.
- `assertRegressionReportMatchesJson` parses summary lines, fixture coverage rows, A/B result rows, and key-value cells; duplicate stale+correct values are rejected.
- Future leak checks are deterministic exact secret + fixture critical risk-term evidence. They are not a claim of full semantic leak detection.
- QA JSON stores structured metrics and short excerpts only; it does not store full model outputs or project-state artifacts.

## Verification Commands
- `node tmp\test_context_pack_v2_phase1_contract.mjs`: passed
- `node tmp\test_state_provenance_phase1_2_contract.mjs`: passed
- `node tmp\test_narrative_voice_scene_contract_phase2.mjs`: passed
- `node tmp\test_narrative_voice_phase2_evidence_contract.mjs`: passed
- `node tmp\test_offline_narrative_quality_regression_phase2_1.mjs`: passed
- `node tmp\test_quality_chain_contract.mjs`: passed
- `node tmp\test_quality_first_generation_contract.mjs`: passed
- `node tmp\test_prompt_boundary_modules.mjs`: passed
- `node tmp\test_writer_store_prompt_boundaries.mjs`: passed
- `node tmp\test_writing_style_standards_contract.mjs`: passed
- `node tmp\test_ai_trace_review_prompt.mjs`: passed
- `node tmp\test_audit_ai_trace_contract.mjs`: passed
- Strict JSON/report alignment probe: passed
- `npm --prefix frontend run build`: passed with existing Vite `INEFFECTIVE_DYNAMIC_IMPORT` warning only

## Review Gate
- Old Phase 2.1 review subthread `019f2e9d-8f4d-7553-8489-69389a6e4c91` found an Important row-level stale-value matcher gap.
- That gap was fixed locally by exact coverage/result row parsing and duplicate key rejection.
- New Phase 2.1.1 fresh review subthread `019f2eaf-9375-7be1-b705-368878a573b4` found no Critical and no Important issues in the current final state.
- The new review independently verified strict JSON/report alignment, duplicate row/key rejection, excerpt-only QA persistence, future leak wording, and scope boundaries. Its only Minor was the old review ID in the Phase 2.1 report, now corrected.

## Remaining Non-Merge / Non-Live Risks
- Real DB migration files remain dry-run/design artifacts; no real migration has been executed.
- No real project cleanup or legacy data repair has been performed.
- No clean project regression has been run.
- No live chapter generation/finalization chain has been run.
- Offline model QA uses fallback DeepSeek credentials because 联通云 DeepSeek V4 Flash credentials are not exposed in this thread.
- Vite build still reports the existing `INEFFECTIVE_DYNAMIC_IMPORT` warning for `src/stores/writerStore.js`.

## Suggested Next Entry
Recommended next stage for product control: `Clean Synthetic Project Regression / No-Live End-to-End Readiness`.

Do not start that stage from this thread without a new master instruction.

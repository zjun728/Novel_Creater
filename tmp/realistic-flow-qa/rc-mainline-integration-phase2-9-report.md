# RC Mainline Integration Phase 2.9 Report

Status: integration dry-run in progress on a local branch. This phase integrates the validated RC commit onto the current mainline baseline without touching real DBs, real projects, live generation, push, or PR.

## Scope Guard
- Did not start backend/frontend dev server, runner, or page.goto.
- Did not run formal chapter generation or finalization chain.
- Did not connect to or write any real DB; no real migration, cleanup, quarantine, or purge executed.
- Did not touch real project data, restore LongformBrowser, or run #98/#99/#50.
- Did not save model output as project body, outline, beat plan, or DB state.
- Did not enter real clean project regression, live canary, or Phase 3 provider/model adapter work.
- Did not push or create a PR.

## Branch And Divergence
- baseBranch=codex/story-block-v1
- baseHead=ccf3d3a
- integrationBranch=codex/novel-creater-platform-rc-integration
- sourceRcBranch=codex/novel-creater-platform-rc
- sourceRcCommit=e584526
- mergeBase=5535098d8d12bfad8cf1d0a7b14f2e9161dadd5a

Left/right summary before integration:

| side | commit | subject |
| --- | --- | --- |
| RC only | e584526 | feat(platform): add ContextPack v2 RC foundation |
| mainline only | ccf3d3a | chore: consolidate architecture and qa contracts |
| mainline only | ed9033d | 1 |

## Apply Strategy
- command=git cherry-pick --no-commit e584526
- result=conflicts_resolved_minimally
- strategy=preserve mainline writer-flow architecture and QA script consolidation while layering RC ContextPack/provenance/finalization/schema/quality foundation.

## Conflict Summary
| file | resolution |
| --- | --- |
| .gitignore | Unioned mainline runtime artifact ignores with RC generated temp store ignores. |
| backend/main.py | Kept mainline story_blocks/ai_proxy/experience_cards routers and added RC project_state router. |
| backend/routers/chapters.py | Preserved story block beat-plan fields and added provenance metadata persistence. |
| backend/routers/helpers.py | Unioned mainline story-block/QA metadata fields with RC provenance/result fields. |
| backend/routers/novel.py | Kept mainline plot-thread sync/status behavior and added RC provenance filtering/persistence. |
| frontend/src/prompts/chapter.js | Kept mainline quality brief and added RC narrative voice / scene execution boundaries. |
| frontend/src/prompts/chapterDraftPrompt.js | Kept mainline humanity/style/story block prompt and added RC Scene Card / NarrativeVoice boundary wording. |
| frontend/src/stores/memoryStore.js | Preserved skipPlotThreadSync behavior while wrapping persisted canon facts with finalization provenance. |
| frontend/src/stores/writerStore.js | Preserved mainline quality imports and added RC beat-plan provenance metadata. |
| frontend/src/utils/contextBuilder.js | Preserved mainline context shaping and added ContextPack v2 output with null-safe context options. |
| frontend/src/utils/finalizationGuard.js | Unioned mainline post-finalize failure classification/retry helpers with RC durable marker provenance. |
| frontend/src/views/WriterView.vue | Preserved mainline runFinalizeChapterCommand flow and added durable finalization marker load/readiness plumbing. |
| tmp/test_finalization_postprocess_contract.mjs | Updated to assert both mainline command architecture and RC durable first-failure persistence. |
| tmp/test_finalization_retry_contract.mjs | Updated to assert mainline retry action gating and RC durable marker closeout. |

Additional integration adjustments:
- frontend/src/application/writer-flow/finalization-command.js now passes finalization provenance through finalizeVersion/processChapterFinalization and durable failure marker hooks.
- tmp/test_writer_flow_finalization_command_contract.mjs now expects finalization provenance and durable marker callbacks.
- tmp/run_platform_rc_preflight_phase2_7.mjs replaces RC parent-only obsolete QA script labels with current mainline QA contract scripts.
- tmp/test_platform_rc_preflight_phase2_7.mjs asserts the updated current-mainline preflight label set.

## Verification Results
| command | result |
| --- | --- |
| node tmp/test_finalization_postprocess_contract.mjs | passed |
| node tmp/test_finalization_retry_contract.mjs | passed |
| node tmp/test_writer_flow_finalization_command_contract.mjs | passed |
| node tmp/test_writing_standard_prompt_boundary_contract.mjs | passed |
| node tmp/test_draft_prompt_humanity_brief_contract.mjs | passed |
| node tmp/test_chase_variety_prompt_contract.mjs | passed |
| node tmp/test_formal_writing_standard_closure_contract.mjs | passed |
| node tmp/test_writer_flow_boundary_audit_contract.mjs | passed |
| node tmp/test_context_pack_v2_phase1_contract.mjs | passed after adding validated-marker and no-id rejected-source regressions |
| node tmp/run_platform_rc_preflight_phase2_7.mjs | passed; refreshed JSON/report |
| node tmp/test_platform_rc_preflight_phase2_7.mjs | passed |
| node tmp/test_offline_narrative_quality_regression_phase2_1.mjs | passed |
| node tmp/test_clean_synthetic_project_regression_phase2_2.mjs | passed |
| node tmp/test_ephemeral_persistence_regression_phase2_3.mjs | passed |
| node tmp/test_production_schema_adapter_phase2_5.mjs | passed |
| node tmp/test_idempotent_migration_inspector_phase2_6.mjs | passed |
| python -m compileall backend | passed |
| git diff --check | passed with CRLF normalization warnings only |
| npm --prefix frontend run build | passed with existing Vite dynamic-import/chunk-size warnings |

## Phase 2.7 Evidence Snapshot
- preflight.total=19
- preflight.failed=0
- alignment.failed=0
- boundaryClean=true
- manifest.longTermCode.count=9
- manifest.backendMigrationSchema.count=4
- manifest.frontendContextProvenanceFinalization.count=12
- manifest.writingQuality.count=6
- manifest.testsRunners.count=22
- manifest.qaReports.count=19
- manifest.generatedTempStores.count=3

## Staged Review
- initialReview.threadId=019f2fe3-dca3-7b03-afae-d488f9a9c7ac
- initialReview.critical=0
- initialReview.important=2
- initialReview.minor=0
- initialReview.result=with_fixes
- initialReviewFixes=validated finalization markers now block ContextPack health; rejected-source targets are provenance/id safe and no longer carry source name/content into stateAuthority or creative context.
- finalReview.status=ready_to_commit
- finalReview.threadId=019f2fed-010f-7a30-b7a9-37f07f73dcf6
- finalReview.critical=0
- finalReview.important=0
- finalReview.minor=1
- finalReview.result=Ready to commit; remaining Minor notes that story-block health targets could later use the same safe id/provenance target helper, but no creative prompt leakage or Critical/Important issue remains.

## Remaining No-Go Conditions
- Real DB migration still requires explicit approval, backup/restore verification, target DB identity, inspector dry-run diff, and rollback/restore plan.
- Real project cleanup/quarantine/purge has not run.
- Real clean project regression has not run.
- Live canary has not run.
- Phase 3 provider/model adapter remains out of scope.
- No push or PR should happen in this phase.

# Production Schema Adapter Phase 2.5 Report

Status: completed disposable schema/adapter dry-run. This is not a real DB migration, real project cleanup, clean regression, canary, or live chapter run.

## Scope Guard
- Did not start backend/frontend dev server, runner, or page.goto.
- Did not run formal chapter generation/finalization chain.
- Did not connect to or write a real DB; no real migration/cleanup/quarantine/purge executed.
- Did not restore LongformBrowser or run #98/#99/#50.
- Did not save model output as project正文、小纲、beat plan, or DB state.
- Did not enter Phase 3 provider/model adapter work or real clean project/live canary.
- Did not create commit/PR.

## Summary
schema.finalizationMarkersClosed=true
schema.projectHealthChecksClosed=true
adapter.backendClosed=true
adapter.frontendClosed=true
dryRun.schemaParserPassed=true
dryRun.migrationIdempotenceReady=false
dryRun.idempotenceUnavailableReason=Existing provenance ALTER TABLE ADD COLUMN and CREATE INDEX statements are draft-only; production apply must use a schema inspector/migration runner that skips existing columns/indexes or a backup-verified one-shot migration.
dryRun.rollbackPassed=true
readiness.halfSuccessBlocked=true
creative.boundaryClean=true

## Schema Closure
| table | productionCreate | provenanceFields | indexes | commitStatusConstraint |
| --- | --- | --- | --- | --- |
| finalization_markers | productionCreate=true; provenanceFields=provenance,source_chapter_num,source_version_id,run_id,finalization_id,commit_status; indexes=3; commitStatusConstraint=true |
| project_health_checks | productionCreate=true; provenanceFields=provenance,source_chapter_num,source_version_id,run_id,finalization_id,commit_status; indexes=3; commitStatusConstraint=true |

## Existing Provenance Coverage
| table | allProvenanceFields | fields |
| --- | --- | --- |
| chapter_versions | allProvenanceFields=true; fields=provenance,source_chapter_num,source_version_id,run_id,finalization_id,commit_status |
| canon_facts | allProvenanceFields=true; fields=provenance,source_chapter_num,source_version_id,run_id,finalization_id,commit_status |
| setting_entities | allProvenanceFields=true; fields=provenance,source_chapter_num,source_version_id,run_id,finalization_id,commit_status |
| setting_relations | allProvenanceFields=true; fields=provenance,source_chapter_num,source_version_id,run_id,finalization_id,commit_status |
| setting_change_events | allProvenanceFields=true; fields=provenance,source_chapter_num,source_version_id,run_id,finalization_id,commit_status |
| project_volumes | allProvenanceFields=true; fields=provenance,source_chapter_num,source_version_id,run_id,finalization_id,commit_status |
| chapter_beat_plans | allProvenanceFields=true; fields=provenance,source_chapter_num,source_version_id,run_id,finalization_id,commit_status |

## Adapter Closure
backend.path=C:\Users\zhangjun\.codex\worktrees\3e01\Novel_Creater\backend\routers\project_state.py
backend.finalizationMarkerRoutes=true
backend.projectHealthCheckRoutes=true
backend.idempotentMarkerUpsert=true
backend.idempotentHealthUpsert=true
frontend.path=C:\Users\zhangjun\.codex\worktrees\3e01\Novel_Creater\frontend\src\api\db\client.js
frontend.finalizationMarkerClient=true
frontend.projectHealthCheckClient=true
frontend.readinessDurableMarkerLoad=true
frontend.contextDurableMarkerInjection=true

## Disposable Migration / Rollback
disposable.storePath=C:\Users\zhangjun\.codex\worktrees\3e01\Novel_Creater\tmp\production-schema-adapter-phase2-5\disposable-store.json
disposable.syntheticOnly=true
disposable.realDbConnection=false
rollback.supported=true
rollback.executedAgainstRealDb=false
rollback.steps=DROP TABLE IF EXISTS project_health_checks; | DROP TABLE IF EXISTS finalization_markers;

## Integration Results
marker.idempotent=true
marker.readBackCount=1
marker.commitStatus=failed_after_chapter_commit
healthCheck.idempotent=true
healthCheck.readBackCount=1
healthCheck.creativeContextContainsHealthJson=false
healthCheck.entersStateAuthority=false
readiness.halfSuccessBlockingIssueCodes=finalization_pending
context.unknownDegradedExcludedFromCreative=true
context.savedBeatConflictFinalFactWins=true
context.guardSnapshotLeakBlocked=true
rollback.removedCollections=true
rollback.postRollbackReadBlocked=true

## Migration Idempotence
idempotence.newTablesRepeatSafe=true
idempotence.existingAlterRepeatSafe=false
idempotence.productionApplyRequiresInspector=true
- The production table additions are repeat-safe through `CREATE TABLE IF NOT EXISTS`.
- Existing table provenance columns/indexes remain plain draft DDL; real apply must use schema inspection or a one-shot backup-verified migration.

## Temp Artifact Policy
- Keep `tmp/ephemeral-persistence-phase2-3/project-store.json` through this audit if reviewers need Phase 2.3 readback evidence.
- Before production merge, choose one policy: retain under explicit QA fixture path, add generated temp-store ignore, or remove after Phase 2.5 JSON/report evidence is accepted.
- This Phase 2.5 report and JSON provide reproducible schema/adapter evidence without treating temp stores as production project data.

## Remaining Risks
- Real DB migration execution remains untested.
- Real project cleanup/quarantine/purge remains unrun.
- Real clean project regression and live canary remain unrun.
- Production rollback must require backup/restore approval before any real migration run.
- Project health-check persistence is an audit artifact; product must decide retention/window before live rollout.
- Durable-marker retry/recovery UX remains local-marker oriented; readiness blocking is closed, but product should decide recovery handling before live rollout.

## Go / No-Go Before Real Clean Project Regression
- Go only after disposable migration evidence, fresh review, backup/rollback plan, and temp artifact policy are accepted.
- No-go if any real DB migration/cleanup is attempted without backup, disposable apply evidence, and rollback plan.
- No-go if persisted health-check rows or finalization markers are ever mapped into `stateAuthority` facts or creative prompt content.

## Fresh Review
review.threadId=019f2f18-b10f-7332-991b-f5efd412f137
review.critical=0
review.important=0
review.conclusion=Ready

## Verification
verification.commandCount=5
| command | result |
| --- | --- |
| node tmp\test_production_schema_adapter_phase2_5.mjs | passed |
| Phase 2.5 JSON/report alignment probe | passed |
| python -m py_compile backend\main.py backend\routers\project_state.py backend\routers\helpers.py backend\routers\provenance_support.py | passed |
| git diff --check | passed with LF-to-CRLF working-copy warnings only |
| npm --prefix frontend run build | passed with existing Vite INEFFECTIVE_DYNAMIC_IMPORT warning |

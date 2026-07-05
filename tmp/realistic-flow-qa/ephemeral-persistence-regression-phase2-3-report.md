# Ephemeral Persistence Regression Phase 2.3 Report

Status: completed ephemeral persistence dry-run. 临时环境通过不等于真实项目迁移/清理完成。

## Scope Guard
- Did not start backend/frontend dev server, runner, or page.goto.
- Did not run formal chapter generation/finalization chain.
- Did not connect to or write a real DB; no real migration/cleanup executed.
- Did not restore LongformBrowser or run #98/#99/#50.
- Did not save model output as project正文、小纲、beat plan, or DB state.
- Did not enter Phase 3 provider/model adapter work or real clean project/live canary.

## Persistence Strategy
persistence.strategy=ephemeral-json-store
persistence.storePath=C:\Users\zhangjun\.codex\worktrees\3e01\Novel_Creater\tmp\ephemeral-persistence-phase2-3\project-store.json
persistence.touchesRealDb=false
persistence.isolationReason=Store path is under tmp/ephemeral-persistence-phase2-3 and contains synthetic fixture data only; no database driver or production DSN is used.

## Schema Dry-Run
schema.mode=migration-sql-parse-dry-run-plus-json-store-schema
schema.executedAgainstRealDb=false
schema.adapterGaps=finalization_markers,project_health_checks

## Write/Read Coverage
| collection | wrote | read | provenanceComplete | strategy |
| --- | --- | --- | --- | --- |
| chapter_versions | wrote=28; read=28; provenanceComplete=true; strategy=chapter_versions |
| canon_facts | wrote=6; read=6; provenanceComplete=true; strategy=canon_facts |
| setting_entities | wrote=7; read=7; provenanceComplete=true; strategy=setting_entities |
| setting_relations | wrote=2; read=2; provenanceComplete=true; strategy=setting_relations |
| setting_change_events | wrote=3; read=3; provenanceComplete=true; strategy=setting_change_events |
| project_volumes | wrote=6; read=6; provenanceComplete=true; strategy=project_volumes |
| chapter_beat_plans | wrote=2; read=2; provenanceComplete=true; strategy=chapter_beat_plans |
| finalization_markers | wrote=1; read=1; provenanceComplete=true; strategy=finalization_markers |
| project_health_checks | wrote=2; read=2; provenanceComplete=true; strategy=project_health_checks |

## Summary
ephemeral.healthyReady=true
ephemeral.pollutedBlocked=true
ephemeral.savedBeatConflictResolved=true
ephemeral.stageHandoffFromFinalState=true
ephemeral.finalizationHalfSuccessBlocked=true
ephemeral.narrativeVoiceSafe=true

## Scenario Results
| scenario | evidence |
| --- | --- |
| healthy | ready=true; healthBlocked=false; creativeContextContainsFutureRoadmap=false; trustedFactCount=2 |
| polluted | ready=false; healthBlocked=true; issueCodes=finalization_pending,untrusted_source,empty_chapter_authority,saved_beat_plan_conflict,guard_snapshot_in_creative_context; blockingIssueCount=8 |
| savedBeatConflict | finalFactWins=true; beatPlanAuthority=plan_evidence_only; creativeContextContainsConflictingBeat=false |
| stageHandoff | sourceType=final_state; canRebuildFromFinalFacts=true; usesFailedCandidate=false; rebuildFinalChapterCount=14 |
| finalization | ready=false; markerStatus=failed_after_chapter_commit; blockingIssueCodes=finalization_pending,untrusted_source,empty_chapter_authority,guard_snapshot_in_creative_context |
| narrativeVoice | voiceScope=expression_only; voiceLintOk=true; scenePromptContainsFutureRoadmap=false; factOrStageOverridePresent=false; qualityPassed=true |

## Cleanup / Projection Dry-Run
cleanup.mode=dry-run-only
cleanup.writesRealData=false
cleanup.proposedActions=hold_generation,quarantine,quarantine,quarantine,quarantine,quarantine,quarantine,quarantine
cleanup.rejectedProjectionSources=2

## Evidence Contract
- JSON/report alignment parses single-value summary lines, coverage rows, scenario rows, and key-value cells; stale+correct duplicates are rejected.
- Migration SQL is parsed only; no real DB driver, DSN, migration runner, or production database connection is used.
- The temporary JSON store is synthetic and disposable; it is not a real project DB.

## Remaining Risks
- Real DB migration execution remains untested.
- Real project cleanup/quarantine/purge remains unrun.
- Real clean project regression and live canary remain unrun.

## Review
review.threadId=019f2ee1-40eb-78e0-9e48-ae2aaf7f9dc0
review.critical=0
review.important=0
review.conclusion=Ready

## Verification
verification.commandCount=4
| command | result |
| --- | --- |
| node tmp\test_ephemeral_persistence_regression_phase2_3.mjs | passed |
| node Phase1-Phase2.3 no-model contract suite | passed |
| node Phase2.3 json/report alignment probe | passed |
| npm --prefix frontend run build | passed with existing Vite INEFFECTIVE_DYNAMIC_IMPORT warning |

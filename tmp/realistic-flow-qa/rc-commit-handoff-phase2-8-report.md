# RC Commit Handoff Phase 2.8 Report

Status: precommit handoff package prepared for a local RC commit. This report is part of the staged commit, so the immutable final commit hash is recorded by post-commit sanity and the final handoff response rather than embedded here.

## Branch / Base
- branch: codex/novel-creater-platform-rc
- preCommitHead: 5535098
- intendedCommitMessage: feat(platform): add ContextPack v2 RC foundation

## Scope Guard
- Did not start backend/frontend dev server, runner, or page.goto.
- Did not run formal chapter generation/finalization chain.
- Did not connect to or write a real DB; no real migration/cleanup/quarantine/purge executed.
- Did not touch real project data, restore LongformBrowser, or run #98/#99/#50.
- Did not save model output as project正文、小纲、beat plan, or DB state.
- Did not enter real clean project regression/live canary or Phase 3 provider/model adapter work.
- Did not push and did not create a PR.

## Precommit Verification
| command | result |
| --- | --- |
| node tmp\run_platform_rc_preflight_phase2_7.mjs | passed; regenerated Phase 2.7 JSON/report |
| node tmp\test_platform_rc_preflight_phase2_7.mjs | passed |
| Phase 2.1/2.2/2.3/2.5/2.6/2.7 JSON/report alignment probe | passed |
| python -m py_compile backend\main.py backend\routers\chapters.py backend\routers\helpers.py backend\routers\novel.py backend\routers\settings_library.py backend\routers\volumes.py backend\routers\provenance_support.py backend\routers\project_state.py | passed |
| git diff --check | passed with CRLF normalization warnings only |
| npm --prefix frontend run build | passed with existing Vite INEFFECTIVE_DYNAMIC_IMPORT warning |

## Staged File Groups
Final staged count including this handoff report: 70 files.

| group | count | notes |
| --- | ---: | --- |
| artifact_policy | 1 | `.gitignore` ignores generated temp stores only. |
| backend_provenance_routes | 6 | Existing backend route integration for provenance/state plumbing. |
| backend_migration_schema_adapter | 4 | Migration draft/rollback plus `project_state` and provenance helpers. |
| frontend_lockfile_build_readiness | 1 | Lockfile metadata from validated build readiness. |
| frontend_state_finalization_integration | 6 | API/store/view integration, durable marker retry and context readiness. |
| frontend_prompt_writing_quality | 3 | Prompt boundary and writing quality contract integration. |
| frontend_context_provenance_quality_utils | 9 | ContextPack, provenance, health check, scene card, voice, evaluator utilities. |
| qa_evidence_reports | 19 | Phase 1 through Phase 2.8 QA evidence and RC reports/JSON. |
| tests_runners | 21 | Deterministic no-model runners and contract tests. |

## Artifact Policy
- Retain `tmp/realistic-flow-qa/*.md` and `tmp/realistic-flow-qa/*.json` as QA evidence.
- Exclude generated disposable stores from production merge: `tmp/ephemeral-persistence-phase2-3/`, `tmp/production-schema-adapter-phase2-5/`, `tmp/idempotent-migration-inspector-phase2-6/`.
- Do not stage `frontend/dist/`, `frontend/node_modules/`, `backend/__pycache__/`, or `backend/routers/__pycache__/`.

## Staged Review
- freshStagedDiffReview: required before commit.
- Critical/Important findings must be fixed before committing.

## Remaining No-Go
- Real DB migration remains no-go without explicit approval, target DB identity, backup/restore verification, inspector dry-run diff, and rollback/restore plan.
- Real project cleanup/quarantine/purge has not run.
- Real clean project regression and live canary have not run.
- Phase 3 provider/model adapter remains out of scope.
- No push or PR in this phase.

# Phase 4C Candidate Load and Read-only Compare Implementation Plan

> Execute in the dedicated
> `D:\CodexData\.codex\worktrees\phase3d-boundary-acceptance\Novel_Creater`
> worktree. Use TDD, one focused gate per task, serial specification then quality review, and
> the lean gate policy. Do not call a real Provider or product database and do not push.

**Goal:** Load an immutable Candidate into WorkingDraft with append-only recovery, and compare
exactly two Candidates through visible read-only UI without fusion or new state machinery.

**Design:**
`docs/superpowers/specs/2026-08-09-phase4c-candidate-load-compare-design.md`

## Task 1: Admit Candidate-sourced recovery rows

**Files:**

- Modify: `backend/schema/40_drafts.sql`
- Modify: `backend/schema_version.py`
- Modify: `backend/repositories/chapter_sessions.py`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_initialize_database.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_chapter_session_repository.py`

1. Add failing schema/repository tests for nullable mutually exclusive operation/Candidate
   recovery sources and `candidate_load`.
2. Run only those tests and confirm RED.
3. Move the existing Candidate create block before recovery, then add `source_candidate_id`,
   source CHECK/FK, v1.11, and closed repository serialization without `ALTER TABLE`.
4. Rerun focused tests, `py_compile`, and `git diff --check`; review and commit.

## Task 2: Implement atomic Candidate load

**Files:**

- Modify: `backend/domain/drafts.py`
- Modify: `backend/repositories/chapter_sessions.py`
- Modify: `backend/services/chapter_sessions.py`
- Modify: `backend/tests/unit/test_chapter_session_service.py`
- Modify: `backend/tests/unit/test_chapter_session_repository.py`
- Modify: `backend/tests/integration/test_draft_operation_integrity.py`

1. Add failing service tests for success, immutable Candidate, stale Candidate allowed, CAS,
   cross-owner/missing/corrupt Candidate, active operation, non-drafting session, transaction
   rollback, exact source payload, and two recovery rows.
2. Add one affected MySQL integrity test proving Candidate immutability and recovery FKs/CHECK.
3. Implement `LoadDraftCandidate`, exact Candidate lookup, locked transaction, hash validation,
   before/update/after writes, and `created_at` public view.
4. Run focused unit tests; leave the MySQL test for the serial slice gate; review and commit.

## Task 3: Expose the strict load route

**Files:**

- Modify: `backend/routers/chapter_sessions.py`
- Modify: `backend/tests/api/test_chapter_session_routes.py`

1. Add RED API tests for the exact route/body, full workspace response, Candidate `createdAt`,
   cross-id behavior, unknown fields, and fixed public errors.
2. Implement the strict DTO and route using the existing service/error map.
3. Run the affected API/unit set, `py_compile`, and `git diff --check`; review and commit.

## Task 4: Add client, Store, and controller load coordination

**Files:**

- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/chapterSessionStore.js`
- Modify: `frontend/src/application/writer/chapterWriterController.js`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/chapterSessionStore.test.mjs`
- Modify: `frontend/tests/unit/chapterWriterController.test.mjs`

1. Add RED tests for exact transport, closed `createdAt`, Candidate/response calibration,
   autosave flush-before-load, action fencing, authoritative adoption, stale/error preservation,
   and local-undo invalidation.
2. Implement one `loadCandidate` method through each existing layer; do not add a second editor
   or direct network path.
3. Run the three affected Node files and `git diff --check`; review and commit.

## Task 5: Add the compact read-only Candidate workbench

**Files:**

- Modify: `frontend/src/views/ChapterWriterView.vue`
- Modify: `frontend/tests/unit/chapterWriterView.test.mjs`

1. Add RED source/behavior contracts for honest metadata, zero/one/two selection, third-choice
   disablement, exact-two comparison, read-only prose, and visible load action.
2. Implement ephemeral selected ids and a compact side-by-side comparison in the existing right
   Candidate card; keep the centre editor width and existing visual language.
3. Run the affected view/controller tests and production build; review and commit.

## Task 6: Add one no-Provider UI-only browser gate

**Files:**

- Create: `frontend/e2e/phase4c-candidate-workbench.spec.ts`
- Create: `frontend/e2e/playwright.phase4c.config.ts`
- Create: `frontend/e2e/run-phase4c.mjs`
- Create: `backend/scripts/prepare_phase4c_browser_db.py`
- Create: `scripts/tests/phase4CBrowserContract.test.mjs`
- Modify: `frontend/package.json`
- Modify: `package.json`
- Modify: `scripts/run-tests.mjs`

1. Add RED contract tests for one exact serial spec, disposable DB, three owned loopback services,
   deny proxy, zero Provider process/calls, visible UI only, safe diagnostics, and zero residue.
2. Implement one scenario: manually persist Candidate A, save it, persist Candidate B, save it,
   select both, observe two read-only panes, load A, and verify authoritative editor digest.
3. The runner must never log prose/Candidate bodies and must independently verify two immutable
   Candidates plus one Candidate-load before/after recovery pair.
4. Run contract tests, then one fresh browser scenario serially; review and commit.

## Task 7: Fresh slice acceptance

**Files:**

- Create: `docs/acceptance/2026-08-09-phase-4c-candidate-load-compare.md`
- Modify: `CURRENT_PROJECT_STATE.md`
- Modify: `PRODUCT_DEVELOPMENT_PLAN.md`
- Modify: `DEVELOPMENT_LOG.md`

1. Audit scope and owned resources; confirm no fusion, Provider operation, new table, product DB,
   Canon, finalization, or full-draft rewrite.
2. Run once, serially: affected Python/API/schema, affected Node, build, affected MySQL, and
   `npm run test:browser:phase4c`.
3. Perform one specification review to `0/0/0`, then one quality review to `0/0/0`; only
   Critical or active-path data-loss/security/deterministic failures expand the slice.
4. Record exact counts and resource ledger. State that full Phase/release regression is deferred
   to Phase 4 close under the lean gate policy.
5. Commit the acceptance/status documents. Do not push and do not claim fusion, full Phase 4,
   real-provider quality, product-database readiness, Canon, or finalization.

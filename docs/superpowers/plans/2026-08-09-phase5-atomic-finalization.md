# Phase 5 Lean Quality Review and Atomic Finalization Implementation Plan

> Execute only in
> `D:\CodexData\.codex\worktrees\phase3d-boundary-acceptance\Novel_Creater`.
> Use focused TDD, one implementer per file, serial specification then quality review, and the
> lean gate policy. Never call a real Provider or product database; do not push.

**Goal:** Turn one current immutable Candidate into one author-confirmed ChangeSet and commit
final prose, Canon, projections, and progress atomically.

**Design:**
`docs/superpowers/specs/2026-08-09-phase5-atomic-finalization-design.md`

## Phase 5A — Foundation

### Task 1: Replace finalization placeholders with the exact lean schema

**Files:** `backend/schema/40_drafts.sql`, `backend/schema_version.py`, schema manifest/version/
initializer tests.

1. RED: assert immutable quality report, one active attempt per session, immutable ChangeSet
   revisions, confirmed revision/hash pins, commit fingerprint, closed checks, and create-only
   bootstrap order.
2. GREEN: implement the minimum exact schema and version bump; no ALTER/migration/runtime DDL.
3. Run focused schema tests, `py_compile`, and `git diff --check`; review and commit.

### Task 2: Add closed finalization domain contracts

**Files:** create `backend/domain/finalization.py`; create focused domain tests.

1. RED: strict JSON, exact enums, canonical hashes, unique ids, evidence bounds, immutable values,
   exact revision/hash/idempotency validation, and unknown-key rejection.
2. GREEN: implement only the DTOs and pure validators required by the persisted payload.
3. Run focused domain tests and diff check; review and commit.

### Task 3: Add deterministic finalization prechecks and repository ownership

**Files:** create `backend/services/finalization_checks.py`,
`backend/repositories/finalization.py`; add focused unit/integration tests.

1. RED: empty/truncated body, Candidate hash, basis drift, session/operation state, deterministic
   local/reference copy, Canon conflict input, exact owner lookups, active slot, immutable revision,
   and rollback behavior.
2. GREEN: implement pure checks plus session-bound SQL methods; do not call a Provider.
3. Run affected unit and one disposable-MySQL integrity set; review and commit.

## Phase 5B — Review and author authority

### Task 4: Add narrow quality and extraction gateways

**Files:** create dedicated gateway/prompt modules and focused gateway tests.

1. RED: one bounded call per gateway, strict closed JSON, absolute timeout and cleanup, cancellation
   priority, fixed redacted errors, and no response/prose logging.
2. GREEN: reuse the existing OpenAI-compatible JSON transport and Provider policy; do not create a
   generic tool runner.
3. Run gateway tests without network; review and commit.

### Task 5: Prepare one finalization attempt

**Files:** create `backend/services/finalization.py`; extend finalization repository and tests.

1. RED: frozen authority, current Candidate only, active-operation fence, idempotency/fingerprint,
   quality failure as `quality_not_completed`, one extraction, invalid extraction failure, drift
   invalidation, and publication of revision 1.
2. GREEN: two short transactions around external calls; never hold SQL locks during Provider work.
3. Run focused unit/integration tests; review and commit.

### Task 6: Expose review, correction, and confirmation APIs

**Files:** create `backend/routers/finalization.py`; wire `backend/main.py`; add API tests.

1. RED: strict bodies, stable public errors, exact GET view, immutable correction revision, CAS,
   no Provider on correction/confirmation, and full-payload confirmation.
2. GREEN: implement the narrow route family and public serialization.
3. Run focused API/service tests and route inventory; review and commit.

## Phase 5C — Atomic commit and visible product loop

### Task 7: Commit Canon, projections, final prose, and progress atomically

**Files:** extend finalization/Canon/Planning repositories and service; add unit/integration tests.

1. RED: stable lock order, confirmed exact revision, all authority drift, hard Canon conflict,
   immutable Planning boundary, full rollback at each write, one final chapter, one Canon revision,
   projection agreement, session final, and idempotent replay/conflict.
2. GREEN: one transaction and no Provider call; reuse Canon conflict/projection functions instead
   of calling the existing transaction-owning Canon service.
3. Run focused unit plus disposable-MySQL atomicity tests; review and commit.

### Task 8: Add the compact Writer finalization panel

**Files:** existing API client/store/controller/Writer view and focused Node tests.

1. RED: selected current Candidate, prepare/reload, hard blocks, advice, full ChangeSet review,
   correction, overall confirmation, commit fencing, final read-only state, safe errors.
2. GREEN: one panel and one state-appropriate primary action; no new router/store/editor.
3. Run affected Node tests and build; review and commit.

### Task 9: UI-only fake-boundary browser acceptance

**Files:** one Phase 5 Playwright spec/config/runner, disposable DB preparer, runner contract tests.

1. RED: exact one browser scenario, injected fake quality/extraction providers, deny proxy,
   disposable MySQL, visible UI only, no body-bearing diagnostics, exact cleanup.
2. GREEN scenario: save Candidate, prepare, inspect report/ChangeSet, make one correction, confirm,
   commit, and verify final chapter/Canon/projection/session consistency.
3. Run one fresh browser scenario; review and commit.

### Task 10: Phase close

1. Run once serially: full Python, root/frontend Node, disposable-MySQL integration, build, Phase 5
   browser, and resource/DB residue audit.
2. Perform one specification review then one quality review. Only Critical or active-path
   data-loss/security/deterministic failures may expand Phase 5.
3. Update acceptance/current state/product plan/development log with exact counts and boundaries.
4. Commit, do not push, and state explicitly that real-provider quality, product database,
   export/backup, and content-quality acceptance remain unaccepted.

## Completion record

Tasks 1–10 are complete. The Phase gate snapshot is `8edc651`.

- Full unit: Python `3430 passed, 6 skipped`; root scripts Node `378/378`; frontend Node
  `710/710`.
- Disposable-MySQL integration: `370 passed`; `created=368 cleaned=368 remaining=0`.
- Build: `2969 modules transformed`; Phase 5 browser: `1/1 passed`.
- Owned process/temp/cache/artifact/test-database residue: `0`.
- Specification review and quality review: `0/0/0` and `0/0/0`.
- Real Provider calls `0`; Product DB reads/writes `0/0`; no push.

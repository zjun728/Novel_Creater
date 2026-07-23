# Phase 2D Creation Bible and Phase Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development`, `test-driven-development`,
> `requesting-code-review`, and `verification-before-completion`. Steps use
> checkbox syntax for tracking.

**Goal:** Deliver one formal creation-Bible workflow, one truthful Phase 2
preparation view, and one full Phase 2 browser acceptance path without touching
the product database, a real Provider, or a live ranking source.

**Architecture:** The server derives the current Bible basis from the active
seed selection and the confirmed creation/style contracts. One nullable
`active_slot` allows exactly one editable draft per project while retaining
confirmed and superseded draft rows. Confirmation atomically freezes an
immutable revision, advances the Bible head, and deactivates the draft. The
frontend has one canonical `/projects/:projectId/bible` route and `bibleStore`;
the old `WriterView/CreativeBible` path is deleted rather than kept as a second
runtime.

**Tech Stack:** FastAPI, Pydantic v2, async MySQL repositories, MySQL 8 schema
v1.4, Vue 3, Pinia, Naive UI, Node test runner, pytest, and Playwright.

**Depends on:** Phase 2A-2C on `main`, ending at `a4585ba`.

---

## Frozen Phase 2D decisions

- Development schema is changed directly. There is no migration or old-data
  compatibility path.
- A Bible basis freezes `selection_revision`, seed identity, contract revision,
  creation contract id/hash, and style contract id/hash. `contract_hash` alone
  is not a valid basis.
- Manual draft/save/confirm works without a Ready model. Only AI generation
  requires the `planning` binding.
- The browser never submits seed, contract, binding, Provider, or model
  identity. The server resolves and freezes them.
- A confirmed or superseded draft is never deleted or reactivated. A new
  current-basis draft is a new row.
- Phase 2 readiness includes only persisted states that exist now. It does not
  fabricate autosave recovery, projection rebuild, or general operation state.
- No plaintext key, Base URL, password, DSN, corpus root, prompt, raw Provider
  response, or corpus text enters a public DTO, log, report, or browser artifact.
- New Bible UI and old Bible runtime never coexist as two callable paths. The
  replacement commit removes the old route-less components, prompts, and Bible
  Store responsibilities.

---

### Task 1: Correct the Bible schema lifecycle

**Files:**

- Modify: `backend/schema/25_bible.sql`
- Modify: `backend/schema/30_planning.sql`
- Modify: `backend/schema_version.py`
- Modify: `backend/repositories/planning.py`
- Modify: `backend/repositories/chapter_sessions.py`
- Modify: `backend/scripts/reset_writer_core_data.py`
- Modify: `backend/tests/unit/test_schema_manifest.py`
- Modify: `backend/tests/unit/test_schema_version.py`
- Modify: `backend/tests/unit/test_initialize_database.py`
- Modify: `backend/tests/unit/test_planning_service.py`
- Modify: `backend/tests/unit/test_reset_writer_core_data.py`
- Modify: `backend/tests/integration/test_schema_bootstrap.py`
- Modify: affected schema-version integration and browser fixtures
- Create: `backend/tests/integration/test_bible_schema_lifecycle.py`

- [x] **Step 1: Write the schema contract tests**

Assert that `project_bible_drafts` has `id` as its primary key, nullable
`active_slot`, `UNIQUE(project_id, active_slot)`, and a check allowing only
`NULL` or `1`. Every Bible draft, attempt, revision, and confirmation request
must contain both contract identities:

```text
contract_revision
creation_contract_id + creation_hash
style_contract_id + style_hash
```

Assert separate foreign keys to `creation_contracts` and `style_contracts`.
Reject the old single `contract_hash` column and the old `project_id` draft
primary key.

Assert generation attempts have `owner_token`, `lease_expires_at`, and
`attempt_version`, with status/lease checks that support the bounded recovery
contract in Task 4. Bump the exact schema version from `writer-core-v1.3.0` to
`writer-core-v1.4.0`; a v1.3 database must fail closed until explicitly
reinitialized, never be modified during application startup.

- [x] **Step 2: Write the disposable-MySQL lifecycle tests**

Using the existing `disposable_mysql` fixture, prove:

1. draft A can be active;
2. a confirmation request can retain a foreign-key reference to A;
3. A can be deactivated without deletion;
4. draft B can become active under a new selection/contract basis;
5. B can be deactivated and draft C can become active when the author returns
   to the same seed under a newer selection generation;
6. a failed confirmation request leaves its draft active and editable;
7. inserting two rows with `active_slot=1` for one project fails.

- [x] **Step 3: Run RED**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/integration/test_schema_bootstrap.py backend/tests/integration/test_bible_schema_lifecycle.py -q
```

Expected: failures identify the old draft primary key and incomplete contract
basis.

- [x] **Step 4: Implement the schema**

Keep all draft rows. Confirmation requests reference the draft's complete
generation identity `(project_id, draft_id, selection_revision,
contract_revision, creation_hash, style_hash)` so a request from one basis
cannot be spliced onto another basis's draft. They also retain their own
immutable draft version/hash snapshot; those mutable-version snapshot fields
are not part of the foreign key. Keep the existing
`volume_plans.contract_hash` and `chapter_sessions.contract_hash` meaning: each
stores the creation-contract content hash. Change only the volume-to-Bible
foreign-key target from the removed Bible `contract_hash` to
`creation_bible_revisions.creation_hash`, and update repository reads and
comparisons against Bible rows accordingly. The exact Bible revision and
`content_hash` referenced by planning already freeze that revision's
`style_contract_id` and `style_hash`, so downstream planning does not need a
second duplicated style-hash column. Do not rename draft DTO/service fields,
modify `40_drafts.sql`, or add migration SQL or compatibility views.

- [x] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_schema_manifest.py backend/tests/unit/test_schema_version.py backend/tests/unit/test_initialize_database.py backend/tests/integration/test_schema_bootstrap.py backend/tests/integration/test_bible_schema_lifecycle.py -q
git diff --check
git add backend/schema backend/schema_version.py backend/repositories/planning.py backend/repositories/chapter_sessions.py backend/scripts/reset_writer_core_data.py backend/tests frontend/e2e/phase2a-assets-settings.spec.ts frontend/tests/unit/applicationSettingsStore.test.mjs
git commit -m "feat: define bible draft lifecycle"
```

---

### Task 2: Implement the manual Bible transaction service

**Files:**

- Create: `backend/domain/bibles.py`
- Create: `backend/repositories/bibles.py`
- Create: `backend/services/bibles.py`
- Create: `backend/routers/bibles.py`
- Modify: `backend/main.py`
- Create: `backend/tests/unit/test_bible_domain.py`
- Create: `backend/tests/unit/test_bible_service.py`
- Create: `backend/tests/api/test_bible_routes.py`
- Create: `backend/tests/integration/test_bible_revisions.py`

- [x] **Step 1: Define and test the payload**

Create strict Pydantic models for:

```text
premiseAndPromise
worldRules[]
powerOrProgressionSystem
protagonist
coreCast[]
factions[]
longTermConflicts[]
relationshipDynamics[]
toneAndNarrativeBoundaries
continuityGuardrails[]
openDesignQuestions[]
```

Fields describe future design and cannot claim an event has already occurred.
Reject unknown keys, blank required text, duplicate stable item ids, and payloads
outside the bounded field/list lengths. Hash only canonical validated data.

- [x] **Step 2: Write service RED tests**

Cover missing/current/superseded draft and head states, archived read-only,
server-derived contract basis, `expectedDraftVersion` and
`expectedHeadRevision` CAS, explicit new-row creation when the prior draft is
superseded, confirmation idempotency, failed-request replay, transaction
rollback, confirmed-to-new-draft adjustment, contract style-only drift, and
A-to-B-to-A selection fencing.

The service must call the canonical `ContractService.get_head()` result and
accept only `contract_ready=True`; it must not duplicate contract integrity SQL
or call the HTTP route.

- [x] **Step 3: Run RED**

```powershell
python -m pytest backend/tests/unit/test_bible_domain.py backend/tests/unit/test_bible_service.py backend/tests/api/test_bible_routes.py backend/tests/integration/test_bible_revisions.py -q
```

- [x] **Step 4: Implement the routes**

```text
GET  /api/projects/:id/bible/head
GET  /api/projects/:id/bible/draft
PUT  /api/projects/:id/bible/draft
POST /api/projects/:id/bible/draft/clone
POST /api/projects/:id/bible/confirm
GET  /api/projects/:id/bible/history
GET  /api/projects/:id/bible/history/:revision
```

`PUT` with `expectedDraftVersion=0` creates a new current-basis row when no
current editable draft exists; if a superseded draft occupies the active slot,
the same transaction deactivates it before inserting the new row. `PUT` with a
positive expected version updates only the current editable row. Confirmation
creates the immutable revision, advances the head, completes the confirmation
request, and clears the active slot in one transaction. No DELETE/reset method,
route, or repository operation exists.

Every Bible read assembles its draft/head/history row and canonical contract
readiness from one explicit database transaction, passing that transaction's
session to `ContractService.get_head()`. A confirmation passes the same session
with `for_update=True`; the canonical Contract service locks every persisted
readiness dependency in its established order through the Bible commit. The
Bible service does not duplicate or shadow the contract-integrity SQL.

If an unexpected `Exception` occurs only after that transaction successfully
reserved the request, the main transaction rolls back the reservation, revision,
head, and active-slot writes together. A separate narrow transaction may then
record only a terminal failed receipt after re-locking and verifying the exact
draft, basis, and head; it never advances the head or changes the draft slot. A
committed failed receipt replays as the stable terminal
`BibleConfirmationFailed`. If that narrow transaction or failed-receipt insert
cannot commit, the API returns the stable retryable `503
BibleConfirmationRetryable` without exposing the original exception, and the
same idempotency key may later succeed.

- [x] **Step 5: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_bible_domain.py backend/tests/unit/test_bible_service.py backend/tests/api/test_bible_routes.py backend/tests/integration/test_bible_revisions.py -q
git diff --check
git add backend
git commit -m "feat: add immutable creation bibles"
```

---

### Task 3: Replace the old Bible frontend with one canonical workspace

**Files:**

- Modify: `frontend/src/api/db/client.js`
- Create: `frontend/src/stores/bibleStore.js`
- Create: `frontend/src/views/ProjectBibleView.vue`
- Create: `frontend/src/components/bible/BibleEditor.vue`
- Create: `frontend/src/components/bible/BibleHistoryDrawer.vue`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/src/views/ArchivedProjectStatusView.vue`
- Delete: `frontend/src/views/WriterView.vue`
- Delete: `frontend/src/components/bible/CreativeBible.vue`
- Delete: `frontend/src/components/bible/CharacterArcView.vue`
- Delete: `frontend/src/components/bible/PlotThreadBoard.vue`
- Delete: `frontend/src/prompts/bibleFromSeed.js`
- Delete: `frontend/src/prompts/settingsFromBible.js`
- Modify: `frontend/src/stores/novelStore.js`
- Modify: `frontend/src/stores/settingStore.js`
- Create: `frontend/tests/unit/bibleStore.test.mjs`
- Create: `frontend/tests/unit/projectBibleView.test.mjs`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`

- [x] **Step 1: Write API and Store RED tests**

Test exact encoded Bible paths, transport allowlists, current-project request
generations, late-response rejection, explicit save only, same-command
idempotency replay, CAS conflict without auto-retry, dirty state preservation,
archived read-only behavior, and server-provided `canEdit/canClone/reasons`.
The Store never derives basis or revives history locally.

- [x] **Step 2: Write view RED tests**

Cover missing seed, missing/draft/superseded contract, manual editing with no
Ready model, explicit Save, complete confirmation preview, confirmed read-only,
Adjust Future Design, superseded content remaining copyable, archive read-only,
history pagination, focus/live region, refresh/back/forward, narrow layout, and
dirty route-leave/beforeunload protection.

- [x] **Step 3: Run RED**

```powershell
node --test frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/projectBibleView.test.mjs frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
```

- [x] **Step 4: Implement the canonical workspace and delete the old path**

Add `/projects/:projectId/bible`. Reuse the contract workspace patterns for
route hydration, dirty generations, module-only overlays, history, CAS, focus,
and archive state. `planning` Not Ready is shown but does not disable manual
Save or Confirm.

In the same commit, delete the unreachable `WriterView` and old Bible
components/prompts. Remove Bible-specific state, normalization, generation,
and setting-projection actions from `novelStore` and `settingStore`; do not leave
compatibility exports. Build must contain only the canonical Bible route.

- [x] **Step 5: Run GREEN, build, and commit**

```powershell
node --test frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/projectBibleView.test.mjs frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
npm --prefix frontend run build
git diff --check
git add frontend
git commit -m "feat: add creation bible workspace"
```

---

### Task 4: Add one bounded backend Bible generation attempt

**Files:**

- Create: `backend/gateways/bible_provider.py`
- Create: `backend/prompts/bible.py`
- Create: `backend/services/bible_generation.py`
- Modify: `backend/routers/bibles.py`
- Modify: `frontend/src/stores/bibleStore.js`
- Modify: `frontend/src/views/ProjectBibleView.vue`
- Create: `backend/tests/unit/test_bible_prompt.py`
- Create: `backend/tests/unit/test_bible_gateway.py`
- Create: `backend/tests/unit/test_bible_generation_service.py`
- Modify: `backend/tests/api/test_bible_routes.py`
- Modify: `backend/tests/integration/test_bible_revisions.py`
- Modify: `frontend/tests/unit/bibleStore.test.mjs`
- Modify: `frontend/tests/unit/projectBibleView.test.mjs`

- [x] **Step 1: Write attempt RED tests**

The service resolves current selection, confirmed contract, frozen assets and
corpus fragments, and the current `planning` binding server-side. Test one
context budget, one gateway call, strict output validation, manifest hash,
idempotency, timeout, Provider failure, parse failure, response-basis drift,
and no draft change on every failure.

Attempt ownership uses `owner_token`, `lease_expires_at`, and
`attempt_version`. An expired reserved/running attempt becomes
`outcome_unknown`; it is never silently retried. A new explicit Generate action
uses a new idempotency key.

- [x] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_bible_prompt.py backend/tests/unit/test_bible_gateway.py backend/tests/unit/test_bible_generation_service.py backend/tests/api/test_bible_routes.py backend/tests/integration/test_bible_revisions.py -q
node --test frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/projectBibleView.test.mjs
```

- [x] **Step 3: Implement one backend-only generation route**

```text
POST /api/projects/:id/bible/generate
GET  /api/projects/:id/bible/generation-attempts/:attemptId
```

The browser sends only author instructions, expected draft/head revisions, and
an idempotency key. Persist safe Provider/model identity and hashes, never raw
request/response diagnostics. The page disables Generate when `planning` is Not
Ready, blocks Generate over dirty local edits, and uses a Bible-module overlay.
Manual editing remains available.

- [x] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_bible_prompt.py backend/tests/unit/test_bible_gateway.py backend/tests/unit/test_bible_generation_service.py backend/tests/api/test_bible_routes.py backend/tests/integration/test_bible_revisions.py -q
node --test frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/projectBibleView.test.mjs
git diff --check
git add backend frontend
git commit -m "feat: generate bible drafts through backend"
```

---

### Task 5: Expose a truthful Phase 2 preparation DTO

**Files:**

- Modify: `backend/repositories/projects.py`
- Modify: `backend/services/project_lifecycle.py`
- Modify: `backend/routers/projects.py`
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/projectStore.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Create: `backend/tests/unit/test_project_preparation.py`
- Modify: `backend/tests/api/test_product_routes.py`
- Modify: `backend/tests/integration/test_project_archive.py`
- Create: `frontend/tests/unit/projectPreparationOverview.test.mjs`
- Modify: `frontend/tests/unit/projectStore.test.mjs`

- [x] **Step 1: Write the exact DTO RED tests**

`GET /api/projects/:id/preparation` returns only persisted Phase 2 facts:

```text
lifecycle: active | archived
activeSelection: missing | current
contract: missing | draft | current | superseded
bible: missing | draft | current | superseded
modelTasks: eight safe task readiness values
capabilities: viewPreparation | editContract | editBible | generateBible
nextAction: select_seed | continue_contract | continue_bible |
            phase_boundary_planning | archived_read_only
targetPath: encoded canonical path or null
reasons[]
```

Priority is lifecycle, selection, contract, Bible, then the non-clickable
planning boundary. Model loss changes only the relevant AI capability/reason;
it does not invalidate manual preparation. Do not add autosave, projection,
chapter-session, or general operation fields in Phase 2D.

- [x] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_project_preparation.py backend/tests/api/test_product_routes.py backend/tests/integration/test_project_archive.py -q
node --test frontend/tests/unit/projectStore.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs
```

- [x] **Step 3: Implement and consume one server authority**

The project overview renders one primary action and small status summaries from
this DTO. It does not join Seed/Contract/Bible Stores in the browser. Project
cards keep their current project-open behavior; no N+1 readiness reads are
added to the library. Later writing phases extend this DTO when their persisted
recovery states exist.

- [x] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_project_preparation.py backend/tests/api/test_product_routes.py backend/tests/integration/test_project_archive.py -q
node --test frontend/tests/unit/projectStore.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs
git diff --check
git add backend frontend
git commit -m "feat: expose phase two preparation state"
```

---

### Task 6: Remove the remaining proven-dead shadow runtime

**Files:**

- Delete after import-graph proof: `frontend/src/stores/novelStore.js`
- Delete after import-graph proof: `frontend/src/stores/settingStore.js`
- Delete after import-graph proof: `frontend/src/stores/memoryStore.js`
- Delete after import-graph proof: `frontend/src/stores/volumeStore.js`
- Delete after import-graph proof: `frontend/src/stores/storyBlockStore.js`
- Delete after import-graph proof: `frontend/src/stores/compareStore.js`
- Delete after import-graph proof: `frontend/src/stores/writerStore.js`
- Delete after import-graph proof: obsolete components imported only by the
  deleted `WriterView`/Stores
- Delete after import-graph proof: obsolete prompts imported only by those
  deleted modules
- Delete after import-graph proof: `frontend/src/api/ai/index.js` and its three
  browser Provider adapters
- Keep: `frontend/src/api/ai/providerPresets.js` while `ProviderForm.vue` uses it
- Modify: `backend/tests/api/test_route_inventory.py`
- Create: `frontend/tests/unit/phase2RuntimeInventory.test.mjs`
- Modify: formal unit tests that currently assert the existence of dead files

- [x] **Step 1: Write behavior/import inventory RED tests**

Import the production router/app and assert canonical routes. Walk production
imports from active route entries and prove none reaches the legacy Stores,
components, prompts, browser AI client, or old Bible modules. Source regex may
support diagnostics but cannot be the only proof.

- [x] **Step 2: Delete the closed dead cluster**

Delete only modules whose complete caller set belongs to the same unreachable
cluster. Preserve `providerPresets.js` and all current canonical Stores. Do not
create compatibility exports or empty forwarding files.

- [x] **Step 3: Verify and commit**

```powershell
python -m pytest backend/tests/api/test_route_inventory.py -q
node --test frontend/tests/unit/phase2RuntimeInventory.test.mjs
npm --prefix frontend run build
npm test
git diff --check
git add backend frontend scripts
git commit -m "refactor: remove superseded preparation runtime"
```

---

### Task 7: Full Phase 2 browser acceptance and integration

**Files:**

- Create: `frontend/e2e/phase2-creative-foundation.spec.ts`
- Create: `frontend/e2e/run-phase2.mjs`
- Create: `frontend/playwright.phase2.config.ts`
- Modify only if a missing neutral primitive is proven:
  `frontend/e2e/support/product-runner.mjs`
- Reuse: `frontend/e2e/runtime-observer.mjs`
- Reuse: `frontend/e2e/server-log-observer.mjs`
- Modify: `frontend/package.json`
- Modify: `package.json`
- Modify: `scripts/run-tests.mjs`
- Create: `scripts/tests/phase2Suite.test.mjs`
- Create: `backend/scripts/prepare_phase2_browser_db.py`
- Create: `backend/tests/unit/test_prepare_phase2_browser_db.py`
- Create: `docs/acceptance/2026-07-23-phase-2-creative-foundation.md`

- [x] **Step 1: Extend the shared runner, not a new lifecycle**

`run-phase2.mjs` must compose `e2e/support/product-runner.mjs`,
`runtime-observer.mjs`, and `server-log-observer.mjs` for reservation,
owned-process, runtime evidence, reverse cleanup, and disposable MySQL. It may
add only Phase 2 fixtures and orchestration. It cannot copy server lifecycle
code from Phase 2A/B/C runners. `prepare_phase2_browser_db.py` invokes the
canonical schema initializer and adds only Phase 2 fixtures; it does not
reimplement bootstrap DDL.

The runner validates explicit `TEST_MYSQL_*`, creates one random
`novel_creator_test_%` database, verifies `SELECT DATABASE()`, uses a synthetic
managed corpus root, binds random `127.0.0.1` ports, disables schedulers, and
injects fakes only at external market/Provider boundaries. Cleanup order is
servers reverse, reservations, database, root; counts must end at remaining=0.

- [x] **Step 2: Write the UI-only browser scenarios**

No `page.request`, `page.route`, `page.evaluate`, browser `fetch`, or Axios
bypass is allowed. Exercise project creation, 10 styles, 64 cards, synthetic
corpus, bindings, market snapshots, multiple seeds, A-to-B-to-A, manual engine,
contract confirm, manual Bible save/confirm, Bible adjustment, history,
archive read-only, refresh/back/forward, narrow viewport, Not Found, and the
preparation boundary. A fake Provider scenario covers one successful Bible
generation and one safe failure without changing the prior draft.

- [x] **Step 3: Run the final gates strictly in sequence**

```powershell
npm run test:browser:phase2
npm test
npm run test:integration
npm run build
git diff --check
```

After browser and integration runs, record created/cleaned/remaining database
counts and verify owned process, port, and temp-root residue is zero. Stop on the
first failure and use systematic debugging before continuing.

- [x] **Step 4: Independent final review**

Run a full specification review first. Only after it reports
Critical/Important/Minor = 0/0/0, run a separate quality/security-boundary
review. Fix findings through the same implementer and repeat the relevant
review before rerunning all five gates.

- [ ] **Step 5: Record honest acceptance evidence and commit**

The report records exact fresh commands/counts, commit, schema and asset hashes,
browser scenarios, cleanup counts, and secret scans. It must include:

```text
Product DB Ready: not evaluated
Real Provider Ready: not evaluated
Content Quality Ready: not evaluated
```

```powershell
git add backend/scripts/prepare_phase2_browser_db.py backend/tests/unit/test_prepare_phase2_browser_db.py frontend/e2e frontend/playwright.phase2.config.ts frontend/package.json package.json scripts docs/acceptance/2026-07-23-phase-2-creative-foundation.md
git commit -m "test: accept phase two creative foundation"
```

- [ ] **Step 6: Finish the branch**

Use `finishing-a-development-branch`. Fetch and compare `origin/main`, do not
force-push, do not clean the user's other worktrees, and use a safe integration
worktree if the main worktree is dirty. Merge/push only after the fresh gates
and final reviews pass. Phase 3 starts from the selected seed, confirmed
contract, and confirmed Bible revisions; no Phase 3 code is included here.

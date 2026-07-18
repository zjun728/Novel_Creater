# Phase 2D Creation Bible and Phase Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `subagent-driven-development`, `test-driven-development`,
> `requesting-code-review`, and `verification-before-completion`.

**Goal:** Add the formal immutable creation-bible workflow, compute one reliable
project-preparation readiness view, and complete Phase 2 browser acceptance
without touching the product database or a real Provider.

**Architecture:** A Bible draft is editable future design based on one active
seed selection and confirmed contract. Optional model generation is one bounded,
idempotent attempt. Confirmation atomically creates an immutable revision and
updates the head. Project overview consumes one server readiness DTO rather than
reconstructing state in the browser.

**Depends on:** Phase 2A–2C.

---

## Task 1: Define the creation-bible domain and immutable history

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

- [ ] **Step 1: Freeze the Bible payload**

Use structured, author-editable sections:

```text
premiseAndPromise
worldRules
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

This is future design, not Canon. Fields never claim an event has happened.
Every draft/revision freezes:

```text
selection revision + seed revision/hash
contract revision/hash
planning binding revision/hash when generated
payload hash
policy version
```

- [ ] **Step 2: Write lifecycle tests**

Cover:

- missing/current/superseded draft and head states;
- create/update draft with expected draft/head revisions;
- confirmation request idempotency and CAS;
- all-or-nothing revision/head/draft update;
- no delete/reset route or repository method;
- edit after confirmation clones to a new draft;
- selection/contract drift invalidates active readiness but keeps history;
- revisiting the same seed/contract content under a new selection generation
  never revives the old Bible;
- archived project is read-only.

- [ ] **Step 3: Run red**

```powershell
python -m pytest backend/tests/unit/test_bible_domain.py backend/tests/unit/test_bible_service.py backend/tests/api/test_bible_routes.py backend/tests/integration/test_bible_revisions.py -q
```

- [ ] **Step 4: Implement routes**

Expose:

```text
GET    /api/projects/:id/bible/head
GET    /api/projects/:id/bible/draft
PUT    /api/projects/:id/bible/draft
POST   /api/projects/:id/bible/draft/clone
POST   /api/projects/:id/bible/confirm
GET    /api/projects/:id/bible/history
GET    /api/projects/:id/bible/history/:revision
```

No DELETE or reset route exists. Public history returns structured values and
hash/revision metadata, never prompts or Provider raw output.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_bible_domain.py backend/tests/unit/test_bible_service.py backend/tests/api/test_bible_routes.py backend/tests/integration/test_bible_revisions.py -q
git add backend
git commit -m "feat: add immutable creation bibles"
```

## Task 2: Add optional backend Bible generation

**Files:**

- Create: `backend/gateways/bible_provider.py`
- Create: `backend/prompts/bible.py`
- Create: `backend/services/bible_generation.py`
- Modify: `backend/routers/bibles.py`
- Create: `backend/tests/unit/test_bible_prompt.py`
- Create: `backend/tests/unit/test_bible_gateway.py`
- Create: `backend/tests/unit/test_bible_generation_service.py`
- Modify: `backend/tests/api/test_bible_routes.py`
- Modify: `backend/tests/integration/test_bible_revisions.py`
- Delete: `frontend/src/prompts/bibleFromSeed.js`
- Modify: `frontend/src/stores/novelStore.js`
- Modify: `frontend/src/stores/settingStore.js`

- [ ] **Step 1: Write bounded generation tests**

The request uses current selection, confirmed contract, frozen assets/fragments,
`planning` binding revision, policy version, idempotency key, and author
instructions. The prompt uses a context budget and includes only necessary
corpus fragments. The output must match the Bible schema.

Provider failure, parse failure, drift, and timeout create one safe failed
attempt and do not change the draft. No hidden repair call occurs. A successful
attempt saves a draft only after the response passes strict validation and the
manifest is still current.

- [ ] **Step 2: Run red**

```powershell
python -m pytest backend/tests/unit/test_bible_prompt.py backend/tests/unit/test_bible_gateway.py backend/tests/unit/test_bible_generation_service.py backend/tests/api/test_bible_routes.py backend/tests/integration/test_bible_revisions.py -q
```

- [ ] **Step 3: Implement one gateway call**

Resolve `planning` binding server-side. Provider/model/request options are not
accepted from the browser. Persist actual Provider/model identity, binding
revision, input/output hashes, and safe status only. Never persist raw response
or secret-bearing request diagnostics.

- [ ] **Step 4: Remove frontend prompt and commit**

Remove the old Bible generation/normalization actions and imports from
`novelStore.js` and `settingStore.js`; canonical Bible state now belongs only to
`bibleStore.js` in Task 3. Do not leave a compatibility export or browser-direct
generation path.

```powershell
python -m pytest backend/tests/unit/test_bible_prompt.py backend/tests/unit/test_bible_gateway.py backend/tests/unit/test_bible_generation_service.py backend/tests/api/test_bible_routes.py backend/tests/integration/test_bible_revisions.py -q
git add backend frontend/src/prompts/bibleFromSeed.js frontend/src/stores/novelStore.js frontend/src/stores/settingStore.js
git commit -m "feat: generate bible drafts through backend"
```

## Task 3: Build the formal Bible page

**Files:**

- Create: `frontend/src/stores/bibleStore.js`
- Create: `frontend/src/views/ProjectBibleView.vue`
- Create: `frontend/src/components/bible/BibleEditor.vue`
- Create: `frontend/src/components/bible/BibleHistoryDrawer.vue`
- Delete: `frontend/src/components/bible/CreativeBible.vue`
- Delete: `frontend/src/components/bible/CharacterArcView.vue`
- Delete: `frontend/src/components/bible/PlotThreadBoard.vue`
- Modify: `frontend/src/views/WriterView.vue`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Create: `frontend/tests/unit/bibleStore.test.mjs`
- Create: `frontend/tests/unit/projectBibleView.test.mjs`
- Modify: `frontend/tests/unit/projectRoutes.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`

- [ ] **Step 1: Write view/state tests**

Test:

- missing seed links to Seeds;
- missing/current/superseded contract links to Contract;
- manual draft works with no Ready model;
- Generate is disabled with a precise Go to Model Settings recovery action when
  `planning` is Not Ready;
- model generation uses a module-only operation overlay;
- author edits generated content locally and explicitly saves the draft;
- Confirm shows the complete frozen basis once and publishes one revision;
- confirmed view is read-only and has Adjust Future Design, not delete/reset;
- history is readable and cannot become active through browser-only state;
- selection/contract drift immediately changes the page to superseded history;
- archived project is read-only;
- route refresh/focus/live-region/narrow layout work.

- [ ] **Step 2: Run red**

```powershell
node --test frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/projectBibleView.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
```

- [ ] **Step 3: Implement canonical route**

Add `/projects/:projectId/bible`. Use section forms, repeatable lists with stable
local keys, explicit Save Draft, and one Confirm action. Do not autosave each
keystroke and do not create a new revision per edit. Confirmed history has no
destructive controls.

Delete the old Bible components that rely on missing APIs, browser model calls,
delete/reset, or parallel arc/thread state. Character arcs and plot-thread
projections belong to later Canon/planning phases, not the Bible as separate
facts. Remove the old embedded `CreativeBible` import/tab from `WriterView.vue`
and replace any still-visible legacy entry with a normal router link to the
canonical project Bible route. Build must resolve with none of the deleted
modules imported.

- [ ] **Step 4: Run tests and commit**

```powershell
node --test frontend/tests/unit/bibleStore.test.mjs frontend/tests/unit/projectBibleView.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs
npm --prefix frontend run build
git add frontend
git commit -m "feat: add creation bible workspace"
```

## Task 4: Create one project-preparation readiness view

**Files:**

- Modify: `backend/repositories/projects.py`
- Modify: `backend/services/project_lifecycle.py`
- Modify: `backend/routers/projects.py`
- Modify: `backend/tests/unit/test_project_creation.py`
- Modify: `backend/tests/api/test_product_routes.py`
- Modify: `backend/tests/integration/test_project_archive.py`
- Modify: `frontend/src/stores/projectStore.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: `frontend/src/components/layout/productShell.js`
- Create: `frontend/tests/unit/projectStore.test.mjs`
- Create: `frontend/tests/unit/projectPreparationOverview.test.mjs`
- Modify: `frontend/tests/unit/productShell.test.mjs`

- [ ] **Step 1: Define the readiness DTO**

The backend returns:

```text
projectionState: synced | drift
autosaveState: ok | failed
activeSession: missing | current | superseded
activeSelection: missing | current
contract: missing | draft | current | superseded
bible: missing | draft | current | superseded
planning: missing | current | superseded
modelTasks: eight safe readiness values
hasFinalChapters
activeOperation
capabilities:
  enterWriter / manualEdit / aiGenerate / saveCandidate / finalize
nextAction:
  view_operation | rebuild_projections | recover_autosave |
  continue_writing | select_seed | continue_contract | continue_bible |
  phase_boundary_planning | phase_boundary_writer
reasons[]
```

`nextAction` is derived on the server from exact revision/hash comparisons.
Provider/model Not Ready does not change manual preparation readiness; it only
adds task-level recovery reasons.

The fixed priority is:

1. active write/finalization operation;
2. Canon/Projection drift;
3. failed autosave on the active draft;
4. valid active Session/working draft;
5. missing selection;
6. missing/superseded contract;
7. missing/superseded Bible;
8. missing/superseded planning;
9. ready to start a new writing Session.

Phase 2 preserves working Phase 1 recovery paths for priorities 1–4. Because
Phases 3 and 4 are not yet delivered, priorities 8–9 return non-clickable
`phase_boundary_*` actions with a clear completion message, not dead navigation.
Phase 3/4 replace those boundary values when their real routes ship.

- [ ] **Step 2: Write transition tests**

Cover new project, selected seed, contract draft/confirmed, Bible
draft/confirmed, A→B→A, model loss, active operation, Canon/Projection drift,
failed autosave, current/superseded Session and working draft, current/missing
planning, archive/restore, refresh, and first finalized chapter. Assert exactly
one primary next action in the fixed priority order.

- [ ] **Step 3: Run red**

```powershell
python -m pytest backend/tests/unit/test_project_creation.py backend/tests/api/test_product_routes.py backend/tests/integration/test_project_archive.py -q
node --test frontend/tests/unit/projectStore.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/productShell.test.mjs
```

- [ ] **Step 4: Implement and consume the DTO**

Project overview and project card stop independently inferring readiness from
multiple stores. Render one primary action and small status summaries. Existing
recovery/rebuild/resume actions retain their real Phase 1 routes. Do not show
Phase 3/4 dead navigation; boundary actions explain which preparation is
complete and which later phase supplies the next real route.

- [ ] **Step 5: Run tests and commit**

```powershell
python -m pytest backend/tests/unit/test_project_creation.py backend/tests/api/test_product_routes.py backend/tests/integration/test_project_archive.py -q
node --test frontend/tests/unit/projectStore.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs frontend/tests/unit/productShell.test.mjs
git add backend frontend
git commit -m "feat: expose creative preparation readiness"
```

## Task 5: Delete remaining Phase 2 shadow runtime

**Files:**

- Audit/delete imports under: `frontend/src/stores/novelStore.js`
- Audit/delete imports under: `frontend/src/api/ai/`
- Delete only when now unused:
  `frontend/src/components/seed/SeedWorkbench.vue`
- Delete only when now unused:
  `frontend/src/components/seed/StyleTrialPanel.vue`
- Audit/delete old Phase 2 exports in: `frontend/src/api/db/client.js`
- Modify: `backend/tests/api/test_route_inventory.py`
- Create: `frontend/tests/unit/phase2RuntimeInventory.test.mjs`

- [ ] **Step 1: Write runtime inventory tests**

Assert formal route inventory includes only the canonical Phase 2 routes and
excludes old `/settings`, market fallback, JSON wizard, old Bible, and
browser-direct Provider paths. Import the production router/app and verify
behavior; do not rely only on source regex.

- [ ] **Step 2: Remove only proven-dead runtime code**

Use import graph/build evidence. Do not delete historical plans, acceptance
reports, approved assets, or later-phase writer code solely because it is not
linked in Phase 2. Remove old runtime modules that now have no canonical caller
and conflict with the new paths.

- [ ] **Step 3: Run tests and commit**

```powershell
python -m pytest backend/tests/api/test_route_inventory.py -q
node --test frontend/tests/unit/phase2RuntimeInventory.test.mjs
npm --prefix frontend run build
git add backend frontend
git commit -m "refactor: remove superseded preparation paths"
```

## Task 6: Full Phase 2 browser acceptance

**Files:**

- Create: `frontend/e2e/phase2-creative-foundation.spec.ts`
- Create: `frontend/e2e/run-phase2.mjs`
- Create: `frontend/playwright.phase2.config.ts`
- Modify: `frontend/package.json`
- Modify: `package.json`
- Modify: `scripts/run-tests.mjs`
- Create: `scripts/tests/phase2Suite.test.mjs`
- Create: `backend/scripts/prepare_phase2_browser_db.py`
- Create: `backend/tests/unit/test_prepare_phase2_browser_db.py`
- Create: `docs/acceptance/2026-07-18-phase-2-creative-foundation.md`

- [ ] **Step 1: Build one runner-owned environment**

The runner:

- validates explicit test-only environment variables;
- creates one random disposable MySQL 8 database;
- initializes exact v1.3 schema and 10+64 assets;
- creates a synthetic managed corpus root;
- starts backend/frontend on reserved loopback ports;
- injects market/model fakes only through backend composition seams;
- records PID/DB/root ownership tokens;
- always terminates children and drops DB in `finally`;
- scans network/page/console/log/report/screenshot output for secret, Base URL,
  DSN, absolute-root, and large-corpus sentinels.

- [ ] **Step 2: Exercise the full manual path**

In a real browser:

1. create/open a project;
2. browse 10 styles and 64 cards;
3. import synthetic corpus and inspect bounded details;
4. set application fallback and project bindings;
5. import separate public-rank snapshots;
6. create multiple manual seeds and select one;
7. enter a manual engine and complete/confirm a contract;
8. manually draft/edit/confirm a Bible;
9. refresh each canonical route and use Back/Forward;
10. verify overview reports preparation complete with no dead Planning button.

- [ ] **Step 3: Exercise recovery and history**

Test source failure with retained snapshot, model task Not Ready with manual
fallback, contract drift, Bible drift, active-operation overlay, A→B→A
supersession, archive read-only, narrow viewport, Not Found, and safe retries.

- [ ] **Step 4: Run the final automated gates**

```powershell
npm run test:browser:phase2
npm test
npm run test:integration
npm run build
git diff --check
git status --short
```

Expected:

- all suites pass;
- browser and integration created/cleaned counts match, `remaining=0`;
- no product DB, real Provider, or live ranking source was contacted;
- no secret/corpus-root/raw-text sentinel appears;
- worktree contains only the acceptance report update before final commit.

- [ ] **Step 5: Perform independent reviews**

Run one full spec review against the July 18 product specification and one
code-quality/security-boundary review. Fix every Critical/Important finding and
rerun all gates.

- [ ] **Step 6: Record evidence and commit**

Record exact commit, schema version/hash, asset package/hash, test counts,
browser scenarios, created/cleaned DB counts, secret scans, known Phase 3
boundary, and the statement:

```text
Product DB Ready: not evaluated
Real Provider Ready: not evaluated
Content Quality Ready: not evaluated
```

Then:

```powershell
git add backend/scripts/prepare_phase2_browser_db.py backend/tests/unit/test_prepare_phase2_browser_db.py frontend/e2e frontend/playwright.phase2.config.ts frontend/package.json package.json scripts docs/acceptance/2026-07-18-phase-2-creative-foundation.md
git commit -m "test: accept phase two creative foundation"
```

## Task 7: Merge readiness, without product mutation

- [ ] **Step 1: Verify branch evidence**

```powershell
git status --short --branch
git log --oneline main..HEAD
npm test
npm run test:integration
npm run test:browser:phase2
npm run build
```

- [ ] **Step 2: Review commit scope**

Ensure no runtime compatibility aliases, product DB artifacts, Provider outputs,
downloaded live HTML, `.env`, corpus blobs, or Playwright reports are tracked.

- [ ] **Step 3: Fast-forward main and push only after all gates pass**

Use the repository's established non-interactive merge/push procedure. Do not
run the product reset or a real Provider test as part of the merge.

- [ ] **Step 4: Hand off Phase 3**

Phase 3 starts only after Phase 2 public contracts are on `main`. Its inputs are
the active seed selection, confirmed creation contract, and confirmed Bible
revisions. No Phase 3 implementation is included in this plan.

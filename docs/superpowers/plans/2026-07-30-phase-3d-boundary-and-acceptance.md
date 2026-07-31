# Phase 3D Boundary and Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one read-only Planning composition of future design, confirmed
plot progress, and Canon/Projection status, then close the complete Phase 3
product path with a UI-only browser gate and evidence-backed acceptance report.

**Architecture:** The existing `GET /api/projects/:projectId/planning` remains
the only public composition endpoint and the existing `PlanningService`,
`PlanningRepository`, `planningStore`, and `PlanningWorkspace.vue` remain the
only runtime chain. `actualProgress` is a closed projection of synchronized
`plot_thread_projections`; it is never a mutable StoryBlock/Stage/SceneTask
completion state. One new formal Phase 3 browser runner exercises the complete
product path through the UI while reusing the neutral owned-resource and
runtime-observer infrastructure.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, aiomysql, MySQL 8, pytest,
Vue 3, Pinia 3, Vue Router 4, Naive UI, Node test runner, Playwright.

---

## Authority and baseline

- Product authority:
  `docs/superpowers/specs/2026-07-18-product-rebuild-and-writer-loop-design.md`.
- Phase 3 authority:
  `docs/superpowers/specs/2026-07-24-phase-3-story-planning-design.md`.
- Phase 3 roadmap:
  `docs/superpowers/plans/2026-07-24-phase-3-story-planning-roadmap.md`.
- Delivery baseline:
  `main@e8aebd9eb851ccc64f160022984342344905cd15`.
- Delivery branch: `codex/phase3d-boundary-acceptance`.
- Worktree:
  `D:\CodexData\.codex\worktrees\phase3d-boundary-acceptance\Novel_Creater`.
- Reproducible frontend-install prerequisite:
  `f63c2a5 fix: restore reproducible frontend install`.

Do not edit the old `dd1a`, Phase 2, Phase 3A/B/C, M4, or M5 worktrees. Do not
copy their untracked files or caches into this worktree.

## Frozen decisions

- Phase 3D makes no schema change. The source schema remains exactly
  `writer-core-v1.5.0`; there is no migration, compatibility query, fallback,
  alias, or second Planning runtime.
- The existing `planning-v1` aggregate, `PlanningService`,
  `PlanningRepository`, `planningStore`, and `PlanningWorkspace.vue` are
  extended in place. Do not add `PlanningV2`, `planningV2Store`,
  `actualProgressStore`, a fourth Planning route, or an archived duplicate.
- `futurePlan` is the current Planning Head when its upstream basis is current.
  Its revision number is independent of the Canon revision number.
- `actualProgress` means only confirmed plot-thread facts from
  `plot_thread_projections` at the synchronized Projection Head. It does not
  mean that a Planning node is complete and it never writes `completed`,
  `progress`, or another lifecycle field into the Planning aggregate.
- Each public actual-progress item has exactly:

  ```json
  {
    "revisionNumber": 1,
    "subjectKey": "global",
    "entityId": null,
    "fieldPath": "plot.gunpowder",
    "value": {"status": "推进"},
    "contentHash": "64-lowercase-hex"
  }
  ```

  No database ID, project ID, created time, SQL field name, evidence, prompt,
  raw Provider output, corpus text, or secret-bearing metadata crosses this
  boundary.
- Items are ordered by `subject_key`, `field_path`, then row `id`. The query
  fixes `project_id` and the exact `projection_revision_number` read from the
  same transaction snapshot.
- When Canon revision is `0`, `actualProgress` is exactly `[]` and the
  repository does not fabricate a row. When Canon and Projection are not
  synchronized, `actualProgress` is also `[]` and
  `canonProjectionStatus.synchronized` is `false`.
- “Same revision” means that `futurePlan`, Projection Head, and actual-progress
  rows are assembled in one database transaction snapshot, and every progress
  item has the exact `canonProjectionStatus.projectionRevision`. It does not
  mean Planning revision and Canon revision numbers must be equal.
- Archived projects read the same current snapshot and history but every
  mutation capability remains false.
- The UI labels the two authorities explicitly as “未来规划” and “正文已发生”.
  Canon revision `0` renders the exact text “尚无已定稿事实”. An unsynchronized
  head renders “正文事实正在重建，暂不展示实际进度”.
- `actualProgress` is display-only. It never enters `localContent`, Planning
  Draft save/confirm bodies, ChapterOutline bodies, or any Pinia mutation
  command.
- The formal Phase 3 browser gate uses six isolated scenarios to prove the
  fourteen roadmap outcomes. The fourteen outcomes are evidence requirements,
  not a requirement to allocate fourteen databases.
- Browser product actions use only Playwright locators, normal navigation,
  keyboard input, and visible product controls. `page.request`, `page.route`,
  `page.evaluate`, browser `fetch`, Axios, direct API clients, direct Pinia
  actions, and database writes from the spec are forbidden.
- The pre-confirmation Session rule is proved by two complementary gates:
  Playwright proves the UI performs zero Session POSTs before Outline
  confirmation, and the Disposable MySQL service test proves a direct
  pre-confirmation create command is rejected. The browser must not bypass the
  UI merely to force an invalid POST.
- Fake gateway behavior may replace only the external Provider boundary.
  Automated acceptance calls no real Provider, product database, or live
  website.
- All shared MySQL, browser, build, and final gates run serially. Every owned
  database, process, port, temporary root, Playwright artifact, and Vite
  `deps_temp_*` directory must be accounted for and cleaned.
- Phase 3D does not implement Chapter writing UX, FinalizationChangeSet, Canon
  writes, projection rebuild, mark-complete controls, content quality review,
  backup/export, real Provider readiness, or product-database readiness.

## File map

**Read-model runtime**

- Modify `backend/repositories/planning.py`: exact-revision plot-thread read.
- Modify `backend/services/planning.py`: closed actual-progress normalization
  and same-snapshot composition.
- Modify `backend/routers/planning.py`: public closed DTO serialization only.
- Modify `backend/tests/unit/test_planning_repository.py`: SQL contract.
- Modify `backend/tests/unit/test_planning_service.py`: Canon 0, synchronized,
  mismatch, archived, and malformed-row behavior.
- Modify `backend/tests/api/test_planning_routes.py`: exact public response and
  no progress mutation route.
- Modify
  `backend/tests/integration/test_planning_aggregate_lifecycle.py`: real MySQL
  same-revision and zero-write evidence.

**Single frontend runtime**

- Modify `frontend/src/api/db/client.js`: strict Planning state projection.
- Modify `frontend/src/stores/planningStore.js`: retain the closed read model
  without copying it into editable content.
- Create
  `frontend/src/components/planning/ActualProgressPanel.vue`: one display-only
  panel shared by all three tabs.
- Modify `frontend/src/components/planning/PlanningWorkspace.vue`: render the
  future/actual boundary.
- Modify `frontend/tests/unit/writerCoreApi.test.mjs`,
  `frontend/tests/unit/planningStore.test.mjs`, and
  `frontend/tests/unit/planningWorkspaceSfc.test.mjs`: closed DTO, authority
  separation, Canon 0, mismatch, archived, and no-write tests.

**Formal Phase 3 gate**

- Create `frontend/e2e/support/deny-proxy.mjs`,
  `frontend/e2e/support/database-residue.mjs`, and
  `frontend/e2e/support/safe-diagnostics.mjs`: neutral safety helpers extracted
  from the accepted 3C runner.
- Modify `frontend/e2e/run-phase3c.mjs`: consume the neutral helpers without
  changing the Phase 3C regression behavior.
- Create `scripts/tests/phase3BrowserSupport.test.mjs`: helper behavior,
  failure, and redaction contracts.
- Create `frontend/e2e/phase3-story-planning.spec.ts`: UI-only product flow.
- Create `frontend/e2e/playwright.phase3.config.ts`: serial local-only config.
- Create `frontend/e2e/run-phase3.mjs`: strict fake boundary and owned
  disposable resources.
- Modify `frontend/package.json` and root `package.json`: one formal
  `test:browser:phase3` entrypoint.
- Modify `scripts/run-tests.mjs`: closed `browser-phase3` dispatcher suite.
- Create `scripts/tests/phase3Suite.test.mjs`: runner, source-graph,
  fourteen-outcome, secret, and cleanup contracts.
- Modify `scripts/tests/run-tests.test.mjs`: dispatcher registration and
  fail-before-spawn authority checks.

**Acceptance facts**

- Create `docs/acceptance/2026-07-30-phase-3-story-planning.md`.
- Modify `CURRENT_PROJECT_STATE.md`, `PRODUCT_DEVELOPMENT_PLAN.md`, and
  `DEVELOPMENT_LOG.md` only after all fresh gates pass.
- Modify `scripts/tests/phase3PlanContract.test.mjs`: exact Phase 3D plan and
  acceptance-document facts.

### Task 1: Add the Closed Same-Revision Actual Progress Read Model

**Files:**
- Modify: `backend/repositories/planning.py`
- Modify: `backend/services/planning.py`
- Modify: `backend/routers/planning.py`
- Modify: `backend/tests/unit/test_planning_repository.py`
- Modify: `backend/tests/unit/test_planning_service.py`
- Modify: `backend/tests/api/test_planning_routes.py`
- Modify:
  `backend/tests/integration/test_planning_aggregate_lifecycle.py`

- [ ] **Step 1: Write repository and service RED tests**

Add tests that require this repository method and exact ordering:

```python
rows = await repository.read_actual_plot_progress(
    session,
    "project-1",
    2,
)
assert "FROM plot_thread_projections" in session.calls[-1].sql
assert "project_id=%s AND revision_number=%s" in session.calls[-1].sql
assert "ORDER BY subject_key,field_path,id" in compact(session.calls[-1].sql)
assert session.calls[-1].args == ("project-1", 2)
```

Extend the service harness with progress rows and assert:

```python
state = await harness.service.get_state("p1")
assert state.actual_progress == (
    ActualProgressResult(
        revision_number=1,
        subject_key="global",
        entity_id=None,
        field_path="plot.gunpowder",
        value={"status": "推进"},
        content_hash=HASH_A,
    ),
)
assert state.canon_projection_status["projectionRevision"] == 1
```

Also require exact empty results for Canon `0` and for `canon=2,
projection=1`, and require malformed revisions, hashes, field paths, or JSON
to raise the existing fixed `PlanningPreconditionFailed` without echoing the
row.

Before implementing production code, add two real-MySQL tests:

1. use the production `CanonService.commit` path to create synchronized
   revision-1 plot progress, insert an unrelated revision-2 control row, and
   require only revision 1;
2. wrap the real repository so `read_projection_head` pauses after returning,
   start a production `CanonService.commit`, and prove with a database-reported
   lock-wait timeout that the Planning read still owns the shared project lock.
   Resume the first GET and require its complete Planning state, status, and
   progress to remain the old snapshot; only then let the Canon commit complete
   and require a fresh GET to retain the same Planning Head and `futurePlan`
   while returning the new synchronized Canon status and progress. The existing
   concurrent Planning-confirmation test separately proves the production
   Planning writer is fenced. Do not invent a transaction that advances
   Planning and Canon/Projection Heads together; the product has no such write
   operation.

The second test uses `asyncio.Event` only to control real database connections
and must release every barrier and cancel/gather every unfinished task in
`finally`; it does not add a production failpoint.

- [ ] **Step 2: Run the focused RED tests**

Run:

```powershell
python -m pytest `
  backend/tests/unit/test_planning_repository.py `
  backend/tests/unit/test_planning_service.py `
  backend/tests/api/test_planning_routes.py -q
python -m pytest `
  backend/tests/integration/test_planning_aggregate_lifecycle.py `
  -q -k "actual_progress or same_snapshot"
```

Expected: FAIL because `read_actual_plot_progress` and non-empty composition do
not exist. The integration command must fail for the same missing behavior,
not because MySQL authority or fixture setup is invalid.

- [ ] **Step 3: Implement the exact repository read**

Add only:

```python
async def read_actual_plot_progress(
    self,
    session,
    project_id: str,
    revision_number: int,
):
    return await session.fetchall(
        """SELECT revision_number,subject_key,entity_id,field_path,
                  payload_json,content_hash
             FROM plot_thread_projections
            WHERE project_id=%s AND revision_number=%s
            ORDER BY subject_key,field_path,id""",
        (project_id, revision_number),
    )
```

Do not join historical revisions, Canon events, mutable Planning tables, or
another projection table.

- [ ] **Step 4: Implement closed normalization and same-snapshot assembly**

In `PlanningService.get_state`, read the Projection Head first inside its
existing transaction. Only when `canon == projection > 0`, call the new
repository method with that exact projection revision. Normalize every row to
a frozen `ActualProgressResult` with the six internal snake_case fields
`revision_number`, `subject_key`, `entity_id`, `field_path`, `value`, and
`content_hash`. Decode JSON through the existing strict JSON helper, validate
the lowercase SHA-256, and reject a row whose revision does not equal the fixed
head. The router, not the service, owns the camelCase public-key mapping.

For Canon `0` or mismatch use:

```python
actual_progress: tuple[ActualProgressResult, ...] = ()
```

Keep `futurePlan`, Draft, Head, capabilities, and archived behavior unchanged.
Do not add a progress write command or endpoint.

- [ ] **Step 5: Close the router contract**

Keep the existing top-level response shape and explicitly serialize only the
six allowed public fields:

```python
"actualProgress": [
    {
        "revisionNumber": item.revision_number,
        "subjectKey": item.subject_key,
        "entityId": item.entity_id,
        "fieldPath": item.field_path,
        "value": item.value,
        "contentHash": item.content_hash,
    }
    for item in result.actual_progress
],
```

Add a RED API test whose runtime progress item also contains private extra
fields and require those fields not to cross the response boundary.
Add an API inventory assertion that no Planning route contains
`complete`, `progress`, `mark`, `sync-memory`, or `rebuild` as a mutation path.

- [ ] **Step 6: Run GREEN and review**

Run the focused command from Step 2 and:

```powershell
git diff --check
```

Expected: all focused tests pass; no schema file changes. Perform implementer
self-review, then independent spec review and independent quality review,
each ending at `Critical 0 / Important 0 / Minor 0`.

- [ ] **Step 7: Commit Task 1**

```powershell
git add backend/repositories/planning.py `
  backend/services/planning.py `
  backend/routers/planning.py `
  backend/tests/unit/test_planning_repository.py `
  backend/tests/unit/test_planning_service.py `
  backend/tests/api/test_planning_routes.py `
  backend/tests/integration/test_planning_aggregate_lifecycle.py
git commit -m "feat: compose canonical planning progress"
```

### Task 2: Re-run the Read Model Gate and Audit Disposable MySQL Cleanup

**Files:**
- Verify only; no source file changes.

- [ ] **Step 1: Re-run the real-MySQL behavior gate**

Run the tests written RED in Task 1:

```powershell
python -m pytest `
  backend/tests/integration/test_planning_aggregate_lifecycle.py `
  -q -k "actual_progress or same_snapshot"
```

Expected: both the exact-revision and controlled-concurrency snapshot tests
pass.

- [ ] **Step 2: Audit cleanup without changing the tree**

Record Disposable MySQL `created`, `cleaned`, and `remaining`; require equality
and zero residue. Run `git diff --check` and require a clean status after the
Task 1 commit. If behavior fails, return the failure to the Task 1 implementer
and repeat both Task 1 reviews; do not weaken or rewrite the already-observed
RED tests.

### Task 3: Show Future and Actual Authorities in the One Planning Workspace

**Files:**
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/planningStore.js`
- Create:
  `frontend/src/components/planning/ActualProgressPanel.vue`
- Modify:
  `frontend/src/components/planning/PlanningWorkspace.vue`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/planningStore.test.mjs`
- Modify:
  `frontend/tests/unit/planningWorkspaceSfc.test.mjs`

- [ ] **Step 1: Write frontend RED tests**

Require the API boundary to accept only the six public item fields, validate
non-negative revision and lowercase hash, and discard/reject private extras.
Require the Store to retain `actualProgress` only under authoritative
`state`, never in `localContent`.

Mount the real SFC and assert:

```javascript
assert.match(html, /未来规划/)
assert.match(html, /正文已发生/)
assert.match(html, /尚无已定稿事实/)
assert.doesNotMatch(html, /标记完成|同步记忆|手工进度/)
```

For mismatch require “正文事实正在重建，暂不展示实际进度”. For a non-empty
projection require the field path and public value, and prove every control in
the panel is non-interactive.

- [ ] **Step 2: Run RED**

Run:

```powershell
node --test `
  frontend/tests/unit/writerCoreApi.test.mjs `
  frontend/tests/unit/planningStore.test.mjs `
  frontend/tests/unit/planningWorkspaceSfc.test.mjs
```

Expected: FAIL because the API does not close this nested DTO and the workspace
does not render it.

- [ ] **Step 3: Add the strict client projection**

Add one `planningActualProgressItem` parser that returns exactly:

```javascript
{
  revisionNumber,
  subjectKey,
  entityId,
  fieldPath,
  value,
  contentHash,
}
```

Use it only in the Planning GET response parser. Do not add a mutation method.

- [ ] **Step 4: Add the display-only panel**

`ActualProgressPanel.vue` accepts `items` and `status` props. It renders:

- Canon/Projection revision labels;
- the Canon-0 empty text;
- the mismatch recovery text;
- otherwise an ordered definition list of subject, field path, and public
  value.

It emits no event and contains no button, checkbox, input, drag handle, or
editable element.

Render it once from `PlanningWorkspace.vue`, outside the editable Planning
sheet, so all three existing route tabs share it. Label the editable aggregate
“未来规划”.

- [ ] **Step 5: Keep Store writes separated**

On hydrate and post-confirm authoritative reread, retain the closed response
under `state`. Preserve the existing construction of `localContent` from only
Draft or `futurePlan`; do not spread `actualProgress` into any request body.

- [ ] **Step 6: Run GREEN and review**

Run Step 2, then:

```powershell
npm --prefix frontend run build
git diff --check
```

Expected: focused tests and build pass. Complete self-review, spec review, and
quality review sequentially at `0/0/0`.

- [ ] **Step 7: Commit Task 3**

```powershell
git add frontend/src/api/db/client.js `
  frontend/src/stores/planningStore.js `
  frontend/src/components/planning/ActualProgressPanel.vue `
  frontend/src/components/planning/PlanningWorkspace.vue `
  frontend/tests/unit/writerCoreApi.test.mjs `
  frontend/tests/unit/planningStore.test.mjs `
  frontend/tests/unit/planningWorkspaceSfc.test.mjs
git commit -m "feat: separate future and actual planning state"
```

### Task 4: Extract Neutral Browser Safety Support

**Files:**
- Create: `frontend/e2e/support/deny-proxy.mjs`
- Create: `frontend/e2e/support/database-residue.mjs`
- Create: `frontend/e2e/support/safe-diagnostics.mjs`
- Modify: `frontend/e2e/run-phase3c.mjs`
- Create: `scripts/tests/phase3BrowserSupport.test.mjs`

- [ ] **Step 1: Write helper RED tests**

Import the wished-for neutral APIs and require:

- deny proxy accepts only owned loopback HTTP and rejects/counts external HTTP
  and CONNECT without retaining URLs or secrets;
- database residue audit accepts only the exact owned random database name,
  compares created/cleaned/remaining, and never emits credentials or raw SQL;
- safe diagnostics flatten one or many lifecycle errors into fixed categories
  without rendering raw messages, environment values, paths, DSNs, prompts,
  or Provider bodies.

Run:

```powershell
node --test scripts/tests/phase3BrowserSupport.test.mjs
```

Expected: FAIL because the neutral support modules do not exist.

- [ ] **Step 2: Extract the minimum helpers**

Move the already accepted generic implementations out of
`run-phase3c.mjs`. Export only the narrow functions used by both the 3C runner
and the future Phase 3 runner. Do not export Phase 3C fixture SQL, scenario
state, browser locators, gateway responses, or write allowlists.

- [ ] **Step 3: Rewire the accepted Phase 3C runner**

Replace its local generic copies with imports from `support/*`. Preserve its
formal spec, config, scenarios, diagnostics, cleanup order, and output
contract exactly.

- [ ] **Step 4: Run GREEN and the Phase 3C regression**

Run:

```powershell
node --test `
  scripts/tests/phase3BrowserSupport.test.mjs `
  scripts/tests/phase3cSuite.test.mjs
npm run test:browser:phase3c
git diff --check
```

Expected: helper tests pass, the accepted Phase 3C browser scenarios remain
green, and all owned residue is zero.

- [ ] **Step 5: Review and commit Task 4**

Complete self-review, sequential spec review, and sequential quality review at
`0/0/0`, then:

```powershell
git add frontend/e2e/support/deny-proxy.mjs `
  frontend/e2e/support/database-residue.mjs `
  frontend/e2e/support/safe-diagnostics.mjs `
  frontend/e2e/run-phase3c.mjs `
  scripts/tests/phase3BrowserSupport.test.mjs
git commit -m "refactor: share browser safety support"
```

### Task 5: Add One Formal Full Phase 3 UI-Only Gate

**Files:**
- Create: `frontend/e2e/phase3-story-planning.spec.ts`
- Create: `frontend/e2e/playwright.phase3.config.ts`
- Create: `frontend/e2e/run-phase3.mjs`
- Modify: `frontend/package.json`
- Modify: `package.json`
- Modify: `scripts/run-tests.mjs`
- Create: `scripts/tests/phase3Suite.test.mjs`
- Modify: `scripts/tests/run-tests.test.mjs`

- [ ] **Step 1: Write dispatcher and source-graph RED tests**

Require one exact spec/config/runner, one dispatcher suite, and one package
entrypoint. Parse the Playwright source through the existing browser
source-graph helper and reject direct or aliased forms of:

```text
page.request
page.route
page.evaluate
fetch
axios
api client imports
Pinia action imports
database helpers
```

- [ ] **Step 2: Run RED**

Run:

```powershell
node --test `
  scripts/tests/phase3Suite.test.mjs `
  scripts/tests/run-tests.test.mjs
```

Expected: FAIL because the Phase 3 suite does not exist.

- [ ] **Step 3: Add the closed dispatcher and source skeleton**

Create the exact spec/config/runner paths and package/dispatcher entries. The
spec initially contains no scenario. The source contract remains RED until all
six named scenarios are implemented. The runner imports only `support/*`,
never a Phase 3B/3C runner.

- [ ] **Step 4: Write lifecycle and audit RED tests**

Extend `phase3Suite.test.mjs` with executable helper-injection tests that prove:

- root registration precedes every fallible initialization;
- cleanup order is servers reverse, reservations, database, root;
- one error preserves identity and several errors aggregate;
- initialization, browser, audit, and cleanup failures are all retained;
- database name, ports, logs, artifacts, and Vite cache are owned and bounded;
- diagnostics use the neutral redaction helper.

Run only these lifecycle test names and observe RED before implementing the
runner lifecycle.

- [ ] **Step 5: Build the runner from neutral infrastructure**

`run-phase3.mjs` must use the existing neutral lifecycle, owned server,
runtime observer, and the Task 4 deny proxy, database residue, and safe
diagnostic helpers. It may copy no Phase 3B/3C private fixture state machine.

Register the owned root before fallible preparation. Each scenario owns a fresh
database and random ports. Cleanup order is:

```text
servers(reverse) -> reservations -> database -> temp root
```

Single cleanup errors retain identity; multiple errors use `AggregateError`.
All diagnostics are fixed safe categories.

- [ ] **Step 6: Develop six UI-only scenarios RED then GREEN**

Use visible product interactions only:

1. `foundation-manual-r1`: finish the Phase 2 preparation UI, disable the
   planning model, create a manual Draft, add Volume/Plot/StoryBlock/Stage/
   SceneTask, confirm R1, and see Canon-0 “尚无已定稿事实”.
2. `revision-outline-session`: clone future design, produce R2 while R1 remains
   in history, create an Outline Draft, prove zero Session POST before
   confirmation, confirm Outline, then enter the exact Session.
3. `baseline-lock`: after first Seed, Contract, and Bible confirmation, the UI
   exposes no replacement action and direct mutation attempts return the fixed
   public conflict without changing any head.
4. `pinned-session`: create a Session, advance Planning Head, refresh Writer,
   and prove the Session retains its historical Planning/Outline pins.
5. `outline-adjustment-before-finalization`: after a drafting ChapterSession
   exists, the author adjusts and adopts a new Outline through visible UI;
   existing prose remains, the old Candidate becomes stale, and a newly saved
   Candidate is current.
6. `archived-navigation`: archive from the visible UI, prove Planning and
   Outline are read-only, then back/forward/refresh across all three canonical
   Planning routes.

The fixture may prepare external market/provider inputs and disposable
prerequisite records, but every product mutation asserted by a scenario must
occur through visible UI controls. Do not use a test-only product endpoint.

For each scenario, in the order above:

1. add only that scenario with its Playwright locators and expected visible
   state;
2. run the same formal runner with
   `PHASE3_FOCUS_SCENARIO=<exact-name>` and observe RED for the missing product
   behavior or fixture support;
3. add only the minimum scenario fixture/runner support;
4. rerun the same scenario to GREEN;
5. run the source-graph contract and `git diff --check`.

`PHASE3_FOCUS_SCENARIO` is a closed development-only allowlist over the same
six formal tests. The public `npm run test:browser:phase3` command never sets it
and always runs all scenarios.

- [ ] **Step 7: Add exact runtime and cleanup audits**

For every scenario:

- settle request bodies at navigation boundaries;
- allow only the exact expected POST/PUT/DELETE routes and counts;
- require forbidden external HTTP and CONNECT counts `0`;
- scan browser evidence, server streams, reports, and artifacts for dynamic
  sentinels plus API key, Authorization, password/DSN, prompt, manifest, raw
  Provider output, and corpus text;
- validate `created=cleaned`, `remaining=0`, owned processes/ports/temp roots
  `0`, Playwright retained media `0`, and Vite `deps_temp_*` `0`.

- [ ] **Step 8: Wire the one formal command**

Add:

```json
"test:browser:phase3": "node scripts/run-tests.mjs browser-phase3"
```

at root, with the frontend runner command delegated through the dispatcher.
Do not change the default Phase 2 gate or retire the explicit 3B/3C regression
entrypoints.

- [ ] **Step 9: Run the complete six-scenario GREEN gate and review**

Run:

```powershell
node --test `
  scripts/tests/phase3Suite.test.mjs `
  scripts/tests/run-tests.test.mjs
npm run test:browser:phase3
git diff --check
```

Expected: all source contracts pass, all six scenarios pass, all fourteen
outcomes are evidenced, and every resource count is zero after cleanup.
Complete self-review, sequential spec review, and sequential quality review at
`0/0/0`.

- [ ] **Step 10: Commit Task 5**

```powershell
git add frontend/e2e/phase3-story-planning.spec.ts `
  frontend/e2e/playwright.phase3.config.ts `
  frontend/e2e/run-phase3.mjs `
  frontend/package.json package.json scripts/run-tests.mjs `
  scripts/tests/phase3Suite.test.mjs `
  scripts/tests/run-tests.test.mjs
git commit -m "test: add full phase three browser gate"
```

### Task 6: Run Fresh Phase 3 Gates and Record Only Proven Facts

**Files:**
- Create: `docs/acceptance/2026-07-30-phase-3-story-planning.md`
- Modify: `CURRENT_PROJECT_STATE.md`
- Modify: `PRODUCT_DEVELOPMENT_PLAN.md`
- Modify: `DEVELOPMENT_LOG.md`
- Modify: `scripts/tests/phase3PlanContract.test.mjs`

- [ ] **Step 1: Run focused gates serially**

Run the final focused Python and Node lists from Tasks 1–5. Record exact exit
codes, passed/skipped/failed counts, database created/cleaned/remaining, and
cleanup residue. Do not reuse historical 3B/3C numbers.

- [ ] **Step 2: Run the final five gates from the implementation HEAD**

Run strictly in this order, stopping on the first failure:

```powershell
npm run test:browser:phase3
npm test
npm run test:integration
npm run build
git diff --check
```

After browser and integration, independently query only owned
`novel_creator_test_%` residue and verify owned processes, ports, temporary
roots, artifacts, and Vite `deps_temp_*` are zero. Do not inspect product data.
These are preliminary evidence used to populate the acceptance contract; they
do not become the final completion claim until Step 6 repeats the gates on the
unchanged final candidate tree.

- [ ] **Step 3: Write the acceptance RED contract**

Extend `phase3PlanContract.test.mjs` to require:

- the exact Phase 3D branch/baseline/schema;
- the closed read-model semantics;
- all fourteen formal browser outcomes;
- exact fresh gate numbers;
- `created=cleaned`, `remaining=0`;
- Provider `0`, product DB reads/writes `0/0`, live website `0`, UI bypass `0`,
  and secret findings `0`;
- explicit non-readiness for Phase 4 Writer, Phase 5 Finalization, real
  Provider, product DB, and content quality.

Run the test and observe RED because the report/fact documents are not updated.

- [ ] **Step 4: Write only verified acceptance facts**

Create the report with exactly:

```text
元数据
验收结论
已交付链路
独立审查
Fresh 最终门禁
隔离与未评估边界
下一步
```

Update the three truth documents so Phase 3D/Phase 3 is complete and Phase 4
Writer Loop is the only next product package. Do not claim content quality,
real model, product database, Finalization, or product Ready.

The report records only this stable evidence tuple:

```text
functional implementation HEAD
exact acceptance-package file list
command order
exit / pass / skip / fail counts
created / cleaned / remaining
owned process / port / temp / artifact / cache counts
provider / product DB / live / bypass / secret counts
```

Do not record wall-clock timestamps, durations, random database names, ports,
temporary paths, or the acceptance commit's self-referential SHA.

- [ ] **Step 5: Run report GREEN and review**

Run:

```powershell
node --test scripts/tests/phase3PlanContract.test.mjs
git diff --check
git status --short --branch
```

Complete independent spec review before independent quality review, both at
`0/0/0`.

- [ ] **Step 6: Re-run the five gates on the final candidate tree**

After the report, truth documents, and report contract are complete and no
further source change is planned, run again in strict order:

```powershell
npm run test:browser:phase3
npm test
npm run test:integration
npm run build
git diff --check
```

The acceptance report may cite only this run. If any field in the stable
evidence tuple differs and the report must be edited, update the report, rerun
its contract, and repeat all five gates again. Before each repetition verify
the functional implementation HEAD and exact acceptance-package file list.
Stop only when every reported field and the tested candidate are identical.

- [ ] **Step 7: Commit the acceptance package**

```powershell
git add docs/acceptance/2026-07-30-phase-3-story-planning.md `
  CURRENT_PROJECT_STATE.md PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md `
  scripts/tests/phase3PlanContract.test.mjs
git commit -m "docs: accept phase three story planning"
```

## Completion protocol

After Task 6, use `verification-before-completion` to inspect the complete
fresh output personally. Verify `git show --check`, commit file lists, clean
status, and zero owned residue. Then use `finishing-a-development-branch`:
fetch and compare `origin/main`, integrate without force push, and never clean
unrelated user files from another worktree. If the canonical main worktree is
dirty, use a fresh owned integration worktree rather than modifying or
deleting the user's content.

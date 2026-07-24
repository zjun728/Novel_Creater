# Phase 3B Volumes and Plots Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Phase 3A Planning aggregate foundation into the formal author-facing Volume and Plot workflow, including manual and AI-editable drafts, immutable history, server-authoritative next actions, and archived/superseded read-only behavior.

**Architecture:** Keep the single `PlanningService`/`PlanningRepository`/`planningStore` chain and the already-final v1.5 schema. Add one lease- and fencing-based Planning generation service around the production AI gateway, then expose two canonical routes backed by one shared Planning workspace and one local draft. The backend remains the sole authority for current/superseded/archived state and project next actions.

**Tech Stack:** Python 3.12, FastAPI, Pydantic 2, aiomysql, MySQL 8, Vue 3, Pinia 3, Vue Router 4, Naive UI, Node test runner, Playwright.

---

## Frozen decisions

- Baseline: `main@0b57f7987ee7be4cc5afe2dabda79b063cafb2d7`.
- Delivery branch: `codex/phase3b-volumes-plots`.
- Phase 3A already owns the final `planning-v1` aggregate and v1.5 tables. Phase 3B makes no schema change and adds no migration or compatibility path.
- `Volume` stores narrative direction only and never stores Plot or StoryBlock IDs.
- `Plot` stores a continuing story line and never stores StoryBlock IDs.
- StoryBlock/Stage/SceneTask editing and ChapterOutline remain Phase 3C work.
- Phase 3B does not weaken Phase 3A confirmation validation. A manual Draft
  containing only Volumes and Plots is savable but not confirmable. Confirmation
  is enabled only when the aggregate already contains the complete valid
  StoryBlock/Stage/SceneTask structure, such as a strict AI result, and the
  author has a read-only full-aggregate summary before confirming.
- Clicking “AI 生成规划” is the author’s explicit authorization to load the result into that exact saved Draft snapshot. If the Draft, project lifecycle, basis, head, binding, or fencing token changes before publish, the attempt is retained as succeeded/superseded evidence and does not change the Draft. There is no second “load result” API or button.
- AI generation never confirms a Planning revision, writes Canon, opens a ChapterSession, or calls a real Provider during automated acceptance.
- Missing model readiness disables only AI generation. Manual create, edit, save, and confirm remain available.
- The API, logs, errors, screenshots, reports, and artifacts expose no prompt, raw Provider output, corpus text, input manifest, API key, Authorization header, password, or DSN.
- The two routes use one `planningStore` and one `PlanningWorkspace.vue`; no `planningV2Store`, `volumeStore`, `plotStore`, `PlanningWorkspaceV2`, compatibility alias, or archived duplicate component is allowed.

## File map

### Backend files to create

- `backend/prompts/planning.py`: closed prompt construction from a frozen safe manifest.
- `backend/gateways/planning_provider.py`: strict Planning provider boundary using the production AI client.
- `backend/services/planning_generation.py`: reserve, call, publish, and status reconciliation.
- `backend/tests/unit/test_planning_prompt.py`
- `backend/tests/unit/test_planning_gateway.py`
- `backend/tests/unit/test_planning_generation_service.py`
- `backend/tests/integration/test_planning_generation.py`

### Backend files to modify

- `backend/repositories/planning.py`
- `backend/services/planning.py`
- `backend/routers/planning.py`
- `backend/repositories/projects.py`
- `backend/services/project_lifecycle.py`
- `backend/main.py` only if dependency construction requires the new gateway/service.
- Existing Planning, route, lifecycle, archive, and secret-boundary tests.

### Frontend files to create

- `frontend/src/views/ProjectPlanningView.vue`
- `frontend/src/application/planning/planningWorkspaceController.js`
- `frontend/src/components/planning/VolumeEditor.vue`
- `frontend/src/components/planning/PlotEditor.vue`
- `frontend/src/components/planning/PlanningHistoryDrawer.vue`
- Focused controller and view tests.

### Frontend files to modify

- `frontend/src/api/db/client.js`
- `frontend/src/stores/planningStore.js`
- `frontend/src/components/planning/PlanningWorkspace.vue`
- `frontend/src/router/projectRoutes.js`
- `frontend/src/components/layout/productShell.js`
- `frontend/src/views/ProjectOverviewView.vue`
- Existing API, Store, route, shell, overview, and runtime-inventory tests.

### Acceptance files to create or modify

- `frontend/e2e/phase3b-volumes-plots.spec.ts`
- `frontend/e2e/playwright.phase3b.config.ts`
- `frontend/e2e/run-phase3b.mjs`
- `scripts/tests/phase3bSuite.test.mjs`
- `scripts/run-tests.mjs`
- Root and frontend `package.json`
- `docs/acceptance/2026-07-24-phase-3b-volumes-plots.md`
- `CURRENT_PROJECT_STATE.md`
- `PRODUCT_DEVELOPMENT_PLAN.md`
- `DEVELOPMENT_LOG.md`

### Task 1: Freeze the Phase 3B Contract

**Files:**
- Modify: `scripts/tests/phase3PlanContract.test.mjs`
- Test: `scripts/tests/phase3PlanContract.test.mjs`

- [ ] **Step 1: Add a failing detailed-plan contract**

Require the committed Phase 3B plan to state:

```javascript
const required = [
  'codex/phase3b-volumes-plots',
  'no schema change',
  'planning_generation_attempts',
  'optimizeDeps',
  'npm run test:browser:phase3b',
]
```

The contract must also reject `planningV2Store`, `PlanningWorkspaceV2`,
`volumeStore`, `plotStore`, a real Provider, product database use, and a
separate result-load endpoint.

- [ ] **Step 2: Run RED**

```powershell
node --test scripts/tests/phase3PlanContract.test.mjs
```

Expected: FAIL until the contract reads this exact detailed plan and its frozen
decisions.

- [ ] **Step 3: Implement the narrow plan reader and run GREEN**

Keep the existing Phase 3 roadmap checks and add this one plan path:

```javascript
const phase3bPlan = 'docs/superpowers/plans/2026-07-24-phase-3b-volumes-and-plots.md'
```

Run the same command. Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add -- scripts/tests/phase3PlanContract.test.mjs
git commit -m "test: freeze phase three b delivery contract"
```

### Task 2: Define the Safe Planning Provider Boundary

**Files:**
- Create: `backend/prompts/planning.py`
- Create: `backend/gateways/planning_provider.py`
- Create: `backend/tests/unit/test_planning_prompt.py`
- Create: `backend/tests/unit/test_planning_gateway.py`

- [ ] **Step 1: Write prompt and gateway RED tests**

The prompt test must prove output requests the closed `DraftPlanningAggregate`
shape and never embeds secrets or raw corpus. The gateway test must require:

```python
class PlanningProvider(Protocol):
    async def generate(
        self,
        *,
        provider: PublicProviderRuntime,
        model_name: str,
        manifest: PlanningGenerationManifest,
        author_instructions: str,
    ) -> dict[str, object]: ...
```

It must reject extra Provider fields and parse only the closed Planning JSON
object.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_planning_prompt.py backend/tests/unit/test_planning_gateway.py -q
```

Expected: FAIL because the two production modules do not exist.

- [ ] **Step 3: Implement the minimal prompt and gateway**

Use the production backend AI client. The prompt may describe Volume/Plot and
preserve existing StoryBlock content, but it must not log or return prompt/raw
output. Convert malformed output to one fixed safe failure category.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_planning_prompt.py backend/tests/unit/test_planning_gateway.py -q
git add -- backend/prompts/planning.py backend/gateways/planning_provider.py backend/tests/unit/test_planning_prompt.py backend/tests/unit/test_planning_gateway.py
git commit -m "feat: add planning provider boundary"
```

### Task 3: Add Attempt, Lease, and Fencing Persistence

**Files:**
- Modify: `backend/repositories/planning.py`
- Modify: `backend/tests/unit/test_planning_repository.py`
- Test: `backend/tests/integration/test_planning_generation.py`

- [ ] **Step 1: Write repository RED tests**

Cover the exact final-schema operations:

```python
lock_generation_attempt_by_key(project_id, idempotency_key)
lock_generation_attempt(project_id, operation_id)
lock_active_generation_attempt(draft_id)
insert_generation_attempt(row)
next_fencing_token(draft_id)
supersede_generation_attempt(operation_id, fencing_token)
fail_generation_attempt(operation_id, fencing_token, failure_code)
succeed_generation_attempt(operation_id, fencing_token, result, result_hash)
load_generation_result_into_draft(
    draft_id, expected_revision, expected_hash, operation_id, content, content_hash
)
```

Require `active_slot=1` only while pending, monotonically increasing fencing
tokens, exact operation ownership, and `source_attempt_id` on successful Draft
load.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_planning_repository.py backend/tests/integration/test_planning_generation.py -q
```

Expected: FAIL on missing repository operations.

- [ ] **Step 3: Implement against `planning_generation_attempts`**

Use only the existing columns in `backend/schema/30_planning.sql`. Every
terminal update must include operation ID, pending status, active slot, and
fencing token in its CAS predicate.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_planning_repository.py backend/tests/integration/test_planning_generation.py -q
git add -- backend/repositories/planning.py backend/tests/unit/test_planning_repository.py backend/tests/integration/test_planning_generation.py
git commit -m "feat: persist planning generation leases"
```

### Task 4: Implement Generation Reserve, Publish, and Reconciliation

**Files:**
- Create: `backend/services/planning_generation.py`
- Create: `backend/tests/unit/test_planning_generation_service.py`
- Modify: `backend/tests/integration/test_planning_generation.py`

- [ ] **Step 1: Write service RED tests**

The command and public result are closed:

```python
@dataclass(frozen=True)
class GeneratePlanningDraft:
    project_id: str
    draft_id: str
    draft_revision: int
    draft_hash: str
    idempotency_key: str
    author_instructions: str

@dataclass(frozen=True)
class PlanningOperationResult:
    operation_id: str
    status: Literal["pending", "succeeded", "failed", "superseded"]
    failure_code: str | None
    model: PublicModelSummary
    loaded: bool
    loaded_draft_revision: int | None
```

Test same-key replay, different-fingerprint conflict, one active lease,
expired-lease supersession, cancellation, gateway failure, malformed result,
author save during generation, lifecycle/basis/head/binding drift, stale
fencing token, successful atomic load, and `get_operation` with no hidden
retry.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_planning_generation_service.py backend/tests/integration/test_planning_generation.py -q
```

- [ ] **Step 3: Implement the two-short-transaction workflow**

Reserve transaction:

```text
lock project -> basis -> Planning head/draft -> planning binding/provider
-> idempotency row -> active lease -> allocate fencing token -> commit
```

Call the gateway after the transaction closes.

Publish transaction:

```text
lock operation -> project -> basis -> head/draft -> binding
-> verify manifest/fingerprint/fence -> validate and normalize result
-> finish attempt -> CAS load exact Draft snapshot -> commit
```

If any authority changed, finish safely without loading the Draft. Never call
the gateway from `get_operation`.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_planning_generation_service.py backend/tests/integration/test_planning_generation.py -q
git add -- backend/services/planning_generation.py backend/tests/unit/test_planning_generation_service.py backend/tests/integration/test_planning_generation.py
git commit -m "feat: generate planning drafts safely"
```

### Task 5: Expose Safe Planning Operations and Explicit History Status

**Files:**
- Modify: `backend/services/planning.py`
- Modify: `backend/routers/planning.py`
- Modify: `backend/tests/unit/test_planning_service.py`
- Modify: `backend/tests/api/test_planning_routes.py`
- Modify: `backend/tests/api/test_public_domain_errors.py`
- Modify: `backend/tests/integration/test_planning_aggregate_lifecycle.py`

- [ ] **Step 1: Write API/read-model RED tests**

Add:

```text
POST /api/projects/{pid}/planning/drafts/{draft_id}/generate
GET  /api/projects/{pid}/planning/operations/{operation_id}
```

The generate body accepts only `draftRevision`, `draftHash`,
`idempotencyKey`, and bounded `authorInstructions`. The operation response
contains only `operationId`, four-state `status`, safe `failureCode`, safe
model summary, `loaded`, and `loadedDraftRevision`.

History items must include server-derived `current`, `superseded`, or
`archived` display status and safe fixed reasons. Planning state must expose
project lifecycle and basis status instead of hiding historical heads.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_planning_service.py backend/tests/api/test_planning_routes.py backend/tests/api/test_public_domain_errors.py backend/tests/integration/test_planning_aggregate_lifecycle.py -q
```

- [ ] **Step 3: Implement the router and read model**

Construct `PlanningGenerationService` through normal dependency injection.
Derive `capabilities.generate` from active lifecycle, current basis, active
Draft, and current `planning` binding readiness. Do not let readiness alter
manual capabilities.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_planning_service.py backend/tests/api/test_planning_routes.py backend/tests/api/test_public_domain_errors.py backend/tests/integration/test_planning_aggregate_lifecycle.py -q
git add -- backend/services/planning.py backend/routers/planning.py backend/tests
git commit -m "feat: expose planning operations and history"
```

### Task 6: Make Project Next Action Planning-Aware

**Files:**
- Modify: `backend/repositories/projects.py`
- Modify: `backend/services/project_lifecycle.py`
- Modify: `backend/tests/unit/test_project_lifecycle_service.py`
- Modify: `backend/tests/api/test_product_routes.py`
- Modify: `backend/tests/integration/test_project_archive.py`

- [ ] **Step 1: Write next-action RED tests**

Extend the single preparation snapshot with current Planning head, current
active Draft, and current/unknown generation operation facts. Assert the
priority:

```text
active write/unknown operation
-> existing valid Session/WorkingDraft
-> Seed -> Contract -> Bible
-> no current Planning head: establish Planning
-> current Planning Draft: continue Planning
-> current Planning head with no Phase3C Outline: phase 3C boundary
```

Both Planning actions target
`/projects/{encodedProjectId}/planning/volumes`. Archived projects expose
read-only Planning entry, not a write action.

- [ ] **Step 2: Run RED**

```powershell
python -m pytest backend/tests/unit/test_project_lifecycle_service.py backend/tests/api/test_product_routes.py backend/tests/integration/test_project_archive.py -q
```

- [ ] **Step 3: Implement one authoritative snapshot and priority**

Do not join Planning facts in the browser and do not add a second preparation
endpoint.

- [ ] **Step 4: Run GREEN and commit**

```powershell
python -m pytest backend/tests/unit/test_project_lifecycle_service.py backend/tests/api/test_product_routes.py backend/tests/integration/test_project_archive.py -q
git add -- backend/repositories/projects.py backend/services/project_lifecycle.py backend/tests
git commit -m "feat: route project next action through planning"
```

### Task 7: Extend the Single Frontend API and Store

**Files:**
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/planningStore.js`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/planningStore.test.mjs`

- [ ] **Step 1: Write frontend RED tests**

Require:

```javascript
api.planning.generateDraft(projectId, draftId, command)
api.planning.getOperation(projectId, operationId)
```

Transport allowlists must discard provider/model/prompt/raw output/manifest
fields. Store tests cover one active generation, unknown-result reconciliation
by GET only, old-project/old-operation fencing, successful authoritative Draft
load, failed/superseded non-overwrite, and model-unready manual work.

- [ ] **Step 2: Add same-project route preservation RED tests**

`ensureLoaded(projectId)` must not reload or clear dirty local content when
Volumes and Plots routes switch inside the same project. Forced reload remains
an explicit recovery action.

- [ ] **Step 3: Run RED**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/planningStore.test.mjs
```

- [ ] **Step 4: Implement and run GREEN**

Keep the existing `usePlanningStore`. Add operation state and reconciliation,
but no new Store.

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/src/api/db/client.js frontend/src/stores/planningStore.js frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/planningStore.test.mjs
git commit -m "feat: manage planning generation in one store"
```

### Task 8: Add Canonical Routes, Navigation, and Shared Editors

**Files:**
- Create: `frontend/src/views/ProjectPlanningView.vue`
- Create: `frontend/src/application/planning/planningWorkspaceController.js`
- Create: `frontend/src/components/planning/VolumeEditor.vue`
- Create: `frontend/src/components/planning/PlotEditor.vue`
- Create: `frontend/src/components/planning/PlanningHistoryDrawer.vue`
- Modify: `frontend/src/components/planning/PlanningWorkspace.vue`
- Modify: `frontend/src/router/projectRoutes.js`
- Modify: `frontend/src/components/layout/productShell.js`
- Modify: `frontend/src/views/ProjectOverviewView.vue`
- Modify: focused frontend tests.

- [ ] **Step 1: Write controller/editor RED tests**

Cover add, edit, reorder, retire, local undo, stable client keys, no reverse
StoryBlock IDs, manual empty Draft, save, confirm, generate, safe recovery,
read-only history, and archived/superseded denial.

Also prove a Volume/Plot-only manual Draft can save but cannot confirm, while a
complete valid aggregate exposes a read-only full summary and may use the
existing confirmation command.

- [ ] **Step 2: Write routing and interaction RED tests**

Require exactly:

```text
/projects/:projectId/planning/volumes
/projects/:projectId/planning/plots
```

Both mount the same `ProjectPlanningView` and shared workspace. Test
direct navigation, refresh, back/forward, selected shell item, active and
archived navigation, server-provided next action, and no `/planning` alias.

- [ ] **Step 3: Write leave-protection RED tests**

Volumes↔Plots in one project preserves dirty state without a prompt. Leaving
Planning, switching project, or unloading prompts once. AI generation uses a
workspace-local clear read-only overlay; confirmation alone uses the global
blocking overlay.

- [ ] **Step 4: Run RED**

```powershell
node --test frontend/tests/unit/planningWorkspaceController.test.mjs frontend/tests/unit/projectPlanningView.test.mjs frontend/tests/unit/projectRoutes.test.mjs frontend/tests/unit/productShell.test.mjs frontend/tests/unit/projectPreparationOverview.test.mjs
```

- [ ] **Step 5: Implement the shared workspace**

Volume fields:

```text
title, coreChange, mainPressure, ensembleFocus, forbiddenEvents
```

Plot fields:

```text
title, plotType, storyQuestion, futureDirection, expectedPayoff, relatedCharacters
```

Use one local aggregate, one save action, one confirmation action, and one
history drawer.

- [ ] **Step 6: Update runtime inventory**

Move `PlanningWorkspace.vue` and `planningStore.js` from future-only inventory
into the active route graph. Continue rejecting retired planning components,
duplicate Stores, and Phase3C navigation.

- [ ] **Step 7: Run GREEN and commit**

```powershell
npm --prefix frontend run test:unit
git add -- frontend/src frontend/tests/unit
git commit -m "feat: add volume and plot planning workspace"
```

### Task 9: Add the Formal Phase 3B Browser Gate

**Files:**
- Create: `frontend/e2e/phase3b-volumes-plots.spec.ts`
- Create: `frontend/e2e/playwright.phase3b.config.ts`
- Create: `frontend/e2e/run-phase3b.mjs`
- Create: `scripts/tests/phase3bSuite.test.mjs`
- Modify: `scripts/run-tests.mjs`
- Modify: `package.json`
- Modify: `frontend/package.json`

- [ ] **Step 1: Write the runner contract RED test**

Require one exact runner/spec/config, UI-only browser actions, loopback random
ports, scheduler off, strict fake Planning gateway only at the external
boundary, random disposable MySQL 8, and reverse owned-resource cleanup.

- [ ] **Step 2: Run RED**

```powershell
node --test scripts/tests/phase3bSuite.test.mjs
```

- [ ] **Step 3: Implement the browser workflow**

The formal UI flow must prove:

1. model-unready manual Draft remains available;
2. add/reorder Volumes and Plots and save without weakening the complete-plan
   confirmation gate;
3. strict fake AI generation loads a complete valid aggregate only into the
   unchanged saved Draft;
4. the author sees the full read-only aggregate summary before confirming R1;
5. an author edit during generation is never overwritten;
6. unknown result is reconciled by operation ID without a second generation;
7. archived and superseded histories are readable and all writes are denied;
8. refresh/back/forward preserve canonical routes;
9. next action is backend-authoritative;
10. responses, logs, and artifacts are secret-safe.

The spec must not use `page.request`, `page.route`, `page.evaluate`, browser
`fetch`, Axios, or another API write bypass.

- [ ] **Step 4: Run GREEN**

```powershell
node --test scripts/tests/phase3bSuite.test.mjs
npm run test:browser:phase3b
```

Expected: all owned databases/processes/ports/temp roots cleaned; database
created count equals cleaned count and remaining is 0.

- [ ] **Step 5: Commit**

```powershell
git add -- frontend/e2e scripts package.json frontend/package.json
git commit -m "test: add phase three b browser gate"
```

### Task 10: Package Acceptance and Documentation

**Files:**
- Create: `docs/acceptance/2026-07-24-phase-3b-volumes-plots.md`
- Modify: `CURRENT_PROJECT_STATE.md`
- Modify: `PRODUCT_DEVELOPMENT_PLAN.md`
- Modify: `DEVELOPMENT_LOG.md`

- [ ] **Step 1: Run focused gates**

```powershell
python -m pytest backend/tests/unit/test_planning_domain.py backend/tests/unit/test_planning_repository.py backend/tests/unit/test_planning_service.py backend/tests/unit/test_planning_generation_service.py backend/tests/api/test_planning_routes.py -q
node --test frontend/tests/unit/planningStore.test.mjs frontend/tests/unit/planningWorkspaceController.test.mjs frontend/tests/unit/projectPlanningView.test.mjs scripts/tests/phase3bSuite.test.mjs
```

- [ ] **Step 2: Run package gates serially**

```powershell
npm run test:browser:phase3b
npm test
npm run test:integration
npm run build
git diff --check
```

After browser and integration, independently verify owned process/port/temp
root residue is 0 and only disposable databases named
`novel_creator_test_<32 lowercase hex>` were created and removed.

- [ ] **Step 3: Obtain sequential reviews**

First request an independent specification review. Fix all findings and repeat
until Critical/Important/Minor = `0/0/0`. Only then request an independent
quality review and repeat to `0/0/0`.

- [ ] **Step 4: Write only fresh evidence**

Record exact fresh test counts, exit codes, created/cleaned/remaining database
counts, browser goal count, build module count, and secret-scan result. Do not
reuse Phase3A or historical numbers.

- [ ] **Step 5: Commit package acceptance**

```powershell
git add -- docs CURRENT_PROJECT_STATE.md PRODUCT_DEVELOPMENT_PLAN.md DEVELOPMENT_LOG.md
git commit -m "test: accept volume and plot planning"
git show --check --stat --oneline HEAD
git status --short --branch
```

## Completion boundary

Phase 3B is complete only when authors can manually or explicitly with AI build
and revise Volumes and Plots through the real product UI, immutable history and
next actions are server-authoritative, archived/superseded states are read-only,
and every package gate is fresh and green.

Phase 3B completion does not claim StoryBlock editing, ChapterOutline
confirmation, chapter writing readiness, Canon writes, real Provider
acceptance, product database readiness, or novel-content quality acceptance.

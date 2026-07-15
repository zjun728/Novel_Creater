# Story-engine Recovery Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give ProjectView a production, read-only way to discover interrupted Provider story-engine batches and let the author reconcile each batch explicitly without a Provider call or test-only path.

**Architecture:** Add one bounded project-scoped GET route backed by a repository query filtered to the current selected seed and binding. Load those public summaries with the creation-contract state, render explicit per-row recovery controls in the existing story-engine step, and exercise the controls through the formal M2 Playwright recovery spec. The existing POST reconcile transaction remains the only state-changing recovery operation.

**Tech Stack:** FastAPI, Pydantic, async MySQL repository/service, Vue 3, Pinia, Node `node:test`, pytest, Playwright, disposable MySQL 8.4.

---

### Task 1: Add the bounded read-only recovery discovery API

**Files:**
- Modify: `backend/repositories/story_engines.py`
- Modify: `backend/services/story_engines.py`
- Modify: `backend/routers/story_engines.py`
- Modify: `backend/tests/support/story_engine_fakes.py`
- Modify: `backend/tests/unit/test_story_engine_service.py`
- Modify: `backend/tests/api/test_story_engine_routes.py`
- Modify: `backend/tests/api/test_route_inventory.py`
- Modify: `backend/tests/integration/test_story_engine_batches.py`

- [ ] **Step 1: Write failing service and route tests**

Add a memory-repository recovery list and tests that require current-project filtering, a bounded public result, and no gateway call:

```python
async def test_recoverable_batches_are_read_only_bounded_public_summaries():
    harness = StoryEngineHarness()
    harness.repository.recoverable_rows = [
        {
            "id": "batch-running",
            "status": "running",
            "public_error_code": None,
            "created_at": 10,
            "finished_at": None,
        },
        {
            "id": "batch-unknown",
            "status": "outcome_unknown",
            "public_error_code": "outcome_unknown",
            "created_at": 20,
            "finished_at": 30,
        },
    ]

    result = await harness.service.list_recoverable("p1")

    assert [item.id for item in result] == ["batch-running", "batch-unknown"]
    assert result[1].public_error_code == "outcome_unknown"
    assert harness.gateway.calls == 0
    assert harness.repository.recoverable_calls == [("p1", 10)]
```

Extend the API route stub with `list_recoverable` and assert the exact response keys:

```python
response = client.get("/api/projects/p1/story-engine-batches/recoverable")
assert response.status_code == 200
assert response.json() == {
    "items": [{
        "id": "batch-running",
        "status": "running",
        "publicErrorCode": None,
        "createdAt": 10,
        "finishedAt": None,
    }]
}
assert set(response.json()["items"][0]) == {
    "id", "status", "publicErrorCode", "createdAt", "finishedAt",
}
```

Add `("GET", "/api/projects/{pid}/story-engine-batches/recoverable")` to the formal route inventory. Define the static `/recoverable` route before `/{batch_id}` so FastAPI never interprets `recoverable` as a batch ID.

- [ ] **Step 2: Run the focused tests and verify RED**

```powershell
python -m pytest backend/tests/unit/test_story_engine_service.py backend/tests/api/test_story_engine_routes.py backend/tests/api/test_route_inventory.py -q
```

Expected: failures state that `list_recoverable`, the repository fake method, and the static GET route do not exist. Existing story-engine tests remain green.

- [ ] **Step 3: Implement the typed service result and repository query**

Add this public service type:

```python
class RecoverableStoryEngineBatchResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    id: str
    status: Literal["reserved", "running", "outcome_unknown"]
    public_error_code: str | None
    created_at: int
    finished_at: int | None
```

Add a read-only service method using `connection_factory`, not a transaction and not the Provider gateway:

```python
async def list_recoverable(
    self, project_id: str
) -> tuple[RecoverableStoryEngineBatchResult, ...]:
    async with self.connection_factory() as session:
        if await self.repository.read_project(session, project_id) is None:
            raise StoryEngineBatchNotFound()
        rows = await self.repository.list_recoverable_batches(
            session, project_id, limit=10
        )
    return tuple(
        RecoverableStoryEngineBatchResult(
            id=row["id"],
            status=row["status"],
            public_error_code=row.get("public_error_code"),
            created_at=int(row["created_at"]),
            finished_at=row.get("finished_at"),
        )
        for row in rows
    )
```

Implement the repository query with a fixed upper bound and no dynamic SQL fragments:

```python
async def list_recoverable_batches(
    self, session, project_id: str, *, limit: int
):
    if limit != 10:
        raise ValueError("recoverable batch limit must be 10")
    return await session.fetchall(
        """SELECT batch.id,batch.status,batch.public_error_code,
                  batch.created_at,batch.finished_at
             FROM story_engine_batches batch
             JOIN project_selected_seeds selected
               ON selected.project_id=batch.project_id
              AND selected.seed_id=batch.seed_id
              AND selected.seed_revision_id=batch.seed_revision_id
              AND selected.seed_hash=batch.seed_hash
             JOIN project_model_binding_heads binding
               ON binding.project_id=batch.project_id
              AND binding.binding_revision_id=batch.binding_revision_id
              AND binding.content_hash=batch.binding_hash
            WHERE batch.project_id=%s
              AND batch.source_type='provider'
              AND batch.status IN ('reserved','running','outcome_unknown')
            ORDER BY batch.created_at ASC,batch.id ASC
            LIMIT 10""",
        (project_id,),
    )
```

The route serializer must construct only the five approved fields:

```python
def _public_recoverable_batch(result) -> dict:
    return {
        "id": result.id,
        "status": result.status,
        "publicErrorCode": result.public_error_code,
        "createdAt": result.created_at,
        "finishedAt": result.finished_at,
    }


@router.get("/projects/{pid}/story-engine-batches/recoverable")
async def list_recoverable_batches(
    pid: str,
    service=Depends(get_story_engine_service),
):
    return {
        "items": [
            _public_recoverable_batch(item)
            for item in await service.list_recoverable(pid)
        ]
    }
```

- [ ] **Step 4: Add a disposable-MySQL integration test for exact filtering**

In `test_story_engine_batches.py`, insert batches that differ by project, manual source, succeeded status, stale selected-seed revision, and stale binding revision. Assert the query returns only the current project's provider rows in `reserved`, `running`, and `outcome_unknown`, in ascending `(created_at, id)` order, and never more than ten.

The test must use the existing MySQL test fixture and a random test database. It must not use product `MYSQL_*` or call the gateway.

- [ ] **Step 5: Run backend GREEN verification**

```powershell
python -m pytest backend/tests/unit/test_story_engine_service.py backend/tests/api/test_story_engine_routes.py backend/tests/api/test_route_inventory.py -q
python -m pytest backend/tests/integration/test_story_engine_batches.py -m mysql -q
```

Expected: all selected tests pass, gateway call count stays zero, and the disposable database fixture reports no remaining test database.

### Task 2: Load and render recoverable batches in the production wizard

**Files:**
- Modify: `frontend/src/api/db/client.js`
- Modify: `frontend/src/stores/creationContractStore.js`
- Modify: `frontend/src/components/project/contract/StoryEngineStep.vue`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`
- Modify: `frontend/tests/unit/creationContractStore.test.mjs`

- [ ] **Step 1: Write failing API/store tests**

Add the exact client route assertion:

```javascript
await api.storyEngines.recoverable('project-1')
assert.deepEqual(lastCall(), [
  'GET',
  '/api/projects/project-1/story-engine-batches/recoverable',
])
```

Extend every existing `store.load()` test double with `api.storyEngines.recoverable`. Add focused tests for discovery and explicit-only reconciliation:

```javascript
test('load installs only the current project recoverable summaries', async () => {
  await withApiMethods([
    [api.contracts.draft, 'get', async () => null],
    [api.contracts, 'head', async () => ({ hasContract: false })],
    [api.storyEngines, 'recoverable', async projectId => ({
      items: [{ id: `${projectId}-running`, status: 'running' }],
    })],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    await store.load('project-1')
    assert.deepEqual(store.recoverableBatches, [
      { id: 'project-1-running', status: 'running' },
    ])
  })
})

test('reconcile removes not_started and retains outcome_unknown without generation', async () => {
  let generations = 0
  const results = new Map([
    ['reserved', { id: 'reserved', status: 'failed', publicErrorCode: 'not_started' }],
    ['running', { id: 'running', status: 'outcome_unknown', publicErrorCode: 'outcome_unknown' }],
  ])
  await withApiMethods([
    [api.storyEngines, 'generate', async () => { generations += 1 }],
    [api.storyEngines, 'reconcile', async (_projectId, batchId) => results.get(batchId)],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    assert.equal('installRecoverableForTestOnly' in store, false)
    // Establish rows through the normal load method in the complete test.
    assert.equal(generations, 0)
    await store.reconcileRecoverableBatch('project-1', 'reserved')
    await store.reconcileRecoverableBatch('project-1', 'running')
    assert.deepEqual(store.recoverableBatches.map(row => row.id), ['running'])
    assert.equal(store.providerOutcomeUnknown, true)
    assert.equal(generations, 0)
  })
})
```

Do not add `installRecoverableForTestOnly`; the assertion above proves that no test-only setter exists. Seed the initial list through `store.load()` in the complete test.

- [ ] **Step 2: Run frontend tests and verify RED**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/creationContractStore.test.mjs
```

Expected: failures identify the missing client method, recovery state, load call, and explicit recovery command.

- [ ] **Step 3: Implement guarded recovery state**

Add the client method:

```javascript
recoverable: projectId => get(
  `/projects/${segment(projectId)}/story-engine-batches/recoverable`,
),
```

Add `recoverableBatches = shallowRef([])` and `reconcilingBatchIds = ref([])` to the store. Clear both on project changes. Include the GET in the existing guarded `load()`:

```javascript
const [loadedDraft, loadedHead, recovery] = await Promise.all([
  readDraft(targetProjectId),
  api.contracts.head(targetProjectId),
  api.storyEngines.recoverable(targetProjectId),
])

if (currentContractState(loadGuard, generation, targetProjectId, stateGeneration)) {
  recoverableBatches.value = Array.isArray(recovery?.items)
    ? recovery.items.map(item => ({ ...item }))
    : []
}
```

Implement one explicit command per row. It must not call `generate`, must ignore a repeated click while the same ID is busy, and must not install a result after the active project changes:

```javascript
async function reconcileRecoverableBatch(nextProjectId, batchId) {
  const targetProjectId = enterProject(nextProjectId)
  const normalizedId = String(batchId || '')
  if (!normalizedId) throw new TypeError('batchId is required')
  if (reconcilingBatchIds.value.includes(normalizedId)) return null
  const stateGeneration = contractStateGeneration
  reconcilingBatchIds.value = [...reconcilingBatchIds.value, normalizedId]
  try {
    const result = await api.storyEngines.reconcile(targetProjectId, normalizedId)
    if (projectId.value !== targetProjectId || contractStateGeneration !== stateGeneration) {
      return result
    }
    if (result.status === 'failed' && result.publicErrorCode === 'not_started') {
      recoverableBatches.value = recoverableBatches.value.filter(
        item => item.id !== normalizedId,
      )
    } else {
      recoverableBatches.value = recoverableBatches.value.map(
        item => item.id === normalizedId ? { ...item, ...result } : item,
      )
    }
    if (result.status === 'outcome_unknown') engineBatch.value = result
    return result
  } catch (failure) {
    error.value = publicError(failure)
    throw failure
  } finally {
    reconcilingBatchIds.value = reconcilingBatchIds.value.filter(
      id => id !== normalizedId,
    )
  }
}
```

- [ ] **Step 4: Render accessible production controls**

Add `recoveryNotice = ref('')` locally to `StoryEngineStep.vue`. Set it to `未开始，已安全结束` when a reconcile result is `failed/not_started`, set it to `结果未知，系统不会自动重试` for `outcome_unknown`, and clear it before each explicit reconcile. Add a section before the existing generation actions when `recoverableBatches.length > 0`:

```vue
<section class="recovery-ledger" aria-labelledby="recoverable-batches-heading">
  <h4 id="recoverable-batches-heading">待恢复的故事发动机批次</h4>
  <n-alert v-if="recoveryNotice" type="info">{{ recoveryNotice }}</n-alert>
  <article v-for="item in store.recoverableBatches" :key="item.id">
    <p>{{ recoveryStatusText(item) }}</p>
    <code>{{ boundedBatchId(item.id) }}</code>
    <n-button
      size="small"
      :aria-label="`核对批次 ${boundedBatchId(item.id)}`"
      :loading="store.reconcilingBatchIds.includes(item.id)"
      :disabled="store.reconcilingBatchIds.includes(item.id)"
      @click="reconcileRecoverable(item)"
    >
      核对本批次结果
    </n-button>
  </article>
</section>
```

`boundedBatchId` returns only the last eight ID characters. `recoveryStatusText` maps `reserved`, `running`, and `outcome_unknown` to fixed public Chinese labels and does not display backend private text. `reconcileRecoverable` catches the store error into the existing bounded `errorMessage`; it does not retry.

- [ ] **Step 5: Run frontend GREEN verification**

```powershell
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/creationContractStore.test.mjs
npm --prefix frontend run build
```

Expected: unit tests and production build pass with no direct Provider call and no test-only state setter.

### Task 3: Complete the formal recovery browser goal

**Files:**
- Create: `frontend/e2e/m2-wizard-recovery.spec.ts`
- Modify: `frontend/e2e/run-milestone2.mjs`
- Modify: `scripts/tests/milestone2-browser-contract.test.mjs`
- Modify: `scripts/tests/browser-runner.test.mjs`

- [ ] **Step 1: Write the recovery spec and keep the source gate RED until production controls exist**

The spec begins only at the formal project route and installs the runtime observer before user actions. It must not import the product API client or use page/request/fetch/route interception.

```typescript
await page.goto('/project/00000000-0000-0000-0000-000000000201')
await expect(page.getByRole('heading', {
  name: '待恢复的故事发动机批次',
})).toBeVisible()

await page.getByRole('button', { name: /核对批次 00000701/ }).click()
await expect(page.getByText('结果未知')).toBeVisible()
await page.getByRole('button', { name: /核对批次 00000702/ }).click()
await expect(page.getByText('未开始，已安全结束')).toBeVisible()

await page.reload()
await expect(page.getByRole('button', {
  name: /核对批次 00000701/,
})).toBeVisible()
await expect(page.getByRole('button', {
  name: /核对批次 00000702/,
})).toHaveCount(0)
```

The exact recovery write allowlist is:

```javascript
[
  {
    method: 'POST',
    path: /\/story-engine-batches\/[^/]+\/reconcile$/,
    count: 2,
    statuses: [200],
  },
]
```

If the same formal spec also proves double-tab draft CAS, add only manual batch writes and draft writes; never add Provider generation:

```javascript
[
  { method: 'POST', path: /\/story-engine-batches\/manual$/, count: 2, statuses: [201] },
  { method: 'PUT', path: /\/contract-draft$/, count: 2, statuses: [200, 409] },
  { method: 'POST', path: /\/story-engine-batches\/[^/]+\/reconcile$/, count: 2, statuses: [200] },
]
```

The spec separately counts response statuses and asserts exactly one draft save is 200 and one is 409. The runtime observer uses one rule for the shared method/path so its first-match behavior cannot hide a status mismatch.

- [ ] **Step 2: Freeze the programmatic runner to the exact spec/scenario map**

Both the CLI and exported validator must accept only this closed map:

```javascript
const FORMAL_SPECS = new Map([
  ['e2e/m2-foundation-regression.spec.ts', 'foundation'],
  ['e2e/m2-wizard-manual.spec.ts', 'manual'],
  ['e2e/m2-wizard-recovery.spec.ts', 'recovery'],
  ['e2e/m2-settings-assets-corpus.spec.ts', 'settings'],
])
```

Reject an unknown path, a duplicate path, a known path paired with the wrong scenario, and a subset/reordered no-argument default. Injected unit tests may pass the exact four entries only; they may inject process runners but may not extend the spec set.

- [ ] **Step 3: Run source/runner tests and verify GREEN**

```powershell
node --test scripts/tests/milestone2-browser-contract.test.mjs scripts/tests/browser-runner.test.mjs scripts/tests/runtime-observer.test.mjs scripts/tests/run-tests.test.mjs
```

Expected: all four formal import closures pass; direct requests and route mocks still fail their negative tests; the recovery graph contains no Provider creation route; arbitrary spec/scenario input is rejected.

- [ ] **Step 4: Run the disposable browser recovery and full M2 browser suite**

```powershell
npm run test:browser:m2
```

Expected: all four specs pass. Recovery performs exactly two reconcile writes, zero Provider-generation writes, and leaves only the `outcome_unknown` row discoverable after reload. Every runner-owned database, server process, log, and temporary corpus directory is removed.

### Task 4: Integrate with M2E Task 3 and commit verified work

**Files:**
- Modify only files already named by M2E Task 3 and this recovery plan.

- [ ] **Step 1: Run the complete Task 3 verification set**

```powershell
python -m pytest backend/tests/unit/test_story_engine_service.py backend/tests/api/test_story_engine_routes.py backend/tests/api/test_route_inventory.py -q
python -m pytest backend/tests/integration/test_story_engine_batches.py -m mysql -q
node --test frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/creationContractStore.test.mjs
node --test scripts/tests/milestone2-browser-contract.test.mjs scripts/tests/browser-runner.test.mjs scripts/tests/runtime-observer.test.mjs scripts/tests/run-tests.test.mjs
npm run test:browser:m2
npm --prefix frontend run build
git diff --check
```

Expected: every command exits 0; no Provider/model call occurs; all MySQL use is disposable; cleanup receipts show no remaining database, process, or temporary corpus path.

- [ ] **Step 2: Self-review against both plans**

Check M2E Task 3 and `2026-07-15-story-engine-recovery-discovery-design.md` line by line. Reject `.first()`/`nth()` order selectors, direct request helpers, route mocks, test-only batch-ID inputs, arbitrary spec paths, broad write regexes, secret-bearing response fields, hidden retries, automatic reconcile, and any Provider-generation write in recovery.

- [ ] **Step 3: Commit the complete Task 3 change**

```powershell
git add package.json frontend/package.json scripts/run-tests.mjs scripts/tests/run-tests.test.mjs scripts/tests/milestone2-browser-contract.test.mjs scripts/tests/browser-runner.test.mjs frontend/e2e/run-milestone2.mjs frontend/e2e/m2-foundation-regression.spec.ts frontend/e2e/m2-wizard-manual.spec.ts frontend/e2e/m2-wizard-recovery.spec.ts frontend/e2e/m2-settings-assets-corpus.spec.ts backend/repositories/story_engines.py backend/services/story_engines.py backend/routers/story_engines.py backend/tests/support/story_engine_fakes.py backend/tests/unit/test_story_engine_service.py backend/tests/api/test_story_engine_routes.py backend/tests/api/test_route_inventory.py backend/tests/integration/test_story_engine_batches.py frontend/src/api/db/client.js frontend/src/stores/creationContractStore.js frontend/src/components/project/contract/StoryEngineStep.vue frontend/tests/unit/writerCoreApi.test.mjs frontend/tests/unit/creationContractStore.test.mjs
git commit -m "test: cover milestone two product flows"
```

Do not push, merge, rebuild the product database, or run the L5 Provider acceptance in this task.

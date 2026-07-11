# M2D Creation Contract Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate the approved five-step CreationContractWizard, immutable contract head/history, model readiness, global assets, and local corpus controls into the formal ProjectView and Settings pages.

**Architecture:** The API client is the only browser transport; Pinia stores own remote state and structured conflicts; pure wizard-state functions own step gating. Vue components only render and dispatch store commands. Formal draft/selection state is always restored from the backend and never from localStorage.

**Tech Stack:** Vue 3, Pinia 3, Naive UI, Vite, JavaScript modules, Node `node:test`.

---

### Task 1: Structured API errors and exact M2 client surface

**Files:**
- Create: `frontend/src/api/db/api-error.js`
- Modify: `frontend/src/api/db/client.js`
- Create: `frontend/tests/unit/apiErrors.test.mjs`
- Modify: `frontend/tests/unit/writerCoreApi.test.mjs`

- [ ] **Step 1: Write RED tests with injected `fetch`**

```javascript
import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError, parseApiError } from '../../src/api/db/api-error.js'

test('public api errors keep stable metadata and discard raw secret text', async () => {
  const response = new Response(JSON.stringify({
    code: 'contract_conflict', message: '项目状态已更新', correlationId: 'cid-1',
    debug: 'browser-secret-must-not-leak',
  }), { status: 409, headers: { 'content-type': 'application/json' } })
  const error = await parseApiError(response)
  assert.ok(error instanceof ApiError)
  assert.deepEqual(
    { status: error.status, code: error.code, message: error.message, correlationId: error.correlationId },
    { status: 409, code: 'contract_conflict', message: '项目状态已更新', correlationId: 'cid-1' },
  )
  assert.equal(JSON.stringify(error).includes('browser-secret-must-not-leak'), false)
})
```

Add client contract assertions for seed CRUD/selection, bindings, story-engine provider/manual/reconcile, assets/recommendations, bounded corpus discovery/import/status, contract draft/preview/confirm/history/clone.

- [ ] **Step 2: Verify RED**

```powershell
node --test frontend/tests/unit/apiErrors.test.mjs frontend/tests/unit/writerCoreApi.test.mjs
```

- [ ] **Step 3: Implement the safe error object and endpoint namespaces**

```javascript
// frontend/src/api/db/api-error.js
export class ApiError extends Error {
  constructor({ status, code = 'request_failed', message = '请求失败', correlationId = '' }) {
    super(message)
    this.name = 'ApiError'
    this.status = Number(status || 0)
    this.code = String(code || 'request_failed')
    this.correlationId = String(correlationId || '')
  }

  toJSON() {
    return { name: this.name, status: this.status, code: this.code, message: this.message, correlationId: this.correlationId }
  }
}

export async function parseApiError(response) {
  let body = {}
  try { body = await response.json() } catch { body = {} }
  return new ApiError({
    status: response.status,
    code: body.code || body.detail?.code,
    message: body.message || body.detail?.message || `请求失败 (${response.status})`,
    correlationId: body.correlationId || body.detail?.correlationId,
  })
}
```

Every write method accepts explicit expected revision/idempotency fields; no client method accepts provider key/base URL, corpus absolute path, or raw full text.

- [ ] **Step 4: Verify client tests GREEN**

Run Step 2. Expected: both files pass; raw body/debug values are not retained.

- [ ] **Step 5: Commit client surface**

```powershell
git add frontend/src/api/db/api-error.js frontend/src/api/db/client.js frontend/tests/unit/apiErrors.test.mjs frontend/tests/unit/writerCoreApi.test.mjs
git commit -m "feat: add safe M2 frontend API client"
```

### Task 2: Pure wizard state and Pinia stores

**Files:**
- Create: `frontend/src/domain/creation-contract/wizard-state.js`
- Modify: `frontend/src/stores/seedStore.js`
- Modify: `frontend/src/stores/providerStore.js`
- Create: `frontend/src/stores/creationContractStore.js`
- Create: `frontend/src/stores/creationAssetStore.js`
- Create: `frontend/src/stores/corpusStore.js`
- Create: `frontend/tests/unit/wizardState.test.mjs`
- Create: `frontend/tests/unit/seedStore.test.mjs`
- Create: `frontend/tests/unit/creationContractStore.test.mjs`
- Create: `frontend/tests/unit/creationAssetStore.test.mjs`
- Create: `frontend/tests/unit/corpusStore.test.mjs`
- Create: `frontend/tests/unit/modelBindingStore.test.mjs`

- [ ] **Step 1: Write RED tests for step gates and recovery states**

```javascript
import assert from 'node:assert/strict'
import test from 'node:test'
import { nextAllowedStep } from '../../src/domain/creation-contract/wizard-state.js'

test('wizard advances only when each backend-owned decision is complete', () => {
  assert.equal(nextAllowedStep({ selectedSeed: null }), 1)
  assert.equal(nextAllowedStep({ selectedSeed: { id: 's1' }, selectedEngine: null }), 2)
  assert.equal(nextAllowedStep({ selectedSeed: { id: 's1' }, selectedEngine: { id: 'e1' }, primaryStyle: null }), 3)
  assert.equal(nextAllowedStep({ selectedSeed: { id: 's1' }, selectedEngine: { id: 'e1' }, primaryStyle: { id: 'st1' }, assetsLoaded: true }), 5)
})
```

Store tests cover stale-request guards, refresh reload, draft CAS, 409 requiring reload, outcome_unknown without automatic generation, confirmation replay, backend-only state, eight binding rows, and no localStorage access. They also prove UI readiness comes from backend `{ready,reasons,seedRevisionId,seedHash,bindingRevision,bindingHash}` and turns false for either seed or binding drift. Draft saving is explicit and deterministic: step 1 persists through selected-seed only; clicking “保存并继续” after engine, style and asset-scope steps performs exactly one draft PUT per step (three total in the normal flow). Field changes never autosave. Refresh restores the last completed saved step; unsaved edits prompt before navigation and may be discarded.

- [ ] **Step 2: Verify RED**

```powershell
node --test frontend/tests/unit/wizardState.test.mjs frontend/tests/unit/seedStore.test.mjs frontend/tests/unit/creationContractStore.test.mjs frontend/tests/unit/creationAssetStore.test.mjs frontend/tests/unit/corpusStore.test.mjs frontend/tests/unit/modelBindingStore.test.mjs
```

- [ ] **Step 3: Implement pure gating and focused stores**

```javascript
// frontend/src/domain/creation-contract/wizard-state.js
export function nextAllowedStep(state = {}) {
  if (!state.selectedSeed) return 1
  if (!state.selectedEngine) return 2
  if (!state.primaryStyle) return 3
  if (!state.assetsLoaded) return 4
  return 5
}

export function contractReady({ readiness } = {}) {
  return Boolean(readiness?.ready === true && Array.isArray(readiness?.reasons) && readiness.reasons.length === 0)
}

export function providerRetryAction(batch) {
  return batch?.status === 'outcome_unknown' ? 'create-new-batch-with-explicit-confirmation' : 'none'
}
```

`creationContractStore` exposes `load`, `saveDraft`, `preview`, `confirm`, `cloneRevision`, and `reconcileBatch`; it never calls itself recursively or auto-retries generation. Asset and corpus stores cache immutable revision reads by ID+hash and invalidate only list/head queries.

- [ ] **Step 4: Verify all store tests GREEN**

Run Step 2. Expected: all pass and the tests' fake localStorage throws if accessed.

- [ ] **Step 5: Commit state layer**

```powershell
git add frontend/src/domain/creation-contract/wizard-state.js frontend/src/stores/seedStore.js frontend/src/stores/providerStore.js frontend/src/stores/creationContractStore.js frontend/src/stores/creationAssetStore.js frontend/src/stores/corpusStore.js frontend/tests/unit/wizardState.test.mjs frontend/tests/unit/seedStore.test.mjs frontend/tests/unit/creationContractStore.test.mjs frontend/tests/unit/creationAssetStore.test.mjs frontend/tests/unit/corpusStore.test.mjs frontend/tests/unit/modelBindingStore.test.mjs
git commit -m "feat: add creation contract frontend state"
```

### Task 3: Five-step CreationContractWizard on the formal ProjectView

**Files:**
- Create: `frontend/src/components/project/CreationContractWizard.vue`
- Create: `frontend/src/components/project/contract/SeedSelectionStep.vue`
- Create: `frontend/src/components/project/contract/StoryEngineStep.vue`
- Create: `frontend/src/components/project/contract/StyleSelectionStep.vue`
- Create: `frontend/src/components/project/contract/AssetScopeStep.vue`
- Create: `frontend/src/components/project/contract/ContractPreviewStep.vue`
- Create: `frontend/src/components/project/ContractHeadSummary.vue`
- Modify: `frontend/src/views/ProjectView.vue`
- Modify: `frontend/tests/unit/m1Navigation.test.mjs`

- [ ] **Step 1: Add a frontend source contract RED test for component boundaries**

The test may assert imports/component existence and forbid `fetch`, `localStorage`, `createAdapter`, `chatCompletion`, `page.request`, or old ExperienceCards modules in the new component tree. Do not use source regex as a substitute for behavior tests; behavior remains in stores and M2E Playwright.

- [ ] **Step 2: Verify RED and preserve the existing M1 page until components exist**

```powershell
node --test frontend/tests/unit/m1Navigation.test.mjs
```

- [ ] **Step 3: Implement the wizard composition**

```vue
<!-- frontend/src/components/project/CreationContractWizard.vue -->
<script setup>
import { computed } from 'vue'
import SeedSelectionStep from './contract/SeedSelectionStep.vue'
import StoryEngineStep from './contract/StoryEngineStep.vue'
import StyleSelectionStep from './contract/StyleSelectionStep.vue'
import AssetScopeStep from './contract/AssetScopeStep.vue'
import ContractPreviewStep from './contract/ContractPreviewStep.vue'
import { useCreationContractStore } from '@/stores/creationContractStore'

const props = defineProps({ projectId: { type: String, required: true } })
const store = useCreationContractStore()
const step = computed(() => store.step)
</script>

<template>
  <section aria-labelledby="creation-contract-heading">
    <h2 id="creation-contract-heading">本书创作契约</h2>
    <seed-selection-step v-if="step === 1" :project-id="props.projectId" />
    <story-engine-step v-else-if="step === 2" :project-id="props.projectId" />
    <style-selection-step v-else-if="step === 3" :project-id="props.projectId" />
    <asset-scope-step v-else-if="step === 4" :project-id="props.projectId" />
    <contract-preview-step v-else :project-id="props.projectId" />
  </section>
</template>
```

Step requirements: seed CRUD/select and locked state; Provider/manual exactly-three engine paths with no auto retry; three recommended styles with full examples and primary/optional secondary; experience/corpus scope; preview showing all frozen versions/hashes/bindings and one atomic confirm. Engine/style/asset steps expose one “保存并继续” action and do not write on individual controls. Browser refresh checkpoints occur only after those saves. After confirm render `ContractHeadSummary` read-only plus “创建新修订”; show “等待滚动规划” and keep Writer disabled.

- [ ] **Step 4: Build and run frontend unit tests**

```powershell
node --test frontend/tests/unit/*.test.mjs
npm --prefix frontend run build
```

Expected: both exit 0; no dormant legacy import enters the bundle.

- [ ] **Step 5: Commit the formal wizard**

```powershell
git add frontend/src/components/project frontend/src/views/ProjectView.vue frontend/tests/unit/m1Navigation.test.mjs
git commit -m "feat: add creation contract wizard to ProjectView"
```

### Task 4: Settings for Provider bindings, creation assets, and local corpus

**Files:**
- Create: `frontend/src/components/settings/CreationAssetSettings.vue`
- Create: `frontend/src/components/settings/CorpusSettings.vue`
- Modify: `frontend/src/components/settings/TaskModelBinding.vue`
- Modify: `frontend/src/components/settings/ProviderSettings.vue`
- Modify: `frontend/src/views/SettingsView.vue`
- Modify: `frontend/src/stores/providerStore.js`

- [ ] **Step 1: Extend store tests for Settings behavior**

Cover complete vs ready, eight-row atomic save, unbound guidance, Provider soft-delete language/state, assets read-only catalog, corpus relative discovery/import, and absence of absolute root/full text. Corpus UI requests at most 1200 preview characters and 20 fragments; tests assert each preview is at most 240 characters and total response preview text at most 4800, and prove the client cannot override those server limits.

- [ ] **Step 2: Verify RED**

```powershell
node --test frontend/tests/unit/modelBindingStore.test.mjs frontend/tests/unit/creationAssetStore.test.mjs frontend/tests/unit/corpusStore.test.mjs
```

- [ ] **Step 3: Implement three simple Settings tabs**

Provider/模型 tab edits Providers and saves all eight bindings atomically. 创作资产 tab shows package version, active style/card counts and bounded previews; it has no review/marketplace controls. 本机语料 tab shows root configured/not-configured, relative filenames, import status, encoding, chapter count and bounded hash; it never displays or accepts an absolute client path.

- [ ] **Step 4: Verify tests and build GREEN**

```powershell
node --test frontend/tests/unit/modelBindingStore.test.mjs frontend/tests/unit/creationAssetStore.test.mjs frontend/tests/unit/corpusStore.test.mjs
npm --prefix frontend run build
```

- [ ] **Step 5: Commit Settings integration**

```powershell
git add frontend/src/components/settings/CreationAssetSettings.vue frontend/src/components/settings/CorpusSettings.vue frontend/src/components/settings/TaskModelBinding.vue frontend/src/components/settings/ProviderSettings.vue frontend/src/views/SettingsView.vue frontend/src/stores/providerStore.js frontend/tests/unit/modelBindingStore.test.mjs frontend/tests/unit/creationAssetStore.test.mjs frontend/tests/unit/corpusStore.test.mjs
git commit -m "feat: expose creation assets and corpus settings"
```

### Task 5: M2D frontend checkpoint

**Files:**
- Modify only files required by failures found in this checkpoint.

- [ ] **Step 1: Run all frontend units**

```powershell
node --test frontend/tests/unit/*.test.mjs
```

- [ ] **Step 2: Run backend API contracts consumed by the UI**

```powershell
python -m pytest backend/tests/api/test_seed_routes.py backend/tests/api/test_model_binding_routes.py backend/tests/api/test_story_engine_routes.py backend/tests/api/test_contract_routes.py backend/tests/api/test_asset_routes.py backend/tests/api/test_corpus_routes.py -q
```

- [ ] **Step 3: Build production frontend**

```powershell
npm --prefix frontend run build
```

- [ ] **Step 4: Inspect the diff and forbidden imports**

```powershell
$legacyMatches = @(rg -n "experienceCardProduct|ExperienceCardsView|createAdapter|directProviderEnabled|localStorage" frontend/src/components/project frontend/src/stores/creationContractStore.js frontend/src/stores/creationAssetStore.js frontend/src/stores/corpusStore.js)
if ($LASTEXITCODE -eq 0) { throw "Forbidden frontend dependency found: $($legacyMatches -join '; ')" }
if ($LASTEXITCODE -ne 1) { throw "rg failed with exit code $LASTEXITCODE" }
git diff --check
```

Expected: `rg` has no output; diff check exits 0.

- [ ] **Step 5: Commit only if checkpoint fixes were needed, then stop**

```powershell
git status --short
```

If tracked changes exist, commit them as `fix: close M2 wizard regression gaps`; otherwise do not create an empty commit. Stop for code/UI review. Browser behavior belongs to M2E and no product DB/Provider is authorized here.

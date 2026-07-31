import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import { api } from '../../src/api/db/client.js'
import { useCreationContractStore } from '../../src/stores/creationContractStore.js'

test('contract store has no product clone revision action', async () => {
  const source = await readFile(new URL('../../src/stores/creationContractStore.js', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /cloneRevision|api\.contracts\.clone/)
})

const HASH_A = 'a'.repeat(64)
const HASH_B = 'b'.repeat(64)

function draftValues(stage) {
  const common = {
    schemaVersion: 'contract-draft-v2',
    draftStage: stage,
    engineOptionId: 'engine-1',
    engineHash: HASH_A,
    channelProfileKey: 'qidian',
    genreProfileKey: 'xuanhuan',
    qualityCharterVersion: 'writer-core-quality-v1',
    targetTotalWords: 1_500_000,
    expectedVolumeCount: 8,
    expectedChapterCount: 500,
    chapterWordRangePreference: [2_800, 3_400],
    prohibitedDirections: ['不写无代价升级'],
    authorNotes: '人物选择优先。',
  }
  if (stage === 'engine') {
    return {
      ...common,
      primaryStyleRef: null,
      secondaryStyleRef: null,
      experienceCardRefs: null,
      corpusSourceRefs: null,
      likes: null,
      dislikes: null,
    }
  }
  const style = {
    ...common,
    primaryStyleRef: { id: 'style-1', revision: 1, contentHash: HASH_B },
    secondaryStyleRef: null,
    likes: ['情节丰满'],
    dislikes: ['干巴巴'],
  }
  if (stage === 'style') {
    return {
      ...style,
      experienceCardRefs: null,
      corpusSourceRefs: null,
    }
  }
  return {
    ...style,
    experienceCardRefs: [],
    corpusSourceRefs: [],
  }
}

function publicDraft(stage, version) {
  return {
    id: 'draft-1',
    projectId: 'project-1',
    baseHeadRevision: 0,
    draftVersion: version,
    contentHash: version % 2 ? HASH_A : HASH_B,
    draftStage: stage,
    isComplete: stage === 'assets',
    draft: draftValues(stage),
  }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

async function withApiMethods(replacements, run) {
  const effectiveReplacements = replacements.some(([owner, key]) => (
    owner === api.storyEngines && key === 'recoverable'
  )) ? replacements : [
    ...replacements,
    [api.storyEngines, 'recoverable', async () => ({ items: [] })],
  ]
  const originals = []
  for (const [owner, key, replacement] of effectiveReplacements) {
    originals.push([owner, key, owner[key]])
    owner[key] = replacement
  }
  try {
    return await run()
  } finally {
    for (const [owner, key, original] of originals.reverse()) owner[key] = original
  }
}

function installThrowingLocalStorage() {
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() {
      throw new Error('creation contract state must not access localStorage')
    },
  })
  return () => {
    if (descriptor) Object.defineProperty(globalThis, 'localStorage', descriptor)
    else delete globalThis.localStorage
  }
}

test('progressive wizard writes only on three explicit saves and refresh restores assets stage', async () => {
  const restoreStorage = installThrowingLocalStorage()
  const saveCalls = []
  let backendDraft = null

  try {
    await withApiMethods([
      [api.contracts.draft, 'get', async () => {
        if (backendDraft) return backendDraft
        throw Object.assign(new Error('missing'), { status: 404, code: 'ContractNotFound' })
      }],
      [api.contracts, 'head', async projectId => ({
        projectId, revision: 0, hasContract: false,
        contractReady: false, reasons: ['contract_missing'],
      })],
      [api.contracts.draft, 'save', async (projectId, command) => {
        saveCalls.push(structuredClone(command))
        backendDraft = {
          ...publicDraft(command.draft.draftStage, command.expectedDraftVersion + 1),
          projectId,
          draft: structuredClone(command.draft),
        }
        return backendDraft
      }],
    ], async () => {
      setActivePinia(createPinia())
      const store = useCreationContractStore()
      await store.load('project-1')

      const engine = draftValues('engine')
      const style = draftValues('style')
      const assets = draftValues('assets')

      // Changing local controls is deliberately outside the store and does not write.
      assert.equal(saveCalls.length, 0)
      await store.saveDraft('project-1', engine)
      assert.equal(saveCalls.length, 1)
      await store.saveDraft('project-1', style)
      assert.equal(saveCalls.length, 2)
      await store.saveDraft('project-1', assets)
      assert.equal(saveCalls.length, 3)
      assert.deepEqual(saveCalls.map(call => call.expectedDraftVersion), [0, 1, 2])
      assert.deepEqual(saveCalls.map(call => call.draft.draftStage), ['engine', 'style', 'assets'])

      setActivePinia(createPinia())
      const refreshed = useCreationContractStore()
      await refreshed.load('project-1')
      assert.equal(refreshed.draft.draftStage, 'assets')
      assert.equal(refreshed.draft.draftVersion, 3)
      assert.equal(refreshed.lastSavedStage, 'assets')
    })
  } finally {
    restoreStorage()
  }
})

test('unsaved edit tracking is local-only and can be explicitly discarded without an API call', async () => {
  let calls = 0
  const unexpectedCall = async () => {
    calls += 1
    throw new Error('unsaved edit tracking must stay local')
  }

  await withApiMethods([
    [api.contracts.draft, 'get', unexpectedCall],
    [api.contracts.draft, 'save', unexpectedCall],
    [api.contracts, 'head', unexpectedCall],
    [api.contracts, 'preview', unexpectedCall],
    [api.contracts, 'confirm', unexpectedCall],
    [api.storyEngines, 'reconcile', unexpectedCall],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()

    assert.equal(store.hasUnsavedChanges, false)
    store.markUnsavedChanges()
    assert.equal(store.hasUnsavedChanges, true)
    store.discardUnsavedChanges()
    assert.equal(store.hasUnsavedChanges, false)
    await Promise.resolve()
    assert.equal(calls, 0)
  })
})

test('a local edit invalidates an older load before it can clear the unsaved checkpoint', async () => {
  const pendingDraft = deferred()
  const pendingHead = deferred()

  await withApiMethods([
    [api.contracts.draft, 'get', async () => pendingDraft.promise],
    [api.contracts, 'head', async () => pendingHead.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    const load = store.load('project-1')

    store.markUnsavedChanges()
    pendingDraft.resolve(publicDraft('assets', 3))
    pendingHead.resolve({ contractReady: true, reasons: [] })
    await load

    assert.equal(store.hasUnsavedChanges, true)
    assert.equal(store.draft, null)
    assert.equal(store.head, null)
  })
})

test('successful load, save, and confirm checkpoints clear unsaved edit state', async () => {
  let loadVersion = 3

  await withApiMethods([
    [api.contracts.draft, 'get', async () => publicDraft('assets', loadVersion)],
    [api.contracts, 'head', async () => ({ contractReady: false, reasons: [] })],
    [api.contracts.draft, 'save', async () => publicDraft('assets', 4)],
    [api.contracts, 'confirm', async () => ({
      projectId: 'project-1', revision: 1, contractReady: true, reasons: [],
    })],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()

    store.markUnsavedChanges()
    await store.load('project-1')
    assert.equal(store.hasUnsavedChanges, false)

    store.markUnsavedChanges()
    await store.saveDraft('project-1', draftValues('assets'))
    assert.equal(store.hasUnsavedChanges, false)

    store.markUnsavedChanges()
    await store.confirm('project-1', { idempotencyKey: 'checkpoint-confirm' })
    assert.equal(store.hasUnsavedChanges, false)

  })
})

test('draft CAS conflict requires an explicit reload and never retries or overwrites', async () => {
  let current = publicDraft('engine', 1)
  let saves = 0
  let reads = 0

  await withApiMethods([
    [api.contracts.draft, 'get', async () => {
      reads += 1
      return current
    }],
    [api.contracts, 'head', async () => ({ contractReady: false, reasons: [] })],
    [api.contracts.draft, 'save', async () => {
      saves += 1
      throw Object.assign(new Error('stale'), {
        status: 409,
        code: 'ContractConflict',
        correlationId: 'cid-conflict',
      })
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    await store.load('project-1')

    await assert.rejects(store.saveDraft('project-1', draftValues('style')), error => (
      error.status === 409 && error.code === 'ContractConflict'
    ))

    assert.equal(saves, 1)
    assert.equal(reads, 1)
    assert.equal(store.requiresReload, true)
    assert.equal(store.conflict.code, 'ContractConflict')
    assert.equal(store.draft.draftStage, 'engine')

    current = publicDraft('style', 2)
    await store.load('project-1')
    assert.equal(reads, 2)
    assert.equal(store.requiresReload, false)
    assert.equal(store.conflict, null)
    assert.equal(store.draft.draftStage, 'style')
  })
})

test('late load results cannot replace the currently active project state', async () => {
  const first = deferred()
  const second = deferred()

  await withApiMethods([
    [api.contracts.draft, 'get', projectId => (
      projectId === 'project-a' ? first.promise : second.promise
    )],
    [api.contracts, 'head', async projectId => ({
      projectId, revision: 0, contractReady: false, reasons: [],
    })],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    const loadA = store.load('project-a')
    const loadB = store.load('project-b')

    second.resolve({ ...publicDraft('style', 2), projectId: 'project-b' })
    await loadB
    first.resolve({ ...publicDraft('engine', 1), projectId: 'project-a' })
    await loadA

    assert.equal(store.projectId, 'project-b')
    assert.equal(store.draft.projectId, 'project-b')
    assert.equal(store.draft.draftStage, 'style')
  })
})

test('a late save response cannot overwrite a newer explicit reload of the same project', async () => {
  const pendingSave = deferred()
  const loadedDrafts = [publicDraft('engine', 1), publicDraft('assets', 3)]

  await withApiMethods([
    [api.contracts.draft, 'get', async () => loadedDrafts.shift()],
    [api.contracts, 'head', async () => ({ contractReady: false, reasons: [] })],
    [api.contracts.draft, 'save', async () => pendingSave.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    await store.load('project-1')

    const save = store.saveDraft('project-1', draftValues('style'))
    await store.load('project-1')
    pendingSave.resolve(publicDraft('style', 2))
    await save

    assert.equal(store.draft.draftStage, 'assets')
    assert.equal(store.draft.draftVersion, 3)
  })
})

test('contract readiness is copied from backend responses and never inferred from a complete draft', async () => {
  const previews = [
    {
      contractReady: true,
      reasons: ['binding_drift'],
      seedRef: { revisionId: 'seed-revision-1', contentHash: HASH_A },
      bindingRef: { revision: 7, contentHash: HASH_B },
    },
    {
      contractReady: true,
      reasons: [],
      seedRef: { revisionId: 'seed-revision-1', contentHash: HASH_A },
      bindingRef: { revision: 7, contentHash: HASH_B },
    },
  ]

  await withApiMethods([
    [api.contracts.draft, 'get', async () => publicDraft('assets', 3)],
    [api.contracts, 'head', async () => ({ contractReady: true, reasons: [] })],
    [api.contracts, 'preview', async () => previews.shift()],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    await store.load('project-1')

    assert.equal(store.draft.isComplete, true)
    assert.equal(store.contractReady, false)
    await store.preview('project-1')
    assert.equal(store.contractReady, false)
    assert.deepEqual(store.readinessReasons, ['binding_drift'])
    await store.preview('project-1')
    assert.equal(store.contractReady, true)
    assert.deepEqual(store.readinessReasons, [])
    assert.deepEqual(store.readiness, {
      ready: true,
      reasons: [],
      seedRevisionId: 'seed-revision-1',
      seedHash: HASH_A,
      bindingRevision: 7,
      bindingHash: HASH_B,
    })
  })
})

for (const reason of ['seed_drift', 'binding_drift']) {
  test(`${reason} from backend keeps UI contract readiness false`, async () => {
    await withApiMethods([
      [api.contracts.draft, 'get', async () => publicDraft('assets', 3)],
      [api.contracts, 'head', async () => ({ contractReady: true, reasons: [] })],
      [api.contracts, 'preview', async () => ({
        contractReady: false,
        reasons: [reason],
        seedRef: { revisionId: 'seed-revision-drift', contentHash: HASH_A },
        bindingRef: { revision: 9, contentHash: HASH_B },
      })],
    ], async () => {
      setActivePinia(createPinia())
      const store = useCreationContractStore()
      await store.load('project-1')
      await store.preview('project-1')

      assert.equal(store.readiness.ready, false)
      assert.deepEqual(store.readiness.reasons, [reason])
      assert.equal(store.contractReady, false)
    })
  })
}

test('a preview for an older draft cannot restore stale readiness after a newer save', async () => {
  const pendingPreview = deferred()

  await withApiMethods([
    [api.contracts.draft, 'get', async () => publicDraft('assets', 3)],
    [api.contracts, 'head', async () => ({ contractReady: false, reasons: [] })],
    [api.contracts, 'preview', async () => pendingPreview.promise],
    [api.contracts.draft, 'save', async () => publicDraft('assets', 4)],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    await store.load('project-1')

    const preview = store.preview('project-1')
    await store.saveDraft('project-1', draftValues('assets'))
    pendingPreview.resolve({ contractReady: true, reasons: [] })
    await preview

    assert.equal(store.draft.draftVersion, 4)
    assert.equal(store.previewResult, null)
    assert.equal(store.contractReady, false)
  })
})

test('outcome_unknown remains pending until reconcileBatch is called explicitly', async () => {
  let reconciles = 0
  let generates = 0

  await withApiMethods([
    [api.storyEngines, 'generate', async () => {
      generates += 1
      throw new Error('must not generate automatically')
    }],
    [api.storyEngines, 'reconcile', async (projectId, batchId) => {
      reconciles += 1
      return { projectId, id: batchId, status: 'outcome_unknown' }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()

    assert.equal(reconciles, 0)
    assert.equal(generates, 0)
    const result = await store.reconcileBatch('project-1', 'batch-1')
    assert.equal(result.status, 'outcome_unknown')
    assert.equal(store.providerOutcomeUnknown, true)
    assert.equal(reconciles, 1)
    assert.equal(generates, 0)
  })
})

test('load installs recoverable summaries only for the current project', async () => {
  const projectARecovery = deferred()

  await withApiMethods([
    [api.contracts.draft, 'get', async () => null],
    [api.contracts, 'head', async projectId => ({ projectId, hasContract: false })],
    [api.storyEngines, 'recoverable', async projectId => (
      projectId === 'project-a'
        ? projectARecovery.promise
        : { items: [{ id: 'project-b-running', status: 'running' }] }
    )],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    const loadA = store.load('project-a')
    await store.load('project-b')

    projectARecovery.resolve({
      items: [{ id: 'project-a-running', status: 'running' }],
    })
    await loadA

    assert.equal(store.projectId, 'project-b')
    assert.deepEqual(store.recoverableBatches, [
      { id: 'project-b-running', status: 'running' },
    ])
  })
})

test('recoverable reconciliation is explicit, per-row fail-closed, and never generates', async () => {
  const pendingReserved = deferred()
  let generations = 0
  const reconciles = []

  await withApiMethods([
    [api.contracts.draft, 'get', async () => null],
    [api.contracts, 'head', async () => ({ hasContract: false })],
    [api.storyEngines, 'recoverable', async () => ({
      items: [
        { id: 'reserved', status: 'reserved' },
        { id: 'running', status: 'running' },
      ],
    })],
    [api.storyEngines, 'generate', async () => {
      generations += 1
      throw new Error('recovery must never generate')
    }],
    [api.storyEngines, 'reconcile', async (_projectId, batchId) => {
      reconciles.push(batchId)
      if (batchId === 'reserved') return pendingReserved.promise
      return {
        id: 'running',
        status: 'outcome_unknown',
        publicErrorCode: 'outcome_unknown',
      }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    assert.equal('installRecoverableForTestOnly' in store, false)
    await store.load('project-1')

    assert.deepEqual(reconciles, [])
    const first = store.reconcileRecoverableBatch('project-1', 'reserved')
    const duplicate = await store.reconcileRecoverableBatch('project-1', 'reserved')
    assert.equal(duplicate, null)
    assert.deepEqual(reconciles, ['reserved'])
    assert.deepEqual(store.reconcilingBatchIds, ['reserved'])

    pendingReserved.resolve({
      id: 'reserved', status: 'failed', publicErrorCode: 'not_started',
    })
    await first
    assert.deepEqual(store.recoverableBatches.map(row => row.id), ['running'])
    assert.deepEqual(store.reconcilingBatchIds, [])

    await store.reconcileRecoverableBatch('project-1', 'running')
    assert.deepEqual(store.recoverableBatches, [{
      id: 'running', status: 'outcome_unknown', publicErrorCode: 'outcome_unknown',
    }])
    assert.equal(store.engineBatch.id, 'running')
    assert.equal(store.providerOutcomeUnknown, true)
    assert.equal(generations, 0)
  })
})

test('recoverable reserved rows and public failures remain visible without retry', async () => {
  let reconciles = 0
  const failure = Object.assign(new Error('bounded public failure'), {
    status: 503,
    code: 'StoryEngineUnavailable',
    correlationId: 'cid-recovery',
  })

  await withApiMethods([
    [api.contracts.draft, 'get', async () => null],
    [api.contracts, 'head', async () => ({ hasContract: false })],
    [api.storyEngines, 'recoverable', async () => ({
      items: [{ id: 'reserved', status: 'reserved' }],
    })],
    [api.storyEngines, 'reconcile', async () => {
      reconciles += 1
      throw failure
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    await store.load('project-1')

    await assert.rejects(
      store.reconcileRecoverableBatch('project-1', 'reserved'),
      failure,
    )
    await Promise.resolve()

    assert.equal(reconciles, 1)
    assert.deepEqual(store.recoverableBatches, [{ id: 'reserved', status: 'reserved' }])
    assert.deepEqual(store.error, {
      status: 503,
      code: 'StoryEngineUnavailable',
      message: 'bounded public failure',
      correlationId: 'cid-recovery',
    })
  })
})

test('non-expired reserved and running recovery results stay visible without retry or generation', async () => {
  const reconciles = []
  let generations = 0

  await withApiMethods([
    [api.contracts.draft, 'get', async () => null],
    [api.contracts, 'head', async () => ({ hasContract: false })],
    [api.storyEngines, 'recoverable', async () => ({
      items: [
        { id: 'reserved-live', status: 'reserved' },
        { id: 'running-live', status: 'running' },
      ],
    })],
    [api.storyEngines, 'generate', async () => { generations += 1 }],
    [api.storyEngines, 'reconcile', async (_projectId, batchId) => {
      reconciles.push(batchId)
      return { id: batchId, status: batchId === 'reserved-live' ? 'reserved' : 'running' }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    await store.load('project-1')

    await store.reconcileRecoverableBatch('project-1', 'reserved-live')
    await store.reconcileRecoverableBatch('project-1', 'running-live')
    await Promise.resolve()

    assert.deepEqual(reconciles, ['reserved-live', 'running-live'])
    assert.equal(generations, 0)
    assert.deepEqual(store.recoverableBatches, [
      { id: 'reserved-live', status: 'reserved' },
      { id: 'running-live', status: 'running' },
    ])
  })
})

test('late recoverable reconciliation cannot cross a project switch', async () => {
  const pendingReconcile = deferred()

  await withApiMethods([
    [api.contracts.draft, 'get', async () => null],
    [api.contracts, 'head', async projectId => ({ projectId, hasContract: false })],
    [api.storyEngines, 'recoverable', async projectId => ({
      items: [{ id: `${projectId}-running`, status: 'running' }],
    })],
    [api.storyEngines, 'reconcile', async () => pendingReconcile.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    await store.load('project-a')
    const reconcile = store.reconcileRecoverableBatch('project-a', 'project-a-running')
    await store.load('project-b')

    pendingReconcile.resolve({
      id: 'project-a-running',
      status: 'outcome_unknown',
      publicErrorCode: 'outcome_unknown',
    })
    await reconcile

    assert.equal(store.projectId, 'project-b')
    assert.deepEqual(store.recoverableBatches, [
      { id: 'project-b-running', status: 'running' },
    ])
    assert.equal(store.engineBatch, null)
  })
})

test('Provider and manual story-engine batches are created only by one explicit store command', async () => {
  const providerCalls = []
  const manualCalls = []
  const options = [{ name: '甲案' }, { name: '乙案' }, { name: '丙案' }]

  await withApiMethods([
    [api.storyEngines, 'generate', async (projectId, command) => {
      providerCalls.push({ projectId, command: structuredClone(command) })
      return { id: 'provider-batch', status: 'succeeded', options }
    }],
    [api.storyEngines, 'manual', async (projectId, command) => {
      manualCalls.push({ projectId, command: structuredClone(command) })
      return { id: 'manual-batch', status: 'succeeded', options }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()

    assert.equal(providerCalls.length, 0)
    assert.equal(manualCalls.length, 0)
    const provider = await store.generateEngineBatch('project-1', {
      idempotencyKey: 'provider-explicit-1',
    })
    assert.equal(provider.id, 'provider-batch')
    assert.deepEqual(providerCalls, [{
      projectId: 'project-1',
      command: { idempotencyKey: 'provider-explicit-1' },
    }])

    const manual = await store.createManualEngineBatch('project-1', {
      idempotencyKey: 'manual-explicit-1',
      options,
    })
    assert.equal(manual.id, 'manual-batch')
    assert.deepEqual(manualCalls, [{
      projectId: 'project-1',
      command: { idempotencyKey: 'manual-explicit-1', options },
    }])
    assert.equal(store.engineBatch.id, 'manual-batch')
  })
})

test('latest story-engine command wins and an outcome_unknown result never triggers hidden recovery', async () => {
  const slowGenerate = deferred()
  const fastLoad = deferred()
  let generates = 0
  let reads = 0
  let reconciles = 0

  await withApiMethods([
    [api.storyEngines, 'generate', async () => {
      generates += 1
      return slowGenerate.promise
    }],
    [api.storyEngines, 'get', async () => {
      reads += 1
      return fastLoad.promise
    }],
    [api.storyEngines, 'reconcile', async () => {
      reconciles += 1
      throw new Error('reconcile must remain explicit')
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()

    const generate = store.generateEngineBatch('project-1', {
      idempotencyKey: 'provider-explicit-2',
    })
    const load = store.loadEngineBatch('project-1', 'batch-newer')
    fastLoad.resolve({ id: 'batch-newer', status: 'outcome_unknown', options: [] })
    await load
    slowGenerate.resolve({ id: 'batch-older', status: 'succeeded', options: [] })
    await generate
    await Promise.resolve()

    assert.equal(generates, 1)
    assert.equal(reads, 1)
    assert.equal(reconciles, 0)
    assert.equal(store.engineBatch.id, 'batch-newer')
    assert.equal(store.providerOutcomeUnknown, true)
  })
})

test('confirm replays the exact command for the same idempotency key after draft consumption', async () => {
  const confirmCalls = []
  const confirmed = {
    projectId: 'project-1', revision: 1, hasContract: true,
    contractReady: true, reasons: [],
  }

  await withApiMethods([
    [api.contracts.draft, 'get', async () => publicDraft('assets', 3)],
    [api.contracts, 'head', async () => ({ contractReady: false, reasons: [] })],
    [api.contracts, 'confirm', async (projectId, command) => {
      confirmCalls.push({ projectId, command: structuredClone(command) })
      return confirmed
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    await store.load('project-1')

    const first = await store.confirm('project-1', { idempotencyKey: 'confirm-1' })
    assert.equal(store.draft, null)
    const replay = await store.confirm('project-1', { idempotencyKey: 'confirm-1' })

    assert.equal(first, confirmed)
    assert.equal(replay, confirmed)
    assert.equal(confirmCalls.length, 2)
    assert.deepEqual(confirmCalls[1], confirmCalls[0])
    assert.deepEqual(confirmCalls[0].command, {
      idempotencyKey: 'confirm-1',
      expectedDraftVersion: 3,
      expectedDraftHash: HASH_A,
    })
    assert.equal(store.confirmed, confirmed)
    assert.equal(store.contractReady, true)
  })
})

test('style trial uses the backend gateway and remains temporary contract-neutral state', async () => {
  assert.equal(typeof api.styleTrials?.generate, 'function')
  const restoreStorage = installThrowingLocalStorage()
  const calls = []
  const trial = {
    attemptId: 'trial-1',
    status: 'succeeded',
    sample: '原创试写正文',
    resultHash: HASH_A,
    publicErrorCode: null,
    provider: {
      providerId: 'provider-1',
      providerType: 'openai-compatible',
      modelName: 'safe-model-name',
      profileRevision: 7,
    },
  }
  const command = {
    selectionRevision: 3,
    engineOptionId: 'engine-1',
    engineHash: HASH_A,
    primaryStyleRevisionId: 'style-1',
    primaryStyleHash: HASH_B,
    secondaryStyleRevisionId: null,
    secondaryStyleHash: null,
    authorScenario: '主角必须在救人和守住秘密之间做选择。',
    idempotencyKey: 'i'.repeat(64),
  }

  try {
    await withApiMethods([
      [api.styleTrials, 'generate', async (projectId, payload) => {
        calls.push({ projectId, payload: structuredClone(payload) })
        return trial
      }],
    ], async () => {
      setActivePinia(createPinia())
      const store = useCreationContractStore()
      const beforeDraft = store.draft
      const result = await store.runStyleTrial('project-1', command)

      assert.equal(result, trial)
      assert.equal(store.styleTrial, trial)
      assert.equal(store.styleTrialLoading, false)
      assert.equal(store.draft, beforeDraft)
      assert.equal(store.previewResult, null)
      assert.equal(store.confirmed, null)
      assert.equal(store.hasUnsavedChanges, false)
      assert.deepEqual(calls, [{ projectId: 'project-1', payload: command }])
      store.clearStyleTrial()
      assert.equal(store.styleTrial, null)
      assert.equal(calls.length, 1)
    })
  } finally {
    restoreStorage()
  }
})

test('history is explicit read-only state and exposes pinned assets and superseded reasons', async () => {
  const history = {
    items: [{
      revision: 4,
      selectionRevision: 8,
      styleRefs: [{ id: 'style-1', revision: 2, contentHash: HASH_A }],
      experienceCardRefs: [{ id: 'card-1', revision: 3, contentHash: HASH_B }],
      corpusSourceRefs: [{
        id: 'source-1', revisionId: 'source-revision-1', revision: 1,
        contentHash: HASH_A, selectionMode: 'author', pinnedHistoricalRevision: true,
        fragments: [],
      }],
      supersededReasons: ['contract_revision_replaced'],
    }],
    nextBeforeRevision: null,
  }
  let calls = 0

  await withApiMethods([
    [api.contracts, 'history', async (projectId, params) => {
      calls += 1
      assert.equal(projectId, 'project-1')
      assert.deepEqual(params, { limit: 50 })
      return history
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    const result = await store.loadHistory('project-1', { limit: 50 })

    assert.equal(calls, 1)
    assert.equal(result, history)
    assert.deepEqual(store.history, history.items)
    assert.equal(store.historyNextBeforeRevision, null)
    assert.equal(store.historyLoading, false)
    assert.equal(store.draft, null)
    assert.equal(store.hasUnsavedChanges, false)
  })
})

test('history pagination reaches more than one hundred revisions with an exclusive cursor', async () => {
  const revisions = Array.from({ length: 105 }, (_, index) => ({
    revision: 105 - index,
    selectionRevision: 8,
  }))
  const calls = []

  await withApiMethods([
    [api.contracts, 'history', async (projectId, params) => {
      calls.push({ projectId, ...params })
      const before = params.beforeRevision ?? Number.POSITIVE_INFINITY
      const items = revisions
        .filter(item => item.revision < before)
        .slice(0, params.limit)
      return {
        items,
        nextBeforeRevision: items.length === params.limit
          ? items.at(-1).revision
          : null,
      }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()

    await store.loadHistory('project-1', { limit: 20 })
    assert.equal(store.historyNextBeforeRevision, 86)
    for (let page = 1; store.historyNextBeforeRevision !== null && page < 10; page += 1) {
      await store.loadHistory('project-1', {
        limit: 20,
        beforeRevision: store.historyNextBeforeRevision,
        append: true,
      })
    }

    assert.deepEqual(calls, [
      { projectId: 'project-1', limit: 20 },
      { projectId: 'project-1', limit: 20, beforeRevision: 86 },
      { projectId: 'project-1', limit: 20, beforeRevision: 66 },
      { projectId: 'project-1', limit: 20, beforeRevision: 46 },
      { projectId: 'project-1', limit: 20, beforeRevision: 26 },
      { projectId: 'project-1', limit: 20, beforeRevision: 6 },
    ])
    assert.deepEqual(store.history.map(item => item.revision), revisions.map(item => item.revision))
    assert.equal(new Set(store.history.map(item => item.revision)).size, 105)

    assert.equal(typeof store.clearHistory, 'function')
    store.clearHistory()
    assert.deepEqual(store.history, [])
    assert.equal(store.historyNextBeforeRevision, null)
  })
})

test('archived read-only load fetches only contract head and never touches draft or recoverable engines', async () => {
  const calls = { draft: 0, head: 0, recoverable: 0 }
  const head = {
    projectId: 'project-1',
    revision: 4,
    hasContract: true,
    contractReady: true,
    reasons: [],
  }

  await withApiMethods([
    [api.contracts.draft, 'get', async () => {
      calls.draft += 1
      return publicDraft('assets', 9)
    }],
    [api.contracts, 'head', async projectId => {
      calls.head += 1
      assert.equal(projectId, 'project-1')
      return head
    }],
    [api.storyEngines, 'recoverable', async () => {
      calls.recoverable += 1
      return { items: [{ id: 'must-not-load' }] }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    const result = await store.load('project-1', { readOnly: true })

    assert.deepEqual(calls, { draft: 0, head: 1, recoverable: 0 })
    assert.equal(result.head, head)
    assert.equal(result.draft, null)
    assert.deepEqual(result.recovery, { items: [] })
    assert.equal(store.readOnly, true)
    assert.equal(store.head, head)
    assert.equal(store.draft, null)
    assert.deepEqual(store.recoverableBatches, [])
  })
})

test('archived read-only mode rejects every formal write before transport', async () => {
  assert.equal(typeof api.styleTrials?.generate, 'function')
  let writes = 0
  const unexpectedWrite = async () => {
    writes += 1
    throw new Error('archived projects must not write')
  }

  await withApiMethods([
    [api.contracts.draft, 'save', unexpectedWrite],
    [api.contracts, 'preview', unexpectedWrite],
    [api.contracts, 'confirm', unexpectedWrite],
    [api.storyEngines, 'generate', unexpectedWrite],
    [api.storyEngines, 'manual', unexpectedWrite],
    [api.styleTrials, 'generate', unexpectedWrite],
  ], async () => {
    setActivePinia(createPinia())
    const store = useCreationContractStore()
    store.setReadOnly(true)

    for (const operation of [
      () => store.saveDraft('project-1', draftValues('engine')),
      () => store.preview('project-1'),
      () => store.confirm('project-1', { idempotencyKey: 'archived' }),
      () => store.generateEngineBatch('project-1', { idempotencyKey: 'archived' }),
      () => store.createManualEngineBatch('project-1', { idempotencyKey: 'archived', options: [] }),
      () => store.runStyleTrial('project-1', {}),
    ]) {
      await assert.rejects(operation, error => error?.code === 'contract_read_only')
    }

    assert.equal(writes, 0)
    assert.equal(store.readOnly, true)
  })
})

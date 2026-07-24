import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import { api } from '../../src/api/db/client.js'
import { usePlanningStore } from '../../src/stores/planningStore.js'

const HASH = 'a'.repeat(64)
const NEXT_HASH = 'b'.repeat(64)

function planningContent(hash = HASH) {
  return {
    schemaVersion: 'planning-v1',
    activeStoryBlockId: null,
    volumes: [],
    plots: [],
    storyBlocks: [],
    contentHash: hash,
  }
}

function editableContent(activeStoryBlockRef = null) {
  return {
    activeStoryBlockRef,
    volumes: [],
    plots: [],
    storyBlocks: [],
  }
}

function draft(hash = HASH, revision = 1) {
  return {
    projectId: 'project-1',
    draftId: 'draft-1',
    baseHeadRevision: 0,
    draftRevision: revision,
    contentHash: hash,
    content: planningContent(hash),
    status: 'active',
    capacityPolicy: { targetMin: 3000, targetMax: 5000, softCeiling: 5000 },
  }
}

function state(projectId = 'project-1', activeDraft = null) {
  return {
    projectId,
    basisStatus: 'current',
    head: { revision: 0, planningRevisionId: null, contentHash: null },
    draft: activeDraft,
    futurePlan: null,
    actualProgress: [],
    canonProjectionStatus: {
      canonRevision: 0,
      projectionRevision: 0,
      contentHash: HASH,
      synchronized: true,
    },
    capacityPolicy: { targetMin: 3000, targetMax: 5000, softCeiling: 5000 },
    capabilities: { view: true, edit: true, confirm: Boolean(activeDraft), generate: false },
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
  const originals = []
  for (const [owner, key, replacement] of replacements) {
    originals.push([owner, key, owner[key]])
    owner[key] = replacement
  }
  try {
    return await run()
  } finally {
    for (const [owner, key, original] of originals.reverse()) owner[key] = original
  }
}

test('planning transport exposes only the revisioned aggregate endpoints', () => {
  assert.equal(typeof api.planning.get, 'function')
  assert.equal(typeof api.planning.history, 'function')
  assert.equal(typeof api.planning.createDraft, 'function')
  assert.equal(typeof api.planning.saveDraft, 'function')
  assert.equal(typeof api.planning.confirmDraft, 'function')
  assert.equal(api.planning.createInitial, undefined)
})

test('planning store loads state, history and starts an explicit draft', async () => {
  const calls = []
  await withApiMethods([
    [api.planning, 'get', async projectId => {
      calls.push(['get', projectId])
      return state(projectId)
    }],
    [api.planning, 'history', async projectId => {
      calls.push(['history', projectId])
      return { items: [] }
    }],
    [api.planning, 'createDraft', async (projectId, body) => {
      calls.push(['createDraft', projectId, structuredClone(body)])
      return { ...draft(), projectId }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()

    await store.load('project-1')
    assert.equal(store.state.head.revision, 0)
    assert.deepEqual(store.history, [])
    assert.equal(store.localContent, null)
    assert.equal(store.dirty, false)

    await store.createDraft('project-1', { idempotencyKey: 'planning-draft-1' })
    assert.equal(store.state.draft.draftId, 'draft-1')
    assert.deepEqual(store.localContent, editableContent())
    assert.equal(store.dirty, false)
    assert.deepEqual(calls, [
      ['get', 'project-1'],
      ['history', 'project-1'],
      ['createDraft', 'project-1', { idempotencyKey: 'planning-draft-1' }],
    ])
  })
})

test('editing is local until save and successful save refreshes the CAS baseline', async () => {
  const calls = []
  await withApiMethods([
    [api.planning, 'get', async () => state('project-1', draft())],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'saveDraft', async (projectId, draftId, body) => {
      calls.push([projectId, draftId, structuredClone(body)])
      return {
        ...draft(NEXT_HASH, 2),
        content: { ...planningContent(NEXT_HASH), activeStoryBlockId: 'block-1' },
      }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')

    store.editLocal({ ...store.localContent, activeStoryBlockRef: 'block-1' })
    assert.equal(store.dirty, true)
    assert.equal(store.state.draft.content.activeStoryBlockId, null)

    await store.saveDraft({ idempotencyKey: 'save-draft-1' })

    assert.deepEqual(calls, [[
      'project-1',
      'draft-1',
      {
        expectedDraftRevision: 1,
        expectedDraftHash: HASH,
        content: editableContent('block-1'),
        idempotencyKey: 'save-draft-1',
      },
    ]])
    assert.equal(store.state.draft.draftRevision, 2)
    assert.equal(store.localContent.activeStoryBlockRef, 'block-1')
    assert.equal(store.dirty, false)
  })
})

test('CAS failure preserves dirty local content for author recovery', async () => {
  const conflict = Object.assign(new Error('规划已变化'), {
    status: 409,
    code: 'PlanningConflict',
    correlationId: 'corr-1',
  })
  await withApiMethods([
    [api.planning, 'get', async () => state('project-1', draft())],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'saveDraft', async () => { throw conflict }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    const local = { ...store.localContent, activeStoryBlockRef: 'author-edit' }
    store.editLocal(local)

    await assert.rejects(
      store.saveDraft({ idempotencyKey: 'save-draft-1' }),
      conflict,
    )

    assert.deepEqual(store.localContent, local)
    assert.equal(store.dirty, true)
    assert.equal(store.error.code, 'PlanningConflict')
  })
})

test('confirmation refreshes state and history through the canonical endpoints', async () => {
  const calls = []
  await withApiMethods([
    [api.planning, 'get', async projectId => {
      calls.push(['get', projectId])
      return state(projectId, calls.length === 1 ? draft() : null)
    }],
    [api.planning, 'history', async projectId => {
      calls.push(['history', projectId])
      return {
        items: calls.length < 4
          ? []
          : [{
              projectId,
              planningRevisionId: 'revision-1',
              revision: 1,
              parentRevision: 0,
              contentHash: HASH,
              content: planningContent(),
            }],
      }
    }],
    [api.planning, 'confirmDraft', async (projectId, draftId, body) => {
      calls.push(['confirm', projectId, draftId, structuredClone(body)])
      return { revision: 1 }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    await store.confirmDraft({ idempotencyKey: 'confirm-draft-1' })

    assert.equal(store.state.draft, null)
    assert.equal(store.history[0].revision, 1)
    assert.equal(store.localContent, null)
    assert.equal(store.dirty, false)
    assert.deepEqual(calls[2], [
      'confirm',
      'project-1',
      'draft-1',
      {
        expectedDraftRevision: 1,
        expectedDraftHash: HASH,
        idempotencyKey: 'confirm-draft-1',
      },
    ])
  })
})

test('discardLocal restores persisted content without creating a version', async () => {
  await withApiMethods([
    [api.planning, 'get', async () => state('project-1', draft())],
    [api.planning, 'history', async () => ({ items: [] })],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    store.editLocal({ changed: true })

    store.discardLocal()

    assert.deepEqual(store.localContent, editableContent())
    assert.equal(store.dirty, false)
  })
})

test('late state, history and mutation responses cannot cross project generations', async () => {
  const oldState = deferred()
  const oldHistory = deferred()
  const oldCreate = deferred()
  await withApiMethods([
    [api.planning, 'get', projectId => (
      projectId === 'project-1' ? oldState.promise : Promise.resolve(state(projectId))
    )],
    [api.planning, 'history', projectId => (
      projectId === 'project-1'
        ? oldHistory.promise
        : Promise.resolve({ items: [{ projectId, revision: 2 }] })
    )],
    [api.planning, 'createDraft', projectId => (
      projectId === 'project-1'
        ? oldCreate.promise
        : Promise.resolve({ ...draft(), projectId })
    )],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    const oldLoad = store.load('project-1')
    const oldMutation = store.createDraft('project-1', {
      idempotencyKey: 'project-1-draft',
    })
    await store.load('project-2')
    oldState.resolve(state('project-1', draft()))
    oldHistory.resolve({ items: [{ projectId: 'project-1', revision: 1 }] })
    oldCreate.resolve({ ...draft(), projectId: 'project-1' })
    await Promise.all([oldLoad, oldMutation])

    assert.equal(store.projectId, 'project-2')
    assert.equal(store.state.projectId, 'project-2')
    assert.equal(store.history[0].projectId, 'project-2')
    assert.equal(store.state.draft, null)
  })
})

test('confirm rejects dirty content and busy mutations before any API request', async () => {
  const savePending = deferred()
  const confirmPending = deferred()
  let confirmCalls = 0
  let saveCalls = 0
  let holdConfirmation = false
  const confirmed = {
    projectId: 'project-1',
    planningRevisionId: 'revision-1',
    revision: 1,
    parentRevision: 0,
    contentHash: NEXT_HASH,
    content: planningContent(NEXT_HASH),
  }
  await withApiMethods([
    [api.planning, 'get', async () => state('project-1', draft())],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'saveDraft', async () => {
      saveCalls += 1
      return savePending.promise
    }],
    [api.planning, 'confirmDraft', async () => {
      confirmCalls += 1
      return holdConfirmation ? confirmPending.promise : confirmed
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    const local = { ...store.localContent, activeStoryBlockRef: 'author-edit' }
    store.editLocal(local)

    await assert.rejects(
      store.confirmDraft({ idempotencyKey: 'dirty-confirm' }),
      /save.*before confirmation|保存.*确认/i,
    )
    assert.equal(confirmCalls, 0)
    assert.deepEqual(store.localContent, local)
    assert.equal(store.dirty, true)

    store.discardLocal()
    const saving = store.saveDraft({ idempotencyKey: 'saving-1' })
    await assert.rejects(
      store.confirmDraft({ idempotencyKey: 'busy-confirm' }),
      /operation.*progress|操作.*进行/i,
    )
    assert.equal(confirmCalls, 0)
    savePending.resolve(draft(NEXT_HASH, 2))
    await saving

    holdConfirmation = true
    const confirming = store.confirmDraft({ idempotencyKey: 'confirming-1' })
    await assert.rejects(
      store.saveDraft({ idempotencyKey: 'busy-save' }),
      /operation.*progress|操作.*进行/i,
    )
    assert.equal(saveCalls, 1)
    confirmPending.resolve(confirmed)
    await confirming
  })
})

test('confirmed write remains successful when authoritative refresh fails', async () => {
  const refreshFailure = Object.assign(new Error('refresh failed'), {
    status: 503,
    code: 'request_failed',
  })
  let getCalls = 0
  let confirmCalls = 0
  const confirmed = {
    projectId: 'project-1',
    planningRevisionId: 'revision-1',
    revision: 1,
    parentRevision: 0,
    contentHash: NEXT_HASH,
    content: planningContent(NEXT_HASH),
  }
  await withApiMethods([
    [api.planning, 'get', async () => {
      getCalls += 1
      if (getCalls > 1) throw refreshFailure
      return state('project-1', draft())
    }],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'confirmDraft', async () => {
      confirmCalls += 1
      return confirmed
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')

    const result = await store.confirmDraft({
      idempotencyKey: 'confirm-refresh-failure',
    })

    assert.equal(result, confirmed)
    assert.equal(confirmCalls, 1)
    assert.equal(store.state.head.revision, 1)
    assert.equal(store.state.futurePlan.contentHash, NEXT_HASH)
    assert.equal(store.state.draft, null)
    assert.equal(store.history[0].planningRevisionId, 'revision-1')
    assert.equal(store.localContent, null)
    assert.equal(store.dirty, false)
    assert.equal(store.state.capabilities.confirm, false)
    assert.equal(store.error.code, 'PlanningRefreshFailed')
    assert.match(store.error.message, /确认成功.*刷新失败/)
  })
})

test('invalidate clears busy flags and late completions cannot revive them', async () => {
  const loadPending = deferred()
  const savePending = deferred()
  const confirmPending = deferred()
  let initialLoad = true
  await withApiMethods([
    [api.planning, 'get', async () => {
      if (initialLoad) return loadPending.promise
      return state('project-1', draft())
    }],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'saveDraft', async () => savePending.promise],
    [api.planning, 'confirmDraft', async () => confirmPending.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    const loading = store.load('project-1')
    assert.equal(store.loading, true)
    store.invalidate()
    assert.equal(store.loading, false)
    loadPending.resolve(state('project-1', draft()))
    await loading
    assert.equal(store.loading, false)
    assert.equal(store.state, null)

    initialLoad = false
    await store.load('project-1')
    const saving = store.saveDraft({ idempotencyKey: 'invalidate-save' })
    assert.equal(store.saving, true)
    store.invalidate()
    assert.equal(store.saving, false)
    savePending.resolve(draft(NEXT_HASH, 2))
    await saving
    assert.equal(store.saving, false)

    const confirming = store.confirmDraft({
      idempotencyKey: 'invalidate-confirm',
    })
    assert.equal(store.confirming, true)
    store.invalidate()
    assert.equal(store.confirming, false)
    confirmPending.resolve({
      projectId: 'project-1',
      planningRevisionId: 'revision-1',
      revision: 1,
      parentRevision: 0,
      contentHash: HASH,
      content: planningContent(),
    })
    await confirming
    assert.equal(store.confirming, false)
  })
})

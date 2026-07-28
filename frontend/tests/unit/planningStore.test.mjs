import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import { api } from '../../src/api/db/client.js'
import { createPlanningWorkspaceController } from '../../src/application/planning/planningWorkspaceController.js'
import {
  canonicalPlanningContentForUi,
  usePlanningStore,
} from '../../src/stores/planningStore.js'

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

function confirmablePlanningContent(hash = HASH) {
  return {
    schemaVersion: 'planning-v1',
    activeStoryBlockId: 'block-1',
    volumes: [{
      id: 'volume-1',
      order: 1,
      title: '第一卷',
      coreChange: '主角从逃亡转为主动追查',
      mainPressure: '',
      ensembleFocus: [],
      forbiddenEvents: [],
      lifecycle: 'active',
    }],
    plots: [{
      id: 'plot-1',
      order: 1,
      title: '典籍暗线',
      plotType: 'main',
      storyQuestion: '残卷为何选择沈砚',
      futureDirection: '',
      expectedPayoff: '',
      relatedCharacters: [],
      lifecycle: 'active',
    }],
    storyBlocks: [{
      id: 'block-1',
      order: 1,
      title: '夜入县衙',
      entrySituation: '',
      blockGoal: '在追兵抵达前取得残卷',
      mainPressure: '',
      expectedChange: '',
      openQuestions: [],
      involvedCharacters: [],
      volumeId: 'volume-1',
      plotIds: ['plot-1'],
      lifecycle: 'active',
      stages: [{
        id: 'stage-1',
        order: 1,
        title: '潜入',
        purpose: '进入县衙密库',
        dramaticQuestion: '沈砚能否避开巡夜守卫',
        lifecycle: 'active',
        sceneTasks: [{
          id: 'task-1',
          order: 1,
          task: '取得残卷',
          completionEvidence: '残卷到手',
          lifecycle: 'active',
        }],
      }],
    }],
    contentHash: hash,
  }
}

function confirmableEditableContent() {
  return {
    activeStoryBlockRef: 'block-1',
    volumes: [{
      id: 'volume-1',
      order: 1,
      title: '第一卷',
      coreChange: '主角从逃亡转为主动追查',
      mainPressure: '',
      ensembleFocus: [],
      forbiddenEvents: [],
      lifecycle: 'active',
    }],
    plots: [{
      id: 'plot-1',
      order: 1,
      title: '典籍暗线',
      plotType: 'main',
      storyQuestion: '残卷为何选择沈砚',
      futureDirection: '',
      expectedPayoff: '',
      relatedCharacters: [],
      lifecycle: 'active',
    }],
    storyBlocks: [{
      id: 'block-1',
      order: 1,
      title: '夜入县衙',
      entrySituation: '',
      blockGoal: '在追兵抵达前取得残卷',
      mainPressure: '',
      expectedChange: '',
      openQuestions: [],
      involvedCharacters: [],
      volumeRef: 'volume-1',
      plotRefs: ['plot-1'],
      lifecycle: 'active',
      stages: [{
        id: 'stage-1',
        order: 1,
        title: '潜入',
        purpose: '进入县衙密库',
        dramaticQuestion: '沈砚能否避开巡夜守卫',
        lifecycle: 'active',
        sceneTasks: [{
          id: 'task-1',
          order: 1,
          task: '取得残卷',
          completionEvidence: '残卷到手',
          lifecycle: 'active',
        }],
      }],
    }],
  }
}

test('canonical UI normalizer maps only authoritative planning field names', () => {
  const authoritative = confirmablePlanningContent()
  authoritative.volumes.push({
    id: 'volume-retired',
    order: 2,
    title: '旧卷',
    lifecycle: 'retired',
  })
  authoritative.plots.push({
    id: 'plot-retired',
    order: 2,
    title: '旧线',
    lifecycle: 'retired',
  })
  authoritative.storyBlocks[0].volumeId = 'volume-retired'
  authoritative.storyBlocks[0].plotIds = ['plot-1', 'plot-retired']
  authoritative.storyBlocks[0].volumeRef = 'must-not-be-read'
  authoritative.storyBlocks[0].plotRefs = ['must-not-be-read']

  const normalized = canonicalPlanningContentForUi(authoritative)

  assert.equal(normalized.activeStoryBlockRef, 'block-1')
  assert.equal(normalized.storyBlocks[0].volumeRef, 'volume-retired')
  assert.deepEqual(normalized.storyBlocks[0].plotRefs, ['plot-1', 'plot-retired'])
  assert.equal(normalized.volumes[1].title, '旧卷')
  assert.equal(normalized.plots[1].lifecycle, 'retired')
  assert.equal('activeStoryBlockId' in normalized, false)
  assert.equal('volumeId' in normalized.storyBlocks[0], false)
  assert.equal('plotIds' in normalized.storyBlocks[0], false)
  assert.equal('schemaVersion' in normalized, false)
  assert.equal('contentHash' in normalized, false)
})

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

function readyState(projectId = 'project-1', activeDraft = draft()) {
  const result = state(projectId, activeDraft)
  result.capabilities.generate = true
  return result
}

function operation(overrides = {}) {
  return {
    operationId: 'operation-1',
    status: 'succeeded',
    failureCode: null,
    model: {
      providerId: 'provider-1',
      modelName: 'deepseek-v4-flash',
    },
    loaded: true,
    loadedDraftRevision: 2,
    ...overrides,
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

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

const SENSITIVE_PLANNING_KEYS = [
  'sk-TestSentinel123456',
  'sk_TestSentinel123456',
  'ghp_TestSentinel12345678901234567890',
  'gho_TestSentinel12345678901234567890',
  'ghu_TestSentinel12345678901234567890',
  'ghs_TestSentinel12345678901234567890',
  'ghr_TestSentinel12345678901234567890',
  'github_pat_TestSentinel1234567890',
  'AKIAABCDEFGHIJKLMNOP',
  'ASIA1234567890ABCDEF',
  'AIzaTestSentinel12345678901234567890123',
  'Authorization-Bearer-TestSentinel',
  'bearer.TestSentinel',
  'apiKey-TestSentinel',
  'api_key.TestSentinel',
  'access-token-TestSentinel',
  'TOKEN-TestSentinel',
  'planning.secret.attempt',
  'PASSWORD:TestSentinel',
  'passwd-TestSentinel',
  'credential_TestSentinel',
  'DSN.TestSentinel',
  'planning%2Dencoded',
]

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
  assert.equal(typeof api.planning.generateDraft, 'function')
  assert.equal(typeof api.planning.getOperation, 'function')
  assert.equal(api.planning.createInitial, undefined)
})

test('sensitive generation keys fail before API calls and never enter recovery state', async () => {
  let generationCalls = 0
  await withApiMethods([
    [api.planning, 'get', async () => readyState('project-1', draft())],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'generateDraft', async () => {
      generationCalls += 1
      throw new TypeError('Invalid Planning idempotency key')
    }],
  ], async () => {
    for (const key of SENSITIVE_PLANNING_KEYS) {
      setActivePinia(createPinia())
      const store = usePlanningStore()
      await store.load('project-1')

      await assert.rejects(
        store.generateDraft({ idempotencyKey: key, authorInstructions: '' }),
        error => {
          assert.equal(error.message, 'Invalid Planning idempotency key')
          assert.equal(String(error).includes(key), false)
          return true
        },
      )
      assert.equal(store.generating, false)
      assert.equal(store.generationOutcomeUnknown, false)
      assert.equal(store.generationRecoveryKey, '')
      assert.equal(store.generationOperation, null)
    }
  })
  assert.equal(generationCalls, 0)
})

test('ensureLoaded preserves dirty content for same-project route switches and reload is explicit', async () => {
  let reads = 0
  await withApiMethods([
    [api.planning, 'get', async () => {
      reads += 1
      return state('project-1', draft(reads === 1 ? HASH : NEXT_HASH, reads))
    }],
    [api.planning, 'history', async () => ({ items: [] })],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.ensureLoaded('project-1')
    const local = { ...store.localContent, activeStoryBlockRef: 'author-edit' }
    store.editLocal(local)

    await store.ensureLoaded('project-1')

    assert.equal(reads, 1)
    assert.deepEqual(store.localContent, local)
    assert.equal(store.dirty, true)

    await store.ensureLoaded('project-1', { force: true })
    assert.equal(reads, 2)
    assert.equal(store.state.draft.draftRevision, 2)
    assert.equal(store.dirty, false)
  })
})

test('one active generation sends one POST and pending reconciliation uses GET only', async () => {
  const pendingPost = deferred()
  const calls = []
  await withApiMethods([
    [api.planning, 'get', async () => readyState('project-1', draft())],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'generateDraft', async (projectId, draftId, command) => {
      calls.push(['post', projectId, draftId, structuredClone(command)])
      return pendingPost.promise
    }],
    [api.planning, 'getOperation', async (projectId, operationId) => {
      calls.push(['get', projectId, operationId])
      return operation({
        operationId,
        status: 'superseded',
        loaded: false,
        loadedDraftRevision: null,
      })
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    const first = store.generateDraft({
      idempotencyKey: 'generate-1',
      authorInstructions: '加强人物冲突',
    })
    assert.equal(store.generating, true)
    await assert.rejects(
      store.generateDraft({
        idempotencyKey: 'generate-2',
        authorInstructions: '',
      }),
      /generation.*progress|生成.*进行/i,
    )
    pendingPost.resolve(operation({
      status: 'pending',
      loaded: false,
      loadedDraftRevision: null,
    }))
    await first
    assert.equal(store.generating, true)

    await store.reconcileGeneration()

    assert.deepEqual(calls, [
      ['post', 'project-1', 'draft-1', {
        draftRevision: 1,
        draftHash: HASH,
        idempotencyKey: 'generate-1',
        authorInstructions: '加强人物冲突',
      }],
      ['get', 'project-1', 'operation-1'],
    ])
    assert.equal(store.generationOperation.status, 'superseded')
    assert.equal(store.generating, false)
  })
})

test('real client network, abort and 504 failures recover only by idempotency key', async () => {
  const originalFetch = global.fetch
  const failures = ['network', 'abort', 'http-504']
  try {
    for (const mode of failures) {
      let posts = 0
      let byKeyReads = 0
      let planningReads = 0
      const key = `unknown-${mode}`
      global.fetch = async (url, options) => {
        const path = new URL(String(url)).pathname
        if (path.endsWith('/planning') && options.method === 'GET') {
          planningReads += 1
          return jsonResponse(readyState('project-1', draft()))
        }
        if (path.endsWith('/planning/history')) {
          return jsonResponse({ items: [] })
        }
        if (path.endsWith('/generate')) {
          posts += 1
          if (mode === 'network') throw new TypeError('network sentinel')
          if (mode === 'abort') {
            const aborted = new Error('abort sentinel')
            aborted.name = 'AbortError'
            throw aborted
          }
          return jsonResponse({
            code: 'GatewayTimeout',
            message: 'gateway timeout',
            operationId: 'must-be-discarded-by-api-error',
          }, 504)
        }
        if (path.includes('/operations/by-idempotency-key/')) {
          byKeyReads += 1
          return jsonResponse({
            code: 'PlanningGenerationOperationNotFound',
            message: 'Planning generation operation not found',
          }, 404)
        }
        throw new Error(`unexpected request ${options.method} ${path}`)
      }

      setActivePinia(createPinia())
      const store = usePlanningStore()
      await store.load('project-1')
      const before = structuredClone(store.localContent)
      await assert.rejects(
        store.generateDraft({ idempotencyKey: key, authorInstructions: '' }),
        error => error.code === 'PlanningGenerationOutcomeUnknown',
      )

      assert.equal(posts, 1)
      assert.equal(store.generationOperation, null)
      assert.equal(store.generationRecoveryKey, key)
      assert.equal(store.generationOutcomeUnknown, true)
      assert.equal(store.generating, true)
      assert.deepEqual(store.localContent, before)

      await assert.rejects(
        store.reconcileGeneration(),
        error => error.status === 404,
      )
      assert.equal(byKeyReads, 1)
      assert.equal(store.generationOutcomeUnknown, true)
      assert.equal(store.generationRecoveryKey, key)
      await assert.rejects(
        store.generateDraft({
          idempotencyKey: `${key}-again`,
          authorInstructions: '',
        }),
        /结果未知|生成.*进行/,
      )
      await assert.rejects(
        store.saveDraft({ idempotencyKey: `${key}-save` }),
        /结果未知|恢复/,
      )
      await assert.rejects(
        store.ensureLoaded('project-1', { force: true }),
        /幂等键|结果未知/,
      )
      assert.equal(posts, 1)
      assert.equal(planningReads, 1)
    }
  } finally {
    global.fetch = originalFetch
  }
})

test('by-key pending recovery stays critical and every later check uses operation id', async () => {
  const originalFetch = global.fetch
  const operationId = '123e4567-e89b-12d3-a456-426614174000'
  const paths = []
  let planningReads = 0
  let posts = 0
  let byKeyReads = 0
  let operationReads = 0
  try {
    global.fetch = async (url, options) => {
      const path = new URL(String(url)).pathname
      paths.push([options.method, path])
      if (path.endsWith('/planning') && options.method === 'GET') {
        planningReads += 1
        return jsonResponse(
          planningReads === 1
            ? readyState('project-1', draft())
            : readyState('project-1', draft(NEXT_HASH, 2)),
        )
      }
      if (path.endsWith('/planning/history')) {
        return jsonResponse({ items: [] })
      }
      if (path.endsWith('/generate')) {
        posts += 1
        throw new TypeError('network result unknown')
      }
      if (path.includes('/operations/by-idempotency-key/')) {
        byKeyReads += 1
        return jsonResponse(operation({
          operationId,
          status: 'pending',
          loaded: false,
          loadedDraftRevision: null,
        }))
      }
      if (path.endsWith(`/operations/${operationId}`)) {
        operationReads += 1
        return jsonResponse(operation(
          operationReads === 1
            ? {
              operationId,
              status: 'pending',
              loaded: false,
              loadedDraftRevision: null,
            }
            : { operationId },
        ))
      }
      throw new Error(`unexpected request ${options.method} ${path}`)
    }

    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    await assert.rejects(
      store.generateDraft({
        idempotencyKey: 'recover-by-key',
        authorInstructions: '',
      }),
      error => error.code === 'PlanningGenerationOutcomeUnknown',
    )

    await store.reconcileGeneration()
    assert.equal(store.generationOperation.operationId, operationId)
    assert.equal(store.generationOperation.status, 'pending')
    assert.equal(store.generationOutcomeUnknown, true)
    assert.equal(store.generating, true)
    await assert.rejects(
      store.ensureLoaded('project-1', { force: true }),
      /结果未知|核对/,
    )

    await store.reconcileGeneration()
    assert.equal(store.generationOperation.operationId, operationId)
    assert.equal(store.generationOperation.status, 'pending')
    assert.equal(store.generationOutcomeUnknown, true)
    assert.equal(store.generating, true)
    assert.equal(store.reconciling, false)

    await store.reconcileGeneration()
    assert.equal(posts, 1)
    assert.equal(byKeyReads, 1)
    assert.equal(operationReads, 2)
    assert.equal(store.state.draft.draftRevision, 2)
    assert.equal(store.generationRecoveryKey, '')
    assert.equal(store.generating, false)
    assert.deepEqual(paths.slice(3).map(item => item[1]), [
      '/api/projects/project-1/planning/operations/by-idempotency-key/recover-by-key',
      `/api/projects/project-1/planning/operations/${operationId}`,
      `/api/projects/project-1/planning/operations/${operationId}`,
      '/api/projects/project-1/planning',
    ])
  } finally {
    global.fetch = originalFetch
  }
})

test('known HTTP generation rejection is not mislabeled as an unknown outcome', async () => {
  const conflict = Object.assign(new Error('规划版本已变化'), {
    status: 409,
    code: 'PlanningGenerationConflict',
    correlationId: 'corr-known',
  })
  await withApiMethods([
    [api.planning, 'get', async () => readyState('project-1', draft())],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'generateDraft', async () => { throw conflict }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')

    await assert.rejects(
      store.generateDraft({ idempotencyKey: 'known-conflict', authorInstructions: '' }),
      conflict,
    )

    assert.equal(store.generating, false)
    assert.equal(store.generationOutcomeUnknown, false)
    assert.equal(store.generationOperation, null)
    assert.equal(store.error.code, 'PlanningGenerationConflict')
  })
})

test('loaded generation reloads authoritative exact draft but never overwrites a dirty local edit', async () => {
  const generated = deferred()
  let reads = 0
  await withApiMethods([
    [api.planning, 'get', async () => {
      reads += 1
      return readyState('project-1', reads === 1 ? draft() : draft(NEXT_HASH, 2))
    }],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'generateDraft', async () => generated.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    const generating = store.generateDraft({
      idempotencyKey: 'generate-loaded',
      authorInstructions: '',
    })
    const local = { ...store.localContent, activeStoryBlockRef: 'author-edit' }
    store.editLocal(local)
    generated.resolve(operation())
    await generating

    assert.equal(reads, 2)
    assert.equal(store.state.draft.draftRevision, 1)
    assert.deepEqual(store.localContent, local)
    assert.equal(store.dirty, true)
    assert.equal(store.generationOperation.status, 'succeeded')
    assert.equal(store.awaitingAuthoritativeReload, true)
    assert.equal(store.generating, true)

    await store.ensureLoaded('project-1', { force: true })
    assert.equal(reads, 3)
    assert.equal(store.state.draft.draftRevision, 2)
    assert.equal(store.dirty, false)
    assert.equal(store.awaitingAuthoritativeReload, false)
    assert.equal(store.generating, false)
  })
})

test('authority reload failure keeps the known operation gate until GET reconciliation succeeds', async () => {
  const refreshFailure = Object.assign(new Error('refresh failed'), {
    status: 503,
    code: 'request_failed',
  })
  let stateReads = 0
  let operationReads = 0
  let posts = 0
  let saves = 0
  await withApiMethods([
    [api.planning, 'get', async () => {
      stateReads += 1
      if (stateReads === 1) return readyState('project-1', draft())
      if (stateReads === 2) throw refreshFailure
      return readyState('project-1', draft(NEXT_HASH, 2))
    }],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'generateDraft', async () => {
      posts += 1
      return operation()
    }],
    [api.planning, 'saveDraft', async () => {
      saves += 1
      return draft(NEXT_HASH, 2)
    }],
    [api.planning, 'getOperation', async (_projectId, operationId) => {
      operationReads += 1
      return operation({ operationId })
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    await store.generateDraft({
      idempotencyKey: 'reload-fails',
      authorInstructions: '',
    })

    assert.equal(store.awaitingAuthoritativeReload, true)
    assert.equal(store.generating, true)
    assert.equal(store.generationOperation.operationId, 'operation-1')
    assert.equal(store.error.code, 'PlanningGenerationRefreshFailed')
    await assert.rejects(
      store.generateDraft({
        idempotencyKey: 'must-not-repost-after-refresh-failure',
        authorInstructions: '',
      }),
      /generation.*progress|生成.*进行|权威.*回读/i,
    )
    assert.equal(posts, 1)
    await assert.rejects(
      store.saveDraft({ idempotencyKey: 'must-not-save-before-authority' }),
      /权威.*回读/,
    )
    assert.equal(saves, 0)

    await store.reconcileGeneration()

    assert.equal(operationReads, 1)
    assert.equal(posts, 1)
    assert.equal(stateReads, 3)
    assert.equal(store.awaitingAuthoritativeReload, false)
    assert.equal(store.generating, false)
    assert.equal(store.state.draft.draftRevision, 2)
  })
})

test('authority recovery rejects regressive operation state and keeps the exact operation', async () => {
  let stateReads = 0
  let operationReads = 0
  await withApiMethods([
    [api.planning, 'get', async () => {
      stateReads += 1
      if (stateReads === 1) return readyState('project-1', draft())
      throw Object.assign(new Error('authority unavailable'), { status: 503 })
    }],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'generateDraft', async () => operation()],
    [api.planning, 'getOperation', async (_projectId, operationId) => {
      operationReads += 1
      return operation({
        operationId,
        status: 'pending',
        loaded: false,
        loadedDraftRevision: null,
      })
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    await store.generateDraft({
      idempotencyKey: 'authority-regression',
      authorInstructions: '',
    })

    await store.reconcileGeneration()

    assert.equal(operationReads, 1)
    assert.equal(store.generationOperation.status, 'succeeded')
    assert.equal(store.generationOperation.loaded, true)
    assert.equal(store.awaitingAuthoritativeReload, true)
    assert.equal(store.generating, true)
    assert.equal(store.error.code, 'PlanningGenerationOperationRegressed')
  })
})

test('mismatched or malformed authority reloads stay gated until the exact draft is read', async () => {
  const badStates = [
    readyState('project-other', draft(NEXT_HASH, 2)),
    readyState('project-1', {
      ...draft(NEXT_HASH, 2),
      projectId: 'project-other',
    }),
    readyState('project-1', { ...draft(NEXT_HASH, 2), draftId: 'draft-other' }),
    readyState('project-1', draft(NEXT_HASH, 3)),
    readyState('project-1', {
      ...draft(NEXT_HASH, 2),
      contentHash: 'not-a-hash',
    }),
    readyState('project-1', {
      ...draft(NEXT_HASH, 2),
      content: { ...planningContent(HASH), contentHash: HASH },
    }),
    { projectId: 'project-1', draft: { draftId: 'draft-1', draftRevision: 2 } },
  ]

  for (const badState of badStates) {
    let stateReads = 0
    let operationReads = 0
    let posts = 0
    await withApiMethods([
      [api.planning, 'get', async () => {
        stateReads += 1
        if (stateReads === 1) return readyState('project-1', draft())
        if (stateReads === 2) return badState
        return readyState('project-1', draft(NEXT_HASH, 2))
      }],
      [api.planning, 'history', async () => ({ items: [] })],
      [api.planning, 'generateDraft', async () => {
        posts += 1
        return operation()
      }],
      [api.planning, 'getOperation', async (_projectId, operationId) => {
        operationReads += 1
        return operation({ operationId })
      }],
    ], async () => {
      setActivePinia(createPinia())
      const store = usePlanningStore()
      await store.load('project-1')
      await store.generateDraft({
        idempotencyKey: `bad-authority-${badStates.indexOf(badState)}`,
        authorInstructions: '',
      })

      assert.equal(store.awaitingAuthoritativeReload, true)
      assert.equal(store.generating, true)
      assert.equal(store.state.draft.draftRevision, 1)
      await assert.rejects(
        store.generateDraft({
          idempotencyKey: 'must-not-repost',
          authorInstructions: '',
        }),
        /generation.*progress|生成.*进行|权威.*回读/i,
      )

      await store.reconcileGeneration()
      assert.equal(posts, 1)
      assert.equal(operationReads, 1)
      assert.equal(stateReads, 3)
      assert.equal(store.awaitingAuthoritativeReload, false)
      assert.equal(store.generating, false)
      assert.equal(store.state.draft.draftRevision, 2)
    })
  }
})

test('loaded generation remains the single active generation until authority reload settles', async () => {
  const reload = deferred()
  let reads = 0
  let posts = 0
  await withApiMethods([
    [api.planning, 'get', async () => {
      reads += 1
      if (reads === 1) return readyState('project-1', draft())
      return reload.promise
    }],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'generateDraft', async () => {
      posts += 1
      return operation()
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    const first = store.generateDraft({
      idempotencyKey: 'generate-authority-reload',
      authorInstructions: '',
    })
    await Promise.resolve()
    await Promise.resolve()

    assert.equal(store.generating, true)
    await assert.rejects(
      store.generateDraft({
        idempotencyKey: 'must-not-post',
        authorInstructions: '',
      }),
      /generation.*progress|生成.*进行|权威.*回读/i,
    )
    assert.equal(posts, 1)

    reload.resolve(readyState('project-1', draft(NEXT_HASH, 2)))
    await first
    assert.equal(store.generating, false)
  })
})

test('failed, superseded and unloaded results never reload or overwrite local content', async () => {
  for (const result of [
    operation({
      status: 'failed',
      failureCode: 'PlanningGenerationFailed',
      loaded: false,
      loadedDraftRevision: null,
    }),
    operation({
      status: 'superseded',
      loaded: false,
      loadedDraftRevision: null,
    }),
    operation({
      status: 'succeeded',
      loaded: false,
      loadedDraftRevision: null,
    }),
  ]) {
    let reads = 0
    await withApiMethods([
      [api.planning, 'get', async () => {
        reads += 1
        return readyState('project-1', draft())
      }],
      [api.planning, 'history', async () => ({ items: [] })],
      [api.planning, 'generateDraft', async () => result],
    ], async () => {
      setActivePinia(createPinia())
      const store = usePlanningStore()
      await store.load('project-1')
      const before = structuredClone(store.localContent)
      await store.generateDraft({
        idempotencyKey: `generate-${result.status}`,
        authorInstructions: '',
      })
      assert.equal(reads, 1)
      assert.deepEqual(store.localContent, before)
      assert.equal(store.dirty, false)
    })
  }
})

test('late old-project and old-operation results cannot overwrite current state', async () => {
  const oldPost = deferred()
  const oldGet = deferred()
  await withApiMethods([
    [api.planning, 'get', async projectId => readyState(projectId, {
      ...draft(),
      projectId,
      draftId: `${projectId}-draft`,
    })],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'generateDraft', async projectId => (
      projectId === 'project-1' ? oldPost.promise : operation({
        operationId: 'operation-new',
        loaded: false,
        loadedDraftRevision: null,
      })
    )],
    [api.planning, 'getOperation', async () => oldGet.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    const first = store.generateDraft({
      idempotencyKey: 'old-project',
      authorInstructions: '',
    })
    await store.load('project-2')
    oldPost.resolve(operation({
      operationId: 'operation-old',
      loaded: false,
      loadedDraftRevision: null,
    }))
    await first
    assert.equal(store.projectId, 'project-2')
    assert.equal(store.generationOperation, null)

    const second = await store.generateDraft({
      idempotencyKey: 'new-operation',
      authorInstructions: '',
    })
    assert.equal(second.operationId, 'operation-new')
    store.generationOperation = operation({
      operationId: 'operation-old',
      status: 'pending',
      loaded: false,
      loadedDraftRevision: null,
    })
    const reconcile = store.reconcileGeneration()
    store.generationOperation = operation({
      operationId: 'operation-new',
      loaded: false,
      loadedDraftRevision: null,
    })
    oldGet.resolve(operation({
      operationId: 'operation-old',
      loaded: true,
      loadedDraftRevision: 2,
    }))
    await reconcile
    assert.equal(store.generationOperation.operationId, 'operation-new')
    assert.equal(store.state.draft.draftId, 'project-2-draft')
  })
})

test('model-unready rejects only generation while manual editing and save remain available', async () => {
  let generates = 0
  let saves = 0
  await withApiMethods([
    [api.planning, 'get', async () => state('project-1', draft())],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'generateDraft', async () => {
      generates += 1
      return operation()
    }],
    [api.planning, 'saveDraft', async () => {
      saves += 1
      return draft(NEXT_HASH, 2)
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    await assert.rejects(
      store.generateDraft({ idempotencyKey: 'unready', authorInstructions: '' }),
      /model.*not ready|模型.*未就绪/i,
    )
    assert.equal(generates, 0)

    store.editLocal({ ...store.localContent, activeStoryBlockRef: 'manual' })
    await store.saveDraft({ idempotencyKey: 'manual-save' })
    assert.equal(saves, 1)
    assert.equal(store.dirty, false)
  })
})

test('planning store loads state, history and starts an explicit draft', async () => {
  const calls = []
  let stateReads = 0
  await withApiMethods([
    [api.planning, 'get', async projectId => {
      calls.push(['get', projectId])
      stateReads += 1
      return state(
        projectId,
        stateReads === 1 ? null : { ...draft(), projectId },
      )
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
      ['get', 'project-1'],
    ])
  })
})

test('editing is local until save and successful save refreshes the CAS baseline', async () => {
  const calls = []
  let stateReads = 0
  const savedDraft = {
    ...draft(NEXT_HASH, 2),
    content: { ...planningContent(NEXT_HASH), activeStoryBlockId: 'block-1' },
  }
  await withApiMethods([
    [api.planning, 'get', async () => {
      stateReads += 1
      return state('project-1', stateReads === 1 ? draft() : savedDraft)
    }],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'saveDraft', async (projectId, draftId, body) => {
      calls.push([projectId, draftId, structuredClone(body)])
      return savedDraft
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

test('confirmed planning can create and save the next draft then regain authoritative confirmation capability', async () => {
  const firstDraft = {
    ...draft(),
    content: confirmablePlanningContent(),
  }
  const nextEmptyDraft = {
    ...draft(NEXT_HASH, 1),
    draftId: 'draft-2',
  }
  const nextSavedDraft = {
    ...draft(HASH, 2),
    draftId: 'draft-2',
    content: confirmablePlanningContent(HASH),
  }
  let stateReads = 0
  let sequence = 0
  await withApiMethods([
    [api.planning, 'get', async projectId => {
      stateReads += 1
      if (stateReads === 1) return state(projectId, firstDraft)
      if (stateReads === 2) return state(projectId, null)
      if (stateReads === 3) {
        const loaded = state(projectId, nextEmptyDraft)
        loaded.capabilities.confirm = false
        return loaded
      }
      const loaded = state(projectId, nextSavedDraft)
      loaded.capabilities.confirm = true
      return loaded
    }],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'confirmDraft', async () => ({
      planningRevisionId: 'revision-1',
      revision: 1,
      contentHash: HASH,
      content: confirmablePlanningContent(),
    })],
    [api.planning, 'createDraft', async () => nextEmptyDraft],
    [api.planning, 'saveDraft', async () => nextSavedDraft],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => 'project-1',
      keyFactory: () => `planning-command-${++sequence}`,
    })

    await store.load('project-1')
    assert.equal(controller.canConfirm.value, true)

    await controller.confirm()
    assert.equal(store.state.draft, null)
    assert.equal(controller.canConfirm.value, false)

    await controller.createManualDraft()
    assert.equal(store.state.draft.draftId, 'draft-2')
    assert.equal(controller.canConfirm.value, false)

    store.editLocal(confirmableEditableContent())
    assert.equal(controller.canSave.value, true)
    await controller.save()

    assert.equal(store.dirty, false)
    assert.equal(store.state.draft.draftRevision, 2)
    assert.equal(store.state.capabilities.confirm, true)
    assert.equal(controller.canConfirm.value, true)
    assert.equal(stateReads, 4)
  })
})

test('successful save keeps its new draft but fails confirmation closed until authority reload recovers', async () => {
  const initialDraft = {
    ...draft(),
    content: confirmablePlanningContent(),
  }
  const savedDraft = {
    ...draft(NEXT_HASH, 2),
    content: confirmablePlanningContent(NEXT_HASH),
  }
  const refreshFailure = Object.assign(new Error('authority unavailable'), {
    status: 503,
    code: 'PlanningUnavailable',
    correlationId: 'corr-refresh',
  })
  let stateReads = 0
  await withApiMethods([
    [api.planning, 'get', async projectId => {
      stateReads += 1
      if (stateReads === 1) return state(projectId, initialDraft)
      if (stateReads === 2) throw refreshFailure
      const loaded = state(projectId, savedDraft)
      loaded.capabilities.confirm = true
      return loaded
    }],
    [api.planning, 'history', async () => ({ items: [] })],
    [api.planning, 'saveDraft', async () => savedDraft],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    const controller = createPlanningWorkspaceController({
      store,
      projectId: () => 'project-1',
      keyFactory: () => 'save-with-refresh-failure',
    })

    await store.load('project-1')
    assert.equal(controller.canConfirm.value, true)
    store.editLocal(confirmableEditableContent())

    const result = await controller.save()

    assert.equal(result.draftRevision, 2)
    assert.equal(store.state.draft.draftRevision, 2)
    assert.equal(store.dirty, false)
    assert.equal(store.error.code, 'PlanningRefreshFailed')
    assert.equal(store.error.correlationId, 'corr-refresh')
    assert.equal(store.state.capabilities.confirm, false)
    assert.equal(controller.canConfirm.value, false)

    await store.ensureLoaded('project-1', { force: true })
    assert.equal(store.state.capabilities.confirm, true)
    assert.equal(controller.canConfirm.value, true)
    assert.equal(stateReads, 3)
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

function outlineContent(goal = '取得残卷') {
  return {
    schemaVersion: 'chapter-outline-draft-v1',
    volumeRef: { id: 'volume-1', revision: 1, contentHash: HASH },
    storyBlockRef: { id: 'block-1', revision: 1, contentHash: HASH },
    stageRefs: [{ id: 'stage-1', revision: 1, contentHash: HASH }],
    sceneTaskRefs: [{ id: 'task-1', revision: 1, contentHash: HASH }],
    chapterGoal: goal,
    expectedCharacters: ['沈砚'],
    continuation: ['追兵逼近'],
    plannedTasks: ['潜入'],
    scenes: ['县衙外'],
    forbiddenEarlyEvents: ['不揭密'],
  }
}

function outlineDraft(overrides = {}) {
  return {
    projectId: 'project-1',
    chapterNumber: 1,
    draftId: 'outline-draft-1',
    baseHeadRevision: 0,
    draftRevision: 1,
    contentHash: HASH,
    content: outlineContent(),
    basis: {
      planningAuthority: {
        planningRevisionId: 'planning-1',
        revision: 1,
        contentHash: HASH,
        content: confirmablePlanningContent(),
      },
      canonProjectionAuthority: {
        canonRevision: 0,
        projectionRevision: 0,
        contentHash: HASH,
        synchronized: true,
      },
    },
    status: 'current',
    ...overrides,
  }
}

function outlineState(projectId = 'project-1', activeDraft = outlineDraft()) {
  return {
    projectId,
    lifecycle: 'active',
    authoritativeChapterNumber: 1,
    targetPath: `/projects/${projectId}/planning/story-blocks`,
    planningAuthority: activeDraft?.basis?.planningAuthority || null,
    canonProjectionAuthority: activeDraft?.basis?.canonProjectionAuthority || null,
    confirmedOutline: null,
    draft: activeDraft ? { ...activeDraft, projectId } : null,
    activeSession: null,
    capabilities: {
      view: true,
      createDraft: activeDraft == null,
      editDraft: activeDraft != null,
      generate: false,
      confirm: activeDraft != null,
      startSession: false,
    },
    reasons: [],
  }
}

test('single planning store owns the exact ChapterOutline child refs', () => {
  setActivePinia(createPinia())
  const store = usePlanningStore()
  for (const field of [
    'outlineState',
    'outlineHistory',
    'outlineLocalContent',
    'outlineDirty',
    'outlineError',
    'outlineLoading',
    'outlineSaving',
    'outlineConfirming',
    'outlineGenerating',
    'outlineReconciling',
    'outlineOperation',
    'outlineRecoveryKey',
    'outlineOutcomeUnknown',
    'outlineAwaitingAuthority',
  ]) {
    assert.equal(field in store, true, field)
  }
  assert.equal(store.outlineDirty, false)
  assert.deepEqual(store.outlineHistory, [])
})

test('outline loading is context fenced and same-project reload preserves local edits', async () => {
  const oldCurrent = deferred()
  let currentReads = 0
  await withApiMethods([
    [api.chapterOutlines, 'current', projectId => {
      currentReads += 1
      return projectId === 'project-1'
        ? oldCurrent.promise
        : Promise.resolve(outlineState(projectId, null))
    }],
    [api.chapterOutlines, 'history', async projectId => ({
      items: [{ projectId, revision: 1, status: 'current' }],
    })],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    const oldLoad = store.loadOutline('project-1')
    await store.loadOutline('project-2')
    oldCurrent.resolve(outlineState('project-1'))
    await oldLoad

    assert.equal(store.outlineState.projectId, 'project-2')
    assert.equal(store.outlineHistory[0].projectId, 'project-2')

    store.outlineState = outlineState('project-2', {
      ...outlineDraft(),
      projectId: 'project-2',
    })
    store.outlineLocalContent = outlineContent()
    store.editOutlineLocal(outlineContent('作者本地目标'))
    await store.ensureOutlineLoaded('project-2')
    assert.equal(currentReads, 2)
    assert.equal(store.outlineLocalContent.chapterGoal, '作者本地目标')
    assert.equal(store.outlineDirty, true)
  })
})

test('outline manual edit stays local until explicit save and works without a model', async () => {
  const calls = []
  let reads = 0
  const saved = outlineDraft({
    draftRevision: 2,
    contentHash: NEXT_HASH,
    content: outlineContent('作者本地目标'),
  })
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      reads += 1
      const value = outlineState('project-1', reads === 1 ? outlineDraft() : saved)
      value.capabilities.generate = false
      return value
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'saveDraft', async (...args) => {
      calls.push(structuredClone(args))
      return saved
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    store.editOutlineLocal(outlineContent('作者本地目标'))

    assert.equal(calls.length, 0)
    assert.equal(store.outlineState.draft.draftRevision, 1)
    assert.equal(store.outlineDirty, true)
    await assert.rejects(
      store.generateOutlineDraft({
        idempotencyKey: 'outline-generate',
        authorInstructions: '',
      }),
      /模型.*未就绪|model.*not ready/i,
    )

    await store.saveOutlineDraft()
    assert.deepEqual(calls[0], [
      'project-1',
      1,
      'outline-draft-1',
      {
        expectedDraftRevision: 1,
        expectedDraftHash: HASH,
        content: outlineContent('作者本地目标'),
      },
    ])
    assert.equal(store.outlineState.draft.draftRevision, 2)
    assert.equal(store.outlineLocalContent.chapterGoal, '作者本地目标')
    assert.equal(store.outlineDirty, false)
  })
})

test('outline save advances its baseline without erasing edits typed while the request is in flight', async () => {
  const saveResponse = deferred()
  let currentReads = 0
  const saved = outlineDraft({
    draftRevision: 2,
    contentHash: NEXT_HASH,
    content: outlineContent('开始保存时的目标'),
  })
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      currentReads += 1
      return outlineState(
        'project-1',
        currentReads === 1 ? outlineDraft() : saved,
      )
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'saveDraft', async () => saveResponse.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    store.editOutlineLocal(outlineContent('开始保存时的目标'))

    const save = store.saveOutlineDraft()
    store.editOutlineLocal(outlineContent('保存期间继续输入'))
    saveResponse.resolve(saved)
    await save

    assert.equal(store.outlineState.draft.draftRevision, 2)
    assert.equal(store.outlineState.draft.content.chapterGoal, '开始保存时的目标')
    assert.equal(store.outlineLocalContent.chapterGoal, '保存期间继续输入')
    assert.equal(store.outlineDirty, true)
    assert.equal(currentReads, 2)
  })
})

test('outline authority refresh cannot erase edits typed after the save response', async () => {
  const refreshStarted = deferred()
  const authorityResponse = deferred()
  let currentReads = 0
  const saved = outlineDraft({
    draftRevision: 2,
    contentHash: NEXT_HASH,
    content: outlineContent('服务端已保存目标'),
  })
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      currentReads += 1
      if (currentReads === 1) return outlineState()
      refreshStarted.resolve()
      return authorityResponse.promise
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'saveDraft', async () => saved],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    store.editOutlineLocal(outlineContent('服务端已保存目标'))

    const save = store.saveOutlineDraft()
    await refreshStarted.promise
    store.editOutlineLocal(outlineContent('刷新期间继续输入'))
    authorityResponse.resolve(outlineState('project-1', saved))
    await save

    assert.equal(store.outlineState.draft.draftRevision, 2)
    assert.equal(store.outlineState.draft.contentHash, NEXT_HASH)
    assert.equal(store.outlineState.draft.content.chapterGoal, '服务端已保存目标')
    assert.equal(store.outlineLocalContent.chapterGoal, '刷新期间继续输入')
    assert.equal(store.outlineDirty, true)
    assert.equal(currentReads, 2)
  })
})

test('stale outline save cannot replace a newer same-project draft snapshot', async () => {
  const saveResponse = deferred()
  let currentReads = 0
  const newerDraft = outlineDraft({
    draftRevision: 7,
    contentHash: NEXT_HASH,
    content: outlineContent('较新的权威目标'),
  })
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      currentReads += 1
      if (currentReads === 1) return outlineState()
      if (currentReads === 2) return outlineState('project-1', newerDraft)
      throw new Error('stale save attempted an authority refresh')
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'saveDraft', async () => saveResponse.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    store.editOutlineLocal(outlineContent('待保存目标'))

    const save = store.saveOutlineDraft()
    await store.loadOutline('project-1')
    saveResponse.resolve(outlineDraft({
      draftRevision: 2,
      contentHash: HASH,
      content: outlineContent('过期保存结果'),
    }))
    await save

    assert.equal(store.outlineState.draft.draftRevision, 7)
    assert.equal(store.outlineLocalContent.chapterGoal, '较新的权威目标')
    assert.equal(currentReads, 2)
  })
})

test('stale outline generation cannot replace a newer draft revision with the same id', async () => {
  const generationResponse = deferred()
  let currentReads = 0
  const newerDraft = outlineDraft({
    draftRevision: 7,
    contentHash: NEXT_HASH,
    content: outlineContent('较新的权威目标'),
  })
  const generatedDraft = outlineDraft({
    draftRevision: 2,
    contentHash: HASH,
    content: outlineContent('过期生成结果'),
  })
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      currentReads += 1
      const value = outlineState(
        'project-1',
        currentReads === 1
          ? outlineDraft()
          : currentReads === 2
            ? newerDraft
            : generatedDraft,
      )
      value.capabilities.generate = true
      return value
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'generateDraft', async () => generationResponse.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')

    const generate = store.generateOutlineDraft({
      idempotencyKey: 'outline-generate',
      authorInstructions: '',
    })
    await store.loadOutline('project-1')
    generationResponse.resolve({
      operationId: 'operation-stale',
      status: 'succeeded',
      failureCode: null,
      model: { providerId: 'provider-1', modelName: 'outline-model' },
      loaded: true,
      loadedDraftRevision: 2,
    })
    await generate

    assert.equal(store.outlineState.draft.draftRevision, 7)
    assert.equal(store.outlineLocalContent.chapterGoal, '较新的权威目标')
    assert.equal(currentReads, 2)
  })
})

test('outline reconciliation accepts only the recovery key that started the request', async () => {
  const reconciliationResponse = deferred()
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      const value = outlineState()
      value.capabilities.generate = true
      return value
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'getOperationByKey', async () => reconciliationResponse.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    store.outlineRecoveryKey = 'outline-recovery-old'
    store.outlineOutcomeUnknown = true

    const reconcile = store.reconcileOutlineGeneration()
    store.outlineRecoveryKey = 'outline-recovery-new'
    reconciliationResponse.resolve({
      operationId: 'operation-stale',
      status: 'pending',
      failureCode: null,
      model: { providerId: 'provider-1', modelName: 'outline-model' },
      loaded: false,
      loadedDraftRevision: null,
    })
    await reconcile

    assert.equal(store.outlineRecoveryKey, 'outline-recovery-new')
    assert.equal(store.outlineOperation, null)
  })
})

test('outline unknown generation reconciles by GET and loads only exact authority', async () => {
  const timeout = Object.assign(new Error('timeout'), {
    status: 0,
    code: 'request_timeout',
  })
  const generatedDraft = outlineDraft({
    draftRevision: 2,
    contentHash: NEXT_HASH,
    content: outlineContent('AI 权威目标'),
  })
  const calls = []
  let authorityReads = 0
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      authorityReads += 1
      const value = outlineState(
        'project-1',
        authorityReads === 1 ? outlineDraft() : generatedDraft,
      )
      value.capabilities.generate = true
      return value
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'generateDraft', async () => {
      calls.push('POST')
      throw timeout
    }],
    [api.chapterOutlines, 'getOperationByKey', async () => {
      calls.push('GET:key')
      return {
        operationId: 'operation-1',
        status: 'succeeded',
        failureCode: null,
        model: { providerId: 'provider-1', modelName: 'outline-model' },
        loaded: true,
        loadedDraftRevision: 2,
      }
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    await assert.rejects(
      store.generateOutlineDraft({
        idempotencyKey: 'outline-generate',
        authorInstructions: '',
      }),
      /结果未知|outcome unknown/i,
    )
    assert.equal(store.outlineOutcomeUnknown, true)
    assert.equal(store.outlineLocalContent.chapterGoal, '取得残卷')

    await store.reconcileOutlineGeneration()
    assert.deepEqual(calls, ['POST', 'GET:key'])
    assert.equal(store.outlineLocalContent.chapterGoal, 'AI 权威目标')
    assert.equal(store.outlineDirty, false)
    assert.equal(store.outlineOutcomeUnknown, false)
    assert.equal(store.outlineAwaitingAuthority, false)
  })
})

test('superseded outline authority never overwrites preserved local edits', async () => {
  const operationResult = {
    operationId: 'operation-1',
    status: 'succeeded',
    failureCode: null,
    model: { providerId: 'provider-1', modelName: 'outline-model' },
    loaded: true,
    loadedDraftRevision: 2,
  }
  let reads = 0
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      reads += 1
      const value = outlineState('project-1', reads === 1
        ? outlineDraft()
        : outlineDraft({
            draftRevision: 2,
            contentHash: NEXT_HASH,
            content: outlineContent('远端生成'),
            status: 'superseded',
          }))
      value.capabilities.generate = true
      return value
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'generateDraft', async () => operationResult],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    store.editOutlineLocal(outlineContent('作者未保存'))
    store.outlineDirty = false
    const promise = store.generateOutlineDraft({
      idempotencyKey: 'outline-generate',
      authorInstructions: '',
    })
    store.editOutlineLocal(outlineContent('生成期间的新编辑'))
    await promise

    assert.equal(store.outlineLocalContent.chapterGoal, '生成期间的新编辑')
    assert.equal(store.outlineDirty, true)
    assert.equal(store.outlineAwaitingAuthority, true)
  })
})

test('confirmed-only and superseded outline states create exactly one current draft', async () => {
  for (const mode of ['confirmed-only', 'superseded']) {
    let authorityReads = 0
    let creates = 0
    const created = outlineDraft({
      draftId: `outline-created-${mode}`,
      status: 'current',
    })
    const initial = mode === 'confirmed-only'
      ? outlineState('project-1', null)
      : outlineState('project-1', outlineDraft({ status: 'superseded' }))
    initial.confirmedOutline = {
      outlineRevisionId: 'confirmed-1',
      content: outlineContent('已确认目标'),
    }
    initial.capabilities.createDraft = true
    initial.capabilities.editDraft = false

    await withApiMethods([
      [api.chapterOutlines, 'current', async () => {
        authorityReads += 1
        if (authorityReads === 1) return structuredClone(initial)
        const loaded = outlineState('project-1', created)
        loaded.confirmedOutline = initial.confirmedOutline
        return loaded
      }],
      [api.chapterOutlines, 'history', async () => ({ items: [] })],
      [api.chapterOutlines, 'createDraft', async () => {
        creates += 1
        return structuredClone(created)
      }],
    ], async () => {
      setActivePinia(createPinia())
      const store = usePlanningStore()
      await store.loadOutline('project-1')

      await store.createOutlineDraft('project-1')

      assert.equal(creates, 1, mode)
      assert.equal(authorityReads, 2, mode)
      assert.equal(store.outlineState.draft.draftId, created.draftId, mode)
      assert.equal(store.outlineState.draft.status, 'current', mode)
      assert.equal(store.outlineState.capabilities.editDraft, true, mode)
      assert.deepEqual(store.outlineLocalContent, created.content, mode)
    })
  }
})

test('forced outline authority retry preserves local edits and retries only on command', async () => {
  const saved = outlineDraft({
    draftRevision: 2,
    contentHash: NEXT_HASH,
    content: outlineContent('服务端已保存目标'),
  })
  const refreshFailure = Object.assign(new Error('authority unavailable'), {
    status: 503,
    code: 'AuthorityUnavailable',
  })
  let authorityReads = 0
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      authorityReads += 1
      if (authorityReads === 1) return outlineState()
      if (authorityReads <= 3) throw refreshFailure
      const loaded = outlineState('project-1', saved)
      loaded.capabilities.generate = true
      return loaded
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'saveDraft', async () => saved],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    store.editOutlineLocal(outlineContent('服务端已保存目标'))
    await store.saveOutlineDraft()
    assert.equal(store.outlineError.code, 'ChapterOutlineRefreshFailed')

    store.editOutlineLocal(outlineContent('刷新失败后的本地输入'))
    await assert.rejects(
      store.ensureOutlineLoaded('project-1', { force: true }),
      /authority unavailable/,
    )
    assert.equal(authorityReads, 3)
    assert.equal(store.outlineError.code, 'ChapterOutlineRefreshFailed')
    assert.equal(store.outlineLocalContent.chapterGoal, '刷新失败后的本地输入')
    assert.equal(store.outlineDirty, true)

    await Promise.resolve()
    assert.equal(authorityReads, 3)

    await store.ensureOutlineLoaded('project-1', { force: true })
    assert.equal(authorityReads, 4)
    assert.equal(store.outlineState.draft.draftRevision, 2)
    assert.equal(store.outlineState.draft.contentHash, NEXT_HASH)
    assert.equal(store.outlineState.capabilities.generate, true)
    assert.equal(store.outlineLocalContent.chapterGoal, '刷新失败后的本地输入')
    assert.equal(store.outlineDirty, true)
    assert.equal(store.outlineError, null)
  })
})

test('outline reconciliation cannot regress a succeeded operation awaiting authority', async () => {
  const succeeded = {
    operationId: 'outline-operation-1',
    status: 'succeeded',
    failureCode: null,
    model: { providerId: 'provider-1', modelName: 'outline-model' },
    loaded: true,
    loadedDraftRevision: 2,
  }
  const regressiveResults = [
    { ...succeeded, status: 'pending', loaded: false, loadedDraftRevision: null },
    { ...succeeded, status: 'failed', loaded: false, loadedDraftRevision: null },
    { ...succeeded, loadedDraftRevision: 3 },
  ]
  let authorityReads = 0
  let operationReads = 0
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      authorityReads += 1
      const loaded = outlineState()
      loaded.capabilities.generate = true
      return loaded
    }],
    [api.chapterOutlines, 'history', async () => ({ items: [] })],
    [api.chapterOutlines, 'generateDraft', async () => succeeded],
    [api.chapterOutlines, 'getOperation', async () => (
      regressiveResults[operationReads++]
    )],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    const localBefore = structuredClone(store.outlineLocalContent)

    await store.generateOutlineDraft({
      idempotencyKey: 'outline-monotonic-operation',
      authorInstructions: '',
    })
    assert.equal(store.outlineAwaitingAuthority, true)
    assert.deepEqual(store.outlineOperation, succeeded)

    for (const result of regressiveResults) {
      assert.deepEqual(await store.reconcileOutlineGeneration(), result)
      assert.deepEqual(store.outlineOperation, succeeded)
      assert.equal(store.outlineAwaitingAuthority, true)
      assert.equal(store.outlineOutcomeUnknown, false)
      assert.equal(store.outlineGenerating, true)
      assert.deepEqual(store.outlineLocalContent, localBefore)
      assert.equal(store.outlineDirty, false)
    }

    assert.equal(operationReads, 3)
    assert.equal(authorityReads, 2)
  })
})

test('stale forced outline load cannot roll back a save accepted while history is pending', async () => {
  const THIRD_HASH = 'c'.repeat(64)
  const draftD2 = outlineDraft({
    draftRevision: 2,
    contentHash: NEXT_HASH,
    content: outlineContent('D2 权威目标'),
  })
  const draftD3 = outlineDraft({
    draftRevision: 3,
    contentHash: THIRD_HASH,
    content: outlineContent('D3 保存目标'),
  })
  const stateD2 = outlineState('project-1', draftD2)
  stateD2.capabilities.generate = false
  stateD2.capabilities.confirm = true
  const stateD3 = outlineState('project-1', draftD3)
  stateD3.capabilities.generate = true
  stateD3.capabilities.confirm = false
  const saveResponse = deferred()
  const staleHistoryStarted = deferred()
  const staleHistory = deferred()
  let authorityReads = 0
  let historyReads = 0

  await withApiMethods([
    [api.chapterOutlines, 'current', async () => {
      authorityReads += 1
      if (authorityReads <= 2) return structuredClone(stateD2)
      return structuredClone(stateD3)
    }],
    [api.chapterOutlines, 'history', async () => {
      historyReads += 1
      if (historyReads === 1) return { items: [{ revision: 2 }] }
      staleHistoryStarted.resolve()
      return staleHistory.promise
    }],
    [api.chapterOutlines, 'saveDraft', async () => saveResponse.promise],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.loadOutline('project-1')
    store.editOutlineLocal(outlineContent('D3 保存目标'))

    const save = store.saveOutlineDraft()
    assert.equal(store.outlineSaving, true)
    const staleLoad = store.ensureOutlineLoaded('project-1', { force: true })
    await staleHistoryStarted.promise
    assert.equal(store.outlineLoading, true)

    saveResponse.resolve(draftD3)
    await save
    assert.equal(store.outlineState.draft.draftRevision, 3)
    assert.equal(store.outlineLoading, true)

    staleHistory.resolve({ items: [{ revision: 999 }] })
    await staleLoad

    assert.equal(store.outlineState.draft.draftRevision, 3)
    assert.equal(store.outlineState.draft.contentHash, THIRD_HASH)
    assert.equal(store.outlineState.draft.content.chapterGoal, 'D3 保存目标')
    assert.equal(store.outlineState.capabilities.generate, true)
    assert.equal(store.outlineState.capabilities.confirm, false)
    assert.equal(store.outlineLocalContent.chapterGoal, 'D3 保存目标')
    assert.equal(store.outlineDirty, false)
    assert.deepEqual(store.outlineHistory, [{ revision: 2 }])
    assert.equal(store.outlineError, null)
    assert.equal(store.outlineLoading, false)
    assert.equal(authorityReads, 3)
    assert.equal(historyReads, 2)
  })
})

test('every outline authority writer advances one shared load fence', async () => {
  const contents = await readFile(
    new URL('../../src/stores/planningStore.js', import.meta.url),
    'utf8',
  )
  const between = (start, end) => contents.slice(
    contents.indexOf(start),
    contents.indexOf(end, contents.indexOf(start)),
  )

  assert.match(contents, /let outlineAuthorityWriteEpoch = 0/)
  assert.match(
    between('async function loadOutline', 'async function ensureOutlineLoaded'),
    /targetAuthorityWriteEpoch[\s\S]*outlineLoadAuthorityIsCurrent/,
  )
  for (const [start, end] of [
    ['async function createOutlineDraft', 'function editOutlineLocal'],
    ['async function saveOutlineDraft', 'async function confirmOutlineDraft'],
    ['async function confirmOutlineDraft', 'function outlineUnknownFailure'],
    ['async function reloadOutlineGenerationAuthority', 'async function acceptOutlineOperation'],
  ]) {
    assert.match(
      between(start, end),
      /commitOutlineAuthorityState\([\s\S]*authorityWrite:\s*true/,
      start,
    )
  }
  assert.match(
    between('async function generateOutlineDraft', 'async function reconcileOutlineGeneration'),
    /acceptOutlineOperation/,
  )
  assert.match(
    between('async function reconcileOutlineGeneration', 'function discardOutlineLocal'),
    /acceptOutlineOperation/,
  )
})

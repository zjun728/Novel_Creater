import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'
import { useBibleStore } from '../../src/stores/bibleStore.js'
import { createBibleWorkspaceController } from '../../src/application/bible/bibleWorkspaceController.js'

test('Bible store exposes no clone draft action after confirmation', async () => {
  const source = await readFile(new URL('../../src/stores/bibleStore.js', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /async function clone|api\.bible\.draft\.clone/)
})

function deferred() { let resolve; let reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
function bible() { const item = id => [{ id, text: `${id} text` }]; return { premiseAndPromise: 'Promise', worldRules: item('world'), powerOrProgressionSystem: 'Growth', protagonist: 'Hero', coreCast: item('cast'), factions: item('faction'), longTermConflicts: item('conflict'), relationshipDynamics: item('relationship'), toneAndNarrativeBoundaries: 'Tone', continuityGuardrails: item('guardrail'), openDesignQuestions: item('question'), privateField: 'must-not-publish' } }
function draft(projectId, version = 1, extra = {}) { return { projectId, lifecycle: 'active', status: 'editable', draftId: 'draft-1', draftVersion: version, baseHeadRevision: 0, contentHash: 'a'.repeat(64), draft: bible(), basis: { selectionRevision: 2 }, canEdit: true, canConfirm: true, canClone: true, reasons: [], createdAt: '2026-01-01', updatedAt: '2026-01-02', privateField: 'must-not-publish', ...extra } }
function head(projectId, revision = 0, extra = {}) { return { projectId, lifecycle: 'active', status: 'current', bibleRevisionId: revision ? 'revision-1' : null, revision, contentHash: revision ? 'b'.repeat(64) : null, bible: revision ? bible() : null, basis: { selectionRevision: 2 }, canEdit: true, canClone: true, reasons: [], confirmedAt: null, privateField: 'must-not-publish', ...extra } }
const response = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
async function withFetch(fetchImpl, run) { const original = global.fetch; global.fetch = fetchImpl; try { return await run() } finally { global.fetch = original } }

test('load rejects late old-project successes and failures', async () => {
  const oldHead = deferred(); const oldDraft = deferred()
  await withFetch(async url => { const path = new URL(String(url)).pathname; if (path.includes('project-a/bible/head')) return oldHead.promise; if (path.includes('project-a/bible/draft')) return oldDraft.promise; return response(path.endsWith('/head') ? head('project-b') : draft('project-b')) }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); const oldLoad = store.load('project-a'); await store.load('project-b'); oldHead.resolve(response(head('project-a'))); oldDraft.reject(new Error('late')); await assert.rejects(oldLoad)
    assert.equal(store.projectId, 'project-b'); assert.equal(store.draft.projectId, 'project-b'); assert.equal(store.error, null)
  })
})

test('edits stay local and dirty until explicit save', async () => {
  const calls = []
  await withFetch(async (url, options = {}) => { calls.push(options.method); const path = new URL(String(url)).pathname; return response(options.method === 'PUT' ? draft('project-1', 2) : path.endsWith('/head') ? head('project-1') : draft('project-1')) }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1'); store.edit({ ...bible(), premiseAndPromise: 'Local' }); assert.equal(store.dirty, true); assert.equal(calls.includes('PUT'), false); await store.save('project-1'); assert.equal(store.dirty, false); assert.equal(store.draft.draftVersion, 2); assert.equal(calls.filter(value => value === 'PUT').length, 1)
  })
})

test('draft CAS conflict remains dirty without retry', async () => {
  let puts = 0
  await withFetch(async (url, options = {}) => { if (options.method === 'PUT') { puts += 1; return response({ code: 'BibleConflict', message: 'stale' }, 409) }; return response(new URL(String(url)).pathname.endsWith('/head') ? head('project-1') : draft('project-1')) }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1'); store.edit(bible()); await assert.rejects(store.save('project-1')); assert.equal(puts, 1); assert.equal(store.dirty, true); assert.equal(store.conflict.code, 'BibleConflict')
  })
})

test('confirm replays the same pending or outcome-unknown command promise and key', async () => {
  const confirmation = deferred(); const bodies = []
  await withFetch(async (url, options = {}) => { const path = new URL(String(url)).pathname; if (path.endsWith('/confirm')) { bodies.push(JSON.parse(options.body)); return confirmation.promise }; return response(path.endsWith('/head') ? head('project-1') : draft('project-1')) }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1'); const first = store.confirm('project-1', { idempotencyKey: 'confirm-1' }); const second = store.confirm('project-1', { idempotencyKey: 'confirm-1' }); assert.equal(bodies.length, 1); confirmation.resolve(response(head('project-1', 1))); const [firstResult, secondResult] = await Promise.all([first, second]); assert.equal(bodies.length, 1); assert.equal(firstResult.revision, 1); assert.equal(secondResult.revision, 1)
  })
})

test('archived and backend capability denial prevent all writes before transport', async () => {
  let writes = 0
  await withFetch(async (url, options = {}) => { if (options.method !== 'GET') writes += 1; const path = new URL(String(url)).pathname; return response(path.endsWith('/head') ? head('project-1', 1, { lifecycle: 'archived', canClone: false }) : draft('project-1', 1, { lifecycle: 'archived', canEdit: false, canConfirm: false, canClone: false, reasons: ['archived'] })) }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1', { readOnly: true }); for (const action of [async () => store.save('project-1'), async () => store.confirm('project-1', { idempotencyKey: 'no' })]) await assert.rejects(action); assert.equal(writes, 0)
  })
})

test('a same-project authority refresh failure fails closed over a formerly writable draft', async () => {
  let refreshFails = false
  let writes = 0
  await withFetch(async (url, options = {}) => {
    const path = new URL(String(url)).pathname
    if (options.method !== 'GET') writes += 1
    if (refreshFails && path.endsWith('/bible/head')) return response({ code: 'BibleUnavailable' }, 503)
    return response(path.endsWith('/head') ? head('project-1') : draft('project-1'))
  }, async () => {
    setActivePinia(createPinia())
    const store = useBibleStore()
    await store.load('project-1')
    assert.equal(store.canEdit, true)
    refreshFails = true
    await assert.rejects(store.load('project-1'))

    assert.equal(store.headHydrated, false)
    assert.equal(store.canEdit, false)
    assert.equal(store.canConfirm, false)
    assert.throws(() => store.edit(bible()))
    assert.throws(() => store.confirm('project-1', { idempotencyKey: 'stale' }))
    for (const action of [
      () => store.save('project-1'),
      () => store.generate('project-1', { idempotencyKey: 'stale' }),
    ]) await assert.rejects(action)
    assert.equal(writes, 0)
  })
})

test('a confirmed Bible head locks every write even when a stale draft claims capabilities', async () => {
  let writes = 0
  await withFetch(async (url, options = {}) => {
    if (options.method !== 'GET') writes += 1
    const path = new URL(String(url)).pathname
    return response(path.endsWith('/head') ? head('project-1', 1) : draft('project-1'))
  }, async () => {
    setActivePinia(createPinia())
    const store = useBibleStore()
    await store.load('project-1')
    assert.equal(store.baselineLocked, true)
    assert.throws(() => store.edit(bible()))
    assert.throws(() => store.confirm('project-1', { idempotencyKey: 'locked' }))
    for (const action of [
      () => store.save('project-1'),
      () => store.generate('project-1', { idempotencyKey: 'locked' }),
    ]) await assert.rejects(action)
    assert.equal(writes, 0)
  })
})

test('history paginates and ignores a late old-project page', async () => {
  const oldHistory = deferred(); const calls = []
  await withFetch(async url => { const parsed = new URL(String(url)); const path = parsed.pathname; calls.push(path + parsed.search); if (path.includes('project-a/bible/history')) return oldHistory.promise; if (path.includes('/history')) return response({ items: [head('project-b', 3)], nextBeforeRevision: 2 }); return response(path.endsWith('/head') ? head(path.includes('project-a') ? 'project-a' : 'project-b') : draft(path.includes('project-a') ? 'project-a' : 'project-b')) }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); const oldLoad = store.loadHistory('project-a', { limit: 20 }); await store.load('project-b'); await store.loadHistory('project-b', { limit: 20 }); oldHistory.resolve(response({ items: [head('project-a', 2)], nextBeforeRevision: null })); await oldLoad; assert.deepEqual(store.history.map(item => item.revision), [3]); assert.equal(store.historyNextBeforeRevision, 2); assert.equal(calls.some(call => call.includes('project-b/bible/history?limit=20')), true)
  })
})

test('a real missing draft remains null until the controller creates it, then first save uses draft version zero', async () => {
  const bodies = []
  await withFetch(async (url, options = {}) => {
    const path = new URL(String(url)).pathname
    if (options.method === 'PUT') { bodies.push(JSON.parse(options.body)); return response(draft('project-1', 1, { draft: bible() })) }
    return response(path.endsWith('/head') ? head('project-1') : draft('project-1', null, { draftId: null, draftVersion: null, status: 'missing', draft: null }))
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1')
    assert.equal(store.draft.draft, null)
    assert.equal(store.draft.canEdit, true)
    await store.save('project-1', { ...bible(), premiseAndPromise: 'first' })
    assert.equal(bodies.length, 1)
    assert.equal(bodies[0].expectedDraftVersion, 0)
  })
})

test('the real controller makes a missing draft editable and saves its first local artifact through PUT version zero', async () => {
  const bodies = []
  await withFetch(async (url, options = {}) => {
    const path = new URL(String(url)).pathname
    if (options.method === 'PUT') { bodies.push(JSON.parse(options.body)); return response(draft('project-1', 1)) }
    return response(path.endsWith('/head') ? head('project-1') : draft('project-1', null, { draftId: null, draftVersion: null, status: 'missing', draft: null }))
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); const workspace = createBibleWorkspaceController({ store, projectId: () => 'project-1' })
    await workspace.hydrate(); assert.equal(workspace.editable.value, true)
    workspace.edit({ ...workspace.working.value, premiseAndPromise: 'first local' }); await workspace.save()
    assert.equal(bodies.length, 1); assert.equal(bodies[0].expectedDraftVersion, 0)
  })
})

test('confirm identity includes draft and head revisions and releases terminal failure', async () => {
  const calls = []
  await withFetch(async (url, options = {}) => {
    const path = new URL(String(url)).pathname
    if (path.endsWith('/confirm')) { calls.push(JSON.parse(options.body)); return response({ code: 'BibleRequestInvalid', message: 'bad' }, 422) }
    return response(path.endsWith('/head') ? head('project-1', 0) : draft('project-1', 1))
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1')
    await assert.rejects(store.confirm('project-1', { idempotencyKey: 'same' }))
    await assert.rejects(store.confirm('project-1', { idempotencyKey: 'same' }))
    assert.equal(calls.length, 2)
  })
})

test('confirmation deduplicates only pending work, retries 503 with the same key, and releases every rejection', async () => {
  const bodies = []; let attempt = 0
  await withFetch(async (url, options = {}) => {
    const path = new URL(String(url)).pathname
    if (path.endsWith('/confirm')) { bodies.push(JSON.parse(options.body)); attempt += 1; return attempt === 1 ? response({ code: 'temporary' }, 503) : response(head('project-1', 1)) }
    return response(path.endsWith('/head') ? head('project-1') : draft('project-1', 1))
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1')
    await assert.rejects(store.confirm('project-1', { idempotencyKey: 'retry-key' }))
    await store.confirm('project-1', { idempotencyKey: 'retry-key' })
    assert.equal(bodies.length, 2)
    assert.equal(bodies[0].idempotencyKey, bodies[1].idempotencyKey)
  })
})

test('history detail participates in busy state and publishes its error only for the current request', async () => {
  const detail = deferred()
  await withFetch(async url => {
    const path = new URL(String(url)).pathname
    if (path.endsWith('/history/1')) return detail.promise
    return response(path.endsWith('/head') ? head('project-1', 1) : draft('project-1'))
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1')
    const pending = store.loadHistoryDetail('project-1', 1); assert.equal(store.historyLoading, true)
    detail.resolve(response({ code: 'missing' }, 404)); await assert.rejects(pending)
    assert.equal(store.historyLoading, false); assert.equal(store.error.status, 404)
  })
})

function generationAttempt(projectId, status = 'succeeded', extra = {}) {
  const pending = ['reserved', 'running'].includes(status)
  return {
    id: `attempt-${projectId}`,
    projectId,
    status,
    attemptVersion: pending ? 1 : 2,
    providerId: 'provider-1',
    modelNameSnapshot: 'novel-model',
    inputManifestHash: '9'.repeat(64),
    resultHash: status === 'succeeded' ? '8'.repeat(64) : null,
    publicErrorCode: status === 'failed'
      ? 'BibleGenerationProviderFailed'
      : status === 'outcome_unknown'
        ? 'BibleGenerationRetryable'
        : null,
    createdAt: 1900000000000,
    completedAt: pending ? null : 1900000000100,
    apiKey: 'must-not-publish',
    rawProviderBody: 'must-not-publish',
    ...extra,
  }
}

test('generate sends one closed command then installs only authoritative head and draft reads', async () => {
  const bodies = []; let headReads = 0; let draftReads = 0
  await withFetch(async (url, options = {}) => {
    const path = new URL(String(url)).pathname
    if (path.endsWith('/bible/generate')) {
      bodies.push(JSON.parse(options.body))
      return response({ attempt: generationAttempt('project-1') })
    }
    if (path.endsWith('/bible/head')) {
      headReads += 1
      return response(head('project-1'))
    }
    if (path.endsWith('/bible/draft')) {
      draftReads += 1
      return response(draft('project-1', draftReads === 1 ? 1 : 2, {
        draft: { ...bible(), premiseAndPromise: draftReads === 1 ? 'BEFORE' : 'AUTHORITATIVE GENERATED' },
      }))
    }
    throw new Error(`unexpected ${path}`)
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore()
    await store.load('project-1')
    const result = await store.generate('project-1', {
      authorInstructions: '强调群像',
      idempotencyKey: 'generation-key-1',
      providerId: 'must-not-send',
    })
    assert.equal(result.status, 'succeeded')
    assert.equal(store.generating, false)
    assert.equal(store.generationAttempt.id, 'attempt-project-1')
    assert.equal(store.generationAttempt.apiKey, undefined)
    assert.equal(store.draft.draftVersion, 2)
    assert.equal(store.draft.draft.premiseAndPromise, 'AUTHORITATIVE GENERATED')
    assert.deepEqual(bodies, [{
      authorInstructions: '强调群像',
      expectedDraftVersion: 1,
      expectedHeadRevision: 0,
      idempotencyKey: 'generation-key-1',
    }])
    assert.equal(headReads, 2)
    assert.equal(draftReads, 2)
  })
})

test('failed or outcome-unknown generation keeps local draft and never performs authority reads', async () => {
  for (const status of ['failed', 'outcome_unknown']) {
    let headReads = 0; let draftReads = 0
    await withFetch(async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      if (path.endsWith('/bible/generate')) {
        return response({ attempt: generationAttempt('project-1', status) })
      }
      if (path.endsWith('/bible/head')) { headReads += 1; return response(head('project-1')) }
      if (path.endsWith('/bible/draft')) { draftReads += 1; return response(draft('project-1', 1, { draft: { ...bible(), premiseAndPromise: 'LOCAL BASIS' } })) }
      throw new Error(`unexpected ${path}`)
    }, async () => {
      setActivePinia(createPinia()); const store = useBibleStore()
      await store.load('project-1')
      const before = JSON.stringify(store.draft)
      const result = await store.generate('project-1', {
        authorInstructions: '',
        idempotencyKey: `generation-${status}`,
      })
      assert.equal(result.status, status)
      assert.equal(JSON.stringify(store.draft), before)
      assert.equal(store.dirty, false)
      assert.equal(headReads, 1)
      assert.equal(draftReads, 1)
    })
  }
})

test('dirty state denies generation before transport and late old-project success is fenced', async () => {
  const oldGeneration = deferred(); let generates = 0; let headReads = 0; let draftReads = 0
  await withFetch(async (url, options = {}) => {
    const path = new URL(String(url)).pathname
    const isA = path.includes('/project-a/')
    if (path.endsWith('/bible/generate')) {
      generates += 1
      return oldGeneration.promise
    }
    if (path.endsWith('/bible/head')) { headReads += 1; return response(head(isA ? 'project-a' : 'project-b')) }
    if (path.endsWith('/bible/draft')) { draftReads += 1; return response(draft(isA ? 'project-a' : 'project-b')) }
    throw new Error(`unexpected ${path}`)
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore()
    await store.load('project-a')
    store.edit({ ...bible(), premiseAndPromise: 'DIRTY' })
    await assert.rejects(
      store.generate('project-a', { authorInstructions: '', idempotencyKey: 'blocked' }),
      error => error.code === 'bible_generation_dirty',
    )
    assert.equal(generates, 0)
    await store.load('project-a')
    const pending = store.generate('project-a', {
      authorInstructions: '',
      idempotencyKey: 'late-a',
    })
    await store.load('project-b')
    oldGeneration.resolve(response({ attempt: generationAttempt('project-a') }))
    await pending
    assert.equal(store.projectId, 'project-b')
    assert.equal(store.draft.projectId, 'project-b')
    assert.equal(store.generationAttempt, null)
    assert.equal(store.generating, false)
    assert.equal(headReads, 3)
    assert.equal(draftReads, 3)
  })
})

test('loadAttempt uses encoded safe attempt endpoint and fences old projects', async () => {
  const calls = []
  await withFetch(async url => {
    const path = new URL(String(url)).pathname; calls.push(path)
    return response(generationAttempt('project/one', 'outcome_unknown'))
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore()
    const result = await store.loadAttempt('project/one', 'attempt/one')
    assert.equal(result.status, 'outcome_unknown')
    assert.equal(store.generationAttempt.publicErrorCode, 'BibleGenerationRetryable')
    assert.equal(store.generationAttempt.rawProviderBody, undefined)
    assert.equal(calls[0], '/api/projects/project%2Fone/bible/generation-attempts/attempt%2Fone')
  })
})

test('propose posts the exact stable body, sanitizes proposal data, and performs no authority reload', async () => {
  const bodies = []; let headReads = 0; let draftReads = 0
  const proposal = { ...bible(), premiseAndPromise: 'PROPOSED', privateField: 'must-not-publish' }
  await withFetch(async (url, options = {}) => {
    const path = new URL(String(url)).pathname
    if (path.endsWith('/bible/proposals')) {
      bodies.push(JSON.parse(options.body))
      return response({ attempt: generationAttempt('project-1', 'succeeded', { proposal }) })
    }
    if (path.endsWith('/bible/head')) { headReads += 1; return response(head('project-1')) }
    if (path.endsWith('/bible/draft')) { draftReads += 1; return response(draft('project-1')) }
    throw new Error(`unexpected ${path}`)
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1')
    const draftBefore = JSON.stringify(store.draft); const headBefore = JSON.stringify(store.head)
    const result = await store.propose('project-1', {
      scope: 'world_rules', authorInstructions: '补足代价链', idempotencyKey: 'proposal-key-1',
      providerId: 'must-not-send', expectedDraftVersion: 999,
    })
    assert.deepEqual(bodies, [{
      scope: 'world_rules', authorInstructions: '补足代价链', expectedDraftVersion: 1,
      expectedHeadRevision: 0, idempotencyKey: 'proposal-key-1',
    }])
    assert.equal(result.proposal.premiseAndPromise, 'PROPOSED')
    assert.equal(result.proposal.privateField, undefined)
    assert.equal(result.apiKey, undefined)
    assert.equal(store.proposalAttempt, result)
    assert.equal(store.proposing, false)
    assert.equal(JSON.stringify(store.draft), draftBefore)
    assert.equal(JSON.stringify(store.head), headBefore)
    assert.equal(store.dirty, false)
    assert.equal(headReads, 1); assert.equal(draftReads, 1)
    store.clearProposal(); assert.equal(store.proposalAttempt, null)
  })
})

test('proposal state is independent from direct generation and project switches fence late proposals', async () => {
  const oldProposal = deferred()
  await withFetch(async (url, options = {}) => {
    const path = new URL(String(url)).pathname; const isA = path.includes('/project-a/')
    if (path.endsWith('/bible/proposals')) return oldProposal.promise
    if (path.endsWith('/bible/head')) return response(head(isA ? 'project-a' : 'project-b'))
    if (path.endsWith('/bible/draft')) return response(draft(isA ? 'project-a' : 'project-b'))
    throw new Error(`unexpected ${path}`)
  }, async () => {
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-a')
    const pending = store.propose('project-a', { scope: 'whole', authorInstructions: '', idempotencyKey: 'late-proposal' })
    assert.equal(store.proposing, true); assert.equal(store.generating, false)
    await store.load('project-b')
    oldProposal.resolve(response({ attempt: generationAttempt('project-a', 'succeeded', { proposal: bible() }) }))
    await pending
    assert.equal(store.projectId, 'project-b'); assert.equal(store.proposalAttempt, null)
    assert.equal(store.proposing, false); assert.equal(store.generationAttempt, null)
  })
})

test('proposal parser accepts every legal backend status without weakening proposal-state rules', async () => {
  for (const status of ['reserved', 'running', 'failed', 'outcome_unknown', 'succeeded']) {
    await withFetch(async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      if (path.endsWith('/bible/proposals')) {
        const extra = status === 'succeeded' ? { proposal: bible() } : {}
        return response({ attempt: generationAttempt('project-1', status, extra) })
      }
      return response(path.endsWith('/head') ? head('project-1') : draft('project-1'))
    }, async () => {
      setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1')
      const result = await store.propose('project-1', {
        scope: 'whole', authorInstructions: '', idempotencyKey: `proposal-${status}`,
      })
      assert.equal(result.status, status)
      assert.equal(Object.hasOwn(result, 'proposal'), status === 'succeeded')
    })
  }
})

test('proposal parser rejects cross-project identity, malformed payloads, illegal status, and invalid proposal combinations', async () => {
  const invalidAttempts = [
    generationAttempt('another-project', 'succeeded', { proposal: bible() }),
    generationAttempt('project-1', 'invented', {}),
    generationAttempt('project-1', 'succeeded', {}),
    generationAttempt('project-1', 'failed', { proposal: bible() }),
    generationAttempt('project-1', 'succeeded', { proposal: { ...bible(), protagonist: 7 } }),
    generationAttempt('project-1', 'succeeded', { proposal: { ...bible(), worldRules: [] } }),
    generationAttempt('project-1', 'succeeded', { proposal: { ...bible(), coreCast: [{ id: 'bad id', text: 'cast' }] } }),
    { ...generationAttempt('project-1', 'succeeded', { proposal: bible() }), attemptVersion: '2' },
  ]
  for (const [index, attempt] of invalidAttempts.entries()) {
    await withFetch(async (url, options = {}) => {
      const path = new URL(String(url)).pathname
      if (path.endsWith('/bible/proposals')) return response({ attempt })
      return response(path.endsWith('/head') ? head('project-1') : draft('project-1'))
    }, async () => {
      setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1')
      const before = JSON.stringify(store.draft)
      await assert.rejects(
        store.propose('project-1', { scope: 'whole', authorInstructions: '', idempotencyKey: `invalid-${index}` }),
        failure => failure.code === 'invalid_response',
      )
      assert.equal(store.error.code, 'invalid_response')
      assert.equal(store.proposalAttempt, null)
      assert.equal(JSON.stringify(store.draft), before)
      assert.equal(store.dirty, false)
    })
  }
})

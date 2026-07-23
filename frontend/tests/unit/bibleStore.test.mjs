import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'
import { useBibleStore } from '../../src/stores/bibleStore.js'
import { createBibleWorkspaceController } from '../../src/application/bible/bibleWorkspaceController.js'

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
    setActivePinia(createPinia()); const store = useBibleStore(); await store.load('project-1', { readOnly: true }); for (const action of [async () => store.save('project-1'), async () => store.confirm('project-1', { idempotencyKey: 'no' }), async () => store.clone('project-1', { sourceRevision: 1 })]) await assert.rejects(action); assert.equal(writes, 0)
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

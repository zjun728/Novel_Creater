import assert from 'node:assert/strict'
import test from 'node:test'
import { ApiError } from '../../src/api/db/api-error.js'
import { createManuscriptController } from '../../src/application/manuscript/manuscriptController.js'

const chapter = (number = 2) => ({ projectId: 'p', projectTitle: 'T', lifecycle: 'active', volume: { id: 'v', order: 1, title: 'V' }, chapter: { number, title: 'C', content: 'text', scalarCount: 4, finalizedAt: '2025-01-01T00:00:00Z' }, outline: { chapterGoal: '', expectedCharacters: [], continuation: [], plannedTasks: [], scenes: [], forbiddenEarlyEvents: [] }, navigation: { previousChapterNumber: null, nextChapterNumber: null } })
const preparation = { lifecycle: 'active', nextAction: 'continue_contract', targetPath: '/contract' }
function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

test('controller publishes validated content and independent preparation', async () => {
  const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => chapter(), index: async () => ({ volumes: [] }) }, projects: { preparation: async () => preparation } } })
  await Promise.all([controller.loadContent('p', 2), controller.loadPreparation('p')])
  assert.equal(controller.content.value.status, 'ready'); assert.equal(controller.content.value.data.chapter.number, 2)
  assert.equal(controller.preparation.value.status, 'ready'); assert.equal(controller.preparation.value.nextAction.label, '继续创作契约')
})

test('same address does not reload while a new address ignores stale completion', async () => {
  const first = deferred(); let calls = 0
  const controller = createManuscriptController({ api: { manuscripts: { chapter: (_p, number) => { calls += 1; return number === 2 ? first.promise : Promise.resolve(chapter(number)) }, index: async () => ({ volumes: [] }) }, projects: { preparation: async () => preparation } } })
  const old = controller.loadContent('p', 2); await controller.loadContent('p', 2); const current = controller.loadContent('p', 3); first.resolve(chapter(2)); await Promise.all([old, current])
  assert.equal(calls, 2); assert.equal(controller.content.value.data.chapter.number, 3)
})

test('maps public error codes without leaking error messages and retains data during retry', async () => {
  let fail = false
  const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => { if (fail) throw new ApiError({ status: 503, code: 'ManuscriptTemporarilyUnavailable', message: 'secret hash' }); return chapter() }, index: async () => ({ volumes: [] }) }, projects: { preparation: async () => preparation } } })
  await controller.loadContent('p', 2); fail = true; await controller.loadContent('p', 2, { force: true })
  assert.equal(controller.content.value.status, 'unavailable'); assert.equal(controller.content.value.data.chapter.number, 2); assert.doesNotMatch(JSON.stringify(controller.content.value), /secret|hash/)
})

test('identity mismatch is integrity failure and invalid addresses do not request', async () => {
  let calls = 0; const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => { calls += 1; return chapter(3) }, index: async () => ({ volumes: [] }) }, projects: { preparation: async () => preparation } } })
  await controller.loadContent('', 2); assert.equal(controller.content.value.status, 'invalid-address'); assert.equal(calls, 0)
  await controller.loadContent('p', 2); assert.equal(controller.content.value.status, 'integrity-failure')
})

test('a normalized address owns its complete response and cross-target retries clear it', async () => {
  let unavailable = false
  const controller = createManuscriptController({ api: { manuscripts: { chapter: async (_p, number) => {
    if (unavailable) throw new ApiError({ code: 'ManuscriptTemporarilyUnavailable', correlationId: 'ok_1' })
    return chapter(number)
  }, index: async () => ({ projectId: 'p', volumes: [], summary: { finalChapterCount: 0, totalScalarCount: 0 } }) }, projects: { preparation: async () => preparation } } })
  await controller.loadContent(' p ', 2)
  assert.equal(controller.content.value.data.projectId, 'p')
  assert.equal(controller.content.value.data.chapter.number, 2)
  unavailable = true
  await controller.loadContent('p', 3)
  assert.equal(controller.content.value.status, 'unavailable')
  assert.equal(controller.content.value.data, null)
})

test('unknown failures do not retain correlation IDs', async () => {
  const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => { throw new ApiError({ code: 'unexpected', correlationId: 'safe_id' }) }, index: async () => ({}) }, projects: { preparation: async () => preparation } } })
  await controller.loadContent('p', 2)
  assert.equal(controller.content.value.correlationId, '')
})

test('invalid preparation invalidates a late valid preparation response', async () => {
  const pending = deferred()
  const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => chapter(), index: async () => ({}) }, projects: { preparation: () => pending.promise } } })
  const earlier = controller.loadPreparation('p')
  await controller.loadPreparation('bad\u200B')
  pending.resolve(preparation); await earlier
  assert.equal(controller.preparation.value.status, 'unavailable')
})

test('controller maps each public error without cross-target retention', async () => {
  for (const [code, status] of Object.entries({ ManuscriptProjectNotFound: 'missing-project', FinalChapterNotFound: 'missing-chapter', ManuscriptRequestInvalid: 'invalid-address', ManuscriptIntegrityFailure: 'integrity-failure', ManuscriptTemporarilyUnavailable: 'unavailable', unknown: 'unavailable' })) {
    const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => { throw new ApiError({ code }) }, index: async () => ({}) }, projects: { preparation: async () => preparation } } })
    await controller.loadContent('p', 2); assert.equal(controller.content.value.status, status); assert.equal(controller.content.value.data, null)
  }
})

test('directory table covers ready empty identity errors and same-target retry retention', async () => {
  const success = { projectId: 'p', title: 'T', lifecycle: 'active', summary: { finalChapterCount: 0, totalScalarCount: 0 }, volumes: [] }
  let error = null
  const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => chapter(), index: async () => { if (error) throw error; return success } }, projects: { preparation: async () => preparation } } })
  await controller.loadDirectory('p'); assert.equal(controller.content.value.status, 'empty'); assert.equal(controller.content.value.data, success)
  error = new ApiError({ code: 'ManuscriptTemporarilyUnavailable' }); const retry = controller.loadDirectory('p', { force: true }); assert.equal(controller.content.value.status, 'loading'); assert.equal(controller.content.value.data, success); await retry; assert.equal(controller.content.value.data, success)
  for (const code of ['ManuscriptProjectNotFound', 'FinalChapterNotFound', 'ManuscriptRequestInvalid', 'ManuscriptIntegrityFailure', 'unknown']) { error = new ApiError({ code }); await controller.loadDirectory('p', { force: true }); assert.equal(controller.content.value.data, null) }
})

test('target switching invalidation and dispose abort signals and reject late publication', async () => {
  const pending = deferred(); const signals = []
  const controller = createManuscriptController({ api: { manuscripts: { chapter: (_p, n, { signal }) => { signals.push(signal); return n === 2 ? pending.promise : Promise.resolve(chapter(n)) }, index: async () => ({}) }, projects: { preparation: async () => preparation } } })
  const old = controller.loadContent('p', 2); await controller.loadContent('p', 3); assert.equal(signals[0].aborted, true); pending.resolve(chapter(2)); await old; assert.equal(controller.content.value.data.chapter.number, 3)
  const waiting = deferred(); const disposed = createManuscriptController({ api: { manuscripts: { chapter: (_p, _n, { signal }) => { signals.push(signal); return waiting.promise }, index: async () => ({}) }, projects: { preparation: async () => preparation } } }); const request = disposed.loadContent('p', 2); disposed.dispose(); assert.equal(signals.at(-1).aborted, true); waiting.resolve(chapter()); await request; assert.equal(disposed.content.value.status, 'loading')
})

test('preparation table is independent from content and honors archived, stale and dispose', async () => {
  const first = deferred(); let count = 0
  const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => { throw new ApiError({ code: 'unknown' }) }, index: async () => ({}) }, projects: { preparation: () => (++count === 1 ? first.promise : Promise.resolve({ ...preparation, lifecycle: 'archived', nextAction: 'archived_read_only', targetPath: null })) } } })
  const old = controller.loadPreparation('p'); await controller.loadPreparation('q'); first.resolve(preparation); await old; assert.equal(controller.preparation.value.status, 'archived'); await controller.loadContent('p', 2); assert.equal(controller.content.value.status, 'unavailable')
})

test('new target clears a ready response immediately while its deferred request is pending', async () => {
  const pending = deferred()
  const controller = createManuscriptController({ api: { manuscripts: { chapter: (_p, number) => number === 2 ? Promise.resolve(chapter(2)) : pending.promise, index: async () => ({}) }, projects: { preparation: async () => preparation } } })
  await controller.loadContent('p', 2)
  const next = controller.loadContent('p', 3)
  assert.equal(controller.content.value.status, 'loading'); assert.equal(controller.content.value.data, null)
  pending.resolve(chapter(3)); await next; assert.equal(controller.content.value.data.chapter.number, 3)
})

test('correlation IDs are retained only for the two approved codes and safe values', async () => {
  for (const [code, id, expected] of [
    ['ManuscriptIntegrityFailure', 'safe_1', 'safe_1'], ['ManuscriptTemporarilyUnavailable', 'safe_2', 'safe_2'],
    ['ManuscriptIntegrityFailure', 'bad id', ''], ['ManuscriptTemporarilyUnavailable', 'bad\n', ''],
    ['ManuscriptProjectNotFound', 'safe_3', ''], ['ManuscriptRequestInvalid', 'safe_4', ''], ['unknown', 'safe_5', ''],
  ]) {
    const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => { throw new ApiError({ code, correlationId: id }) }, index: async () => ({}) }, projects: { preparation: async () => preparation } } })
    await controller.loadContent('p', 2); assert.equal(controller.content.value.correlationId, expected, code)
  }
})

test('disposed preparation ignores both late resolve and reject', async () => {
  for (const outcome of ['resolve', 'reject']) {
    const pending = deferred()
    const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => chapter(), index: async () => ({}) }, projects: { preparation: () => pending.promise } } })
    const request = controller.loadPreparation('p'); assert.equal(controller.preparation.value.status, 'loading'); controller.dispose()
    if (outcome === 'resolve') pending.resolve(preparation); else pending.reject(new Error('late'))
    await request; assert.equal(controller.preparation.value.status, 'loading', outcome)
  }
})

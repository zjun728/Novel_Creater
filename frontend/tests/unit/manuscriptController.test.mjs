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
  assert.equal(controller.content.value.status, 'ready'); assert.equal(controller.content.value.chapter.number, 2)
  assert.equal(controller.preparation.value.status, 'ready'); assert.equal(controller.preparation.value.nextAction.label, '继续创作契约')
})

test('same address does not reload while a new address ignores stale completion', async () => {
  const first = deferred(); let calls = 0
  const controller = createManuscriptController({ api: { manuscripts: { chapter: (_p, number) => { calls += 1; return number === 2 ? first.promise : Promise.resolve(chapter(number)) }, index: async () => ({ volumes: [] }) }, projects: { preparation: async () => preparation } } })
  const old = controller.loadContent('p', 2); await controller.loadContent('p', 2); const current = controller.loadContent('p', 3); first.resolve(chapter(2)); await Promise.all([old, current])
  assert.equal(calls, 2); assert.equal(controller.content.value.chapter.number, 3)
})

test('maps public error codes without leaking error messages and retains data during retry', async () => {
  let fail = false
  const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => { if (fail) throw new ApiError({ status: 503, code: 'ManuscriptTemporarilyUnavailable', message: 'secret hash' }); return chapter() }, index: async () => ({ volumes: [] }) }, projects: { preparation: async () => preparation } } })
  await controller.loadContent('p', 2); fail = true; await controller.loadContent('p', 2, { force: true })
  assert.equal(controller.content.value.status, 'unavailable'); assert.equal(controller.content.value.chapter.number, 2); assert.doesNotMatch(JSON.stringify(controller.content.value), /secret|hash/)
})

test('identity mismatch is integrity failure and invalid addresses do not request', async () => {
  let calls = 0; const controller = createManuscriptController({ api: { manuscripts: { chapter: async () => { calls += 1; return chapter(3) }, index: async () => ({ volumes: [] }) }, projects: { preparation: async () => preparation } } })
  await controller.loadContent('', 2); assert.equal(controller.content.value.status, 'invalid-address'); assert.equal(calls, 0)
  await controller.loadContent('p', 2); assert.equal(controller.content.value.status, 'integrity-failure')
})


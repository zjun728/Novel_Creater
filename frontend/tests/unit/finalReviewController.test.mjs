import assert from 'node:assert/strict'
import test from 'node:test'
import { createFinalReviewController } from '../../src/application/manuscript/finalReviewController.js'

const review = (projectId = 'p', chapterNumber = 2) => ({
  projectId, chapterNumber, finalizationId: 'final-2', canonRevision: 2, summary: '抵达码头。',
  qualityReport: { status: 'completed', deterministicBlocks: [], findings: [], contentHash: 'a'.repeat(64) },
  canonEvents: [], storyProgressEvents: [], planningPatches: [],
})
const deferred = () => { let resolve; let reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }

test('review loads only when requested and passes an abort signal to the read API', async () => {
  const calls = []
  const controller = createFinalReviewController({ api: { workbench: { review: async (...args) => { calls.push(args); return review() } } } })
  assert.equal(calls.length, 0)
  assert.equal(controller.state.value.status, 'idle')
  assert.equal(await controller.load('p', 2), true)
  assert.equal(controller.state.value.status, 'ready')
  assert.deepEqual(calls[0].slice(0, 2), ['p', 2])
  assert.ok(calls[0][2].signal instanceof AbortSignal)
})

test('a later project or chapter read aborts and fences the previous result', async () => {
  const first = deferred(); let firstSignal
  const controller = createFinalReviewController({ api: { workbench: { review: (id, number, options) => {
    if (id === 'old') { firstSignal = options.signal; return first.promise }
    return Promise.resolve(review(id, number))
  } } } })
  const pending = controller.load('old', 2)
  await controller.load('new', 3)
  assert.equal(firstSignal.aborted, true)
  first.resolve(review('old', 2)); await pending
  assert.equal(controller.state.value.data.projectId, 'new')
  assert.equal(controller.state.value.data.chapterNumber, 3)
})

test('closing the review clears data and a late completion cannot reopen it', async () => {
  const response = deferred(); let signal
  const controller = createFinalReviewController({ api: { workbench: { review: (_id, _number, options) => { signal = options.signal; return response.promise } } } })
  const pending = controller.load('p', 2)
  controller.reset()
  assert.equal(signal.aborted, true)
  response.resolve(review()); await pending
  assert.deepEqual(controller.state.value, { status: 'idle', data: null, message: '' })
  controller.dispose()
  assert.equal(await controller.load('p', 2), false)
})

test('wrong project, chapter, malformed report and unverified evidence are rejected', async () => {
  const samples = [
    review('other'), review('p', 3), { ...review(), qualityReport: null },
    { ...review(), qualityReport: { ...review().qualityReport, status: 'unknown' } },
    { ...review(), storyProgressEvents: [{ id: 'progress', targetType: 'stage', targetId: 's', status: 'completed', evidence: { excerpt: '伪造片段', verified: false } }] },
  ]
  for (const value of samples) {
    const controller = createFinalReviewController({ api: { workbench: { review: async () => value } } })
    assert.equal(await controller.load('p', 2), false)
    assert.equal(controller.state.value.status, 'error')
    assert.equal(controller.state.value.data, null)
  }
})

test('read failure exposes fixed public copy and retries independently', async () => {
  let fail = true
  const controller = createFinalReviewController({ api: { workbench: { review: async () => {
    if (fail) throw { code: 'internal_error', message: 'PRIVATE_PROVIDER_RESPONSE' }
    return review()
  } } } })
  await controller.load('p', 2)
  assert.doesNotMatch(controller.state.value.message, /PRIVATE_PROVIDER_RESPONSE/)
  assert.match(controller.state.value.message, /审查记录/)
  fail = false
  assert.equal(await controller.load('p', 2), true)
  assert.equal(controller.state.value.data.chapterNumber, 2)
})

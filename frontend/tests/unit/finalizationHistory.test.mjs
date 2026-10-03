import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, shallowRef } from 'vue'

const hash = 'a'.repeat(64)
const reviewValue = () => ({ attemptId: 'attempt', candidateId: 'candidate', candidateHash: hash,
  changeSet: { revision: 1, contentHash: hash, payload: { canonEvents: [{ entityId: 'hero', fieldPath: 'observation.Record' }] } } })
const candidate = () => ({ id: 'candidate', contentHash: hash, canonRevision: 14 })

async function setup(read, { project = 'p', session = 's' } = {}) {
  const { createFinalizationHistory } = await import('../../src/application/writer/finalizationHistory.js')
  const review = shallowRef(reviewValue())
  const candidates = shallowRef([candidate()])
  const owner = shallowRef({ project, session })
  const calls = []
  const history = createFinalizationHistory({
    getProjectId: () => owner.value.project, getSessionId: () => owner.value.session,
    getReview: () => review.value, getCandidates: () => candidates.value,
    readHistory: async (p, s, command) => { calls.push([p, s, command]); return read(p, s, command) },
  })
  return { history, review, candidates, owner, calls }
}
const response = (project, session, command, value = '历史值') => ({ projectId: project,
  chapterSessionId: session, ...command, items: [{ entityId: 'hero', fieldPath: 'observation.Record',
    state: 'present', value, source: { eventId: 'event', revision: 13, eventOrder: 2 } }] })
const settle = async () => { await nextTick(); await new Promise(resolve => setTimeout(resolve, 0)) }

test('history loads separately, shares the frozen key and never mutates review', async () => {
  const mounted = await setup(async (...args) => response(...args))
  try {
    const original = structuredClone(mounted.review.value)
    await settle()
    assert.equal(mounted.history.lookup('hero', 'observation.Record').value, '历史值')
    assert.equal(mounted.history.lookup('other', 'observation.Record').state, 'not_loaded')
    assert.equal(mounted.history.lookup('hero', 'observation.record').state, 'not_loaded')
    assert.equal(mounted.calls[0][2].canonRevision, 14)
    await mounted.history.refresh()
    assert.deepEqual(mounted.review.value, original)
    assert.equal(mounted.calls.length, 2)
  } finally { mounted.history.dispose() }
})

test('history failures are local, with no automatic retries or latest-value fallback', async () => {
  const mounted = await setup(async () => { throw new Error('unavailable') })
  try {
    await settle()
    assert.equal(mounted.history.lookup('hero', 'observation.Record').state, 'unavailable')
    assert.equal(mounted.calls.length, 1)
    assert.equal(mounted.review.value.changeSet.revision, 1)
    await mounted.history.refresh()
    assert.equal(mounted.calls.length, 2)
  } finally { mounted.history.dispose() }
})

test('history response identity mismatch is unavailable', async () => {
  const mounted = await setup(async (...args) => ({ ...response(...args), canonRevision: 15 }))
  try {
    await settle()
    assert.equal(mounted.history.lookup('hero', 'observation.Record').state, 'unavailable')
  } finally { mounted.history.dispose() }
})

for (const change of ['project', 'session', 'attempt', 'candidate', 'frozenRevision', 'savedRevision']) {
  test(`late history response is discarded after ${change} changes`, async () => {
    const pending = []
    const mounted = await setup((...args) => new Promise(resolve => pending.push(() => resolve(response(...args, pending.length ? '新身份值' : '旧身份值')))))
    try {
      await settle()
      if (change === 'project' || change === 'session') mounted.owner.value = { ...mounted.owner.value, [change]: 'changed' }
      if (change === 'attempt') mounted.review.value = { ...mounted.review.value, attemptId: 'changed' }
      if (change === 'candidate') {
        mounted.review.value = { ...mounted.review.value, candidateId: 'changed' }
        mounted.candidates.value = [{ ...candidate(), id: 'changed' }]
      }
      if (change === 'frozenRevision') mounted.candidates.value = [{ ...candidate(), canonRevision: 15 }]
      if (change === 'savedRevision') mounted.review.value = { ...mounted.review.value,
        changeSet: { ...mounted.review.value.changeSet, revision: 2, contentHash: 'b'.repeat(64) } }
      await settle()
      assert.equal(pending.length, 2)
      pending[0]()
      await settle()
      assert.notEqual(mounted.history.lookup('hero', 'observation.Record').state, 'present')
      pending[1]()
      await settle()
      assert.equal(mounted.history.lookup('hero', 'observation.Record').state, 'present')
      assert.equal(mounted.history.reference.value.attemptId, mounted.review.value.attemptId)
    } finally { mounted.history.dispose(); pending.forEach(release => release()) }
  })
}

test('no saved/frozen identity means unavailable, not a query for arbitrary history', async () => {
  const mounted = await setup(async (...args) => response(...args), { project: '' })
  try {
    await settle()
    assert.equal(mounted.calls.length, 0)
    assert.equal(mounted.history.lookup('hero', 'observation.Record').state, 'unavailable')
  } finally { mounted.history.dispose() }
})

test('disposed history ignores completion', async () => {
  let release
  const mounted = await setup((...args) => new Promise(resolve => { release = () => resolve(response(...args)) }))
  await settle()
  mounted.history.dispose()
  release()
  await settle()
  assert.equal(mounted.history.reference.value, null)
})

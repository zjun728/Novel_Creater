import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { createTopicCenterStore } from '../../src/stores/topicCenterStore.js'

function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
}

test('late list and detail responses cannot replace newer topic state', async () => {
  setActivePinia(createPinia())
  const oldList = deferred()
  const oldDetail = deferred()
  let listCount = 0
  const store = createTopicCenterStore({
    listCandidates: () => (++listCount === 1 ? oldList.promise : Promise.resolve([{ id: 'new' }])),
    getCandidate: id => (id === 'old' ? oldDetail.promise : Promise.resolve({ id })),
  }, 'topic-guard')()

  const pendingList = store.loadCandidates()
  await store.loadCandidates()
  oldList.resolve([{ id: 'old' }])
  await pendingList
  assert.equal(store.candidates[0].id, 'new')

  const pendingDetail = store.openCandidate('old')
  await store.openCandidate('new')
  oldDetail.resolve({ id: 'old' })
  await pendingDetail
  assert.equal(store.activeCandidate.id, 'new')
})

test('discussion send is explicit and handoff never claims selection', async () => {
  setActivePinia(createPinia())
  const calls = []
  const store = createTopicCenterStore({
    sendMessage: async (id, data) => {
      calls.push(['send', id, data])
      return { status: 'succeeded', requestId: 'r1', assistantMessageId: 'm2',
        result: { reply: '继续。', directionSuggestions: [], candidateSuggestions: [] } }
    },
    getDiscussion: async id => ({ discussion: { id }, messages: [], requests: [] }),
    handoff: async () => ({
      project: { id: 'p1', title: '典镇山河' },
      seed: { id: 's1', revision: 1, isSelected: false, selectionRevision: 0 },
      handoff: { candidateId: 'c1', version: 2 },
    }),
  }, 'topic-actions')()

  const message = await store.sendMessage('d1', { content: '我的想法' })
  const handoff = await store.handoff('c1', 2, {})
  assert.equal(message.result.reply, '继续。')
  assert.equal(calls.length, 1)
  assert.equal(handoff.seed.isSelected, false)
  assert.equal(handoff.seed.selectionRevision, 0)
  assert.equal(store.handoffBusy, false)
})

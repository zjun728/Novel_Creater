import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { createTopicCenterStore } from '../../src/stores/topicCenterStore.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
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
  store.activeDiscussion = { discussion: { id: 'd1' }, messages: [], requests: [] }

  const message = await store.sendMessage('d1', { content: '我的想法' })
  const handoff = await store.handoff('c1', 2, {})
  assert.equal(message.result.reply, '继续。')
  assert.equal(calls.length, 1)
  assert.equal(handoff.seed.isSelected, false)
  assert.equal(handoff.seed.selectionRevision, 0)
  assert.equal(store.handoffBusy, false)
})

test('provider-not-ready failure remains available until explicitly cleared', async () => {
  setActivePinia(createPinia())
  const failure = Object.assign(new Error('请先配置默认模型'), {
    code: 'TOPIC_PROVIDER_NOT_READY',
  })
  const store = createTopicCenterStore({
    sendMessage: async () => { throw failure },
  }, 'topic-provider-recovery')()
  store.activeDiscussion = { discussion: { id: 'd1' }, messages: [], requests: [] }

  await assert.rejects(
    store.sendMessage('d1', { content: '保留这段想法' }),
    candidate => candidate === failure,
  )
  assert.equal(store.lastSendFailure.discussionId, 'd1')
  assert.equal(store.lastSendFailure.code, 'TOPIC_PROVIDER_NOT_READY')
  assert.equal(store.lastSendFailure.message, '请先配置默认模型')

  store.clearSendFailure()
  assert.equal(store.lastSendFailure, null)
})

test('draft persistence does not expand the public topic store recovery API', () => {
  setActivePinia(createPinia())
  const store = createTopicCenterStore({}, 'topic-recovery-surface')()
  assert.equal(store.lastSendFailure, null)
  assert.equal(typeof store.clearSendFailure, 'function')
  for (const key of ['getDraft', 'setDraft', 'clearDraft']) assert.equal(store[key], undefined)
})

test('a parsed send response is accepted without depending on discussion refresh', async () => {
  setActivePinia(createPinia())
  let refreshCalls = 0
  const store = createTopicCenterStore({
    sendMessage: async () => ({
      status: 'succeeded', requestId: 'r1', assistantMessageId: 'm2',
      result: { reply: '已接受。', directionSuggestions: [], candidateSuggestions: [] },
    }),
    getDiscussion: async () => { refreshCalls += 1; throw new Error('reload failed') },
  }, 'topic-send-acceptance')()
  store.activeDiscussion = { discussion: { id: 'd1' }, messages: [], requests: [] }

  const result = await store.sendMessage('d1', { content: '已提交内容' })

  assert.equal(result.result.reply, '已接受。')
  assert.equal(refreshCalls, 0)
  assert.equal(store.lastSendFailure, null)
})

test('a second concurrent send is rejected without stealing sending ownership', async () => {
  setActivePinia(createPinia())
  const gate = deferred()
  let calls = 0
  const store = createTopicCenterStore({
    sendMessage: async () => { calls += 1; return gate.promise },
    getDiscussion: async id => ({ discussion: { id }, messages: [], requests: [] }),
  }, 'topic-send-owner')()
  store.activeDiscussion = { discussion: { id: 'd1' }, messages: [], requests: [] }

  const first = store.sendMessage('d1', { content: '第一条' })
  await assert.rejects(
    store.sendMessage('d1', { content: '第二条' }),
    failure => failure?.code === 'TOPIC_SEND_BUSY',
  )
  assert.equal(calls, 1)
  assert.equal(store.sending, true)

  gate.resolve({ status: 'succeeded', requestId: 'r1', assistantMessageId: 'm2',
    result: { reply: '继续。', directionSuggestions: [], candidateSuggestions: [] } })
  await first
  assert.equal(store.sending, false)
  assert.equal(store.lastSendFailure, null)
})

test('failure remains scoped to its origin discussion after context switches', async () => {
  setActivePinia(createPinia())
  const gate = deferred()
  const store = createTopicCenterStore({
    sendMessage: async () => gate.promise,
    getDiscussion: async id => ({ discussion: { id }, messages: [], requests: [] }),
  }, 'topic-stale-send-failure')()
  store.activeDiscussion = { discussion: { id: 'd1' }, messages: [], requests: [] }

  const pending = store.sendMessage('d1', { content: '旧讨论' })
  await store.openDiscussion('d2')
  gate.reject(Object.assign(new Error('old provider failure'), {
    code: 'TOPIC_PROVIDER_NOT_READY',
  }))
  await assert.rejects(pending)

  assert.equal(store.activeDiscussion.discussion.id, 'd2')
  assert.equal(store.lastSendFailure.discussionId, 'd1')
  assert.equal(store.lastSendFailure.code, 'TOPIC_PROVIDER_NOT_READY')
})

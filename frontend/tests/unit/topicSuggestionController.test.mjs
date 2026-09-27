import assert from 'node:assert/strict'
import test from 'node:test'
import { createTopicSuggestionController, enterBlankTopicDiscussion } from '../../src/application/topics/topicSuggestionController.js'

function fixture(overrides = {}) {
  const calls = []
  const market = {
    sources: [{ id: 'a', displayName: '综合榜', canRefresh: true }, { id: 'b', displayName: '停用榜', canRefresh: false }],
    loadSources: async () => calls.push('sources'), isSourceBusy: () => false,
    refreshSource: async (id, key) => { calls.push(['refresh', id, key]); return { id: 'snapshot-a', contentHash: 'hash-a', capturedAt: 1 } },
    ...overrides.market,
  }
  const topics = {
    sending: false, selectedEvidence: [], discussionSubject: { id: 'old' },
    createDiscussion: async title => { calls.push(['create', title]); return { discussion: { id: 'new-discussion' } } },
    sendMessage: async (id, data) => calls.push(['send', id, data]),
    openDiscussion: async id => calls.push(['open', id]), ...overrides.topics,
  }
  return { calls, market, topics, controller: createTopicSuggestionController({ market, topics, commandKey: () => 'k'.repeat(64) }) }
}

test('genre selection does not fetch or generate; explicit generation binds fresh evidence to a new discussion', async () => {
  const { calls, controller, topics } = fixture()
  controller.selectGenre('修真')
  assert.equal(controller.state.genre, '修真')
  assert.deepEqual(calls, [])
  assert.equal(await controller.generate(), true)
  const send = calls.find(item => item[0] === 'send')
  assert.equal(send[1], 'new-discussion')
  assert.match(send[2].content, /修真/)
  assert.match(send[2].content, /不是该题材专榜/)
  assert.deepEqual(send[2].evidence, [{ snapshotId: 'snapshot-a', contentHash: 'hash-a' }])
  assert.equal(topics.discussionSubject, null)
  assert.equal(calls.filter(item => item[0] === 'refresh').length, 1)
})

test('all failed sources stop before discussion creation and provider generation', async () => {
  const { controller, calls } = fixture({ market: { refreshSource: async () => { throw Error('offline') } } })
  assert.equal(await controller.generate(), false)
  assert.match(controller.state.error, /未调用 AI/)
  assert.equal(controller.state.sources[0].succeeded, false)
  assert.equal(calls.some(item => ['create', 'send'].includes(item[0])), false)
})

test('partial refresh never uses stale or failed snapshots', async () => {
  const { controller, calls } = fixture({ market: {
    sources: [{ id: 'a', displayName: '成功', canRefresh: true }, { id: 'b', displayName: '失败', canRefresh: true }],
    refreshSource: async id => { if (id === 'b') throw Error('offline'); return { id: 'fresh', contentHash: 'fresh-hash', capturedAt: 5 } },
  } })
  assert.equal(await controller.generate(), true)
  assert.deepEqual(calls.find(item => item[0] === 'send')[2].evidence, [{ snapshotId: 'fresh', contentHash: 'fresh-hash' }])
  assert.deepEqual(controller.state.sources.map(item => item.succeeded), [true, false])
})

test('double clicks and genre changes cannot replace an in-flight generation', async () => {
  let release
  const pending = new Promise(resolve => { release = resolve })
  const { controller, calls } = fixture({ market: { loadSources: () => pending } })
  const first = controller.generate()
  controller.selectGenre('修真')
  assert.equal(controller.state.genre, '东方玄幻')
  assert.equal(await controller.generate(), false)
  release()
  assert.equal(await first, true)
  assert.equal(calls.filter(item => item[0] === 'send').length, 1)
})

test('ambiguous send outcome prevents duplicate creation and retains discussion recovery identity', async () => {
  const { controller, calls } = fixture({ topics: { sendMessage: async () => { throw Error('connection lost') } } })
  assert.equal(await controller.generate(), false)
  assert.equal(controller.state.discussionId, 'new-discussion')
  assert.equal(controller.state.outcomeUnknown, true)
  assert.equal(await controller.generate(), false)
  assert.equal(calls.filter(item => item[0] === 'create').length, 1)
})

test('failure to read successful results asks for recovery rather than claiming generation failed', async () => {
  const { controller } = fixture({ topics: { openDiscussion: async () => { throw Error('offline') } } })
  assert.equal(await controller.generate(), false)
  assert.match(controller.state.error, /建议已生成/)
  assert.equal(controller.state.discussionId, 'new-discussion')
})


test('failed regeneration keeps the last successful cards, provenance and genre across page remount', async () => {
  const result = { directionSuggestions: [{ title: '真实建议' }] }
  const { controller, topics, market } = fixture({ topics: {
    openDiscussion: async () => ({ requests: [{ status: 'succeeded', assistantMessageId: 'assistant', result, completedAt: 123 }] }),
  } })
  await controller.generate()
  assert.deepEqual(controller.state.lastResult.result, result)
  assert.equal(controller.state.lastResult.sources[0].capturedAt, 1)
  const original = controller.state.lastResult
  controller.selectGenre('历史')
  market.refreshSource = async () => { throw Error('offline') }
  assert.equal(await controller.generate(), false)
  assert.equal(controller.state.lastResult, original)
  assert.equal(controller.state.lastResult.genre, '东方玄幻')
  const remounted = createTopicSuggestionController({ topics, market })
  assert.equal(remounted.state.lastResult, original)
})

test('direct discussion clears recommendation context without creating or sending anything', () => {
  const calls = []
  const topics = { sending: false, activeDiscussion: { discussion: { id: 'old' } }, selectedEvidence: [{ snapshotId: 'market' }], discussionSubject: { id: 'direction' }, discussionRecommendation: { title: '不应带入' },
    leaveSection: () => calls.push('invalidate'), clearSendFailure: () => calls.push('clear'),
    createDiscussion: () => assert.fail('must not create on navigation'), sendMessage: () => assert.fail('must not send on navigation') }
  assert.equal(enterBlankTopicDiscussion(topics), true)
  assert.equal(topics.activeDiscussion, null)
  assert.deepEqual(topics.selectedEvidence, [])
  assert.equal(topics.discussionSubject, null)
  assert.equal(topics.discussionRecommendation, null)
  assert.deepEqual(calls, ['invalidate', 'clear'])
})

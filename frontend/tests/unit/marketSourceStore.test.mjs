import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { useMarketSourceStore } from '../../src/stores/marketSourceStore.js'

function response(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

async function withFetch(fetchImpl, action) {
  const original = globalThis.fetch
  globalThis.fetch = fetchImpl
  try {
    return await action()
  } finally {
    globalThis.fetch = original
  }
}

const source = {
  id: 'qidian',
  stableKey: 'qidian-newsign',
  displayName: '起点新人签约榜',
  platform: 'qidian',
  rankingName: 'newsign',
  category: 'male',
  policyStatus: 'verified_public',
  automaticRefreshAllowed: true,
  refreshStatus: 'failed',
  lastSucceededAt: 1_752_800_000,
  lastSnapshotId: 'snapshot-1',
  publicErrorCode: 'MARKET_FETCH_FAILED',
  scheduleRevision: 3,
  scheduleEnabled: false,
  scheduleIntervalMinutes: 360,
  scheduleNextRunAt: null,
}

test('source inventory retains last success and visible failure beside immutable snapshot freshness', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  await withFetch(async url => {
    if (String(url).endsWith('/market-sources')) return response([source])
    if (String(url).endsWith('/market-sources/qidian/snapshots')) {
      return response([{
        id: 'snapshot-1',
        sourceId: 'qidian',
        capturedAt: 1_752_800_000,
        contentHash: 'a'.repeat(64),
        entryCount: 20,
      }])
    }
    throw new Error(`unexpected request ${url}`)
  }, () => store.loadSources())

  assert.equal(store.sources[0].lastSucceededAt, 1_752_800_000)
  assert.equal(store.sources[0].publicErrorCode, 'MARKET_FETCH_FAILED')
  assert.equal(store.snapshotHistory.qidian[0].id, 'snapshot-1')
  assert.equal(store.sourceState('qidian').freshness, 'available-with-later-failure')
})

test('manual import and per-source refresh publish only returned snapshot facts', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  const requests = []
  await withFetch(async (url, options) => {
    requests.push({
      path: String(url).replace('http://127.0.0.1:8000/api', ''),
      method: options.method,
      body: JSON.parse(options.body),
    })
    return response({
      id: options.method === 'POST' ? `snapshot-${requests.length}` : 'snapshot',
      sourceId: 'qidian',
      capturedAt: 123,
      contentHash: 'c'.repeat(64),
      entryCount: 1,
      entries: [],
    })
  }, async () => {
    await store.importManualSnapshot('qidian', {
      platform: 'qidian',
      rankingName: 'newsign',
      category: 'male',
      capturedAt: 123,
      sourceURL: 'https://www.qidian.com/rank/newsign/',
      entries: [{
        rank: 1, title: '甲', author: '乙', category: '玄幻',
        workURL: 'https://www.qidian.com/book/1/', publicMetrics: {},
      }],
    }, 'm'.repeat(64))
    await store.refreshSource('qidian', 'r'.repeat(64))
  })

  assert.deepEqual(requests.map(item => item.path), [
    '/market-sources/qidian/manual-import',
    '/market-sources/qidian/refresh',
  ])
  assert.equal(requests[0].body.snapshot.entries[0].title, '甲')
  assert.equal(requests[1].body.idempotencyKey, 'r'.repeat(64))
})

test('snapshot success and later failure both reload authoritative source freshness safely', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  store.$patch({
    sources: [{
      ...source,
      refreshStatus: 'idle',
      lastSucceededAt: null,
      lastSnapshotId: null,
      publicErrorCode: null,
    }],
  })
  let phase = 'success'

  await withFetch(async (url, options) => {
    if (options.method === 'POST' && phase === 'success') {
      return response({
        id: 'snapshot-2',
        sourceId: 'qidian',
        capturedAt: 1_752_900_000,
        contentHash: 'e'.repeat(64),
        entryCount: 1,
        entries: [],
      })
    }
    if (options.method === 'POST') {
      return response({
        error: {
          code: 'MARKET_FETCH_FAILED',
          message: 'refresh failed',
        },
      }, 502)
    }
    if (phase === 'success') {
      return response({
        ...source,
        refreshStatus: 'succeeded',
        lastSucceededAt: 1_752_900_001,
        lastSnapshotId: 'snapshot-2',
        publicErrorCode: null,
      })
    }
    return response({
      ...source,
      refreshStatus: 'failed',
      lastSucceededAt: 1_752_900_001,
      lastSnapshotId: 'snapshot-2',
      publicErrorCode: 'MARKET_FETCH_FAILED',
    })
  }, async () => {
    await store.refreshSource('qidian', 'a'.repeat(64))
    assert.equal(store.sources[0].lastSnapshotId, 'snapshot-2')
    assert.equal(store.sources[0].lastSucceededAt, 1_752_900_001)
    assert.equal(store.sources[0].publicErrorCode, null)

    phase = 'failure'
    await assert.rejects(
      store.refreshSource('qidian', 'b'.repeat(64)),
      error => error.status === 502,
    )
    assert.equal(store.sources[0].lastSnapshotId, 'snapshot-2')
    assert.equal(store.sources[0].lastSucceededAt, 1_752_900_001)
    assert.equal(store.sources[0].publicErrorCode, 'MARKET_FETCH_FAILED')
    assert.equal(
      store.sourceState('qidian').freshness,
      'available-with-later-failure',
    )
  })
})

test('global market state does not expose removed project analysis or scheduling operations', () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  for (const property of [
    'updateSchedule',
    'scheduleExplanation',
    'scheduleConflictSourceId',
    'analyze',
    'activateProject',
    'analysisState',
    'analysisProjectId',
    'analysisLoading',
  ]) {
    assert.equal(property in store, false, `${property} should not be public`)
  }
})

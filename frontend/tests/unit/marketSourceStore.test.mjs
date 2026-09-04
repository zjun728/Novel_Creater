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
  adapterKey: 'qidian_public_rank',
  platform: 'qidian',
  rankingName: 'newsign',
  category: 'male',
  policyStatus: 'verified_public',
  policyVersion: 'public-rank-policy-v1',
  checkedAt: 1_752_700_000,
  evidenceURL: 'https://www.qidian.com/',
  automaticRefreshAllowed: true,
  canManualImport: true,
  canRefresh: true,
  canSchedule: false,
  refreshStatus: 'idle',
  lastAttemptedAt: null,
  lastSucceededAt: 1_752_800_000,
  lastSnapshotId: 'snapshot-1',
  publicErrorCode: 'MARKET_FETCH_FAILED',
}

function snapshotSummary(id = 'snapshot-1', entryCount = 1) {
  return {
    id, sourceId: 'qidian', capturedAt: 1_752_800_000,
    platform: 'qidian', rankingName: 'newsign', category: 'male',
    sourceURL: 'https://www.qidian.com/rank/newsign/', contentHash: 'a'.repeat(64),
    entryCount, captureMode: 'network', adapterVersion: 'qidian-public-rank-v1',
  }
}

function snapshotDetail(id = 'snapshot-1') {
  return {
    ...snapshotSummary(id),
    entries: [{
      rank: 1, title: '雾港天文钟', author: '合成作者甲', category: '奇幻',
      workURL: 'https://www.qidian.com/book/1/', publicMetrics: {},
    }],
  }
}

test('source inventory retains last success and visible failure beside immutable snapshot freshness', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  await withFetch(async url => {
    if (String(url).endsWith('/market-sources')) return response([source])
    if (String(url).endsWith('/market-sources/qidian/snapshots')) {
      return response([snapshotSummary('snapshot-1')])
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
    return response(snapshotDetail(`snapshot-${requests.length}`))
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
      return response(snapshotDetail('snapshot-2'))
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
        refreshStatus: 'idle',
        lastSucceededAt: 1_752_900_001,
        lastSnapshotId: 'snapshot-2',
        publicErrorCode: null,
      })
    }
    return response({
      ...source,
        refreshStatus: 'idle',
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

test('store rejects unparsed API payloads before they enter state', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  await withFetch(async () => response([{ ...source, secret: 'sensitive' }]), async () => {
    await assert.rejects(store.loadSources(), TypeError)
  })
  assert.deepEqual(store.sources, [])
})

test('snapshot detail cache requires matching source identity and retains immutable success on failure', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  let phase = 'success'
  await withFetch(async () => {
    if (phase === 'success') return response(snapshotDetail())
    if (phase === 'mismatch') return response({ ...snapshotDetail(), sourceId: 'other' })
    return response({ code: 'MARKET_REFRESH_FAILED', message: 'failed' }, 503)
  }, async () => {
    const detail = await store.loadSnapshotDetail('qidian', 'snapshot-1')
    assert.equal(Object.isFrozen(detail), true)
    assert.equal(Object.isFrozen(detail.entries), true)

    phase = 'mismatch'
    await assert.rejects(store.loadSnapshotDetail('qidian', 'snapshot-1'), TypeError)
    assert.equal(store.snapshotDetails[JSON.stringify(['qidian', 'snapshot-1'])], detail)

    phase = 'failure'
    await assert.rejects(store.loadSnapshotDetail('qidian', 'snapshot-1'))
    assert.equal(store.snapshotDetails[JSON.stringify(['qidian', 'snapshot-1'])], detail)
    assert.equal(store.snapshotDetailFailures[JSON.stringify(['qidian', 'snapshot-1'])].status, 503)
  })
})

test('late independent snapshot detail response remains cached under its own composite key', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  let releaseFirst
  const first = new Promise(resolve => { releaseFirst = resolve })
  await withFetch(async url => {
    if (String(url).endsWith('/snapshot-1')) {
      await first
      return response(snapshotDetail('snapshot-1'))
    }
    return response(snapshotDetail('snapshot-2'))
  }, async () => {
    const oldRequest = store.loadSnapshotDetail('qidian', 'snapshot-1')
    const latest = await store.loadSnapshotDetail('qidian', 'snapshot-2')
    releaseFirst()
    await oldRequest
    assert.equal(store.snapshotDetails[JSON.stringify(['qidian', 'snapshot-2'])], latest)
    assert.equal(store.snapshotDetails[JSON.stringify(['qidian', 'snapshot-1'])].id, 'snapshot-1')
  })
})

test('store fences source and history identity mismatches at the parsed client boundary', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  await withFetch(async url => {
    if (String(url).endsWith('/market-sources/qidian')) return response({ ...source, id: 'other' })
    if (String(url).endsWith('/snapshots')) return response([{ ...snapshotSummary(), sourceId: 'other' }])
    return response([source])
  }, async () => {
    await assert.rejects(store.loadSource('qidian'), TypeError)
    await assert.rejects(store.loadSources(), TypeError)
  })
})

test('cache separates equal snapshot ids from different sources', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  await withFetch(async url => {
    const isOther = String(url).includes('/other/')
    return response({ ...snapshotDetail('same'), sourceId: isOther ? 'other' : 'qidian' })
  }, async () => {
    const qidian = await store.loadSnapshotDetail('qidian', 'same')
    const other = await store.loadSnapshotDetail('other', 'same')
    assert.equal(store.snapshotDetails[JSON.stringify(['qidian', 'same'])], qidian)
    assert.equal(store.snapshotDetails[JSON.stringify(['other', 'same'])], other)
  })
})

test('successful refresh reloads authoritative history for a first snapshot', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  await withFetch(async (url, options) => {
    if (options.method === 'POST') return response(snapshotDetail('first'))
    if (String(url).endsWith('/snapshots')) return response([snapshotSummary('first')])
    return response(source)
  }, async () => {
    await store.refreshSource('qidian', 'r'.repeat(64))
  })
  assert.equal(store.snapshotHistory.qidian[0].id, 'first')
})

test('successful refresh keeps a first immutable history fallback when reread fails', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  await withFetch(async (url, options) => {
    if (options.method === 'POST') return response(snapshotDetail('first'))
    if (String(url).endsWith('/snapshots')) return response({ code: 'MARKET_REFRESH_FAILED' }, 503)
    return response(source)
  }, async () => { await store.refreshSource('qidian', 'r'.repeat(64)) })
  assert.equal(store.snapshotHistory.qidian[0].id, 'first')
  assert.equal(Object.hasOwn(store.snapshotHistory.qidian[0], 'entries'), false)
  assert.equal(Object.isFrozen(store.snapshotHistory.qidian[0]), true)
})

test('bulk commit cannot invalidate a newer pending point source request', async () => {
  setActivePinia(createPinia())
  const store = useMarketSourceStore()
  let releaseBulk
  let releasePoint
  const bulkGate = new Promise(resolve => { releaseBulk = resolve })
  const pointGate = new Promise(resolve => { releasePoint = resolve })
  let listCalls = 0
  await withFetch(async url => {
    const path = String(url)
    if (path.endsWith('/market-sources')) {
      listCalls += 1
      await bulkGate
      return response([{ ...source, displayName: 'bulk' }])
    }
    if (path.endsWith('/market-sources/qidian')) {
      await pointGate
      return response({ ...source, displayName: 'point' })
    }
    if (path.endsWith('/snapshots')) return response([snapshotSummary()])
    throw new Error(`unexpected ${path}`)
  }, async () => {
    const bulk = store.loadSources()
    const point = store.loadSource('qidian')
    releaseBulk()
    await bulk
    releasePoint()
    await point
  })
  assert.equal(listCalls, 1)
  assert.equal(store.sources[0].displayName, 'point')
})

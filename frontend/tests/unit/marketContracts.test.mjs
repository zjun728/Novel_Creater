import assert from 'node:assert/strict'
import test from 'node:test'

import {
  parseMarketSource,
  parseMarketSnapshotDetail,
  parseMarketSnapshotSummary,
} from '../../src/application/market/marketContracts.js'

const summary = {
  id: 'snapshot-1', sourceId: 'qidian', capturedAt: 1_752_800_000,
  platform: 'qidian', rankingName: 'newsign', category: 'male',
  sourceURL: 'https://www.qidian.com/rank/newsign/', contentHash: 'a'.repeat(64),
  entryCount: 1, captureMode: 'network', adapterVersion: 'qidian-public-rank-v1',
}

const detail = {
  ...summary,
  entries: [{
    rank: 1, title: '雾港天文钟', author: '合成作者甲', category: '奇幻',
    workURL: 'https://www.qidian.com/book/900000001/',
    publicMetrics: { weeklyRecommendations: 321 },
  }],
}

test('parses and deeply freezes trusted network snapshot detail', () => {
  const parsed = parseMarketSnapshotDetail(detail)
  assert.equal(parsed.captureMode, 'network')
  assert.equal(parsed.entries[0].rank, 1)
  assert.equal(parsed.entries[0].workURL, detail.entries[0].workURL)
  assert.equal(Object.isFrozen(parsed), true)
  assert.equal(Object.isFrozen(parsed.entries), true)
  assert.equal(Object.isFrozen(parsed.entries[0]), true)
  assert.equal(Object.isFrozen(parsed.entries[0].publicMetrics), true)
})

test('rejects untrusted snapshot shapes and provenance', () => {
  const cases = [
    { ...detail, extra: true },
    { ...detail, entries: [{ ...detail.entries[0], rank: 2 }] },
    { ...detail, entries: [{ ...detail.entries[0], workURL: 'http://www.qidian.com/book/1/' }] },
    { ...detail, entries: [{ ...detail.entries[0], publicMetrics: Object.fromEntries(Array.from({ length: 33 }, (_, index) => [`m${index}`, index])) }] },
    { ...detail, entryCount: 2 },
    { ...detail, captureMode: 'unknown' },
    { ...detail, adapterVersion: 'untrusted_adapter-v99' },
  ]
  for (const value of cases) assert.throws(() => parseMarketSnapshotDetail(value))
  assert.throws(() => parseMarketSnapshotSummary({ ...summary, entries: [] }))
})

test('enforces snapshot integer, hash, entry, URL, and metric boundaries without URL rewriting', () => {
  const badUrls = [
    'https://user@www.qidian.com/book/1/', 'https://www.qidian.com:443/book/1/',
    'https://www.qidian.com/book/1/#x', 'https://localhost/book/1/',
    'https://127.0.0.1/book/1/', 'https://www.qidian.com/%2fbook/1/',
    'https://www.qidian.com/%5cbook/1/', 'https://www.qidian.com/%25x',
    'https://ｗｗｗ.qidian.com/book/1/', 'https://www.qidian.com\\book/1/',
    'https://intranet/', 'https://foo.localhost/book/1/', 'https://-internal.com/book/1/',
  ]
  for (const capturedAt of [0, -1, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => parseMarketSnapshotSummary({ ...summary, capturedAt }))
  }
  for (const entryCount of [0, 101]) assert.throws(() => parseMarketSnapshotSummary({ ...summary, entryCount }))
  for (const contentHash of ['A'.repeat(64), 'g'.repeat(64), 'a'.repeat(63)]) {
    assert.throws(() => parseMarketSnapshotSummary({ ...summary, contentHash }))
  }
  for (const workURL of badUrls) {
    assert.throws(() => parseMarketSnapshotSummary({ ...summary, sourceURL: workURL }))
    assert.throws(() => parseMarketSnapshotDetail({ ...detail, entries: [{ ...detail.entries[0], workURL }] }))
  }
  for (const sourceURL of [
    'https://www.qidian.com/%zz', 'https://www.qidian.com/%ZZ',
    'https://www.qidian.com/%', 'https://www.qidian.com/%2',
  ]) assert.throws(() => parseMarketSnapshotSummary({ ...summary, sourceURL }))
  assert.equal(
    parseMarketSnapshotSummary({ ...summary, sourceURL: 'https://www.qidian.com/%E4%BD%9C%E5%93%81' }).sourceURL,
    'https://www.qidian.com/%E4%BD%9C%E5%93%81',
  )
  assert.throws(() => parseMarketSnapshotDetail({ ...detail, entries: [{ ...detail.entries[0], workURL: 'https://book.qidian.com/book/1/' }] }))
  for (const publicMetrics of [{ key: 'x'.repeat(513) }, { key: null }, { key: {} }, { key: Infinity }, { key: NaN }]) {
    assert.throws(() => parseMarketSnapshotDetail({ ...detail, entries: [{ ...detail.entries[0], publicMetrics }] }))
  }
  assert.equal(parseMarketSnapshotDetail({ ...detail, entries: [{ ...detail.entries[0], publicMetrics: { metric: 1e16 } }] }).entries[0].publicMetrics.metric, 1e16)
  assert.throws(() => parseMarketSnapshotDetail({ ...detail, entries: [{ ...detail.entries[0], extra: true }] }))
})

test('accepts only bidirectionally consistent capture mode and adapter version', () => {
  assert.equal(parseMarketSnapshotDetail({ ...detail, adapterVersion: 'future-market-v12' }).adapterVersion, 'future-market-v12')
  for (const value of [
    { ...detail, captureMode: 'manual' },
    { ...detail, captureMode: 'network', adapterVersion: 'manual-snapshot-v1' },
    { ...detail, captureMode: 'manual', adapterVersion: 'future-market-v1' },
    { ...detail, adapterVersion: 'Future-v1' },
  ]) assert.throws(() => parseMarketSnapshotDetail(value))
})

test('rejects non-data record boundaries while accepting backend-valid Unicode text', () => {
  const withSymbol = { ...summary, [Symbol('extra')]: true }
  assert.throws(() => parseMarketSnapshotSummary(withSymbol))
  const getter = { ...summary }
  Object.defineProperty(getter, 'id', { enumerable: true, get: () => 'snapshot-1' })
  assert.throws(() => parseMarketSnapshotSummary(getter))
  assert.equal(parseMarketSnapshotDetail({ ...detail, entries: [{ ...detail.entries[0], title: '星��‍��' }] }).entries[0].title, '星��‍��')
  const source = {
    id: 'qidian', stableKey: 'qidian-newsign', displayName: '星��‍��', adapterKey: 'qidian_public_rank', platform: 'qidian', rankingName: 'newsign', category: 'male', policyStatus: 'verified_public', policyVersion: 'v1', checkedAt: 1, evidenceURL: 'https://www.qidian.com/', automaticRefreshAllowed: true, canManualImport: true, canRefresh: true, canSchedule: false, refreshStatus: 'idle', lastAttemptedAt: null, lastSucceededAt: null, lastSnapshotId: null, publicErrorCode: null,
  }
  assert.equal(parseMarketSource(source).displayName, '星��‍��')
  assert.throws(() => parseMarketSource({ ...source, canRefresh: false }))
})

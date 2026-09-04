import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

const component = path.resolve(
  import.meta.dirname,
  '../../src/components/topics/MarketSnapshotWorks.vue',
)

test('ranked snapshot reads as public evidence rather than a count-only receipt', async () => {
  const source = await readFile(component, 'utf8')
  for (const text of ['排名', '书名', '作者', '题材', '公开指标', '查看原页面']) {
    assert.match(source, new RegExp(text))
  }
  assert.match(source, /entry\.workURL/)
  assert.match(source, /rel="noopener noreferrer"/)
  assert.match(source, /snapshot\.entries/)
  assert.match(source, /snapshot\.capturedAt/)
  assert.match(source, /snapshot\.entryCount/)
})

test('ranked snapshot exposes provenance, attachment, and readable metric labels', async () => {
  const source = await readFile(component, 'utf8')
  assert.match(source, /网络刷新/)
  assert.match(source, /人工导入/)
  assert.match(source, /adapterVersion/)
  assert.match(source, /附加到讨论/)
  assert.match(source, /visibleMetrics/)
  assert.match(source, /metricLabel/)
  assert.match(source, /aria-label="榜单作品"/)
  assert.match(source, /:aria-busy="loading"/)
  assert.match(source, /aria-live="polite"/)
  assert.match(source, /loadAnnouncement/)
})

test('ranked snapshot keeps mobile reading on the page scroll owner', async () => {
  const source = await readFile(component, 'utf8')
  assert.match(source, /@media\s*\(max-width:\s*720px\)/)
  assert.doesNotMatch(source, /document\.body|body\s*\{/)
  assert.doesNotMatch(source, /\.ranked-works\s*\{[^}]*overflow-y:\s*(?:auto|scroll)/)
})

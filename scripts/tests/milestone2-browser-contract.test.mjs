import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  assertSafeBrowserGraph,
  assertSafeBrowserSource,
} from '../browser-source-contract.mjs'

const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
)
const formalSpecs = [
  'e2e/m2-foundation-regression.spec.ts',
  'e2e/m2-wizard-manual.spec.ts',
  'e2e/m2-wizard-recovery.spec.ts',
  'e2e/m2-settings-assets-corpus.spec.ts',
]

function readFormalBrowserSource(fileName) {
  try {
    return readFileSync(path.join(repositoryRoot, 'frontend', fileName), 'utf8')
  } catch (error) {
    if (error?.code === 'ENOENT') return undefined
    throw error
  }
}

function requireFormalBrowserSource(fileName) {
  const source = readFormalBrowserSource(fileName)
  assert.equal(typeof source, 'string', `missing formal M2 browser source: ${fileName}`)
  return source
}

function declaredWriteRules(source) {
  const rules = source.split(/\r?\n/u)
    .map(line => line.trim().replace(/,$/u, ''))
    .filter(line => /^\{ method: '[A-Z]+', path: .+, count: \d+, statuses: \[\d+(?:, ?\d+)*\] \}$/u.test(line))
  assert.equal(
    rules.length,
    (source.match(/\bmethod:\s*'[A-Z]+'/gu) || []).length,
    'every write rule must be one exact auditable entry',
  )
  const identities = rules.map(rule => {
    const match = rule.match(/^\{ method: '([^']+)', path: (.+), count:/u)
    return `${match[1]} ${match[2]}`
  })
  assert.equal(new Set(identities).size, identities.length, 'write rules must not overlap')
  return rules
}

test('all formal M2 browser specs and their local import closures are safe', () => {
  for (const spec of formalSpecs) {
    assert.doesNotThrow(
      () => assertSafeBrowserGraph(spec, readFormalBrowserSource),
      `unsafe formal M2 browser graph: ${spec}`,
    )
  }
})

test('formal M2 specs start only from their assigned product pages', () => {
  for (const spec of formalSpecs.slice(0, 3)) {
    const source = requireFormalBrowserSource(spec)
    assert.match(
      source,
      /page\.goto\(['"]\/project\/00000000-0000-0000-0000-000000000201['"]\)/,
    )
    assert.equal((source.match(/page\.goto\(/g) || []).length, 1)
  }
  const settings = requireFormalBrowserSource(formalSpecs[3])
  assert.match(settings, /page\.goto\(['"]\/settings['"]\)/)
  assert.equal((settings.match(/page\.goto\(/g) || []).length, 1)
})

test('formal browser config requires the runner-owned dynamic Vite base URL', () => {
  const source = requireFormalBrowserSource('playwright.m2.config.ts')
  assert.match(source, /process\.env\.PLAYWRIGHT_BASE_URL/u)
  assert.doesNotMatch(source, /baseURL:\s*['"]http:\/\/127\.0\.0\.1:5173/u)
})

test('manual wizard declares the exact write contract and no Provider creation route', () => {
  const source = requireFormalBrowserSource('e2e/m2-wizard-manual.spec.ts')
  const expectedEntries = [
    "{ method: 'PUT', path: /\\/selected-seed$/, count: 1, statuses: [200] }",
    "{ method: 'POST', path: /\\/story-engine-batches\\/manual$/, count: 1, statuses: [201] }",
    "{ method: 'PUT', path: /\\/contract-draft$/, count: 3, statuses: [200] }",
    "{ method: 'POST', path: /\\/contracts\\/preview$/, count: 1, statuses: [200] }",
    "{ method: 'POST', path: /\\/contracts\\/confirm$/, count: 1, statuses: [201] }",
  ]

  assert.deepEqual(declaredWriteRules(source), expectedEntries)
  assert.doesNotMatch(source, /story-engine-batches\s*\/?['"`]/)
  assert.doesNotMatch(source, /生成三套方案|生成新三案/)
  for (const required of [
    '返回故事发动机',
    '.dblclick()',
    'page.reload()',
    '当前生效的创作契约',
    '创建新修订',
  ]) assert.equal(source.includes(required), true, required)
})

test('recovery wizard freezes reconcile plus real two-tab draft CAS without Provider creation', () => {
  const source = requireFormalBrowserSource('e2e/m2-wizard-recovery.spec.ts')
  assert.deepEqual(declaredWriteRules(source), [
    "{ method: 'POST', path: /\\/story-engine-batches\\/manual$/, count: 2, statuses: [201] }",
    "{ method: 'PUT', path: /\\/contract-draft$/, count: 2, statuses: [200, 409] }",
    "{ method: 'POST', path: /\\/story-engine-batches\\/[^/]+\\/reconcile$/, count: 2, statuses: [200] }",
  ])
  assert.doesNotMatch(source, /path: \/\\\/story-engine-batches\\\/$/u)
  assert.doesNotMatch(source, /生成三套方案|生成新三案/u)
  for (const required of [
    '核对批次 00000701',
    '核对批次 00000702',
    'context().newPage()',
    '草稿版本已经变化',
    'statuses: [200, 409]',
  ]) assert.equal(source.includes(required), true, required)
})

test('foundation and settings goals cover the retained v1.1 and bounded asset corpus UI', () => {
  const foundation = requireFormalBrowserSource('e2e/m2-foundation-regression.spec.ts')
  for (const required of [
    'writer-core-v1.1.0',
    'Canon 0',
    'Projection 0',
    '进入写作台',
    'toBeDisabled',
    '本书创作契约',
    'Not Ready · 暂不可生成',
    'task_unbound:writing',
    '正文写作尚未绑定',
  ]) assert.equal(foundation.includes(required), true, required)
  assert.deepEqual(declaredWriteRules(foundation), [])

  const settings = requireFormalBrowserSource('e2e/m2-settings-assets-corpus.spec.ts')
  for (const required of [
    '创作资产',
    'writer-core-v1.1.0',
    '10 / 10',
    '64 / 64',
    '本机语料',
    'synthetic-browser-corpus.txt',
  ]) assert.equal(settings.includes(required), true, required)
  assert.doesNotMatch(settings, /打开有界预览|章节索引|片段预览/u)
  assert.equal(
    settings.includes("getByText('创作资产', { exact: true })"),
    true,
  )
  assert.equal(
    settings.includes("getByText('本机语料', { exact: true })"),
    true,
  )
  assert.equal(
    settings.includes("getByRole('region', { name: '已导入语料修订' })"),
    true,
  )
  assert.doesNotMatch(settings, /getByRole\(['"]tab['"]/u)
  assert.deepEqual(declaredWriteRules(settings), [
    "{ method: 'POST', path: /\\/corpus\\/imports$/, count: 1, statuses: [200] }",
  ])
  assert.equal(settings.includes('apiResponses.filter'), true)
  assert.equal((settings.match(/toHaveLength\(1\)/gu) || []).length >= 2, true)
})

test('approved formal goals use only real semantic UI locators without ordinal selectors', () => {
  for (const spec of formalSpecs) {
    const source = requireFormalBrowserSource(spec)
    assert.doesNotMatch(source, /\.first\(\)|\.last\(\)|\.nth\(/u)
    assert.doesNotMatch(source, /\.locator\(/u)
    assert.equal(source.includes('runtimeSensitiveValues()'), true)
    assert.equal(source.includes("requiredEnvironment('BROWSER_TEST_DATABASE')"), false)
  }
})

test('source contract accepts UI actions and rejects shadow writes', () => {
  assert.doesNotThrow(() => assertSafeBrowserSource(
    "await page.getByRole('button', { name: '确认' }).click()",
  ))

  const forbiddenSources = [
    "await page.request.post('/api/contracts/confirm')",
    "await page['request'].post('/api/contracts/confirm')",
    "await page?.request.post('/api/contracts/confirm')",
    "await page/* comment */.request.post('/api/contracts/confirm')",
    "await request.post('/api/contracts/confirm')",
    "await request.put('/api/contracts/confirm')",
    "await request.patch('/api/contracts/confirm')",
    "await request.delete('/api/contracts/confirm')",
    "await fetch('/api/contracts/confirm', { method: 'POST' })",
    "await globalThis.fetch('/api/contracts/confirm', { method: 'POST' })",
    "await self.fetch('/api/contracts/confirm', { method: 'POST' })",
    "import { api } from '@/api/db/client'; await api.contracts.confirm('p1')",
    "await api.contracts.confirm('p1')",
    'await api.health()',
    "await api['health']()",
    "await page.route('**/api/**', route => route.fulfill({ status: 200 }))",
    'await route.continue()',
    'await route.fallback()',
    'await route.abort()',
    "import axios from 'axios'; await axios.post('/api/contracts/confirm')",
    "import got from 'got'; await got.post('/api/contracts/confirm')",
    "import { request } from 'undici'; await request('/api/contracts/confirm')",
    "const xhr = new XMLHttpRequest(); xhr.open('POST', '/api/contracts/confirm')",
    "import http from 'node:http'; http.request('http://127.0.0.1')",
    "const https = require('https'); https.request('https://example.invalid')",
    "https.get('https://example.invalid')",
    "async function write(p) { await p.request.post('/api/write') } await write(page)",
    "async function write({ request: client }) { await client.post('/api/write') }",
  ]

  for (const source of forbiddenSources) {
    assert.throws(() => assertSafeBrowserSource(source), /shadow browser write/)
  }
})

test('source contract ignores forbidden-looking comments and string literals', () => {
  assert.doesNotThrow(() => assertSafeBrowserSource(`
    // await fetch('/api/contracts/confirm')
    const documentation = "page.request.post('/api/contracts/confirm')"
    await page.getByLabel('api.health()').fill(documentation)
  `))
})

test('source contract scans every local import in the graph', () => {
  const files = new Map([
    ['spec.ts', "import './safe-helper.js'; await page.getByRole('button').click()"],
    ['safe-helper.js', "export * from './unsafe-helper.js'"],
    ['unsafe-helper.js', "await page.request.post('/api/contracts/confirm')"],
  ])

  assert.throws(
    () => assertSafeBrowserGraph('spec.ts', name => files.get(name)),
    /shadow browser write.*unsafe-helper\.js/,
  )
})

test('source graph discovers imports separated by comments', () => {
  for (const entrySource of [
    "import /* local helper */ './unsafe-helper.js'",
    "await import /* local helper */ ('./unsafe-helper.js')",
    "require /* local helper */ ('./unsafe-helper.js')",
  ]) {
    const files = new Map([
      ['spec.ts', entrySource],
      ['unsafe-helper.js', "await page['request'].post('/api/contracts/confirm')"],
    ])

    assert.throws(
      () => assertSafeBrowserGraph('spec.ts', name => files.get(name)),
      /shadow browser write.*unsafe-helper\.js/,
    )
  }
})

test('source graph rejects missing and outside-root helpers', () => {
  assert.throws(
    () => assertSafeBrowserGraph('spec.ts', name => (
      name === 'spec.ts' ? "import './missing.js'" : undefined
    )),
    /missing browser source.*missing\.js/,
  )

  assert.throws(
    () => assertSafeBrowserGraph('spec.ts', name => (
      name === 'spec.ts' ? "import '../outside.js'" : undefined
    )),
    /outside browser source root/,
  )

  assert.throws(
    () => assertSafeBrowserGraph('C:\\outside\\spec.ts', () => 'export const safe = true'),
    /outside browser source root/,
  )

  assert.throws(
    () => assertSafeBrowserGraph('C:outside\\spec.ts', () => 'export const safe = true'),
    /outside browser source root/,
  )
})

test('source graph handles safe cycles and still detects unsafe cyclic helpers', () => {
  const safeCycle = new Map([
    ['spec.ts', "import './a.js'; await page.getByRole('button').click()"],
    ['a.js', "import './b.js'; export const a = true"],
    ['b.js', "import './a.js'; export const b = true"],
  ])
  assert.doesNotThrow(() => assertSafeBrowserGraph('spec.ts', name => safeCycle.get(name)))

  safeCycle.set('b.js', "import './a.js'; await route.abort()")
  assert.throws(
    () => assertSafeBrowserGraph('spec.ts', name => safeCycle.get(name)),
    /shadow browser write.*b\.js/,
  )
})

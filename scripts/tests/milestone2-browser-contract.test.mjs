import assert from 'node:assert/strict'
import test from 'node:test'

import {
  assertSafeBrowserGraph,
  assertSafeBrowserSource,
} from '../browser-source-contract.mjs'

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

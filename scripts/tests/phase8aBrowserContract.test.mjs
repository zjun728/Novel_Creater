import assert from 'node:assert/strict'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph, collectBrowserTestDeclarations } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const source = relative => readFileSync(path.join(root, relative), 'utf8')

test('Phase 8A registers one exact disposable browser target', async () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(rootPackage.scripts['test:browser:phase8a'], 'node scripts/run-tests.mjs browser-phase8a')
  assert.equal(frontendPackage.scripts['test:e2e:phase8a'], 'node e2e/run-phase8a.mjs')
  assert.equal(frontendPackage.scripts['test:browser:phase8a'], 'node ../scripts/run-tests.mjs browser-phase8a')
  for (const relative of [
    'backend/scripts/prepare_phase8a_browser_db.py',
    'frontend/e2e/run-phase8a.mjs',
    'frontend/e2e/playwright.phase8a.config.mjs',
    'frontend/e2e/phase8a/manuscript-productization.spec.mjs',
  ]) assert.equal(existsSync(path.join(root, relative)), true, relative)

  const calls = []
  assert.equal(runSuites(['browser-phase8a'], {
    rootDirectory: root,
    environment: {
      TEST_MYSQL_HOST: '127.0.0.1', TEST_MYSQL_PORT: '33060',
      TEST_MYSQL_USER: 'root', TEST_MYSQL_PASSWORD: 'test-only',
    },
    pytestTempLifecycle: { prepare() {}, cleanupStage() {}, cleanupAll() {} },
    spawnSyncImpl(command, args, options) { calls.push({ command, args, options }); return { status: 0 } },
  }), 0)
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase8a.mjs']])
  const runner = await import('../../frontend/e2e/run-phase8a.mjs')
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase8a.config.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, ['phase8a/manuscript-productization.spec.mjs'])
})

test('Phase 8A runner owns unique ports, root, browser cache, downloads, and schema cleanup', () => {
  const runner = source('frontend/e2e/run-phase8a.mjs')
  for (const marker of [
    'createDatabaseName', 'reserveLocalPort', 'new Set(ports).size', 'createOwnedRoot',
    'browser-downloads', 'downloads', 'artifacts', 'waitForPortRelease',
    'prepare_phase8a_browser_db', 'prepare_product_shell_browser_db', '--drop',
    'runOwnedProductLifecycle', 'stopOwnedServer', 'BROWSER_OUTBOUND_LEDGER_PATH',
    'assertDenyProxyLedger', '1/1 wide-screen point passed', 'owned child processes/ports/temp/downloads/disposable schemas=0',
    'expectedConnectCount: counts.connect',
    "process.once('SIGINT'", "process.once('SIGTERM'", 'cleanupRoot(owned, roots, ports)',
  ]) assert.equal(runner.includes(marker), true, marker)
  assert.doesNotMatch(runner, /\bmysqld\b|MYSQL_DB:\s*['"]novel_creator['"]/u)
  assert.match(runner, /self\.inner = RealAsyncClient/u)
  assert.match(runner, /def deny\(self\):/u)
  assert.ok(runner.indexOf("def deny(self):") < runner.indexOf("output.write('forbidden-outbound"))
  assert.equal(runner.includes('provider-client-created'), false)
})

test('Phase 8A cleanup removes its owned root even when an audit fails', async () => {
  const { cleanupRoot } = await import('../../frontend/e2e/run-phase8a.mjs')
  const owned = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase8a-'))
  const roots = {
    outboundLedgerPath: path.join(owned, 'outbound-ledger.log'),
    denyProxyLedgerPath: path.join(owned, 'deny-proxy.log'),
  }
  mkdirSync(path.join(owned, 'vite-cache'))
  writeFileSync(roots.outboundLedgerPath, '')
  writeFileSync(roots.denyProxyLedgerPath, 'invalid-entry\n')
  await assert.rejects(cleanupRoot(owned, roots, [], {
    removeOwnedRootImpl: target => rmSync(target, { recursive: true, force: true }),
  }), /denied browser background/u)
  assert.equal(existsSync(owned), false)
})

test('Phase 8A visible workflow is wide-screen only and mutation safe', () => {
  const entry = 'frontend/e2e/phase8a/manuscript-productization.spec.mjs'
  const spec = source(entry)
  assertSafeBrowserGraph(entry, relative => source(relative))
  const declarations = collectBrowserTestDeclarations(spec, entry)
  assert.deepEqual(declarations.map(item => item.title), [
    '@phase8a accepts the complete awaiting-author and corrupt manuscript workflows at wide desktop sizes',
  ])
  for (const marker of [
    '1440', '900', 'innerWidth', 'prefers-reduced-motion', 'scrollWidth', 'clientWidth', '44',
    '作品稿件', '泔水醒来，三日织机赌局', '废料改机', '复验定局',
    '查看本章定稿', '归档', 'waitForEvent', 'download.saveAs',
    'manuscript-chapter-1-download-txt', 'manuscript-chapter-3-download-txt',
  ]) assert.equal(spec.includes(marker), true, marker)
  assert.doesNotMatch(spec, /page\.request|page\.route|\bfetch\s*\(|\baxios\b|route\.fulfill/u)
  const evaluateCalls = [...spec.matchAll(/page\.evaluate\s*\(([^;]+);?/gu)].map(match => match[0])
  assert.ok(evaluateCalls.length > 0)
  assert.doesNotMatch(spec, /page\.evaluate[^\n]*(?:click|value\s*=|dispatchEvent|localStorage|sessionStorage|style\.)/u)
  assert.match(spec, /box\.width >= 44 && box\.height >= 44/u)
  assert.match(spec, /motion\.transitionDuration/u)
})

test('Phase 8A config has one Chromium worker and runner-owned output paths', () => {
  const config = source('frontend/e2e/playwright.phase8a.config.mjs')
  for (const marker of ['chromium', 'workers: 1', 'fullyParallel: false', 'BROWSER_DOWNLOAD_ROOT', 'BROWSER_ARTIFACT_ROOT']) {
    assert.equal(config.includes(marker), true, marker)
  }
  assert.match(config, /chromium-wide-100/u)
  const spec = source('frontend/e2e/phase8a/manuscript-productization.spec.mjs')
})

test('Phase 8A assertion failures are classified without exposing report content', async () => {
  const { classifyBrowserFailure } = await import('../../frontend/e2e/run-phase8a.mjs')
  const owned = mkdtempSync(path.join(os.tmpdir(), 'phase8a-report-'))
  const report = path.join(owned, 'result.json')
  try {
    writeFileSync(report, JSON.stringify({ errors: [{ message: 'aggregate failure' }], suites: [{ specs: [{ tests: [{ results: [{ errors: [{
      message: 'SECRET visible manuscript value',
      location: { file: 'manuscript-productization.spec.mjs', line: 123, column: 4 },
    }] }] }] }] }] }))
    assert.equal(classifyBrowserFailure(report), 'assertion@123')
    writeFileSync(report, JSON.stringify({ errors: [{
      message: 'Test timeout of 300000ms exceeded',
      location: { file: 'manuscript-productization.spec.mjs', line: 44, column: 4 },
    }] }))
    assert.equal(classifyBrowserFailure(report), 'timeout@44')
    writeFileSync(report, JSON.stringify({ errors: [{
      message: 'SECRET assertion failure',
      stack: 'Error: SECRET assertion failure\n at manuscript-productization.spec.mjs:205:7',
    }] }))
    assert.equal(classifyBrowserFailure(report), 'assertion@205')
    writeFileSync(report, JSON.stringify({ suites: [{ specs: [{ tests: [{ results: [{ error: {
      message: 'SECRET singular reporter error',
      stack: 'Error: SECRET\n at manuscript-productization.spec.mjs:206:8',
    } }] }] }] }] }))
    assert.equal(classifyBrowserFailure(report), 'assertion@206')
  } finally {
    rmSync(owned, { recursive: true, force: true })
  }
})

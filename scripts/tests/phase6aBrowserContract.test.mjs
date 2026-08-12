import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph, collectBrowserTestDeclarations } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const source = relative => readFileSync(path.join(root, relative), 'utf8')

test('Phase 6A owns one disposable UI-only browser lifecycle', async () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(rootPackage.scripts['test:browser:phase6a'], 'node scripts/run-tests.mjs browser-phase6a')
  assert.equal(frontendPackage.scripts['test:e2e:phase6a'], 'node e2e/run-phase6a.mjs')
  assert.equal(frontendPackage.scripts['test:browser:phase6a'], 'node ../scripts/run-tests.mjs browser-phase6a')
  for (const relative of [
    'backend/scripts/prepare_phase6a_browser_db.py',
    'frontend/e2e/run-phase6a.mjs',
    'frontend/e2e/playwright.phase6a.config.mjs',
    'frontend/e2e/phase6a/finalized-novel-download.spec.mjs',
  ]) assert.equal(existsSync(path.join(root, relative)), true, relative)
  const calls = []
  const status = runSuites(['browser-phase6a'], {
    rootDirectory: root,
    environment: {
      TEST_MYSQL_HOST: '127.0.0.1', TEST_MYSQL_PORT: '33060',
      TEST_MYSQL_USER: 'root', TEST_MYSQL_PASSWORD: 'test-only',
    },
    pytestTempLifecycle: { prepare() {}, cleanupStage() {}, cleanupAll() {} },
    spawnSyncImpl(command, args, options) { calls.push({ command, args, options }); return { status: 0 } },
  })
  assert.equal(status, 0)
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase6a.mjs']])
  const runner = await import('../../frontend/e2e/run-phase6a.mjs')
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase6a.config.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, ['phase6a/finalized-novel-download.spec.mjs'])
  assert.match(source('frontend/e2e/run-phase6a.mjs'), /createDatabaseName/u)
  assert.match(source('frontend/e2e/run-phase6a.mjs'), /reserveLocalPort/u)
  for (const marker of [
    'downloads', 'DENY_PROXY_SOURCE', 'PHASE6A_HOLD_DOWNLOAD_SECONDS',
    'assertDenyProxyLedger', '--verify-postconditions', 'waitForPortRelease',
    'deps_temp_', 'BROWSER_OUTBOUND_LEDGER_PATH',
  ]) assert.equal(source('frontend/e2e/run-phase6a.mjs').includes(marker), true, marker)
  const config = source('frontend/e2e/playwright.phase6a.config.mjs')
  assert.match(config, /BROWSER_DOWNLOAD_ROOT/u)
  assert.match(config, /output paths must be direct children/u)
  assert.match(config, /proxy:/u)
  assert.doesNotMatch(source('frontend/e2e/run-phase6a.mjs'), /provider.*(?:url|key)|mysqld/iu)
})

test('Phase 6A browser spec uses visible controls and Playwright download events only', () => {
  const entry = 'frontend/e2e/phase6a/finalized-novel-download.spec.mjs'
  const spec = source(entry)
  assertSafeBrowserGraph(entry, relative => source(relative))
  const declarations = collectBrowserTestDeclarations(spec, entry)
  assert.deepEqual(declarations.map(item => item.title), [
    '@phase6a downloads finalized TXT from Overview and Markdown after archive',
  ])
  assert.match(declarations[0].bodySource, /waitForEvent\(['"]download/u)
  assert.match(spec, /download\.saveAs/u)
  assert.match(spec, /readFile\(target, 'utf8'\)/u)
  assert.match(spec, /PHASE6A_WORKING_SENTINEL/u)
  assert.match(spec, /PHASE6A_CANDIDATE_SENTINEL/u)
  assert.match(spec, /PHASE6A_UNSAVED_SENTINEL/u)
  assert.match(spec, /waitForEvent\(['"]page/u)
  assert.match(spec, /modifiers:\s*\[['"]Control['"]\]/u)
  assert.match(spec, /\.fill\(UNSAVED_SENTINEL\)/u)
  assert.match(spec, /toHaveValue\(UNSAVED_SENTINEL\)/u)
  assert.match(spec, /未暂存/u)
  assert.match(spec, /正在准备下载/u)
  for (const label of ['下载整本定稿', '下载分卷定稿', '归档']) {
    assert.equal(declarations[0].bodySource.includes(label), true, label)
  }
  assert.doesNotMatch(spec, /page\.(?:request|route|evaluate)|\bfetch\(|\baxios\b/u)
})

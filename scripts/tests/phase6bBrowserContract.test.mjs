import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph, collectBrowserTestDeclarations } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const source = relative => readFileSync(path.join(root, relative), 'utf8')

test('Phase 6B owns one disposable UI-only browser lifecycle and verifier', async () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(rootPackage.scripts['test:browser:phase6b'], 'node scripts/run-tests.mjs browser-phase6b')
  assert.equal(frontendPackage.scripts['test:e2e:phase6b'], 'node e2e/run-phase6b.mjs')
  assert.equal(frontendPackage.scripts['test:browser:phase6b'], 'node ../scripts/run-tests.mjs browser-phase6b')

  for (const relative of [
    'backend/scripts/prepare_phase6b_browser_db.py',
    'frontend/e2e/run-phase6b.mjs',
    'frontend/e2e/playwright.phase6b.config.mjs',
    'frontend/e2e/phase6b/project-backup.spec.mjs',
  ]) assert.equal(existsSync(path.join(root, relative)), true, relative)

  const calls = []
  const status = runSuites(['browser-phase6b'], {
    rootDirectory: root,
    environment: {
      TEST_MYSQL_HOST: '127.0.0.1', TEST_MYSQL_PORT: '33060',
      TEST_MYSQL_USER: 'root', TEST_MYSQL_PASSWORD: 'test-only',
    },
    pytestTempLifecycle: { prepare() {}, cleanupStage() {}, cleanupAll() {} },
    spawnSyncImpl(command, args, options) { calls.push({ command, args, options }); return { status: 0 } },
  })
  assert.equal(status, 0)
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase6b.mjs']])

  const runner = await import('../../frontend/e2e/run-phase6b.mjs')
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase6b.config.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, ['phase6b/project-backup.spec.mjs'])
  const runnerSource = source('frontend/e2e/run-phase6b.mjs')
  for (const marker of [
    'createDatabaseName', 'reserveLocalPort', 'DENY_PROXY_SOURCE',
    'artifactRoot', 'downloadRoot', 'corpusRoot', 'packageTempRoot',
    'assertDenyProxyLedger', '--verify-postconditions', 'waitForPortRelease',
    'deps_temp_', 'BROWSER_OUTBOUND_LEDGER_PATH', 'VERIFY_PACKAGE_SOURCE',
    'consumerFailure', 'safeClassifyFailure', 'manifest.json',
  ]) assert.equal(runnerSource.includes(marker), true, marker)
  assert.match(
    runnerSource,
    /async def phase6b_held_project_package\(path, cleanup\):[\s\S]*?finally:[\s\S]*?cleanup\(\)/u,
    'held response cancellation invokes the real idempotent package cleanup',
  )
  assert.doesNotMatch(runnerSource, /@app\.middleware\(['"]http['"]\)/u)
  assert.match(runnerSource, /manifest\.get\('format'\) != 'novel-creator-project'/u)
  assert.doesNotMatch(runnerSource, /novel-creator-project-package/u)
  assert.doesNotMatch(runnerSource, /OPENAI_API_KEY|ANTHROPIC_API_KEY|mysqld/iu)
  assert.match(runnerSource, /PHASE6B_VERIFY_STATE_PATH/u)
  assert.match(runnerSource, /phase6bVerifierCause/u)
  for (const marker of ['active-entry-set', 'active-zip-mode', 'active-corpus-blob']) {
    assert.equal(runnerSource.includes(marker), true, marker)
  }

  const verifierFailure = new Error('hidden')
  verifierFailure.phase6bStage = 'package-verifier'
  verifierFailure.phase6bVerifierCause = 'active-lifecycle'
  assert.deepEqual(JSON.parse(runner.safeClassifyFailure(verifierFailure)), {
    firstStage: 'package-verifier', errorCount: 1, browserCause: null,
    fixtureCause: null, verifierCause: 'active-lifecycle',
  })

  const fixture = source('backend/scripts/prepare_phase6b_browser_db.py')
  assert.match(fixture, /DraftOperationService/u)
  assert.match(fixture, /await operation_service\._reserve\(/u)
  assert.match(fixture, /await operation_service\.cancel\(/u)
  assert.match(fixture, /class ProviderMustNotRun/u)
  assert.doesNotMatch(fixture, /INSERT INTO draft_operation_attempts/iu)

  const config = source('frontend/e2e/playwright.phase6b.config.mjs')
  for (const marker of [
    'BROWSER_DOWNLOAD_ROOT', 'BROWSER_ARTIFACT_ROOT', 'BROWSER_CORPUS_ROOT',
    'BROWSER_PACKAGE_TEMP_ROOT', 'output paths must be direct children', 'proxy:',
  ]) assert.equal(config.includes(marker), true, marker)
})

test('Phase 6B browser spec uses visible UI, real downloads, ZIP verification and consumer failure', () => {
  const entry = 'frontend/e2e/phase6b/project-backup.spec.mjs'
  const spec = source(entry)
  assertSafeBrowserGraph(entry, relative => source(relative))
  const declarations = collectBrowserTestDeclarations(spec, entry)
  assert.deepEqual(declarations.map(item => item.title), [
    '@phase6b backs up active and archived project with consumer cleanup',
  ])
  const body = declarations[0].bodySource
  assert.match(spec, /waitForEvent\(['"]download/u)
  assert.match(spec, /download\.saveAs/u)
  assert.match(body, /consumerPage\.close/u)
  assert.match(body, /创建项目备份/u)
  assert.match(spec, /正在建立一致快照|正在写入备份包/u)
  assert.match(
    spec,
    /await expect\(page\.getByRole\('dialog', \{ name: '正在建立一致快照' \}\)\)\.toBeHidden/u,
    'backup helper waits for its blocking operation to finish before later UI actions',
  )
  assert.match(
    spec,
    /await expect\(card\)\.toBeVisible\(\{ timeout: uiTimeout \}\)/u,
    'library actions wait for the asynchronously loaded project card',
  )
  assert.match(spec, /activeListResponsePromise/u)
  assert.match(spec, /pathname\.endsWith\('\/api\/projects'\)/u)
  assert.match(spec, /phase6b-library-load-error/u)
  assert.match(spec, /phase6b-library-empty/u)
  assert.match(spec, /phase6b-library-card-missing/u)
  assert.match(spec, /Phase6A finalized download/u)
  assert.doesNotMatch(spec, /contract integration/u)
  assert.match(body, /归档/u)
  assert.match(body, /Novel Creator 项目库/u)
  assert.match(spec, /X-Package-SHA256|x-package-sha256/u)
  assert.doesNotMatch(spec, /page\.(?:request|route|evaluate)|\bfetch\(|\baxios\b/u)
})

test('Phase 6B classifies only actual Playwright errors with fixed locator categories', async () => {
  const { classifyBrowserFailure } = await import('../../frontend/e2e/run-phase6b.mjs')
  const rootPath = mkdtempSync(path.join(os.tmpdir(), 'phase6b-classifier-'))
  const resultPath = path.join(rootPath, 'result.json')
  try {
    writeFileSync(resultPath, JSON.stringify({
      config: { timeout: 180_000 },
      suites: [{ specs: [{ tests: [{ results: [{ errors: [{
        message: 'expect(received).toBe(expected)',
        location: { file: 'project-backup.spec.mjs', line: 65 },
      }] }] }] }] }],
    }))
    assert.equal(classifyBrowserFailure(resultPath), 'assertion@65')

    writeFileSync(resultPath, JSON.stringify({ suites: [{ specs: [{ tests: [{ results: [{ errors: [{
      message: 'locator.click: Timeout 10000ms exceeded.\nCall log:\n - waiting for locator',
      location: { file: 'project-backup.spec.mjs', line: 67 },
    }] }] }] }] }] }))
    assert.equal(classifyBrowserFailure(resultPath), 'locator-missing@67')

    writeFileSync(resultPath, JSON.stringify({ suites: [{ specs: [{ tests: [{ results: [{ errors: [{
      message: 'locator.click: Timeout 10000ms exceeded.\nlocator resolved to element\nintercepts pointer events',
      location: { file: 'project-backup.spec.mjs', line: 67 },
    }] }] }] }] }] }))
    assert.equal(classifyBrowserFailure(resultPath), 'locator-intercepted@67')

    writeFileSync(resultPath, JSON.stringify({ suites: [{ specs: [{ tests: [{ results: [{ errors: [{
      message: 'phase6b-library-empty',
      location: { file: 'project-backup.spec.mjs', line: 74 },
    }] }] }] }] }] }))
    assert.equal(classifyBrowserFailure(resultPath), 'phase6b-library-empty')
  } finally {
    rmSync(rootPath, { recursive: true, force: true })
  }
})

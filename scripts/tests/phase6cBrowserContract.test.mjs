import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { EventEmitter } from 'node:events'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph, collectBrowserTestDeclarations } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const source = relative => readFileSync(path.join(root, relative), 'utf8')

test('Phase 6C owns one disposable browser lifecycle and formal gate', async () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(rootPackage.scripts['test:browser:phase6c'], 'node scripts/run-tests.mjs browser-phase6c')
  assert.equal(frontendPackage.scripts['test:e2e:phase6c'], 'node e2e/run-phase6c.mjs')
  assert.equal(frontendPackage.scripts['test:browser:phase6c'], 'node ../scripts/run-tests.mjs browser-phase6c')

  for (const relative of [
    'backend/scripts/prepare_phase6c_browser_db.py',
    'frontend/e2e/run-phase6c.mjs',
    'frontend/e2e/playwright.phase6c.config.mjs',
    'frontend/e2e/phase6c/project-import.spec.mjs',
    'frontend/e2e/phase6c/runtime-observer.mjs',
  ]) assert.equal(existsSync(path.join(root, relative)), true, relative)

  const calls = []
  const status = runSuites(['browser-phase6c'], {
    rootDirectory: root,
    environment: {
      TEST_MYSQL_HOST: '127.0.0.1', TEST_MYSQL_PORT: '33060',
      TEST_MYSQL_USER: 'root', TEST_MYSQL_PASSWORD: 'test-only',
    },
    pytestTempLifecycle: { prepare() {}, cleanupStage() {}, cleanupAll() {} },
    spawnSyncImpl(command, args, options) { calls.push({ command, args, options }); return { status: 0 } },
  })
  assert.equal(status, 0)
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase6c.mjs']])

  const runner = await import('../../frontend/e2e/run-phase6c.mjs')
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase6c.config.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, ['phase6c/project-import.spec.mjs'])
  const runnerSource = source('frontend/e2e/run-phase6c.mjs')
  for (const marker of [
    'createDatabaseName', 'reserveLocalPort', 'DENY_PROXY_SOURCE',
    'artifactRoot', 'downloadRoot', 'corpusRoot', 'packageTempRoot', 'quarantineRoot',
    'assertDenyProxyLedger', '--verify-postconditions', 'waitForPortRelease',
    'deps_temp_', 'BROWSER_OUTBOUND_LEDGER_PATH', 'phase6c_held_import',
    'consumerFailure', 'safeClassifyFailure', 'project-import-staging',
  ]) assert.equal(runnerSource.includes(marker), true, marker)
  assert.doesNotMatch(runnerSource, /OPENAI_API_KEY|ANTHROPIC_API_KEY|mysqld/iu)

  const fixture = source('backend/scripts/prepare_phase6c_browser_db.py')
  for (const marker of [
    'prepare_phase6b_browser_db', 'ProviderMustNotRun', 'read_verified_project_package',
    'verify_postconditions', 'project_package_import_commands', 'project_import_provenance',
    'managed_corpus_storage_key',
  ]) assert.equal(fixture.includes(marker), true, marker)
  assert.doesNotMatch(fixture, /provider_profile_revision/u)

  const config = source('frontend/e2e/playwright.phase6c.config.mjs')
  for (const marker of [
    'BROWSER_DOWNLOAD_ROOT', 'BROWSER_ARTIFACT_ROOT', 'BROWSER_CORPUS_ROOT',
    'BROWSER_PACKAGE_TEMP_ROOT', 'BROWSER_IMPORT_QUARANTINE_ROOT',
    'output paths must be direct children', 'proxy:',
  ]) assert.equal(config.includes(marker), true, marker)
})

test('Phase 6C spec is one visible UI backup-import-download flow with recovery', () => {
  const entry = 'frontend/e2e/phase6c/project-import.spec.mjs'
  const spec = source(entry)
  assertSafeBrowserGraph(entry, relative => source(relative))
  const declarations = collectBrowserTestDeclarations(spec, entry)
  assert.deepEqual(declarations.map(item => item.title), [
    '@phase6c imports a real backup atomically and recovers its unknown result',
  ])
  const body = declarations[0].bodySource
  for (const marker of [
    '创建项目备份', '导入项目备份', '选择项目备份', 'setInputFiles',
    '新项目名称', '导入为新项目', 'Provider Not Ready', '下载整本定稿',
    'waitForEvent', 'download.saveAs', 'consumerFailure', 'visibleImportState',
    'importStatusSummary',
  ]) assert.equal(spec.includes(marker), true, marker)
  const observer = source('frontend/e2e/phase6c/runtime-observer.mjs')
  for (const marker of [
    'importStatusSummary', 'postCount', 'getCount', 'statusCategories',
    'consoleErrors', 'requestFailures', 'non2xx', 'originViolations', 'listenerCount',
  ]) {
    assert.equal(observer.includes(marker), true, marker)
  }
  assert.doesNotMatch(`${spec}\n${observer}`, /response\.(?:body|json|text)\s*\(/u)
  assert.match(body, /getByRole\(['"]button['"],\s*\{\s*name:\s*['"]导入为新项目/u)
  assert.match(body, /getByLabel\(['"]新项目名称/u)
  assert.doesNotMatch(spec, /page\.(?:request|route|evaluate)|\bfetch\(|\baxios\b/u)
  for (const forbidden of ['合并', '覆盖', '目标项目', '二次确认', '取消导入']) {
    assert.equal(spec.includes(forbidden), false, forbidden)
  }
})

test('Phase 6C failure classification ignores configured timeout values', async () => {
  const { classifyBrowserFailureResult } = await import('../../frontend/e2e/run-phase6c.mjs')
  const configuredOnly = {
    config: { timeout: 240_000, use: { actionTimeout: 12_000 } },
    errors: [{
      message: 'runtime-console-frameworkOrPageError-adjacent-count-1',
      location: { file: 'phase6c/project-import.spec.mjs', line: 111, column: 3 },
    }],
  }
  assert.equal(
    classifyBrowserFailureResult(configuredOnly),
    'runtime-console-frameworkOrPageError-adjacent-count-1@111',
  )
  assert.equal(classifyBrowserFailureResult({
    config: { timeout: 240_000 },
    errors: [{
      message: 'Test timeout of 240000ms exceeded.',
      location: { file: 'phase6c/project-import.spec.mjs', line: 111, column: 3 },
    }],
  }), 'timeout@111')
})

test('Phase 6C runtime finish exposes only closed safe counters', async () => {
  const { observeRuntime, assertRuntimeEvidenceHealthy } = await import(
    '../../frontend/e2e/phase6c/runtime-observer.mjs'
  )
  const page = new EventEmitter()
  const runtime = observeRuntime(page, {
    allowedOrigins: ['http://127.0.0.1:4173'], expectedFailedRequest: '/api/project-imports',
  })
  page.emit('console', { type: () => 'error', text: () => 'sensitive text must not escape' })
  const evidence = await runtime.finish()
  assert.deepEqual(evidence, {
    consoleErrors: 1, expectedNetworkConsole: 0, requestFailures: 0,
    expectedCorsNetworkConsole: 0,
    expectedRequestFailures: 0, non2xx: 0, originViolations: 0,
    pendingRequests: 0, listenerCount: 0, pageErrors: 0,
    consoleDiagnostics: {
      locationlessNetwork: { adjacent: 0, notAdjacent: 0 },
      otherResourceNetwork: { adjacent: 0, notAdjacent: 0 },
      frameworkOrPageError: { adjacent: 0, notAdjacent: 0 },
      other: { adjacent: 0, notAdjacent: 1 },
    },
  })
  assert.throws(() => assertRuntimeEvidenceHealthy(evidence), {
    message: 'runtime-console-other-notAdjacent-count-1',
  })
  assert.equal(JSON.stringify(evidence).includes('sensitive text must not escape'), false)
})

test('Phase 6C runtime allows one exactly-associated Chromium CORS console event', async () => {
  const { observeRuntime, assertRuntimeEvidenceHealthy } = await import(
    '../../frontend/e2e/phase6c/runtime-observer.mjs'
  )
  const sourceOrigin = 'http://127.0.0.1:4173'
  const targetOrigin = 'http://127.0.0.1:4174'
  const expectedPath = '/api/project-imports'
  const cors = (source = sourceOrigin, target = `${targetOrigin}${expectedPath}`) => ({
    type: () => 'error',
    text: () => `Access to fetch at '${target}' from origin '${source}' has been blocked by CORS policy: No access control header is present.`,
    location: () => ({ url: `${sourceOrigin}/assets/app.js` }),
  })
  const failure = () => ({ method: () => 'POST', url: () => `${targetOrigin}${expectedPath}` })
  const capture = async events => {
    const page = new EventEmitter()
    const runtime = observeRuntime(page, {
      allowedOrigins: [sourceOrigin, targetOrigin], expectedFailedRequest: expectedPath,
    })
    for (const [event, value] of events) page.emit(event, value)
    return runtime.finish()
  }

  const zero = await capture([['requestfailed', failure()]])
  assert.equal(zero.expectedCorsNetworkConsole, 0)
  assert.doesNotThrow(() => assertRuntimeEvidenceHealthy(zero))
  const one = await capture([['console', cors()], ['requestfailed', failure()]])
  assert.equal(one.expectedCorsNetworkConsole, 1)
  assert.doesNotThrow(() => assertRuntimeEvidenceHealthy(one))
  const two = await capture([
    ['console', cors()], ['requestfailed', failure()], ['console', cors()],
  ])
  assert.throws(() => assertRuntimeEvidenceHealthy(two), {
    message: 'runtime-expected-cors-network-console-count-2',
  })

  for (const candidate of [
    cors('http://127.0.0.1:4999'),
    cors(sourceOrigin, `http://127.0.0.1:4999${expectedPath}`),
    cors(sourceOrigin, `${targetOrigin}${expectedPath}?retry=1`),
  ]) {
    const evidence = await capture([['console', candidate], ['requestfailed', failure()]])
    assert.throws(() => assertRuntimeEvidenceHealthy(evidence), {
      message: 'runtime-console-otherResourceNetwork-adjacent-count-1',
    })
  }

  const nonAdjacent = await capture([
    ['console', cors()], ['console', { type: () => 'log' }],
    ['console', { type: () => 'log' }], ['console', { type: () => 'log' }],
    ['requestfailed', failure()],
  ])
  assert.throws(() => assertRuntimeEvidenceHealthy(nonAdjacent), {
    message: 'runtime-console-otherResourceNetwork-notAdjacent-count-1',
  })
})

test('Phase 6C runtime binds the injected network failure exactly once', async () => {
  const { observeRuntime, assertRuntimeEvidenceHealthy } = await import(
    '../../frontend/e2e/phase6c/runtime-observer.mjs'
  )
  const origin = 'http://127.0.0.1:4173'
  const expectedPath = '/api/project-imports'
  const makePage = () => new EventEmitter()
  const failed = (method, suffix, selectedOrigin = origin) => ({
    method: () => method, url: () => `${selectedOrigin}${suffix}`,
  })
  const networkConsole = (suffix = expectedPath, selectedOrigin = origin) => ({
    type: () => 'error', text: () => 'Failed to load resource: net::ERR_FAILED',
    location: () => ({ url: `${selectedOrigin}${suffix}` }),
  })
  const capture = async events => {
    const page = makePage()
    const runtime = observeRuntime(page, {
      allowedOrigins: [origin], expectedFailedRequest: expectedPath,
    })
    for (const [event, value] of events) page.emit(event, value)
    return runtime.finish()
  }

  const exact = await capture([
    ['requestfailed', failed('POST', expectedPath)],
    ['console', networkConsole()],
    ['console', networkConsole()],
  ])
  assert.equal(exact.expectedRequestFailures, 1)
  assert.equal(exact.expectedNetworkConsole, 2)
  assert.doesNotThrow(() => assertRuntimeEvidenceHealthy(exact))

  for (const [events, message] of [
    [[], 'runtime-expected-request-failures-count-0'],
    [[
      ['requestfailed', failed('POST', expectedPath)],
      ['requestfailed', failed('POST', expectedPath)],
    ], 'runtime-expected-request-failures-count-2'],
    [[['requestfailed', failed('POST', expectedPath, 'http://127.0.0.1:4999')]],
      'runtime-request-failures-count-1'],
    [[['requestfailed', failed('POST', `${expectedPath}?retry=1`)]],
      'runtime-request-failures-count-1'],
    [[['requestfailed', failed('POST', `${expectedPath}/extra`)]],
      'runtime-request-failures-count-1'],
  ]) {
    const evidence = await capture(events)
    assert.throws(() => assertRuntimeEvidenceHealthy(evidence), { message })
  }

  const unrelatedConsole = await capture([
    ['requestfailed', failed('POST', expectedPath)],
    ['console', {
      type: () => 'error', text: () => 'product rendering failure',
      location: () => ({ url: `${origin}/projects` }),
    }],
  ])
  assert.throws(() => assertRuntimeEvidenceHealthy(unrelatedConsole), {
    message: 'runtime-console-frameworkOrPageError-adjacent-count-1',
  })
})

test('Phase 6C runtime reports fixed console diagnostic enums without details', async () => {
  const { observeRuntime, assertRuntimeEvidenceHealthy } = await import(
    '../../frontend/e2e/phase6c/runtime-observer.mjs'
  )
  const origin = 'http://127.0.0.1:4173'
  const expectedPath = '/api/project-imports'
  const page = new EventEmitter()
  const runtime = observeRuntime(page, {
    allowedOrigins: [origin], expectedFailedRequest: expectedPath,
  })
  const emitConsole = (text, url) => page.emit('console', {
    type: () => 'error', text: () => text, location: () => ({ url }),
  })
  emitConsole('Failed to load resource: net::ERR_FAILED', '')
  emitConsole('Failed to load resource: net::ERR_FAILED', `${origin}/other-resource`)
  page.emit('requestfailed', {
    method: () => 'POST', url: () => `${origin}${expectedPath}`,
  })
  emitConsole('framework render error', `${origin}/projects`)
  emitConsole('opaque console error', '')
  page.emit('pageerror', new Error('must not escape'))
  const evidence = await runtime.finish()
  assert.deepEqual(evidence.consoleDiagnostics, {
    locationlessNetwork: { adjacent: 1, notAdjacent: 0 },
    otherResourceNetwork: { adjacent: 1, notAdjacent: 0 },
    frameworkOrPageError: { adjacent: 1, notAdjacent: 0 },
    other: { adjacent: 1, notAdjacent: 0 },
  })
  assert.equal(evidence.pageErrors, 1)
  assert.equal(JSON.stringify(evidence).includes('must not escape'), false)
  assert.throws(() => assertRuntimeEvidenceHealthy(evidence), {
    message: 'runtime-console-locationlessNetwork-adjacent-count-1',
  })
})

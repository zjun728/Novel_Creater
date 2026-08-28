import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph, collectBrowserTestDeclarations } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'
import { runBoundedOwnedCommand as realBoundedCommand } from '../../frontend/e2e/support/product-runner.mjs'

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
    'pageEventLedgerPath', 'console known linked=4', 'console unexpected=0', 'page errors=0', 'request failures=0',
    "processTarget.once('SIGINT'", "processTarget.once('SIGTERM'", 'deps.cleanupRoot(owned, roots, ports)',
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

test('Phase 8A lifecycle prepares the owned fixture in two independent commands before services', async () => {
  const runner = await import('../../frontend/e2e/run-phase8a.mjs')
  const harness = phase8aHarness('success')
  assert.equal(await runner.runPhase8A({
    environment: harness.environment,
    dependencies: harness.dependencies,
    processTarget: harness.processTarget,
    log() {},
  }), 0)
  const fixtureCommands = harness.commandCalls.filter(call => call.label === 'Phase8A fixture preparation')
  assert.equal(fixtureCommands.length, 2)
  assert.equal(fixtureCommands[0].command, fixtureCommands[1].command)
  assert.deepEqual(fixtureCommands[0].args, fixtureCommands[1].args)
  assert.ok(fixtureCommands[1].sequence < harness.firstServerSequence)
  assert.deepEqual(harness.resources, {
    childProcesses: 0, ports: 0, tempRoots: 0, downloads: 0, schemas: 0,
  })
})

for (const scenario of ['success', 'assertion-failure', 'SIGINT', 'SIGTERM', 'child-startup-failure']) {
  test(`Phase 8A injected ${scenario} lifecycle releases every owned resource`, async () => {
    const runner = await import('../../frontend/e2e/run-phase8a.mjs')
    const harness = phase8aHarness(scenario)
    const operation = runner.runPhase8A({
      environment: harness.environment,
      dependencies: harness.dependencies,
      processTarget: harness.processTarget,
      log: value => harness.logs.push(value),
    })
    if (scenario === 'success') assert.equal(await operation, 0)
    else await assert.rejects(operation)
    assert.deepEqual(harness.resources, {
      childProcesses: 0, ports: 0, tempRoots: 0, downloads: 0, schemas: 0,
    })
    assert.equal(harness.processTarget.listenerCount('SIGINT'), 0)
    assert.equal(harness.processTarget.listenerCount('SIGTERM'), 0)
    assert.equal(harness.logs.length, scenario === 'success' ? 1 : 0)
  })
}

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
  assert.match(spec, /mappedChapterFiveAction\.click\(\)/u)
  assert.match(spec, /章节地址与服务端权威不一致/u)
  assert.equal(spec.includes('/planning/story-blocks$'), true)
  assert.match(spec, /第 5 章小纲/u)
  assert.match(spec, /assertFinalSequence\(chapterText, \[0\]\)/u)
  assert.match(spec, /assertFinalSequence\(volumeText, \[0, 1, 2\]\)/u)
  assert.match(spec, /assertFinalSequence\(bookText, \[0, 1, 2\]\)/u)
  assert.match(spec, /expectSafeFailure\(page, \(\) => page\.locator\('#manuscript-chapter-3'\)\.click\(\)\)/u)
  assert.match(spec, /expectSafeFailure\(page, \(\) => page\.locator\('#manuscript-chapter-3-download-txt'\)\.click\(\)\)/u)
  assert.match(spec, /PROSE\[2\]/u)
  assert.doesNotMatch(spec, /page\.request|page\.route|\bfetch\s*\(|\baxios\b|route\.fulfill/u)
  const evaluateCalls = [...spec.matchAll(/page\.evaluate\s*\(([^;]+);?/gu)].map(match => match[0])
  assert.ok(evaluateCalls.length > 0)
  assert.doesNotMatch(spec, /page\.evaluate[^\n]*(?:click|value\s*=|dispatchEvent|localStorage|sessionStorage|style\.)/u)
  assert.match(spec, /box\.width >= 44 && box\.height >= 44/u)
  assert.match(spec, /FOCUSABLE_SELECTOR/u)
  assert.match(spec, /assertKeyboardDomOrder/u)
  assert.match(spec, /expect\(box\)\.not\.toBeNull\(\)/u)
  assert.match(spec, /getComputedStyle\(element, '::before'\)/u)
  assert.match(spec, /getComputedStyle\(element, '::after'\)/u)
  assert.match(spec, /page\.on\('console'/u)
  assert.match(spec, /page\.on\('pageerror'/u)
  assert.match(spec, /page\.on\('requestfailed'/u)
  assert.match(spec, /page\.on\('response'/u)
  assert.match(spec, /assertPageEventsZero/u)
  assert.match(spec, /assertExpectedCorruptPageEvents/u)
})

test('Phase 8A config has one Chromium worker and runner-owned output paths', () => {
  const config = source('frontend/e2e/playwright.phase8a.config.mjs')
  for (const marker of ['chromium', 'workers: 1', 'fullyParallel: false', 'BROWSER_DOWNLOAD_ROOT', 'BROWSER_ARTIFACT_ROOT']) {
    assert.equal(config.includes(marker), true, marker)
  }
  assert.match(config, /chromium-wide-100/u)
  assert.match(config, /headless:\s*false/u)
  assert.match(config, /launchOptions:\s*\{\s*downloadsPath:\s*browserDownloadsRoot\s*\}/u)
  assert.match(config, /contextOptions:\s*\{\s*reducedMotion:\s*'reduce'\s*\}/u)
  const spec = source('frontend/e2e/phase8a/manuscript-productization.spec.mjs')
})

test('Phase 8A page event ledger accepts only the exact linked corrupt failures and emits safe diagnostics', async () => {
  const { assertPageEventLedger } = await import('../../frontend/e2e/run-phase8a.mjs')
  const linked = {
    consoleErrors: 4, pageErrors: 0, requestFailures: 0,
    summaries: [
      { kind: 'console-error', category: 'resource-status', source: 'manuscript-chapter', status: 500 },
      { kind: 'console-error', category: 'resource-status', source: 'novel-download-chapter', status: 500 },
      { kind: 'console-error', category: 'resource-status', source: 'novel-download-volume', status: 500 },
      { kind: 'console-error', category: 'resource-status', source: 'novel-download-book', status: 500 },
    ],
    responses: [
      { method: 'GET', route: 'manuscript-chapter', stage: 'corrupt', status: 500 },
      { method: 'GET', route: 'novel-download-chapter', stage: 'corrupt', status: 500 },
      { method: 'GET', route: 'novel-download-volume', stage: 'corrupt', status: 500 },
      { method: 'GET', route: 'novel-download-book', stage: 'corrupt', status: 500 },
    ],
  }
  assert.deepEqual(assertPageEventLedger(JSON.stringify(linked)), {
    consoleKnownLinked: 4, consoleUnexpected: 0, pageErrors: 0, requestFailures: 0,
  })
  for (const mutate of [
    value => value.responses.pop(),
    value => value.responses.reverse(),
    value => value.summaries.push(value.summaries[0]),
  ]) {
    const invalid = structuredClone(linked)
    mutate(invalid)
    assert.throws(() => assertPageEventLedger(JSON.stringify(invalid)), /page event ledger/u)
  }
  const nonzero = JSON.stringify({
    ...linked, pageErrors: 1, summaries: [...linked.summaries, { kind: 'page-error' }],
  })
  let failure
  try { assertPageEventLedger(nonzero) } catch (error) { failure = error }
  assert.match(failure.message, /page event ledger/u)
  const unsafe = nonzero.replace('page-error', 'https://secret.example/?token=never-echo')
  try { assertPageEventLedger(unsafe) } catch (error) { failure = error }
  assert.doesNotMatch(failure.message, /secret|token|https?:/iu)
})

test('Phase 8A request failure summaries expose only closed safe categories', async () => {
  const { summarizeRequestFailure } = await import('../../frontend/e2e/phase8a/page-events.mjs')
  const secret = '8a000000-0000-4000-8000-000000000003'
  const request = {
    method: () => 'GET',
    url: () => `http://127.0.0.1:43123/api/projects/${secret}/manuscript/chapters/99?token=never-echo`,
    failure: () => ({ errorText: 'net::ERR_ABORTED secret raw failure' }),
  }
  assert.deepEqual(summarizeRequestFailure(request, 'corrupt'), {
    kind: 'request-failed', stage: 'corrupt', method: 'GET',
    route: 'manuscript-chapter', failureType: 'aborted',
  })
  const encoded = JSON.stringify(summarizeRequestFailure(request, 'corrupt'))
  assert.doesNotMatch(encoded, /8a000000|99|token|never-echo|secret|ERR_ABORTED|127\.0\.0\.1|43123/iu)
  assert.deepEqual(summarizeRequestFailure({
    method: () => 'TRACE',
    url: () => 'https://outside.example/private?credential=never-echo',
    failure: () => ({ errorText: 'net::ERR_CONNECTION_RESET private detail' }),
  }, 'untrusted-stage'), {
    kind: 'request-failed', stage: 'unknown', method: 'OTHER',
    route: 'not-owned', failureType: 'connection',
  })
})

test('Phase 8A reduced-motion parser treats infinite iteration as motion', async () => {
  const { parseIterationCount } = await import('../../frontend/e2e/phase8a/accessibility.mjs')
  assert.equal(parseIterationCount('infinite'), Number.POSITIVE_INFINITY)
  assert.equal(parseIterationCount('2'), 2)
})

test('Phase 8A assertion failures are classified without exposing report content', async () => {
  const { classifyBoundedCause, classifyBrowserFailure } = await import('../../frontend/e2e/run-phase8a.mjs')
  const owned = mkdtempSync(path.join(os.tmpdir(), 'phase8a-report-'))
  const report = path.join(owned, 'result.json')
  try {
    assert.equal(classifyBrowserFailure(report, new Error('Phase8A browser test process exited with status 1')), 'report-missing-bounded-exit-status')
    writeFileSync(report, '{invalid')
    assert.equal(classifyBrowserFailure(report, new Error('Phase8A browser test process failed to start SECRET')), 'report-invalid-json-bounded-start')
    writeFileSync(report, JSON.stringify({ suites: [] }))
    assert.equal(classifyBrowserFailure(report, new Error('Phase8A browser test deadline exceeded SECRET')), 'report-no-errors-bounded-deadline')
    writeFileSync(report, JSON.stringify({ errors: [{ message: 'SECRET opaque reporter failure' }] }))
    assert.equal(classifyBrowserFailure(report, new Error('SECRET raw bounded failure')), 'report-unmapped-error-bounded-other')
    assert.deepEqual([
      new Error('process exited with status 7'), new Error('process failed to start'),
      new Error('deadline exceeded'), new Error('owned service exited before requested stop'),
      new Error('process log scan failed'), Object.assign(new Error('cancelled'), { name: 'AbortError' }),
      new Error('SECRET raw other'),
    ].map(classifyBoundedCause), [
      'exit-status', 'start', 'deadline', 'service', 'log-scan', 'abort', 'other',
    ])
    writeFileSync(report, JSON.stringify({ errors: [{
      message: 'phase8a-page-events-console-1-page-0-request-0-first-resource-status-500',
      location: { file: 'manuscript-productization.spec.mjs', line: 47, column: 4 },
    }] }))
    assert.equal(classifyBrowserFailure(report), 'phase8a-page-events-console-1-page-0-request-0-first-resource-status-500@47')
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

function phase8aHarness(scenario) {
  const processTarget = new EventEmitter()
  const resources = { childProcesses: 0, ports: 0, tempRoots: 0, downloads: 0, schemas: 0 }
  const environment = {}
  let port = 42000
  let serverStarts = 0
  let sequence = 0
  const commandCalls = []
  let firstServerSequence = Number.POSITIVE_INFINITY
  const roots = {
    artifactRoot: 'C:\\owned\\artifacts', downloadRoot: 'C:\\owned\\downloads',
    browserDownloadsRoot: 'C:\\owned\\browser-downloads', backendPath: 'C:\\owned\\backend.py',
    denyProxyPath: 'C:\\owned\\deny.cjs', viteConfigPath: 'C:\\owned\\vite.mjs',
    resultPath: 'C:\\owned\\result.json', outboundLedgerPath: 'C:\\owned\\outbound.log',
    denyProxyLedgerPath: 'C:\\owned\\deny.log',
    pageEventLedgerPath: 'C:\\owned\\page-events.json',
  }
  const dependencies = {
    validateTestEnvironment() {},
    createDatabaseName: () => 'novel_creator_test_0123456789abcdef0123456789abcdef',
    assertDatabaseName() {},
    createOwnedRoot() { resources.tempRoots += 1; return 'C:\\owned' },
    createRoots() { resources.downloads += 2; return roots },
    async reserveLocalPort() {
      resources.ports += 1
      const value = port++
      let released = false
      return { port: value, async release() { if (!released) { released = true; resources.ports -= 1 } } }
    },
    startOwnedServer() {
      firstServerSequence = Math.min(firstServerSequence, sequence++)
      serverStarts += 1
      if (scenario === 'child-startup-failure' && serverStarts === 1) throw new Error('child startup failed')
      resources.childProcesses += 1
      return { child: {}, state: {}, stopped: false }
    },
    async stopOwnedServer(server) {
      if (!server.stopped) { server.stopped = true; resources.childProcesses -= 1 }
    },
    async waitForOwnedServer() {},
    readOwnedText(target) {
      if (target === roots.pageEventLedgerPath) return JSON.stringify({
        consoleErrors: 4, pageErrors: 0, requestFailures: 0,
        summaries: [
          { kind: 'console-error', category: 'resource-status', source: 'manuscript-chapter', status: 500 },
          { kind: 'console-error', category: 'resource-status', source: 'novel-download-chapter', status: 500 },
          { kind: 'console-error', category: 'resource-status', source: 'novel-download-volume', status: 500 },
          { kind: 'console-error', category: 'resource-status', source: 'novel-download-book', status: 500 },
        ],
        responses: [
          { method: 'GET', route: 'manuscript-chapter', stage: 'corrupt', status: 500 },
          { method: 'GET', route: 'novel-download-chapter', stage: 'corrupt', status: 500 },
          { method: 'GET', route: 'novel-download-volume', stage: 'corrupt', status: 500 },
          { method: 'GET', route: 'novel-download-book', stage: 'corrupt', status: 500 },
        ],
      })
      return ''
    },
    async runBoundedOwnedCommand(command, args, _options, settings) {
      commandCalls.push({ command, args: [...args], label: settings.label, sequence: sequence++ })
      if (settings.label === 'Phase8A database preparation') resources.schemas += 1
      if (settings.label === 'Phase8A database cleanup') {
        if (scenario === 'SIGINT' || scenario === 'SIGTERM') {
          assert.equal(settings.signal, undefined)
          await realBoundedCommand(process.execPath, ['-e', 'process.exit(0)'], { stdio: 'ignore' }, {
            label: 'real injected schema cleanup', timeoutMs: 5_000, settleMs: 500,
            stopTimeoutMs: 1_000,
          })
        }
        resources.schemas -= 1
      }
      if (settings.label !== 'Phase8A browser test') return { status: 0 }
      if (scenario === 'assertion-failure') throw new Error('browser assertion failed')
      if (scenario === 'SIGINT' || scenario === 'SIGTERM') {
        processTarget.emit(scenario)
        assert.equal(settings.signal.aborted, true)
        throw settings.signal.reason
      }
      return { status: 0 }
    },
    cleanupRoot() { resources.tempRoots = 0; resources.downloads = 0 },
    assertDatabaseResidue() {},
    async runOwnedProductLifecycle(configuration) {
      const reservations = []
      const servers = []
      let root = null
      let database = null
      const lifecycle = {
        setRoot(value) { root = value; return value },
        setDatabase(value) { database = value; return value },
        registerReservation(value) { reservations.push(value); return value },
        registerServer(value) { servers.push(value); return value },
        async releaseReservation(value) { await configuration.releaseReservation(value) },
      }
      let primary = null
      try { await configuration.body(lifecycle) } catch (error) { primary = error }
      const cleanup = []
      for (const server of [...servers].reverse()) {
        try { await configuration.stopServer(server) } catch (error) { cleanup.push(error) }
      }
      for (const reservation of reservations) {
        try { await configuration.releaseReservation(reservation) } catch (error) { cleanup.push(error) }
      }
      if (database) {
        try { await configuration.dropDatabase(database) } catch (error) { cleanup.push(error) }
      }
      if (root) {
        try { await configuration.removeRoot(root) } catch (error) { cleanup.push(error) }
      }
      const failures = [primary, ...cleanup].filter(Boolean)
      if (failures.length === 1) throw failures[0]
      if (failures.length > 1) throw new AggregateError(failures)
    },
  }
  return {
    dependencies, environment, logs: [], processTarget, resources, commandCalls,
    get firstServerSequence() { return firstServerSequence },
  }
}

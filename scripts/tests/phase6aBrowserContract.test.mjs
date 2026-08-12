import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import os from 'node:os'

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
  assert.match(config, /bypass:\s*allowedOrigins\.map/u)
  const fixture = source('backend/scripts/prepare_phase6a_browser_db.py')
  assert.doesNotMatch(fixture, /from backend\.tests|import backend\.tests/u)
  assert.doesNotMatch(fixture, /from backend\.routers|finalization\._(?:service|atomic_service)/u)
  assert.doesNotMatch(fixture, /hashlib|\bsha256\b|canonical_hash|build_projection_bundle/u)
  assert.doesNotMatch(fixture, /INSERT\s+INTO\s+provider_profiles/iu)
  assert.match(fixture, /ProviderCreateCommand, ProviderProfileService, SqlProviderProfileRepository/u)
  assert.match(fixture, /base_url="http:\/\/127\.0\.0\.1:1\/v1"/u)
  assert.ok(fixture.indexOf('await providers.create(') < fixture.indexOf('await projects.create('))
  assert.match(fixture, /from backend\.domain\.chapter_outlines import EditableChapterOutlineContent/u)
  assert.match(fixture, /return EditableChapterOutlineContent\.model_validate\(/u)
  for (const field of [
    'worldRules', 'coreCast', 'factions', 'longTermConflicts',
    'relationshipDynamics', 'continuityGuardrails', 'openDesignQuestions',
  ]) {
    assert.match(fixture, new RegExp(`"${field}": \\(item\\(`, 'u'), field)
  }
  const spec = source('frontend/e2e/phase6a/finalized-novel-download.spec.mjs')
  assert.match(spec, /observeRuntime\(context,/u)
  assert.ok(spec.indexOf('observeRuntime(context') < spec.indexOf('page.goto('))
  const observer = source('frontend/e2e/phase6a/runtime-observer.mjs')
  for (const marker of [
    "context.on('page'", "page.on('pageerror'", "context.on(event, listener)",
    "page.on('download'", "page.on('close'",
    'pendingRequests', 'listenerCount', 'consoleNetworkErrors',
    'consoleBrowserFrameworkErrors', 'consoleAppExplicitErrors', 'consoleUnknownErrors',
    'consoleAdjacentOwnedRequests', 'consoleAdjacentPopupCloses', 'consoleAdjacentDownloads',
    'networkOwnedStatus2xx', 'networkOwnedStatus3xx', 'networkOwnedStatus4xx',
    'networkOwnedStatus5xx', 'networkOwnedRequestFailed', 'networkOwnedCancelled',
    'networkOwned4xxDocument', 'networkOwned4xxScript', 'networkOwned4xxStylesheet',
    'networkOwned4xxImage', 'networkOwned4xxFont', 'networkOwned4xxFetch',
    'networkOwned4xxXhr', 'networkOwned4xxOther',
  ]) assert.equal(observer.includes(marker), true, marker)
  assert.doesNotMatch(source('frontend/e2e/run-phase6a.mjs'), /provider.*(?:url|key)|mysqld/iu)
})

test('Phase 6A root cleanup retries fixed categories and reports safe counts', async () => {
  const { classifyBrowserFailure, cleanupRoot, safeCliFailureSummary } = await import('../../frontend/e2e/run-phase6a.mjs')
  const retryKey = {
    portRelease: 'portReleaseRetries', rootAudit: 'rootAuditRetries', rootRemoval: 'rootRemovalRetries',
  }
  const createOwned = () => {
    const owned = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase6a-'))
    const roots = {
      outboundLedgerPath: path.join(owned, 'outbound-ledger.log'),
      denyProxyLedgerPath: path.join(owned, 'deny-proxy.log'),
      downloadRoot: path.join(owned, 'downloads'),
    }
    mkdirSync(roots.downloadRoot); writeFileSync(roots.outboundLedgerPath, ''); writeFileSync(roots.denyProxyLedgerPath, '')
    return { owned, roots }
  }
  for (const category of Object.keys(retryKey)) {
    const { owned, roots } = createOwned(); let attempts = 0
    const fault = () => { attempts += 1; if (attempts === 1) throw new Error(`SECRET-${category}`) }
    const retries = await cleanupRoot(owned, roots, [44123], {
      waitForPortReleaseImpl: async () => { if (category === 'portRelease') fault() },
      auditRootImpl: async () => { if (category === 'rootAudit') fault() },
      removeOwnedRootImpl(target) { if (category === 'rootRemoval') fault(); rmSync(target, { recursive: true }) },
    })
    assert.equal(attempts, 2, category)
    assert.deepEqual(retries, {
      portReleaseRetries: category === 'portRelease' ? 1 : 0,
      rootAuditRetries: category === 'rootAudit' ? 1 : 0,
      rootRemovalRetries: category === 'rootRemoval' ? 1 : 0,
    })
    assert.equal(existsSync(owned), false)
  }
  for (const category of Object.keys(retryKey)) {
    const { owned, roots } = createOwned(); let attempts = 0
    const permanent = () => { attempts += 1; throw new Error(`SECRET-${category}-${owned}`) }
    try {
      await assert.rejects(cleanupRoot(owned, roots, [44123], {
        waitForPortReleaseImpl: async () => { if (category === 'portRelease') permanent() },
        auditRootImpl: async () => { if (category === 'rootAudit') permanent() },
        removeOwnedRootImpl(target) { if (category === 'rootRemoval') permanent(); rmSync(target, { recursive: true }) },
      }), error => {
        assert.equal(attempts, 2, category)
        const summary = safeCliFailureSummary(error)
        assert.deepEqual(JSON.parse(summary), {
          firstStage: 'root-cleanup', errorCount: 1, browserCause: null,
          cleanupCategoryCounts: {
            portRelease: category === 'portRelease' ? 1 : 0,
            rootAudit: category === 'rootAudit' ? 1 : 0,
            rootRemoval: category === 'rootRemoval' ? 1 : 0,
          },
          cleanupRetryCounts: {
            portReleaseRetries: category === 'portRelease' ? 1 : 0,
            rootAuditRetries: category === 'rootAudit' ? 1 : 0,
            rootRemovalRetries: category === 'rootRemoval' ? 1 : 0,
          },
        })
        assert.equal(summary.includes('SECRET'), false); assert.equal(summary.includes(owned), false)
        return true
      })
    } finally { if (existsSync(owned)) rmSync(owned, { recursive: true, force: true }) }
  }

  const reportRoot = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase6a-report-'))
  const reportPath = path.join(reportRoot, 'result.json')
  try {
    const writeReport = error => writeFileSync(reportPath, JSON.stringify({
      config: { timeout: 30000 },
      suites: [{ specs: [{ tests: [{ results: [{ errors: [error] }] }] }] }],
    }))
    writeReport({
      message: 'Error: phase6a-runtime-consoleNetworkErrors-count-2-adjacent-ownedRequest-1-popupClose-0-download-1-owned-status2xx-0-status3xx-0-status4xx-1-status5xx-0-requestfailed-0-cancelled-0-4xx-document-0-script-0-stylesheet-0-image-1-font-0-fetch-0-xhr-0-other-0',
      location: { file: 'finalized-novel-download.spec.mjs', line: 83, column: 3 },
    })
    assert.equal(classifyBrowserFailure(reportPath), 'phase6a-runtime-consoleNetworkErrors-count-2-adjacent-ownedRequest-1-popupClose-0-download-1-owned-status2xx-0-status3xx-0-status4xx-1-status5xx-0-requestfailed-0-cancelled-0-4xx-document-0-script-0-stylesheet-0-image-1-font-0-fetch-0-xhr-0-other-0')
    writeReport({
      message: 'Expected element to be visible',
      location: { file: 'finalized-novel-download.spec.mjs', line: 76, column: 3 },
    })
    assert.equal(classifyBrowserFailure(reportPath), 'assertion@76')
    writeReport({
      message: 'Test timeout of 30000ms exceeded.',
      location: { file: 'finalized-novel-download.spec.mjs', line: 44, column: 3 },
    })
    assert.equal(classifyBrowserFailure(reportPath), 'timeout@44')
  } finally {
    rmSync(reportRoot, { recursive: true, force: true })
  }
  assert.doesNotMatch(source('frontend/e2e/run-phase6a.mjs'), /JSON\.stringify\(report\)/u)
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

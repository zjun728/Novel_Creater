import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'


const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
)


function readWorkspaceFile(relativePath) {
  return readFileSync(path.join(repositoryRoot, relativePath), 'utf8')
}


test('Phase 2 exposes one formal explicit browser entrypoint', () => {
  const rootPackage = JSON.parse(readWorkspaceFile('package.json'))
  const frontendPackage = JSON.parse(readWorkspaceFile('frontend/package.json'))

  assert.equal(rootPackage.scripts['test:browser'], 'node scripts/run-tests.mjs browser-phase2c')
  assert.equal(
    rootPackage.scripts['test:browser:phase2'],
    'node scripts/run-tests.mjs browser-phase2',
  )
  assert.equal(frontendPackage.scripts['test:e2e'], 'node e2e/run-phase2c.mjs')
  assert.equal(frontendPackage.scripts['test:e2e:phase2'], 'node e2e/run-phase2.mjs')
})


test('dispatcher validates Phase 2 MySQL authority before starting only its runner', () => {
  const calls = []
  const completeEnvironment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }

  assert.equal(runSuites(['browser-phase2'], {
    rootDirectory: repositoryRoot,
    environment: completeEnvironment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  }), 0)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].args, ['frontend/e2e/run-phase2.mjs'])
  assert.equal(calls[0].options.shell, false)

  calls.length = 0
  const incompleteEnvironment = { ...completeEnvironment }
  delete incompleteEnvironment.TEST_MYSQL_PASSWORD
  assert.equal(runSuites(['browser-phase2'], {
    rootDirectory: repositoryRoot,
    environment: incompleteEnvironment,
    stderr: { write() {} },
    spawnSyncImpl() {
      calls.push('spawned')
      return { status: 0 }
    },
  }), 2)
  assert.deepEqual(calls, [])
})


test('Phase 2 runner owns one exact spec and fails closed before allocating resources', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const expected = ['e2e/phase2-creative-foundation.spec.ts']

  assert.deepEqual(runner.FORMAL_SPECS, expected)
  assert.deepEqual(runner.resolveCommandLineSpecs([]), expected)
  assert.throws(
    () => runner.resolveCommandLineSpecs(['e2e/arbitrary.spec.ts']),
    /does not accept spec paths/iu,
  )

  const allocations = []
  await assert.rejects(runner.runPhase2({
    environment: {
      TEST_MYSQL_HOST: '127.0.0.1',
      TEST_MYSQL_PORT: '33060',
      TEST_MYSQL_USER: 'root',
    },
    databaseNameFactory() { allocations.push('database') },
    ownedRootFactory() { allocations.push('root') },
    portReservationFactory() { allocations.push('port') },
  }), /TEST_MYSQL_PASSWORD/u)
  assert.deepEqual(allocations, [])
})


test('Phase 2 runner composes the shared lifecycle and observers', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2.mjs')

  assert.match(source, /from '\.\/support\/product-runner\.mjs'/u)
  assert.match(source, /\brunOwnedProductLifecycle\b/u)
  assert.match(source, /\brunBoundedOwnedCommand\b/u)
  assert.match(source, /\bstartOwnedServer\b/u)
  assert.match(source, /\bstopOwnedServer\b/u)
  assert.match(source, /from '\.\/runtime-observer\.mjs'/u)
  assert.match(source, /\bruntimeSensitiveValues\b/u)
  assert.match(source, /from '\.\/server-log-observer\.mjs'/u)
  assert.match(source, /\bcreateServerLogObserver\b/u)
  assert.match(
    source,
    /backend\.scripts\.prepare_phase2_browser_db/u,
  )
  assert.doesNotMatch(
    source,
    /function\s+(?:runOwnedProductLifecycle|startOwnedServer|stopOwnedServer)\s*\(/u,
  )
})


test('Phase 2 Playwright source is UI-only and uses the runtime observer', () => {
  const entry = 'frontend/e2e/phase2-creative-foundation.spec.ts'
  assertSafeBrowserGraph(entry, relativePath => readWorkspaceFile(relativePath))
  const source = readWorkspaceFile(entry)

  assert.match(source, /\bobserveRuntime\b/u)
  assert.match(source, /\bassertRuntimeEvidenceHealthy\b/u)
  assert.match(
    source,
    /const contractDraftPath = `\/api\/projects\/\$\{projectId\}\/contract-draft`/u,
  )
  assert.match(
    source,
    /assertRuntimeEvidenceHealthy\(evidence,\s*\{[\s\S]*?responseFailureAllowlist:\s*\[\{[\s\S]*?status:\s*404,[\s\S]*?method:\s*'GET',[\s\S]*?pathname:\s*contractDraftPath,[\s\S]*?count:\s*1,[\s\S]*?\}\],[\s\S]*?consoleErrorAllowlist:\s*\[\{[\s\S]*?message:\s*'error: Failed to load resource: the server responded with a status of 404 \(Not Found\)',[\s\S]*?count:\s*1,[\s\S]*?linkedResponseFailure:\s*\{[\s\S]*?status:\s*404,[\s\S]*?method:\s*'GET',[\s\S]*?pathname:\s*contractDraftPath,[\s\S]*?\}[\s\S]*?\}\],[\s\S]*?\}\)/u,
  )
  assert.doesNotMatch(source, /responseFailures:\s*\[\]/u)
  assert.doesNotMatch(source, /consoleErrors:\s*\[\]/u)
  assert.match(source, /\bassertExactWrites\b/u)
  assert.match(source, /\bscanRuntimeEvidence\b/u)
  assert.match(source, /BROWSER_VITE_ORIGIN/u)
  assert.match(source, /BROWSER_BACKEND_ORIGIN/u)
  assert.match(source, /runnerOrigins\.has\(new URL\(entry\.url\)\.origin\)/u)
  assert.match(source, /new URL\(entry\.url\)\.origin === BACKEND_ORIGIN/u)
  assert.match(source, /BROWSER_TRANSCRIPT_SENTINEL/u)
  assert.match(source, /BROWSER_QIDIAN_SNAPSHOT_PATH/u)
  assert.match(source, /BROWSER_QQ_SNAPSHOT_PATH/u)
  assert.match(source, /BROWSER_CORPUS_FILE/u)
  assert.match(source, /BROWSER_RUNTIME_AUDIT_DIAGNOSTIC/u)
  assert.match(source, /\bwriteRuntimeAuditDiagnostic\b/u)
  assert.match(source, /\bpathnameCategory\b/u)
  assert.match(source, /\bhealthErrors\b/u)
  assert.match(source, /\brequestFailureDetails\b/u)
  assert.match(source, /\bapiResponseBodyReadErrorDetails\b/u)
  assert.match(
    source,
    /const evidence = await runtime\.finish\(\)\s+writeRuntimeAuditDiagnostic\(evidence, projectId\)\s+await auditRuntime\(evidence, checkpoints, projectId\)/u,
  )
  assert.match(source, /selectSeed\(page, projectId, '雾港错钟', 3\)/u)
  assert.match(source, /生成创作圣经/u)
  assert.match(source, /FAIL_SAFE/u)
  assert.match(source, /调整未来设计/u)
  assert.match(source, /修订历史/u)
  assert.match(source, /phase_boundary_planning/u)
  assert.match(source, /page\.reload\(/u)
  assert.match(source, /page\.goBack\(/u)
  assert.match(source, /page\.goForward\(/u)
  assert.match(source, /page\.setViewportSize\(/u)
  assert.match(
    source,
    /async function settleNavigationBoundary\(page, runtime\) \{\s+await page\.waitForLoadState\('networkidle'\)\s+await runtime\.settle\(\)\s+\}/u,
  )
  assert.match(
    source,
    /async function verifyNavigationAndPreparation\(page, projectId: string, runtime\)/u,
  )
  assert.match(
    source,
    /async function archiveAndVerifyReadOnly\(page, projectId: string, runtime\)/u,
  )
  assert.equal(
    source.match(/await settleNavigationBoundary\(page, runtime\)/gu)?.length,
    12,
  )
  assert.match(
    source,
    /await verifyNavigationAndPreparation\(page, projectId, runtime\)/u,
  )
  assert.match(
    source,
    /await archiveAndVerifyReadOnly\(page, projectId, runtime\)/u,
  )
  assert.match(source, /归档/u)
  assert.match(source, /此入口已升级或不存在/u)
  assert.doesNotMatch(
    source,
    /page\.request|page\.route|page\.evaluate|\bfetch\s*\(|\baxios\b/u,
  )
})


test('Phase 2 Playwright config is serial, loopback-only, and retains no media', () => {
  const source = readWorkspaceFile('frontend/playwright.phase2.config.ts')

  assert.match(source, /\^http:\\\/\\\/127\\\.0\\\.0\\\.1:\\d\+\$/u)
  assert.match(source, /fullyParallel:\s*false/u)
  assert.match(source, /workers:\s*1/u)
  assert.match(source, /trace:\s*'off'/u)
  assert.match(source, /screenshot:\s*'off'/u)
  assert.match(source, /video:\s*'off'/u)
  assert.match(source, /preserveOutput:\s*'never'/u)
})


test('Phase 2 browser progress ledger is closed and contains no diagnostics', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')

  assert.deepEqual(
    runner.verifyBrowserStepLedger(
      'library-visible\nproject-created\n',
    ),
    [
      'library-visible',
      'project-created',
    ],
  )
  assert.throws(
    () => runner.verifyBrowserStepLedger('library-visible\nsecret=value\n'),
    /progress ledger/iu,
  )
  const fullLedger = runner.ALLOWED_BROWSER_STEPS
    .map(step => `${step}\n`)
    .join('')
  assert.deepEqual(
    runner.verifyBrowserStepLedger(fullLedger, { requireComplete: true }),
    runner.ALLOWED_BROWSER_STEPS,
  )
  assert.throws(
    () => runner.verifyBrowserStepLedger(
      'library-visible\nproject-created\n',
      { requireComplete: true },
    ),
    /progress ledger/iu,
  )
  assert.equal(
    runner.renderPhase2CliFailure(
      new Error('Phase 2 browser stopped after corpus-imported'),
    ),
    'Phase 2 browser acceptance failed after corpus-imported.\n',
  )
  assert.equal(
    runner.renderPhase2CliFailure(
      new Error('Phase 2 browser stopped after secret=value'),
    ),
    'Phase 2 browser acceptance failed.\n',
  )
})


test('Phase 2 runtime audit diagnostics expose only fixed safe categories', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const diagnostic = JSON.stringify({
    responseFailures: [
      {
        status: 404,
        method: 'GET',
        pathnameCategory: 'contract-draft',
        count: 2,
      },
    ],
    consoleErrors: [
      { category: 'resource-404', count: 1 },
      { category: 'ui-error-boundary', count: 1 },
    ],
    healthErrors: [
      { category: 'page-error', count: 1 },
      { category: 'request-failure', count: 2 },
    ],
    requestFailureDetails: [
      {
        method: 'GET',
        pathCategory: 'assets',
        errorCategory: 'cancelled',
        count: 2,
      },
    ],
    apiResponseBodyReadErrorDetails: [
      {
        method: 'GET',
        status: 200,
        pathCategory: 'project',
        errorCategory: 'protocol-no-resource',
        count: 1,
      },
    ],
  })

  assert.equal(
    runner.verifyRuntimeAuditDiagnostic(diagnostic),
    'response[404:GET:contract-draft=2];'
      + 'console[resource-404=1,ui-error-boundary=1];'
      + 'health[page-error=1,request-failure=2];'
      + 'requestFailures[GET:assets:cancelled=2];'
      + 'apiBodyReadErrors[GET:200:project:protocol-no-resource=1]',
  )
  assert.throws(
    () => runner.verifyRuntimeAuditDiagnostic(JSON.stringify({
      responseFailures: [{
        status: 404,
        method: 'GET',
        pathnameCategory: '/api/projects/private/contract-draft',
        count: 1,
      }],
      consoleErrors: [],
      healthErrors: [],
      requestFailureDetails: [],
      apiResponseBodyReadErrorDetails: [],
    })),
    /audit diagnostic/iu,
  )
  assert.throws(
    () => runner.verifyRuntimeAuditDiagnostic(JSON.stringify({
      responseFailures: [],
      consoleErrors: [{
        category: 'resource-404',
        count: 1,
        message: 'raw console text',
      }],
      healthErrors: [],
      requestFailureDetails: [],
      apiResponseBodyReadErrorDetails: [],
    })),
    /audit diagnostic/iu,
  )

  const error = new Error('Phase 2 browser stopped after not-found-visible')
  error.phase2AuditDiagnostic = diagnostic
  assert.equal(
    runner.renderPhase2CliFailure(error),
    'Phase 2 browser acceptance failed after not-found-visible; '
      + 'response[404:GET:contract-draft=2];'
      + 'console[resource-404=1,ui-error-boundary=1];'
      + 'health[page-error=1,request-failure=2];'
      + 'requestFailures[GET:assets:cancelled=2];'
      + 'apiBodyReadErrors[GET:200:project:protocol-no-resource=1].\n',
  )
  assert.throws(
    () => runner.verifyRuntimeAuditDiagnostic(JSON.stringify({
      responseFailures: [],
      consoleErrors: [],
      healthErrors: [],
      requestFailureDetails: [{
        method: 'GET',
        pathCategory: 'assets',
        errorCategory: 'cancelled',
        count: 1,
        errorText: 'raw browser error',
      }],
      apiResponseBodyReadErrorDetails: [],
    })),
    /audit diagnostic/iu,
  )
})


test('Phase 2 runner scans private gateway and transcript sentinels', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2.mjs')

  assert.match(source, /BROWSER_PRIVATE_PROVIDER_URL:\s*gatewayUrl/u)
  assert.match(source, /BROWSER_TRANSCRIPT_SENTINEL/u)
  assert.match(
    source,
    /\.\.\.runtimeSensitiveValues\(environments\.sensitiveController\)/u,
  )
  assert.match(
    source,
    /environments\.sensitiveController\.BROWSER_TRANSCRIPT_SENTINEL/u,
  )
})


test('Phase 2 runner owns snapshots and validates the exact fake gateway calls', async () => {
  const runner = await import('../../frontend/e2e/run-phase2.mjs')
  const source = readWorkspaceFile('frontend/e2e/run-phase2.mjs')

  assert.match(source, /qidian-public-snapshot\.json/u)
  assert.match(source, /qq-public-snapshot\.json/u)
  assert.match(source, /BROWSER_QIDIAN_SNAPSHOT_PATH/u)
  assert.match(source, /BROWSER_QQ_SNAPSHOT_PATH/u)
  assert.match(source, /BROWSER_FAKE_COUNTER_PATH/u)
  assert.match(source, /Generate one complete creation Bible/u)
  assert.match(source, /Rank only the supplied eligible asset and corpus candidates/u)
  assert.match(source, /bible-success/u)
  assert.match(source, /bible-failure/u)
  assert.doesNotMatch(source, /appendFileSync\([^\n]*(?:messages|body|content)/u)

  assert.deepEqual(
    runner.verifyGatewayCounterLedger(
      'asset-ranking\nasset-ranking\nbible-success\nbible-failure\n',
    ),
    {
      'asset-ranking': 2,
      'bible-success': 1,
      'bible-failure': 1,
    },
  )
  for (const invalid of [
    '',
    'asset-ranking\nbible-success\nbible-failure\n',
    'asset-ranking\nasset-ranking\nbible-success\n',
    'asset-ranking\nasset-ranking\nbible-success\nbible-failure\nunknown\n',
  ]) {
    assert.throws(
      () => runner.verifyGatewayCounterLedger(invalid),
      /gateway call ledger/iu,
    )
  }
})

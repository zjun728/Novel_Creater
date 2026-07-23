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
  assert.match(source, /\bscanRuntimeEvidence\b/u)
  assert.match(source, /BROWSER_VITE_ORIGIN/u)
  assert.match(source, /BROWSER_BACKEND_ORIGIN/u)
  assert.match(source, /runnerOrigins\.has\(new URL\(entry\.url\)\.origin\)/u)
  assert.match(source, /new URL\(entry\.url\)\.origin === BACKEND_ORIGIN/u)
  assert.match(source, /BROWSER_TRANSCRIPT_SENTINEL/u)
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
      'library-navigation-start\nlibrary-navigation-finished\n',
    ),
    [
      'library-navigation-start',
      'library-navigation-finished',
    ],
  )
  assert.throws(
    () => runner.verifyBrowserStepLedger('library-navigation-start\nsecret=value\n'),
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
      'library-navigation-start\nlibrary-navigation-finished\n',
      { requireComplete: true },
    ),
    /progress ledger/iu,
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

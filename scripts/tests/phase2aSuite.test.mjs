import assert from 'node:assert/strict'
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { PassThrough } from 'node:stream'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'


const scriptsDirectory = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const repositoryRoot = path.dirname(scriptsDirectory)
const runnerModule = '../../frontend/e2e/run-phase2a.mjs'
const TEST_ENVIRONMENT = Object.freeze({
  TEST_MYSQL_HOST: '127.0.0.1',
  TEST_MYSQL_PORT: '33060',
  TEST_MYSQL_USER: 'root',
  TEST_MYSQL_PASSWORD: 'phase2a-test-password',
})


function readWorkspaceFile(relativePath) {
  return readFileSync(path.join(repositoryRoot, relativePath), 'utf8')
}

async function runnerRun({ ownedRoot, portReservationFactory }) {
  const runner = await import(runnerModule)
  return runner.runPhase2A({
    environment: TEST_ENVIRONMENT,
    databaseNameFactory: () => (
      'novel_creator_test_0123456789abcdef0123456789abcdef'
    ),
    ownedRootFactory: () => ownedRoot,
    portReservationFactory,
  })
}


test('Phase 2A exposes one explicit root build and browser command', () => {
  const rootPackage = JSON.parse(readWorkspaceFile('package.json'))
  const frontendPackage = JSON.parse(readWorkspaceFile('frontend/package.json'))

  assert.equal(rootPackage.scripts.build, 'npm --prefix frontend run build')
  assert.equal(
    rootPackage.scripts['test:browser:phase2a'],
    'node scripts/run-tests.mjs browser-phase2a',
  )
  assert.equal(
    frontendPackage.scripts['test:e2e:phase2a'],
    'node e2e/run-phase2a.mjs',
  )
  assert.equal(frontendPackage.scripts['test:e2e:m2'], undefined)
})


test('Phase 2A runner owns one exact closed formal spec', async () => {
  const runner = await import(runnerModule)
  const expected = ['e2e/phase2a-assets-settings.spec.ts']

  assert.deepEqual(runner.FORMAL_SPECS, expected)
  assert.deepEqual(runner.resolveCommandLineSpecs([]), expected)
  assert.deepEqual(runner.validateSpecs(expected), expected)
  assert.throws(
    () => runner.resolveCommandLineSpecs(['e2e/phase2c-contract.spec.ts']),
    /does not accept spec paths/i,
  )
  assert.throws(
    () => runner.validateSpecs(['e2e/phase2c-contract.spec.ts']),
    /formal|spec/i,
  )
  assert.throws(
    () => runner.validateSpecs([...expected, ...expected]),
    /formal|spec/i,
  )
})


test('Phase 2A Playwright source is semantic UI only and has no shadow network writes', () => {
  const entry = 'frontend/e2e/phase2a-assets-settings.spec.ts'
  assertSafeBrowserGraph(entry, relativePath => readWorkspaceFile(relativePath))

  const source = readWorkspaceFile(entry)
  assert.doesNotMatch(source, /page\.(?:request|route)\b/u)
  assert.doesNotMatch(source, /\bfetch\s*\(/u)
  assert.doesNotMatch(source, /\baxios\b/u)
  assert.doesNotMatch(source, /allowMissingResponse/u)
  assert.match(source, /assertExactWrites\s*\(/u)
  assert.match(source, /scanRuntimeEvidence\s*\(/u)
  assert.match(source, /confirmPermanentDelete/u)
  assert.match(source, /expect\(deleteRequests\)\.toHaveLength\(1\)/u)
  assert.doesNotMatch(source, /net::ERR_ABORTED/u)
  const confirmIndex = source.indexOf(
    "await deleteDialog.getByRole('button', { name: '确认永久删除', exact: true }).click()",
  )
  const settledIndex = source.indexOf(
    'await expect(corpusDrawer).toBeHidden()',
    confirmIndex,
  )
  const navigationIndex = source.indexOf(
    "await page.goto('/settings/application')",
    confirmIndex,
  )
  assert.ok(confirmIndex >= 0)
  assert.ok(settledIndex > confirmIndex)
  assert.ok(navigationIndex > settledIndex)
  const backIndex = source.indexOf('await page.goBack()')
  const backSettledIndex = source.indexOf(
    "await page.waitForLoadState('networkidle')",
    backIndex,
  )
  const forwardIndex = source.indexOf('await page.goForward()', backIndex)
  assert.ok(backIndex >= 0)
  assert.ok(backSettledIndex > backIndex)
  assert.ok(forwardIndex > backSettledIndex)
  assert.match(source, /page\.locator\('\.drawer-alert'\).*toHaveCount\(0\)/u)
  assert.match(
    source,
    /method:\s*'DELETE'[\s\S]*?statuses:\s*\[204\][\s\S]*?count:\s*1/u,
  )
  assert.match(source, /BROWSER_VITE_ORIGIN/u)
  assert.match(source, /BROWSER_BACKEND_ORIGIN/u)
  assert.match(source, /checkpointSurfaces/u)
  assert.match(source, /page\.locator\('body'\)\.innerText\(\)/u)
  assert.match(source, /evidence\.responses\.every/u)
  assert.match(source, /runnerOrigins\.has\(new URL\(entry\.url\)\.origin\)/u)
  assert.doesNotMatch(source, /new URL\(entry\.url\)\.hostname/u)
  assert.doesNotMatch(source, /\[\^\/\]\+/u)
  assert.doesNotMatch(source, /page\.screenshot\s*\(/u)
})


test('Phase 2A config is serial, local-only, bounded, and disables media retention', () => {
  const source = readWorkspaceFile('frontend/playwright.phase2a.config.ts')

  assert.match(source, /fullyParallel:\s*false/u)
  assert.match(source, /workers:\s*1/u)
  assert.match(source, /127\\?\.0\\?\.0\\?\.1/u)
  assert.match(source, /trace:\s*'off'/u)
  assert.match(source, /screenshot:\s*'off'/u)
  assert.match(source, /video:\s*'off'/u)
  assert.match(source, /preserveOutput:\s*'never'/u)
  assert.match(source, /BROWSER_ARTIFACT_ROOT/u)
  assert.match(source, /BROWSER_CORPUS_ROOT_SENTINEL/u)
  assert.doesNotMatch(source, /\.\.\/output\/playwright/u)
  assert.doesNotMatch(source, /retain-on-failure|only-on-failure/u)
  assert.match(source, /phase2a-test-results/u)
})


test('Phase 2A runner fails closed without explicit test MySQL authority', async () => {
  const runner = await import(runnerModule)
  const environment = { ...TEST_ENVIRONMENT }
  delete environment.TEST_MYSQL_PASSWORD
  let databaseCalls = 0
  let rootCalls = 0
  let portCalls = 0

  await assert.rejects(
    runner.runPhase2A({
      environment,
      databaseNameFactory() {
        databaseCalls += 1
        return 'novel_creator_test_0123456789abcdef0123456789abcdef'
      },
      ownedRootFactory() {
        rootCalls += 1
        return 'unused'
      },
      portReservationFactory() {
        portCalls += 1
        return Promise.reject(new Error('must not reserve'))
      },
    }),
    /TEST_MYSQL_PASSWORD/u,
  )
  assert.deepEqual({ databaseCalls, rootCalls, portCalls }, {
    databaseCalls: 0,
    rootCalls: 0,
    portCalls: 0,
  })
})

test('Phase 2A runner removes an owned root when corpus preparation fails', async () => {
  const ownedRoot = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase2a-'))
  mkdirSync(path.join(ownedRoot, 'discovery'))
  let portCalls = 0

  try {
    await assert.rejects(
      runnerRun({
        ownedRoot,
        portReservationFactory() {
          portCalls += 1
          return Promise.reject(new Error('port acquisition must not run'))
        },
      }),
      /exist|EEXIST/i,
    )
    assert.equal(existsSync(ownedRoot), false)
    assert.equal(portCalls, 0)
  } finally {
    rmSync(ownedRoot, { recursive: true, force: true })
  }
})

test('Phase 2A runner releases the first port and aggregates cleanup failure when the second acquisition fails', async () => {
  const ownedRoot = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase2a-'))
  let portCalls = 0
  let releaseCalls = 0

  try {
    let rejection
    try {
      await runnerRun({
        ownedRoot,
        portReservationFactory() {
          portCalls += 1
          if (portCalls === 1) {
            return Promise.resolve({
              port: 41_001,
              async release() {
                releaseCalls += 1
                throw new Error('first port cleanup failed')
              },
            })
          }
          return Promise.reject(new Error('second port acquisition failed'))
        },
      })
      assert.fail('runner must reject')
    } catch (error) {
      rejection = error
    }

    const messages = [
      rejection?.message,
      ...(rejection instanceof AggregateError
        ? rejection.errors.map(error => error?.message)
        : []),
    ].join('\n')
    assert.match(messages, /second port acquisition failed/u)
    assert.match(messages, /first port cleanup failed/u)
    assert.equal(releaseCalls, 1)
    assert.equal(existsSync(ownedRoot), false)
  } finally {
    rmSync(ownedRoot, { recursive: true, force: true })
  }
})


test('Phase 2A runner source owns synthetic roots, fake gateway, and no external client', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2a.mjs')

  assert.match(source, /CORPUS_ROOT/u)
  assert.match(source, /MANAGED_CORPUS_ROOT/u)
  assert.match(source, /phase2a-version-1\.txt/u)
  assert.match(source, /phase2a-version-2\.txt/u)
  assert.match(source, /phase2a-referenced\.txt/u)
  assert.match(source, /FakeProviderConnectionGateway/u)
  assert.match(source, /connection_gateway/u)
  assert.match(source, /prepare_product_shell_browser_db/u)
  assert.match(source, /seed_writer_assets/u)
  assert.match(source, /createDelete204AccessObserver/u)
  assert.match(source, /BROWSER_VITE_ORIGIN:\s*viteUrl/u)
  assert.match(source, /BROWSER_BACKEND_ORIGIN:\s*backendUrl/u)
  assert.match(
    source,
    /BROWSER_ARTIFACT_ROOT:\s*path\.join\([\s\S]*?'phase2a-test-results'/u,
  )
  assert.match(source, /exactly one corpus DELETE 204/u)
  assert.match(source, /access_log=True/u)
  assert.match(source, /use_colors.*False/u)
  assert.match(source, /%\(client_addr\)s.*%\(request_line\)s.*%\(status_code\)s/u)
  assert.doesNotMatch(source, /ProviderConnectionGateway\s*\(/u)
  assert.doesNotMatch(source, /httpx\.(?:AsyncClient|Client)/u)
})

test('Phase 2A backend access observer requires exactly one corpus DELETE 204', async () => {
  const { createDelete204AccessObserver } = await import(runnerModule)
  const child = {
    stdout: new PassThrough(),
    stderr: new PassThrough(),
  }
  const observer = createDelete204AccessObserver(child)
  child.stderr.write(
    'INFO: 127.0.0.1:50000 - "DELETE /api/corpus/sources/11111111-1111-4111-8111-111111111111 HT',
  )
  child.stderr.write('TP/1.1" 204 No Content\n')

  assert.deepEqual(observer.finish(), { matchCount: 1 })

  for (const lines of [
    [],
    ['INFO: "DELETE /api/corpus/sources/11111111-1111-4111-8111-111111111111 HTTP/1.1" 200 OK\n'],
    [
      'INFO: "DELETE /api/corpus/sources/11111111-1111-4111-8111-111111111111 HTTP/1.1" 204 No Content\n',
      'INFO: "DELETE /api/corpus/sources/22222222-2222-4222-8222-222222222222 HTTP/1.1" 204 No Content\n',
    ],
  ]) {
    const nextChild = {
      stdout: new PassThrough(),
      stderr: new PassThrough(),
    }
    const next = createDelete204AccessObserver(nextChild)
    for (const line of lines) nextChild.stdout.write(line)
    assert.throws(
      () => next.finish(),
      /DELETE 204.*prefixLines=\d+.*parsedAccessRecords=\d+.*corpusRecords=\d+/i,
    )
  }
})


test('dispatcher validates the exact Phase 2A spec before starting only its runner', () => {
  const calls = []
  let stderr = ''
  const exitCode = runSuites(['browser-phase2a'], {
    environment: TEST_ENVIRONMENT,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
    stderr: { write(chunk) { stderr += chunk } },
  })

  assert.equal(exitCode, 0, stderr)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].args, ['frontend/e2e/run-phase2a.mjs'])
  assert.equal(calls[0].options.shell, false)
  assert.equal(
    existsSync(path.join(repositoryRoot, 'frontend/e2e/m2-settings-assets-corpus.spec.ts')),
    false,
  )
})


test('dispatcher refuses Phase 2A before spawn when test authority is incomplete', () => {
  const environment = { ...TEST_ENVIRONMENT }
  delete environment.TEST_MYSQL_USER
  const calls = []
  let stderr = ''
  const exitCode = runSuites(['browser-phase2a'], {
    environment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
    stderr: { write(chunk) { stderr += chunk } },
  })

  assert.equal(exitCode, 2)
  assert.deepEqual(calls, [])
  assert.match(stderr, /TEST_MYSQL_USER/u)
  assert.doesNotMatch(stderr, new RegExp(TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD, 'u'))
})


test('acceptance report states the real Phase 2A evidence boundary', () => {
  const source = readWorkspaceFile(
    'docs/acceptance/2026-07-18-phase-2a-assets-providers.md',
  )

  for (const required of [
    'Disposable MySQL',
    '真实浏览器',
    'fake connection gateway',
    'Provider/model calls：`0`',
    'Product DB reads/writes：`0/0`',
    '10',
    '64',
    '旧 M2 Settings',
  ]) {
    assert.match(source, new RegExp(required, 'u'))
  }
  assert.doesNotMatch(source, /browser-secret-must-not-leak/u)
  assert.doesNotMatch(source, /private-provider\.example/u)
})

import assert from 'node:assert/strict'
import {
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  realpathSync,
  rmSync,
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph } from '../browser-source-contract.mjs'
import {
  isCommandLineEntrypoint as isDispatcherCommandLineEntrypoint,
  runSuites,
} from '../run-tests.mjs'


const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
)
const runnerModule = '../../frontend/e2e/run-phase2b.mjs'
const DATABASE = 'novel_creator_test_0123456789abcdef0123456789abcdef'
const TEST_ENVIRONMENT = Object.freeze({
  PATH: process.env.PATH || '',
  TEST_MYSQL_HOST: '127.0.0.1',
  TEST_MYSQL_PORT: '33060',
  TEST_MYSQL_USER: 'root',
  TEST_MYSQL_PASSWORD: 'phase2b-test-password',
})


function readWorkspaceFile(relativePath) {
  return readFileSync(path.join(repositoryRoot, relativePath), 'utf8')
}


test('Phase 2B exposes one closed browser entrypoint', () => {
  const rootPackage = JSON.parse(readWorkspaceFile('package.json'))
  const frontendPackage = JSON.parse(readWorkspaceFile('frontend/package.json'))

  assert.equal(
    rootPackage.scripts['test:browser:phase2b'],
    'node scripts/run-tests.mjs browser-phase2b',
  )
  assert.equal(
    frontendPackage.scripts['test:e2e:phase2b'],
    'node e2e/run-phase2b.mjs',
  )
})


test('Phase 2B runner owns exactly one formal spec and rejects CLI paths', async () => {
  const runner = await import(runnerModule)
  const expected = ['e2e/phase2b-market-seeds.spec.ts']

  assert.deepEqual(runner.FORMAL_SPECS, expected)
  assert.deepEqual(runner.resolveCommandLineSpecs([]), expected)
  assert.deepEqual(runner.validateSpecs(expected), expected)
  assert.throws(
    () => runner.resolveCommandLineSpecs(expected),
    /does not accept spec paths/i,
  )
  assert.throws(
    () => runner.validateSpecs(['e2e/phase2a-assets-settings.spec.ts']),
    /formal|spec/i,
  )
})


test('runner recognizes its CLI path through the worktree junction', async () => {
  const runner = await import(runnerModule)
  const apparentPath = path.join(
    repositoryRoot,
    'frontend',
    'e2e',
    'run-phase2b.mjs',
  )
  const canonicalPath = realpathSync(apparentPath)

  assert.equal(
    runner.isCommandLineEntrypoint(apparentPath, canonicalPath),
    true,
  )
})


test('dispatcher recognizes its CLI path through the worktree junction', () => {
  const apparentPath = path.join(repositoryRoot, 'scripts', 'run-tests.mjs')
  assert.equal(
    isDispatcherCommandLineEntrypoint(apparentPath, realpathSync(apparentPath)),
    true,
  )
})


test('formal Phase 2B source is product UI only and declares its runtime audit', () => {
  const entry = 'frontend/e2e/phase2b-market-seeds.spec.ts'
  assertSafeBrowserGraph(entry, relativePath => readWorkspaceFile(relativePath))

  const source = readWorkspaceFile(entry)
  assert.doesNotMatch(source, /page\.(?:request|route)\b/u)
  assert.doesNotMatch(source, /\bfetch\s*\(/u)
  assert.doesNotMatch(source, /\baxios\b/u)
  assert.doesNotMatch(source, /page\.evaluate\s*\(/u)
  assert.match(source, /assertExactWrites\s*\(/u)
  assert.match(source, /scanRuntimeEvidence\s*\(/u)
  assert.match(source, /BROWSER_VITE_ORIGIN/u)
  assert.match(source, /BROWSER_BACKEND_ORIGIN/u)
  assert.match(source, /起点新签榜/u)
  assert.match(source, /QQ 阅读男生人气榜/u)
  assert.match(source, /选定代次 3/u)
  assert.match(source, /保留上次成功 · 最新刷新失败/u)
  assert.match(source, /MARKET_TRANSPORT_FAILED/u)
  assert.match(source, /expectedRefreshFailureURL/u)
  assert.match(source, /status\(\)\)\.toBe\(503\)/u)
  assert.match(source, /已归档 · 只读/u)
  assert.match(source, /确认永久删除/u)
  assert.match(source, /page\.goBack\(\)/u)
  assert.match(source, /page\.goForward\(\)/u)
  assert.match(source, /page\.reload\(\)/u)
  assert.match(source, /setViewportSize/u)
})


test('Phase 2B config is serial, bounded, local-only, and retains no media', () => {
  const source = readWorkspaceFile('frontend/playwright.phase2b.config.ts')

  assert.match(source, /fullyParallel:\s*false/u)
  assert.match(source, /workers:\s*1/u)
  assert.match(source, /127\\?\.0\\?\.0\\?\.1/u)
  assert.match(source, /trace:\s*'off'/u)
  assert.match(source, /screenshot:\s*'off'/u)
  assert.match(source, /video:\s*'off'/u)
  assert.match(source, /preserveOutput:\s*'never'/u)
  assert.match(source, /BROWSER_ARTIFACT_ROOT/u)
  assert.match(source, /phase2b-test-results/u)
})


test('runner fails closed before allocating resources without test MySQL authority', async () => {
  const runner = await import(runnerModule)
  const environment = { ...TEST_ENVIRONMENT }
  delete environment.TEST_MYSQL_PASSWORD
  let databaseCalls = 0
  let rootCalls = 0
  let portCalls = 0

  await assert.rejects(
    runner.runPhase2B({
      environment,
      databaseNameFactory() {
        databaseCalls += 1
        return DATABASE
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


test('runner rejects the product database name before allocating resources', async () => {
  const runner = await import(runnerModule)
  let rootCalls = 0
  let portCalls = 0

  await assert.rejects(
    runner.runPhase2B({
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: () => 'novel_creator',
      ownedRootFactory() {
        rootCalls += 1
        return 'unused'
      },
      portReservationFactory() {
        portCalls += 1
        return Promise.reject(new Error('must not reserve'))
      },
    }),
    /disposable|refusing/i,
  )
  assert.deepEqual({ rootCalls, portCalls }, { rootCalls: 0, portCalls: 0 })
})


test('child environments replace inherited database defaults with one random test DB', async () => {
  const runner = await import(runnerModule)
  const roots = {
    root: String.raw`C:\Temp\phase2b-owned`,
    filesRoot: String.raw`C:\Temp\phase2b-owned\files`,
    qidianPath: String.raw`C:\Temp\phase2b-owned\qidian.json`,
    qqPath: String.raw`C:\Temp\phase2b-owned\qq.json`,
    counterPath: String.raw`C:\Temp\phase2b-owned\counter.log`,
  }
  const environments = runner.buildEnvironments(
    { ...TEST_ENVIRONMENT, MYSQL_DB: 'novel_creator' },
    DATABASE,
    'http://127.0.0.1:41001',
    'http://127.0.0.1:41002',
    'phase2b-nonce',
    roots,
  )

  assert.equal(environments.backend.MYSQL_DB, DATABASE)
  assert.equal(environments.backend.BROWSER_TEST_DATABASE, DATABASE)
  assert.equal(environments.browser.BROWSER_TEST_DATABASE, DATABASE)
  assert.equal('MYSQL_DB' in environments.prepare, false)
  assert.equal(JSON.stringify(environments).includes('"novel_creator"'), false)
})


test('runner removes its owned root when preparation fails before a port is reserved', async () => {
  const runner = await import(runnerModule)
  const ownedRoot = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase2b-'))
  mkdirSync(path.join(ownedRoot, 'files'))
  let portCalls = 0

  try {
    await assert.rejects(
      runner.runPhase2B({
        environment: TEST_ENVIRONMENT,
        databaseNameFactory: () => DATABASE,
        ownedRootFactory: () => ownedRoot,
        portReservationFactory() {
          portCalls += 1
          return Promise.reject(new Error('port must not be reserved'))
        },
      }),
      /exist|EEXIST/i,
    )
    assert.equal(portCalls, 0)
    assert.equal(existsSync(ownedRoot), false)
  } finally {
    rmSync(ownedRoot, { recursive: true, force: true })
  }
})


test('runner source explicitly seeds sources, injects fakes, and delegates lifecycle cleanup', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2b.mjs')

  for (const required of [
    'prepare_product_shell_browser_db',
    'seed_market_sources',
    'MARKET_SCHEDULER_ENABLED',
    'FakeMarketAnalysisGateway',
    'FakeSeedGateway',
    'FakeFailingQidianAdapter',
    'BROWSER_VITE_ORIGIN',
    'BROWSER_BACKEND_ORIGIN',
    'phase2b-test-results',
    'selection_revision',
    'ForbiddenOutboundAsyncClient',
    'forbidden_outbound_httpx_calls',
    'BROWSER_TEST_DATABASE',
    'SELECT DATABASE() AS database_name',
  ]) assert.match(
    source,
    new RegExp(required.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'),
    required,
  )
  assert.match(source, /return runPhase2BLifecycle\(\{/u)
  assert.doesNotMatch(source, /class AcceptanceMarketSourceService/u)
  assert.doesNotMatch(source, /UPDATE market_source_refresh_states/u)
  assert.doesNotMatch(source, /\bprovider_calls\s*=\s*0/u)
  assert.doesNotMatch(source, /\bwebsite_calls\s*=\s*0/u)
  assert.doesNotMatch(source, /\bproduct_db_(?:reads|writes)\s*=\s*0/u)
  assert.doesNotMatch(source, /httpx\.AsyncClient\s*\(/u)
  assert.doesNotMatch(source, /MARKET_SCHEDULER_ENABLED:\s*['"]true['"]/u)
  assert.match(source, /print\("seed_revisions=2"\)/u)
  assert.match(source, /print\("selection_revisions=3"\)/u)
  assert.doesNotMatch(source, /print\("seed_revisions=3"\)/u)
})


test('runner inline Python is ASCII-safe across the Windows owned-process boundary', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2b.mjs')
  for (const name of ['FIXTURE_SOURCE', 'BACKEND_SOURCE', 'VERIFICATION_SOURCE']) {
    const match = source.match(new RegExp(
      `const ${name} = String\\.raw\`([\\s\\S]*?)\`\\n`,
      'u',
    ))
    assert.ok(match, `missing ${name}`)
    assert.doesNotMatch(match[1], /[^\u0000-\u007f]/u, name)
  }
})


test('fake gateway evidence uses an append-only ledger safe for concurrent requests', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2b.mjs')

  assert.match(source, /COUNTER_PATH\.open\("a", encoding="utf-8"\)/u)
  assert.match(source, /counter_lines\.count\("fake_seed_gateway_calls"\)/u)
  assert.doesNotMatch(
    source,
    /counters\s*=\s*json\.loads\(COUNTER_PATH\.read_text/u,
  )
})


test('archived seed regression freezes full state and rejects every seed mutation', () => {
  const source = readWorkspaceFile(
    'backend/tests/integration/test_seed_revisions.py',
  )
  const regression = source.match(
    /async def test_archived_project_retains_readable_seed_state_but_rejects_mutations\([\s\S]*?\n\nasync def install_matching_contract/u,
  )?.[0] || ''

  for (const required of [
    '"identities"',
    '"heads"',
    '"revisions"',
    '"selection"',
    '"selection_ledger"',
    'service.create(',
    'service.edit(',
    'service.select(',
    'service.delete(',
    'service.archive(',
    'service.restore(',
    'state_after == state_before',
  ]) assert.match(regression, new RegExp(required.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'))
})


test('runner diagnostics redact every expanded sensitive value before reporting', async () => {
  const runner = await import(runnerModule)
  const diagnostic = [
    'failure at C:\\Temp\\owned-root',
    'database=novel_creator_test_private',
  ].join('\n')
  const rendered = runner.redactRuntimeDiagnostic(diagnostic, [
    String.raw`C:\Temp\owned-root`,
    'novel_creator_test_private',
  ])

  assert.equal(rendered.includes('owned-root'), false)
  assert.equal(rendered.includes('novel_creator_test_private'), false)
  assert.match(rendered, /\[REDACTED\]/u)
})


test('dispatcher validates and starts only the closed Phase 2B runner', () => {
  const calls = []
  let stderr = ''
  const exitCode = runSuites(['browser-phase2b'], {
    environment: TEST_ENVIRONMENT,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
    stderr: { write(chunk) { stderr += chunk } },
  })

  assert.equal(exitCode, 0, stderr)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].args, ['frontend/e2e/run-phase2b.mjs'])
  assert.equal(calls[0].options.shell, false)
})


test('dispatcher refuses Phase 2B before spawn when test authority is incomplete', () => {
  const environment = { ...TEST_ENVIRONMENT }
  delete environment.TEST_MYSQL_USER
  const calls = []
  let stderr = ''
  const exitCode = runSuites(['browser-phase2b'], {
    environment,
    spawnSyncImpl(...args) {
      calls.push(args)
      return { status: 0 }
    },
    stderr: { write(chunk) { stderr += chunk } },
  })

  assert.equal(exitCode, 2)
  assert.deepEqual(calls, [])
  assert.match(stderr, /TEST_MYSQL_USER/u)
  assert.doesNotMatch(stderr, /phase2b-test-password/u)
})


test('acceptance report records exact evidence and honest isolation boundaries', () => {
  const source = readWorkspaceFile(
    'docs/acceptance/2026-07-18-phase-2b-market-seeds.md',
  )

  for (const required of [
    'Disposable MySQL',
    '真实 Playwright 浏览器',
    'Qidian',
    'QQ',
    'A → B → A',
    '官方刷新接口返回 HTTP `503`',
    '结构性不可达',
    'ForbiddenOutboundAsyncClient',
    'BROWSER_TEST_DATABASE',
    '数据库身份',
    'mutation capabilities',
    'hasFinalChapters',
    '真实 FastAPI + Disposable MySQL API',
    'scheduler',
  ]) assert.match(
    source,
    new RegExp(required.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'),
    required,
  )
  assert.doesNotMatch(source, /Provider\/model calls：`0`/u)
  assert.doesNotMatch(source, /Product DB reads\/writes：`0\/0`/u)
  assert.doesNotMatch(source, /所有允许写入的 HTTP 状态均为 `200`/u)
  assert.doesNotMatch(source, /phase2b-browser-secret/u)
  assert.doesNotMatch(source, /private-provider/u)
})

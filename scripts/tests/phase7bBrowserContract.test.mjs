import assert from 'node:assert/strict'
import {
  existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync,
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { EventEmitter } from 'node:events'
import { fileURLToPath } from 'node:url'

import { collectBrowserTestDeclarations } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const source = relative => readFileSync(path.join(root, relative), 'utf8')

test('Phase 7B registers one exact formal read-only browser target', async () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(rootPackage.scripts['test:browser:phase7b'], 'node scripts/run-tests.mjs browser-phase7b')
  assert.equal(frontendPackage.scripts['test:e2e:phase7b'], 'node e2e/run-phase7b.mjs')
  assert.equal(frontendPackage.scripts['test:browser:phase7b'], 'node ../scripts/run-tests.mjs browser-phase7b')

  for (const relative of [
    'frontend/e2e/phase7b-product-database-readiness.spec.mjs',
    'frontend/e2e/playwright.phase7b.config.mjs',
    'frontend/e2e/run-phase7b.mjs',
  ]) assert.equal(existsSync(path.join(root, relative)), true, relative)

  const calls = []
  const environment = {
    MYSQL_DB: 'novel_creator_v113',
    MARKET_SCHEDULER_ENABLED: 'false',
    PHASE7B_BROWSER_TASK_ROOT: path.join(root, '.contract-owned-root'),
    PHASE7B_BROWSER_TASK_NONCE: 'a'.repeat(32),
  }
  assert.equal(runSuites(['browser-phase7b'], {
    rootDirectory: root,
    environment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
    pytestTempLifecycle: { prepare() {}, cleanupStage() {}, cleanupAll() {} },
  }), 0)
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase7b.mjs']])
  assert.equal(calls[0].options.shell, false)

  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, ['phase7b-product-database-readiness.spec.mjs'])
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase7b.config.mjs')
})

test('Phase 7B spec proves only the exact approved read-only product state', () => {
  const spec = source('frontend/e2e/phase7b-product-database-readiness.spec.mjs')
  const declarations = collectBrowserTestDeclarations(
    spec,
    'frontend/e2e/phase7b-product-database-readiness.spec.mjs',
  )
  assert.deepEqual(declarations.map(item => item.title), [
    'new product database exposes only approved empty/static state',
  ])
  for (const marker of [
    "page.goto('/api/health')", "toEqual({ ok: true })", "page.goto('/projects')",
    "name: '项目库'", "name: '从一个名字开始'", "page.goto('/assets/styles')",
    "name: '风格模板库'", "getByText('APPROVED STYLES')", "toContainText('10')",
    "toHaveCount(10)", "page.goto('/assets/experience')", "name: '经验卡库'",
    "getByText('APPROVED CARDS')", "toContainText('64')", "page.goto('/api/market-sources')",
    'toHaveLength(2)', "page.goto('/settings/providers')", "name: 'Provider 与模型'",
    "getByText('还没有 Provider 配置')", 'assertRuntimeEvidenceHealthy',
  ]) assert.equal(spec.includes(marker), true, marker)
  assert.doesNotMatch(spec, /page\.(?:request|route|evaluate)|route\.fulfill|\bfetch\s*\(|\baxios\b/iu)
  assert.doesNotMatch(spec, /\b(?:POST|PUT|PATCH|DELETE)\b|writeAllowlist|SQL|bootstrap|fixture|seed/iu)
})

test('Phase 7B runner borrows its sandbox and emits only private internal evidence', async () => {
  const runnerSource = source('frontend/e2e/run-phase7b.mjs')
  for (const marker of [
    'reserveLocalPort', 'startOwnedServer', 'stopOwnedServer', 'waitForPortRelease',
    'PHASE7B_BROWSER_TASK_ROOT', 'PHASE7B_BROWSER_TASK_NONCE', 'artifactRoot',
    'resultPath', 'vite-cache', 'providerCalls', 'outboundRequests', 'writeRequests',
    'PHASE7B_BROWSER_INTERNAL_EVIDENCE=', 'MYSQL_DB', 'novel_creator_v113',
    'MARKET_SCHEDULER_ENABLED', 'false',
  ]) assert.equal(runnerSource.includes(marker), true, marker)
  for (const forbidden of [
    'createFilesystemRootOwner', 'createRunnerRoot', 'removeRunnerRoot',
    'PHASE7B_BROWSER_SMOKE_SUMMARY=', 'rootCount', 'mkdtempSync',
  ]) assert.equal(runnerSource.includes(forbidden), false, forbidden)
  assert.doesNotMatch(runnerSource, /createDatabaseName|prepare_product_shell_browser_db|initialize_database|\bmysqld\b|\bDROP\s+DATABASE\b|\bCREATE\s+DATABASE\b/iu)
  assert.doesNotMatch(runnerSource, /ProviderMustNotRun|DENY_PROXY_SOURCE|writeAllowlist/iu)

  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const inherited = {
    Path: 'inherited-path', ONLY_TEST: 'yes', MYSQL_DB: 'wrong', mysql_db: 'also-wrong',
    MARKET_SCHEDULER_ENABLED: 'true', phase7b_browser_task_root: 'private-root',
    PHASE7B_BROWSER_TASK_NONCE: 'private-nonce',
  }
  const backend = runner.createBackendEnvironment(inherited)
  assert.deepEqual(backend, {
    Path: 'inherited-path', ONLY_TEST: 'yes', MYSQL_DB: 'novel_creator_v113',
    MARKET_SCHEDULER_ENABLED: 'false',
  })
  assert.deepEqual(inherited, {
    Path: 'inherited-path', ONLY_TEST: 'yes', MYSQL_DB: 'wrong', mysql_db: 'also-wrong',
    MARKET_SCHEDULER_ENABLED: 'true', phase7b_browser_task_root: 'private-root',
    PHASE7B_BROWSER_TASK_NONCE: 'private-nonce',
  })
  const backendLaunch = runner.createBackendLaunch({
    ownerNonce: 'd'.repeat(32),
    port: 43123,
  })
  assert.deepEqual(backendLaunch.args.slice(-2), ['d'.repeat(32), '43123'])
  assert.equal(backendLaunch.args.join('\n').includes('private-root'), false)
  assert.equal(backendLaunch.args.join('\n').includes('private-nonce'), false)
  assert.deepEqual(runner.internalEvidence(), {
    firstStage: null, firstCause: null, scenarioCount: 1,
    providerCalls: 0, outboundRequests: 0,
    processCount: 0, portCount: 0, artifactCount: 0,
  })
  assert.equal(
    runner.renderInternalEvidence(runner.internalEvidence()),
    'PHASE7B_BROWSER_INTERNAL_EVIDENCE={"firstStage":null,"firstCause":null,"scenarioCount":1,"providerCalls":0,"outboundRequests":0,"processCount":0,"portCount":0,"artifactCount":0}',
  )
})

test('Phase 7B config is one-worker, loopback-only, and direct-child-owned', () => {
  const config = source('frontend/e2e/playwright.phase7b.config.mjs')
  for (const marker of [
    'workers: 1', 'fullyParallel: false', '127.0.0.1', 'BROWSER_ALLOWED_ORIGINS',
    'BROWSER_OWNED_ROOT', 'BROWSER_ARTIFACT_ROOT', 'BROWSER_RESULT_PATH',
    'direct children', "trace: 'off'", "screenshot: 'off'", "video: 'off'",
  ]) assert.equal(config.includes(marker), true, marker)
  assert.doesNotMatch(config, /localhost|0\.0\.0\.0/iu)
})

test('Phase 7B borrowed sandbox uses only fixed direct children and never deletes its root', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  const nonce = 'b'.repeat(32)
  try {
    const roots = runner.createBorrowedRunnerPaths(taskRoot, nonce)
    assert.deepEqual(Object.values(roots).sort(), [
      path.join(taskRoot, 'artifacts'), path.join(taskRoot, 'result.json'),
      taskRoot, path.join(taskRoot, 'vite-cache'), path.join(taskRoot, 'vite.config.mjs'),
    ].sort())
    assert.deepEqual(readFileNames(taskRoot), ['artifacts'])
    runner.cleanupBorrowedArtifacts(roots)
    assert.equal(existsSync(taskRoot), true)
    assert.deepEqual(readFileNames(taskRoot), [])
  } finally {
    rmSync(taskRoot, { recursive: true, force: true })
  }
})

test('Phase 7B borrowed sandbox rejects aliases and invalid nonces', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  try {
    assert.throws(() => runner.validateBorrowedContract({
      MYSQL_DB: 'novel_creator_v113', MARKET_SCHEDULER_ENABLED: 'false',
      PHASE7B_BROWSER_TASK_ROOT: `${taskRoot}${path.sep}..${path.sep}${path.basename(taskRoot)}`,
      PHASE7B_BROWSER_TASK_NONCE: 'c'.repeat(32),
    }), { message: 'Phase7B browser contract is invalid' })
    assert.throws(() => runner.validateBorrowedContract({
      MYSQL_DB: 'novel_creator_v113', MARKET_SCHEDULER_ENABLED: 'false',
      PHASE7B_BROWSER_TASK_ROOT: taskRoot, PHASE7B_BROWSER_TASK_NONCE: 'C'.repeat(32),
    }), { message: 'Phase7B browser contract is invalid' })
  } finally {
    rmSync(taskRoot, { recursive: true, force: true })
  }
})

test('Phase 7B process audit rejects a final unterminated marker', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const stdout = new EventEmitter()
  const audit = runner.createRuntimeAudit({ stdout })
  stdout.emit('data', Buffer.from('PHASE7B_PROVIDER_CALL'))
  assert.throws(() => audit.finish(), {
    message: 'Phase7B backend audit output was truncated',
  })
})

test('Phase 7B process audit defers unexpected output to its bounded finish', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const stdout = new EventEmitter()
  const audit = runner.createRuntimeAudit({ stdout })
  assert.doesNotThrow(() => stdout.emit('data', Buffer.from('unexpected\n')))
  assert.throws(() => audit.finish(), {
    message: 'Phase7B backend emitted unexpected standard output',
  })
})

test('Phase 7B injected lifecycle runs every owned step in exact order and strips child controls', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const harness = phase7bHarness(runner)
  const logs = []
  assert.equal(await runner.runPhase7B({
    environment: harness.environment,
    dependencies: harness.dependencies,
    log: value => logs.push(value),
  }), 0)
  assert.deepEqual(harness.events, [
    'contract', 'paths:create', 'port:reserve:0', 'port:reserve:1', 'vite:config',
    'backend:environment', 'sensitive-values', 'backend:nonce', 'backend:launch',
    'port:release:0', 'backend:start', 'runtime:observe', 'backend:wait', 'port:release:1',
    'vite:start', 'vite:wait', 'browser:run', 'browser:audit', 'vite:stop',
    'backend:stop', 'runtime:audit', 'port:audit:41001', 'port:audit:41002',
    'artifact:cleanup', 'artifact:audit',
  ])
  const lifecycle = harness.events.flatMap(event => ({
    'port:reserve:0': 'ports:reserve', 'backend:start': 'backend:start',
    'runtime:observe': 'runtime:observe', 'vite:start': 'vite:start',
    'browser:run': 'playwright:run', 'vite:stop': 'vite:stop',
    'backend:stop': 'backend:stop', 'port:audit:41001': 'ports:audit',
    'artifact:audit': 'artifacts:audit',
  })[event] || [])
  assert.deepEqual(lifecycle, [
    'ports:reserve', 'backend:start', 'runtime:observe', 'vite:start',
    'playwright:run', 'vite:stop', 'backend:stop', 'ports:audit', 'artifacts:audit',
  ])
  assert.deepEqual(harness.backendEnvironment, {
    ONLY_TEST: 'yes', MYSQL_DB: 'novel_creator_v113', MARKET_SCHEDULER_ENABLED: 'false',
  })
  assert.equal(
    Object.keys(harness.backendEnvironment).some(key => key.startsWith('PHASE7B_BROWSER_')),
    false,
  )
  assert.equal(Object.hasOwn(harness.backendEnvironment, 'M2_BROWSER_RUN_NONCE'), false)
  assert.equal(
    Object.keys(harness.browserEnvironment).some(key => key.startsWith('PHASE7B_BROWSER_')),
    false,
  )
  assert.equal(
    Object.keys(harness.viteEnvironment).some(key => key.startsWith('PHASE7B_BROWSER_')),
    false,
  )
  assert.deepEqual(logs, [
    'PHASE7B_BROWSER_INTERNAL_EVIDENCE={"firstStage":null,"firstCause":null,"scenarioCount":1,"providerCalls":0,"outboundRequests":0,"processCount":0,"portCount":0,"artifactCount":0}',
  ])
  assertAcquiredResourcesCleaned(harness)
})

for (const failure of [
  'paths:create', 'port:reserve:0', 'port:reserve:1', 'vite:config', 'backend:start',
  'backend:environment', 'sensitive-values', 'backend:nonce', 'backend:launch',
  'runtime:observe', 'backend:wait', 'vite:start', 'vite:wait', 'browser:run',
  'browser:audit', 'port:release:0', 'port:release:1',
]) {
  test(`Phase 7B injected lifecycle cleans all acquired resources after ${failure} failure`, async () => {
    const runner = await import('../../frontend/e2e/run-phase7b.mjs')
    const harness = phase7bHarness(runner, { failAt: failure })
    await assert.rejects(() => runner.runPhase7B({
      environment: harness.environment,
      dependencies: harness.dependencies,
      log() {},
    }), error => {
      assert.equal(firstLeafMessage(error), `failure:${failure}`)
      return true
    })
    assertAcquiredResourcesCleaned(harness)
  })
}

for (const failure of [
  'vite:stop', 'backend:stop', 'runtime:audit', 'port:audit:41001',
  'port:audit:41002', 'artifact:cleanup', 'artifact:audit',
]) {
  test(`Phase 7B injected cleanup reports ${failure} without skipping later cleanup`, async () => {
    const runner = await import('../../frontend/e2e/run-phase7b.mjs')
    const harness = phase7bHarness(runner, { failAt: failure })
    await assert.rejects(() => runner.runPhase7B({
      environment: harness.environment,
      dependencies: harness.dependencies,
      log() {},
    }), error => {
      assert.equal(flattenMessages(error).includes(`failure:${failure}`), true)
      return true
    })
    for (const required of [
      'vite:stop', 'backend:stop', 'runtime:audit', 'port:audit:41001',
      'port:audit:41002', 'artifact:cleanup', 'artifact:audit',
    ]) assert.equal(harness.events.includes(required), true, `${failure} skipped ${required}`)
  })
}

test('Phase 7B preserves primary-first ordering across cleanup failures', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const harness = phase7bHarness(runner, {
    failAt: new Set(['browser:run', 'vite:stop', 'port:audit:41001', 'artifact:cleanup']),
  })
  await assert.rejects(() => runner.runPhase7B({
    environment: harness.environment,
    dependencies: harness.dependencies,
    log() {},
  }), error => {
    assert.deepEqual(flattenMessages(error).filter(value => value.startsWith('failure:')), [
      'failure:browser:run', 'failure:vite:stop', 'failure:port:audit:41001',
      'failure:artifact:cleanup', 'failure:artifact-residue',
    ])
    return true
  })
})

test('Phase 7B emits no evidence after any lifecycle failure', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const harness = phase7bHarness(runner, { failAt: 'artifact:cleanup' })
  const logs = []
  await assert.rejects(() => runner.runPhase7B({
    environment: harness.environment,
    dependencies: harness.dependencies,
    log: value => logs.push(value),
  }))
  assert.deepEqual(logs, [])
})

function readFileNames(directory) {
  return existsSync(directory)
    ? readdirSync(directory).sort()
    : []
}

function phase7bHarness(runner, { failAt = null } = {}) {
  const events = []
  const resources = { artifacts: false, started: new Set(), stopped: new Set() }
  const shouldFail = name => failAt instanceof Set ? failAt.has(name) : failAt === name
  const hit = name => {
    events.push(name)
    if (shouldFail(name)) throw new Error(`failure:${name}`)
  }
  const environment = {
    ONLY_TEST: 'yes', MYSQL_DB: 'novel_creator_v113', MARKET_SCHEDULER_ENABLED: 'false',
    PHASE7B_BROWSER_TASK_ROOT: 'C:\\owned-task-root',
    PHASE7B_BROWSER_TASK_NONCE: 'a'.repeat(32),
    M2_BROWSER_RUN_NONCE: 'must-not-reach-backend',
  }
  const roots = {
    runnerRoot: 'C:\\owned-task-root',
    artifactRoot: 'C:\\owned-task-root\\artifacts',
    resultPath: 'C:\\owned-task-root\\result.json',
    viteConfigPath: 'C:\\owned-task-root\\vite.config.mjs',
  }
  const reservations = [0, 1].map(index => ({
    port: 41001 + index,
    async release() { hit(`port:release:${index}`) },
  }))
  let reservationIndex = 0
  const servers = []
  const dependencies = {
    validateBorrowedContract() { hit('contract'); return { taskRoot: 'C:\\owned-task-root', nonce: 'a'.repeat(32) } },
    createBorrowedRunnerPaths() {
      resources.artifacts = true
      try { hit('paths:create') } catch (error) { resources.artifacts = false; throw error }
      return roots
    },
    async reserveLocalPort() {
      const index = reservationIndex++
      hit(`port:reserve:${index}`)
      return reservations[index]
    },
    writeViteConfig() { hit('vite:config') },
    createBackendEnvironment(value) {
      hit('backend:environment')
      return runner.createBackendEnvironment(value)
    },
    runtimeSensitiveValues() { hit('sensitive-values'); return [] },
    backendNonce() { hit('backend:nonce'); return 'b'.repeat(32) },
    createBackendLaunch() { hit('backend:launch'); return { args: ['-c', 'owned'] } },
    startOwnedServer(_command, _args, options, settings) {
      const kind = settings.label.includes('API') ? 'backend' : 'vite'
      hit(`${kind}:start`)
      if (kind === 'backend') harness.backendEnvironment = options.env
      if (kind === 'vite') harness.viteEnvironment = options.env
      const server = { kind, child: { stdout: new EventEmitter() }, state: {}, auditors: [] }
      resources.started.add(kind)
      servers.push(server)
      return server
    },
    createRuntimeAudit() { hit('runtime:observe'); return { finish: () => ({ providerCalls: 0, outboundRequests: 0, writeRequests: 0 }) } },
    async waitForBackendOwner() { hit('backend:wait') },
    async waitForViteOwner() { hit('vite:wait') },
    async runBoundedOperation(_label, _timeout, _settle, operation) { return operation(new AbortController().signal) },
    async runBoundedOwnedCommand(_command, _args, options) {
      harness.browserEnvironment = options.env
      hit('browser:run')
    },
    auditBrowserReport() { hit('browser:audit') },
    async stopOwnedServer(server) { hit(`${server.kind}:stop`); resources.stopped.add(server.kind) },
    assertRuntimeAuditZero() { hit('runtime:audit') },
    async waitForPortRelease(port) { hit(`port:audit:${port}`) },
    cleanupBorrowedArtifacts() {
      hit('artifact:cleanup')
      resources.artifacts = false
    },
    auditBorrowedArtifacts() {
      hit('artifact:audit')
      if (resources.artifacts) throw new Error('failure:artifact-residue')
      return 0
    },
  }
  const harness = {
    backendEnvironment: null, browserEnvironment: null, viteEnvironment: null, dependencies,
    environment, events, resources, roots,
  }
  return harness
}

function assertAcquiredResourcesCleaned(harness) {
  assert.equal(harness.resources.artifacts, false)
  assert.deepEqual([...harness.resources.stopped].sort(), [...harness.resources.started].sort())
}

function flattenMessages(error) {
  if (error instanceof AggregateError) {
    return error.errors.flatMap(flattenMessages)
  }
  const nested = error?.cause ? flattenMessages(error.cause) : []
  return [String(error?.message || ''), ...nested]
}

function firstLeafMessage(error) {
  return flattenMessages(error).find(value => value.startsWith('failure:')) || ''
}

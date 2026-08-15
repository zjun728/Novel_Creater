import assert from 'node:assert/strict'
import {
  existsSync, lstatSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync,
  rmSync,
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

test('Phase 7B runner owns resources, preserves product data, and emits the Task 5 summary contract', async () => {
  const runnerSource = source('frontend/e2e/run-phase7b.mjs')
  for (const marker of [
    'reserveLocalPort', 'startOwnedServer', 'stopOwnedServer', 'waitForPortRelease',
    'PHASE7B_BROWSER_TASK_ROOT', 'PHASE7B_BROWSER_TASK_NONCE', 'artifactRoot',
    'resultPath', 'deps_temp_', 'providerCalls', 'outboundRequests', 'writeRequests',
    'PHASE7B_BROWSER_SMOKE_SUMMARY=', 'MYSQL_DB', 'novel_creator_v113',
    'MARKET_SCHEDULER_ENABLED', 'false',
  ]) assert.equal(runnerSource.includes(marker), true, marker)
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
  assert.deepEqual(runner.safeSummary(), {
    firstStage: null, firstCause: null, scenarioCount: 1,
    providerCalls: 0, outboundRequests: 0,
    processCount: 0, portCount: 0, rootCount: 0, artifactCount: 0,
  })
  assert.equal(
    runner.renderSummary(runner.safeSummary()),
    'PHASE7B_BROWSER_SMOKE_SUMMARY={"firstStage":null,"firstCause":null,"scenarioCount":1,"providerCalls":0,"outboundRequests":0,"processCount":0,"portCount":0,"rootCount":0,"artifactCount":0}',
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

test('Phase 7B root setup rolls back its new child on partial setup failure', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  const nonce = 'b'.repeat(32)
  try {
    assert.throws(() => runner.createRunnerRoot(taskRoot, nonce, {
      writeFileSyncImpl() { throw new Error('private setup failure') },
    }), { message: 'private setup failure' })
    assert.deepEqual(readFileNames(taskRoot), [])
  } finally {
    rmSync(taskRoot, { recursive: true, force: true })
  }
})

test('Phase 7B root cleanup removes owned residue even when its audit fails', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  const nonce = 'c'.repeat(32)
  const roots = runner.createRunnerRoot(taskRoot, nonce)
  mkdirSync(path.join(roots.runnerRoot, 'vite-cache', 'deps_temp_owned'), { recursive: true })
  try {
    assert.throws(() => runner.auditRunnerRootArtifacts(roots, taskRoot), {
      message: 'Phase7B Vite deps_temp_ residue was not zero',
    })
    runner.removeRunnerRoot(roots, taskRoot, nonce)
    assert.equal(existsSync(roots.runnerRoot), false)
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

test('Phase 7B root cleanup recovers the original direct child and preserves its replacement', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  const nonce = 'e'.repeat(32)
  const roots = runner.createRunnerRoot(taskRoot, nonce)
  const escaped = `${roots.runnerRoot}-escaped`
  renameSync(roots.runnerRoot, escaped)
  mkdirSync(roots.runnerRoot)
  try {
    runner.removeRunnerRoot(roots, taskRoot, nonce)
    assert.equal(existsSync(roots.runnerRoot), true)
    assert.equal(existsSync(escaped), false)
  } finally {
    rmSync(taskRoot, { recursive: true, force: true })
  }
})

test('Phase 7B root acquisition consumes a bound primitive, never an unbound path identity', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  const canonical = path.join(taskRoot, 'primitive-root')
  const original = path.join(taskRoot, 'primitive-root-original')
  let lease
  const rootOwner = {
    acquire() {
      mkdirSync(canonical)
      const identity = directoryIdentity(canonical)
      renameSync(canonical, original)
      mkdirSync(canonical)
      lease = fakeRootLease(taskRoot, canonical, identity)
      return lease
    },
  }
  try {
    const roots = runner.createRunnerRoot(taskRoot, 'f'.repeat(32), { rootOwner })
    assert.equal(roots.runnerRoot, original)
    assert.deepEqual(readdirSync(canonical), [])
    runner.removeRunnerRoot(roots, taskRoot, 'f'.repeat(32))
    assert.equal(existsSync(original), false)
    assert.equal(existsSync(canonical), true)
    assert.equal(lease.closed, true)
  } finally {
    rmSync(taskRoot, { recursive: true, force: true })
  }
})

test('Phase 7B filesystem ownership rejects replacement during create-to-bind acquisition', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  const canonical = path.join(taskRoot, 'race-root')
  const original = path.join(taskRoot, 'race-root-original')
  const rootOwner = runner.createFilesystemRootOwner({
    mkdtempSyncImpl() {
      mkdirSync(canonical)
      renameSync(canonical, original)
      mkdirSync(canonical)
      return canonical
    },
  })
  try {
    assert.throws(() => rootOwner.acquire(taskRoot, '2'.repeat(32)), error => {
      assert.equal(error.message, 'Phase7B root acquisition observed ambiguous new identities')
      assert.deepEqual(error.phase7bResourceCounts, { rootCount: 1, artifactCount: 0 })
      return true
    })
    assert.equal(existsSync(canonical), true)
    assert.equal(existsSync(original), true)
  } finally {
    rmSync(taskRoot, { recursive: true, force: true })
  }
})

test('Phase 7B filesystem ownership preserves acquisition error before handle-close failure', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  const rootOwner = runner.createFilesystemRootOwner({
    fstatSyncImpl() { throw new Error('primary-acquisition') },
    closeSyncImpl() { throw new Error('cleanup-close') },
  })
  try {
    assert.throws(() => rootOwner.acquire(taskRoot, '3'.repeat(32)), error => {
      assert.deepEqual(flattenMessages(error).filter(Boolean), [
        'primary-acquisition', 'cleanup-close',
      ])
      assert.deepEqual(error.phase7bResourceCounts, { rootCount: 1, artifactCount: 0 })
      return true
    })
  } finally {
    rmSync(taskRoot, { recursive: true, force: true })
  }
})

test('Phase 7B filesystem ownership denies deletion when its bound handle identity drifts', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  let canonical
  let identityReads = 0
  let removals = 0
  const rootOwner = runner.createFilesystemRootOwner({
    mkdtempSyncImpl(prefix) { canonical = mkdtempSync(prefix); return canonical },
    fstatSyncImpl() {
      identityReads += 1
      const stats = lstatSync(canonical)
      return {
        isDirectory: () => true,
        dev: identityReads === 1 ? stats.dev : stats.dev + 1,
        ino: stats.ino,
      }
    },
    rmSyncImpl() { removals += 1 },
  })
  const lease = rootOwner.acquire(taskRoot, '4'.repeat(32))
  try {
    assert.throws(() => lease.deleteOwned(canonical), {
      message: 'Phase7B root ownership handle identity drifted',
    })
    assert.equal(removals, 0)
    assert.equal(existsSync(canonical), true)
  } finally {
    lease.close()
    rmSync(taskRoot, { recursive: true, force: true })
  }
})

test('Phase 7B root recovery fails safe when the owned identity escapes its task parent', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  const outsideParent = mkdtempSync(path.join(os.tmpdir(), 'phase7b-outside-'))
  const nonce = '1'.repeat(32)
  const roots = runner.createRunnerRoot(taskRoot, nonce)
  const outside = path.join(outsideParent, 'escaped')
  renameSync(roots.runnerRoot, outside)
  mkdirSync(roots.runnerRoot)
  try {
    assert.throws(() => runner.removeRunnerRoot(roots, taskRoot, nonce), {
      message: 'Phase7B owned root is outside its validated task parent',
    })
    assert.equal(existsSync(outside), true)
    assert.equal(existsSync(roots.runnerRoot), true)
    assert.deepEqual(runner.resourceCounts(roots), { rootCount: 1, artifactCount: 1 })
  } finally {
    rmSync(taskRoot, { recursive: true, force: true })
    rmSync(outsideParent, { recursive: true, force: true })
  }
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
    'contract', 'root:create', 'port:reserve:0', 'port:reserve:1', 'vite:config',
    'backend:environment', 'sensitive-values', 'backend:nonce', 'backend:launch',
    'port:release:0', 'backend:start', 'runtime:observe', 'backend:wait', 'port:release:1',
    'vite:start', 'vite:wait', 'browser:run', 'browser:audit', 'vite:stop',
    'backend:stop', 'runtime:audit', 'port:audit:41001', 'port:audit:41002',
    'artifact:audit', 'root:remove', 'resource:counts',
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
  assert.deepEqual(logs, [
    'PHASE7B_BROWSER_SMOKE_SUMMARY={"firstStage":null,"firstCause":null,"scenarioCount":1,"providerCalls":0,"outboundRequests":0,"processCount":0,"portCount":0,"rootCount":0,"artifactCount":0}',
  ])
})

for (const failure of [
  'root:create', 'port:reserve:0', 'port:reserve:1', 'vite:config', 'backend:start',
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
      assert.deepEqual(error.phase7bResourceCounts, { rootCount: 0, artifactCount: 0 })
      return true
    })
    assertAcquiredResourcesCleaned(harness)
  })
}

for (const failure of [
  'vite:stop', 'backend:stop', 'runtime:audit', 'port:audit:41001',
  'port:audit:41002', 'artifact:audit',
  'root:remove',
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
      'port:audit:41002', 'artifact:audit', 'root:remove', 'resource:counts',
    ]) assert.equal(harness.events.includes(required), true, `${failure} skipped ${required}`)
  })
}

test('Phase 7B preserves primary-first ordering across cleanup failures', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const harness = phase7bHarness(runner, {
    failAt: new Set(['browser:run', 'vite:stop', 'port:audit:41001', 'root:remove']),
  })
  await assert.rejects(() => runner.runPhase7B({
    environment: harness.environment,
    dependencies: harness.dependencies,
    log() {},
  }), error => {
    assert.deepEqual(flattenMessages(error).filter(value => value.startsWith('failure:')), [
      'failure:browser:run', 'failure:vite:stop', 'failure:port:audit:41001',
      'failure:root:remove',
    ])
    return true
  })
})

test('Phase 7B failure summary reports actual unresolved root and artifact counts', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const harness = phase7bHarness(runner, { failAt: 'root:remove' })
  await assert.rejects(() => runner.runPhase7B({
    environment: harness.environment,
    dependencies: harness.dependencies,
    log() {},
  }), error => {
    assert.deepEqual(error.phase7bResourceCounts, { rootCount: 1, artifactCount: 1 })
    assert.equal(
      runner.renderFailureSummary(error),
      'PHASE7B_BROWSER_SMOKE_SUMMARY={"firstStage":"root-cleanup","firstCause":"stage-failed","scenarioCount":1,"providerCalls":0,"outboundRequests":0,"processCount":0,"portCount":0,"rootCount":1,"artifactCount":1}',
    )
    return true
  })
})

test('Phase 7B failure summary retains pre-return acquisition residue evidence', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const harness = phase7bHarness(runner)
  harness.dependencies.createRunnerRoot = () => {
    const error = new Error('acquisition-race')
    error.phase7bResourceCounts = { rootCount: 1, artifactCount: 0 }
    throw error
  }
  await assert.rejects(() => runner.runPhase7B({
    environment: harness.environment,
    dependencies: harness.dependencies,
    log() {},
  }), error => {
    assert.deepEqual(error.phase7bResourceCounts, { rootCount: 1, artifactCount: 0 })
    assert.match(runner.renderFailureSummary(error), /"rootCount":1,"artifactCount":0\}$/u)
    return true
  })
})

function readFileNames(directory) {
  return existsSync(directory)
    ? readdirSync(directory).sort()
    : []
}

function directoryIdentity(directory) {
  const stats = lstatSync(directory)
  return { dev: stats.dev, ino: stats.ino }
}

function fakeRootLease(taskRoot, canonicalPath, identity) {
  return {
    canonicalPath,
    identity,
    closed: false,
    resolveOwned() {
      const matches = readdirSync(taskRoot, { withFileTypes: true })
        .filter(entry => entry.isDirectory() && !entry.isSymbolicLink())
        .map(entry => path.join(taskRoot, entry.name))
        .filter(candidate => {
          const current = directoryIdentity(candidate)
          return current.dev === identity.dev && current.ino === identity.ino
        })
      return matches.length === 1 ? matches[0] : null
    },
    deleteOwned() {
      const owned = this.resolveOwned()
      if (!owned) throw new Error('outside')
      rmSync(owned, { recursive: true })
    },
    close() { this.closed = true },
  }
}

function phase7bHarness(runner, { failAt = null } = {}) {
  const events = []
  const resources = { root: false, artifacts: false }
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
    runnerRoot: 'C:\\owned-task-root\\runner',
    artifactRoot: 'C:\\owned-task-root\\runner\\artifacts',
    resultPath: 'C:\\owned-task-root\\runner\\result.json',
    viteConfigPath: 'C:\\owned-task-root\\runner\\vite.config.mjs',
  }
  const reservations = [0, 1].map(index => ({
    port: 41001 + index,
    async release() { hit(`port:release:${index}`) },
  }))
  let reservationIndex = 0
  const servers = []
  const dependencies = {
    validateContract() { hit('contract'); return { taskRoot: 'C:\\owned-task-root', nonce: 'a'.repeat(32) } },
    createRunnerRoot() {
      hit('root:create')
      resources.root = true
      resources.artifacts = true
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
      const server = { kind, child: { stdout: new EventEmitter() }, state: {}, auditors: [] }
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
    async stopOwnedServer(server) { hit(`${server.kind}:stop`) },
    assertRuntimeAuditZero() { hit('runtime:audit') },
    async waitForPortRelease(port) { hit(`port:audit:${port}`) },
    auditRunnerRootArtifacts() { hit('artifact:audit') },
    removeRunnerRoot() {
      hit('root:remove')
      resources.root = false
      resources.artifacts = false
    },
    resourceCounts() {
      hit('resource:counts')
      return {
        rootCount: resources.root ? 1 : 0,
        artifactCount: resources.artifacts ? 1 : 0,
      }
    },
  }
  const harness = {
    backendEnvironment: null, browserEnvironment: null, dependencies,
    environment, events, resources, roots,
  }
  return harness
}

function assertAcquiredResourcesCleaned(harness) {
  assert.equal(harness.resources.root, false)
  assert.equal(harness.resources.artifacts, false)
  assert.equal(harness.events.includes('resource:counts'), true)
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

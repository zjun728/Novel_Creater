import assert from 'node:assert/strict'
import {
  existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync,
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
    assert.throws(() => runner.removeRunnerRoot(roots, taskRoot, nonce), {
      message: 'Phase7B Vite deps_temp_ residue was not zero',
    })
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

test('Phase 7B root cleanup preserves a replacement with different identity', async () => {
  const runner = await import('../../frontend/e2e/run-phase7b.mjs')
  const taskRoot = mkdtempSync(path.join(os.tmpdir(), 'phase7b-contract-'))
  const nonce = 'e'.repeat(32)
  const roots = runner.createRunnerRoot(taskRoot, nonce)
  const escaped = `${roots.runnerRoot}-escaped`
  renameSync(roots.runnerRoot, escaped)
  mkdirSync(roots.runnerRoot)
  try {
    assert.throws(() => runner.removeRunnerRoot(roots, taskRoot, nonce), {
      message: 'Phase7B runner root lost ownership',
    })
    assert.equal(existsSync(roots.runnerRoot), true)
    assert.equal(existsSync(escaped), true)
  } finally {
    rmSync(taskRoot, { recursive: true, force: true })
  }
})

function readFileNames(directory) {
  return existsSync(directory)
    ? readdirSync(directory).sort()
    : []
}

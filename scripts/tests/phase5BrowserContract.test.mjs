import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import {
  assertSafeBrowserGraph,
  collectBrowserTestDeclarations,
} from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'


const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..')
const source = relativePath => readFileSync(path.join(repositoryRoot, relativePath), 'utf8')


test('Phase 5 owns one narrow fake-boundary browser entrypoint', () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(rootPackage.scripts['test:browser:phase5'], 'node scripts/run-tests.mjs browser-phase5')
  assert.equal(frontendPackage.scripts['test:e2e:phase5'], 'node e2e/run-phase5.mjs')
  assert.equal(frontendPackage.scripts['test:browser:phase5'], 'node ../scripts/run-tests.mjs browser-phase5')
  for (const relativePath of [
    'backend/scripts/prepare_phase5_browser_db.py',
    'frontend/e2e/run-phase5.mjs',
    'frontend/e2e/playwright.phase5.config.ts',
    'frontend/e2e/phase5-atomic-finalization.spec.ts',
  ]) assert.equal(existsSync(path.join(repositoryRoot, relativePath)), true, relativePath)

  const calls = []
  const status = runSuites(['browser-phase5'], {
    rootDirectory: repositoryRoot,
    environment: {
      TEST_MYSQL_HOST: '127.0.0.1', TEST_MYSQL_PORT: '33060',
      TEST_MYSQL_USER: 'root', TEST_MYSQL_PASSWORD: 'test-only',
    },
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  })
  assert.equal(status, 0)
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase5.mjs']])
  assert.equal(calls[0].options.shell, false)
})


test('Phase 5 runner reuses the owned three-service lifecycle with in-process fakes', async () => {
  const runner = await import('../../frontend/e2e/run-phase5.mjs')
  const value = source('frontend/e2e/run-phase5.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, ['phase5-atomic-finalization.spec.ts'])
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase5.config.ts')
  assert.equal(runner.FORMAL_SCENARIO.tag, '@atomic-finalization')
  for (const fragment of [
    "from './support/product-runner.mjs'", "from './support/deny-proxy.mjs'",
    "from './support/database-residue.mjs'", 'runOwnedProductLifecycle',
    'novel-creator-phase5-', 'createDatabaseName', 'reserveLocalPort',
    'BROWSER_ALLOWED_ORIGINS', 'BROWSER_DENY_PROXY_URL',
    'prepare_phase5_browser_db', 'verify-postconditions',
    'injected fake quality/extraction providers', 'real provider calls = 0',
    'product DB reads/writes = 0/0', 'vite-cache', 'deps_temp',
  ]) assert.equal(value.includes(fragment), true, fragment)
  assert.equal(value.match(/startOwnedServer\(/gu)?.length, 3)
  assert.doesNotMatch(value, /BROWSER_PROVIDER_BASE_URL|fake-provider|provider-ledger|localhost|0\.0\.0\.0/iu)
  assert.equal(runner.formatBrowserPassedSummary(1), 'Phase5 browser: 1/1 scenarios passed')
  assert.throws(() => runner.formatBrowserPassedSummary(0), /counters/iu)
})


test('Phase 5 browser graph performs review, correction, confirmation and commit through visible UI', () => {
  const entry = 'frontend/e2e/phase5-atomic-finalization.spec.ts'
  const spec = source(entry)
  const config = source('frontend/e2e/playwright.phase5.config.ts')
  assertSafeBrowserGraph(entry, relativePath => source(relativePath))
  const declarations = collectBrowserTestDeclarations(spec, entry)
  assert.deepEqual(declarations.map(item => item.title), [
    '@atomic-finalization reviews, corrects, confirms, and atomically finalizes one Candidate',
  ])
  const body = declarations[0].bodySource
  for (const label of [
    '保存为候选', '审查并定稿', '质量建议', 'Canon 事实', '故事进度',
    '未来规划调整', '保存修正', '确认以上变更', '定稿本章', '本章已定稿',
  ]) assert.equal(body.includes(label), true, label)
  assert.match(body, /runtime\.finish\(\)/u)
  assert.match(body, /assertHealthy\(evidence/u)
  assert.doesNotMatch(spec, /page\.(?:request|route|evaluate)|\bfetch\(|\baxios\b|console\.(?:log|error)/u)
  for (const fragment of [
    'fullyParallel: false', 'workers: 1', "preserveOutput: 'never'",
    "trace: 'off'", "screenshot: 'off'", "video: 'off'",
  ]) assert.equal(config.includes(fragment), true, fragment)
})


test('Phase 5 fixture verifies the real atomic postconditions without product DB access', () => {
  const fixture = source('backend/scripts/prepare_phase5_browser_db.py')
  for (const fragment of [
    'novel_creator_test_', 'prepare_canonical_workspace', 'verify_postconditions',
    'final_chapters', 'finalization_records', 'canon_revisions', 'projection_heads',
    'plot_thread_projections', 'project_planning_heads', "status='final'",
  ]) assert.equal(fixture.includes(fragment), true, fragment)
  assert.doesNotMatch(fixture, /DROP DATABASE|CREATE DATABASE/iu)
})

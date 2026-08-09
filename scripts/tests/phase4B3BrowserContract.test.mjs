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


const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
)


function source(relativePath) {
  return readFileSync(path.join(repositoryRoot, relativePath), 'utf8')
}


test('Phase 4B3 owns one narrow fake-provider browser entrypoint', () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(
    rootPackage.scripts['test:browser:phase4b3'],
    'node scripts/run-tests.mjs browser-phase4b3',
  )
  assert.equal(
    frontendPackage.scripts['test:e2e:phase4b3'],
    'node e2e/run-phase4b3.mjs',
  )
  assert.equal(
    frontendPackage.scripts['test:browser:phase4b3'],
    'node ../scripts/run-tests.mjs browser-phase4b3',
  )
  for (const relativePath of [
    'backend/scripts/prepare_phase4b3_browser_db.py',
    'frontend/e2e/run-phase4b3.mjs',
    'frontend/e2e/playwright.phase4b3.config.ts',
    'frontend/e2e/phase4b3-selection-tools.spec.ts',
  ]) assert.equal(existsSync(path.join(repositoryRoot, relativePath)), true, relativePath)

  const calls = []
  const status = runSuites(['browser-phase4b3'], {
    rootDirectory: repositoryRoot,
    environment: {
      TEST_MYSQL_HOST: '127.0.0.1',
      TEST_MYSQL_PORT: '33060',
      TEST_MYSQL_USER: 'root',
      TEST_MYSQL_PASSWORD: 'test-only',
    },
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  })
  assert.equal(status, 0)
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase4b3.mjs']])
  assert.equal(calls[0].options.shell, false)
})


test('Phase 4B3 runner is a single serial owned-resource scenario', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b3.mjs')
  const runnerSource = source('frontend/e2e/run-phase4b3.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, ['phase4b3-selection-tools.spec.ts'])
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase4b3.config.ts')
  assert.equal(runner.FORMAL_SCENARIO.tag, '@selection-tools')
  for (const fragment of [
    "from './support/product-runner.mjs'",
    "from './support/deny-proxy.mjs'",
    "from './support/database-residue.mjs'",
    'runOwnedProductLifecycle',
    'novel-creator-phase4b3-',
    'createDatabaseName',
    'reserveLocalPort',
    'BROWSER_ALLOWED_ORIGINS',
    'BROWSER_DENY_PROXY_URL',
    'BROWSER_PROVIDER_BASE_URL',
    'prepare_phase4b3_browser_db',
    'verify-postconditions',
    'real provider calls = 0',
    'product DB reads/writes = 0/0',
    '}, 10000)',
  ]) assert.equal(runnerSource.includes(fragment), true, fragment)
  assert.doesNotMatch(runnerSource, /localhost|0\.0\.0\.0/u)
  assert.equal(runner.formatBrowserPassedSummary(1), 'Phase4B3 browser: 1/1 scenarios passed')
  assert.throws(() => runner.formatBrowserPassedSummary(0), /counters/iu)
})


test('Phase 4B3 browser graph uses only visible UI for four local tools, cancel, and undo', () => {
  const entry = 'frontend/e2e/phase4b3-selection-tools.spec.ts'
  const spec = source(entry)
  const config = source('frontend/e2e/playwright.phase4b3.config.ts')
  assertSafeBrowserGraph(entry, relativePath => source(relativePath))
  const declarations = collectBrowserTestDeclarations(spec, entry)
  assert.deepEqual(declarations.map(item => item.title), [
    '@selection-tools completes four local tools, preserves cancelled prose, and undoes once',
  ])
  const body = declarations[0].bodySource
  for (const label of ['AI 改写', 'AI 润色', 'AI 扩写', 'AI 缩写', '停止生成', '撤销本次 AI 修改']) {
    assert.equal(body.includes(label), true, label)
  }
  assert.match(body, /replacementPreview/u)
  assert.match(body, /runtime\.finish\(\)/u)
  assert.match(body, /assertHealthy\(evidence/u)
  assert.doesNotMatch(spec, /page\.(?:request|route|evaluate)|\bfetch\(|\baxios\b/u)
  assert.doesNotMatch(spec, /\.toHaveValue\(|console\.(?:log|error)/u)
  for (const fragment of [
    'fullyParallel: false',
    'workers: 1',
    "preserveOutput: 'never'",
    "trace: 'off'",
    "screenshot: 'off'",
    "video: 'off'",
  ]) assert.equal(config.includes(fragment), true, fragment)
})

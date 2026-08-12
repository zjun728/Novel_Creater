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


test('Phase 4C owns one narrow provider-free browser entrypoint', () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(
    rootPackage.scripts['test:browser:phase4c'],
    'node scripts/run-tests.mjs browser-phase4c',
  )
  assert.equal(
    frontendPackage.scripts['test:e2e:phase4c'],
    'node e2e/run-phase4c.mjs',
  )
  assert.equal(
    frontendPackage.scripts['test:browser:phase4c'],
    'node ../scripts/run-tests.mjs browser-phase4c',
  )
  for (const relativePath of [
    'backend/scripts/prepare_phase4c_browser_db.py',
    'frontend/e2e/run-phase4c.mjs',
    'frontend/e2e/playwright.phase4c.config.ts',
    'frontend/e2e/phase4c-candidate-workbench.spec.ts',
  ]) assert.equal(existsSync(path.join(repositoryRoot, relativePath)), true, relativePath)

  const calls = []
  const status = runSuites(['browser-phase4c'], {
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
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase4c.mjs']])
  assert.equal(calls[0].options.shell, false)
})


test('Phase 4C runner owns three local services and no provider process', async () => {
  const runner = await import('../../frontend/e2e/run-phase4c.mjs')
  const runnerSource = source('frontend/e2e/run-phase4c.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, ['phase4c-candidate-workbench.spec.ts'])
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase4c.config.ts')
  assert.equal(runner.FORMAL_SCENARIO.tag, '@candidate-workbench')
  for (const fragment of [
    "from './support/product-runner.mjs'",
    "from './support/deny-proxy.mjs'",
    "from './support/database-residue.mjs'",
    'runOwnedProductLifecycle',
    'novel-creator-phase4c-',
    'createDatabaseName',
    'reserveLocalPort',
    'BROWSER_ALLOWED_ORIGINS',
    'BROWSER_DENY_PROXY_URL',
    'prepare_phase4c_browser_db',
    'verify-postconditions',
    'real provider calls = 0',
    'product DB reads/writes = 0/0',
    '}, 10000)',
  ]) assert.equal(runnerSource.includes(fragment), true, fragment)
  assert.doesNotMatch(runnerSource, /BROWSER_PROVIDER_BASE_URL|fake-provider|provider-ledger/iu)
  assert.equal(runnerSource.match(/startOwnedServer\(/gu)?.length, 3)
  assert.doesNotMatch(runnerSource, /localhost|0\.0\.0\.0/u)
  assert.equal(runner.formatBrowserPassedSummary(1), 'Phase4C browser: 1/1 scenarios passed')
  assert.throws(() => runner.formatBrowserPassedSummary(0), /counters/iu)
})


test('Phase 4C browser graph saves, compares, and loads candidates through visible UI', () => {
  const entry = 'frontend/e2e/phase4c-candidate-workbench.spec.ts'
  const spec = source(entry)
  const config = source('frontend/e2e/playwright.phase4c.config.ts')
  assertSafeBrowserGraph(entry, relativePath => source(relativePath))
  const declarations = collectBrowserTestDeclarations(spec, entry)
  assert.deepEqual(declarations.map(item => item.title), [
    '@candidate-workbench saves two, compares two read-only drafts, and loads one',
  ])
  const body = declarations[0].bodySource
  for (const label of [
    '保存为候选',
    '选择候选 1 进行比较',
    '选择候选 2 进行比较',
    '候选稿只读比较',
    '载入为工作稿',
  ]) assert.equal(body.includes(label), true, label)
  assert.match(body, /runtime\.finish\(\)/u)
  assert.match(body, /assertHealthy\(evidence/u)
  assert.doesNotMatch(spec, /page\.(?:request|route|evaluate)|\bfetch\(|\baxios\b/u)
  assert.doesNotMatch(spec, /console\.(?:log|error)/u)
  for (const fragment of [
    'fullyParallel: false',
    'workers: 1',
    "preserveOutput: 'never'",
    "trace: 'off'",
    "screenshot: 'off'",
    "video: 'off'",
  ]) assert.equal(config.includes(fragment), true, fragment)
})

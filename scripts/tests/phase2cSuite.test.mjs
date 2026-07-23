import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
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


const RUN_ONE_SCENARIO_BOUNDARY =
  /async function runOneScenario\(([\s\S]*?)\r?\n\}\r?\n\r?\n\r?\nexport async function runPhase2C/u
const BACKEND_SOURCE_BOUNDARY =
  /const BACKEND_SOURCE = String\.raw`([\s\S]*?)`\r?\n\r?\nconst FAKE_GATEWAY_SOURCE/u
const FAKE_GATEWAY_SOURCE_BOUNDARY =
  /const FAKE_GATEWAY_SOURCE = String\.raw`([\s\S]*?)`(?:\r?\n)+const VERIFICATION_SOURCE/u
const MANUAL_CONFIGURATION_SOURCE_BOUNDARY =
  /const MANUAL_CONFIGURATION_SOURCE = String\.raw`([\s\S]*?)`\r?\n\r?\nexport function validateSpecs/u
const VISIBLE_SELECT_HELPER_BOUNDARY =
  /(async function chooseVisibleSelectOption[\s\S]*?)\r?\n\}\r?\n\r?\n\r?\nfunction safeDiagnosticText/u


function assertBoundaryAcceptsLfAndCrlf(boundary, lfSource, description) {
  assert.match(lfSource, boundary, `${description} must accept LF`)
  assert.match(
    lfSource.replaceAll('\n', '\r\n'),
    boundary,
    `${description} must accept CRLF`,
  )
}


test('Phase 2C remains an explicit gate while full Phase 2 is the default', () => {
  const rootPackage = JSON.parse(readWorkspaceFile('package.json'))
  const frontendPackage = JSON.parse(readWorkspaceFile('frontend/package.json'))
  assert.equal(rootPackage.scripts['test:browser'], 'node scripts/run-tests.mjs browser-phase2')
  assert.equal(rootPackage.scripts['test:browser:phase2c'], 'node scripts/run-tests.mjs browser-phase2c')
  assert.equal(frontendPackage.scripts['test:e2e'], 'node e2e/run-phase2.mjs')
  assert.equal(frontendPackage.scripts['test:e2e:phase2c'], 'node e2e/run-phase2c.mjs')
  for (const alias of ['test:browser:m2', 'test:milestone2']) {
    assert.equal(rootPackage.scripts[alias], undefined)
  }
  assert.equal(frontendPackage.scripts['test:e2e:m2'], undefined)

  for (const relativePath of [
    'scripts/tests/milestone2-browser-contract.test.mjs',
    'scripts/tests/scan-m2-artifacts.test.mjs',
    'frontend/e2e/m2-settings-assets-corpus.spec.ts',
    'frontend/e2e/m2-wizard-manual.spec.ts',
    'frontend/e2e/m2-wizard-recovery.spec.ts',
    'frontend/e2e/m2-foundation-regression.spec.ts',
    'frontend/e2e/run-milestone2.mjs',
    'frontend/playwright.m2.config.ts',
  ]) {
    assert.equal(existsSync(path.join(repositoryRoot, relativePath)), false, relativePath)
  }
})


test('dispatcher owns one closed Phase 2C runner and validates MySQL before spawn', () => {
  const calls = []
  const completeEnvironment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }
  assert.equal(runSuites(['browser-phase2c'], {
    rootDirectory: repositoryRoot,
    environment: completeEnvironment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  }), 0)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].args, ['frontend/e2e/run-phase2c.mjs'])
  assert.equal(calls[0].options.shell, false)

  calls.length = 0
  let stderr = ''
  const incompleteEnvironment = { ...completeEnvironment }
  delete incompleteEnvironment.TEST_MYSQL_PASSWORD
  assert.equal(runSuites(['browser-phase2c'], {
    rootDirectory: repositoryRoot,
    environment: incompleteEnvironment,
    stderr: { write(chunk) { stderr += chunk } },
    spawnSyncImpl() {
      calls.push('spawned')
      return { status: 0 }
    },
  }), 2)
  assert.deepEqual(calls, [])
  assert.match(stderr, /TEST_MYSQL_PASSWORD/u)
})


test('neutral product runner owns exact disposable names and reverse cleanup semantics', async () => {
  const support = await import('../../frontend/e2e/support/product-runner.mjs')
  assert.equal(
    support.createDatabaseName(() => '01234567-89ab-cdef-0123-456789abcdef'),
    'novel_creator_test_0123456789abcdef0123456789abcdef',
  )
  assert.throws(() => support.assertDatabaseName('novel_creator'), /disposable/u)

  const events = []
  await support.runOwnedProductLifecycle({
    async body(lifecycle) {
      lifecycle.setRoot('root')
      lifecycle.setDatabase('database')
      lifecycle.registerReservation({ name: 'one' })
      lifecycle.registerReservation({ name: 'two' })
      lifecycle.registerServer({ name: 'backend' })
      lifecycle.registerServer({ name: 'vite' })
    },
    async stopServer(item) { events.push(`server:${item.name}`) },
    async releaseReservation(item) { events.push(`reservation:${item.name}`) },
    async dropDatabase(item) { events.push(`database:${item}`) },
    async removeRoot(item) { events.push(`root:${item}`) },
  })
  assert.deepEqual(events, [
    'server:vite',
    'server:backend',
    'reservation:one',
    'reservation:two',
    'database:database',
    'root:root',
  ])
})


test('Phase 2C runner owns one exact spec and fails before resource allocation', async () => {
  const runner = await import('../../frontend/e2e/run-phase2c.mjs')
  const expected = ['e2e/phase2c-contract.spec.ts']
  assert.deepEqual(runner.FORMAL_SPECS, expected)
  assert.deepEqual(runner.resolveCommandLineSpecs([]), expected)
  assert.deepEqual(runner.validateSpecs(expected), expected)
  assert.throws(
    () => runner.resolveCommandLineSpecs(['e2e/arbitrary.spec.ts']),
    /does not accept spec paths/iu,
  )
  const allocations = []
  await assert.rejects(runner.runPhase2C({
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


test('Phase 2C dispatches manual and gateway as separate closed scenarios', async () => {
  const runner = await import('../../frontend/e2e/run-phase2c.mjs')
  const manual = { tag: '@manual', mode: 'manual' }
  const gateway = { tag: '@gateway', mode: 'gateway' }
  assert.deepEqual(runner.FORMAL_SCENARIOS, [manual, gateway])
  assert.deepEqual(runner.resolveFormalScenarios(undefined), [manual, gateway])
  assert.deepEqual(runner.resolveFormalScenarios(''), [manual, gateway])
  assert.deepEqual(runner.resolveFormalScenarios('@manual'), [manual])
  assert.deepEqual(runner.resolveFormalScenarios('@gateway'), [gateway])
  assert.throws(
    () => runner.resolveFormalScenarios('manual|gateway'),
    /exactly @manual or @gateway/iu,
  )

  const calls = []
  const environment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }
  await runner.runPhase2C({
    environment,
    async runOneScenarioImpl(values) {
      calls.push({ spec: values.spec, scenario: values.scenario })
    },
  })
  assert.deepEqual(calls, [
    { spec: 'e2e/phase2c-contract.spec.ts', scenario: manual },
    { spec: 'e2e/phase2c-contract.spec.ts', scenario: gateway },
  ])

  const roots = {
    root: 'C:\\temp\\phase2c',
    filesRoot: 'C:\\temp\\phase2c\\files',
    qidianPath: 'C:\\temp\\phase2c\\qidian.json',
    qqPath: 'C:\\temp\\phase2c\\qq.json',
    counterPath: 'C:\\temp\\phase2c\\counter.log',
    outboundLedgerPath: 'C:\\temp\\phase2c\\outbound.log',
    corpusPath: 'C:\\temp\\phase2c\\corpus.txt',
    corpusRoot: 'C:\\temp\\phase2c\\corpus',
    managedRoot: 'C:\\temp\\phase2c\\managed',
  }
  for (const scenario of [manual, gateway]) {
    const environments = runner.buildEnvironments(
      environment,
      'novel_creator_test_0123456789abcdef0123456789abcdef',
      'http://127.0.0.1:8000',
      'http://127.0.0.1:5173',
      scenario.mode === 'gateway' ? 'http://127.0.0.1:9000/v1' : null,
      'owned-nonce',
      roots,
      'project-1',
      scenario,
    )
    assert.equal(environments.browser.BROWSER_SCENARIO_MODE, scenario.mode)
  }
})


test('Phase 2C runtime policy has exact closed per-scenario missing-draft counts', async () => {
  const { expectedMissingDraftFailureCount } = await import(
    '../../frontend/e2e/phase2c-runtime-policy.mjs'
  )
  assert.equal(expectedMissingDraftFailureCount('manual'), 1)
  assert.equal(expectedMissingDraftFailureCount('gateway'), 2)
  for (const invalid of ['', 'unknown', undefined, null]) {
    assert.throws(
      () => expectedMissingDraftFailureCount(invalid),
      /scenario mode is invalid/iu,
    )
  }
})


test('each LF/CRLF Phase 2C scenario block owns fresh resources and gateway owns only localhost fake I/O', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2c.mjs')
  assertBoundaryAcceptsLfAndCrlf(
    RUN_ONE_SCENARIO_BOUNDARY,
    'async function runOneScenario() {\n}\n\n\nexport async function runPhase2C',
    'per-scenario lifecycle boundary',
  )
  const scenarioSource = source.match(RUN_ONE_SCENARIO_BOUNDARY)
  assert.ok(scenarioSource, 'runner must expose one closed per-scenario lifecycle')
  assert.match(scenarioSource[0], /databaseName\s*=\s*databaseNameFactory\(\)/u)
  assert.match(scenarioSource[0], /ownedRootFactory\(\)/u)
  assert.match(scenarioSource[0], /projectId\s*=\s*projectIdFactory\(\)/u)
  assert.match(scenarioSource[0], /scenario\.tag/u)
  assert.match(scenarioSource[0], /'--grep',\s*scenario\.tag/u)
  assert.match(scenarioSource[0], /scenario\.mode\s*===\s*'gateway'/u)
  assert.match(scenarioSource[0], /gatewayReservation/u)
  assert.match(scenarioSource[0], /registerServer\(startOwnedServer\([\s\S]*?roots\.fakeGatewayPath/u)
  assert.match(source, /const FAKE_GATEWAY_SOURCE = String\.raw`/u)
  assert.match(
    source,
    /writeFileSync\(fakeGatewayPath, FAKE_GATEWAY_SOURCE, \{[\s\S]*?flag: 'wx'/u,
  )
  assert.match(source, /http:\/\/127\.0\.0\.1:\$\{gatewayReservation\.port\}/u)
  assert.match(source, /PROJECT_ID\s*=\s*os\.environ\["BROWSER_PROJECT_ID"\]/u)
  assert.doesNotMatch(source, /const PROJECT_ID = '2b000000-0000-4000-8000-000000000001'/u)
})


test('gateway ledger accepts the two distinct asset-ranking input generations', async () => {
  const runner = await import('../../frontend/e2e/run-phase2c.mjs')
  assert.deepEqual(
    runner.verifyGatewayCounterLedger(
      'story-engine\nasset-ranking\nstyle-trial\nasset-ranking\n',
    ),
    {
      'story-engine': 1,
      'style-trial': 1,
      'asset-ranking': 2,
    },
  )
  for (const invalid of [
    '',
    'story-engine\nstyle-trial\n',
    'story-engine\nstyle-trial\nasset-ranking\n',
    'story-engine\nstory-engine\nstyle-trial\nasset-ranking\nasset-ranking\n',
    'story-engine\nstyle-trial\nasset-ranking\nunknown\n',
  ]) {
    assert.throws(
      () => runner.verifyGatewayCounterLedger(invalid),
      /gateway call ledger/iu,
    )
  }
})


test('LF/CRLF Phase 2C backend block installs a fail-closed HTTPX boundary before product import', async () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2c.mjs')
  assertBoundaryAcceptsLfAndCrlf(
    BACKEND_SOURCE_BOUNDARY,
    'const BACKEND_SOURCE = String.raw`body`\n\nconst FAKE_GATEWAY_SOURCE',
    'backend source boundary',
  )
  const match = source.match(BACKEND_SOURCE_BOUNDARY)
  assert.ok(match, 'backend boundary must remain one closed runner-owned program')
  const backend = match[1]
  assert.ok(
    backend.indexOf('import httpx') < backend.indexOf('from backend.main import app'),
    'HTTPX guard must be installed before importing backend.main',
  )
  assert.match(backend, /class GuardedAsyncClient/u)
  assert.match(backend, /httpx\.AsyncClient\s*=\s*GuardedAsyncClient/u)
  assert.match(backend, /BROWSER_SCENARIO_MODE/u)
  assert.match(backend, /BROWSER_PROVIDER_BASE_URL/u)
  assert.match(backend, /BROWSER_OUTBOUND_LEDGER_PATH/u)
  assert.match(backend, /SCENARIO_MODE\s*(?:==|!=)\s*["']gateway["']/u)
  assert.match(backend, /127\.0\.0\.1/u)
  assert.match(backend, /\/v1\/chat\/completions/u)
  assert.match(backend, /forbidden-outbound/u)
  assert.doesNotMatch(
    backend,
    /(?:write|append)[^\n]*(?:url|header|body|prompt|response)/iu,
  )
  assert.match(source, /outboundLedgerPath/u)
  assert.match(
    source,
    /writeFileSync\(outboundLedgerPath, '', \{ encoding: 'utf8', flag: 'wx' \}\)/u,
  )
  assert.match(
    source,
    /verifyForbiddenOutboundLedger\(\s*readFileSync\(roots\.outboundLedgerPath, 'utf8'\),?\s*\)/u,
  )

  const runner = await import('../../frontend/e2e/run-phase2c.mjs')
  assert.deepEqual(runner.verifyForbiddenOutboundLedger(''), {
    'forbidden-outbound': 0,
  })
  for (const ledger of ['forbidden-outbound\n', 'http://private.example\n']) {
    assert.throws(
      () => runner.verifyForbiddenOutboundLedger(ledger),
      /forbidden outbound ledger/iu,
    )
  }
})


test('LF/CRLF fake gateway block fail-closes unknown traffic and returns formal low-confidence fixtures', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2c.mjs')
  assertBoundaryAcceptsLfAndCrlf(
    FAKE_GATEWAY_SOURCE_BOUNDARY,
    'const FAKE_GATEWAY_SOURCE = String.raw`body`\nconst VERIFICATION_SOURCE',
    'fake gateway source boundary',
  )
  const match = source.match(FAKE_GATEWAY_SOURCE_BOUNDARY)
  assert.ok(match, 'fake gateway must remain one closed runner-owned program')
  const gateway = match[1]
  assert.match(gateway, /request\.method === 'GET' && request\.url === '\/health'/u)
  assert.match(
    gateway,
    /request\.method === 'POST' && request\.url === '\/v1\/chat\/completions'/u,
  )
  assert.match(gateway, /'story-engine'/u)
  assert.match(gateway, /'style-trial'/u)
  assert.match(gateway, /'asset-ranking'/u)
  assert.match(gateway, /options:\s*STORY_ENGINE_OPTIONS/u)
  assert.match(gateway, /sample:/u)
  assert.match(gateway, /confidence:\s*0\.2/u)
  assert.match(gateway, /assetRecommendations/u)
  assert.match(gateway, /corpusRecommendations:\s*\[\]/u)
  assert.match(gateway, /sendJson\(response, (?:400|404|405|422),/u)
  assert.doesNotMatch(gateway, /appendFileSync\([^\n]*(?:authorization|messages|requestBody|rawResponse)/iu)
  assert.doesNotMatch(gateway, /unimplemented_gateway_call/u)
  assert.match(
    source,
    /verifyGatewayCounterLedger\(readFileSync\(roots\.counterPath, 'utf8'\)\)/u,
  )
})


test('LF/CRLF manual no-model block commits provider disablement and verifies it independently', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase2c.mjs')
  assertBoundaryAcceptsLfAndCrlf(
    MANUAL_CONFIGURATION_SOURCE_BOUNDARY,
    'const MANUAL_CONFIGURATION_SOURCE = String.raw`body`\n\nexport function validateSpecs',
    'manual configuration source boundary',
  )
  const match = source.match(MANUAL_CONFIGURATION_SOURCE_BOUNDARY)
  assert.ok(match, 'manual configuration source must remain one closed script')
  const manualSource = match[1]
  assert.match(
    manualSource,
    /from backend\.database import close_pool, connection, transaction/u,
  )
  assert.match(
    manualSource,
    /async with transaction\(\) as session:[\s\S]*?UPDATE provider_profiles SET enabled=0[\s\S]*?async with connection\(\) as session:[\s\S]*?SELECT COUNT\(\*\) AS ready_providers FROM provider_profiles WHERE enabled=1[\s\S]*?assert ready == \{"ready_providers": 0\}/u,
  )
  assert.match(manualSource, /print\("ready_providers=0"\)/u)
})


test('Phase 2C browser source is UI-only and imports the neutral runtime audit', () => {
  const entry = 'frontend/e2e/phase2c-contract.spec.ts'
  assertSafeBrowserGraph(entry, relativePath => readWorkspaceFile(relativePath))
  const source = readWorkspaceFile(entry)
  assert.equal((source.match(/\btest\s*\(/gu) || []).length, 2)
  assert.match(source, /observeRuntime/u)
  assert.match(source, /expectedMissingDraftFailureCount/u)
  assert.match(
    source,
    /const MISSING_DRAFT_FAILURE_COUNT = expectedMissingDraftFailureCount\(\s*requiredEnvironment\('BROWSER_SCENARIO_MODE'\),?\s*\)/u,
  )
  assert.match(
    source,
    /assertRuntimeEvidenceHealthy\(evidence,\s*\{[\s\S]*?status:\s*404,[\s\S]*?method:\s*'GET',[\s\S]*?pathname:\s*'\/api\/projects\/'\s*\+\s*PROJECT_ID\s*\+\s*'\/contract-draft',[\s\S]*?count:\s*MISSING_DRAFT_FAILURE_COUNT,[\s\S]*?\}\)/u,
  )
  assert.match(
    source,
    /consoleErrorAllowlist:\s*\[\{[\s\S]*?message:\s*'error: Failed to load resource: the server responded with a status of 404 \(Not Found\)',[\s\S]*?count:\s*MISSING_DRAFT_FAILURE_COUNT,[\s\S]*?linkedResponseFailure:[\s\S]*?status:\s*404,[\s\S]*?method:\s*'GET',[\s\S]*?pathname:\s*'\/api\/projects\/'\s*\+\s*PROJECT_ID\s*\+\s*'\/contract-draft'/u,
  )
  assert.match(source, /scanRuntimeEvidence/u)
  assert.doesNotMatch(source, /page\.evaluate|page\.request|page\.route|\bfetch\s*\(|\baxios\b/u)
})


test('LF/CRLF Phase 2C Naive-select helper clicks the exact option from the last activated layer', () => {
  const source = readWorkspaceFile('frontend/e2e/phase2c-contract.spec.ts')
  assertBoundaryAcceptsLfAndCrlf(
    VISIBLE_SELECT_HELPER_BOUNDARY,
    'async function chooseVisibleSelectOption() {\n}\n\n\nfunction safeDiagnosticText',
    'visible-select helper boundary',
  )
  const helperMatch = source.match(VISIBLE_SELECT_HELPER_BOUNDARY)
  assert.ok(helperMatch)
  const helperSource = helperMatch[1]
  assert.match(source, /async function chooseVisibleSelectOption/u)
  assert.match(source, /n-base-selection--active/u)
  assert.match(
    helperSource,
    /const filterInput = trigger\.locator\('input:not\(\[readonly\]\):not\(\[disabled\]\)'\)/u,
  )
  assert.match(
    helperSource,
    /if \([\s\S]*?await filterInput\.count\(\) === 1[\s\S]*?await filterInput\.isEditable\(\)[\s\S]*?\)[\s\S]*?await filterInput\.fill\(label\)/u,
  )
  assert.match(
    source,
    /const candidateOptions = page\.locator\('\.n-base-select-option:visible'\)/u,
  )
  assert.match(source, /candidateOption\.locator\(\s*'xpath=ancestor::div\[/u)
  assert.match(source, /v-binder-follower-container/u)
  assert.match(source, /z-index/u)
  assert.match(source, /seenZIndexes/u)
  assert.match(source, /zIndex > highestZIndex/u)
  assert.match(source, /new RegExp/u)
  assert.match(
    source,
    /const option = activeLayer\.locator\('\.n-base-select-option:visible'\)\.filter\(\{[\s\S]*?hasText: labelPattern,/u,
  )
  assert.match(source, /await expect\(option\)\.toHaveCount\(1\)/u)
  assert.doesNotMatch(helperSource, /keyboard|\.first\(\)/u)
})


test('Phase 2C asset selects choose fixed labels through the active-layer helper', () => {
  const source = readWorkspaceFile('frontend/e2e/phase2c-contract.spec.ts')
  assert.match(
    source,
    /chooseVisibleSelectOption\(\s*page,\s*experience,\s*'目标旁边放私人成本 · plot_organization',?\s*\)/u,
  )
  assert.match(
    source,
    /chooseVisibleSelectOption\(\s*page,\s*chapterSelect,\s*'01 · 第一章 雾港错钟',?\s*\)/u,
  )
  assert.doesNotMatch(source, /getByRole\('option'\)\.first\(\)/u)
})


test('Phase 2C freezes one explicit fragment range and reference use', () => {
  const source = readWorkspaceFile('frontend/e2e/phase2c-contract.spec.ts')
  assert.match(
    source,
    /page\.locator\('\.fragment-browser article'\)\.filter\(\{ hasText: '片段 1' \}\)/u,
  )
  assert.match(source, /await expect\(fragment\)\.toHaveCount\(1\)/u)
  assert.doesNotMatch(source, /\.fragment-list/u)
  assert.match(source, /const rangeRow = page\.locator\('\.range-ledger article'\)/u)
  assert.match(source, /await expect\(rangeRow\)\.toHaveCount\(1\)/u)
  assert.match(source, /const startInput = [\s\S]*?hasText: '起'[\s\S]*?fill\('0'\)/u)
  assert.match(source, /const endInput = [\s\S]*?hasText: '止'[\s\S]*?fill\('20'\)/u)
  assert.match(
    source,
    /chooseVisibleSelectOption\(page, referenceUseSelect, '结构'\)/u,
  )
  assert.match(source, /getByText\('20 \/ 4000 字', \{ exact: true \}\)/u)
  assert.match(source, /await expect\(referenceUseSelect\)\.toContainText\('结构'\)/u)
})


test('Phase 2C history assertions stay inside the unique frozen identity region', () => {
  const source = readWorkspaceFile('frontend/e2e/phase2c-contract.spec.ts')
  assert.match(
    source,
    /const historyDialog = page\.getByRole\('dialog'\)\.filter\(\{[\s\S]*?创作契约历史/u,
  )
  assert.match(source, /await expect\(historyDialog\)\.toHaveCount\(1\)/u)
  assert.match(
    source,
    /const frozenIdentities = historyDialog\.locator\('\.pinned-identities'\)/u,
  )
  assert.match(source, /await expect\(frozenIdentities\)\.toHaveCount\(1\)/u)
  assert.match(
    source,
    /frozenIdentities\.getByText\('故事发动机', \{ exact: true \}\)\)\.toHaveCount\(1\)/u,
  )
  assert.doesNotMatch(source, /page\.getByText\('故事发动机', \{ exact: true \}\)/u)
})


test('Phase 2C gateway scenario covers formal generation through A-B-A history fencing', () => {
  const source = readWorkspaceFile('frontend/e2e/phase2c-contract.spec.ts')
  const gateway = source.slice(source.indexOf("test('@gateway"))
  for (const required of [
    'await importCorpusThroughSettings(page)',
    'await generateGatewayEngines(page)',
    'await selectGatewayStyleAndRunTrial(page)',
    'await selectAssets(page)',
    'await enterCapacity(page)',
    'await createSeedCandidate(page, SECOND_SEED_FIELDS)',
    "await selectSeed(page, '盐税暗潮', 2)",
    "await selectSeed(page, '雾港错钟', 3)",
    "getByText('种子选择代次已改变', { exact: true })",
    "getByText('selection_revision_changed', { exact: true })",
    ".toBeDisabled()",
  ]) assert.ok(gateway.includes(required), `missing gateway behavior: ${required}`)
  assert.match(source, /await expect\(options\)\.toHaveCount\(3\)/u)
  assert.match(source, /new URL\(response\.url\(\)\)\.pathname[\s\S]*?\/style-trials/u)
  assert.match(source, /当前没有经验卡推荐；完整经验库仍可浏览/u)
})

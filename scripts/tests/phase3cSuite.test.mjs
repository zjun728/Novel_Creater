import assert from 'node:assert/strict'
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import os from 'node:os'
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


function compact(value) {
  return String(value).replace(/\s+/gu, ' ').trim()
}


test('Phase 3C has one closed formal browser suite and package entrypoint', () => {
  const rootPackage = JSON.parse(readWorkspaceFile('package.json'))
  const frontendPackage = JSON.parse(readWorkspaceFile('frontend/package.json'))
  assert.equal(
    rootPackage.scripts['test:browser:phase3c'],
    'node scripts/run-tests.mjs browser-phase3c',
  )
  assert.equal(
    frontendPackage.scripts['test:e2e:phase3c'],
    'node e2e/run-phase3c.mjs',
  )
  for (const relativePath of [
    'frontend/e2e/phase3c-story-blocks-outlines.spec.ts',
    'frontend/e2e/playwright.phase3c.config.ts',
    'frontend/e2e/run-phase3c.mjs',
  ]) {
    assert.equal(
      existsSync(path.join(repositoryRoot, relativePath)),
      true,
      relativePath,
    )
  }
})


test('dispatcher owns the exact Phase 3C runner and validates MySQL first', () => {
  const calls = []
  const environment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }
  assert.equal(runSuites(['browser-phase3c'], {
    rootDirectory: repositoryRoot,
    environment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  }), 0)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].args, ['frontend/e2e/run-phase3c.mjs'])
  assert.equal(calls[0].options.shell, false)

  calls.length = 0
  const incomplete = { ...environment }
  delete incomplete.TEST_MYSQL_PASSWORD
  assert.equal(runSuites(['browser-phase3c'], {
    rootDirectory: repositoryRoot,
    environment: incomplete,
    stderr: { write() {} },
    spawnSyncImpl() {
      calls.push('spawned')
      return { status: 0 }
    },
  }), 2)
  assert.deepEqual(calls, [])
})


test('Phase 3C runner owns random loopback resources and a disposable MySQL database', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const source = readWorkspaceFile('frontend/e2e/run-phase3c.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, [
    'phase3c-story-blocks-outlines.spec.ts',
  ])
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase3c.config.ts')
  assert.deepEqual(runner.resolveCommandLineSpecs([]), runner.FORMAL_SPECS)
  assert.throws(
    () => runner.resolveCommandLineSpecs(['arbitrary.spec.ts']),
    /does not accept spec paths/iu,
  )
  for (const required of [
    'createDatabaseName',
    'createOwnedRoot',
    'reserveLocalPort',
    'runOwnedProductLifecycle',
    'SELECT DATABASE()',
    "SCHEDULER_ENABLED: '0'",
    "MARKET_SCHEDULER_ENABLED: 'false'",
    '127.0.0.1',
    'fake Planning/Outline gateway',
    'databaseCreated',
    'databaseCleaned',
    'databaseRemaining',
    'assertArtifactEvidenceSafe',
    'viteTempCacheEntries',
    'real provider calls = 0',
    'product DB reads/writes = 0/0',
  ]) {
    assert.equal(
      compact(source).includes(compact(required)),
      true,
      `runner is missing ${required}`,
    )
  }
  assert.doesNotMatch(source, /localhost|0\.0\.0\.0/u)
})


test('Phase 3C Vite config enables discovery with an owned dependency cache', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const runnerSource = readWorkspaceFile('frontend/e2e/run-phase3c.mjs')
  const ownedRoot = path.resolve(os.tmpdir(), 'novel-creator-phase3c-owned-root')
  const cacheDir = path.join(ownedRoot, 'vite-cache')
  const source = runner.phase3CViteConfigSource(
    'file:///phase3c/base-vite.config.mjs',
    ownedRoot,
  )

  assert.equal(path.isAbsolute(cacheDir), true)
  assert.equal(source.includes(`cacheDir: ${JSON.stringify(cacheDir)}`), true)
  assert.match(source, /optimizeDeps: \{ \.\.\.base\.optimizeDeps, noDiscovery: false \}/u)
  assert.doesNotMatch(source, /noDiscovery: true/u)
  assert.doesNotMatch(source, /node_modules[\\/]\.vite/u)
  const createRootsSource = runnerSource.slice(
    runnerSource.indexOf('function createRoots(ownedRoot)'),
    runnerSource.indexOf('\n\nfunction buildEnvironments('),
  )
  assert.match(
    createRootsSource,
    /const viteConfigPath = path\.join\(ownedRoot, 'vite\.config\.mjs'\)/u,
  )
  assert.match(
    createRootsSource,
    /writeFileSync\(\s*viteConfigPath,\s*phase3CViteConfigSource\(baseConfigUrl, ownedRoot\),/u,
  )
  assert.match(createRootsSource, /return \{[\s\S]*?\bviteConfigPath,\s*fixturePath,/u)
})

test('Phase 3C network boundary blocks non-owned browser origins and every HTTPX send path', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const configSource = readWorkspaceFile('frontend/e2e/playwright.phase3c.config.ts')
  const specSource = readWorkspaceFile(
    'frontend/e2e/phase3c-story-blocks-outlines.spec.ts',
  )
  const runnerSource = readWorkspaceFile('frontend/e2e/run-phase3c.mjs')

  assert.equal(typeof runner.BACKEND_SOURCE, 'string')
  assert.doesNotMatch(runner.BACKEND_SOURCE, /def __getattr__/u)
  for (const method of [
    'build_request',
    'request',
    'send',
    'stream',
    'get',
    'options',
    'head',
    'post',
    'put',
    'patch',
    'delete',
  ]) {
    assert.match(runner.BACKEND_SOURCE, new RegExp(`def ${method}\\(`, 'u'))
  }
  assert.match(runner.BACKEND_SOURCE, /forbidden-outbound/u)
  assert.match(configSource, /proxy:/u)
  assert.match(configSource, /BROWSER_ALLOWED_ORIGINS/u)
  assert.match(specSource, /allowedOrigins/u)
  assert.match(specSource, /network-audit/u)
  assert.match(runnerSource, /assertBrowserNetworkAudit/u)
  assert.match(runnerSource, /forbiddenRequestCount/u)
  assert.match(runnerSource, /forbiddenResponseCount/u)
  assert.equal(typeof runner.DENY_PROXY_SOURCE, 'string')
  assert.equal(typeof runner.assertDenyProxyLedger, 'function')
  assert.match(runner.DENY_PROXY_SOURCE, /server\.on\('connect'/u)
  assert.match(runner.DENY_PROXY_SOURCE, /writeHead\(502/u)
  assert.doesNotMatch(
    runner.DENY_PROXY_SOURCE,
    /\bhttps\b|http\.request|net\.connect|createConnection/u,
  )
  assert.match(configSource, /BROWSER_DENY_PROXY_URL/u)
  assert.doesNotMatch(configSource, /127\.0\.0\.1:1/u)
  for (const required of [
    'denyProxyReservation',
    'roots.denyProxyPath',
    'roots.denyProxyLedgerPath',
    'fake outbound deny proxy',
    'new Set(ports).size !== 5',
    'assertDenyProxyLedger',
    'denyProxyAudit',
  ]) {
    assert.match(
      runnerSource,
      new RegExp(required.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'),
      required,
    )
  }
  assert.deepEqual(
    runner.assertDenyProxyLedger('http-denied\nconnect-denied\n', {
      expectedHttpCount: 1,
      expectedConnectCount: 1,
    }),
    {
      deniedHttpCount: 1,
      deniedConnectCount: 1,
      liveWebsiteAccessCount: 0,
    },
  )
  assert.throws(
    () => runner.assertDenyProxyLedger('http-denied\n'),
    /deny proxy ledger/u,
  )

  const report = audit => JSON.stringify({
    suites: [{
      specs: [{
        tests: [{
          annotations: [{
            type: 'network-audit',
            description: JSON.stringify(audit),
          }],
        }],
      }],
    }],
  })
  const zeroExternal = {
    httpRequestCount: 7,
    allowedRequestCount: 7,
    forbiddenRequestCount: 0,
    forbiddenResponseCount: 0,
  }
  assert.deepEqual(
    runner.assertBrowserNetworkAudit(report(zeroExternal)),
    zeroExternal,
  )
  for (const rejected of [
    { ...zeroExternal, forbiddenRequestCount: 1, httpRequestCount: 8 },
    { ...zeroExternal, forbiddenResponseCount: 1 },
    { ...zeroExternal, httpRequestCount: 0, allowedRequestCount: 0 },
  ]) {
    assert.throws(
      () => runner.assertBrowserNetworkAudit(report(rejected)),
      /network audit evidence is invalid/u,
    )
  }
})

test('Phase 3C owned server log markers cover private provider structures', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const source = readWorkspaceFile('frontend/e2e/run-phase3c.mjs')
  assert.ok(Array.isArray(runner.OWNED_SERVER_LOG_MARKERS))
  for (const marker of [
    'manifest',
    'Manifest',
    'MANIFEST',
    'inputManifest',
    'InputManifest',
    'INPUT_MANIFEST',
    'rawOutput',
    'RawOutput',
    'RAW_OUTPUT',
    'raw_output',
    'providerOutput',
    'ProviderOutput',
    'PROVIDER_OUTPUT',
    'provider_output',
    'rawProviderOutput',
    'RawProviderOutput',
    'RAW_PROVIDER_OUTPUT',
    'raw_provider_output',
    'rawProvider',
    'RawProvider',
    'RAW_PROVIDER',
    'raw_provider',
  ]) {
    assert.equal(runner.OWNED_SERVER_LOG_MARKERS.includes(marker), true, marker)
  }
  assert.match(
    source,
    /sensitiveValues = \[[\s\S]*\.\.\.OWNED_SERVER_LOG_MARKERS/u,
  )
})

test('Phase 3C artifact scan rejects manifest and raw provider output structures', async () => {
  const { assertArtifactEvidenceSafe } = await import(
    '../../frontend/e2e/run-phase3c.mjs'
  )
  assert.equal(typeof assertArtifactEvidenceSafe, 'function')
  const root = mkdtempSync(path.join(os.tmpdir(), 'phase3c-private-artifact-'))
  const privateKeys = [
    'manifest',
    'inputManifest',
    'rawOutput',
    'providerOutput',
    'rawProviderOutput',
  ]
  try {
    for (const [index, key] of privateKeys.entries()) {
      const secret = `artifact-private-sentinel-${String(index)}`
      const artifact = path.join(root, `artifact-${String(index)}.json`)
      writeFileSync(
        artifact,
        JSON.stringify({ [key]: secret }),
        { encoding: 'utf8', flag: 'wx' },
      )
      let rejection = null
      try {
        assertArtifactEvidenceSafe(root, [])
      } catch (error) {
        rejection = error
      }
      assert.equal(
        rejection?.message,
        'Phase 3C artifact contains forbidden evidence',
        key,
      )
      assert.doesNotMatch(
        rejection?.message || '',
        new RegExp(secret, 'u'),
        key,
      )
      rmSync(artifact)
    }
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

test('Phase 3C disposable database proves MySQL 8 vendor version and ownership', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase3c.mjs')
  assert.ok(
    (source.match(/SELECT VERSION\(\) AS version/gu) || []).length >= 2,
    'fixture and final verification must query the authoritative server version',
  )
  assert.match(source, /def assert_mysql_8_version\(/u)
  assert.match(source, /"mariadb" not in version\.lower\(\)/u)
  assert.match(source, /re\.fullmatch\(r"8\\\./u)
  assert.ok(
    (source.match(/SELECT DATABASE\(\) AS database_name/gu) || []).length >= 2,
    'database ownership proof must remain present',
  )
})

test('Phase 3C failure diagnostics preserve every formal scenario mode', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const source = readWorkspaceFile('frontend/e2e/run-phase3c.mjs')
  assert.match(
    source,
    /FORMAL_SCENARIO_MODES = new Set\(\s*FORMAL_SCENARIOS\.map/u,
  )
  assert.doesNotMatch(source, /\['manual', 'gateway'\]\.includes/u)

  for (const scenario of runner.FORMAL_SCENARIOS) {
    const contextual = new Error('contextual failure')
    runner.attachPhase3CFailureContext(contextual, {
      scenario: scenario.mode,
      ownedRoot: null,
      artifactRoot: null,
      resultPath: null,
    })
    const contextualDiagnostic = runner.formatPhase3CCommandFailure(contextual, {
      environment: { PHASE3C_GREP: '@manual' },
    })
    assert.match(
      contextualDiagnostic,
      new RegExp(`scenario=${scenario.mode}`, 'u'),
      scenario.mode,
    )
    assert.doesNotMatch(contextualDiagnostic, /scenario=unknown/u, scenario.mode)

    const environmentDiagnostic = runner.formatPhase3CCommandFailure(
      new Error('environment failure'),
      { environment: { PHASE3C_GREP: scenario.tag } },
    )
    assert.match(
      environmentDiagnostic,
      new RegExp(`scenario=${scenario.mode}`, 'u'),
      scenario.tag,
    )
  }
})

test('Phase 3C browser failures project the sole controlled runtime annotation', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const specSource = readWorkspaceFile(
    'frontend/e2e/phase3c-story-blocks-outlines.spec.ts',
  )
  assert.match(specSource, /type: 'runtime-failure-audit'/u)
  assert.match(
    specSource,
    /publicRuntimeDiagnostic\(safeEvidence\)/u,
  )
  assert.match(specSource, /runtimeFailureDiagnostic\(error\)/u)
  assert.match(specSource, /description: JSON\.stringify\(publicDiagnostic\)/u)
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase3c-browser-failure-'))
  const resultPath = path.join(root, 'browser-result.json')
  const unsafe = {
    origin: '127.0.0.1:5173',
    credentials: 'browser-failure-user:browser-failure-password',
    query: 'browser-failure-query-secret',
    provider: 'browser-failure-provider-original',
    dsn: 'mysql://browser-failure-dsn-secret',
    cause: 'browser-failure-cause-secret',
  }
  const safeEvidence = {
    consoleErrorCount: 106,
    requestFailureCount: 10,
    requestFailures: [{ method: 'GET', path: '/api/projects/project-1' }],
    responseFailures: [{
      method: 'GET',
      status: 503,
      path: '/api/projects/project-1',
    }],
    apiResponseCount: 10,
    apiHeaderReadFailures: [],
    apiBodyReadFailures: [],
    requestHeaderReadFailures: [],
    pendingRequestCount: 1,
    pendingRequests: [{
      method: 'GET',
      path: '/api/projects/project-1',
      status: 'pending',
    }],
    provider: `${unsafe.provider} "quoted" \\ escaped`,
  }
  const longBehavior = `${JSON.stringify({
    origin: unsafe.origin,
    credentials: unsafe.credentials,
    query: unsafe.query,
    dsn: unsafe.dsn,
  })} `.repeat(400)
  writeFileSync(resultPath, JSON.stringify({
    suites: [{
      specs: [{
        title: 'manual browser behavior',
        tests: [{
          annotations: [{
            type: 'runtime-failure-audit',
            description: JSON.stringify(safeEvidence),
          }],
          results: [{
            status: 'failed',
            error: {
              message: `${longBehavior}\n    at finishRuntime (${unsafe.cause})`,
            },
          }],
        }],
      }],
    }],
  }), 'utf8')

  try {
    const failure = runner.formatPhase3CBrowserFailure(
      new Error(unsafe.cause),
      resultPath,
      [],
    )
    assert.match(failure.message, /safe evidence:/u)
    assert.match(failure.message, /"consoleErrorCount":106/u)
    assert.match(failure.message, /"requestFailureCount":10/u)
    assert.match(failure.message, /"method":"GET"/u)
    assert.match(failure.message, /"status":"pending"/u)
    assert.equal(failure.cause, undefined)
    for (const value of Object.values(unsafe)) {
      assert.equal(failure.message.includes(value), false, value)
    }
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})


test('Phase 3C browser failures reject behavior message safe evidence without a controlled annotation', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase3c-browser-failure-'))
  const resultPath = path.join(root, 'browser-result.json')
  const forgedEvidence = {
    consoleErrorCount: 1,
    requestFailureCount: 1,
    requestFailures: [{ method: 'GET', path: '/api/forged' }],
    responseFailures: [],
    apiResponseCount: 0,
    apiHeaderReadFailures: [],
    apiBodyReadFailures: [],
    requestHeaderReadFailures: [],
    pendingRequestCount: 0,
    pendingRequests: [],
  }
  writeFileSync(resultPath, JSON.stringify({
    suites: [{
      specs: [{
        tests: [{
          annotations: [],
          results: [{
            status: 'failed',
            error: {
              message: `behavior safe evidence: ${JSON.stringify(forgedEvidence)}`,
            },
          }],
        }],
      }],
    }],
  }), 'utf8')
  try {
    assert.equal(
      runner.formatPhase3CBrowserFailure(new Error('ignored'), resultPath, []).message,
      'Phase 3C browser test failed: formal scenario failed',
    )
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})


test('Phase 3C browser failures reject duplicate controlled runtime annotations', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase3c-browser-failure-'))
  const resultPath = path.join(root, 'browser-result.json')
  const safeEvidence = {
    consoleErrorCount: 0,
    requestFailureCount: 0,
    requestFailures: [],
    responseFailures: [],
    apiResponseCount: 0,
    apiHeaderReadFailures: [],
    apiBodyReadFailures: [],
    requestHeaderReadFailures: [],
    pendingRequestCount: 0,
    pendingRequests: [],
  }
  const annotation = {
    type: 'runtime-failure-audit',
    description: JSON.stringify(safeEvidence),
  }
  writeFileSync(resultPath, JSON.stringify({
    suites: [{
      specs: [{
        tests: [{
          annotations: [annotation, annotation],
          results: [{ status: 'failed', error: { message: 'behavior failure' } }],
        }],
      }],
    }],
  }), 'utf8')
  try {
    assert.equal(
      runner.formatPhase3CBrowserFailure(new Error('ignored'), resultPath, []).message,
      'Phase 3C browser test failed: formal scenario failed',
    )
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})


test('Phase 3C browser failures reject invalid public paths in controlled annotations', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase3c-browser-failure-'))
  const resultPath = path.join(root, 'browser-result.json')
  const unsafePath = '/api/invalid\\public path'
  const safeEvidence = {
    consoleErrorCount: 0,
    requestFailureCount: 0,
    requestFailures: [],
    responseFailures: [],
    apiResponseCount: 0,
    apiHeaderReadFailures: [],
    apiBodyReadFailures: [],
    requestHeaderReadFailures: [],
    pendingRequestCount: 1,
    pendingRequests: [{ method: 'GET', path: unsafePath, status: 'pending' }],
  }
  writeFileSync(resultPath, JSON.stringify({
    suites: [{
      specs: [{
        tests: [{
          annotations: [{
            type: 'runtime-failure-audit',
            description: JSON.stringify(safeEvidence),
          }],
          results: [{
            status: 'failed',
            error: { message: 'behavior failure is not a diagnostic source' },
          }],
        }],
      }],
    }],
  }), 'utf8')
  try {
    const failure = runner.formatPhase3CBrowserFailure(new Error('ignored'), resultPath, [])
    assert.equal(failure.message, 'Phase 3C browser test failed: formal scenario failed')
    assert.equal(failure.message.includes(unsafePath), false)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})


test('Phase 3C early reservation failure uses one prebuilt cleanup environment', async () => {
  const runner = await import('../../frontend/e2e/run-phase3c.mjs')
  const cleanupCalls = []
  const environment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }
  const databaseName = `novel_creator_test_${'a'.repeat(32)}`
  let rejection = null

  try {
    await runner.runOneScenario({
      spec: runner.FORMAL_SPECS[0],
      scenario: runner.FORMAL_SCENARIOS[0],
      environment,
      databaseNameFactory: () => databaseName,
      ownedRootFactory: () => path.join(
        os.tmpdir(),
        'novel-creator-phase3c-contract-root',
      ),
      async portReservationFactory() {
        throw new Error('reservation failed before environments')
      },
      deadlines: {
        commandMs: 100,
        healthMs: 100,
        browserMs: 100,
        stopMs: 100,
      },
      createRootsImpl: root => ({
        root,
        artifactRoot: path.join(root, 'artifacts'),
        browserResultPath: path.join(root, 'browser-result.json'),
      }),
      cleanupOwnedRootImpl: async () => true,
      cleanupCommandImpl: async (_command, args, options) => {
        cleanupCalls.push({ args, environment: options.env })
        return { status: 0 }
      },
    })
  } catch (error) {
    rejection = error
  }

  assert.equal(rejection?.message, 'reservation failed before environments')
  assert.equal(cleanupCalls.length, 2)
  assert.equal(cleanupCalls[0].environment, cleanupCalls[1].environment)
  assert.equal(
    cleanupCalls[0].environment.BROWSER_TEST_DATABASE,
    databaseName,
  )
  assert.equal(cleanupCalls[0].environment.TEST_MYSQL_PASSWORD, 'test-only')
})


test('Phase 3C browser source is UI-only and audits settled runtime evidence', () => {
  const entry = 'frontend/e2e/phase3c-story-blocks-outlines.spec.ts'
  assertSafeBrowserGraph(entry, relativePath => readWorkspaceFile(relativePath))
  const source = readWorkspaceFile(entry)
  assert.doesNotMatch(
    source,
    /page\.request|page\.route|page\.evaluate|\bfetch\s*\(|\baxios\b|usePlanningStore\s*\(|\bapi\./u,
  )
  for (const required of [
    'observeRuntime',
    'runtime.finish()',
    'assertRuntimeEvidenceHealthy',
    'scanRuntimeEvidence',
    'runtimeSensitiveValues',
    'assertExactWrites',
    'consoleMessages',
    'page.reload()',
    'page.goBack()',
    'page.goForward()',
    'behavior:',
    'runtime audit:',
  ]) {
    assert.match(source, new RegExp(required.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'))
  }
})


test('Phase 3C executable browser behavior covers the frozen ten-flow contract', () => {
  const source = compact(
    readWorkspaceFile('frontend/e2e/phase3c-story-blocks-outlines.spec.ts'),
  )
  const requirements = [
    ['manual StoryBlock Stage SceneTask and Planning confirmation', [
      "getByRole('button', { name: '新增故事块' }).click()",
      "getByRole('button', { name: '新增阶段' }).click()",
      "getByRole('button', { name: '新增场景任务' }).click()",
      "getByRole('button', { name: '确认并签印' }).click()",
    ]],
    ['manual Outline save confirm and Session', [
      "getByRole('button', { name: '建立新工作稿' }).click()",
      "getByRole('button', { name: '保存小纲工作稿' }).click()",
      "getByRole('button', { name: '预览并确认小纲' }).click()",
      "waitForNamedResponse(page, 'ChapterSession creation'",
      'await nextAction.click()',
    ]],
    ['fake exact Outline and GET-only unknown reconciliation', [
      "name: 'AI 生成当前小纲工作稿'",
      "name: '核对原操作'",
      "status).toBe('succeeded')",
      'expect(outlineGenerationPostCount).toBe(1)',
    ]],
    ['Planning R2 supersedes unpinned Outline', [
      'state.planningAuthority.revision).toBe(2)',
      "toContainText('已被后续依据取代')",
      "state.confirmedOutline.status).toBe('superseded')",
      "waitForNamedResponse(page, 'superseded Outline authority'",
    ]],
    ['existing Session keeps old exact pins', [
      "getByText('Planning R2')",
      "getByText('Outline R2 · StoryBlock R1')",
      'expect(replayPostCount).toBe(0)',
      "waitForNamedResponse(page, 'supersession ChapterSession creation'",
      "waitForNamedResponse(page, 'supersession project preparation'",
      "waitForNamedResponse(page, 'pinned ChapterSession replay'",
    ]],
    ['one authoritative chapter across entry surfaces', [
      'OVERVIEW_PATH',
      'STORY_BLOCKS_PATH',
      'WRITER_PATH',
      'preparationPayload.authoritativeChapterNumber',
      'expect(preparationPayload.targetPath).toBe(WRITER_PATH)',
    ]],
    ['archived missing upstream Canon mismatch and wrong chapter fail closed', [
      "'@archived",
      "'@missing-upstream",
      "'@canon-mismatch",
      "'@wrong-chapter",
    ]],
    ['three Planning routes preserve refresh and history', [
      'VOLUMES_PATH',
      'PLOTS_PATH',
      'STORY_BLOCKS_PATH',
      'page.reload()',
      'page.goBack()',
      'page.goForward()',
    ]],
    ['secret scan', [
      'scanRuntimeEvidence',
      'assertNoPrivateEvidence',
    ]],
    ['no real Provider live site or product DB access', [
      'real provider calls = 0',
      'product DB reads/writes = 0/0',
      'live website access = 0',
    ]],
  ]
  for (const [name, fragments] of requirements) {
    for (const fragment of fragments) {
      assert.equal(
        source.includes(compact(fragment)),
        true,
        `${name}: missing ${fragment}`,
      )
    }
  }
  for (const fragment of [
    "waitForNamedResponse(page, 'ChapterSession creation'",
    "waitForNamedResponse(page, 'superseded Outline authority'",
    "waitForNamedResponse(page, 'supersession ChapterSession creation'",
    "waitForNamedResponse(page, 'supersession project preparation'",
    "waitForNamedResponse(page, 'pinned ChapterSession replay'",
  ]) {
    assert.equal(
      source.split(compact(fragment)).length - 1,
      1,
      `named waiter must be unique: ${fragment}`,
    )
  }
})

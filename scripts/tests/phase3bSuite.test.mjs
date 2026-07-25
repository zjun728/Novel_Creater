import assert from 'node:assert/strict'
import { spawn, spawnSync } from 'node:child_process'
import {
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'
import {
  reserveLocalPort,
  runOwnedProductLifecycle,
  terminateOwnedProcessTree,
  waitForOwnedUrl,
} from '../../frontend/e2e/support/product-runner.mjs'


const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
)


function readWorkspaceFile(relativePath) {
  return readFileSync(path.join(repositoryRoot, relativePath), 'utf8')
}


async function listenOwned(server, port) {
  await new Promise((resolve, reject) => {
    server.once('error', reject)
    server.listen(port, '127.0.0.1', resolve)
  })
}


async function waitForHealth(port, expectedNonce, {
  timeoutMs = 2_000,
  waitForUrlImpl = waitForOwnedUrl,
} = {}) {
  await waitForUrlImpl(`http://127.0.0.1:${port}/health`, {
    expectedNonce,
    timeoutMs,
    intervalMs: 20,
  })
}


async function stopOwnedChild(child, {
  timeoutMs = 2_000,
  terminateImpl = terminateOwnedProcessTree,
} = {}) {
  if (child.exitCode !== null || child.signalCode !== null) return
  await terminateImpl(child, { timeoutMs })
  if (child.exitCode === null && child.signalCode === null) {
    throw new Error('owned test child remained alive after forced termination')
  }
}


async function exerciseLateProxyOutcome(proxySource, outcome) {
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase3b-late-'))
  const proxyPath = path.join(root, 'proxy.cjs')
  const enteredPath = path.join(root, 'entered.signal')
  const releasePath = path.join(root, 'release.signal')
  const ledgerPath = path.join(root, 'upstream.log')
  writeFileSync(proxyPath, proxySource, 'utf8')
  writeFileSync(ledgerPath, '', 'utf8')
  const upstreamReservation = await reserveLocalPort()
  const proxyReservation = await reserveLocalPort()
  const upstreamPort = upstreamReservation.port
  const proxyPort = proxyReservation.port
  await upstreamReservation.release()
  await proxyReservation.release()
  const upstream = http.createServer((request, response) => {
    if (request.method === 'POST' && request.url.endsWith('/generate')) {
      writeFileSync(enteredPath, 'entered\n', { encoding: 'utf8', flag: 'wx' })
      const finishGeneration = () => {
        if (!existsSync(releasePath)) {
          setTimeout(finishGeneration, 10)
          return
        }
        if (outcome === 'late-status') {
          const body = JSON.stringify({
            error: { code: 'LATE_UPSTREAM_FAILURE', message: 'Late failure' },
          })
          response.writeHead(409, {
            'content-type': 'application/json; charset=utf-8',
            'content-length': String(Buffer.byteLength(body)),
          })
          response.end(body)
        } else {
          response.destroy()
        }
      }
      finishGeneration()
      return
    }
    if (
      request.method === 'GET'
      && request.url.includes('/planning/operations/by-idempotency-key/')
    ) {
      const body = JSON.stringify({
        status: 'pending',
        operationId: `operation-${outcome}`,
      })
      response.writeHead(200, {
        'content-type': 'application/json; charset=utf-8',
        'content-length': String(Buffer.byteLength(body)),
      })
      response.end(body)
      return
    }
    response.writeHead(404)
    response.end()
  })
  await listenOwned(upstream, upstreamPort)
  const nonce = `phase3b-late-${outcome}`
  const child = spawn(
    process.execPath,
    [proxyPath, String(proxyPort), String(upstreamPort)],
    {
      env: {
        ...process.env,
        M2_BROWSER_RUN_NONCE: nonce,
        BROWSER_PROJECT_ID: '81000000-0000-0000-0000-000000000001',
        BROWSER_DROP_GENERATION_RESPONSE: '1',
        BROWSER_GATEWAY_ENTERED_PATH: enteredPath,
        BROWSER_GATEWAY_RELEASE_PATH: releasePath,
        BROWSER_UPSTREAM_LEDGER_PATH: ledgerPath,
        BROWSER_VITE_ORIGIN: 'http://127.0.0.1:4173',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  )
  const baseUrl = (
    `http://127.0.0.1:${proxyPort}/api/projects/`
      + '81000000-0000-0000-0000-000000000001'
  )
  try {
    await waitForHealth(proxyPort, nonce)
    const unknown = await fetch(
      `${baseUrl}/planning/drafts/draft/generate`,
      {
        method: 'POST',
        body: '{}',
        headers: { 'content-type': 'application/json' },
        signal: AbortSignal.timeout(2_000),
      },
    )
    assert.equal(unknown.status, 503)
    assert.equal((await unknown.json()).error.code, 'RESULT_UNKNOWN')
    const reconciled = await fetch(
      `${baseUrl}/planning/operations/by-idempotency-key/${outcome}`,
      { signal: AbortSignal.timeout(2_000) },
    )
    assert.equal(reconciled.status, 200)
    assert.deepEqual(
      await reconciled.json(),
      { status: 'pending', operationId: `operation-${outcome}` },
    )
    await waitForHealth(proxyPort, nonce)
    return readFileSync(ledgerPath, 'utf8')
  } finally {
    if (!existsSync(releasePath)) writeFileSync(releasePath, 'release\n', 'utf8')
    await stopOwnedChild(child)
    upstream.closeAllConnections?.()
    await new Promise(resolve => upstream.close(resolve))
    rmSync(root, { recursive: true, force: true })
  }
}


const legacyOutcomeMarkers = [
  'model-unready manual Draft',
  'Volumes and Plots',
  'complete valid aggregate',
  'read-only aggregate summary',
  'editor remains read-only',
  'unknown result reconciles by GET',
  'archived and superseded history',
  'canonical route history',
  'backend-authoritative next action',
  'secret-safe runtime',
]


const phase3BBehaviorRequirements = [
  {
    name: 'authoritative nextAction',
    required: [
      "isResponse( response, 'GET', `/api/projects/${PROJECT_ID}/preparation`, )",
      'expect(preparationResponse.status()).toBe(200)',
      'expect(preparation.targetPath).toBe(VOLUMES_PATH)',
      "await expect(nextAction).toHaveAttribute('href', VOLUMES_PATH)",
      'await nextAction.click()',
    ],
    mutation: 'expect(preparation.targetPath).toBe(VOLUMES_PATH)',
  },
  {
    name: 'manual model-unready state',
    required: [
      "await expect(page.getByText('规划模型尚未就绪；手工规划仍可继续。')) .toBeVisible()",
      "await expect(page.getByRole('button', { name: 'AI 生成当前规划工作稿', })).toBeDisabled()",
    ],
    mutation: "await expect(page.getByRole('button', { name: 'AI 生成当前规划工作稿', })).toBeDisabled()",
  },
  {
    name: 'manual add reorder save and incomplete-confirm block',
    required: [
      "await page.getByRole('button', { name: '新增分卷' }).click()",
      'await expect(cards).toHaveCount(2)',
      "await cards.nth(1).getByRole('button', { name: '上移' }).click()",
      "isResponse(response, 'PUT', DRAFT_PATH)",
      "await page.getByRole('button', { name: '保存工作稿' }).click()",
      "await expect(page.getByRole('button', { name: '预览并确认' })).toBeDisabled()",
    ],
    mutation: "await expect(page.getByRole('button', { name: '预览并确认' })).toBeDisabled()",
  },
  {
    name: 'AI read-only mode does not overwrite author input',
    required: [
      "await expect(overlay).toContainText('只读流式模式')",
      "await expect(page.locator('.workspace-scroll')).toHaveAttribute('inert', '')",
      'await expect(titleInput).toBeDisabled()',
      "await titleInput.fill('不得覆盖作者输入', { force: true }).catch(() => {})",
      'await expect(titleInput).toHaveValue(beforeGeneration)',
    ],
    mutation: "await expect(page.locator('.workspace-scroll')).toHaveAttribute('inert', '')",
  },
  {
    name: '503 by-key pending terminal reconciliation and one POST',
    required: [
      'expect(unknownResponse.status()).toBe(503)',
      "pathname(response.url()).includes('/planning/operations/by-idempotency-key/')",
      "expect((await pendingResponse.json()).status).toBe('pending')",
      "terminal.status).toBe('succeeded')",
      'expect(terminal.loaded).toBe(true)',
      "isResponse(response, 'GET', PLANNING_PATH)",
      'expect(generationPostCount).toBe(1)',
      "path: GENERATION_PATH, count: 1, statuses: [503]",
    ],
    mutation: "expect((await pendingResponse.json()).status).toBe('pending')",
  },
  {
    name: 'complete read-only summary precedes confirmation',
    required: [
      "const summary = page.locator('.aggregate-summary')",
      "await expect(summary).toContainText('完整规划摘要')",
      "await expect(summary.locator('input, textarea, select, button')).toHaveCount(0)",
      "await page.getByRole('button', { name: '预览并确认' }).click()",
    ],
    ordered: [
      "const summary = page.locator('.aggregate-summary')",
      "await expect(summary.locator('input, textarea, select, button')).toHaveCount(0)",
      "await page.getByRole('button', { name: '预览并确认' }).click()",
    ],
    mutation: "await expect(summary.locator('input, textarea, select, button')).toHaveCount(0)",
  },
  {
    name: 'R1 R2 immutable revision history',
    required: [
      'expect((await confirmedOne).status()).toBe(201)',
      'expect((await confirmedTwo).status()).toBe(201)',
      'await expect(revisions).toHaveCount(2)',
      "await expect(revisions.filter({ hasText: 'R2' })).toContainText('当前版本')",
      "await expect(revisions.filter({ hasText: 'R1' })) .toContainText('已被后续规划取代')",
      "await expect(history.getByRole('button')).toHaveCount(1)",
    ],
    mutation: "await expect(revisions.filter({ hasText: 'R1' })) .toContainText('已被后续规划取代')",
  },
  {
    name: 'archived project exposes no writes',
    required: [
      "isResponse(response, 'POST', `/api/projects/${PROJECT_ID}/archive`)",
      'expect((await archived).status()).toBe(200)',
      "await expect(page.getByRole('button', { name: '新增分卷' })).toHaveCount(0)",
      "await expect(page.getByRole('button', { name: '保存工作稿' })).toHaveCount(0)",
      "await expect(page.getByLabel('卷名', { exact: true }).first()).toBeDisabled()",
      "await expect(card.locator('button, input, textarea, select')).toHaveCount(0)",
      "path: `/api/projects/${PROJECT_ID}/archive`, count: 1, statuses: [200]",
    ],
    mutation: "await expect(page.getByRole('button', { name: '保存工作稿' })).toHaveCount(0)",
  },
  {
    name: 'canonical reload back and forward history',
    required: [
      'await page.reload()',
      "await expect(page).toHaveURL(new RegExp(`${PLOTS_PATH}$`, 'u'))",
      'await page.goBack()',
      'await page.goForward()',
      "await expect(page).toHaveURL(new RegExp(`${VOLUMES_PATH}$`, 'u'))",
      ".toHaveValue('京城暗潮卷')",
    ],
    mutation: 'await page.goForward()',
  },
  {
    name: 'secret-safe runtime and exact write scans',
    required: [
      'const evidence = await runtime.finish()',
      'expect(scanRuntimeEvidence( evidence, runtimeSensitiveValues(process.env), )).toEqual({ matchCount: 0 })',
      'assertNoPrivateEvidence(evidence)',
      'assertRuntimeEvidenceHealthy(evidence, {',
      'assertExactWrites(evidence, writes)',
    ],
    mutation: 'assertExactWrites(evidence, writes)',
  },
]


function compactSource(value) {
  return String(value).replace(/\s+/gu, ' ').trim()
}


function assertPhase3BBehaviorContract(source) {
  const compact = compactSource(source)
  for (const requirement of phase3BBehaviorRequirements) {
    for (const fragment of requirement.required) {
      assert.equal(
        compact.includes(compactSource(fragment)),
        true,
        `${requirement.name}: missing executable evidence ${compactSource(fragment)}`,
      )
    }
    let prior = -1
    for (const fragment of requirement.ordered || []) {
      const index = compact.indexOf(compactSource(fragment), prior + 1)
      assert.notEqual(index, -1, `${requirement.name}: missing ordered evidence`)
      assert.equal(index > prior, true, `${requirement.name}: evidence order changed`)
      prior = index
    }
  }
}


test('Phase 3B has one closed formal browser suite and package entrypoint', () => {
  const rootPackage = JSON.parse(readWorkspaceFile('package.json'))
  const frontendPackage = JSON.parse(readWorkspaceFile('frontend/package.json'))
  assert.equal(
    rootPackage.scripts['test:browser:phase3b'],
    'node scripts/run-tests.mjs browser-phase3b',
  )
  assert.equal(
    frontendPackage.scripts['test:e2e:phase3b'],
    'node e2e/run-phase3b.mjs',
  )
  for (const relativePath of [
    'frontend/e2e/phase3b-volumes-plots.spec.ts',
    'frontend/e2e/playwright.phase3b.config.ts',
    'frontend/e2e/run-phase3b.mjs',
  ]) {
    assert.equal(existsSync(path.join(repositoryRoot, relativePath)), true, relativePath)
  }
})


test('dispatcher owns the exact Phase 3B runner and validates MySQL first', () => {
  const calls = []
  const environment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }
  assert.equal(runSuites(['browser-phase3b'], {
    rootDirectory: repositoryRoot,
    environment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  }), 0)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].args, ['frontend/e2e/run-phase3b.mjs'])
  assert.equal(calls[0].options.shell, false)

  calls.length = 0
  let stderr = ''
  const incomplete = { ...environment }
  delete incomplete.TEST_MYSQL_PASSWORD
  assert.equal(runSuites(['browser-phase3b'], {
    rootDirectory: repositoryRoot,
    environment: incomplete,
    stderr: { write(chunk) { stderr += chunk } },
    spawnSyncImpl() {
      calls.push('spawned')
      return { status: 0 }
    },
  }), 2)
  assert.deepEqual(calls, [])
  assert.match(stderr, /TEST_MYSQL_PASSWORD/u)
})


test('Phase 3B runner owns one exact spec and one exact config', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  const source = readWorkspaceFile('frontend/e2e/run-phase3b.mjs')
  assert.deepEqual(runner.FORMAL_SPECS, ['phase3b-volumes-plots.spec.ts'])
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase3b.config.ts')
  assert.deepEqual(runner.resolveCommandLineSpecs([]), runner.FORMAL_SPECS)
  assert.deepEqual(runner.validateSpecs(runner.FORMAL_SPECS), runner.FORMAL_SPECS)
  assert.throws(
    () => runner.resolveCommandLineSpecs(['arbitrary.spec.ts']),
    /does not accept spec paths/iu,
  )
  assert.match(source, /runPhase3BCommandLine\(\{ specs \}\)/u)
  assert.doesNotMatch(source, /console\.error\('Phase 3B browser runner failed\.'\)/u)
})


test('Phase 3B CLI reports owned diagnostics while redacting secrets and database names', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  const secret = 'phase3b-cli-secret-sentinel'
  const database = 'novel_creator_test_phase3b_cli_secret'
  const ownedRoot = path.join(repositoryRoot, 'novel-creator-phase3b-cli-contract')
  const artifactRoot = path.join(ownedRoot, 'artifacts')
  const resultPath = path.join(ownedRoot, 'browser-result.json')
  const failure = new Error(`browser failed with ${secret} on ${database}`)
  failure.stack = [
    `Error: browser failed with ${secret} on ${database}`,
    `    at ${path.join(ownedRoot, 'browser-failure.mjs')}:10:2`,
  ].join('\n')
  assert.equal(
    runner.attachPhase3BFailureContext(failure, {
      scenario: 'gateway',
      ownedRoot,
      artifactRoot,
      resultPath,
      sensitiveValues: [secret, database],
    }),
    failure,
  )
  let diagnostic = ''

  const status = await runner.runPhase3BCommandLine({
    specs: runner.FORMAL_SPECS,
    environment: {
      PHASE3B_GREP: '@gateway',
      TEST_MYSQL_HOST: '127.0.0.1',
      TEST_MYSQL_PORT: '3308',
      TEST_MYSQL_USER: 'root',
      TEST_MYSQL_PASSWORD: secret,
    },
    runPhase3BImpl: async () => {
      throw failure
    },
    writeError(message) {
      diagnostic += String(message)
    },
  })

  assert.equal(status, 1)
  assert.match(diagnostic, /scenario=gateway/u)
  assert.match(diagnostic, /error\[1\]\.name=Error/u)
  assert.match(diagnostic, /error\[1\]\.message=browser failed with \[redacted\]/u)
  assert.match(diagnostic, /error\[1\]\.stack=.*browser-failure\.mjs/u)
  assert.match(diagnostic, new RegExp(`trace=${artifactRoot.replaceAll('\\', '\\\\')}`, 'u'))
  assert.match(diagnostic, new RegExp(`result=${resultPath.replaceAll('\\', '\\\\')}`, 'u'))
  assert.match(diagnostic, /\[redacted\]/u)
  assert.doesNotMatch(diagnostic, new RegExp(secret, 'u'))
  assert.doesNotMatch(diagnostic, new RegExp(database, 'u'))
})


test('Phase 3B CLI renders every aggregate leaf without printing raw errors', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  const first = new TypeError('first safe failure')
  const second = new Error('second safe failure')
  const aggregate = new AggregateError([first, second], 'raw aggregate wrapper')
  let diagnostic = ''

  const status = await runner.runPhase3BCommandLine({
    specs: runner.FORMAL_SPECS,
    environment: { PHASE3B_GREP: '@manual' },
    runPhase3BImpl: async () => {
      throw aggregate
    },
    writeError(message) {
      diagnostic += String(message)
    },
  })

  assert.equal(status, 1)
  assert.match(diagnostic, /scenario=manual/u)
  assert.match(diagnostic, /error\.count=2/u)
  assert.match(diagnostic, /error\[1\]\.name=TypeError/u)
  assert.match(diagnostic, /error\[1\]\.message=first safe failure/u)
  assert.match(diagnostic, /error\[2\]\.name=Error/u)
  assert.match(diagnostic, /error\[2\]\.message=second safe failure/u)
  assert.doesNotMatch(diagnostic, /raw aggregate wrapper/u)
})


test('Phase 3B browser source is UI-only and audits the complete runtime', () => {
  const entry = 'frontend/e2e/phase3b-volumes-plots.spec.ts'
  assertSafeBrowserGraph(entry, relativePath => readWorkspaceFile(relativePath))
  const source = readWorkspaceFile(entry)
  assert.doesNotMatch(
    source,
    /page\.request|page\.route|page\.evaluate|\bfetch\s*\(|\baxios\b/u,
  )
  assert.match(source, /observeRuntime/u)
  assert.match(source, /assertRuntimeEvidenceHealthy/u)
  assert.match(source, /scanRuntimeEvidence/u)
  assert.match(source, /runtimeSensitiveValues/u)
  assert.match(source, /function privateEvidenceSurfaces/u)
  assert.doesNotMatch(source, /const rendered = evidenceText\(evidence\)/u)
  assert.match(source, /page\.goBack\(\)/u)
  assert.match(source, /page\.goForward\(\)/u)
  assert.match(source, /page\.reload\(\)/u)
  assert.match(source, /getByRole\('combobox'\)\.selectOption/u)
  assert.match(
    source,
    /OVERVIEW_PATH\s*=\s*`\/projects\/\$\{PROJECT_ID\}\/overview`/u,
  )
})


test('Phase 3B runner isolates provider I/O and owns disposable resources', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase3b.mjs')
  assert.match(source, /createDatabaseName/u)
  assert.match(source, /SELECT DATABASE\(\)/u)
  assert.match(source, /SCHEDULER_ENABLED:\s*'0'/u)
  assert.match(source, /127\.0\.0\.1/u)
  assert.match(source, /GuardedAsyncClient/u)
  assert.match(source, /forbidden-outbound/u)
  assert.match(source, /FAKE_PLANNING_GATEWAY_SOURCE/u)
  assert.match(source, /\/v1\/chat\/completions/u)
  assert.match(source, /BROWSER_VITE_ORIGIN/u)
  assert.match(source, /'access-control-allow-origin': browserOrigin/u)
  assert.match(source, /from backend\.services\.bibles import BIBLE_POLICY_VERSION/u)
  assert.match(source, /SET policy_version=%s/u)
  assert.match(
    source,
    /VITE_API_BASE_URL:\s*`\$\{browserApiUrl\}\/api`/u,
  )
  assert.match(source, /runOwnedProductLifecycle/u)
  assert.match(source, /stopServer:/u)
  assert.match(source, /releaseReservation:/u)
  assert.match(source, /(?:async\s+)?dropDatabase(?:\s*:|\s*\()/u)
  assert.match(source, /(?:async\s+)?removeRoot(?:\s*:|\s*\()/u)
  assert.match(source, /AggregateError/u)
  assert.match(
    source,
    /assertArtifactEvidenceSafeImpl\s*=\s*assertArtifactEvidenceSafe/u,
  )
  assert.match(
    source,
    /assertArtifactEvidenceSafeImpl\(\s*roots\.artifactRoot,\s*sensitiveValues,\s*\[roots\.browserResultPath\]/u,
  )
})


test('Phase 3B contract health wait bounds a stable non-200 response', async () => {
  const reservation = await reserveLocalPort()
  const port = reservation.port
  await reservation.release()
  const server = http.createServer((_request, response) => {
    response.writeHead(503, { 'content-type': 'application/json' })
    response.end(JSON.stringify({ browserRunNonce: 'wrong-nonce' }))
  })
  await listenOwned(server, port)
  const startedAt = Date.now()
  try {
    await assert.rejects(
      waitForHealth(port, 'expected-nonce', { timeoutMs: 120 }),
      /timed out waiting for runner-owned browser server/u,
    )
    assert.equal(Date.now() - startedAt < 1_000, true)
  } finally {
    await new Promise(resolve => server.close(resolve))
  }
})


test('Phase 3B contract cleanup force-terminates a child that ignores graceful stop', async () => {
  const child = spawn(
    process.execPath,
    [
      '-e',
      "process.on('SIGTERM',()=>{});process.stdout.write('ready\\n');"
        + 'setInterval(()=>{},1000)',
    ],
    {
      detached: process.platform !== 'win32',
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  )
  try {
    await Promise.race([
      new Promise(resolve => child.stdout.once('data', resolve)),
      new Promise((_, reject) => setTimeout(
        () => reject(new Error('non-exiting child did not start')),
        1_000,
      )),
    ])
    await stopOwnedChild(child, { timeoutMs: 1_000 })
    assert.equal(child.exitCode !== null || child.signalCode !== null, true)
  } finally {
    if (child.exitCode === null && child.signalCode === null) {
      await terminateOwnedProcessTree(child, { timeoutMs: 1_000 })
    }
  }
})


test('Phase 3B fixture persists the formal seed contract and Bible documents', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase3b.mjs')
  assert.match(source, /from backend\.domain\.bibles import BiblePayload/u)
  assert.match(
    source,
    /from backend\.domain\.contracts import CreationContractPayload/u,
  )
  assert.match(
    source,
    /from backend\.domain\.seeds import \([\s\S]*?SeedPayload[\s\S]*?seed_revision_document[\s\S]*?\)/u,
  )
  assert.match(source, /seed_document = build_seed_fixture_document\(\)/u)
  assert.match(source, /seed_document = validate_seed_fixture_document\(/u)
  assert.match(
    source,
    /CreationContractPayload\.model_validate_json\([\s\S]*?strict=True/u,
  )
  assert.match(source, /BiblePayload\.model_validate\([\s\S]*?strict=True/u)
  assert.match(source, /bible_content = validate_bible_fixture_document\(/u)
  assert.match(source, /content=bible_content/u)
})


test('Phase 3B fixture document contract executes official strict validators and rejects mutations', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  assert.equal(typeof runner.FIXTURE_DOCUMENT_CONTRACT_SOURCE, 'string')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase3b-fixture-'))
  const contractPath = path.join(root, 'fixture_contract.py')
  const probePath = path.join(root, 'probe.py')
  writeFileSync(contractPath, runner.FIXTURE_DOCUMENT_CONTRACT_SOURCE, 'utf8')
  writeFileSync(
    probePath,
    String.raw`
from copy import deepcopy

from fixture_contract import (
    build_bible_fixture_document,
    build_creation_fixture_document,
    build_seed_fixture_document,
    validate_bible_fixture_document,
    validate_creation_fixture_document,
    validate_seed_fixture_document,
)
from backend.domain.json_contracts import canonical_hash
from backend.domain.seeds import (
    build_seed_provenance,
    decode_seed_revision,
    seed_revision_document,
)


def rejects(action):
    try:
        action()
    except (AssertionError, TypeError, ValueError):
        return
    raise AssertionError("mutation was accepted")


seed_document = build_seed_fixture_document()
seed_payload, seed_provenance = decode_seed_revision(seed_document)
assert seed_provenance is None
seed_hash = canonical_hash(seed_payload)
assert validate_seed_fixture_document(seed_document, seed_hash) == seed_document

provenance = build_seed_provenance(
    kind="manual",
    snapshots=(),
    analysis=None,
    inspiration_attempt=None,
    public_notes=("fixture provenance",),
)
provenance_document = seed_revision_document(seed_payload, provenance)
decoded_payload, decoded_provenance = decode_seed_revision(provenance_document)
assert decoded_payload == seed_payload
assert decoded_provenance == provenance
assert validate_seed_fixture_document(
    provenance_document,
    seed_hash,
) == provenance_document

rejects(lambda: validate_seed_fixture_document(seed_document, "0" * 64))
invalid_seed = deepcopy(seed_document)
invalid_seed.pop("logline")
rejects(lambda: validate_seed_fixture_document(invalid_seed, seed_hash))
injected_provenance = deepcopy(seed_document)
injected_provenance["_provenance"] = {"apiKey": "never-echo"}
rejects(
    lambda: validate_seed_fixture_document(injected_provenance, seed_hash)
)

creation_document = build_creation_fixture_document()
creation_hash = canonical_hash(creation_document)
assert validate_creation_fixture_document(
    creation_document,
    creation_hash,
) == creation_document
mutated_creation = deepcopy(creation_document)
mutated_creation["selectedSeed"]["logline"] = "hash-breaking mutation"
rejects(
    lambda: validate_creation_fixture_document(
        mutated_creation,
        creation_hash,
    )
)

bible_document = build_bible_fixture_document()
assert validate_bible_fixture_document(bible_document) == bible_document
invalid_bible = deepcopy(bible_document)
invalid_bible.pop("continuityGuardrails")
rejects(lambda: validate_bible_fixture_document(invalid_bible))

print("fixture-contract-behavior=passed")
`,
    'utf8',
  )
  try {
    const result = spawnSync('python', [probePath], {
      cwd: repositoryRoot,
      encoding: 'utf8',
      env: {
        ...process.env,
        PYTHONPATH: [
          repositoryRoot,
          process.env.PYTHONPATH,
        ].filter(Boolean).join(path.delimiter),
      },
      timeout: 10_000,
      windowsHide: true,
    })
    assert.equal(
      result.status,
      0,
      `fixture contract probe failed: ${result.stderr || result.stdout}`,
    )
    assert.equal(result.stdout.trim(), 'fixture-contract-behavior=passed')
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})


test('Phase 3B fake gateway requires the complete public storyContext basis', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase3b.mjs')
  assert.match(source, /const storyContext = evidence\.manifest\.storyContext/u)
  assert.match(source, /storyContext\.seed\.logline/u)
  assert.match(source, /storyContext\.engine\.storyPromise/u)
  assert.match(source, /storyContext\.engine\.conflictLoop/u)
  assert.match(source, /storyContext\.longFormCapacity\.targetTotalWords/u)
  assert.match(source, /storyContext\.longFormCapacity\.expectedChapterCount/u)
  assert.match(source, /storyContext\.coreCharacters/u)
  assert.match(source, /storyContext\.relationshipDynamics/u)
  assert.match(source, /storyContext\.worldRules/u)
  assert.match(source, /storyContext\.continuityGuardrails/u)
  assert.match(source, /storyContextText\.includes\(expectedSecret\)/u)
  assert.match(source, /corpus/iu)
})


test('Phase 3B fake gateway recursively rejects private provenance and incomplete public basis', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  assert.equal(typeof runner.FAKE_PLANNING_GATEWAY_SOURCE, 'string')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase3b-gateway-'))
  const gatewayPath = path.join(root, 'gateway.cjs')
  const counterPath = path.join(root, 'counter.log')
  const enteredPath = path.join(root, 'entered.signal')
  const releasePath = path.join(root, 'release.signal')
  writeFileSync(gatewayPath, runner.FAKE_PLANNING_GATEWAY_SOURCE, 'utf8')
  writeFileSync(counterPath, '', 'utf8')
  const reservation = await reserveLocalPort()
  const port = reservation.port
  await reservation.release()
  const expectedSecret = 'gateway-contract-secret'
  const child = spawn(process.execPath, [gatewayPath, String(port)], {
    env: {
      ...process.env,
      M2_BROWSER_RUN_NONCE: 'phase3b-gateway-contract',
      BROWSER_GATEWAY_COUNTER_PATH: counterPath,
      BROWSER_GATEWAY_ENTERED_PATH: enteredPath,
      BROWSER_GATEWAY_RELEASE_PATH: releasePath,
      BROWSER_SECRET_SENTINEL: expectedSecret,
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })
  const publicStoryContext = {
    seed: { logline: 'A public logline' },
    engine: {
      storyPromise: 'A public promise',
      conflictLoop: 'A public conflict loop',
    },
    longFormCapacity: {
      targetTotalWords: 200_000,
      expectedChapterCount: 80,
    },
    coreCharacters: [{ id: 'character-1', text: 'A character' }],
    relationshipDynamics: [{ id: 'relationship-1', text: 'A bond' }],
    worldRules: [{ id: 'world-rule-1', text: 'A rule' }],
    continuityGuardrails: [{ id: 'guardrail-1', text: 'A guardrail' }],
  }
  const requestBody = storyContext => ({
    max_tokens: 2_000,
    messages: [
      { role: 'system', content: 'Return JSON' },
      {
        role: 'user',
        content: JSON.stringify({
          manifest: {
            storyContext,
            draft: { volumes: [], plots: [] },
          },
        }),
      },
    ],
    model: 'test-model',
    response_format: { type: 'json_object' },
    stream: false,
    temperature: 0.2,
  })
  const callGateway = storyContext => fetch(
    `http://127.0.0.1:${port}/v1/chat/completions`,
    {
      method: 'POST',
      headers: {
        authorization: `Bearer ${expectedSecret}`,
        'content-type': 'application/json',
      },
      body: JSON.stringify(requestBody(storyContext)),
      signal: AbortSignal.timeout(2_000),
    },
  )
  try {
    await waitForHealth(port, 'phase3b-gateway-contract')
    for (const privateKey of ['provenance', '_provenance', 'Pro_Ve_Nance']) {
      const privateValue = `private-${privateKey}-must-not-echo`
      const unsafe = structuredClone(publicStoryContext)
      unsafe.coreCharacters[0][privateKey] = { nested: privateValue }
      const rejected = await callGateway(unsafe)
      assert.equal(rejected.status, 404)
      const safeBody = await rejected.text()
      assert.equal(safeBody.includes(privateValue), false)
      assert.deepEqual(
        JSON.parse(safeBody),
        { error: { code: 'NOT_FOUND', message: 'Not found' } },
      )
    }
    const incomplete = structuredClone(publicStoryContext)
    delete incomplete.relationshipDynamics
    const incompleteResponse = await callGateway(incomplete)
    assert.equal(incompleteResponse.status, 404)
    assert.equal(readFileSync(counterPath, 'utf8'), '')

    writeFileSync(releasePath, 'release\n', { encoding: 'utf8', flag: 'wx' })
    const accepted = await callGateway(publicStoryContext)
    assert.equal(accepted.status, 200)
    assert.equal(readFileSync(counterPath, 'utf8'), 'planning-generation\n')
  } finally {
    await stopOwnedChild(child)
    rmSync(root, { recursive: true, force: true })
  }
})


test('Phase 3B transparent proxy keeps fault state request-local across formal error and reconciliation', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  assert.equal(typeof runner.TRANSPARENT_FAULT_PROXY_SOURCE, 'string')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase3b-proxy-'))
  const proxyPath = path.join(root, 'proxy.cjs')
  const enteredPath = path.join(root, 'entered.signal')
  const releasePath = path.join(root, 'release.signal')
  const ledgerPath = path.join(root, 'upstream.log')
  writeFileSync(proxyPath, runner.TRANSPARENT_FAULT_PROXY_SOURCE, 'utf8')
  writeFileSync(ledgerPath, '', 'utf8')
  const upstreamReservation = await reserveLocalPort()
  const proxyReservation = await reserveLocalPort()
  const upstreamPort = upstreamReservation.port
  const proxyPort = proxyReservation.port
  await upstreamReservation.release()
  await proxyReservation.release()
  const formalBody = JSON.stringify({
    error: { code: 'PLANNING_GENERATION_NOT_READY', message: 'Not ready' },
  })
  let generationCount = 0
  const upstream = http.createServer((request, response) => {
    if (request.method === 'POST' && request.url.endsWith('/generate')) {
      generationCount += 1
      if (generationCount === 1) {
        response.writeHead(409, {
          'content-type': 'application/json; charset=utf-8',
          'content-length': String(Buffer.byteLength(formalBody)),
        })
        response.end(formalBody)
        return
      }
      if (generationCount === 2) {
        writeFileSync(enteredPath, 'entered\n', { encoding: 'utf8', flag: 'wx' })
        const waitForRelease = () => {
          if (existsSync(releasePath)) {
            const generated = JSON.stringify({ status: 'succeeded' })
            response.writeHead(200, {
              'content-type': 'application/json; charset=utf-8',
              'content-length': String(Buffer.byteLength(generated)),
            })
            response.end(generated)
            return
          }
          setTimeout(waitForRelease, 10)
        }
        waitForRelease()
        return
      }
    }
    if (
      request.method === 'GET'
      && request.url.includes('/planning/operations/by-idempotency-key/')
    ) {
      const pending = JSON.stringify({
        status: 'pending',
        operationId: 'operation-1',
      })
      response.writeHead(200, {
        'content-type': 'application/json; charset=utf-8',
        'content-length': String(Buffer.byteLength(pending)),
      })
      response.end(pending)
      return
    }
    response.writeHead(404)
    response.end()
  })
  await listenOwned(upstream, upstreamPort)
  const child = spawn(
    process.execPath,
    [proxyPath, String(proxyPort), String(upstreamPort)],
    {
      env: {
        ...process.env,
        M2_BROWSER_RUN_NONCE: 'phase3b-proxy-contract',
        BROWSER_PROJECT_ID: '81000000-0000-0000-0000-000000000001',
        BROWSER_DROP_GENERATION_RESPONSE: '1',
        BROWSER_GATEWAY_ENTERED_PATH: enteredPath,
        BROWSER_GATEWAY_RELEASE_PATH: releasePath,
        BROWSER_UPSTREAM_LEDGER_PATH: ledgerPath,
        BROWSER_VITE_ORIGIN: 'http://127.0.0.1:4173',
      },
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    },
  )
  const generationUrl = (
    `http://127.0.0.1:${proxyPort}/api/projects/`
      + '81000000-0000-0000-0000-000000000001/planning/drafts/draft/generate'
  )
  try {
    await waitForHealth(proxyPort, 'phase3b-proxy-contract')
    const startedAt = Date.now()
    const response = await fetch(
      generationUrl,
      {
        method: 'POST',
        body: '{}',
        headers: { 'content-type': 'application/json' },
        signal: AbortSignal.timeout(2_000),
      },
    )
    assert.equal(response.status, 409)
    assert.deepEqual(await response.json(), JSON.parse(formalBody))
    assert.equal(Date.now() - startedAt < 2_000, true)

    const unknown = await fetch(generationUrl, {
      method: 'POST',
      body: '{}',
      headers: { 'content-type': 'application/json' },
      signal: AbortSignal.timeout(2_000),
    })
    assert.equal(unknown.status, 503)
    assert.deepEqual(
      await unknown.json(),
      {
        error: {
          code: 'RESULT_UNKNOWN',
          message: 'Result must be reconciled',
        },
      },
    )
    const reconciled = await fetch(
      `http://127.0.0.1:${proxyPort}/api/projects/`
        + '81000000-0000-0000-0000-000000000001'
        + '/planning/operations/by-idempotency-key/key-1',
      { signal: AbortSignal.timeout(2_000) },
    )
    assert.equal(reconciled.status, 200)
    assert.deepEqual(
      await reconciled.json(),
      { status: 'pending', operationId: 'operation-1' },
    )
    assert.equal(existsSync(releasePath), true)
    assert.equal(
      readFileSync(ledgerPath, 'utf8'),
      'upstream-generation-status=409\nupstream-generation-status=200\n',
    )
  } finally {
    if (!existsSync(releasePath)) writeFileSync(releasePath, 'release\n', 'utf8')
    await stopOwnedChild(child)
    await new Promise(resolve => upstream.close(resolve))
    rmSync(root, { recursive: true, force: true })
  }
})


test('Phase 3B transparent proxy finalizes late upstream failure outcomes after fixed 503', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  assert.equal(typeof runner.TRANSPARENT_FAULT_PROXY_SOURCE, 'string')
  assert.equal(
    await exerciseLateProxyOutcome(
      runner.TRANSPARENT_FAULT_PROXY_SOURCE,
      'late-status',
    ),
    'upstream-generation-status=409\n',
  )
  assert.equal(
    await exerciseLateProxyOutcome(
      runner.TRANSPARENT_FAULT_PROXY_SOURCE,
      'connection-error',
    ),
    'upstream-generation-error=transport\n',
  )
})


test('Phase 3B runner keeps Vite discovery closed and leaves no temp cache', () => {
  const source = readWorkspaceFile('frontend/e2e/run-phase3b.mjs')
  assert.match(source, /optimizeDeps:\s*\{[\s\S]*?noDiscovery:\s*true/u)
  assert.match(source, /deps_temp_/u)
  assert.match(source, /vite temp cache residue/u)
})


test('Phase 3B formal UI flow binds all ten outcomes to executable behavior', () => {
  const source = readWorkspaceFile('frontend/e2e/phase3b-volumes-plots.spec.ts')
  assertPhase3BBehaviorContract(source)
  assert.doesNotMatch(
    source,
    /Formal outcome names kept visible for the closed suite contract/u,
  )
})


test('Phase 3B executable behavior mutations fail even when legacy comments remain', () => {
  const source = readWorkspaceFile('frontend/e2e/phase3b-volumes-plots.spec.ts')
  const legacyComment = `/* ${legacyOutcomeMarkers.join(' | ')} */`
  for (const requirement of phase3BBehaviorRequirements) {
    const compact = compactSource(source)
    const target = compactSource(requirement.mutation)
    const start = compact.indexOf(target)
    assert.notEqual(start, -1, `${requirement.name}: mutation target missing`)
    const mutated = compact.slice(0, start)
      + compact.slice(start + target.length)
      + legacyComment
    assert.throws(
      () => assertPhase3BBehaviorContract(mutated),
      new RegExp(requirement.name.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&'), 'u'),
    )
  }
})


test('Phase 3B config confines artifacts to the runner-owned root', () => {
  const source = readWorkspaceFile('frontend/e2e/playwright.phase3b.config.ts')
  assert.match(source, /BROWSER_OWNED_ROOT/u)
  assert.match(source, /BROWSER_ARTIFACT_ROOT/u)
  assert.match(source, /path\.dirname\(output\)/u)
  assert.match(source, /preserveOutput:\s*'never'/u)
  assert.match(source, /workers:\s*1/u)
  assert.match(source, /trace:\s*'off'/u)
  assert.match(source, /screenshot:\s*'off'/u)
  assert.match(source, /video:\s*'off'/u)
})


test('Phase 3B registers its root before fallible initialization and still cleans it', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  const initializationFailure = new Error('injected root initialization failure')
  const ownedRoot = 'phase3b-owned-root'
  const events = []

  await assert.rejects(
    runner.runOneScenario({
      spec: runner.FORMAL_SPECS[0],
      scenario: runner.FORMAL_SCENARIOS[0],
      environment: {},
      databaseNameFactory: () => 'novel_creator_test_phase3b_fault',
      ownedRootFactory() {
        events.push('create-owned-root')
        return ownedRoot
      },
      createRootsImpl(root) {
        events.push(`initialize:${root}`)
        throw initializationFailure
      },
      async cleanupOwnedRootImpl({ root }) {
        events.push(`remove:${root}`)
        return true
      },
      portReservationFactory() {
        throw new Error('port reservation must not run after initialization failure')
      },
      deadlines: {},
    }),
    error => error === initializationFailure,
  )

  assert.deepEqual(events, [
    'create-owned-root',
    `initialize:${ownedRoot}`,
    `remove:${ownedRoot}`,
  ])
})


test('Phase 3B keeps initialization and root deletion failures without overwriting either', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  const initializationFailure = new Error('injected root initialization failure')
  const deletionFailure = new Error('injected root deletion failure')

  await assert.rejects(
    runner.runOneScenario({
      spec: runner.FORMAL_SPECS[0],
      scenario: runner.FORMAL_SCENARIOS[0],
      environment: {},
      databaseNameFactory: () => 'novel_creator_test_phase3b_fault',
      ownedRootFactory: () => 'phase3b-owned-root',
      createRootsImpl() {
        throw initializationFailure
      },
      async cleanupOwnedRootImpl() {
        throw deletionFailure
      },
      portReservationFactory() {
        throw new Error('port reservation must not run after initialization failure')
      },
      deadlines: {},
    }),
    error => {
      assert.equal(error instanceof AggregateError, true)
      assert.deepEqual(error.errors, [initializationFailure, deletionFailure])
      return true
    },
  )
})


test('Phase 3B root cleanup deletes the root after an artifact validation failure', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  const artifactFailure = new Error('injected artifact scan failure')
  const events = []

  await assert.rejects(
    runner.cleanupOwnedRoot({
      root: 'phase3b-owned-root',
      roots: {
        artifactRoot: 'phase3b-artifacts',
        browserResultPath: 'phase3b-result.json',
      },
      ports: [],
      sensitiveValues: [],
      viteTempCacheEntriesImpl() {
        events.push('cache')
        return []
      },
      assertArtifactEvidenceSafeImpl() {
        events.push('artifact')
        throw artifactFailure
      },
      removeOwnedRootImpl() {
        events.push('remove')
      },
      existsSyncImpl() {
        events.push('verify-removed')
        return false
      },
    }),
    error => error === artifactFailure,
  )

  assert.deepEqual(events, ['cache', 'artifact', 'remove', 'verify-removed'])
})


test('Phase 3B root cleanup aggregates validation and deletion failures in order', async () => {
  const runner = await import('../../frontend/e2e/run-phase3b.mjs')
  const artifactFailure = new Error('injected artifact scan failure')
  const deletionFailure = new Error('injected root deletion failure')
  const events = []

  await assert.rejects(
    runner.cleanupOwnedRoot({
      root: 'phase3b-owned-root',
      roots: {
        artifactRoot: 'phase3b-artifacts',
        browserResultPath: 'phase3b-result.json',
      },
      ports: [],
      sensitiveValues: [],
      viteTempCacheEntriesImpl: () => [],
      assertArtifactEvidenceSafeImpl() {
        events.push('artifact')
        throw artifactFailure
      },
      removeOwnedRootImpl() {
        events.push('remove')
        throw deletionFailure
      },
      existsSyncImpl() {
        throw new Error('absence check must not overwrite deletion failure')
      },
    }),
    error => {
      assert.equal(error instanceof AggregateError, true)
      assert.deepEqual(error.errors, [artifactFailure, deletionFailure])
      return true
    },
  )

  assert.deepEqual(events, ['artifact', 'remove'])
})


test('Phase 3B lifecycle keeps server reverse, reservation, database, root cleanup order', async () => {
  const bodyFailure = new Error('injected body failure')
  const events = []

  await assert.rejects(
    runOwnedProductLifecycle({
      async body(lifecycle) {
        lifecycle.setRoot('root')
        lifecycle.setDatabase('database')
        lifecycle.registerReservation('reservation-a')
        lifecycle.registerReservation('reservation-b')
        lifecycle.registerServer('server-a')
        lifecycle.registerServer('server-b')
        events.push('body')
        throw bodyFailure
      },
      async stopServer(server) {
        events.push(`stop:${server}`)
      },
      async releaseReservation(reservation) {
        events.push(`release:${reservation}`)
      },
      async dropDatabase(database) {
        events.push(`drop:${database}`)
      },
      async removeRoot(root) {
        events.push(`remove:${root}`)
      },
    }),
    error => error === bodyFailure,
  )

  assert.deepEqual(events, [
    'body',
    'stop:server-b',
    'stop:server-a',
    'release:reservation-a',
    'release:reservation-b',
    'drop:database',
    'remove:root',
  ])
})

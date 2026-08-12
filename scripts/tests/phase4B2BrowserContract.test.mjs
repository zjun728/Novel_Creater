import assert from 'node:assert/strict'
import { closeSync, existsSync, ftruncateSync, mkdtempSync, openSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import http from 'node:http'
import os from 'node:os'
import path from 'node:path'
import { spawn, spawnSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { assertSafeBrowserGraph, collectBrowserTestDeclarations } from '../browser-source-contract.mjs'
import { runSuites } from '../run-tests.mjs'
import { reserveLocalPort, runOwnedProductLifecycle } from '../../frontend/e2e/support/product-runner.mjs'


const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
)
const PYTHON_COMMAND = process.env.PYTHON || 'python'
const PYTHON_ENVIRONMENT = Object.freeze(Object.fromEntries([
  'PATH', 'Path', 'PATHEXT', 'SystemRoot', 'SYSTEMROOT', 'WINDIR', 'COMSPEC',
  'ComSpec', 'PYTHONPATH', 'PYTHONHOME', 'PYTHONUTF8', 'PYTHONIOENCODING', 'VIRTUAL_ENV',
].filter(key => Object.hasOwn(process.env, key)).map(key => [key, process.env[key]])))


function source(relativePath) {
  return readFileSync(path.join(repositoryRoot, relativePath), 'utf8')
}


function compact(value) {
  return String(value).replace(/\s+/gu, ' ').trim()
}


const HTTP_REQUEST_TIMEOUT_MS = 2_000


function requestStatus(options, body) {
  return new Promise((resolve, reject) => {
    let settled = false
    let timer = null
    const finish = (error, status) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (error) reject(error)
      else resolve(status)
    }
    const request = http.request(options, response => {
      response.resume()
      response.once('error', error => finish(error))
      response.once('end', () => finish(null, response.statusCode))
    })
    request.once('error', error => finish(error))
    timer = setTimeout(() => request.destroy(new Error('contract HTTP request timed out')), HTTP_REQUEST_TIMEOUT_MS)
    try { request.end(body) } catch (error) { finish(error) }
  })
}


async function withOwnedCleanup(body, cleanupGroups) {
  let result
  let primary = null
  try { result = await body() } catch (error) { primary = error }
  const errors = primary === null ? [] : [primary]
  for (const group of cleanupGroups) {
    const settled = await Promise.allSettled(group.map(task => task()))
    errors.push(...settled.filter(item => item.status === 'rejected').map(item => item.reason))
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase4B2 contract cleanup failed')
  return result
}


async function waitForProvider(port, nonce) {
  const deadline = Date.now() + 5_000
  while (Date.now() < deadline) {
    try {
      const status = await requestStatus({ host: '127.0.0.1', port, method: 'GET', path: '/health' })
      if (status === 200) return
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 20))
  }
  throw new Error(`fake provider ${nonce} did not become ready`)
}


async function stopOwnedChild(child) {
  if (!child || child.exitCode !== null) return
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      child.kill('SIGKILL')
      reject(new Error('fake provider did not stop'))
    }, 5_000)
    child.once('close', () => { clearTimeout(timer); resolve() })
    child.kill('SIGTERM')
  })
}


function sha256(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}


function fixedConstant(sourceText, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/gu, '\\$&')
  const match = sourceText.match(new RegExp(`^\\s*(?:export\\s+)?(?:const\\s+)?${escaped}\\s*=\\s*['\"]([0-9a-f]{64})['\"]`, 'mu'))
  assert.ok(match, `missing ${name}`)
  return match[1]
}


function providerRequest(port, agent) {
  return requestStatus({
    host: '127.0.0.1',
    port,
    method: 'POST',
    path: '/v1/chat/completions',
    agent,
    headers: {
      authorization: 'Bearer contract-only-secret',
      'content-type': 'application/json',
    },
  }, JSON.stringify({ stream: true }))
}


test('Phase 4B2 owns one closed fake-provider browser suite and entrypoints', () => {
  const rootPackage = JSON.parse(source('package.json'))
  const frontendPackage = JSON.parse(source('frontend/package.json'))
  assert.equal(
    rootPackage.scripts['test:browser:phase4b2'],
    'node scripts/run-tests.mjs browser-phase4b2',
  )
  assert.equal(
    frontendPackage.scripts['test:e2e:phase4b2'],
    'node e2e/run-phase4b2.mjs',
  )
  assert.equal(
    frontendPackage.scripts['test:browser:phase4b2'],
    'node ../scripts/run-tests.mjs browser-phase4b2',
  )
  for (const relativePath of [
    'backend/scripts/prepare_phase4b2_browser_db.py',
    'frontend/e2e/run-phase4b2.mjs',
    'frontend/e2e/playwright.phase4b2.config.ts',
    'frontend/e2e/phase4b2-draft-streaming.spec.ts',
  ]) {
    assert.equal(existsSync(path.join(repositoryRoot, relativePath)), true, relativePath)
  }

  const calls = []
  const environment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }
  assert.equal(runSuites(['browser-phase4b2'], {
    rootDirectory: repositoryRoot,
    environment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  }), 0)
  assert.deepEqual(calls.map(call => call.args), [['frontend/e2e/run-phase4b2.mjs']])
  assert.equal(calls[0].options.shell, false)
})


test('Phase 4B2 runner bounds disposable resources and fake-provider evidence', async () => {
  const runnerPath = 'frontend/e2e/run-phase4b2.mjs'
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const runnerSource = source(runnerPath)
  assert.deepEqual(runner.FORMAL_SPECS, ['phase4b2-draft-streaming.spec.ts'])
  assert.equal(runner.FORMAL_CONFIG, 'playwright.phase4b2.config.ts')
  assert.deepEqual(runner.FORMAL_SCENARIOS.map(item => item.tag), [
    '@complete', '@reconnect', '@cancel-output', '@cancel-empty',
  ])
  assert.deepEqual(runner.resolveCommandLineSpecs([]), runner.FORMAL_SPECS)
  assert.throws(() => runner.resolveCommandLineSpecs(['outside.spec.ts']), /does not accept spec paths/iu)
  for (const fragment of [
    "from './support/product-runner.mjs'",
    "from './support/deny-proxy.mjs'",
    "from './support/database-residue.mjs'",
    "from './support/safe-diagnostics.mjs'",
    'createDatabaseName',
    'createOwnedRoot',
    'reserveLocalPort',
    'runOwnedProductLifecycle',
    'assertDatabaseResidue',
    'BROWSER_ALLOWED_ORIGINS',
    'BROWSER_DENY_PROXY_URL',
    'BROWSER_PROVIDER_BASE_URL',
    'fake streaming provider',
    'REQUEST_LIMIT = 65536',
    "request.destroy()",
    'vite-cache',
    'deps_temp',
    'novel_creator_test_',
    'real provider calls = 0',
    'product DB reads/writes = 0/0',
    'verify-postconditions',
    'assertProviderLedger',
    'cleanupOwnedRoot',
  ]) {
    assert.equal(compact(runnerSource).includes(compact(fragment)), true, fragment)
  }
  assert.doesNotMatch(runnerSource, /run-phase4b2\.mjs[^\n]*run-phase4b2\.mjs/u)
  assert.doesNotMatch(runnerSource, /localhost|0\.0\.0\.0/u)
  for (const scenario of runner.FORMAL_SCENARIOS) {
    const terminal = scenario.mode === 'complete' ? 'completed' : 'transport-closed'
    assert.doesNotThrow(() => runner.assertProviderLedger([
      `scenario=${scenario.mode}`,
      'method=POST path=/v1/chat/completions status=200',
      'connection=1',
      'call=1',
      `terminal=${terminal}`,
    ].join('\n'), scenario))
  }
  assert.throws(() => runner.assertProviderLedger([
    'scenario=complete',
    'method=POST path=/v1/chat/completions status=200',
    'connection=1',
    'call=1',
    'terminal=cancelled',
  ].join('\n'), runner.FORMAL_SCENARIOS[0]))
})


test('Phase 4B2 reports only selected successful scenarios', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const environment = {
    TEST_MYSQL_HOST: '127.0.0.1',
    TEST_MYSQL_PORT: '33060',
    TEST_MYSQL_USER: 'root',
    TEST_MYSQL_PASSWORD: 'test-only',
  }
  assert.equal(
    runner.formatScenarioPassedSummary('complete'),
    'Phase4B2 complete: scenario passed; DB/process/port/temp/artifact/Vite residue=0; real provider calls = 0; product DB reads/writes = 0/0',
  )
  assert.equal(runner.formatScenarioPassedSummary('complete').includes('4 serial UI-only scenarios'), false)
  for (const [grep, expectedTags, expectedTotal] of [
    ['@complete', ['@complete'], 'Phase4B2 browser: 1/1 scenarios passed'],
    [undefined, ['@complete', '@reconnect', '@cancel-output', '@cancel-empty'], 'Phase4B2 browser: 4/4 scenarios passed'],
  ]) {
    const calls = []
    const logs = []
    await runner.runPhase4B2({
      environment: { ...environment, ...(grep ? { PHASE4B2_GREP: grep } : {}) },
      async runOneScenarioImpl({ scenario }) { calls.push(scenario.tag) },
      log(message) { logs.push(message) },
    })
    assert.deepEqual(calls, expectedTags)
    assert.deepEqual(logs, [expectedTotal])
  }
  const failureLogs = []
  await assert.rejects(runner.runPhase4B2({
    environment: { ...environment, PHASE4B2_GREP: '@complete' },
    async runOneScenarioImpl() { throw new Error('expected scenario failure') },
    log(message) { failureLogs.push(message) },
  }), /expected scenario failure/u)
  assert.deepEqual(failureLogs, [])
})


test('Phase 4B2 fixture and browser scenarios use canonical UI-only paths', async () => {
  const fixture = source('backend/scripts/prepare_phase4b2_browser_db.py')
  const config = source('frontend/e2e/playwright.phase4b2.config.ts')
  const entry = 'frontend/e2e/phase4b2-draft-streaming.spec.ts'
  const spec = source(entry)
  for (const fragment of [
    'novel_creator_test_',
    'assert_database_name',
    'confirmed immutable basis',
    'Planning',
    'StoryBlock',
    'confirmed Outline',
    'ChapterSession',
    'WorkingDraft',
    'BROWSER_PROVIDER_BASE_URL',
    'stream=1',
    'supports_streaming=1',
    'verify-postconditions',
    'Candidate',
    'recovery',
    'terminal operation/event',
  ]) assert.equal(compact(fixture).includes(compact(fragment)), true, fragment)
  for (const fragment of [
    'fullyParallel: false',
    'workers: 1',
    'preserveOutput: \'never\'',
    'BROWSER_DENY_PROXY_URL',
    'BROWSER_ALLOWED_ORIGINS',
    'allowedOrigins.length !== 2',
    'bypass: allowedOrigins.map',
  ]) assert.equal(compact(config).includes(compact(fragment)), true, fragment)

  assertSafeBrowserGraph(entry, relativePath => source(relativePath))
  const declarations = collectBrowserTestDeclarations(spec, entry)
  assert.deepEqual(declarations.map(item => item.title), [
    '@complete streams a readonly preview and reloads an editable WorkingDraft',
    '@reconnect reload restores one persisted partial without provider recall',
    '@cancel-output preserves the latest partial after reload',
    '@cancel-empty restores the original WorkingDraft after reload',
  ])
  for (const declaration of declarations) {
    assert.match(declaration.bodySource, /openWriter\(page\)/u)
    assert.match(declaration.bodySource, /runtime\.finish\(\)/u)
    assert.match(declaration.bodySource, /assertHealthy\(evidence/u)
  }
  const reconnect = declarations.find(item => item.title.startsWith('@reconnect '))
  assert.ok(reconnect)
  const recoveryStatus = "await expect(page.getByRole('status')).toHaveText('正在恢复连接')"
  const readonly = "await expect(editor).toHaveAttribute('readonly', '')"
  const scalar = 'await expect.poll(() => editorScalarCount(editor)).toBe(PARTIAL_SCALAR_COUNT)'
  for (const checkpoint of [recoveryStatus, readonly, scalar]) {
    assert.equal(reconnect.bodySource.includes(checkpoint), true, checkpoint)
  }
  const workspaceObserver = 'const workspaceReload = page.waitForResponse(response => isLoopbackGet(response, workspaceReloadPath))'
  const operationObserver = 'const operationReload = page.waitForResponse(response => isLoopbackGet(response, activeDraftOperationReloadPath))'
  const reloadedResponses = 'const [workspaceResponse, operationResponse] = await reloadWithRecoveryObservers(page, workspaceReload, operationReload)'
  const workspaceStatus = 'await expect(workspaceResponse.status()).toBe(200)'
  const operationStatus = 'await expect(operationResponse.status()).toBe(200)'
  assert.equal(reconnect.bodySource.includes(workspaceObserver), true, workspaceObserver)
  assert.equal(reconnect.bodySource.includes(operationObserver), true, operationObserver)
  assert.equal(reconnect.bodySource.includes(reloadedResponses), true, reloadedResponses)
  assert.equal(reconnect.bodySource.includes(workspaceStatus), true, workspaceStatus)
  assert.equal(reconnect.bodySource.includes(operationStatus), true, operationStatus)
  assert.notEqual(
    reconnect.bodySource.slice(0, reconnect.bodySource.indexOf(workspaceObserver)).split('\n').length,
    reconnect.bodySource.slice(0, reconnect.bodySource.indexOf(operationObserver)).split('\n').length,
  )
  assert.notEqual(
    reconnect.bodySource.slice(0, reconnect.bodySource.indexOf(workspaceStatus)).split('\n').length,
    reconnect.bodySource.slice(0, reconnect.bodySource.indexOf(operationStatus)).split('\n').length,
  )
  assert.doesNotMatch(spec, /function observeLoopbackGet200\(/u)
  assert.ok(reconnect.bodySource.indexOf('reloadWithRecoveryObservers') < reconnect.bodySource.indexOf(recoveryStatus))
  assert.ok(reconnect.bodySource.indexOf(recoveryStatus) < reconnect.bodySource.indexOf(readonly))
  assert.ok(reconnect.bodySource.indexOf(readonly) < reconnect.bodySource.lastIndexOf(scalar))
  const extractFunction = name => {
    const start = spec.indexOf(`function ${name}(`)
    assert.ok(start >= 0, name)
    const bodyStart = spec.indexOf('{', start)
    let depth = 0
    for (let index = bodyStart; index < spec.length; index += 1) {
      if (spec[index] === '{') depth += 1
      if (spec[index] === '}' && --depth === 0) return spec.slice(start, index + 1)
    }
    throw new Error(`unterminated ${name}`)
  }
  const isLoopbackGet = new Function(`return (${extractFunction('isLoopbackGet')})`)()
  const cancelOutput = declarations.find(item => item.title.startsWith('@cancel-output '))
  assert.ok(cancelOutput)
  assert.match(cancelOutput.bodySource, /expect\(page\.getByText\('已停止，已保留生成内容'\)\)\.toBeVisible\(\)/u)
  const response = ({ url, method = 'GET', status = 200 }) => ({
    url: () => url,
    request: () => ({ method: () => method }),
    status: () => status,
    body: () => { throw new Error('response body must not be read') },
  })
  const projectId = '81000000-0000-0000-0000-000000000001'
  const { workspaceReloadPath, activeDraftOperationReloadPath } = new Function(`return (${extractFunction('createReloadResponsePaths')})`)()(projectId)
  assert.equal(isLoopbackGet(response({ url: `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/1` }), workspaceReloadPath), true)
  assert.equal(isLoopbackGet({
    url: () => `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/1`,
    request: () => ({ method: () => 'GET' }),
    status: () => { throw new Error('matcher must not read response status') },
    body: () => { throw new Error('response body must not be read') },
  }, workspaceReloadPath), true)
  assert.equal(isLoopbackGet(response({ url: `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/11111111-1111-1111-1111-111111111111/draft-operations/22222222-2222-2222-2222-222222222222` }), activeDraftOperationReloadPath), true)
  for (const sample of [
    response({ url: `https://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/1` }),
    response({ url: `http://localhost:4310/api/projects/${projectId}/chapter-sessions/1` }),
    response({ url: `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/1`, method: 'POST' }),
    response({ url: `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/2` }),
  ]) assert.equal(isLoopbackGet(sample, workspaceReloadPath), false)
  for (const sample of [
    response({ url: 'http://127.0.0.1:4310/api/projects/81000000-0000-0000-0000-000000000002/chapter-sessions/11111111-1111-1111-1111-111111111111/draft-operations/22222222-2222-2222-2222-222222222222' }),
    response({ url: `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/not-a-uuid/draft-operations/22222222-2222-2222-2222-222222222222` }),
    response({ url: `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/11111111-1111-1111-1111-111111111111/draft-operations/not-a-uuid` }),
    response({ url: `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/11111111-1111-1111-1111-111111111111/draft-operations` }),
    response({ url: `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/11111111-1111-1111-1111-111111111111/draft-operations/22222222-2222-2222-2222-222222222222/events` }),
    response({ url: `https://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/11111111-1111-1111-1111-111111111111/draft-operations/22222222-2222-2222-2222-222222222222` }),
    response({ url: `http://localhost:4310/api/projects/${projectId}/chapter-sessions/11111111-1111-1111-1111-111111111111/draft-operations/22222222-2222-2222-2222-222222222222` }),
    response({ url: `http://127.0.0.1:4310/api/projects/${projectId}/chapter-sessions/11111111-1111-1111-1111-111111111111/draft-operations/22222222-2222-2222-2222-222222222222`, method: 'POST' }),
  ]) assert.equal(isLoopbackGet(sample, activeDraftOperationReloadPath), false)
  const reloadWithRecoveryObservers = new Function(`return (${extractFunction('reloadWithRecoveryObservers')})`)()
  for (const reload of [
    () => Promise.reject(new Error('reload failure')),
    () => { throw new Error('reload failure') },
  ]) {
    const consumed = []
    const observer = name => {
      const promise = new Promise(() => {})
      const nativeThen = promise.then
      Object.defineProperty(promise, 'then', {
        value(...args) { consumed.push(name); return nativeThen.call(this, ...args) },
      })
      return promise
    }
    await assert.rejects(
      reloadWithRecoveryObservers({ reload() { assert.deepEqual(consumed, ['workspace', 'operation']); return reload() } }, observer('workspace'), observer('operation')),
      /reload failure/u,
    )
    assert.deepEqual(consumed, ['workspace', 'operation'])
  }
  for (const fragment of [
    'observeRuntime',
    'assertRuntimeEvidenceHealthy',
    'createHash',
    'waitForAcceptedProviderCall',
    'BROWSER_PROVIDER_LEDGER_PATH',
    'workspaceReloadPath',
    'activeDraftOperationReloadPath',
  ]) assert.equal(spec.includes(fragment), true, `missing ${fragment}`)
  const partialIndex = spec.indexOf('toBe(PARTIAL_SCALAR_COUNT)')
  const completionIndex = spec.indexOf('toBe(COMPLETE_SCALAR_COUNT)')
  assert.ok(partialIndex >= 0 && completionIndex > partialIndex)
  assert.equal(source('frontend/e2e/run-phase4b2.mjs').includes('GENERATED_TEXT_MARKERS'), true)
  assert.doesNotMatch(spec, /page\.request|page\.route|page\.evaluate|\bfetch\s*\(|\baxios\b/u)
})


test('Phase 4B2 content digests are fixed and shared by browser, runner, and verifier', async () => {
  const spec = source('frontend/e2e/phase4b2-draft-streaming.spec.ts')
  const runner = source('frontend/e2e/run-phase4b2.mjs')
  const fixture = source('backend/scripts/prepare_phase4b2_browser_db.py')
  const runnerModule = await import('../../frontend/e2e/run-phase4b2.mjs')
  const partial = '雨'.repeat(256)
  const complete = partial + '记'
  const names = [
    'PARTIAL_OUTPUT_SHA256',
    'COMPLETED_OUTPUT_SHA256',
  ]
  for (const name of names) {
    const expected = name.startsWith('PARTIAL') ? sha256(partial) : sha256(complete)
    assert.equal(fixedConstant(spec, name), expected)
    assert.equal(fixedConstant(runner, name), expected)
    assert.equal(fixedConstant(fixture, name), expected)
  }
  assert.equal(sha256(runnerModule.GENERATED_TEXT_MARKERS[0]), sha256(partial))
  assert.equal(runnerModule.GENERATED_TEXT_MARKERS[1].codePointAt(0), 0x8bb0)
  assert.equal(sha256(runnerModule.GENERATED_TEXT_MARKERS[2]), sha256(complete))
  for (const fragment of [
    "const partial = '雨'.repeat(256)",
    "const completion = '记'",
    'delta(partial)',
    'delta(completion)',
  ]) assert.equal(runner.includes(fragment), true, 'fake stream marker is incomplete')
})


test('Phase 4B2 fake SSE header passes the real chapter draft provider validator', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const headers = [...runner.FAKE_STREAMING_PROVIDER_SOURCE.matchAll(/'content-type': '([^']+)'/gu)]
  const match = headers.at(-1)
  assert.ok(match, 'fake SSE header is missing')
  const verification = spawnSync(PYTHON_COMMAND, ['-c', [
    'import sys, httpx',
    'from backend.gateways.chapter_draft_provider import ChapterDraftProviderGateway',
    'ChapterDraftProviderGateway._validate_stream_headers(httpx.Response(200, headers={"content-type": sys.argv[1]}))',
  ].join('\n'), match[1]], {
    cwd: repositoryRoot,
    encoding: 'utf8',
    timeout: 5_000,
    windowsHide: true,
    env: PYTHON_ENVIRONMENT,
  })
  assert.equal(verification.status, 0, 'fake SSE header was not accepted')
})


test('Phase 4B2 fixture passes only single-connection kwargs to its transaction factory', () => {
  const verification = spawnSync(PYTHON_COMMAND, ['-c', [
    'import asyncio',
    'from backend.scripts.prepare_phase4b2_browser_db import _configuration',
    'from backend.tests.support import disposable_mysql',
    'captured = {}',
    'class Raw:',
    '    async def begin(self): pass',
    '    async def commit(self): pass',
    '    def close(self): pass',
    'async def connect(**kwargs): captured.update(kwargs); return Raw()',
    'async def main():',
    '    config = _configuration("novel_creator_test_0123456789abcdef0123456789abcdef")',
    '    assert "minsize" not in config and "maxsize" not in config',
    '    disposable_mysql.aiomysql.connect = connect',
    '    async with disposable_mysql.transaction_factory_for(config)(): pass',
    '    assert "minsize" not in captured and "maxsize" not in captured and captured["autocommit"] is False',
    'asyncio.run(main())',
  ].join('\n')], {
    cwd: repositoryRoot,
    encoding: 'utf8',
    timeout: 5_000,
    windowsHide: true,
    env: {
      ...PYTHON_ENVIRONMENT,
      MYSQL_HOST: '127.0.0.1',
      MYSQL_PORT: '33060',
      MYSQL_USER: 'fixture-contract',
      MYSQL_PASSWORD: 'fixture-contract',
    },
  })
  assert.equal(verification.status, 0, 'Phase4B2 transaction connection kwargs are invalid')
})


test('Phase 4B2 verifier accepts consistent heartbeat snapshots and exact recovery rows', () => {
  const verification = spawnSync(PYTHON_COMMAND, ['-c', [
    'from backend.scripts.prepare_phase4b2_browser_db import assert_exactly_one_attempt, assert_postcondition_snapshot, PARTIAL_OUTPUT_SHA256, COMPLETED_OUTPUT_SHA256, EMPTY_OUTPUT_SHA256',
    'base_hash = EMPTY_OUTPUT_SHA256',
    'def events(*types): return [{"sequence_num": index, "event_type": value} for index, value in enumerate(types, 1)]',
    'def recovery(operation, result_hash): return [{"working_draft_revision": 1, "content_hash": base_hash, "snapshot_role": "before", "source_operation_id": operation}, {"working_draft_revision": 2, "content_hash": result_hash, "snapshot_role": "after", "source_operation_id": operation}]',
    'def complete_attempt(operation="complete"): return {"id": operation, "status": "completed", "base_working_draft_revision": 1, "base_working_draft_hash": base_hash, "partial_output_hash": COMPLETED_OUTPUT_SHA256, "partial_output_scalars": 257, "result_working_draft_revision": 2, "result_content_hash": COMPLETED_OUTPUT_SHA256, "last_event_sequence": 4}',
    'def partial_attempt(operation, status): return {"id": operation, "status": status, "base_working_draft_revision": 1, "base_working_draft_hash": base_hash, "partial_output_hash": PARTIAL_OUTPUT_SHA256, "partial_output_scalars": 256, "result_working_draft_revision": 2 if status == "cancelled" else None, "result_content_hash": PARTIAL_OUTPUT_SHA256 if status == "cancelled" else None, "last_event_sequence": 0}',
    'def reject(call):',
    '    try: call()',
    '    except RuntimeError: return',
    '    raise AssertionError()',
    'complete = complete_attempt()',
    'assert_exactly_one_attempt([complete])',
    'assert_postcondition_snapshot({"active_draft_operation_id": None}, {"total": 0}, complete, {"revision": 2, "content_hash": COMPLETED_OUTPUT_SHA256}, events("started", "delta", "delta", "completed"), tuple(recovery("complete", COMPLETED_OUTPUT_SHA256)), "complete")',
    'reconnect = partial_attempt("reconnect", "running"); reconnect["last_event_sequence"] = 3',
    'assert_postcondition_snapshot({"active_draft_operation_id": "reconnect"}, {"total": 0}, reconnect, {"revision": 1, "content_hash": base_hash}, events("started", "delta", "heartbeat"), tuple(), "reconnect")',
    'cancel = partial_attempt("cancel", "cancelled"); cancel["last_event_sequence"] = 4',
    'assert_postcondition_snapshot({"active_draft_operation_id": None}, {"total": 0}, cancel, {"revision": 2, "content_hash": PARTIAL_OUTPUT_SHA256}, events("started", "delta", "heartbeat", "cancelled"), tuple(recovery("cancel", PARTIAL_OUTPUT_SHA256)), "cancel-output")',
    'empty = {"id": "empty", "status": "cancelled", "base_working_draft_revision": 1, "base_working_draft_hash": base_hash, "partial_output_hash": EMPTY_OUTPUT_SHA256, "partial_output_scalars": 0, "result_working_draft_revision": None, "result_content_hash": None, "last_event_sequence": 3}',
    'assert_postcondition_snapshot({"active_draft_operation_id": None}, {"total": 0}, empty, {"revision": 1, "content_hash": base_hash}, events("started", "heartbeat", "cancelled"), tuple(), "cancel-empty")',
    'reject(lambda: assert_exactly_one_attempt([complete, complete]))',
    'bad_order = complete_attempt(); reject(lambda: assert_postcondition_snapshot({"active_draft_operation_id": None}, {"total": 0}, bad_order, {"revision": 2, "content_hash": COMPLETED_OUTPUT_SHA256}, events("started", "heartbeat", "delta", "delta", "completed"), recovery("complete", COMPLETED_OUTPUT_SHA256), "complete"))',
    'bad_delta_count = complete_attempt(); bad_delta_count["last_event_sequence"] = 3; reject(lambda: assert_postcondition_snapshot({"active_draft_operation_id": None}, {"total": 0}, bad_delta_count, {"revision": 2, "content_hash": COMPLETED_OUTPUT_SHA256}, events("started", "delta", "completed"), recovery("complete", COMPLETED_OUTPUT_SHA256), "complete"))',
    'wrong_base = complete_attempt(); wrong_base["base_working_draft_revision"] = 2; reject(lambda: assert_postcondition_snapshot({"active_draft_operation_id": None}, {"total": 0}, wrong_base, {"revision": 3, "content_hash": COMPLETED_OUTPUT_SHA256}, events("started", "delta", "delta", "completed"), [{"working_draft_revision": 2, "content_hash": base_hash, "snapshot_role": "before", "source_operation_id": "complete"}, {"working_draft_revision": 3, "content_hash": COMPLETED_OUTPUT_SHA256, "snapshot_role": "after", "source_operation_id": "complete"}], "complete"))',
  ].join('\n')], {
    cwd: repositoryRoot,
    encoding: 'utf8',
    timeout: 5_000,
    windowsHide: true,
    env: PYTHON_ENVIRONMENT,
  })
  assert.equal(verification.status, 0, 'Phase4B2 verifier snapshot contract failed')
  const fixture = source('backend/scripts/prepare_phase4b2_browser_db.py')
  const isolation = fixture.indexOf('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
  const snapshot = fixture.indexOf('START TRANSACTION READ ONLY, WITH CONSISTENT SNAPSHOT')
  assert.equal(isolation >= 0 && snapshot > isolation, true, 'verifier transaction order is invalid')
  assert.equal(fixture.includes('attempts = await session.fetchall('), true, 'verifier must load all attempts')
})


test('Phase 4B2 registers each acquired port before a later reservation failure', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  assert.equal(typeof runner.reserveOwnedPorts, 'function', 'Phase4B2 port reservation helper is missing')
  const calls = []
  let sequence = 0
  await assert.rejects(runOwnedProductLifecycle({
    async body(lifecycle) {
      lifecycle.setDatabase('owned-disposable')
      lifecycle.setRoot('owned-root')
      await runner.reserveOwnedPorts({
        count: 4,
        registerReservation: lifecycle.registerReservation,
        async portReservationFactory() {
          sequence += 1
          calls.push(`reserve:${sequence}`)
          if (sequence === 3) throw new Error('synthetic reservation failure')
          const port = sequence
          return { port, async release() { calls.push(`release:${port}`) } }
        },
      })
    },
    async stopServer() { calls.push('stop') },
    async releaseReservation(reservation) { await reservation.release() },
    async dropDatabase() { calls.push('drop') },
    async removeRoot() { calls.push('root') },
  }), /synthetic reservation failure/u)
  assert.deepEqual(calls, [
    'reserve:1', 'reserve:2', 'reserve:3', 'release:1', 'release:2', 'drop', 'root',
  ])
})


test('Phase 4B2 contract HTTP helpers bound requests and preserve all cleanup failures', async () => {
  const contract = source('scripts/tests/phase4B2BrowserContract.test.mjs')
  for (const fragment of [
    'HTTP_REQUEST_TIMEOUT_MS',
    'request.destroy(',
    'Promise.allSettled',
    'withOwnedCleanup',
  ]) assert.equal(contract.includes(fragment), true, `missing ${fragment}`)
  const calls = []
  await assert.rejects(withOwnedCleanup(async () => {
    throw new Error('primary')
  }, [
    [async () => { calls.push('stop'); throw new Error('stop') }, async () => { calls.push('release'); throw new Error('release') }],
    [async () => { calls.push('remove') }],
  ]), error => {
    assert.ok(error instanceof AggregateError)
    assert.equal(error.errors.length, 3)
    return true
  })
  assert.deepEqual(calls, ['stop', 'release', 'remove'])
})


test('Phase 4B2 CLI failure output is a fixed safe summary', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  assert.equal(
    runner.safeCliFailureSummary(),
    '{"stages":[{"stage":"lifecycle","count":1}]}',
  )
  const runnerSource = source('frontend/e2e/run-phase4b2.mjs')
  assert.equal(runnerSource.includes('console.error(safeCliFailureSummary(error))'), true)
  assert.equal(runnerSource.includes('console.error(error)'), false)
})


test('Phase 4B2 nested lifecycle failures project only allowlisted stage counts', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const rawEvidence = 'raw-secret-body /unsafe/path request-body=private'
  const failure = new AggregateError([
    runner.createSafeStageFailure('database-preparation', new Error(rawEvidence)),
    new AggregateError([
      runner.createSafeStageFailure('browser-test', new Error(rawEvidence)),
      new Error(rawEvidence),
    ]),
  ])
  const summary = runner.formatSafeStageSummary(failure)
  assert.equal(summary, '{"stages":[{"stage":"database-preparation","count":1},{"stage":"browser-test","count":1},{"stage":"lifecycle","count":1}]}')
  assert.equal(summary.includes(rawEvidence), false)
  assert.equal(runner.safeCliFailureSummary(failure).includes('"count":1'), true)
  assert.equal(runner.safeCliFailureSummary(failure).includes(rawEvidence), false)
})


test('Phase 4B2 safe stage formatter traverses error graphs without duplicate or raw evidence', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const rawEvidence = 'raw-secret-body /unsafe/path request-body=private'
  const cyclic = new AggregateError([])
  cyclic.errors.push(cyclic)
  const shared = runner.createSafeStageFailure('browser-test', new Error(rawEvidence))
  const duplicated = new AggregateError([shared, shared])
  const caused = new Error('outer', {
    cause: runner.createSafeStageFailure('canonical-fixture', new Error(rawEvidence)),
  })
  const empty = new AggregateError([])
  const cases = [
    [cyclic, '{"stages":[{"stage":"lifecycle","count":1}]}'],
    [duplicated, '{"stages":[{"stage":"browser-test","count":1}]}'],
    [caused, '{"stages":[{"stage":"canonical-fixture","count":1}]}'],
    [empty, '{"stages":[{"stage":"lifecycle","count":1}]}'],
  ]
  for (const [error, expected] of cases) {
    const summary = runner.formatSafeStageSummary(error)
    assert.equal(summary, expected)
    assert.equal(summary.includes(rawEvidence), false)
    assert.equal(runner.safeCliFailureSummary(error).includes(rawEvidence), false)
  }
})


test('Phase 4B2 browser failures project only owned fixed Playwright diagnostics', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase4b2-browser-result-'))
  const outsideRoot = mkdtempSync(path.join(os.tmpdir(), 'phase4b2-outside-result-'))
  const resultPath = path.join(root, 'browser-result.json')
  const raw = 'raw-secret-body /unsafe/path request-body=private'
  const scenario = runner.FORMAL_SCENARIOS.find(item => item.mode === 'reconnect')
  const fallback = { scenario: 'reconnect', passed: 0, failed: 0, skipped: 0, failureLine: 0, failureColumn: 0 }
  const report = (errors, { nestedSuites = undefined } = {}) => {
    const suite = {
      title: raw,
      specs: [{
        title: '@reconnect reload restores one persisted partial without provider recall',
        tests: [{
          title: raw,
          results: [{
            status: 'failed',
            errors,
            stdout: [{ text: raw }],
            stderr: [{ text: raw }],
            attachments: [{ name: raw, path: 'C:/unsafe/path/attachment.txt' }],
          }],
        }],
      }],
    }
    if (nestedSuites !== undefined) suite.suites = nestedSuites
    return { suites: [suite] }
  }
  try {
    writeFileSync(resultPath, JSON.stringify(report([
      { message: raw, stack: raw, snippet: raw, expected: raw, actual: raw, location: { file: 'C:/unsafe/path/foreign.spec.ts', line: 999, column: 7 } },
      { message: raw, stack: raw, location: { file: 'frontend/e2e/phase4b2-draft-streaming.spec.ts', line: 119, column: 13 } },
    ])), 'utf8')
    const diagnostics = runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario)
    assert.deepEqual(diagnostics, {
      scenario: 'reconnect', passed: 0, failed: 1, skipped: 0, failureLine: 119, failureColumn: 13,
    })
    const failure = runner.createBrowserTestStageFailure(
      { ownedRoot: root, browserResultPath: resultPath },
      scenario,
      new Error(raw),
    )
    const summary = runner.formatSafeStageSummary(failure)
    assert.equal(summary, JSON.stringify({ stages: [{
      stage: 'browser-test', count: 1, scenario: 'reconnect', passed: 0, failed: 1, skipped: 0, failureLine: 119, failureColumn: 13,
    }] }))
    for (const unsafe of [raw, 'C:/unsafe/path', 'attachment.txt', '@reconnect reload restores one persisted partial without provider recall']) {
      assert.equal(summary.includes(unsafe), false)
      assert.equal(runner.safeCliFailureSummary(failure).includes(unsafe), false)
    }
    writeFileSync(resultPath, JSON.stringify(report([
      { location: { file: 'C:/unsafe/path/foreign.spec.ts', line: 321, column: 4 } },
    ])), 'utf8')
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario), {
      ...fallback, failed: 1,
    })
    writeFileSync(resultPath, JSON.stringify(report([], { nestedSuites: {} })), 'utf8')
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario), fallback)
    writeFileSync(resultPath, '{ malformed JSON with raw-secret-body }', 'utf8')
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario), fallback)
    const sparseHandle = openSync(resultPath, 'w')
    try { ftruncateSync(sparseHandle, runner.MAX_SAFE_PLAYWRIGHT_RESULT_BYTES + 1) } finally { closeSync(sparseHandle) }
    let oversizedReads = 0
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      readSyncImpl() { oversizedReads += 1; throw new Error(raw) },
    }), fallback)
    assert.equal(oversizedReads, 0)
    writeFileSync(resultPath, Buffer.alloc(runner.MAX_SAFE_PLAYWRIGHT_RESULT_BYTES + 1))
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario), fallback)
    const stableStats = (overrides = {}) => ({
      size: 1n, dev: 1n, ino: 1n, mtimeNs: 1n, ctimeNs: 1n, isFile: () => true, isSymbolicLink: () => false, ...overrides,
    })
    const safeReport = Buffer.from(JSON.stringify(report([
      { location: { file: 'frontend/e2e/phase4b2-draft-streaming.spec.ts', line: 71, column: 2 } },
    ])))
    writeFileSync(resultPath, safeReport)
    let symlinkReads = 0
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      realpathSyncImpl(target) { return target === resultPath ? path.join(root, 'outside-target.json') : target },
      openSyncImpl() { symlinkReads += 1; throw new Error(raw) },
    }), fallback)
    assert.equal(symlinkReads, 0)
    let closedAfterReadFailure = 0
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      openSyncImpl() { return 41 },
      lstatSyncImpl() { return stableStats() },
      fstatSyncImpl() { return stableStats() },
      readSyncImpl() { throw new Error(raw) },
      closeSyncImpl() { closedAfterReadFailure += 1 },
      realpathSyncImpl(target) { return target },
    }), fallback)
    assert.equal(closedAfterReadFailure, 1)
    let closedAfterReplacement = 0
    let resultRealpaths = 0
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      openSyncImpl() { return 42 },
      lstatSyncImpl() { return stableStats() },
      fstatSyncImpl() { return stableStats() },
      readSyncImpl(_fd, buffer, offset, length) { safeReport.copy(buffer, offset, 0, Math.min(length, safeReport.length)); return safeReport.length },
      closeSyncImpl() { closedAfterReplacement += 1 },
      realpathSyncImpl(target) {
        if (target !== resultPath) return target
        resultRealpaths += 1
        return resultRealpaths === 1 ? target : path.join(outsideRoot, 'browser-result.json')
      },
    }), fallback)
    assert.equal(closedAfterReplacement, 1)
    let boundedLength = 0
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      openSyncImpl() { return 43 },
      lstatSyncImpl() { return stableStats() },
      fstatSyncImpl() { return stableStats() },
      readSyncImpl(_fd, _buffer, _offset, length) { boundedLength = length; return length },
      closeSyncImpl() {},
      realpathSyncImpl(target) { return target },
    }), fallback)
    assert.equal(boundedLength, runner.MAX_SAFE_PLAYWRIGHT_RESULT_BYTES + 1)
    let modifiedStats = 0
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      openSyncImpl() { return 44 },
      lstatSyncImpl() { return stableStats() },
      fstatSyncImpl() { modifiedStats += 1; return stableStats({ mtimeNs: BigInt(modifiedStats) }) },
      readSyncImpl() { return 0 },
      closeSyncImpl() {},
      realpathSyncImpl(target) { return target },
    }), fallback)
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      openSyncImpl() { return 45 },
      lstatSyncImpl() { return stableStats({ dev: 0n, ino: 0n }) },
      fstatSyncImpl() { return stableStats({ dev: 0n, ino: 0n }) },
      readSyncImpl() { throw new Error(raw) },
      closeSyncImpl() {},
      realpathSyncImpl(target) { return target },
    }), fallback)
    let swappedBeforeRead = 0
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      lstatSyncImpl() { return stableStats({ dev: 11n, ino: 12n }) },
      openSyncImpl() { return 46 },
      fstatSyncImpl() { return stableStats({ dev: 21n, ino: 22n }) },
      readSyncImpl() { swappedBeforeRead += 1; return 0 },
      closeSyncImpl() {},
      realpathSyncImpl(target) { return target },
    }), fallback)
    assert.equal(swappedBeforeRead, 0)
    let lstatCalls = 0
    let swappedAndRestoredReads = 0
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      lstatSyncImpl() {
        lstatCalls += 1
        return stableStats({ dev: 31n, ino: lstatCalls === 1 ? 32n : 33n })
      },
      openSyncImpl() { return 47 },
      fstatSyncImpl() { return stableStats({ dev: 31n, ino: 32n }) },
      readSyncImpl() { swappedAndRestoredReads += 1; return 0 },
      closeSyncImpl() {},
      realpathSyncImpl(target) { return target },
    }), fallback)
    assert.equal(swappedAndRestoredReads, 1)
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: resultPath }, scenario, {
      realpathSyncImpl() { throw new Error(raw) },
    }), fallback)
    const outsidePath = path.join(outsideRoot, 'browser-result.json')
    writeFileSync(outsidePath, JSON.stringify(report([])), 'utf8')
    assert.deepEqual(runner.readSafePlaywrightFailure({ ownedRoot: root, browserResultPath: outsidePath }, scenario), fallback)
    const otherStage = runner.createSafeStageFailure('database-preparation', Object.assign(new Error(raw), {
      browserTestDiagnostics: diagnostics,
    }))
    assert.equal(
      runner.formatSafeStageSummary(otherStage),
      JSON.stringify({ stages: [{ stage: 'database-preparation', count: 1 }] }),
    )
  } finally {
    rmSync(root, { recursive: true, force: true })
    rmSync(outsideRoot, { recursive: true, force: true })
  }
})


test('Phase 4B2 path identity folds case only on Windows', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  assert.equal(
    runner.samePathIdentity('/Owned/Result.json', '/owned/result.json', { platform: 'win32' }),
    true,
  )
  assert.equal(
    runner.samePathIdentity('/Owned/Result.json', '/owned/result.json', { platform: 'linux' }),
    false,
  )
  const config = source('frontend/e2e/playwright.phase4b2.config.ts')
  assert.equal(config.includes("process.platform === 'win32'"), true)
})


test('Phase 4B2 fake provider rejects an over-limit request before the request body ends', { timeout: 15_000 }, async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase4b2-provider-'))
  const sourcePath = path.join(root, 'fake-provider.cjs')
  const ledgerPath = path.join(root, 'provider-ledger.log')
  const reservation = await reserveLocalPort()
  const nonce = 'phase4b2-provider-contract'
  let child = null
  let pendingRequest = null
  await withOwnedCleanup(async () => {
    writeFileSync(sourcePath, runner.FAKE_STREAMING_PROVIDER_SOURCE, 'utf8')
    writeFileSync(ledgerPath, '', 'utf8')
    await reservation.release()
    child = spawn(process.execPath, [sourcePath, String(reservation.port)], {
      env: {
        ...process.env,
        M2_BROWSER_RUN_NONCE: nonce,
        BROWSER_PROVIDER_LEDGER_PATH: ledgerPath,
        BROWSER_SCENARIO_MODE: 'complete',
        BROWSER_SECRET_SENTINEL: 'contract-only-secret',
      },
      shell: false,
      stdio: 'ignore',
      windowsHide: true,
    })
    await waitForProvider(reservation.port, nonce)
    const status = await new Promise((resolve, reject) => {
      let settled = false
      let timer = null
      const finish = (error, value) => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        if (error) reject(error)
        else resolve(value)
      }
      const request = http.request({
        host: '127.0.0.1',
        port: reservation.port,
        method: 'POST',
        path: '/v1/chat/completions',
        headers: { authorization: 'Bearer contract-only-secret' },
      })
      pendingRequest = request
      request.once('response', response => { response.resume(); finish(null, response.statusCode) })
      request.once('error', error => finish(error))
      timer = setTimeout(() => {
        request.destroy(new Error('fake provider request timed out'))
        finish(new Error('fake provider did not reject an over-limit request before body end'))
      }, HTTP_REQUEST_TIMEOUT_MS)
      request.write(Buffer.alloc(65_537, 0x61))
    })
    assert.equal(status, 413)
    await new Promise(resolve => setTimeout(resolve, 25))
    assert.deepEqual(
      readFileSync(ledgerPath, 'utf8').split(/\r?\n/u).filter(Boolean),
      ['terminal=payload-too-large'],
    )
  }, [
    [async () => { pendingRequest?.destroy() }, async () => stopOwnedChild(child), async () => reservation.release()],
    [async () => rmSync(root, { recursive: true, force: true })],
  ])
})


test('Phase 4B2 fake provider counts accepted sockets separately from calls', { timeout: 15_000 }, async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase4b2-provider-'))
  const sourcePath = path.join(root, 'fake-provider.cjs')
  const ledgerPath = path.join(root, 'provider-ledger.log')
  const reservation = await reserveLocalPort()
  let child = null
  const keepAlive = new http.Agent({ keepAlive: true, maxSockets: 1 })
  await withOwnedCleanup(async () => {
    writeFileSync(sourcePath, runner.FAKE_STREAMING_PROVIDER_SOURCE, 'utf8')
    writeFileSync(ledgerPath, '', 'utf8')
    await reservation.release()
    child = spawn(process.execPath, [sourcePath, String(reservation.port)], {
      env: { ...process.env, M2_BROWSER_RUN_NONCE: 'socket-contract', BROWSER_PROVIDER_LEDGER_PATH: ledgerPath, BROWSER_SCENARIO_MODE: 'complete', BROWSER_SECRET_SENTINEL: 'contract-only-secret' },
      shell: false, stdio: 'ignore', windowsHide: true,
    })
    await waitForProvider(reservation.port, 'socket-contract')
    assert.equal(await providerRequest(reservation.port, keepAlive), 200)
    assert.equal(await providerRequest(reservation.port, keepAlive), 200)
    assert.equal(await providerRequest(reservation.port, false), 200)
    const entries = readFileSync(ledgerPath, 'utf8').split(/\r?\n/u).filter(Boolean)
    assert.deepEqual(entries.filter(entry => entry.startsWith('connection=')), [
      'connection=1', 'connection=1', 'connection=2',
    ])
    assert.deepEqual(entries.filter(entry => entry.startsWith('call=')), [
      'call=1', 'call=2', 'call=3',
    ])
  }, [
    [async () => { keepAlive.destroy() }, async () => stopOwnedChild(child), async () => reservation.release()],
    [async () => rmSync(root, { recursive: true, force: true })],
  ])
})


test('Phase 4B2 root cleanup removes its owned root after an audit failure', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase4b2-cleanup-'))
  try {
    await assert.rejects(runner.cleanupOwnedRoot({
      root,
      roots: { artifactRoot: root, browserResultPath: path.join(root, 'result.json') },
      ports: [],
      sensitiveValues: [],
      assertArtifactEvidenceSafeImpl() { throw new Error('synthetic audit failure') },
    }), /Phase4B2 root cleanup failed/u)
    assert.equal(existsSync(root), false)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})


test('Phase 4B2 root cleanup attempts every audit and removal after multiple failures', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase4b2-cleanup-'))
  const calls = []
  try {
    await assert.rejects(runner.cleanupOwnedRoot({
      root,
      roots: { artifactRoot: root },
      ports: [40111, 40112],
      sensitiveValues: [],
      async waitForPortReleaseImpl(port) { calls.push(`port:${port}`); throw new Error('port') },
      ownedViteTempCacheEntriesImpl() { calls.push('vite'); return ['deps_temp_owned'] },
      assertArtifactEvidenceSafeImpl() { calls.push('artifact'); throw new Error('artifact') },
      removeOwnedRootImpl(target) { calls.push('remove'); rmSync(target, { recursive: true, force: true }) },
    }), error => {
      assert.ok(error instanceof AggregateError)
      assert.equal(error.errors.length, 4)
      return true
    })
    assert.deepEqual(calls, ['port:40111', 'port:40112', 'vite', 'artifact', 'remove'])
    assert.equal(existsSync(root), false)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})


test('Phase 4B2 backend outbound ledger rejects every non-exact value without echoing it', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  for (const value of ['', 'forbidden-outbound\n', 'allowed-local-provider\nallowed-local-provider\n', 'allowed-local-provider\nforbidden-outbound\n']) {
    assert.throws(() => runner.assertBackendOutboundLedger(value), error => (
      error.message === 'backend outbound ledger did not match the loopback-only contract'
      && (value === '' || !error.message.includes(value))
    ))
  }
})


test('Phase 4B2 generated backend ledger literals evaluate to token-delimited records', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const evaluatePythonSingleQuotedLiteral = literal => {
    assert.match(literal, /^'(?:[^'\\]|\\.)*'$/su)
    const escapes = new Map([['n', '\n'], ['r', '\r'], ['t', '\t'], ['\\', '\\'], ["'", "'"]])
    let evaluated = ''
    for (let index = 1; index < literal.length - 1; index += 1) {
      const character = literal[index]
      if (character !== '\\') {
        evaluated += character
        continue
      }
      const escaped = literal[index += 1]
      assert.ok(escapes.has(escaped))
      evaluated += escapes.get(escaped)
    }
    return evaluated
  }
  for (const token of ['allowed-local-provider', 'forbidden-outbound']) {
    const expression = new RegExp(String.raw`output\.write\(('${token}(?:[^'\\]|\\.)*')\)`, 'u')
    const literal = runner.BACKEND_SOURCE.match(expression)?.[1]
    assert.ok(literal)
    assert.equal(evaluatePythonSingleQuotedLiteral(literal), `${token}\n`)
  }
})

test('Phase 4B2 outbound audit projects fixed counters without ledger evidence', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const malformed = 'raw-secret-body /unsafe/path request-body=private'
  const cases = [
    ['', { allowed: 0, forbidden: 0, malformed: 1, total: 1 }],
    ['allowed-local-provider\nallowed-local-provider\n', { allowed: 2, forbidden: 0, malformed: 0, total: 2 }],
    ['forbidden-outbound\n', { allowed: 0, forbidden: 1, malformed: 0, total: 1 }],
    ['allowed-local-provider\nforbidden-outbound\n', { allowed: 1, forbidden: 1, malformed: 0, total: 2 }],
    [`${malformed}\n`, { allowed: 0, forbidden: 0, malformed: 1, total: 1 }],
  ]
  for (const [ledger, counters] of cases) {
    let failure = null
    assert.throws(() => runner.assertBackendOutboundLedger(ledger), error => {
      failure = error
      return error.message === 'backend outbound ledger did not match the loopback-only contract'
    })
    assert.deepEqual(failure.outboundAuditCounters, counters)
    const summary = runner.formatSafeStageSummary(
      runner.createSafeStageFailure('outbound-audit', failure),
    )
    assert.equal(summary, JSON.stringify({ stages: [{ stage: 'outbound-audit', count: 1, ...counters }] }))
    assert.equal(summary.includes(malformed), false)
    assert.equal(summary.includes('allowed-local-provider'), false)
    assert.equal(summary.includes('forbidden-outbound'), false)
    assert.equal(runner.safeCliFailureSummary(runner.createSafeStageFailure('outbound-audit', failure)).includes(malformed), false)
  }
  assert.doesNotThrow(() => runner.assertBackendOutboundLedger('allowed-local-provider\r\n'))
})


test('Phase 4B2 artifact audit rejects generated output without putting it in a failure', async () => {
  const runner = await import('../../frontend/e2e/run-phase4b2.mjs')
  const root = mkdtempSync(path.join(os.tmpdir(), 'novel-creator-phase4b2-artifact-'))
  const artifactPath = path.join(root, 'result.json')
  try {
    for (const marker of runner.GENERATED_TEXT_MARKERS) {
      writeFileSync(artifactPath, marker, 'utf8')
      assert.throws(
        () => runner.assertArtifactEvidenceSafe(root, [], [artifactPath]),
        error => {
          assert.equal(error.message, 'Phase4B2 artifact contains sensitive evidence')
          assert.equal(error.message.includes(marker), false)
          return true
        },
      )
    }
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})

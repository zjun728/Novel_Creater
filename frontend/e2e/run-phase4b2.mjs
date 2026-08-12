import { randomUUID } from 'node:crypto'
import {
  closeSync,
  existsSync,
  constants as fsConstants,
  fstatSync,
  lstatSync,
  mkdirSync,
  openSync,
  readSync,
  readFileSync,
  readdirSync,
  realpathSync,
  writeFileSync,
} from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import {
  BASE_ENV_ALLOWLIST,
  assertDatabaseName,
  assertOwnedRoot,
  createDatabaseName,
  createOwnedRoot,
  removeOwnedRoot,
  reserveLocalPort,
  runBoundedOwnedCommand,
  runOwnedProductLifecycle,
  startOwnedServer,
  stopOwnedServer,
  validateTestEnvironment,
  waitForOwnedServer,
} from './support/product-runner.mjs'
import { DENY_PROXY_SOURCE, assertDenyProxyLedger } from './support/deny-proxy.mjs'
import { assertDatabaseResidue } from './support/database-residue.mjs'
import { formatSafeLifecycleDiagnostics } from './support/safe-diagnostics.mjs'
import { assertNoPrivateEvidenceMarkers, runtimeSensitiveValues } from './runtime-observer.mjs'


export const FORMAL_SPECS = Object.freeze(['phase4b2-draft-streaming.spec.ts'])
export const FORMAL_CONFIG = 'playwright.phase4b2.config.ts'
export const FORMAL_SCENARIOS = Object.freeze([
  Object.freeze({ tag: '@complete', mode: 'complete' }),
  Object.freeze({ tag: '@reconnect', mode: 'reconnect' }),
  Object.freeze({ tag: '@cancel-output', mode: 'cancel-output' }),
  Object.freeze({ tag: '@cancel-empty', mode: 'cancel-empty' }),
])
const FORMAL_SCENARIO_TITLES = Object.freeze({
  complete: '@complete streams a readonly preview and reloads an editable WorkingDraft',
  reconnect: '@reconnect reload restores one persisted partial without provider recall',
  'cancel-output': '@cancel-output preserves the latest partial after reload',
  'cancel-empty': '@cancel-empty restores the original WorkingDraft after reload',
})
const FORMAL_SCENARIO_BY_MODE = new Map(FORMAL_SCENARIOS.map(item => [item.mode, item]))
export const SAFE_STAGE_ALLOWLIST = Object.freeze([
  'database-preparation',
  'canonical-fixture',
  'fake-provider-start',
  'backend-start',
  'deny-proxy-start',
  'vite-start',
  'browser-test',
  'outbound-audit',
  'deny-proxy-audit',
  'postcondition-verifier',
  'provider-ledger-audit',
  'database-cleanup',
  'root-cleanup',
  'lifecycle',
])
const SAFE_STAGE_SET = new Set(SAFE_STAGE_ALLOWLIST)
const OUTBOUND_AUDIT_COUNTER_KEYS = Object.freeze(['allowed', 'forbidden', 'malformed', 'total'])
const BROWSER_TEST_DIAGNOSTIC_KEYS = Object.freeze(['passed', 'failed', 'skipped', 'failureLine', 'failureColumn'])
export const MAX_SAFE_PLAYWRIGHT_RESULT_BYTES = 2 * 1024 * 1024

function safeOutboundAuditCounters(value) {
  return Object.freeze(Object.fromEntries(OUTBOUND_AUDIT_COUNTER_KEYS.map(key => [
    key,
    Number.isSafeInteger(value?.[key]) && value[key] >= 0 ? value[key] : 0,
  ])))
}

function safeBrowserTestDiagnostics(value, fallbackMode = 'complete') {
  const scenario = FORMAL_SCENARIO_BY_MODE.has(value?.scenario) ? value.scenario : fallbackMode
  return Object.freeze({
    scenario: FORMAL_SCENARIO_BY_MODE.has(scenario) ? scenario : 'complete',
    ...Object.fromEntries(BROWSER_TEST_DIAGNOSTIC_KEYS.map(key => [
      key,
      Number.isSafeInteger(value?.[key]) && value[key] >= 0 ? value[key] : 0,
    ])),
  })
}

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const FORMAL_SPEC_PATH = path.join(frontendRoot, 'e2e', FORMAL_SPECS[0])
const OWNED_ROOT_PREFIX = 'novel-creator-phase4b2-'
// Disposable database names are generated only as novel_creator_test_<uuid32>.
const PROJECT_ID = '81000000-0000-0000-0000-000000000001'
const SECRET_SENTINEL = 'phase4b2-browser-secret-must-not-leak'
const PARTIAL_OUTPUT = '雨'.repeat(256)
const COMPLETION_DELTA = '记'
export const PARTIAL_OUTPUT_SHA256 = 'f0a0b60f973a06b3723525ece56b44231bf8b4d1715e7356d2d008063767741f'
export const COMPLETED_OUTPUT_SHA256 = 'c88ade88d9dd15b14d6bd8b9c7662072148fdb8dc4fc714d56a9fb9a31f12fbe'
export const GENERATED_TEXT_MARKERS = Object.freeze([
  PARTIAL_OUTPUT,
  COMPLETION_DELTA,
  PARTIAL_OUTPUT + COMPLETION_DELTA,
])
const DEFAULT_DEADLINES = Object.freeze({ commandMs: 90_000, healthMs: 45_000, browserMs: 180_000, stopMs: 8_000 })

export const FAKE_STREAMING_PROVIDER_SOURCE = String.raw`
const { appendFileSync } = require('node:fs')
const http = require('node:http')
const port = Number(process.argv[2])
const nonce = process.env.M2_BROWSER_RUN_NONCE
const ledgerPath = process.env.BROWSER_PROVIDER_LEDGER_PATH
const scenario = process.env.BROWSER_SCENARIO_MODE
const secret = process.env.BROWSER_SECRET_SENTINEL
const partial = '雨'.repeat(256)
const completion = '记'
const REQUEST_LIMIT = 65536
const socketIds = new WeakMap()
let nextConnection = 0
let calls = 0
function record(value) { appendFileSync(ledgerPath, value + '\n', 'utf8') }
function reject(response, status, terminal) { response.writeHead(status); response.end(); record('terminal=' + terminal) }
function connectionId(socket) {
  if (!socketIds.has(socket)) socketIds.set(socket, ++nextConnection)
  return socketIds.get(socket)
}
http.createServer((request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end(JSON.stringify({ browserRunNonce: nonce }))
    return
  }
  if (request.method !== 'POST' || request.url !== '/v1/chat/completions') return reject(response, 404, 'rejected')
  let size = 0
  let body = ''
  let rejected = false
  request.on('data', chunk => {
    if (rejected) return
    size += chunk.length
    if (size > REQUEST_LIMIT) {
      rejected = true
      reject(response, 413, 'payload-too-large')
      request.destroy()
      return
    }
    body += chunk.toString('utf8')
  })
  request.on('end', () => {
    if (rejected) return
    let valid = false
    try { valid = request.headers.authorization === 'Bearer ' + secret && JSON.parse(body).stream === true } catch {}
    if (!valid) return reject(response, 400, 'rejected')
    const connection = connectionId(request.socket)
    calls += 1
    record('scenario=' + scenario); record('method=POST path=/v1/chat/completions status=200')
    record('connection=' + connection); record('call=' + calls)
    response.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' })
    const delta = text => response.write('data: ' + JSON.stringify({ choices: [{ index: 0, delta: { content: text } }] }) + '\n\n')
    let terminal = false
    const closeCancelled = () => {
      if (!terminal) { terminal = true; record('terminal=transport-closed') }
    }
    const done = () => {
      if (terminal) return
      terminal = true
      response.write('data: [DONE]\n\n')
      response.end()
      record('terminal=completed')
    }
    response.once('close', closeCancelled)
    if (scenario === 'cancel-empty') return
    delta(partial)
    if (scenario === 'complete') return setTimeout(() => { delta(completion); done() }, 1100)
  })
}).listen(port, '127.0.0.1')
`

export const BACKEND_SOURCE = String.raw`
import os, sys
from urllib.parse import urlsplit
import httpx, uvicorn
provider = urlsplit(os.environ['BROWSER_PROVIDER_BASE_URL'])
ledger = os.environ['BROWSER_OUTBOUND_LEDGER_PATH']
RealAsyncClient = httpx.AsyncClient
class GuardedAsyncClient:
    def __init__(self, *args, **kwargs): self.inner = RealAsyncClient(*args, **kwargs)
    async def __aenter__(self): await self.inner.__aenter__(); return self
    async def __aexit__(self, *args): return await self.inner.__aexit__(*args)
    async def aclose(self): return await self.inner.aclose()
    def build_request(self, *args, **kwargs): return self.inner.build_request(*args, **kwargs)
    def guard(self, method, url):
        target = urlsplit(str(url))
        if not (str(method).upper() == 'POST' and target.scheme == 'http' and target.hostname == '127.0.0.1' and target.port == provider.port and target.path == '/v1/chat/completions' and not target.query and not target.fragment):
            with open(ledger, 'a', encoding='utf-8') as output: output.write('forbidden-outbound\n')
            raise RuntimeError('forbidden outbound request')
        with open(ledger, 'a', encoding='utf-8') as output: output.write('allowed-local-provider\n')
    async def request(self, method, url, *args, **kwargs): self.guard(method, url); return await self.inner.request(method, url, *args, **kwargs)
    async def send(self, request, *args, **kwargs): self.guard(request.method, request.url); return await self.inner.send(request, *args, **kwargs)
    def stream(self, method, url, *args, **kwargs): self.guard(method, url); return self.inner.stream(method, url, *args, **kwargs)
    async def post(self, url, *args, **kwargs): return await self.request('POST', url, *args, **kwargs)
httpx.AsyncClient = GuardedAsyncClient
from backend.main import app
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
`

function sourceRoot(ownedRoot) {
  const artifactRoot = path.join(ownedRoot, 'artifacts')
  const providerPath = path.join(ownedRoot, 'fake-provider.cjs')
  const backendPath = path.join(ownedRoot, 'backend.py')
  const denyProxyPath = path.join(ownedRoot, 'deny-proxy.cjs')
  const viteConfigPath = path.join(ownedRoot, 'vite.config.mjs')
  const browserResultPath = path.join(ownedRoot, 'browser-result.json')
  const providerLedgerPath = path.join(ownedRoot, 'provider-ledger.log')
  const outboundLedgerPath = path.join(ownedRoot, 'outbound-ledger.log')
  const denyProxyLedgerPath = path.join(ownedRoot, 'deny-proxy.log')
  mkdirSync(artifactRoot)
  for (const [target, value] of [[providerPath, FAKE_STREAMING_PROVIDER_SOURCE], [backendPath, BACKEND_SOURCE], [denyProxyPath, DENY_PROXY_SOURCE], [providerLedgerPath, ''], [outboundLedgerPath, ''], [denyProxyLedgerPath, '']]) writeFileSync(target, value, { encoding: 'utf8', flag: 'wx' })
  const base = pathToFileURL(path.join(frontendRoot, 'vite.config.js')).href
  writeFileSync(viteConfigPath, `import base from ${JSON.stringify(base)}\nexport default { ...base, cacheDir: ${JSON.stringify(path.join(ownedRoot, 'vite-cache'))}, optimizeDeps: { ...base.optimizeDeps, noDiscovery: false } }\n`, { encoding: 'utf8', flag: 'wx' })
  return { ownedRoot, artifactRoot, providerPath, backendPath, denyProxyPath, viteConfigPath, browserResultPath, providerLedgerPath, outboundLedgerPath, denyProxyLedgerPath }
}

function cleanEnvironment(environment, databaseName) {
  const base = Object.fromEntries(BASE_ENV_ALLOWLIST.filter(key => Object.hasOwn(environment, key)).map(key => [key, environment[key]]))
  return { ...base, TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST, TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT, TEST_MYSQL_USER: environment.TEST_MYSQL_USER, TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD, BROWSER_TEST_DATABASE: databaseName }
}

function childOptions(cwd, env) { return { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] } }

function isRecord(value) {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function knownScenario(value) {
  return FORMAL_SCENARIOS.find(item => item.mode === value?.mode && item.tag === value?.tag) || null
}

function safeResultStats(stats, { rejectLinks = false } = {}) {
  return Boolean(
    stats
    && typeof stats.isFile === 'function'
    && stats.isFile()
    && (!rejectLinks || (typeof stats.isSymbolicLink === 'function' && !stats.isSymbolicLink()))
    && typeof stats.size === 'bigint'
    && stats.size >= 0n
    && stats.size <= BigInt(MAX_SAFE_PLAYWRIGHT_RESULT_BYTES)
    && typeof stats.dev === 'bigint'
    && typeof stats.ino === 'bigint'
    && stats.dev > 0n
    && stats.ino > 0n
    && typeof stats.mtimeNs === 'bigint'
    && typeof stats.ctimeNs === 'bigint'
    && stats.mtimeNs >= 0n
    && stats.ctimeNs >= 0n
  )
}

function sameFileStats(left, right) {
  return left.size === right.size
    && left.dev === right.dev
    && left.ino === right.ino
    && left.mtimeNs === right.mtimeNs
    && left.ctimeNs === right.ctimeNs
}

function ownedBrowserResultPath(roots, { lstatSyncImpl, realpathSyncImpl }) {
  try {
    if (typeof roots?.ownedRoot !== 'string' || typeof roots?.browserResultPath !== 'string') return null
    const ownedRoot = assertOwnedRoot(roots.ownedRoot, OWNED_ROOT_PREFIX)
    if (!path.isAbsolute(roots.browserResultPath) || path.basename(roots.browserResultPath) !== 'browser-result.json') return null
    const ownedRootRealPath = realpathSyncImpl(ownedRoot)
    const resultRealPath = realpathSyncImpl(roots.browserResultPath)
    if (!samePathIdentity(resultRealPath, path.join(ownedRootRealPath, 'browser-result.json'))) return null
    const beforeOpen = lstatSyncImpl(roots.browserResultPath, { bigint: true })
    if (!safeResultStats(beforeOpen, { rejectLinks: true })) return null
    return { resultPath: roots.browserResultPath, ownedRootRealPath, beforeOpen }
  } catch {
    return null
  }
}

function isFormalSpecLocation(value, realpathSyncImpl) {
  try {
    if (typeof value !== 'string' || value.length === 0) return false
    const candidate = path.isAbsolute(value) ? value : path.resolve(repositoryRoot, value)
    return samePathIdentity(realpathSyncImpl(candidate), realpathSyncImpl(FORMAL_SPEC_PATH))
  } catch {
    return false
  }
}

export function readSafePlaywrightFailure(roots, expectedScenario, {
  lstatSyncImpl = lstatSync,
  realpathSyncImpl = realpathSync,
  openSyncImpl = openSync,
  fstatSyncImpl = fstatSync,
  readSyncImpl = readSync,
  closeSyncImpl = closeSync,
} = {}) {
  const scenario = knownScenario(expectedScenario)
  const fallback = safeBrowserTestDiagnostics({ scenario: scenario?.mode || 'complete' })
  let descriptor = null
  try {
    const ownedResult = ownedBrowserResultPath(roots, { lstatSyncImpl, realpathSyncImpl })
    if (!ownedResult) return fallback
    const noFollow = typeof fsConstants.O_NOFOLLOW === 'number' ? fsConstants.O_NOFOLLOW : 0
    descriptor = openSyncImpl(ownedResult.resultPath, fsConstants.O_RDONLY | noFollow)
    const before = fstatSyncImpl(descriptor, { bigint: true })
    if (!safeResultStats(before) || before.dev !== ownedResult.beforeOpen.dev || before.ino !== ownedResult.beforeOpen.ino) return fallback
    const buffer = Buffer.alloc(MAX_SAFE_PLAYWRIGHT_RESULT_BYTES + 1)
    let byteCount = 0
    while (byteCount <= MAX_SAFE_PLAYWRIGHT_RESULT_BYTES) {
      const remaining = (MAX_SAFE_PLAYWRIGHT_RESULT_BYTES + 1) - byteCount
      const bytesRead = readSyncImpl(descriptor, buffer, byteCount, remaining, null)
      if (!Number.isSafeInteger(bytesRead) || bytesRead < 0 || bytesRead > remaining) return fallback
      if (bytesRead === 0) break
      byteCount += bytesRead
    }
    if (byteCount > MAX_SAFE_PLAYWRIGHT_RESULT_BYTES) return fallback
    const after = fstatSyncImpl(descriptor, { bigint: true })
    if (!safeResultStats(after) || !sameFileStats(before, after)) return fallback
    const current = lstatSyncImpl(ownedResult.resultPath, { bigint: true })
    if (!safeResultStats(current, { rejectLinks: true }) || !sameFileStats(ownedResult.beforeOpen, current)) return fallback
    if (!samePathIdentity(realpathSyncImpl(ownedResult.resultPath), path.join(realpathSyncImpl(roots.ownedRoot), 'browser-result.json'))) return fallback
    const reportText = buffer.toString('utf8', 0, byteCount)
    const report = JSON.parse(reportText)
    if (!isRecord(report) || !Array.isArray(report.suites) || !scenario) return fallback
    const matchingSpecs = []
    const visitSuite = suite => {
      if (!isRecord(suite) || !Array.isArray(suite.specs)) throw new Error('invalid Playwright suite schema')
      for (const spec of suite.specs) {
        if (!isRecord(spec) || typeof spec.title !== 'string' || !Array.isArray(spec.tests)) throw new Error('invalid Playwright spec schema')
        if (spec.title === FORMAL_SCENARIO_TITLES[scenario.mode]) matchingSpecs.push(spec)
      }
      const nestedSuites = suite.suites === undefined ? [] : suite.suites
      if (!Array.isArray(nestedSuites)) throw new Error('invalid Playwright suite schema')
      for (const nestedSuite of nestedSuites) visitSuite(nestedSuite)
    }
    for (const suite of report.suites) visitSuite(suite)
    if (matchingSpecs.length !== 1) return fallback
    const counters = { passed: 0, failed: 0, skipped: 0, failureLine: 0, failureColumn: 0 }
    for (const test of matchingSpecs[0].tests) {
      if (!isRecord(test) || !Array.isArray(test.results)) throw new Error('invalid Playwright test schema')
      for (const result of test.results) {
        if (!isRecord(result) || !['passed', 'failed', 'skipped', 'timedOut', 'interrupted'].includes(result.status) || !Array.isArray(result.errors)) {
          throw new Error('invalid Playwright result schema')
        }
        if (result.status === 'passed') counters.passed += 1
        else if (result.status === 'skipped') counters.skipped += 1
        else {
          counters.failed += 1
          if (counters.failureLine === 0) {
            for (const error of result.errors) {
              const location = isRecord(error) && isRecord(error.location) ? error.location : null
              if (!Number.isSafeInteger(location?.line) || location.line < 1 || !isFormalSpecLocation(location.file, realpathSyncImpl)) continue
              counters.failureLine = location.line
              counters.failureColumn = Number.isSafeInteger(location.column) && location.column > 0 ? location.column : 0
              break
            }
          }
        }
      }
    }
    return safeBrowserTestDiagnostics({ scenario: scenario.mode, ...counters })
  } catch {
    return fallback
  } finally {
    if (descriptor !== null) {
      try { closeSyncImpl(descriptor) } catch {}
    }
  }
}

export function createSafeStageFailure(stage, cause) {
  const error = new Error('Phase4B2 stage failed', { cause })
  error.phase4B2Stage = SAFE_STAGE_SET.has(stage) ? stage : 'lifecycle'
  if (error.phase4B2Stage === 'outbound-audit') {
    error.outboundAuditCounters = safeOutboundAuditCounters(cause?.outboundAuditCounters)
  }
  if (error.phase4B2Stage === 'browser-test' && cause?.browserTestDiagnostics !== undefined) {
    error.browserTestDiagnostics = safeBrowserTestDiagnostics(cause.browserTestDiagnostics)
  }
  return error
}

export function createBrowserTestStageFailure(roots, expectedScenario, cause) {
  const error = createSafeStageFailure('browser-test', cause)
  error.browserTestDiagnostics = readSafePlaywrightFailure(roots, expectedScenario)
  return error
}

export async function runSafeStage(stage, operation) {
  try { return await operation() } catch (error) { throw createSafeStageFailure(stage, error) }
}

export function formatSafeStageSummary(error) {
  const counts = new Map()
  const outboundAuditCounters = { allowed: 0, forbidden: 0, malformed: 0, total: 0 }
  let browserTestDiagnostics = null
  const record = (stage, metadata) => {
    counts.set(stage, (counts.get(stage) || 0) + 1)
    if (stage === 'outbound-audit') {
      const counters = safeOutboundAuditCounters(metadata)
      for (const key of OUTBOUND_AUDIT_COUNTER_KEYS) outboundAuditCounters[key] += counters[key]
    }
    if (stage === 'browser-test' && metadata !== undefined) browserTestDiagnostics = safeBrowserTestDiagnostics(metadata)
  }
  const visitedObjects = new WeakSet()
  const visitedPrimitives = new Set()
  const visit = value => {
    const isObject = (typeof value === 'object' && value !== null) || typeof value === 'function'
    if (!isObject) {
      if (visitedPrimitives.has(value)) return
      visitedPrimitives.add(value)
      record('lifecycle')
      return
    }
    if (visitedObjects.has(value)) return
    visitedObjects.add(value)
    if (SAFE_STAGE_SET.has(value.phase4B2Stage)) {
      record(value.phase4B2Stage, value.phase4B2Stage === 'outbound-audit'
        ? value.outboundAuditCounters
        : value.browserTestDiagnostics)
      return
    }
    let hasDescendant = false
    if (value instanceof AggregateError) {
      for (const nested of value.errors) {
        hasDescendant = true
        visit(nested)
      }
    }
    if (value.cause !== undefined) {
      hasDescendant = true
      visit(value.cause)
    }
    if (!hasDescendant) record('lifecycle')
  }
  visit(error)
  if (counts.size === 0) record('lifecycle')
  return JSON.stringify({
    stages: SAFE_STAGE_ALLOWLIST
      .filter(stage => counts.has(stage))
      .map(stage => stage === 'outbound-audit'
        ? { stage, count: counts.get(stage), ...outboundAuditCounters }
        : stage === 'browser-test' && browserTestDiagnostics
          ? { stage, count: counts.get(stage), ...browserTestDiagnostics }
          : { stage, count: counts.get(stage) }),
  })
}

export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList) || argumentsList.length !== 0) throw new Error('Phase4B2 browser runner does not accept spec paths')
  return [...FORMAL_SPECS]
}

function selectedScenarios(value) {
  if (!value) return [...FORMAL_SCENARIOS]
  const match = FORMAL_SCENARIOS.find(item => item.tag === value)
  if (!match) throw new Error('PHASE4B2_GREP must select one exact formal scenario')
  return [match]
}

function ownedViteTempCacheEntries(ownedRoot) {
  const directory = path.join(ownedRoot, 'vite-cache')
  return existsSync(directory)
    ? readdirSync(directory, { withFileTypes: true })
      .filter(entry => entry.isDirectory() && entry.name.startsWith('deps_temp_'))
      .map(entry => entry.name)
    : []
}

function artifactFiles(root) {
  if (!existsSync(root)) return []
  const files = []
  const visit = directory => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name)
      if (entry.isDirectory()) visit(target)
      else if (entry.isFile()) files.push(target)
      else throw new Error('Phase4B2 artifact root contains a non-regular entry')
    }
  }
  visit(root)
  return files
}

export function assertArtifactEvidenceSafe(root, sensitiveValues, extraFiles = []) {
  for (const target of [...artifactFiles(root), ...extraFiles]) {
    const text = readFileSync(target, 'utf8')
    assertNoPrivateEvidenceMarkers([text])
    if ([...sensitiveValues, ...GENERATED_TEXT_MARKERS].some(value => value && text.includes(value))) {
      throw new Error('Phase4B2 artifact contains sensitive evidence')
    }
  }
}

async function waitForPortRelease(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer().once('error', reject)
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => probe.close(error => error ? reject(error) : resolve()))
  })
}

export function assertProviderLedger(value, scenario) {
  const entries = String(value).split(/\r?\n/u).filter(Boolean)
  const terminal = scenario.mode === 'complete' ? 'completed' : 'transport-closed'
  const expected = [
    `scenario=${scenario.mode}`,
    'method=POST path=/v1/chat/completions status=200',
    'connection=1',
    'call=1',
    `terminal=${terminal}`,
  ]
  if (JSON.stringify(entries) !== JSON.stringify(expected)) {
    throw new Error('fake streaming provider ledger did not match its closed contract')
  }
}

export function assertBackendOutboundLedger(value) {
  const normalized = String(value).replaceAll('\r\n', '\n')
  const lines = normalized === '' ? [''] : normalized.split('\n')
  if (normalized.endsWith('\n')) lines.pop()
  const counters = { allowed: 0, forbidden: 0, malformed: 0, total: 0 }
  for (const line of lines) {
    counters.total += 1
    if (line === 'allowed-local-provider') counters.allowed += 1
    else if (line === 'forbidden-outbound') counters.forbidden += 1
    else counters.malformed += 1
  }
  const safeCounters = safeOutboundAuditCounters(counters)
  if (safeCounters.allowed === 1 && safeCounters.forbidden === 0 && safeCounters.malformed === 0 && safeCounters.total === 1) return
  const error = new Error('backend outbound ledger did not match the loopback-only contract')
  error.outboundAuditCounters = safeCounters
  throw error
}

export async function cleanupOwnedRoot({
  root,
  roots,
  ports,
  sensitiveValues,
  waitForPortReleaseImpl = waitForPortRelease,
  ownedViteTempCacheEntriesImpl = ownedViteTempCacheEntries,
  assertArtifactEvidenceSafeImpl = assertArtifactEvidenceSafe,
  removeOwnedRootImpl = removeOwnedRoot,
}) {
  const errors = []
  for (const port of ports) {
    try { await waitForPortReleaseImpl(port) } catch (error) { errors.push(error) }
  }
  try {
    if (ownedViteTempCacheEntriesImpl(root).length !== 0) {
      throw new Error('owned Vite deps_temp residue was not zero')
    }
  } catch (error) { errors.push(error) }
  try {
    if (roots) {
      assertArtifactEvidenceSafeImpl(roots.artifactRoot, sensitiveValues, [
        roots.providerLedgerPath,
        roots.outboundLedgerPath,
        roots.denyProxyLedgerPath,
        roots.browserResultPath,
      ].filter(target => typeof target === 'string' && existsSync(target)))
    }
  } catch (error) { errors.push(error) }
  try {
    removeOwnedRootImpl(root, OWNED_ROOT_PREFIX)
    if (existsSync(root)) throw new Error('owned temporary root remained')
  } catch (error) {
    errors.push(error)
  }
  if (errors.length > 0) throw new AggregateError(errors, 'Phase4B2 root cleanup failed')
  return true
}

export async function reserveOwnedPorts({
  count,
  portReservationFactory = reserveLocalPort,
  registerReservation,
}) {
  if (!Number.isInteger(count) || count < 1 || typeof registerReservation !== 'function') {
    throw new Error('Phase4B2 port reservation contract is invalid')
  }
  const reservations = []
  for (let index = 0; index < count; index += 1) {
    const reservation = await portReservationFactory()
    registerReservation(reservation)
    reservations.push(reservation)
  }
  return reservations
}

export function formatScenarioPassedSummary(mode) {
  return `Phase4B2 ${mode}: scenario passed; DB/process/port/temp/artifact/Vite residue=0; real provider calls = 0; product DB reads/writes = 0/0`
}

export function formatBrowserPassedSummary(passed, selected) {
  if (!Number.isSafeInteger(passed) || !Number.isSafeInteger(selected) || passed < 0 || selected < 1 || passed > selected) {
    throw new Error('Phase4B2 scenario summary counters are invalid')
  }
  return `Phase4B2 browser: ${passed}/${selected} scenarios passed`
}

export async function runOneScenario({ spec, scenario, environment, databaseNameFactory = createDatabaseName, ownedRootFactory = createOwnedRoot, portReservationFactory = reserveLocalPort, deadlines = DEFAULT_DEADLINES, log = console.log }) {
  const databaseName = databaseNameFactory(); assertDatabaseName(databaseName)
  const cleanupEnvironment = cleanEnvironment(environment, databaseName)
  let roots = null; let root = null; const ports = []; let databaseCreated = 0; let databaseCleaned = 0; let providerLedgerVerified = false
  await runOwnedProductLifecycle({
      async body(lifecycle) {
        root = lifecycle.setRoot(ownedRootFactory(OWNED_ROOT_PREFIX)); roots = sourceRoot(root); lifecycle.setDatabase(databaseName)
        const reservations = await reserveOwnedPorts({ count: 4, portReservationFactory, registerReservation: lifecycle.registerReservation })
        ports.push(...reservations.map(item => item.port)); if (new Set(ports).size !== 4) throw new Error('Phase4B2 runner received duplicate owned ports')
        const [providerPort, backendPort, denyPort, vitePort] = ports
        const providerUrl = `http://127.0.0.1:${providerPort}/v1`; const backendUrl = `http://127.0.0.1:${backendPort}`; const denyUrl = `http://127.0.0.1:${denyPort}`; const viteUrl = `http://127.0.0.1:${vitePort}`; const nonce = randomUUID()
        const base = Object.fromEntries(BASE_ENV_ALLOWLIST.filter(key => Object.hasOwn(environment, key)).map(key => [key, environment[key]]))
        const backendEnvironment = { ...base, MYSQL_HOST: environment.TEST_MYSQL_HOST, MYSQL_PORT: environment.TEST_MYSQL_PORT, MYSQL_USER: environment.TEST_MYSQL_USER, MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD, MYSQL_DB: databaseName, BROWSER_TEST_DATABASE: databaseName, BROWSER_PROJECT_ID: PROJECT_ID, BROWSER_PROVIDER_BASE_URL: providerUrl, BROWSER_SECRET_SENTINEL: SECRET_SENTINEL, BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath, BROWSER_SCENARIO_MODE: scenario.mode, M2_BROWSER_RUN_NONCE: nonce, MARKET_SCHEDULER_ENABLED: 'false', SCHEDULER_ENABLED: '0' }
        const providerEnvironment = { ...base, BROWSER_PROVIDER_LEDGER_PATH: roots.providerLedgerPath, BROWSER_SCENARIO_MODE: scenario.mode, BROWSER_SECRET_SENTINEL: SECRET_SENTINEL, M2_BROWSER_RUN_NONCE: nonce }
        const browserEnvironment = { ...base, PLAYWRIGHT_BASE_URL: viteUrl, BROWSER_OWNED_ROOT: root, BROWSER_ARTIFACT_ROOT: roots.artifactRoot, BROWSER_RESULT_PATH: roots.browserResultPath, BROWSER_PROVIDER_LEDGER_PATH: roots.providerLedgerPath, BROWSER_PROJECT_ID: PROJECT_ID, BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, backendUrl]), BROWSER_DENY_PROXY_URL: denyUrl, MYSQL_HOST: environment.TEST_MYSQL_HOST, MYSQL_PORT: environment.TEST_MYSQL_PORT, MYSQL_USER: environment.TEST_MYSQL_USER, MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD, MYSQL_DB: databaseName, BROWSER_TEST_DATABASE: databaseName, BROWSER_SECRET_SENTINEL: SECRET_SENTINEL }
        const sensitiveValues = runtimeSensitiveValues(browserEnvironment)
        const python = environment.PYTHON || 'python'; const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js'); const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
        await runSafeStage('database-preparation', async () => { await runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', databaseName], childOptions(repositoryRoot, cleanupEnvironment), { label: 'database preparation', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs }); databaseCreated = 1 })
        await runSafeStage('canonical-fixture', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_phase4b2_browser_db', '--database', databaseName], childOptions(repositoryRoot, backendEnvironment), { label: 'Phase4B2 canonical fixture', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs }))
        const servers = []
        async function start(stage, reservation, command, args, options, label, health) { return runSafeStage(stage, async () => { await lifecycle.releaseReservation(reservation); const server = lifecycle.registerServer(startOwnedServer(command, args, options, { label, sensitiveValues })); servers.push(server); await waitForOwnedServer(server, health, { expectedNonce: nonce, timeoutMs: deadlines.healthMs }); return server }) }
        await start('fake-provider-start', reservations[0], process.execPath, [roots.providerPath, String(providerPort)], childOptions(repositoryRoot, providerEnvironment), 'fake streaming provider', `http://127.0.0.1:${providerPort}/health`)
        await start('backend-start', reservations[1], python, ['-c', `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name='__main__')`, String(backendPort)], childOptions(repositoryRoot, backendEnvironment), 'backend', `${backendUrl}/api/health`)
        await start('deny-proxy-start', reservations[2], process.execPath, [roots.denyProxyPath, String(denyPort)], childOptions(repositoryRoot, { ...base, M2_BROWSER_RUN_NONCE: nonce, BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath }), 'fake outbound deny proxy', `${denyUrl}/health`)
        await start('vite-start', reservations[3], process.execPath, [viteCli, '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], childOptions(frontendRoot, { ...base, NODE_ENV: 'test', VITE_API_BASE_URL: `${backendUrl}/api`, M2_BROWSER_RUN_NONCE: nonce }), 'vite', `${viteUrl}/__m2-browser-owner`)
        try {
          await runBoundedOwnedCommand(process.execPath, [playwrightCli, 'test', `e2e/${spec}`, '--config', `e2e/${FORMAL_CONFIG}`, '--grep', scenario.tag], childOptions(frontendRoot, browserEnvironment), { label: 'Phase4B2 browser test', sensitiveValues, timeoutMs: deadlines.browserMs, stopTimeoutMs: deadlines.stopMs, states: servers })
        } catch (error) {
          throw createBrowserTestStageFailure(roots, scenario, error)
        }
        await runSafeStage('outbound-audit', () => assertBackendOutboundLedger(readFileSync(roots.outboundLedgerPath, 'utf8')))
        await runSafeStage('deny-proxy-audit', () => assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8')))
        await runSafeStage('postcondition-verifier', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_phase4b2_browser_db', '--database', databaseName, '--verify-postconditions', scenario.mode], childOptions(repositoryRoot, backendEnvironment), { label: 'Phase4B2 verify-postconditions', sensitiveValues, timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs, states: servers }))
      },
      async stopServer(server) {
        await stopOwnedServer(server, { timeoutMs: deadlines.stopMs })
        if (server?.label === 'fake streaming provider') await runSafeStage('provider-ledger-audit', () => { assertProviderLedger(readFileSync(roots.providerLedgerPath, 'utf8'), scenario); providerLedgerVerified = true })
      },
      releaseReservation: reservation => reservation.release(),
      async dropDatabase(name) { await runSafeStage('database-cleanup', async () => { await runBoundedOwnedCommand(environment.PYTHON || 'python', ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', name, '--drop'], childOptions(repositoryRoot, cleanupEnvironment), { label: 'database cleanup', timeoutMs: deadlines.commandMs, stopTimeoutMs: deadlines.stopMs }); databaseCleaned = 1 }) },
      async removeRoot(target) { await runSafeStage('root-cleanup', () => cleanupOwnedRoot({ root: target, roots, ports, sensitiveValues: runtimeSensitiveValues({ ...environment, MYSQL_DB: databaseName, BROWSER_SECRET_SENTINEL: SECRET_SENTINEL }) })) },
    })
  if (!providerLedgerVerified) throw createSafeStageFailure('provider-ledger-audit', new Error('Phase4B2 provider ledger audit was not reached'))
  await runSafeStage('database-cleanup', () => assertDatabaseResidue(databaseName, databaseName, { created: databaseCreated, cleaned: databaseCleaned, remaining: 0 }))
  log(formatScenarioPassedSummary(scenario.mode))
}

export async function runPhase4B2({ specs = FORMAL_SPECS, environment = process.env, deadlines = {}, runOneScenarioImpl = runOneScenario, log = console.log } = {}) {
  validateTestEnvironment(environment)
  if (JSON.stringify(specs) !== JSON.stringify(FORMAL_SPECS)) throw new Error('Phase4B2 requires its one exact formal browser spec')
  const normalized = { ...DEFAULT_DEADLINES, ...deadlines }
  const scenarios = selectedScenarios(environment.PHASE4B2_GREP)
  let passed = 0
  for (const scenario of scenarios) {
    await runOneScenarioImpl({ spec: FORMAL_SPECS[0], scenario, environment, deadlines: normalized, log })
    passed += 1
  }
  log(formatBrowserPassedSummary(passed, scenarios.length))
  return 0
}

export function samePathIdentity(left, right, { platform = process.platform } = {}) {
  const normalize = value => {
    if (typeof value !== 'string' || value.length === 0) return null
    const resolved = path.resolve(value)
    return platform === 'win32' ? resolved.toLowerCase() : resolved
  }
  const normalizedLeft = normalize(left)
  return normalizedLeft !== null && normalizedLeft === normalize(right)
}

export function isCommandLineEntrypoint(argumentPath, modulePath) { try { return Boolean(argumentPath) && samePathIdentity(realpathSync(argumentPath), realpathSync(fileURLToPath(modulePath))) } catch { return false } }
export function safeCliFailureSummary(error = new Error('Phase4B2 lifecycle failed')) { return formatSafeStageSummary(error) }
if (isCommandLineEntrypoint(process.argv[1], import.meta.url)) {
  runPhase4B2().then(status => { process.exitCode = status }).catch(error => {
    console.error(safeCliFailureSummary(error))
    process.exitCode = 1
  })
}

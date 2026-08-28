import { randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, writeFileSync } from 'node:fs'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import {
  BASE_ENV_ALLOWLIST, assertDatabaseName, assertOwnedRoot, createDatabaseName,
  createOwnedRoot, removeOwnedRoot, reserveLocalPort, runBoundedOwnedCommand,
  runOwnedProductLifecycle, startOwnedServer, stopOwnedServer,
  validateTestEnvironment, waitForOwnedServer,
} from './support/product-runner.mjs'
import { DENY_PROXY_SOURCE, assertDenyProxyLedger } from './support/deny-proxy.mjs'
import { assertDatabaseResidue } from './support/database-residue.mjs'

export const FORMAL_SPECS = Object.freeze(['phase8a/manuscript-productization.spec.mjs'])
export const FORMAL_CONFIG = 'playwright.phase8a.config.mjs'
const ROOT_PREFIX = 'novel-creator-phase8a-'
const DEFAULT_DEADLINES = Object.freeze({ commandMs: 120_000, healthMs: 45_000, browserMs: 300_000, stopMs: 8_000 })
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.resolve(frontend, '..')
const options = (cwd, env) => ({ cwd, env, stdio: ['ignore', 'pipe', 'pipe'] })
const allowed = environment => Object.fromEntries(BASE_ENV_ALLOWLIST.filter(key => Object.hasOwn(environment, key)).map(key => [key, environment[key]]))

const BACKEND_SOURCE = String.raw`
import os, sys
import httpx, uvicorn
ledger = os.environ['BROWSER_OUTBOUND_LEDGER_PATH']
RealAsyncClient = httpx.AsyncClient
class DeniedAsyncClient:
    def __init__(self, *args, **kwargs):
        self.inner = RealAsyncClient(*args, **kwargs)
    async def __aenter__(self): await self.inner.__aenter__(); return self
    async def __aexit__(self, *args): return await self.inner.__aexit__(*args)
    async def aclose(self): return await self.inner.aclose()
    def build_request(self, *args, **kwargs): return self.inner.build_request(*args, **kwargs)
    def deny(self):
        with open(ledger, 'a', encoding='utf-8') as output: output.write('forbidden-outbound\n')
        raise RuntimeError('Phase8A outbound Provider access is forbidden')
    async def request(self, *args, **kwargs): self.deny()
    async def send(self, *args, **kwargs): self.deny()
    def stream(self, *args, **kwargs): self.deny()
    async def post(self, *args, **kwargs): self.deny()
httpx.AsyncClient = DeniedAsyncClient
from backend.main import app
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
`

function createRoots(owned) {
  const roots = {
    artifactRoot: path.join(owned, 'artifacts'),
    downloadRoot: path.join(owned, 'downloads'),
    browserDownloadsRoot: path.join(owned, 'browser-downloads'),
    backendPath: path.join(owned, 'backend.py'),
    denyProxyPath: path.join(owned, 'deny-proxy.cjs'),
    viteConfigPath: path.join(owned, 'vite.config.mjs'),
    resultPath: path.join(owned, 'browser-result.json'),
    pageEventLedgerPath: path.join(owned, 'page-events.json'),
    outboundLedgerPath: path.join(owned, 'outbound-ledger.log'),
    denyProxyLedgerPath: path.join(owned, 'deny-proxy.log'),
  }
  mkdirSync(roots.artifactRoot)
  mkdirSync(roots.downloadRoot)
  mkdirSync(roots.browserDownloadsRoot)
  for (const [target, contents] of [
    [roots.backendPath, BACKEND_SOURCE], [roots.denyProxyPath, DENY_PROXY_SOURCE],
    [roots.outboundLedgerPath, ''], [roots.denyProxyLedgerPath, ''],
  ]) writeFileSync(target, contents, { encoding: 'utf8', flag: 'wx' })
  writeFileSync(roots.viteConfigPath, `import base from ${JSON.stringify(pathToFileURL(path.join(frontend, 'vite.config.js')).href)}\nexport default { ...base, cacheDir: ${JSON.stringify(path.join(owned, 'vite-cache'))} }\n`, { encoding: 'utf8', flag: 'wx' })
  return roots
}

function denyProxyCounts(value) {
  const entries = String(value).split(/\r?\n/u).filter(Boolean)
  return {
    http: entries.filter(entry => entry === 'http-denied').length,
    connect: entries.filter(entry => entry === 'connect-denied').length,
    invalid: entries.filter(entry => !['http-denied', 'connect-denied'].includes(entry)).length,
  }
}

function assertBrowserDenyLedger(value) {
  const counts = denyProxyCounts(value)
  try {
    if (counts.http !== 0 || counts.invalid !== 0) throw new Error('unexpected deny ledger entry')
    return assertDenyProxyLedger(value, { expectedConnectCount: counts.connect })
  } catch {
    throw new Error(`Phase8A denied browser background http=${counts.http} connect=${counts.connect} invalid=${counts.invalid}`)
  }
}

async function waitForPortRelease(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer()
    const timer = setTimeout(() => { probe.close(); reject(new Error('Phase8A owned port remained bound')) }, 10_000)
    probe.once('error', error => { clearTimeout(timer); reject(error) })
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => probe.close(error => {
      clearTimeout(timer)
      if (error) reject(error); else resolve()
    }))
  })
}

export async function cleanupRoot(owned, roots, ports, {
  waitForPortReleaseImpl = waitForPortRelease,
  removeOwnedRootImpl = removeOwnedRoot,
} = {}) {
  const failures = []
  for (const port of ports) {
    try { await waitForPortReleaseImpl(port) } catch (error) { failures.push(error) }
  }
  try {
    const cache = path.join(owned, 'vite-cache')
    const viteTemps = existsSync(cache)
      ? readdirSync(cache, { withFileTypes: true }).filter(entry => entry.isDirectory() && entry.name.startsWith('deps_temp_'))
      : []
    if (viteTemps.length) throw new Error('Phase8A Vite temp residue was not zero')
    if (readFileSync(roots.outboundLedgerPath, 'utf8').trim()) throw new Error('Phase8A Provider or outbound request was attempted')
    assertBrowserDenyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8'))
  } catch (error) {
    failures.push(error)
  }
  try {
    removeOwnedRootImpl(assertOwnedRoot(owned, ROOT_PREFIX), ROOT_PREFIX)
    if (existsSync(owned)) throw new Error('Phase8A owned root remained')
  } catch (error) {
    failures.push(error)
  }
  if (failures.length === 1) throw failures[0]
  if (failures.length > 1) throw new AggregateError(failures, 'Phase8A cleanup failed')
}

function reportErrors(value, found = []) {
  if (Array.isArray(value)) { for (const item of value) reportErrors(item, found); return found }
  if (!value || typeof value !== 'object') return found
  if (Array.isArray(value.errors)) {
    for (const error of value.errors) if (error && typeof error.message === 'string') found.push(error)
  }
  if (value.error && typeof value.error.message === 'string') found.push(value.error)
  for (const key of ['suites', 'specs', 'tests', 'results']) if (value[key]) reportErrors(value[key], found)
  return found
}

const PAGE_EVENT_MARKER = /^phase8a-page-events-(?<checkpoint>workflow|complete-reader|complete-downloads|complete-archive)-console-(?<consoleCount>[0-9]{1,2})-page-(?<pageCount>[0-9]{1,2})-request-(?<requestCount>[0-9]{1,2})-first-(?<consoleSource>none|novel-download-(?:chapter|volume|book|unknown)|manuscript-(?:chapter|index)|lifecycle|other-api|frontend-asset|other)-(?<consoleCategory>resource-status|other)-(?<consoleStatus>[0-9]{1,3})-response-(?<responseStage>none|setup|complete|awaiting|corrupt|unknown)-(?<responseMethod>get|post|put|patch|delete|head|options|other)-(?<responseRoute>other|not-owned|manuscript-(?:chapter|index)|novel-download-(?:chapter|volume|book|unknown)|other-api|other-owned)-(?<responseStatus>[0-9]{1,3})-failed-(?<failureStage>none|setup|complete|awaiting|corrupt|unknown)-(?<failureMethod>get|post|put|patch|delete|head|options|other)-(?<failureRoute>not-owned|manuscript-(?:chapter|index)|novel-download|other-api|frontend-asset|frontend-route)-(?<failureType>aborted|connection|timeout|blocked|other)$/u

function validatedEvidenceMarker(message) {
  if (typeof message !== 'string' || message.length > 512) return null
  const motion = message.match(/^phase8a-motion-transition-(?<duration>[0-9]{1,9})$/u)
  if (motion) {
    const duration = Number(motion.groups.duration)
    const serialized = `phase8a-motion-transition-${duration}`
    return duration <= 300_000_000 && serialized === message ? serialized : null
  }
  const match = message.match(PAGE_EVENT_MARKER)
  if (!match) return null
  const groups = match.groups
  const consoleCount = Number(groups.consoleCount)
  const pageCount = Number(groups.pageCount)
  const requestCount = Number(groups.requestCount)
  const consoleStatus = Number(groups.consoleStatus)
  const responseStatus = Number(groups.responseStatus)
  if (
    (consoleStatus !== 0 && (consoleStatus < 100 || consoleStatus > 599))
    || (responseStatus !== 0 && (responseStatus < 400 || responseStatus > 599))
    || (consoleCount === 0 && `${groups.consoleSource}-${groups.consoleCategory}-${consoleStatus}` !== 'none-other-0')
    || (consoleCount > 0 && groups.consoleSource === 'none')
    || (groups.responseStage === 'none'
      && `${groups.responseMethod}-${groups.responseRoute}-${responseStatus}` !== 'get-other-0')
    || (groups.responseStage !== 'none' && responseStatus === 0)
    || (requestCount === 0
      && `${groups.failureStage}-${groups.failureMethod}-${groups.failureRoute}-${groups.failureType}` !== 'none-get-not-owned-other')
    || (requestCount > 0 && groups.failureStage === 'none')
  ) return null
  const serialized = `phase8a-page-events-${groups.checkpoint}-console-${consoleCount}-page-${pageCount}-request-${requestCount}-first-${groups.consoleSource}-${groups.consoleCategory}-${consoleStatus}-response-${groups.responseStage}-${groups.responseMethod}-${groups.responseRoute}-${responseStatus}-failed-${groups.failureStage}-${groups.failureMethod}-${groups.failureRoute}-${groups.failureType}`
  return serialized === message ? serialized : null
}

export function classifyBoundedCause(error) {
  const categories = []
  const visit = value => {
    if (!value || typeof value !== 'object') return
    const message = typeof value.message === 'string' ? value.message : ''
    if (value.name === 'AbortError' || /interrupted by SIG|\babort(?:ed)?\b/iu.test(message)) categories.push('abort')
    if (/deadline exceeded/iu.test(message)) categories.push('deadline')
    if (/log scan|runtime-sensitive/iu.test(message)) categories.push('log-scan')
    if (/process failed to start/iu.test(message)) categories.push('start')
    if (/process exited with status/iu.test(message)) categories.push('exit-status')
    if (/\bservice\b.*exited before requested stop/iu.test(message)) categories.push('service')
    if (value.cause) visit(value.cause)
    if (value instanceof AggregateError) value.errors.forEach(visit)
  }
  visit(error)
  for (const category of ['abort', 'deadline', 'service', 'log-scan', 'start', 'exit-status']) {
    if (categories.includes(category)) return category
  }
  return 'other'
}

export function classifyBrowserFailure(resultPath, boundedError) {
  const boundedCause = classifyBoundedCause(boundedError)
  if (!existsSync(resultPath)) return `report-missing-bounded-${boundedCause}`
  let report
  try { report = JSON.parse(readFileSync(resultPath, 'utf8')) } catch {
    return `report-invalid-json-bounded-${boundedCause}`
  }
  const errors = reportErrors(report)
  const error = errors.find(item => (
    item.location?.file?.endsWith('manuscript-productization.spec.mjs')
    && Number.isInteger(item.location.line)
  )) || errors[0]
  if (!error) return `report-no-errors-bounded-${boundedCause}`
  const stackLine = typeof error.stack === 'string'
    ? error.stack.match(/manuscript-productization\.spec\.mjs:(\d+):\d+/u)?.[1]
    : null
  const locationLine = error.location?.file?.endsWith('manuscript-productization.spec.mjs')
    && Number.isInteger(error.location.line) ? error.location.line : null
  const line = locationLine || stackLine || 'unknown'
  const evidenceMarker = validatedEvidenceMarker(error.message)
  if (evidenceMarker) return `${evidenceMarker}@${line}`
  if (/timed out|timeout/iu.test(error.message)) return `timeout@${line}`
  if (/locator|strict mode/iu.test(error.message)) return `locator@${line}`
  if (locationLine || stackLine) return `assertion@${line}`
  return `report-unmapped-error-bounded-${boundedCause}`
}

export function assertPageEventLedger(value) {
  let parsed
  try { parsed = JSON.parse(value) } catch { throw new Error('Phase8A page event ledger was invalid') }
  const keys = parsed && typeof parsed === 'object' && !Array.isArray(parsed)
    ? Object.keys(parsed).sort() : []
  const expectedKeys = ['consoleErrors', 'pageErrors', 'requestFailures', 'responses', 'summaries']
  const routes = ['manuscript-chapter', 'novel-download-chapter', 'novel-download-volume', 'novel-download-book']
  const expectedResponses = routes.map(route => ({ method: 'GET', route, stage: 'corrupt', status: 500 }))
  const expectedSummaries = routes.map(source => ({
    kind: 'console-error', category: 'resource-status', source, status: 500,
  }))
  if (
    JSON.stringify(keys) !== JSON.stringify(expectedKeys.sort())
    || parsed.consoleErrors !== 4 || parsed.pageErrors !== 0 || parsed.requestFailures !== 0
    || JSON.stringify(parsed.responses) !== JSON.stringify(expectedResponses)
    || JSON.stringify(parsed.summaries) !== JSON.stringify(expectedSummaries)
  ) throw new Error('Phase8A page event ledger was invalid')
  return { consoleKnownLinked: 4, consoleUnexpected: 0, pageErrors: 0, requestFailures: 0 }
}

export function safeFailureSummary(error) {
  let browserCause = null
  const visit = value => {
    if (!value || typeof value !== 'object') return
    if (typeof value.phase8aBrowserCause === 'string') browserCause ||= value.phase8aBrowserCause
    if (value.cause) visit(value.cause)
    if (value instanceof AggregateError) value.errors.forEach(visit)
  }
  visit(error)
  return `Phase8A browser lifecycle failed; browserCause=${browserCause || 'lifecycle'}; cleanup was attempted`
}

export async function runPhase8A({
  environment = process.env,
  log = console.log,
  deadlines = {},
  dependencies = {},
  processTarget = process,
} = {}) {
  const deps = {
    validateTestEnvironment, createDatabaseName, assertDatabaseName, createOwnedRoot, createRoots,
    reserveLocalPort, runBoundedOwnedCommand, runOwnedProductLifecycle, startOwnedServer,
    waitForOwnedServer, stopOwnedServer, cleanupRoot, assertDatabaseResidue,
    readOwnedText: target => readFileSync(target, 'utf8'),
    ...dependencies,
  }
  deps.validateTestEnvironment(environment)
  const limits = { ...DEFAULT_DEADLINES, ...deadlines }
  const database = deps.createDatabaseName()
  deps.assertDatabaseName(database)
  const base = allowed(environment)
  const ports = []
  let roots
  let created = 0
  let cleaned = 0
  let deniedConnects = 0
  const controller = new AbortController()
  const signalHandler = signal => controller.abort(new Error(`Phase8A interrupted by ${signal}`))
  const onSigint = () => signalHandler('SIGINT')
  const onSigterm = () => signalHandler('SIGTERM')
  processTarget.once('SIGINT', onSigint)
  processTarget.once('SIGTERM', onSigterm)
  const mysql = {
    ...base,
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST, TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER, TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_HOST: environment.TEST_MYSQL_HOST, MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER, MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: database, BROWSER_TEST_DATABASE: database,
  }
  const bodyCommand = (command, args, cwd, env, label, states = []) => deps.runBoundedOwnedCommand(
    command, args, options(cwd, env),
    { label, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs, states, signal: controller.signal },
  )
  const cleanupCommand = (command, args, cwd, env, label) => deps.runBoundedOwnedCommand(
    command, args, options(cwd, env),
    { label, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs },
  )
  try {
    await deps.runOwnedProductLifecycle({
      async body(lifecycle) {
        const owned = lifecycle.setRoot(deps.createOwnedRoot(ROOT_PREFIX))
        roots = deps.createRoots(owned)
        lifecycle.setDatabase(database)
        const reservations = []
        for (let index = 0; index < 3; index += 1) {
          const reservation = lifecycle.registerReservation(await deps.reserveLocalPort())
          reservations.push(reservation)
          ports.push(reservation.port)
        }
        if (new Set(ports).size !== 3) throw new Error('Phase8A API, deny proxy, and Vite ports are not unique')
        const [apiPort, denyPort, vitePort] = ports
        const apiUrl = `http://127.0.0.1:${apiPort}`
        const denyUrl = `http://127.0.0.1:${denyPort}`
        const viteUrl = `http://127.0.0.1:${vitePort}`
        const nonce = randomUUID()
        const python = environment.PYTHON || 'python'
        const backendEnvironment = {
          ...mysql, BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath,
          M2_BROWSER_RUN_NONCE: nonce, SCHEDULER_ENABLED: '0', MARKET_SCHEDULER_ENABLED: 'false',
        }
        const browserEnvironment = {
          ...mysql, PLAYWRIGHT_BASE_URL: viteUrl,
          BROWSER_OWNED_ROOT: owned, BROWSER_ARTIFACT_ROOT: roots.artifactRoot,
          BROWSER_DOWNLOAD_ROOT: roots.downloadRoot,
          BROWSER_BROWSER_DOWNLOADS_ROOT: roots.browserDownloadsRoot,
          BROWSER_RESULT_PATH: roots.resultPath,
          BROWSER_PAGE_EVENT_LEDGER_PATH: roots.pageEventLedgerPath,
          BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, apiUrl]),
          BROWSER_DENY_PROXY_URL: denyUrl,
          BROWSER_COMPLETE_PROJECT_ID: '8a000000-0000-4000-8000-000000000001',
          BROWSER_AWAITING_PROJECT_ID: '8a000000-0000-4000-8000-000000000002',
          BROWSER_CORRUPT_PROJECT_ID: '8a000000-0000-4000-8000-000000000003',
        }
        await bodyCommand(python, ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', database], root, mysql, 'Phase8A database preparation')
        created = 1
        await bodyCommand(python, ['-m', 'backend.scripts.prepare_phase8a_browser_db', '--database', database], root, backendEnvironment, 'Phase8A fixture preparation')
        await bodyCommand(python, ['-m', 'backend.scripts.prepare_phase8a_browser_db', '--database', database], root, backendEnvironment, 'Phase8A fixture preparation')
        await lifecycle.releaseReservation(reservations[0])
        const backend = lifecycle.registerServer(deps.startOwnedServer(python, ['-c', `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name='__main__')`, String(apiPort)], options(root, backendEnvironment), { label: 'Phase8A API' }))
        await deps.waitForOwnedServer(backend, `${apiUrl}/api/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs, signal: controller.signal })
        await lifecycle.releaseReservation(reservations[1])
        const deny = lifecycle.registerServer(deps.startOwnedServer(process.execPath, [roots.denyProxyPath, String(denyPort)], options(root, { ...base, BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath, M2_BROWSER_RUN_NONCE: nonce }), { label: 'Phase8A deny proxy' }))
        await deps.waitForOwnedServer(deny, `${denyUrl}/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs, signal: controller.signal })
        await lifecycle.releaseReservation(reservations[2])
        const vite = lifecycle.registerServer(deps.startOwnedServer(process.execPath, [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], options(frontend, { ...base, VITE_API_BASE_URL: `${apiUrl}/api`, M2_BROWSER_RUN_NONCE: nonce }), { label: 'Phase8A Vite' }))
        await deps.waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, { expectedNonce: nonce, timeoutMs: limits.healthMs, signal: controller.signal })
        try {
          await deps.runBoundedOwnedCommand(process.execPath, [path.join(frontend, 'node_modules', 'playwright', 'cli.js'), 'test', `e2e/${FORMAL_SPECS[0]}`, '--config', `e2e/${FORMAL_CONFIG}`], options(frontend, browserEnvironment), { label: 'Phase8A browser test', timeoutMs: limits.browserMs, stopTimeoutMs: limits.stopMs, states: [backend, deny, vite], signal: controller.signal })
        } catch (error) {
          error.phase8aBrowserCause = classifyBrowserFailure(roots.resultPath, error)
          throw error
        }
        if (deps.readOwnedText(roots.outboundLedgerPath).trim()) throw new Error('Phase8A Provider request ledger was not zero')
        deniedConnects = assertBrowserDenyLedger(deps.readOwnedText(roots.denyProxyLedgerPath)).deniedConnectCount
        try {
          assertPageEventLedger(deps.readOwnedText(roots.pageEventLedgerPath))
        } catch (error) {
          error.phase8aBrowserCause = 'page-events-invalid'
          throw error
        }
        await bodyCommand(python, ['-m', 'backend.scripts.prepare_phase8a_browser_db', '--database', database, '--verify-postconditions'], root, backendEnvironment, 'Phase8A postcondition verifier', [backend, deny, vite])
      },
      stopServer: server => deps.stopOwnedServer(server, { timeoutMs: limits.stopMs }),
      releaseReservation: reservation => reservation.release(),
      async dropDatabase(name) {
        await cleanupCommand(environment.PYTHON || 'python', ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', name, '--drop'], root, mysql, 'Phase8A database cleanup')
        cleaned = 1
      },
      removeRoot: owned => deps.cleanupRoot(owned, roots, ports),
    })
  } finally {
    processTarget.removeListener('SIGINT', onSigint)
    processTarget.removeListener('SIGTERM', onSigterm)
  }
  deps.assertDatabaseResidue(database, database, { created, cleaned, remaining: 0 })
  log(`Phase8A browser: 1/1 wide-screen point passed; Provider requests=0; denied Chromium background connects=${deniedConnects}; page console known linked=4; page console unexpected=0; page errors=0; request failures=0; live website access=0; owned child processes/ports/temp/downloads/disposable schemas=0`)
  return 0
}

if ((() => { try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)) } catch { return false } })()) {
  runPhase8A().then(value => { process.exitCode = value }).catch(error => {
    console.error(safeFailureSummary(error))
    process.exitCode = 1
  })
}

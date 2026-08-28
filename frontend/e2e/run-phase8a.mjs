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

export function classifyBrowserFailure(resultPath) {
  try {
    const errors = reportErrors(JSON.parse(readFileSync(resultPath, 'utf8')))
    const error = errors.find(item => (
      item.location?.file?.endsWith('manuscript-productization.spec.mjs')
      && Number.isInteger(item.location.line)
    )) || errors[0]
    if (!error) return 'unclassified'
    const stackLine = typeof error.stack === 'string'
      ? error.stack.match(/manuscript-productization\.spec\.mjs:(\d+):\d+/u)?.[1]
      : null
    const line = error.location?.file?.endsWith('manuscript-productization.spec.mjs') && Number.isInteger(error.location.line)
      ? error.location.line : stackLine || 'unknown'
    const category = /timed out|timeout/iu.test(error.message)
      ? 'timeout' : /locator|strict mode/iu.test(error.message) ? 'locator' : 'assertion'
    return `${category}@${line}`
  } catch {
    return 'unclassified'
  }
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

export async function runPhase8A({ environment = process.env, log = console.log, deadlines = {} } = {}) {
  validateTestEnvironment(environment)
  const limits = { ...DEFAULT_DEADLINES, ...deadlines }
  const database = createDatabaseName()
  assertDatabaseName(database)
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
  process.once('SIGINT', onSigint)
  process.once('SIGTERM', onSigterm)
  const mysql = {
    ...base,
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST, TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER, TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_HOST: environment.TEST_MYSQL_HOST, MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER, MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: database, BROWSER_TEST_DATABASE: database,
  }
  const ownedCommand = (command, args, cwd, env, label, states = []) => runBoundedOwnedCommand(
    command, args, options(cwd, env),
    { label, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs, states, signal: controller.signal },
  )
  try {
    await runOwnedProductLifecycle({
      async body(lifecycle) {
        const owned = lifecycle.setRoot(createOwnedRoot(ROOT_PREFIX))
        roots = createRoots(owned)
        lifecycle.setDatabase(database)
        const reservations = []
        for (let index = 0; index < 3; index += 1) {
          const reservation = lifecycle.registerReservation(await reserveLocalPort())
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
          BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, apiUrl]),
          BROWSER_DENY_PROXY_URL: denyUrl,
          BROWSER_COMPLETE_PROJECT_ID: '8a000000-0000-4000-8000-000000000001',
          BROWSER_AWAITING_PROJECT_ID: '8a000000-0000-4000-8000-000000000002',
          BROWSER_CORRUPT_PROJECT_ID: '8a000000-0000-4000-8000-000000000003',
        }
        await ownedCommand(python, ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', database], root, mysql, 'Phase8A database preparation')
        created = 1
        await ownedCommand(python, ['-m', 'backend.scripts.prepare_phase8a_browser_db', '--database', database], root, backendEnvironment, 'Phase8A fixture preparation')
        await lifecycle.releaseReservation(reservations[0])
        const backend = lifecycle.registerServer(startOwnedServer(python, ['-c', `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name='__main__')`, String(apiPort)], options(root, backendEnvironment), { label: 'Phase8A API' }))
        await waitForOwnedServer(backend, `${apiUrl}/api/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs })
        await lifecycle.releaseReservation(reservations[1])
        const deny = lifecycle.registerServer(startOwnedServer(process.execPath, [roots.denyProxyPath, String(denyPort)], options(root, { ...base, BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath, M2_BROWSER_RUN_NONCE: nonce }), { label: 'Phase8A deny proxy' }))
        await waitForOwnedServer(deny, `${denyUrl}/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs })
        await lifecycle.releaseReservation(reservations[2])
        const vite = lifecycle.registerServer(startOwnedServer(process.execPath, [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], options(frontend, { ...base, VITE_API_BASE_URL: `${apiUrl}/api`, M2_BROWSER_RUN_NONCE: nonce }), { label: 'Phase8A Vite' }))
        await waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, { expectedNonce: nonce, timeoutMs: limits.healthMs })
        try {
          await runBoundedOwnedCommand(process.execPath, [path.join(frontend, 'node_modules', 'playwright', 'cli.js'), 'test', `e2e/${FORMAL_SPECS[0]}`, '--config', `e2e/${FORMAL_CONFIG}`], options(frontend, browserEnvironment), { label: 'Phase8A browser test', timeoutMs: limits.browserMs, stopTimeoutMs: limits.stopMs, states: [backend, deny, vite], signal: controller.signal })
        } catch (error) {
          error.phase8aBrowserCause = classifyBrowserFailure(roots.resultPath)
          throw error
        }
        if (readFileSync(roots.outboundLedgerPath, 'utf8').trim()) throw new Error('Phase8A Provider request ledger was not zero')
        deniedConnects = assertBrowserDenyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8')).deniedConnectCount
        await ownedCommand(python, ['-m', 'backend.scripts.prepare_phase8a_browser_db', '--database', database, '--verify-postconditions'], root, backendEnvironment, 'Phase8A postcondition verifier', [backend, deny, vite])
      },
      stopServer: server => stopOwnedServer(server, { timeoutMs: limits.stopMs }),
      releaseReservation: reservation => reservation.release(),
      async dropDatabase(name) {
        await ownedCommand(environment.PYTHON || 'python', ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', name, '--drop'], root, mysql, 'Phase8A database cleanup')
        cleaned = 1
      },
      removeRoot: owned => cleanupRoot(owned, roots, ports),
    })
  } finally {
    process.removeListener('SIGINT', onSigint)
    process.removeListener('SIGTERM', onSigterm)
  }
  assertDatabaseResidue(database, database, { created, cleaned, remaining: 0 })
  log(`Phase8A browser: 1/1 wide-screen point passed; Provider requests=0; denied Chromium background connects=${deniedConnects}; live website access=0; owned child processes/ports/temp/downloads/disposable schemas=0`)
  return 0
}

if ((() => { try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)) } catch { return false } })()) {
  runPhase8A().then(value => { process.exitCode = value }).catch(error => {
    console.error(safeFailureSummary(error))
    process.exitCode = 1
  })
}

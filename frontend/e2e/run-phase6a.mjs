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

export const FORMAL_SPECS = Object.freeze(['phase6a/finalized-novel-download.spec.mjs'])
export const FORMAL_CONFIG = 'playwright.phase6a.config.mjs'
const ROOT_PREFIX = 'novel-creator-phase6a-'
const PROJECT_ID = '81000000-0000-0000-0000-000000000001'
const DEFAULT_DEADLINES = Object.freeze({ commandMs: 90_000, healthMs: 45_000, browserMs: 180_000, stopMs: 8_000 })
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.resolve(frontend, '..')
const SAFE_STAGES = new Set(['database-preparation', 'fixture-preparation', 'backend-start', 'deny-proxy-start', 'vite-start', 'browser-test', 'outbound-audit', 'deny-proxy-audit', 'postcondition-verifier', 'server-cleanup', 'database-cleanup', 'root-cleanup'])

// This is a runner-owned test hook: it only delays the actual endpoint before
// delegating to FastAPI, then the production router/service/repository performs
// the request normally.  It never substitutes a response or touches page routes.
const BACKEND_SOURCE = String.raw`
import asyncio, os, sys
import httpx, uvicorn
ledger = os.environ['BROWSER_OUTBOUND_LEDGER_PATH']
RealAsyncClient = httpx.AsyncClient
class DeniedAsyncClient:
    def __init__(self, *args, **kwargs): self.inner = RealAsyncClient(*args, **kwargs)
    async def __aenter__(self): await self.inner.__aenter__(); return self
    async def __aexit__(self, *args): return await self.inner.__aexit__(*args)
    async def aclose(self): return await self.inner.aclose()
    def build_request(self, *args, **kwargs): return self.inner.build_request(*args, **kwargs)
    def deny(self):
        with open(ledger, 'a', encoding='utf-8') as output: output.write('forbidden-outbound\n')
        raise RuntimeError('forbidden outbound request')
    async def request(self, *args, **kwargs): self.deny()
    async def send(self, *args, **kwargs): self.deny()
    def stream(self, *args, **kwargs): self.deny()
    async def post(self, *args, **kwargs): self.deny()
httpx.AsyncClient = DeniedAsyncClient
from backend.main import app
@app.middleware('http')
async def phase6a_held_download(request, call_next):
    if request.url.path.endswith('/novel-download'):
        await asyncio.sleep(float(os.environ.get('PHASE6A_HOLD_DOWNLOAD_SECONDS', '1.2')))
    return await call_next(request)
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
`

const options = (cwd, env) => ({ cwd, env, stdio: ['ignore', 'pipe', 'pipe'] })
const allowed = environment => Object.fromEntries(BASE_ENV_ALLOWLIST.filter(key => Object.hasOwn(environment, key)).map(key => [key, environment[key]]))
const normalize = value => { const resolved = path.resolve(value); return process.platform === 'win32' ? resolved.toLowerCase() : resolved }

function createRoots(owned) {
  const roots = {
    artifactRoot: path.join(owned, 'artifacts'), downloadRoot: path.join(owned, 'downloads'),
    backendPath: path.join(owned, 'backend.py'), denyProxyPath: path.join(owned, 'deny-proxy.cjs'),
    viteConfigPath: path.join(owned, 'vite.config.mjs'), resultPath: path.join(owned, 'browser-result.json'),
    outboundLedgerPath: path.join(owned, 'outbound-ledger.log'), denyProxyLedgerPath: path.join(owned, 'deny-proxy.log'),
  }
  mkdirSync(roots.artifactRoot); mkdirSync(roots.downloadRoot)
  for (const [target, contents] of [[roots.backendPath, BACKEND_SOURCE], [roots.denyProxyPath, DENY_PROXY_SOURCE], [roots.outboundLedgerPath, ''], [roots.denyProxyLedgerPath, '']]) writeFileSync(target, contents, { encoding: 'utf8', flag: 'wx' })
  writeFileSync(roots.viteConfigPath, `import base from ${JSON.stringify(pathToFileURL(path.join(frontend, 'vite.config.js')).href)}\nexport default { ...base, cacheDir: ${JSON.stringify(path.join(owned, 'vite-cache'))} }\n`, { encoding: 'utf8', flag: 'wx' })
  return roots
}

async function waitForPortRelease(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer()
    const timeout = setTimeout(() => { probe.close(); reject(new Error('Phase6A owned port remained bound')) }, 10_000)
    probe.once('error', error => { clearTimeout(timeout); reject(error) })
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => probe.close(error => { clearTimeout(timeout); if (error) reject(error); else resolve() }))
  })
}

async function cleanupRoot(owned, roots, ports) {
  const errors = []
  for (const port of ports) try { await waitForPortRelease(port) } catch (error) { errors.push(error) }
  try {
    const cache = path.join(owned, 'vite-cache')
    const temp = existsSync(cache) ? readdirSync(cache, { withFileTypes: true }).filter(entry => entry.isDirectory() && entry.name.startsWith('deps_temp_')) : []
    if (temp.length) throw new Error('Phase6A owned Vite deps_temp residue was not zero')
    if (readFileSync(roots.outboundLedgerPath, 'utf8').trim()) throw new Error('Phase6A backend made an outbound request')
    assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8'))
    if (readdirSync(roots.downloadRoot, { withFileTypes: true }).some(entry => !entry.isFile())) throw new Error('Phase6A download root contains a non-file')
  } catch (error) { errors.push(error) }
  try { removeOwnedRoot(assertOwnedRoot(owned, ROOT_PREFIX), ROOT_PREFIX); if (existsSync(owned)) throw new Error('Phase6A owned root remained') } catch (error) { errors.push(error) }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase6A root cleanup failed')
}

async function runStage(stage, action) {
  try { return await action() } catch (cause) {
    const error = new Error('Phase6A stage failed', { cause }); error.phase6aStage = SAFE_STAGES.has(stage) ? stage : 'lifecycle'; throw error
  }
}

function classifyBrowserFailure(resultPath) {
  try {
    const report = JSON.parse(readFileSync(resultPath, 'utf8'))
    const rendered = JSON.stringify(report)
    const line = rendered.match(/finalized-novel-download\.spec\.mjs:(\d+)/u)?.[1] || 'unknown'
    return `${/timed out|timeout/iu.test(rendered) ? 'timeout' : /locator/iu.test(rendered) ? 'locator' : 'assertion'}@${line}`
  } catch { return 'unclassified' }
}

export async function runPhase6A({ environment = process.env, log = console.log, deadlines = {} } = {}) {
  validateTestEnvironment(environment)
  const limits = { ...DEFAULT_DEADLINES, ...deadlines }
  const database = createDatabaseName(); assertDatabaseName(database)
  const base = allowed(environment); const ports = []; let roots = null; let created = 0; let cleaned = 0
  const mysql = { ...base, TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST, TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT, TEST_MYSQL_USER: environment.TEST_MYSQL_USER, TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD, MYSQL_HOST: environment.TEST_MYSQL_HOST, MYSQL_PORT: environment.TEST_MYSQL_PORT, MYSQL_USER: environment.TEST_MYSQL_USER, MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD, MYSQL_DB: database, BROWSER_TEST_DATABASE: database }
  await runOwnedProductLifecycle({
    async body(lifecycle) {
      const owned = lifecycle.setRoot(createOwnedRoot(ROOT_PREFIX)); roots = createRoots(owned); lifecycle.setDatabase(database)
      const reservations = []
      for (let index = 0; index < 3; index += 1) { const reservation = lifecycle.registerReservation(await reserveLocalPort()); reservations.push(reservation); ports.push(reservation.port) }
      if (new Set(ports).size !== 3) throw new Error('Phase6A owned ports are not unique')
      const [apiPort, denyPort, vitePort] = ports; const apiUrl = `http://127.0.0.1:${apiPort}`; const denyUrl = `http://127.0.0.1:${denyPort}`; const viteUrl = `http://127.0.0.1:${vitePort}`; const nonce = randomUUID(); const python = environment.PYTHON || 'python'
      const backendEnvironment = { ...mysql, BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath, M2_BROWSER_RUN_NONCE: nonce, SCHEDULER_ENABLED: '0', MARKET_SCHEDULER_ENABLED: 'false', PHASE6A_HOLD_DOWNLOAD_SECONDS: '1.2' }
      const browserEnvironment = { ...mysql, PLAYWRIGHT_BASE_URL: viteUrl, BROWSER_PROJECT_ID: PROJECT_ID, BROWSER_OWNED_ROOT: owned, BROWSER_ARTIFACT_ROOT: roots.artifactRoot, BROWSER_DOWNLOAD_ROOT: roots.downloadRoot, BROWSER_RESULT_PATH: roots.resultPath, BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, apiUrl]), BROWSER_DENY_PROXY_URL: denyUrl }
      await runStage('database-preparation', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', database], options(root, mysql), { label: 'Phase6A database preparation', timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs })); created = 1
      await runStage('fixture-preparation', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_phase6a_browser_db', '--database', database], options(root, backendEnvironment), { label: 'Phase6A fixture preparation', timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs }))
      await lifecycle.releaseReservation(reservations[0])
      const backend = lifecycle.registerServer(startOwnedServer(python, ['-c', `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name='__main__')`, String(apiPort)], options(root, backendEnvironment), { label: 'Phase6A API' }))
      await runStage('backend-start', () => waitForOwnedServer(backend, `${apiUrl}/api/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs }))
      await lifecycle.releaseReservation(reservations[1])
      const deny = lifecycle.registerServer(startOwnedServer(process.execPath, [roots.denyProxyPath, String(denyPort)], options(root, { ...base, BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath, M2_BROWSER_RUN_NONCE: nonce }), { label: 'Phase6A deny proxy' }))
      await runStage('deny-proxy-start', () => waitForOwnedServer(deny, `${denyUrl}/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs }))
      await lifecycle.releaseReservation(reservations[2])
      const vite = lifecycle.registerServer(startOwnedServer(process.execPath, [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], options(frontend, { ...base, VITE_API_BASE_URL: `${apiUrl}/api`, M2_BROWSER_RUN_NONCE: nonce }), { label: 'Phase6A Vite' }))
      await runStage('vite-start', () => waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, { expectedNonce: nonce, timeoutMs: limits.healthMs }))
      await runStage('browser-test', async () => {
        try { return await runBoundedOwnedCommand(process.execPath, [path.join(frontend, 'node_modules', 'playwright', 'cli.js'), 'test', `e2e/${FORMAL_SPECS[0]}`, '--config', `e2e/${FORMAL_CONFIG}`], options(frontend, browserEnvironment), { label: 'Phase6A browser test', timeoutMs: limits.browserMs, stopTimeoutMs: limits.stopMs, states: [backend, deny, vite] }) } catch (error) { error.phase6aBrowserCause = classifyBrowserFailure(roots.resultPath); throw error }
      })
      await runStage('outbound-audit', () => { if (readFileSync(roots.outboundLedgerPath, 'utf8').trim()) throw new Error('Phase6A backend made an outbound request') })
      await runStage('deny-proxy-audit', () => assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8')))
      await runStage('postcondition-verifier', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_phase6a_browser_db', '--database', database, '--verify-postconditions'], options(root, backendEnvironment), { label: 'Phase6A postcondition verifier', timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs, states: [backend, deny, vite] }))
    },
    stopServer: server => runStage('server-cleanup', () => stopOwnedServer(server, { timeoutMs: limits.stopMs })),
    releaseReservation: reservation => reservation.release(),
    async dropDatabase(name) { await runStage('database-cleanup', () => runBoundedOwnedCommand(environment.PYTHON || 'python', ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', name, '--drop'], options(root, mysql), { label: 'Phase6A database cleanup', timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs })); cleaned = 1 },
    removeRoot: owned => runStage('root-cleanup', () => cleanupRoot(owned, roots, ports)),
  })
  assertDatabaseResidue(database, database, { created, cleaned, remaining: 0 })
  log('Phase6A browser: 1/1 scenarios passed; DB/process/ports/temp/artifacts/downloads/Vite residue=0; outbound/provider calls=0; product DB reads/writes=0/0')
  return 0
}

export function safeCliFailureSummary(error) {
  const stages = []; let browserCause = null; const visit = value => { if (!value || typeof value !== 'object') return; if (typeof value.phase6aStage === 'string') stages.push(value.phase6aStage); if (typeof value.phase6aBrowserCause === 'string') browserCause ||= value.phase6aBrowserCause; if (value.cause) visit(value.cause); if (value instanceof AggregateError) value.errors.forEach(visit) }; visit(error)
  return JSON.stringify({ firstStage: stages[0] || 'lifecycle', errorCount: Math.max(stages.length, 1), browserCause })
}

if ((() => { try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)) } catch { return false } })()) runPhase6A().then(value => { process.exitCode = value }).catch(error => { console.error(safeCliFailureSummary(error)); process.exitCode = 1 })

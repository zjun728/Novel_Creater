import { randomUUID } from 'node:crypto'
import {
  existsSync,
  mkdirSync,
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
import {
  assertNoPrivateEvidenceMarkers,
  runtimeSensitiveValues,
} from './runtime-observer.mjs'


export const FORMAL_SPECS = Object.freeze(['phase4c-candidate-workbench.spec.ts'])
export const FORMAL_CONFIG = 'playwright.phase4c.config.ts'
export const FORMAL_SCENARIO = Object.freeze({ tag: '@candidate-workbench' })
const OWNED_ROOT_PREFIX = 'novel-creator-phase4c-'
const PROJECT_ID = '81000000-0000-0000-0000-000000000001'
const SECRET_SENTINEL = 'phase4c-browser-secret-must-not-leak'
const DRAFT_MARKERS = Object.freeze(['甲'.repeat(96), '乙'.repeat(112)])
const DEFAULT_DEADLINES = Object.freeze({
  commandMs: 90_000,
  healthMs: 45_000,
  browserMs: 180_000,
  stopMs: 8_000,
})
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const SAFE_STAGES = new Set([
  'database-preparation', 'canonical-fixture', 'backend-start',
  'deny-proxy-start', 'vite-start', 'browser-test', 'outbound-audit',
  'deny-proxy-audit', 'postcondition-verifier', 'server-cleanup',
  'database-cleanup', 'root-cleanup',
])


const BACKEND_SOURCE = String.raw`
import os, sys
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
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
`


function childOptions(cwd, env) {
  return { cwd, env, stdio: ['ignore', 'pipe', 'pipe'] }
}


function allowedEnvironment(environment) {
  return Object.fromEntries(BASE_ENV_ALLOWLIST
    .filter(key => Object.hasOwn(environment, key))
    .map(key => [key, environment[key]]))
}


function databaseEnvironment(environment, databaseName) {
  return {
    ...allowedEnvironment(environment),
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
    TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
    TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    BROWSER_TEST_DATABASE: databaseName,
  }
}


function createRoots(root) {
  const artifactRoot = path.join(root, 'artifacts')
  const backendPath = path.join(root, 'backend.py')
  const denyProxyPath = path.join(root, 'deny-proxy.cjs')
  const viteConfigPath = path.join(root, 'vite.config.mjs')
  const browserResultPath = path.join(root, 'browser-result.json')
  const outboundLedgerPath = path.join(root, 'outbound-ledger.log')
  const denyProxyLedgerPath = path.join(root, 'deny-proxy.log')
  mkdirSync(artifactRoot)
  for (const [target, value] of [
    [backendPath, BACKEND_SOURCE],
    [denyProxyPath, DENY_PROXY_SOURCE],
    [outboundLedgerPath, ''],
    [denyProxyLedgerPath, ''],
  ]) writeFileSync(target, value, { encoding: 'utf8', flag: 'wx' })
  const baseConfig = pathToFileURL(path.join(frontendRoot, 'vite.config.js')).href
  writeFileSync(
    viteConfigPath,
    `import base from ${JSON.stringify(baseConfig)}\nexport default { ...base, cacheDir: ${JSON.stringify(path.join(root, 'vite-cache'))}, optimizeDeps: { ...base.optimizeDeps, noDiscovery: false } }\n`,
    { encoding: 'utf8', flag: 'wx' },
  )
  return {
    artifactRoot,
    backendPath,
    denyProxyPath,
    viteConfigPath,
    browserResultPath,
    outboundLedgerPath,
    denyProxyLedgerPath,
  }
}


function artifactFiles(root) {
  if (!existsSync(root)) return []
  const files = []
  const visit = directory => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name)
      if (entry.isDirectory()) visit(target)
      else if (entry.isFile()) files.push(target)
      else throw new Error('Phase4C artifact root contains a non-regular entry')
    }
  }
  visit(root)
  return files
}


function assertArtifactEvidenceSafe(roots, sensitiveValues) {
  for (const target of [
    ...artifactFiles(roots.artifactRoot),
    roots.outboundLedgerPath,
    roots.denyProxyLedgerPath,
    roots.browserResultPath,
  ].filter(existsSync)) {
    const value = readFileSync(target, 'utf8')
    assertNoPrivateEvidenceMarkers([value])
    if ([...sensitiveValues, ...DRAFT_MARKERS].some(item => item && value.includes(item))) {
      throw new Error('Phase4C artifact contains sensitive evidence')
    }
  }
}


function assertOutboundLedger(value) {
  if (String(value).trim() !== '') {
    throw new Error('Phase4C backend made an outbound request')
  }
}


async function waitForPortRelease(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer()
    const timeout = setTimeout(() => {
      probe.close()
      reject(new Error('owned port remained bound'))
    }, 10000)
    probe.once('error', error => {
      clearTimeout(timeout)
      reject(error)
    })
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      probe.close(error => {
        clearTimeout(timeout)
        if (error) reject(error)
        else resolve()
      })
    })
  })
}


async function cleanupRoot(root, roots, ports, sensitiveValues) {
  const errors = []
  for (const port of ports) {
    try { await waitForPortRelease(port) } catch (error) { errors.push(error) }
  }
  try {
    const cache = path.join(root, 'vite-cache')
    const residue = existsSync(cache)
      ? readdirSync(cache, { withFileTypes: true }).filter(entry => (
        entry.isDirectory() && entry.name.startsWith('deps_temp_')
      ))
      : []
    if (residue.length !== 0) throw new Error('Phase4C owned Vite deps_temp residue was not zero')
  } catch (error) { errors.push(error) }
  try { assertArtifactEvidenceSafe(roots, sensitiveValues) } catch (error) { errors.push(error) }
  try {
    removeOwnedRoot(assertOwnedRoot(root, OWNED_ROOT_PREFIX), OWNED_ROOT_PREFIX)
    if (existsSync(root)) throw new Error('Phase4C owned temporary root remained')
  } catch (error) { errors.push(error) }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase4C root cleanup failed')
}


async function runStage(stage, operation) {
  try {
    return await operation()
  } catch (cause) {
    const error = new Error('Phase4C stage failed', { cause })
    error.phase4CStage = SAFE_STAGES.has(stage) ? stage : 'lifecycle'
    throw error
  }
}


export function formatBrowserPassedSummary(passed) {
  if (passed !== 1) throw new Error('Phase4C scenario summary counters are invalid')
  return 'Phase4C browser: 1/1 scenarios passed'
}


export async function runPhase4C({ environment = process.env, log = console.log, deadlines = {} } = {}) {
  validateTestEnvironment(environment)
  const limits = { ...DEFAULT_DEADLINES, ...deadlines }
  const databaseName = createDatabaseName()
  assertDatabaseName(databaseName)
  const cleanupEnvironment = databaseEnvironment(environment, databaseName)
  const base = allowedEnvironment(environment)
  const ports = []
  let roots = null
  let created = 0
  let cleaned = 0
  await runOwnedProductLifecycle({
    async body(lifecycle) {
      const root = lifecycle.setRoot(createOwnedRoot(OWNED_ROOT_PREFIX))
      roots = createRoots(root)
      lifecycle.setDatabase(databaseName)
      const reservations = []
      for (let index = 0; index < 3; index += 1) {
        const reservation = lifecycle.registerReservation(await reserveLocalPort())
        reservations.push(reservation)
        ports.push(reservation.port)
      }
      if (new Set(ports).size !== 3) throw new Error('Phase4C runner received duplicate owned ports')
      const [backendPort, denyPort, vitePort] = ports
      const backendUrl = `http://127.0.0.1:${backendPort}`
      const denyUrl = `http://127.0.0.1:${denyPort}`
      const viteUrl = `http://127.0.0.1:${vitePort}`
      const nonce = randomUUID()
      const backendEnvironment = {
        ...base,
        MYSQL_HOST: environment.TEST_MYSQL_HOST,
        MYSQL_PORT: environment.TEST_MYSQL_PORT,
        MYSQL_USER: environment.TEST_MYSQL_USER,
        MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
        MYSQL_DB: databaseName,
        BROWSER_TEST_DATABASE: databaseName,
        BROWSER_PROJECT_ID: PROJECT_ID,
        BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
        BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath,
        M2_BROWSER_RUN_NONCE: nonce,
        MARKET_SCHEDULER_ENABLED: 'false',
        SCHEDULER_ENABLED: '0',
      }
      const browserEnvironment = {
        ...backendEnvironment,
        PLAYWRIGHT_BASE_URL: viteUrl,
        BROWSER_OWNED_ROOT: root,
        BROWSER_ARTIFACT_ROOT: roots.artifactRoot,
        BROWSER_RESULT_PATH: roots.browserResultPath,
        BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, backendUrl]),
        BROWSER_DENY_PROXY_URL: denyUrl,
      }
      const sensitiveValues = runtimeSensitiveValues(browserEnvironment)
      const python = environment.PYTHON || 'python'
      const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')
      const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')

      await runStage('database-preparation', () => runBoundedOwnedCommand(
        python,
        ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', databaseName],
        childOptions(repositoryRoot, cleanupEnvironment),
        { label: 'Phase4C database preparation', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs },
      ))
      created = 1
      await runStage('canonical-fixture', () => runBoundedOwnedCommand(
        python,
        ['-m', 'backend.scripts.prepare_phase4c_browser_db', '--database', databaseName],
        childOptions(repositoryRoot, backendEnvironment),
        { label: 'Phase4C canonical fixture', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs },
      ))

      await lifecycle.releaseReservation(reservations[0])
      const backend = lifecycle.registerServer(startOwnedServer(
        python,
        ['-c', `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name='__main__')`, String(backendPort)],
        childOptions(repositoryRoot, backendEnvironment),
        { label: 'backend', sensitiveValues },
      ))
      await runStage('backend-start', () => waitForOwnedServer(
        backend,
        `${backendUrl}/api/health`,
        { expectedNonce: nonce, timeoutMs: limits.healthMs },
      ))

      await lifecycle.releaseReservation(reservations[1])
      const denyProxy = lifecycle.registerServer(startOwnedServer(
        process.execPath,
        [roots.denyProxyPath, String(denyPort)],
        childOptions(repositoryRoot, {
          ...base,
          BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath,
          M2_BROWSER_RUN_NONCE: nonce,
        }),
        { label: 'deny proxy', sensitiveValues },
      ))
      await runStage('deny-proxy-start', () => waitForOwnedServer(
        denyProxy,
        `${denyUrl}/health`,
        { expectedNonce: nonce, timeoutMs: limits.healthMs },
      ))

      await lifecycle.releaseReservation(reservations[2])
      const vite = lifecycle.registerServer(startOwnedServer(
        process.execPath,
        [viteCli, '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'],
        childOptions(frontendRoot, {
          ...base,
          NODE_ENV: 'test',
          VITE_API_BASE_URL: `${backendUrl}/api`,
          M2_BROWSER_RUN_NONCE: nonce,
        }),
        { label: 'vite', sensitiveValues },
      ))
      await runStage('vite-start', () => waitForOwnedServer(
        vite,
        `${viteUrl}/__m2-browser-owner`,
        { expectedNonce: nonce, timeoutMs: limits.healthMs },
      ))

      const servers = [backend, denyProxy, vite]
      await runStage('browser-test', () => runBoundedOwnedCommand(
        process.execPath,
        [
          playwrightCli,
          'test',
          `e2e/${FORMAL_SPECS[0]}`,
          '--config',
          `e2e/${FORMAL_CONFIG}`,
          '--grep',
          FORMAL_SCENARIO.tag,
        ],
        childOptions(frontendRoot, browserEnvironment),
        { label: 'Phase4C browser test', sensitiveValues, timeoutMs: limits.browserMs, stopTimeoutMs: limits.stopMs, states: servers },
      ))
      await runStage('outbound-audit', async () => (
        assertOutboundLedger(readFileSync(roots.outboundLedgerPath, 'utf8'))
      ))
      await runStage('deny-proxy-audit', async () => (
        assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8'))
      ))
      await runStage('postcondition-verifier', () => runBoundedOwnedCommand(
        python,
        ['-m', 'backend.scripts.prepare_phase4c_browser_db', '--database', databaseName, '--verify-postconditions'],
        childOptions(repositoryRoot, backendEnvironment),
        { label: 'Phase4C verify-postconditions', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs, states: servers },
      ))
    },
    stopServer: server => runStage('server-cleanup', () => stopOwnedServer(server, { timeoutMs: limits.stopMs })),
    releaseReservation: reservation => reservation.release(),
    async dropDatabase(name) {
      await runStage('database-cleanup', () => runBoundedOwnedCommand(
        environment.PYTHON || 'python',
        ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', name, '--drop'],
        childOptions(repositoryRoot, cleanupEnvironment),
        { label: 'Phase4C database cleanup', timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs },
      ))
      cleaned = 1
    },
    removeRoot: root => runStage('root-cleanup', () => cleanupRoot(
      root,
      roots,
      ports,
      runtimeSensitiveValues({ ...environment, MYSQL_DB: databaseName, BROWSER_SECRET_SENTINEL: SECRET_SENTINEL }),
    )),
  })
  assertDatabaseResidue(databaseName, databaseName, { created, cleaned, remaining: 0 })
  log('Phase4C candidate workbench: scenario passed; DB/process/port/temp/artifact/Vite residue=0; real provider calls = 0; product DB reads/writes = 0/0')
  log(formatBrowserPassedSummary(1))
  return 0
}


export function samePathIdentity(left, right) {
  const normalize = value => {
    const resolved = path.resolve(value)
    return process.platform === 'win32' ? resolved.toLowerCase() : resolved
  }
  return normalize(left) === normalize(right)
}


export function safeCliFailureSummary(error) {
  const counts = new Map()
  const visited = new Set()
  const visit = value => {
    if (!value || typeof value !== 'object' || visited.has(value)) return
    visited.add(value)
    if (typeof value.phase4CStage === 'string') {
      counts.set(value.phase4CStage, (counts.get(value.phase4CStage) || 0) + 1)
    }
    if (value instanceof AggregateError) value.errors.forEach(visit)
    if (value.cause) visit(value.cause)
  }
  visit(error)
  if (counts.size === 0) {
    const fallback = formatSafeLifecycleDiagnostics([{ category: 'lifecycle', error }])
    return JSON.stringify({ firstStage: 'lifecycle', errorCount: fallback.errorCount })
  }
  const stages = [...counts].map(([stage, count]) => ({ stage, count }))
  return JSON.stringify({
    firstStage: stages[0].stage,
    errorCount: stages.reduce((total, item) => total + item.count, 0),
    stages,
  })
}


if ((() => {
  try {
    return samePathIdentity(realpathSync(process.argv[1]), realpathSync(fileURLToPath(import.meta.url)))
  } catch {
    return false
  }
})()) {
  runPhase4C().then(status => { process.exitCode = status }).catch(error => {
    console.error(safeCliFailureSummary(error))
    process.exitCode = 1
  })
}

import { randomUUID } from 'node:crypto'
import {
  existsSync,
  lstatSync,
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
import { BACKEND_SOURCE } from './run-phase4b2.mjs'


export const FORMAL_SPECS = Object.freeze(['phase4b3-selection-tools.spec.ts'])
export const FORMAL_CONFIG = 'playwright.phase4b3.config.ts'
export const FORMAL_SCENARIO = Object.freeze({ tag: '@selection-tools' })
const OWNED_ROOT_PREFIX = 'novel-creator-phase4b3-'
const PROJECT_ID = '81000000-0000-0000-0000-000000000001'
const SECRET_SENTINEL = 'phase4b3-browser-secret-must-not-leak'
const GENERATED_TEXT_MARKERS = Object.freeze([
  '基'.repeat(8), '改'.repeat(256), '润'.repeat(256),
  '扩'.repeat(256), '缩'.repeat(256),
])
const DEFAULT_DEADLINES = Object.freeze({ commandMs: 90_000, healthMs: 45_000, browserMs: 180_000, stopMs: 8_000 })
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const formalSpecPath = path.join(frontendRoot, 'e2e', FORMAL_SPECS[0])
const SAFE_STAGES = new Set([
  'database-preparation', 'canonical-fixture', 'fake-provider-start',
  'backend-start', 'deny-proxy-start', 'vite-start', 'browser-test',
  'outbound-audit', 'deny-proxy-audit', 'provider-ledger-audit',
  'postcondition-verifier', 'server-cleanup', 'database-cleanup', 'root-cleanup',
])


async function runStage(stage, operation) {
  try {
    return await operation()
  } catch (cause) {
    const error = new Error('Phase4B3 stage failed', { cause })
    error.phase4B3Stage = SAFE_STAGES.has(stage) ? stage : 'lifecycle'
    throw error
  }
}


export const FAKE_LOCAL_PROVIDER_SOURCE = String.raw`
const { appendFileSync } = require('node:fs')
const http = require('node:http')
const port = Number(process.argv[2])
const nonce = process.env.M2_BROWSER_RUN_NONCE
const ledgerPath = process.env.BROWSER_PROVIDER_LEDGER_PATH
const secret = process.env.BROWSER_SECRET_SENTINEL
const outputs = ['改', '润', '扩', '缩'].map(value => value.repeat(256))
const REQUEST_LIMIT = 65536
let calls = 0
function record(value) { appendFileSync(ledgerPath, value + '\n', 'utf8') }
function reject(response, status) { response.writeHead(status); response.end(); record('terminal=rejected') }
http.createServer((request, response) => {
  if (request.method === 'GET' && request.url === '/health') {
    response.writeHead(200, { 'content-type': 'application/json' })
    response.end(JSON.stringify({ browserRunNonce: nonce }))
    return
  }
  if (request.method !== 'POST' || request.url !== '/v1/chat/completions') return reject(response, 404)
  let size = 0
  let body = ''
  let rejected = false
  request.on('data', chunk => {
    if (rejected) return
    size += chunk.length
    if (size > REQUEST_LIMIT) {
      rejected = true
      reject(response, 413)
      request.destroy()
      return
    }
    body += chunk.toString('utf8')
  })
  request.on('end', () => {
    if (rejected) return
    let valid = false
    try { valid = request.headers.authorization === 'Bearer ' + secret && JSON.parse(body).stream === true } catch {}
    if (!valid || calls >= outputs.length) return reject(response, 400)
    const call = ++calls
    record('call=' + call)
    record('accepted-local-provider')
    response.writeHead(200, { 'content-type': 'text/event-stream', 'cache-control': 'no-cache', connection: 'keep-alive' })
    response.write('data: ' + JSON.stringify({ choices: [{ index: 0, delta: { content: outputs[call - 1] } }] }) + '\n\n')
    let terminal = false
    response.once('close', () => {
      if (!terminal) { terminal = true; record('terminal=transport-closed') }
    })
    if (call === 3) return
    setTimeout(() => {
      if (terminal) return
      terminal = true
      response.write('data: [DONE]\n\n')
      response.end()
      record('terminal=completed')
    }, 10000)
  })
}).listen(port, '127.0.0.1')
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
  const providerPath = path.join(root, 'fake-provider.cjs')
  const backendPath = path.join(root, 'backend.py')
  const denyProxyPath = path.join(root, 'deny-proxy.cjs')
  const viteConfigPath = path.join(root, 'vite.config.mjs')
  const browserResultPath = path.join(root, 'browser-result.json')
  const providerLedgerPath = path.join(root, 'provider-ledger.log')
  const outboundLedgerPath = path.join(root, 'outbound-ledger.log')
  const denyProxyLedgerPath = path.join(root, 'deny-proxy.log')
  mkdirSync(artifactRoot)
  for (const [target, value] of [
    [providerPath, FAKE_LOCAL_PROVIDER_SOURCE],
    [backendPath, BACKEND_SOURCE],
    [denyProxyPath, DENY_PROXY_SOURCE],
    [providerLedgerPath, ''],
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
    providerPath,
    backendPath,
    denyProxyPath,
    viteConfigPath,
    browserResultPath,
    providerLedgerPath,
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
      else throw new Error('Phase4B3 artifact root contains a non-regular entry')
    }
  }
  visit(root)
  return files
}


function assertArtifactEvidenceSafe(roots, sensitiveValues) {
  for (const target of [
    ...artifactFiles(roots.artifactRoot),
    roots.providerLedgerPath,
    roots.outboundLedgerPath,
    roots.denyProxyLedgerPath,
    roots.browserResultPath,
  ].filter(existsSync)) {
    const text = readFileSync(target, 'utf8')
    assertNoPrivateEvidenceMarkers([text])
    if ([...sensitiveValues, ...GENERATED_TEXT_MARKERS].some(value => value && text.includes(value))) {
      throw new Error('Phase4B3 artifact contains sensitive evidence')
    }
  }
}


function assertProviderLedger(value) {
  const entries = String(value).split(/\r?\n/u).filter(Boolean)
  const expected = []
  for (let call = 1; call <= 4; call += 1) {
    expected.push(`call=${call}`, 'accepted-local-provider')
    expected.push(`terminal=${call === 3 ? 'transport-closed' : 'completed'}`)
  }
  if (JSON.stringify(entries) !== JSON.stringify(expected)) {
    throw new Error('Phase4B3 fake provider ledger did not match its closed contract')
  }
}


function readSafeBrowserDiagnostics(root, roots) {
  const fallback = { passed: 0, failed: 1, skipped: 0, failureLine: 0, failureColumn: 0 }
  try {
    const target = roots.browserResultPath
    const stats = lstatSync(target)
    if (
      stats.isSymbolicLink()
      || !stats.isFile()
      || stats.size < 1
      || stats.size > 2 * 1024 * 1024
      || realpathSync(target) !== realpathSync(path.join(assertOwnedRoot(root, OWNED_ROOT_PREFIX), 'browser-result.json'))
    ) return fallback
    const report = JSON.parse(readFileSync(target, 'utf8'))
    const counters = { passed: 0, failed: 0, skipped: 0, failureLine: 0, failureColumn: 0, digests: [] }
    const visit = suite => {
      for (const spec of Array.isArray(suite?.specs) ? suite.specs : []) {
        if (spec?.title !== '@selection-tools completes four local tools, preserves cancelled prose, and undoes once') continue
        for (const item of Array.isArray(spec.tests) ? spec.tests : []) {
          for (const result of Array.isArray(item?.results) ? item.results : []) {
            if (result?.status === 'passed') counters.passed += 1
            else if (result?.status === 'skipped') counters.skipped += 1
            else {
              counters.failed += 1
              if (counters.failureLine !== 0) continue
              for (const error of Array.isArray(result?.errors) ? result.errors : []) {
                for (const value of String(error?.message || '').match(/\b[0-9a-f]{64}\b/gu) || []) {
                  if (counters.digests.length < 4 && !counters.digests.includes(value)) {
                    counters.digests.push(value)
                  }
                }
                const location = error?.location
                if (
                  !Number.isSafeInteger(location?.line)
                  || location.line < 1
                  || typeof location.file !== 'string'
                ) continue
                const candidate = path.isAbsolute(location.file)
                  ? location.file
                  : path.resolve(repositoryRoot, location.file)
                if (realpathSync(candidate) !== realpathSync(formalSpecPath)) continue
                counters.failureLine = location.line
                counters.failureColumn = Number.isSafeInteger(location.column) && location.column > 0
                  ? location.column
                  : 0
                break
              }
            }
          }
        }
      }
      for (const nested of Array.isArray(suite?.suites) ? suite.suites : []) visit(nested)
    }
    for (const suite of Array.isArray(report?.suites) ? report.suites : []) visit(suite)
    return counters.failed > 0 ? counters : fallback
  } catch {
    return fallback
  }
}


function assertOutboundLedger(value) {
  const entries = String(value).split(/\r?\n/u).filter(Boolean)
  if (entries.length !== 4 || entries.some(item => item !== 'allowed-local-provider')) {
    throw new Error('Phase4B3 backend outbound ledger did not match the loopback-only contract')
  }
}


async function waitForPortRelease(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer().once('error', reject)
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => (
      probe.close(error => error ? reject(error) : resolve())
    ))
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
    if (residue.length !== 0) throw new Error('Phase4B3 owned Vite deps_temp residue was not zero')
  } catch (error) { errors.push(error) }
  try { assertArtifactEvidenceSafe(roots, sensitiveValues) } catch (error) { errors.push(error) }
  try {
    removeOwnedRoot(assertOwnedRoot(root, OWNED_ROOT_PREFIX), OWNED_ROOT_PREFIX)
    if (existsSync(root)) throw new Error('Phase4B3 owned temporary root remained')
  } catch (error) { errors.push(error) }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase4B3 root cleanup failed')
}


export function formatBrowserPassedSummary(passed) {
  if (passed !== 1) throw new Error('Phase4B3 scenario summary counters are invalid')
  return 'Phase4B3 browser: 1/1 scenarios passed'
}


export async function runPhase4B3({ environment = process.env, log = console.log, deadlines = {} } = {}) {
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
      for (let index = 0; index < 4; index += 1) {
        const reservation = lifecycle.registerReservation(await reserveLocalPort())
        reservations.push(reservation)
        ports.push(reservation.port)
      }
      if (new Set(ports).size !== 4) throw new Error('Phase4B3 runner received duplicate owned ports')
      const [providerPort, backendPort, denyPort, vitePort] = ports
      const providerUrl = `http://127.0.0.1:${providerPort}/v1`
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
        BROWSER_PROVIDER_BASE_URL: providerUrl,
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
        BROWSER_PROVIDER_LEDGER_PATH: roots.providerLedgerPath,
        BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, backendUrl]),
        BROWSER_DENY_PROXY_URL: denyUrl,
      }
      const sensitiveValues = runtimeSensitiveValues(browserEnvironment)
      const python = environment.PYTHON || 'python'
      const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')
      const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
      await runStage('database-preparation', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', databaseName], childOptions(repositoryRoot, cleanupEnvironment), { label: 'Phase4B3 database preparation', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs }))
      created = 1
      await runStage('canonical-fixture', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_phase4b3_browser_db', '--database', databaseName], childOptions(repositoryRoot, backendEnvironment), { label: 'Phase4B3 canonical fixture', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs }))
      const servers = []
      const start = async (stage, reservation, command, args, options, label, health) => runStage(stage, async () => {
        await lifecycle.releaseReservation(reservation)
        const server = lifecycle.registerServer(startOwnedServer(command, args, options, { label, sensitiveValues }))
        servers.push(server)
        await waitForOwnedServer(server, health, { expectedNonce: nonce, timeoutMs: limits.healthMs })
      })
      await start('fake-provider-start', reservations[0], process.execPath, [roots.providerPath, String(providerPort)], childOptions(repositoryRoot, { ...base, BROWSER_PROVIDER_LEDGER_PATH: roots.providerLedgerPath, BROWSER_SECRET_SENTINEL: SECRET_SENTINEL, M2_BROWSER_RUN_NONCE: nonce }), 'fake local provider', `http://127.0.0.1:${providerPort}/health`)
      await start('backend-start', reservations[1], python, ['-c', `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name='__main__')`, String(backendPort)], childOptions(repositoryRoot, backendEnvironment), 'backend', `${backendUrl}/api/health`)
      await start('deny-proxy-start', reservations[2], process.execPath, [roots.denyProxyPath, String(denyPort)], childOptions(repositoryRoot, { ...base, BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath, M2_BROWSER_RUN_NONCE: nonce }), 'deny proxy', `${denyUrl}/health`)
      await start('vite-start', reservations[3], process.execPath, [viteCli, '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], childOptions(frontendRoot, { ...base, NODE_ENV: 'test', VITE_API_BASE_URL: `${backendUrl}/api`, M2_BROWSER_RUN_NONCE: nonce }), 'vite', `${viteUrl}/__m2-browser-owner`)
      try {
        await runStage('browser-test', () => runBoundedOwnedCommand(process.execPath, [playwrightCli, 'test', `e2e/${FORMAL_SPECS[0]}`, '--config', `e2e/${FORMAL_CONFIG}`, '--grep', FORMAL_SCENARIO.tag], childOptions(frontendRoot, browserEnvironment), { label: 'Phase4B3 browser test', sensitiveValues, timeoutMs: limits.browserMs, stopTimeoutMs: limits.stopMs, states: servers }))
      } catch (error) {
        error.browserDiagnostics = readSafeBrowserDiagnostics(root, roots)
        throw error
      }
      await runStage('outbound-audit', async () => assertOutboundLedger(readFileSync(roots.outboundLedgerPath, 'utf8')))
      await runStage('deny-proxy-audit', async () => assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8')))
      await runStage('provider-ledger-audit', async () => assertProviderLedger(readFileSync(roots.providerLedgerPath, 'utf8')))
      await runStage('postcondition-verifier', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_phase4b3_browser_db', '--database', databaseName, '--verify-postconditions'], childOptions(repositoryRoot, backendEnvironment), { label: 'Phase4B3 verify-postconditions', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs, states: servers }))
    },
    stopServer: server => runStage('server-cleanup', () => stopOwnedServer(server, { timeoutMs: limits.stopMs })),
    releaseReservation: reservation => reservation.release(),
    async dropDatabase(name) {
      await runStage('database-cleanup', () => runBoundedOwnedCommand(environment.PYTHON || 'python', ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', name, '--drop'], childOptions(repositoryRoot, cleanupEnvironment), { label: 'Phase4B3 database cleanup', timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs }))
      cleaned = 1
    },
    removeRoot: root => runStage('root-cleanup', () => cleanupRoot(root, roots, ports, runtimeSensitiveValues({ ...environment, MYSQL_DB: databaseName, BROWSER_SECRET_SENTINEL: SECRET_SENTINEL }))),
  })
  assertDatabaseResidue(databaseName, databaseName, { created, cleaned, remaining: 0 })
  log('Phase4B3 selection-tools: scenario passed; DB/process/port/temp/artifact/Vite residue=0; real provider calls = 0; product DB reads/writes = 0/0')
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
    if (!value || (typeof value !== 'object' && typeof value !== 'function') || visited.has(value)) return
    visited.add(value)
    if (typeof value.phase4B3Stage === 'string') {
      counts.set(value.phase4B3Stage, (counts.get(value.phase4B3Stage) || 0) + 1)
    }
    if (!browserDiagnostics && value.browserDiagnostics) {
      browserDiagnostics = value.browserDiagnostics
    }
    if (value instanceof AggregateError) value.errors.forEach(visit)
    if (value.cause) visit(value.cause)
  }
  let browserDiagnostics = null
  visit(error)
  if (counts.size === 0) {
    const fallback = formatSafeLifecycleDiagnostics([{ category: 'lifecycle', error }])
    return JSON.stringify({ firstStage: 'lifecycle', errorCount: fallback.errorCount, stages: [{ stage: 'lifecycle', count: fallback.errorCount }] })
  }
  const stages = [...counts].map(([stage, count]) => ({ stage, count }))
  return JSON.stringify({ firstStage: stages[0].stage, errorCount: stages.reduce((total, item) => total + item.count, 0), stages, ...(browserDiagnostics ? { browser: browserDiagnostics } : {}) })
}


if ((() => {
  try { return samePathIdentity(realpathSync(process.argv[1]), realpathSync(fileURLToPath(import.meta.url))) } catch { return false }
})()) {
  runPhase4B3().then(status => { process.exitCode = status }).catch(error => {
    console.error(safeCliFailureSummary(error))
    process.exitCode = 1
  })
}

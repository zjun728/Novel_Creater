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
import { formatSafeLifecycleDiagnostics } from './support/safe-diagnostics.mjs'
import { assertNoPrivateEvidenceMarkers, runtimeSensitiveValues } from './runtime-observer.mjs'

export const FORMAL_SPECS = Object.freeze(['phase5-atomic-finalization.spec.ts'])
export const FORMAL_CONFIG = 'playwright.phase5.config.ts'
export const FORMAL_SCENARIO = Object.freeze({ tag: '@atomic-finalization' })
const OWNED_ROOT_PREFIX = 'novel-creator-phase5-'
const PROJECT_ID = '81000000-0000-0000-0000-000000000001'
const SECRET_SENTINEL = 'phase5-browser-secret-must-not-leak'
const BODY_MARKER = '夜雨压着城门。主角递上路引'
const DEFAULT_DEADLINES = Object.freeze({ commandMs: 90_000, healthMs: 45_000, browserMs: 180_000, stopMs: 8_000 })
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const SAFE_STAGES = new Set([
  'database-preparation', 'canonical-fixture', 'backend-start', 'deny-proxy-start',
  'vite-start', 'browser-test', 'outbound-audit', 'deny-proxy-audit',
  'postcondition-verifier', 'server-cleanup', 'database-cleanup', 'root-cleanup',
])

const BACKEND_SOURCE = String.raw`
import os, sys
from hashlib import sha256
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
from backend.domain.finalization import FinalizationChangeSet, QualityFinding
from backend.domain.routers import finalization
def evidence(prose):
    end = min(4, len(prose))
    return {'startScalar': 0, 'endScalar': end, 'excerptHash': sha256(prose[:end].encode()).hexdigest(), 'confidence': 1.0, 'rationale': '正文直接证据。'}
class FakeQuality:
    async def audit(self, *, provider, model_name, manifest):
        return (QualityFinding.model_validate({'id': 'phase5-finding', 'dimension': 'pacing', 'reason': '开场节奏可更紧凑。', 'suggestedAction': '压缩首段说明。', 'evidence': evidence(manifest.candidate_prose)}),)
class FakeExtraction:
    async def extract(self, *, provider, model_name, manifest):
        prose = manifest.candidate_prose
        planning = manifest.planning_context['content']
        plot, block = planning['plots'][0], planning['storyBlocks'][0]
        proof = evidence(prose)
        return FinalizationChangeSet.model_validate({
            'schemaVersion': 'finalization-changeset-v1', 'title': '第一章：入城',
            'summary': '主角通过盘查进入城中。', 'existingEntityIds': [],
            'entities': [{'id': '30000000-0000-4000-8000-000000000001', 'entityType': 'person', 'canonicalName': '守门人'}],
            'aliases': [{'id': '30000000-0000-4000-8000-000000000002', 'entityId': '30000000-0000-4000-8000-000000000001', 'alias': '老卒'}],
            'canonEvents': [{'id': '30000000-0000-4000-8000-000000000003', 'entityId': '30000000-0000-4000-8000-000000000001', 'factKind': 'dynamic_event', 'fieldPath': 'location', 'value': '城门', 'evidence': proof, 'effectiveStartChapter': 1, 'effectiveEndChapter': None, 'assertionOperator': 'equals', 'valueCardinality': 'single'}],
            'storyProgressEvents': [{'id': '30000000-0000-4000-8000-000000000004', 'targetType': 'story_block', 'targetId': block['id'], 'status': 'completed', 'evidence': proof}],
            'planningPatches': [{'id': '30000000-0000-4000-8000-000000000005', 'targetType': 'plot', 'targetId': plot['id'], 'expectedRevision': plot['revision'], 'expectedHash': plot['contentHash'], 'fieldPath': 'futureDirection', 'replacement': '追查城内接头人。', 'evidence': proof}],
            'planningSuggestions': [],
        })
finalization._service.quality_provider = FakeQuality()
finalization._service.extraction_provider = FakeExtraction()
from backend.main import app
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
`

const childOptions = (cwd, env) => ({ cwd, env, stdio: ['ignore', 'pipe', 'pipe'] })
const allowedEnvironment = environment => Object.fromEntries(BASE_ENV_ALLOWLIST
  .filter(key => Object.hasOwn(environment, key)).map(key => [key, environment[key]]))
const databaseEnvironment = (environment, databaseName) => ({
  ...allowedEnvironment(environment), TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
  TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT, TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
  TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD, BROWSER_TEST_DATABASE: databaseName,
})

function createRoots(root) {
  const roots = {
    artifactRoot: path.join(root, 'artifacts'), backendPath: path.join(root, 'backend.py'),
    denyProxyPath: path.join(root, 'deny-proxy.cjs'), viteConfigPath: path.join(root, 'vite.config.mjs'),
    browserResultPath: path.join(root, 'browser-result.json'), outboundLedgerPath: path.join(root, 'outbound-ledger.log'),
    denyProxyLedgerPath: path.join(root, 'deny-proxy.log'),
  }
  mkdirSync(roots.artifactRoot)
  for (const [target, value] of [[roots.backendPath, BACKEND_SOURCE], [roots.denyProxyPath, DENY_PROXY_SOURCE], [roots.outboundLedgerPath, ''], [roots.denyProxyLedgerPath, '']]) {
    writeFileSync(target, value, { encoding: 'utf8', flag: 'wx' })
  }
  const baseConfig = pathToFileURL(path.join(frontendRoot, 'vite.config.js')).href
  writeFileSync(roots.viteConfigPath, `import base from ${JSON.stringify(baseConfig)}\nexport default { ...base, cacheDir: ${JSON.stringify(path.join(root, 'vite-cache'))}, optimizeDeps: { ...base.optimizeDeps, noDiscovery: false } }\n`, { encoding: 'utf8', flag: 'wx' })
  return roots
}

function artifactFiles(root) {
  if (!existsSync(root)) return []
  const files = []
  const visit = directory => {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      const target = path.join(directory, entry.name)
      if (entry.isDirectory()) visit(target)
      else if (entry.isFile()) files.push(target)
      else throw new Error('Phase5 artifact root contains a non-regular entry')
    }
  }
  visit(root)
  return files
}

function assertArtifactEvidenceSafe(roots, sensitiveValues) {
  for (const target of [...artifactFiles(roots.artifactRoot), roots.outboundLedgerPath, roots.denyProxyLedgerPath, roots.browserResultPath].filter(existsSync)) {
    const value = readFileSync(target, 'utf8')
    assertNoPrivateEvidenceMarkers([value])
    if ([...sensitiveValues, BODY_MARKER].some(item => item && value.includes(item))) throw new Error('Phase5 artifact contains sensitive evidence')
  }
}

function classifyBrowserFailure(resultPath) {
  try {
    const report = JSON.parse(readFileSync(resultPath, 'utf8'))
    const values = []
    const visit = value => {
      if (!value || typeof value !== 'object') return
      if (typeof value.message === 'string') values.push(value.message)
      if (typeof value.stack === 'string') values.push(value.stack)
      for (const child of Object.values(value)) {
        if (Array.isArray(child)) child.forEach(visit)
        else if (child && typeof child === 'object') visit(child)
      }
    }
    visit(report)
    const joined = values.join('\n')
    const line = joined.match(/phase5-atomic-finalization\.spec\.ts:(\d+)/u)?.[1] || 'unknown'
    const reviewState = joined.match(/review-status-(awaiting_author|failed|invalidated|cancelled|committed)-blocks-([a-z_,]+|none)/u)?.[0]
    const kind = reviewState || (/strict mode violation/iu.test(joined) ? 'locator-strict'
      : /assertExactWrites/iu.test(joined) ? 'write-contract'
        : /timed out|timeout/iu.test(joined) ? 'timeout'
          : /locator/iu.test(joined) ? 'locator'
            : 'assertion')
    return `${kind}@${line}`
  } catch {
    return 'unclassified'
  }
}

async function waitForPortRelease(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer()
    const timeout = setTimeout(() => { probe.close(); reject(new Error('owned port remained bound')) }, 10_000)
    probe.once('error', error => { clearTimeout(timeout); reject(error) })
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => probe.close(error => {
      clearTimeout(timeout); if (error) reject(error); else resolve()
    }))
  })
}

async function cleanupRoot(root, roots, ports, sensitiveValues) {
  const errors = []
  for (const port of ports) try { await waitForPortRelease(port) } catch (error) { errors.push(error) }
  try {
    const cache = path.join(root, 'vite-cache')
    const residue = existsSync(cache) ? readdirSync(cache, { withFileTypes: true }).filter(entry => entry.isDirectory() && entry.name.startsWith('deps_temp_')) : []
    if (residue.length) throw new Error('Phase5 owned Vite deps_temp residue was not zero')
  } catch (error) { errors.push(error) }
  try { assertArtifactEvidenceSafe(roots, sensitiveValues) } catch (error) { errors.push(error) }
  try { removeOwnedRoot(assertOwnedRoot(root, OWNED_ROOT_PREFIX), OWNED_ROOT_PREFIX); if (existsSync(root)) throw new Error('Phase5 owned temporary root remained') } catch (error) { errors.push(error) }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase5 root cleanup failed')
}

async function runStage(stage, operation) {
  try { return await operation() } catch (cause) {
    const error = new Error('Phase5 stage failed', { cause }); error.phase5Stage = SAFE_STAGES.has(stage) ? stage : 'lifecycle'; throw error
  }
}

export function formatBrowserPassedSummary(passed) {
  if (passed !== 1) throw new Error('Phase5 scenario summary counters are invalid')
  return 'Phase5 browser: 1/1 scenarios passed'
}

export async function runPhase5({ environment = process.env, log = console.log, deadlines = {} } = {}) {
  validateTestEnvironment(environment)
  const limits = { ...DEFAULT_DEADLINES, ...deadlines }
  const databaseName = createDatabaseName(); assertDatabaseName(databaseName)
  const cleanupEnvironment = databaseEnvironment(environment, databaseName)
  const base = allowedEnvironment(environment)
  const ports = []; let roots = null; let created = 0; let cleaned = 0
  await runOwnedProductLifecycle({
    async body(lifecycle) {
      const root = lifecycle.setRoot(createOwnedRoot(OWNED_ROOT_PREFIX)); roots = createRoots(root); lifecycle.setDatabase(databaseName)
      const reservations = []
      for (let index = 0; index < 3; index += 1) { const reservation = lifecycle.registerReservation(await reserveLocalPort()); reservations.push(reservation); ports.push(reservation.port) }
      if (new Set(ports).size !== 3) throw new Error('Phase5 runner received duplicate owned ports')
      const [backendPort, denyPort, vitePort] = ports
      const backendUrl = `http://127.0.0.1:${backendPort}`; const denyUrl = `http://127.0.0.1:${denyPort}`; const viteUrl = `http://127.0.0.1:${vitePort}`
      const nonce = randomUUID()
      const backendEnvironment = {
        ...base, MYSQL_HOST: environment.TEST_MYSQL_HOST, MYSQL_PORT: environment.TEST_MYSQL_PORT,
        MYSQL_USER: environment.TEST_MYSQL_USER, MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
        MYSQL_DB: databaseName, BROWSER_TEST_DATABASE: databaseName, BROWSER_PROJECT_ID: PROJECT_ID,
        BROWSER_SECRET_SENTINEL: SECRET_SENTINEL, BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath,
        M2_BROWSER_RUN_NONCE: nonce, MARKET_SCHEDULER_ENABLED: 'false', SCHEDULER_ENABLED: '0',
      }
      const browserEnvironment = { ...backendEnvironment, PLAYWRIGHT_BASE_URL: viteUrl, BROWSER_OWNED_ROOT: root, BROWSER_ARTIFACT_ROOT: roots.artifactRoot, BROWSER_RESULT_PATH: roots.browserResultPath, BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, backendUrl]), BROWSER_DENY_PROXY_URL: denyUrl }
      const sensitiveValues = runtimeSensitiveValues(browserEnvironment)
      const python = environment.PYTHON || 'python'
      const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')
      const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
      await runStage('database-preparation', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', databaseName], childOptions(repositoryRoot, cleanupEnvironment), { label: 'Phase5 database preparation', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs }))
      created = 1
      await runStage('canonical-fixture', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_phase5_browser_db', '--database', databaseName], childOptions(repositoryRoot, backendEnvironment), { label: 'Phase5 canonical fixture', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs }))
      await lifecycle.releaseReservation(reservations[0])
      const backend = lifecycle.registerServer(startOwnedServer(python, ['-c', `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name='__main__')`, String(backendPort)], childOptions(repositoryRoot, backendEnvironment), { label: 'backend', sensitiveValues }))
      await runStage('backend-start', () => waitForOwnedServer(backend, `${backendUrl}/api/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs }))
      await lifecycle.releaseReservation(reservations[1])
      const denyProxy = lifecycle.registerServer(startOwnedServer(process.execPath, [roots.denyProxyPath, String(denyPort)], childOptions(repositoryRoot, { ...base, BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath, M2_BROWSER_RUN_NONCE: nonce }), { label: 'deny proxy', sensitiveValues }))
      await runStage('deny-proxy-start', () => waitForOwnedServer(denyProxy, `${denyUrl}/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs }))
      await lifecycle.releaseReservation(reservations[2])
      const vite = lifecycle.registerServer(startOwnedServer(process.execPath, [viteCli, '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'], childOptions(frontendRoot, { ...base, NODE_ENV: 'test', VITE_API_BASE_URL: `${backendUrl}/api`, M2_BROWSER_RUN_NONCE: nonce }), { label: 'vite', sensitiveValues }))
      await runStage('vite-start', () => waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, { expectedNonce: nonce, timeoutMs: limits.healthMs }))
      const servers = [backend, denyProxy, vite]
      await runStage('browser-test', async () => {
        try {
          return await runBoundedOwnedCommand(process.execPath, [playwrightCli, 'test', `e2e/${FORMAL_SPECS[0]}`, '--config', `e2e/${FORMAL_CONFIG}`, '--grep', FORMAL_SCENARIO.tag], childOptions(frontendRoot, browserEnvironment), { label: 'Phase5 browser test', sensitiveValues, timeoutMs: limits.browserMs, stopTimeoutMs: limits.stopMs, states: servers })
        } catch (error) {
          error.phase5BrowserCause = classifyBrowserFailure(roots.browserResultPath)
          throw error
        }
      })
      await runStage('outbound-audit', async () => { if (readFileSync(roots.outboundLedgerPath, 'utf8').trim()) throw new Error('Phase5 backend made an outbound request') })
      await runStage('deny-proxy-audit', async () => assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8')))
      await runStage('postcondition-verifier', () => runBoundedOwnedCommand(python, ['-m', 'backend.scripts.prepare_phase5_browser_db', '--database', databaseName, '--verify-postconditions'], childOptions(repositoryRoot, backendEnvironment), { label: 'Phase5 verify postconditions', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs, states: servers }))
    },
    stopServer: server => runStage('server-cleanup', () => stopOwnedServer(server, { timeoutMs: limits.stopMs })),
    releaseReservation: reservation => reservation.release(),
    async dropDatabase(name) { await runStage('database-cleanup', () => runBoundedOwnedCommand(environment.PYTHON || 'python', ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', name, '--drop'], childOptions(repositoryRoot, cleanupEnvironment), { label: 'Phase5 database cleanup', timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs })); cleaned = 1 },
    removeRoot: root => runStage('root-cleanup', () => cleanupRoot(root, roots, ports, runtimeSensitiveValues({ ...environment, MYSQL_DB: databaseName, BROWSER_SECRET_SENTINEL: SECRET_SENTINEL }))),
  })
  assertDatabaseResidue(databaseName, databaseName, { created, cleaned, remaining: 0 })
  log('Phase5 atomic finalization: scenario passed; DB/process/port/temp/artifact/Vite residue=0; injected fake quality/extraction providers; real provider calls = 0; product DB reads/writes = 0/0')
  log(formatBrowserPassedSummary(1))
  return 0
}

export function samePathIdentity(left, right) {
  const normalize = value => { const resolved = path.resolve(value); return process.platform === 'win32' ? resolved.toLowerCase() : resolved }
  return normalize(left) === normalize(right)
}

export function safeCliFailureSummary(error) {
  const counts = new Map(); const visited = new Set(); let browserCause = null
  const visit = value => { if (!value || typeof value !== 'object' || visited.has(value)) return; visited.add(value); if (typeof value.phase5Stage === 'string') counts.set(value.phase5Stage, (counts.get(value.phase5Stage) || 0) + 1); if (typeof value.phase5BrowserCause === 'string') browserCause ??= value.phase5BrowserCause; if (value instanceof AggregateError) value.errors.forEach(visit); if (value.cause) visit(value.cause) }
  visit(error)
  if (!counts.size) { const fallback = formatSafeLifecycleDiagnostics([{ category: 'lifecycle', error }]); return JSON.stringify({ firstStage: 'lifecycle', errorCount: fallback.errorCount }) }
  const stages = [...counts].map(([stage, count]) => ({ stage, count }))
  return JSON.stringify({ firstStage: stages[0].stage, errorCount: stages.reduce((total, item) => total + item.count, 0), browserCause, stages })
}

if ((() => { try { return samePathIdentity(realpathSync(process.argv[1]), realpathSync(fileURLToPath(import.meta.url))) } catch { return false } })()) {
  runPhase5().then(status => { process.exitCode = status }).catch(error => { console.error(safeCliFailureSummary(error)); process.exitCode = 1 })
}

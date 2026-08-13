import { randomUUID } from 'node:crypto'
import {
  existsSync, mkdirSync, readFileSync, readdirSync, realpathSync, statSync, writeFileSync,
} from 'node:fs'
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

export const FORMAL_SPECS = Object.freeze(['phase6b/project-backup.spec.mjs'])
export const FORMAL_CONFIG = 'playwright.phase6b.config.mjs'
const ROOT_PREFIX = 'novel-creator-phase6b-'
const PROJECT_ID = '81000000-0000-0000-0000-000000000001'
const SECRET_SENTINEL = 'phase6b-private-api-key-sentinel'
const BASE_URL_SENTINEL = 'https://phase6b-private.invalid/v1'
const WORKING_SENTINEL = 'PHASE6A_WORKING_SENTINEL'
const CANDIDATE_SENTINEL = 'PHASE6A_CANDIDATE_SENTINEL'
const consumerFailure = 'owned-response-consumer-close'
const DEFAULT_DEADLINES = Object.freeze({
  commandMs: 120_000, healthMs: 45_000, browserMs: 240_000, stopMs: 8_000,
})
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.resolve(frontend, '..')
const SAFE_STAGES = new Set([
  'database-preparation', 'fixture-preparation', 'backend-start', 'deny-proxy-start',
  'vite-start', 'browser-test', 'response-cleanup-audit', 'package-verifier',
  'outbound-audit', 'deny-proxy-audit', 'artifact-audit', 'postcondition-verifier',
  'server-cleanup', 'database-cleanup', 'root-cleanup',
])

// The test-only wrapper holds the real streaming response body while preserving
// the production router, repository, package service and cleanup callback.
const BACKEND_SOURCE = String.raw`
import asyncio, os, sys
from pathlib import Path
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
from backend.domain.routers import project_packages
project_packages.PROJECT_PACKAGE_TEMP_PARENT = Path(os.environ['PHASE6B_PACKAGE_TEMP_ROOT'])
real_stream_project_package = project_packages.stream_project_package
async def phase6b_held_project_package(path, cleanup):
    try:
        await asyncio.sleep(float(os.environ.get('PHASE6B_HOLD_BACKUP_SECONDS', '1.2')))
        async for chunk in real_stream_project_package(path, cleanup):
            yield chunk
    finally:
        cleanup()
project_packages.stream_project_package = phase6b_held_project_package
from backend.main import app
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
`

// This verifier is launched as an owned process. It parses the actual ZIP
// bytes saved by Playwright and emits no project or secret content.
const VERIFY_PACKAGE_SOURCE = String.raw`
import hashlib, json, os, pathlib, stat, sys, zipfile

archives = [pathlib.Path(value) for value in sys.argv[1:3]]
corpus_root = pathlib.Path(os.environ['MANAGED_CORPUS_ROOT'])
state_path = pathlib.Path(os.environ['PHASE6B_VERIFY_STATE_PATH'])
def checkpoint(value): state_path.write_text(str(value), encoding='ascii')
secret = os.environ['PHASE6B_VERIFY_SECRET'].encode()
base_url = os.environ['PHASE6B_VERIFY_BASE_URL'].encode()
working = os.environ['PHASE6B_VERIFY_WORKING'].encode()
candidate = os.environ['PHASE6B_VERIFY_CANDIDATE'].encode()
checkpoint(10)
blob_files = [item for item in corpus_root.rglob('*') if item.is_file()]
if len(blob_files) != 1: raise RuntimeError('owned corpus file count mismatch')
blob = blob_files[0].read_bytes()
blob_hash = hashlib.sha256(blob).hexdigest()
blob_path = 'corpus/blobs/sha256/' + blob_hash
payload_paths = [
    'assets/frozen.jsonl', 'corpus/revisions.jsonl', 'history/operations.jsonl',
    'history/providers.jsonl', 'project/graph.jsonl', 'validation/projections.json',
    blob_path,
]
expected_names = sorted(payload_paths + ['manifest.json', 'manifest.sha256'])

def records(package, name):
    raw = package.read(name)
    if not raw.endswith(b'\n'): raise RuntimeError('structured entry is not LF terminated')
    return [json.loads(line) for line in raw.splitlines()]

for index, archive in enumerate(archives):
    stage = 20 + index * 10
    checkpoint(stage)
    if not archive.is_file(): raise RuntimeError('browser download is missing')
    with zipfile.ZipFile(archive, 'r') as package:
        checkpoint(stage * 10 + 1)
        if package.comment != b'': raise RuntimeError('zip comment is not deterministic')
        infos = package.infolist()
        checkpoint(stage * 10 + 2)
        if [info.filename for info in infos] != expected_names: raise RuntimeError('zip entry order/set mismatch')
        for info in infos:
            checkpoint(stage * 10 + 3)
            if info.date_time != (1980, 1, 1, 0, 0, 0): raise RuntimeError('zip timestamp mismatch')
            checkpoint(stage * 10 + 4)
            if info.compress_type != zipfile.ZIP_STORED: raise RuntimeError('zip compression mismatch')
            checkpoint(stage * 10 + 5)
            if info.create_system != 3 or stat.S_IMODE(info.external_attr >> 16) != 0o600: raise RuntimeError('zip mode mismatch')
            checkpoint(stage * 10 + 6)
            if info.extra or info.comment or info.flag_bits & 0x08: raise RuntimeError('zip metadata mismatch')
        checkpoint(stage * 10 + 7)
        if package.read(blob_path) != blob: raise RuntimeError('corpus blob is incomplete')
        checkpoint(stage + 1)
        manifest_bytes = package.read('manifest.json')
        manifest = json.loads(manifest_bytes)
        if package.read('manifest.sha256') != hashlib.sha256(manifest_bytes).hexdigest().encode('ascii') + b'\n':
            raise RuntimeError('manifest hash mismatch')
        entries = manifest.get('entries')
        if [entry.get('path') for entry in entries] != sorted(payload_paths): raise RuntimeError('manifest entry order mismatch')
        for entry in entries:
            data = package.read(entry['path'])
            if entry.get('byteLength') != len(data) or entry.get('sha256') != hashlib.sha256(data).hexdigest():
                raise RuntimeError('manifest payload digest mismatch')
        if manifest.get('format') != 'novel-creator-project' or manifest.get('version') != 1:
            raise RuntimeError('manifest contract mismatch')
        graph = records(package, 'project/graph.jsonl')
        assets = records(package, 'assets/frozen.jsonl')
        corpus = records(package, 'corpus/revisions.jsonl')
        operations = records(package, 'history/operations.jsonl')
        providers = records(package, 'history/providers.jsonl')
        projections = json.loads(package.read('validation/projections.json'))
        graph_bytes = package.read('project/graph.jsonl')
        checkpoint(stage + 2)
        project = [record for record in graph if record.get('entityType') == 'project']
        project_data = project[0].get('data', {}) if len(project) == 1 else {}
        expected_revision = index
        expected_archived = index == 1
        if (len(project) != 1 or project_data.get('lifecycleRevision') != expected_revision
                or (project_data.get('archivedAt') is not None) != expected_archived):
            raise RuntimeError('project lifecycle snapshot mismatch')
        checkpoint(stage + 3)
        if working not in graph_bytes or candidate not in graph_bytes: raise RuntimeError('draft authority is absent')
        if not any(record.get('entityType') == 'final-chapter' for record in graph): raise RuntimeError('final chapter is absent')
        asset_types = {record.get('entityType') for record in assets}
        if not {'asset'} <= asset_types or len(assets) < 2: raise RuntimeError('frozen assets are absent')
        checkpoint(stage + 4)
        if not corpus or not operations or not providers or not isinstance(projections, dict) or not projections:
            raise RuntimeError('package evidence is incomplete')
        checkpoint(stage + 5)
        for name in expected_names:
            data = package.read(name)
            if secret in data or base_url in data: raise RuntimeError('referenced secret leaked')
`

const options = (cwd, env) => ({ cwd, env, stdio: ['ignore', 'pipe', 'pipe'] })
const allowed = environment => Object.fromEntries(
  BASE_ENV_ALLOWLIST.filter(key => Object.hasOwn(environment, key)).map(key => [key, environment[key]]),
)

function createRoots(owned) {
  const roots = {
    artifactRoot: path.join(owned, 'artifacts'), downloadRoot: path.join(owned, 'downloads'),
    corpusRoot: path.join(owned, 'corpus'), packageTempRoot: path.join(owned, 'package-temp'),
    backendPath: path.join(owned, 'backend.py'), verifierPath: path.join(owned, 'verify-package.py'),
    denyProxyPath: path.join(owned, 'deny-proxy.cjs'), viteConfigPath: path.join(owned, 'vite.config.mjs'),
    resultPath: path.join(owned, 'browser-result.json'),
    fixtureStatePath: path.join(owned, 'fixture-state.txt'),
    verifierStatePath: path.join(owned, 'verifier-state.txt'),
    outboundLedgerPath: path.join(owned, 'outbound-ledger.log'),
    denyProxyLedgerPath: path.join(owned, 'deny-proxy.log'),
  }
  for (const directory of [roots.artifactRoot, roots.downloadRoot, roots.corpusRoot, roots.packageTempRoot]) mkdirSync(directory)
  for (const [target, contents] of [
    [roots.backendPath, BACKEND_SOURCE], [roots.verifierPath, VERIFY_PACKAGE_SOURCE],
    [roots.denyProxyPath, DENY_PROXY_SOURCE], [roots.outboundLedgerPath, ''],
    [roots.denyProxyLedgerPath, ''],
  ]) writeFileSync(target, contents, { encoding: 'utf8', flag: 'wx' })
  writeFileSync(
    roots.viteConfigPath,
    `import base from ${JSON.stringify(pathToFileURL(path.join(frontend, 'vite.config.js')).href)}\nexport default { ...base, cacheDir: ${JSON.stringify(path.join(owned, 'vite-cache'))} }\n`,
    { encoding: 'utf8', flag: 'wx' },
  )
  return roots
}

function filesBelow(directory) {
  if (!existsSync(directory)) return []
  const result = []
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name)
    if (entry.isDirectory()) result.push(...filesBelow(target))
    else if (entry.isFile()) result.push(target)
    else throw new Error('Phase6B owned root contains a non-regular entry')
  }
  return result
}

function assertArtifactEvidenceSafe(roots, sensitiveValues) {
  const targets = [
    ...filesBelow(roots.artifactRoot), roots.resultPath,
    roots.outboundLedgerPath, roots.denyProxyLedgerPath,
  ].filter(existsSync)
  for (const target of targets) {
    const value = readFileSync(target, 'utf8')
    if (sensitiveValues.some(marker => marker && value.includes(marker))) {
      throw new Error('Phase6B log or artifact contains sensitive evidence')
    }
    if (/mysql(?:\+aiomysql)?:\/\//iu.test(value)) throw new Error('Phase6B log or artifact contains a DSN')
  }
}

async function waitForPortRelease(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer()
    const timeout = setTimeout(() => { probe.close(); reject(new Error('Phase6B owned port remained bound')) }, 10_000)
    probe.once('error', error => { clearTimeout(timeout); reject(error) })
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => probe.close(error => {
      clearTimeout(timeout)
      if (error) reject(error); else resolve()
    }))
  })
}

async function waitForPackageTempCleanup(packageTempRoot) {
  const deadline = Date.now() + 10_000
  while (Date.now() < deadline) {
    if (readdirSync(packageTempRoot).length === 0) return
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Phase6B package temp residue was not zero')
}

async function cleanupRoot(owned, roots, ports, sensitiveValues) {
  const errors = []
  for (const port of ports) try { await waitForPortRelease(port) } catch (error) { errors.push(error) }
  try {
    const cache = path.join(owned, 'vite-cache')
    const residue = existsSync(cache)
      ? readdirSync(cache, { withFileTypes: true }).filter(entry => entry.isDirectory() && entry.name.startsWith('deps_temp_'))
      : []
    if (residue.length) throw new Error('Phase6B owned Vite deps_temp residue was not zero')
    if (readdirSync(roots.packageTempRoot).length) throw new Error('Phase6B package temp residue was not zero')
    const downloads = readdirSync(roots.downloadRoot, { withFileTypes: true })
    if (downloads.length !== 2 || downloads.some(entry => !entry.isFile())) throw new Error('Phase6B download ledger mismatch')
    if (filesBelow(roots.corpusRoot).length !== 1) throw new Error('Phase6B corpus ledger mismatch')
    if (readFileSync(roots.outboundLedgerPath, 'utf8').trim()) throw new Error('Phase6B backend made an outbound request')
    assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8'))
    assertArtifactEvidenceSafe(roots, sensitiveValues)
  } catch (error) { errors.push(error) }
  try {
    removeOwnedRoot(assertOwnedRoot(owned, ROOT_PREFIX), ROOT_PREFIX)
    if (existsSync(owned)) throw new Error('Phase6B owned root remained')
  } catch (error) { errors.push(error) }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase6B root cleanup failed')
}

async function runStage(stage, action) {
  try { return await action() } catch (cause) {
    const error = new Error('Phase6B stage failed', { cause })
    error.phase6bStage = SAFE_STAGES.has(stage) ? stage : 'lifecycle'
    throw error
  }
}

function reportErrors(report) {
  const found = []
  const visit = value => {
    if (Array.isArray(value)) { value.forEach(visit); return }
    if (!value || typeof value !== 'object') return
    if (Array.isArray(value.errors)) {
      for (const error of value.errors) if (error && typeof error.message === 'string') found.push(error)
    }
    for (const child of Object.values(value)) visit(child)
  }
  visit(report)
  return found
}

function browserErrorLine(error) {
  if (error.location?.file?.endsWith('project-backup.spec.mjs') && Number.isInteger(error.location.line)) {
    return String(error.location.line)
  }
  return error.stack?.match(/project-backup\.spec\.mjs:(\d+):\d+/u)?.[1] || 'unknown'
}

export function classifyBrowserFailure(resultPath) {
  try {
    const errors = reportErrors(JSON.parse(readFileSync(resultPath, 'utf8')))
    const error = errors[0]
    if (!error) return 'unclassified'
    const line = browserErrorLine(error)
    const status = error.message.match(/backup-status-(\d{3})/u)?.[1]
    if (status) return `backup-status-${status}`
    const libraryMarker = error.message.match(/phase6b-library-(?:load-error|empty|card-missing)/u)?.[0]
    if (libraryMarker) return libraryMarker
    if (/locator\.click/iu.test(error.message) && /timed out|timeout/iu.test(error.message)) {
      if (/intercepts pointer events/iu.test(error.message)) return `locator-intercepted@${line}`
      if (/element is not enabled|disabled/iu.test(error.message)) return `locator-disabled@${line}`
      if (/element is not visible/iu.test(error.message)) return `locator-hidden@${line}`
      if (!/locator resolved to/iu.test(error.message)) return `locator-missing@${line}`
      return `locator-timeout@${line}`
    }
    return `${/timed out|timeout/iu.test(error.message) ? 'timeout' : /locator/iu.test(error.message) ? 'locator' : 'assertion'}@${line}`
  } catch { return 'unclassified' }
}

export function safeClassifyFailure(error) {
  const stages = []
  let browserCause = null
  let fixtureCause = null
  let verifierCause = null
  const visit = value => {
    if (!value || typeof value !== 'object') return
    if (typeof value.phase6bStage === 'string') stages.push(value.phase6bStage)
    if (typeof value.phase6bBrowserCause === 'string') browserCause ||= value.phase6bBrowserCause
    if (typeof value.phase6bFixtureCause === 'string') fixtureCause ||= value.phase6bFixtureCause
    if (typeof value.phase6bVerifierCause === 'string') verifierCause ||= value.phase6bVerifierCause
    if (typeof value.message === 'string') {
      if (/status 61/u.test(value.message)) fixtureCause ||= 'preparation-snapshot-timeout'
      if (/status 62/u.test(value.message)) fixtureCause ||= 'contract-head-timeout'
      if (/status 63/u.test(value.message)) fixtureCause ||= 'preparation-service-timeout'
    }
    if (value.cause) visit(value.cause)
    if (value instanceof AggregateError) value.errors.forEach(visit)
  }
  visit(error)
  return JSON.stringify({ firstStage: stages[0] || 'lifecycle', errorCount: Math.max(stages.length, 1), browserCause, fixtureCause, verifierCause })
}

export async function runPhase6B({ environment = process.env, log = console.log, deadlines = {} } = {}) {
  validateTestEnvironment(environment)
  const limits = { ...DEFAULT_DEADLINES, ...deadlines }
  const database = createDatabaseName(); assertDatabaseName(database)
  const base = allowed(environment)
  const ports = []
  let roots = null
  let created = 0
  let cleaned = 0
  const mysql = {
    ...base,
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST, TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER, TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_HOST: environment.TEST_MYSQL_HOST, MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER, MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: database, BROWSER_TEST_DATABASE: database,
  }
  const sensitiveValues = [
    environment.TEST_MYSQL_PASSWORD, SECRET_SENTINEL, BASE_URL_SENTINEL, WORKING_SENTINEL,
  ].filter(Boolean)

  await runOwnedProductLifecycle({
    async body(lifecycle) {
      const owned = lifecycle.setRoot(createOwnedRoot(ROOT_PREFIX))
      roots = createRoots(owned)
      lifecycle.setDatabase(database)
      const reservations = []
      for (let index = 0; index < 3; index += 1) {
        const reservation = lifecycle.registerReservation(await reserveLocalPort())
        reservations.push(reservation); ports.push(reservation.port)
      }
      if (new Set(ports).size !== 3) throw new Error('Phase6B owned ports are not unique')
      const [apiPort, denyPort, vitePort] = ports
      const apiUrl = `http://127.0.0.1:${apiPort}`
      const denyUrl = `http://127.0.0.1:${denyPort}`
      const viteUrl = `http://127.0.0.1:${vitePort}`
      const nonce = randomUUID()
      const python = environment.PYTHON || 'python'
      const backendEnvironment = {
        ...mysql, BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath,
        M2_BROWSER_RUN_NONCE: nonce, SCHEDULER_ENABLED: '0', MARKET_SCHEDULER_ENABLED: 'false',
        MANAGED_CORPUS_ROOT: roots.corpusRoot, PHASE6B_PACKAGE_TEMP_ROOT: roots.packageTempRoot,
        PHASE6B_HOLD_BACKUP_SECONDS: '1.2', PHASE6B_FIXTURE_STATE_PATH: roots.fixtureStatePath,
      }
      const browserEnvironment = {
        ...mysql, PLAYWRIGHT_BASE_URL: viteUrl, BROWSER_PROJECT_ID: PROJECT_ID,
        BROWSER_OWNED_ROOT: owned, BROWSER_ARTIFACT_ROOT: roots.artifactRoot,
        BROWSER_DOWNLOAD_ROOT: roots.downloadRoot, BROWSER_CORPUS_ROOT: roots.corpusRoot,
        BROWSER_PACKAGE_TEMP_ROOT: roots.packageTempRoot, BROWSER_RESULT_PATH: roots.resultPath,
        BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, apiUrl]), BROWSER_DENY_PROXY_URL: denyUrl,
      }
      const verifierEnvironment = {
        ...backendEnvironment, PHASE6B_VERIFY_SECRET: SECRET_SENTINEL,
        PHASE6B_VERIFY_BASE_URL: BASE_URL_SENTINEL, PHASE6B_VERIFY_WORKING: WORKING_SENTINEL,
        PHASE6B_VERIFY_CANDIDATE: CANDIDATE_SENTINEL, PHASE6B_VERIFY_STATE_PATH: roots.verifierStatePath,
      }

      await runStage('database-preparation', () => runBoundedOwnedCommand(
        python, ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', database],
        options(root, mysql), { label: 'Phase6B database preparation', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs },
      )); created = 1
      await runStage('fixture-preparation', async () => {
        try {
          return await runBoundedOwnedCommand(
            python, ['-m', 'backend.scripts.prepare_phase6b_browser_db', '--database', database],
            options(root, backendEnvironment), { label: 'Phase6B fixture preparation', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs },
          )
        } catch (error) {
          const code = existsSync(roots.fixtureStatePath) ? readFileSync(roots.fixtureStatePath, 'ascii').trim() : ''
          error.phase6bFixtureCause = ({
            61: 'preparation-snapshot-timeout', 62: 'contract-head-timeout', 63: 'preparation-service-timeout',
            10: 'preparation-snapshot-entered', 11: 'contract-head-entered', 12: 'preparation-transaction-exit',
            20: 'preparation-service-entered', 21: 'preparation-service-complete',
          })[code] || null
          throw error
        }
      })
      await lifecycle.releaseReservation(reservations[0])
      const backend = lifecycle.registerServer(startOwnedServer(
        python, ['-c', `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name='__main__')`, String(apiPort)],
        options(root, backendEnvironment), { label: 'Phase6B API', sensitiveValues },
      ))
      await runStage('backend-start', () => waitForOwnedServer(backend, `${apiUrl}/api/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs }))
      await lifecycle.releaseReservation(reservations[1])
      const deny = lifecycle.registerServer(startOwnedServer(
        process.execPath, [roots.denyProxyPath, String(denyPort)],
        options(root, { ...base, BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath, M2_BROWSER_RUN_NONCE: nonce }),
        { label: 'Phase6B deny proxy', sensitiveValues },
      ))
      await runStage('deny-proxy-start', () => waitForOwnedServer(deny, `${denyUrl}/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs }))
      await lifecycle.releaseReservation(reservations[2])
      const vite = lifecycle.registerServer(startOwnedServer(
        process.execPath,
        [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'],
        options(frontend, { ...base, VITE_API_BASE_URL: `${apiUrl}/api`, M2_BROWSER_RUN_NONCE: nonce }),
        { label: 'Phase6B Vite', sensitiveValues },
      ))
      await runStage('vite-start', () => waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, { expectedNonce: nonce, timeoutMs: limits.healthMs }))
      const servers = [backend, deny, vite]
      await runStage('browser-test', async () => {
        try {
          return await runBoundedOwnedCommand(
            process.execPath,
            [path.join(frontend, 'node_modules', 'playwright', 'cli.js'), 'test', `e2e/${FORMAL_SPECS[0]}`, '--config', `e2e/${FORMAL_CONFIG}`],
            options(frontend, browserEnvironment),
            { label: 'Phase6B browser test', sensitiveValues, timeoutMs: limits.browserMs, stopTimeoutMs: limits.stopMs, states: servers },
          )
        } catch (error) {
          error.phase6bBrowserCause = classifyBrowserFailure(roots.resultPath)
          throw error
        }
      })
      await runStage('response-cleanup-audit', () => waitForPackageTempCleanup(roots.packageTempRoot))
      const archives = ['active-project-backup.zip', 'archived-project-backup.zip'].map(name => path.join(roots.downloadRoot, name))
      if (archives.some(target => !existsSync(target) || !statSync(target).isFile())) throw new Error('Phase6B saved download is missing')
      await runStage('package-verifier', async () => {
        try {
          return await runBoundedOwnedCommand(
            python, [roots.verifierPath, ...archives], options(root, verifierEnvironment),
            { label: 'Phase6B package verifier', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs, states: servers },
          )
        } catch (error) {
          const code = existsSync(roots.verifierStatePath) ? readFileSync(roots.verifierStatePath, 'ascii').trim() : ''
          error.phase6bVerifierCause = ({
            10: 'corpus-envelope', 20: 'active-zip-envelope', 21: 'active-manifest',
            201: 'active-zip-comment', 202: 'active-entry-set', 203: 'active-zip-timestamp',
            204: 'active-zip-compression', 205: 'active-zip-mode', 206: 'active-zip-metadata', 207: 'active-corpus-blob',
            22: 'active-lifecycle', 23: 'active-authority', 24: 'active-evidence', 25: 'active-secret-scan',
            30: 'archived-zip-envelope', 31: 'archived-manifest', 32: 'archived-lifecycle',
            301: 'archived-zip-comment', 302: 'archived-entry-set', 303: 'archived-zip-timestamp',
            304: 'archived-zip-compression', 305: 'archived-zip-mode', 306: 'archived-zip-metadata', 307: 'archived-corpus-blob',
            33: 'archived-authority', 34: 'archived-evidence', 35: 'archived-secret-scan',
          })[code] || null
          throw error
        }
      })
      await runStage('outbound-audit', () => {
        if (readFileSync(roots.outboundLedgerPath, 'utf8').trim()) throw new Error('Phase6B backend made an outbound request')
      })
      await runStage('deny-proxy-audit', () => assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8')))
      await runStage('artifact-audit', () => assertArtifactEvidenceSafe(roots, sensitiveValues))
      await runStage('postcondition-verifier', () => runBoundedOwnedCommand(
        python, ['-m', 'backend.scripts.prepare_phase6b_browser_db', '--database', database, '--verify-postconditions'],
        options(root, backendEnvironment), { label: 'Phase6B postcondition verifier', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs, states: servers },
      ))
    },
    stopServer: server => runStage('server-cleanup', () => stopOwnedServer(server, { sensitiveValues, timeoutMs: limits.stopMs })),
    releaseReservation: reservation => reservation.release(),
    async dropDatabase(name) {
      await runStage('database-cleanup', () => runBoundedOwnedCommand(
        environment.PYTHON || 'python', ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', name, '--drop'],
        options(root, mysql), { label: 'Phase6B database cleanup', sensitiveValues, timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs },
      )); cleaned = 1
    },
    removeRoot: owned => runStage('root-cleanup', () => cleanupRoot(owned, roots, ports, sensitiveValues)),
  })
  assertDatabaseResidue(database, database, { created, cleaned, remaining: 0 })
  log(`Phase6B browser: 1/1 scenarios passed; consumerFailure=${consumerFailure}; DB/process/ports/temp/corpus/download/artifact/Vite residue=0; outbound/provider calls=0; product DB reads/writes=0/0`)
  return 0
}

if ((() => {
  try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)) } catch { return false }
})()) {
  runPhase6B().then(value => { process.exitCode = value }).catch(error => {
    console.error(safeClassifyFailure(error)); process.exitCode = 1
  })
}

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

export const FORMAL_SPECS = Object.freeze(['phase6c/project-import.spec.mjs'])
export const FORMAL_CONFIG = 'playwright.phase6c.config.mjs'
const ROOT_PREFIX = 'novel-creator-phase6c-'
const PROJECT_ID = '81000000-0000-0000-0000-000000000001'
const SECRET_SENTINEL = 'phase6b-private-api-key-sentinel'
const BASE_URL_SENTINEL = 'https://phase6b-private.invalid/v1'
const consumerFailure = 'owned-import-response-close-after-publication'
const DEFAULT_DEADLINES = Object.freeze({
  commandMs: 180_000, healthMs: 45_000, browserMs: 300_000, stopMs: 8_000,
})
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.resolve(frontend, '..')
const SAFE_STAGES = new Set([
  'database-preparation', 'fixture-preparation', 'backend-start', 'deny-proxy-start',
  'vite-start', 'browser-test', 'response-cleanup-audit', 'outbound-audit',
  'deny-proxy-audit', 'artifact-audit', 'postcondition-verifier', 'server-cleanup',
  'database-cleanup', 'root-cleanup',
])

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
from backend.routers import project_imports, project_packages
project_packages.PROJECT_PACKAGE_TEMP_PARENT = Path(os.environ['PHASE6C_PACKAGE_TEMP_ROOT'])
project_imports.PROJECT_IMPORT_TEMP_PARENT = Path(os.environ['PHASE6C_IMPORT_QUARANTINE_ROOT'])
from backend.services.project_imports import ProjectImportService
real_import_project = ProjectImportService.import_project
phase6c_import_held = False
async def phase6c_held_import(self, upload, request):
    global phase6c_import_held
    result = await real_import_project(self, upload, request)
    if not phase6c_import_held:
        phase6c_import_held = True
        Path(os.environ['PHASE6C_PUBLICATION_MARKER']).write_text('published', encoding='ascii')
        await asyncio.sleep(float(os.environ.get('PHASE6C_HOLD_IMPORT_SECONDS', '0.4')))
        raise asyncio.CancelledError()
    return result
ProjectImportService.import_project = phase6c_held_import
from backend.main import app
uvicorn.run(app, host='127.0.0.1', port=int(sys.argv[1]), log_level='warning')
`

const options = (cwd, env) => ({ cwd, env, stdio: ['ignore', 'pipe', 'pipe'] })
const allowed = environment => Object.fromEntries(
  BASE_ENV_ALLOWLIST
    .filter(key => Object.hasOwn(environment, key))
    .map(key => [key, environment[key]]),
)

function createRoots(owned) {
  const roots = {
    artifactRoot: path.join(owned, 'artifacts'),
    downloadRoot: path.join(owned, 'downloads'),
    corpusRoot: path.join(owned, 'corpus'),
    packageTempRoot: path.join(owned, 'package-temp'),
    quarantineRoot: path.join(owned, 'import-quarantine'),
    backendPath: path.join(owned, 'backend.py'),
    denyProxyPath: path.join(owned, 'deny-proxy.cjs'),
    viteConfigPath: path.join(owned, 'vite.config.mjs'),
    resultPath: path.join(owned, 'browser-result.json'),
    baselinePath: path.join(owned, 'baseline.json'),
    publicationMarkerPath: path.join(owned, 'publication.marker'),
    outboundLedgerPath: path.join(owned, 'outbound-ledger.log'),
    denyProxyLedgerPath: path.join(owned, 'deny-proxy.log'),
  }
  for (const directory of [
    roots.artifactRoot, roots.downloadRoot, roots.corpusRoot,
    roots.packageTempRoot, roots.quarantineRoot,
  ]) mkdirSync(directory)
  for (const [target, contents] of [
    [roots.backendPath, BACKEND_SOURCE],
    [roots.denyProxyPath, DENY_PROXY_SOURCE],
    [roots.outboundLedgerPath, ''],
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
  const files = []
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name)
    if (entry.isDirectory()) files.push(...filesBelow(target))
    else if (entry.isFile()) files.push(target)
    else throw new Error('Phase6C owned root contains a non-regular entry')
  }
  return files
}

function assertArtifactEvidenceSafe(roots, sensitiveValues) {
  const targets = [
    ...filesBelow(roots.artifactRoot), roots.resultPath,
    roots.outboundLedgerPath, roots.denyProxyLedgerPath,
  ].filter(existsSync)
  for (const target of targets) {
    const value = readFileSync(target, 'utf8')
    if (sensitiveValues.some(marker => marker && value.includes(marker))) {
      throw new Error('Phase6C log or artifact contains sensitive evidence')
    }
    if (/mysql(?:\+aiomysql)?:\/\//iu.test(value)) {
      throw new Error('Phase6C log or artifact contains a DSN')
    }
  }
}

async function waitForPortRelease(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer()
    const timer = setTimeout(() => {
      probe.close()
      reject(new Error('Phase6C owned port remained bound'))
    }, 10_000)
    probe.once('error', error => { clearTimeout(timer); reject(error) })
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => probe.close(error => {
      clearTimeout(timer)
      if (error) reject(error)
      else resolve()
    }))
  })
}

async function waitForEmptyRoots(roots) {
  const deadline = Date.now() + 15_000
  const stagingRoot = path.join(roots.corpusRoot, '.project-import-staging')
  while (Date.now() < deadline) {
    if (
      readdirSync(roots.packageTempRoot).length === 0
      && readdirSync(roots.quarantineRoot).length === 0
      && (!existsSync(stagingRoot) || filesBelow(stagingRoot).length === 0)
    ) return
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Phase6C package/quarantine/project-import-staging residue was not zero')
}

async function cleanupRoot(owned, roots, ports, sensitiveValues) {
  const errors = []
  for (const port of ports) {
    try { await waitForPortRelease(port) } catch (error) { errors.push(error) }
  }
  try {
    const cache = path.join(owned, 'vite-cache')
    const dependencyTemps = existsSync(cache)
      ? readdirSync(cache, { withFileTypes: true })
        .filter(entry => entry.isDirectory() && entry.name.startsWith('deps_temp_'))
      : []
    if (dependencyTemps.length) throw new Error('Phase6C owned Vite deps_temp_ residue was not zero')
    if (readdirSync(roots.packageTempRoot).length) throw new Error('Phase6C package temp residue was not zero')
    if (readdirSync(roots.quarantineRoot).length) throw new Error('Phase6C quarantine residue was not zero')
    const stagingRoot = path.join(roots.corpusRoot, '.project-import-staging')
    if (existsSync(stagingRoot) && filesBelow(stagingRoot).length) {
      throw new Error('Phase6C project-import-staging residue was not zero')
    }
    const downloads = readdirSync(roots.downloadRoot, { withFileTypes: true })
    if (downloads.length !== 2 || downloads.some(entry => !entry.isFile())) {
      throw new Error('Phase6C download ledger mismatch')
    }
    if (filesBelow(roots.corpusRoot).length !== 1) throw new Error('Phase6C corpus ledger mismatch')
    if (!existsSync(roots.publicationMarkerPath)
      || readFileSync(roots.publicationMarkerPath, 'ascii') !== 'published') {
      throw new Error('Phase6C publication response failure was not injected')
    }
    if (readFileSync(roots.outboundLedgerPath, 'utf8').trim()) {
      throw new Error('Phase6C backend made an outbound request')
    }
    assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8'))
    assertArtifactEvidenceSafe(roots, sensitiveValues)
  } catch (error) { errors.push(error) }
  try {
    removeOwnedRoot(assertOwnedRoot(owned, ROOT_PREFIX), ROOT_PREFIX)
    if (existsSync(owned)) throw new Error('Phase6C owned root remained')
  } catch (error) { errors.push(error) }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase6C root cleanup failed')
}

async function runStage(stage, action) {
  try { return await action() } catch (cause) {
    const error = new Error('Phase6C stage failed', { cause })
    error.phase6cStage = SAFE_STAGES.has(stage) ? stage : 'lifecycle'
    throw error
  }
}

function failureEvidence(value, output = []) {
  if (!value || typeof value !== 'object') return output
  if (Array.isArray(value)) {
    for (const item of value) failureEvidence(item, output)
    return output
  }
  for (const [key, child] of Object.entries(value)) {
    if (key === 'error' || key === 'errors') output.push(JSON.stringify(child))
    else if (key !== 'config') failureEvidence(child, output)
  }
  return output
}

export function classifyBrowserFailureResult(result) {
  try {
    const rendered = failureEvidence(result).join('\n')
    const line = rendered.match(/project-import\.spec\.mjs:(\d+)/u)?.[1]
      || rendered.match(/project-import\.spec\.mjs[^}]{0,120}"line":(\d+)/u)?.[1]
      || 'unknown'
    const preflightStatus = rendered.match(/actual[^0-9]{0,40}(\d{3})/iu)?.[1]
    if (rendered.includes('preflight response must succeed')) {
      return `preflight-status-${preflightStatus || 'absent'}@${line}`
    }
    const diagnostic = rendered.match(
      /phase6c-import-diagnostic postCount=(\d+) postCategories=([a-z+-]+) getCount=(\d+) getCategories=([a-z+-]+) visible=([a-z-]+)/u,
    )
    if (diagnostic) {
      return `timeout@${line};post=${diagnostic[1]}:${diagnostic[2]};get=${diagnostic[3]}:${diagnostic[4]};visible=${diagnostic[5]}`
    }
    const runtimeCategory = rendered.match(
      /runtime-(console-(?:locationlessNetwork|otherResourceNetwork|frameworkOrPageError|other)-(?:adjacent|notAdjacent)|expected-cors-network-console|request-failures|non2xx|origin-violations|pending-requests|listeners|page-errors)-count-(\d+|invalid)/u,
    )
    if (runtimeCategory) return `runtime-${runtimeCategory[1]}-count-${runtimeCategory[2]}@${line}`
    return `${/timed out|timeout/iu.test(rendered) ? 'timeout' : /locator/iu.test(rendered) ? 'locator' : 'assertion'}@${line}`
  } catch { return 'unclassified' }
}

function classifyBrowserFailure(resultPath) {
  try { return classifyBrowserFailureResult(JSON.parse(readFileSync(resultPath, 'utf8'))) }
  catch { return 'unclassified' }
}

export function safeClassifyFailure(error) {
  const stages = []
  let browserCause = null
  let fixtureCause = null
  const visit = value => {
    if (!value || typeof value !== 'object') return
    if (typeof value.phase6cStage === 'string') stages.push(value.phase6cStage)
    if (typeof value.phase6cBrowserCause === 'string') browserCause ||= value.phase6cBrowserCause
    if (typeof value.phase6cFixtureCause === 'string') fixtureCause ||= value.phase6cFixtureCause
    if (value.cause) visit(value.cause)
    if (value instanceof AggregateError) value.errors.forEach(visit)
  }
  visit(error)
  return JSON.stringify({
    firstStage: stages[0] || 'lifecycle',
    errorCount: Math.max(stages.length, 1),
    browserCause,
    fixtureCause,
  })
}

export async function runPhase6C({ environment = process.env, log = console.log, deadlines = {} } = {}) {
  validateTestEnvironment(environment)
  const limits = { ...DEFAULT_DEADLINES, ...deadlines }
  const database = createDatabaseName()
  assertDatabaseName(database)
  const base = allowed(environment)
  const ports = []
  let roots = null
  let created = 0
  let cleaned = 0
  const mysql = {
    ...base,
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
    TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
    TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: database,
    BROWSER_TEST_DATABASE: database,
  }
  const sensitiveValues = [
    environment.TEST_MYSQL_PASSWORD, SECRET_SENTINEL, BASE_URL_SENTINEL,
  ].filter(Boolean)

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
      if (new Set(ports).size !== 3) throw new Error('Phase6C owned ports are not unique')
      const [apiPort, denyPort, vitePort] = ports
      const apiUrl = `http://127.0.0.1:${apiPort}`
      const denyUrl = `http://127.0.0.1:${denyPort}`
      const viteUrl = `http://127.0.0.1:${vitePort}`
      const nonce = randomUUID()
      const python = environment.PYTHON || 'python'
      const backupPath = path.join(roots.downloadRoot, 'phase6c-import-source.zip')
      const finalPath = path.join(roots.downloadRoot, 'phase6c-imported-finalized.txt')
      const backendEnvironment = {
        ...mysql,
        BROWSER_OWNED_ROOT: owned,
        BROWSER_DOWNLOAD_ROOT: roots.downloadRoot,
        BROWSER_RESULT_PATH: roots.resultPath,
        BROWSER_OUTBOUND_LEDGER_PATH: roots.outboundLedgerPath,
        M2_BROWSER_RUN_NONCE: nonce,
        SCHEDULER_ENABLED: '0',
        MARKET_SCHEDULER_ENABLED: 'false',
        MANAGED_CORPUS_ROOT: roots.corpusRoot,
        PHASE6B_FIXTURE_STATE_PATH: path.join(owned, 'phase6b-fixture-state.txt'),
        PHASE6C_PACKAGE_TEMP_ROOT: roots.packageTempRoot,
        PHASE6C_IMPORT_QUARANTINE_ROOT: roots.quarantineRoot,
        PHASE6C_PUBLICATION_MARKER: roots.publicationMarkerPath,
        PHASE6C_HOLD_IMPORT_SECONDS: '0.4',
        PHASE6C_BASELINE_PATH: roots.baselinePath,
        PHASE6C_BACKUP_PATH: backupPath,
        PHASE6C_FINAL_PATH: finalPath,
      }
      const browserEnvironment = {
        ...mysql,
        PLAYWRIGHT_BASE_URL: viteUrl,
        BROWSER_PROJECT_ID: PROJECT_ID,
        BROWSER_OWNED_ROOT: owned,
        BROWSER_ARTIFACT_ROOT: roots.artifactRoot,
        BROWSER_DOWNLOAD_ROOT: roots.downloadRoot,
        BROWSER_CORPUS_ROOT: roots.corpusRoot,
        BROWSER_PACKAGE_TEMP_ROOT: roots.packageTempRoot,
        BROWSER_IMPORT_QUARANTINE_ROOT: roots.quarantineRoot,
        BROWSER_RESULT_PATH: roots.resultPath,
        BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, apiUrl]),
        BROWSER_DENY_PROXY_URL: denyUrl,
      }

      await runStage('database-preparation', () => runBoundedOwnedCommand(
        python,
        ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', database],
        options(root, mysql),
        {
          label: 'Phase6C database preparation', sensitiveValues,
          timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs,
        },
      ))
      created = 1
      await runStage('fixture-preparation', async () => {
        try {
          await runBoundedOwnedCommand(
            python,
            ['-m', 'backend.scripts.prepare_phase6c_browser_db', '--database', database],
            options(root, backendEnvironment),
            {
              label: 'Phase6C fixture preparation', sensitiveValues,
              timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs,
            },
          )
        } catch (error) {
          try {
            const result = JSON.parse(readFileSync(roots.resultPath, 'utf8'))
            if (typeof result.fixtureCause === 'string') error.phase6cFixtureCause = result.fixtureCause
          } catch {}
          throw error
        }
      })

      await lifecycle.releaseReservation(reservations[0])
      const backend = lifecycle.registerServer(startOwnedServer(
        python,
        ['-c', `import runpy; runpy.run_path(${JSON.stringify(roots.backendPath)}, run_name='__main__')`, String(apiPort)],
        options(root, backendEnvironment),
        { label: 'Phase6C API', sensitiveValues },
      ))
      await runStage('backend-start', () => waitForOwnedServer(
        backend, `${apiUrl}/api/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs },
      ))

      await lifecycle.releaseReservation(reservations[1])
      const deny = lifecycle.registerServer(startOwnedServer(
        process.execPath,
        [roots.denyProxyPath, String(denyPort)],
        options(root, {
          ...base,
          BROWSER_DENY_PROXY_LEDGER_PATH: roots.denyProxyLedgerPath,
          M2_BROWSER_RUN_NONCE: nonce,
        }),
        { label: 'Phase6C deny proxy', sensitiveValues },
      ))
      await runStage('deny-proxy-start', () => waitForOwnedServer(
        deny, `${denyUrl}/health`, { expectedNonce: nonce, timeoutMs: limits.healthMs },
      ))

      await lifecycle.releaseReservation(reservations[2])
      const vite = lifecycle.registerServer(startOwnedServer(
        process.execPath,
        [
          path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'),
          '--config', roots.viteConfigPath, '--host', '127.0.0.1',
          '--port', String(vitePort), '--strictPort',
        ],
        options(frontend, {
          ...base, VITE_API_BASE_URL: `${apiUrl}/api`, M2_BROWSER_RUN_NONCE: nonce,
        }),
        { label: 'Phase6C Vite', sensitiveValues },
      ))
      await runStage('vite-start', () => waitForOwnedServer(
        vite, `${viteUrl}/__m2-browser-owner`, { expectedNonce: nonce, timeoutMs: limits.healthMs },
      ))

      const servers = [backend, deny, vite]
      await runStage('browser-test', async () => {
        try {
          return await runBoundedOwnedCommand(
            process.execPath,
            [
              path.join(frontend, 'node_modules', 'playwright', 'cli.js'),
              'test', `e2e/${FORMAL_SPECS[0]}`, '--config', `e2e/${FORMAL_CONFIG}`,
            ],
            options(frontend, browserEnvironment),
            {
              label: 'Phase6C browser test', sensitiveValues,
              timeoutMs: limits.browserMs, stopTimeoutMs: limits.stopMs, states: servers,
            },
          )
        } catch (error) {
          error.phase6cBrowserCause = classifyBrowserFailure(roots.resultPath)
          throw error
        }
      })
      await runStage('response-cleanup-audit', () => waitForEmptyRoots(roots))
      for (const target of [backupPath, finalPath]) {
        if (!existsSync(target) || !statSync(target).isFile()) {
          throw new Error('Phase6C saved download is missing')
        }
      }
      await runStage('outbound-audit', () => {
        if (readFileSync(roots.outboundLedgerPath, 'utf8').trim()) {
          throw new Error('Phase6C backend made an outbound request')
        }
      })
      await runStage('deny-proxy-audit', () => (
        assertDenyProxyLedger(readFileSync(roots.denyProxyLedgerPath, 'utf8'))
      ))
      await runStage('artifact-audit', () => assertArtifactEvidenceSafe(roots, sensitiveValues))
      await runStage('postcondition-verifier', () => runBoundedOwnedCommand(
        python,
        [
          '-m', 'backend.scripts.prepare_phase6c_browser_db', '--database', database,
          '--verify-postconditions',
        ],
        options(root, backendEnvironment),
        {
          label: 'Phase6C postcondition verifier', sensitiveValues,
          timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs, states: servers,
        },
      ))
    },
    stopServer: server => runStage('server-cleanup', () => stopOwnedServer(
      server, { sensitiveValues, timeoutMs: limits.stopMs },
    )),
    releaseReservation: reservation => reservation.release(),
    async dropDatabase(name) {
      await runStage('database-cleanup', () => runBoundedOwnedCommand(
        environment.PYTHON || 'python',
        ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', name, '--drop'],
        options(root, mysql),
        {
          label: 'Phase6C database cleanup', sensitiveValues,
          timeoutMs: limits.commandMs, stopTimeoutMs: limits.stopMs,
        },
      ))
      cleaned = 1
    },
    removeRoot: owned => runStage(
      'root-cleanup', () => cleanupRoot(owned, roots, ports, sensitiveValues),
    ),
  })
  assertDatabaseResidue(database, database, { created, cleaned, remaining: 0 })
  log(`Phase6C browser: 1/1 scenarios passed; consumerFailure=${consumerFailure}; DB/process/ports/quarantine/project-import-staging/temp/download/artifact/Vite residue=0; outbound/provider calls=0; product DB reads/writes=0/0`)
  return 0
}

if ((() => {
  try {
    return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url))
  } catch { return false }
})()) {
  runPhase6C().then(value => { process.exitCode = value }).catch(error => {
    console.error(safeClassifyFailure(error))
    process.exitCode = 1
  })
}

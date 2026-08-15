import {
  closeSync, existsSync, fstatSync, lstatSync, mkdirSync, mkdtempSync, openSync,
  readFileSync, readdirSync, realpathSync, rmSync, writeFileSync,
} from 'node:fs'
import { randomUUID } from 'node:crypto'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import {
  reserveLocalPort, runBoundedOwnedCommand, runBoundedOperation,
  startOwnedServer, stopOwnedServer,
} from './support/product-runner.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'

export const FORMAL_SPECS = Object.freeze(['phase7b-product-database-readiness.spec.mjs'])
export const FORMAL_CONFIG = 'playwright.phase7b.config.mjs'
const DATABASE = 'novel_creator_v113'
const TASK_ROOT_KEY = 'PHASE7B_BROWSER_TASK_ROOT'
const TASK_NONCE_KEY = 'PHASE7B_BROWSER_TASK_NONCE'
const RUNNER_ROOT_PREFIX = 'phase7b-runner-'
const SUMMARY_MARKER = 'PHASE7B_BROWSER_SMOKE_SUMMARY='
const PROVIDER_MARKER = 'PHASE7B_PROVIDER_CALL'
const OUTBOUND_MARKER = 'PHASE7B_OUTBOUND_REQUEST'
const WRITE_MARKER = 'PHASE7B_WRITE_REQUEST'
const SAFE_STAGES = new Set([
  'contract', 'root-setup', 'port-reservation', 'backend-start', 'vite-start',
  'browser-test', 'runtime-audit', 'server-cleanup', 'port-cleanup', 'root-cleanup',
])
const DEFAULT_DEADLINES = Object.freeze({
  healthMs: 45_000, browserMs: 180_000, stopMs: 8_000, settleMs: 15_000,
})
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontend, '..')
const normalize = value => {
  const resolved = path.resolve(value)
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved
}
const sameIdentity = (stats, identity) => (
  stats?.dev === identity?.dev && stats?.ino === identity?.ino
)
const options = (cwd, env) => ({ cwd, env, stdio: ['ignore', 'pipe', 'pipe'] })

const BACKEND_SOURCE = String.raw`
import sys
import httpx, uvicorn
nonce, port = sys.argv[1:3]
class DeniedAsyncClient:
    def __init__(self, *args, **kwargs): pass
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def aclose(self): return None
    def deny(self):
        print('${PROVIDER_MARKER}', flush=True)
        print('${OUTBOUND_MARKER}', flush=True)
        raise RuntimeError('outbound request denied by Phase7B read-only smoke')
    def build_request(self, *args, **kwargs): self.deny()
    async def request(self, *args, **kwargs): self.deny()
    async def send(self, *args, **kwargs): self.deny()
    def stream(self, *args, **kwargs): self.deny()
    async def get(self, *args, **kwargs): self.deny()
    async def post(self, *args, **kwargs): self.deny()
httpx.AsyncClient = DeniedAsyncClient
from backend.main import app
@app.middleware('http')
async def phase7b_read_only_audit(request, call_next):
    if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
        print('${WRITE_MARKER}', flush=True)
    response = await call_next(request)
    response.headers['x-phase7b-browser-owner'] = nonce
    return response
uvicorn.run(app, host='127.0.0.1', port=int(port), log_level='warning')
`

function stripCaseInsensitive(environment, names) {
  const denied = new Set(names.map(name => name.toUpperCase()))
  return Object.fromEntries(Object.entries(environment).filter(([key]) => (
    !denied.has(key.toUpperCase())
  )))
}

export function createBackendEnvironment(environment) {
  return {
    ...stripCaseInsensitive(environment, [
      'MYSQL_DB', 'MARKET_SCHEDULER_ENABLED', TASK_ROOT_KEY, TASK_NONCE_KEY,
      'M2_BROWSER_RUN_NONCE',
    ]),
    MYSQL_DB: DATABASE,
    MARKET_SCHEDULER_ENABLED: 'false',
  }
}

export function safeSummary({
  firstStage = null,
  firstCause = null,
  resourceCounts: counts = { rootCount: 0, artifactCount: 0 },
} = {}) {
  return {
    firstStage,
    firstCause,
    scenarioCount: 1,
    providerCalls: 0,
    outboundRequests: 0,
    processCount: 0,
    portCount: 0,
    rootCount: Number.isInteger(counts?.rootCount) && counts.rootCount >= 0
      ? counts.rootCount : 1,
    artifactCount: Number.isInteger(counts?.artifactCount) && counts.artifactCount >= 0
      ? counts.artifactCount : 1,
  }
}

export function renderSummary(summary) {
  return `${SUMMARY_MARKER}${JSON.stringify(summary)}`
}

function directIdentityMatches(taskRoot, identity) {
  return readdirSync(taskRoot, { withFileTypes: true }).flatMap(entry => {
    if (!entry.isDirectory() || entry.isSymbolicLink()) return []
    const candidate = path.join(taskRoot, entry.name)
    try {
      return sameIdentity(lstatSync(candidate), identity) ? [candidate] : []
    } catch (error) {
      if (error?.code === 'ENOENT') return []
      throw error
    }
  })
}

function directDirectoryIdentities(taskRoot) {
  return readdirSync(taskRoot, { withFileTypes: true }).flatMap(entry => {
    if (!entry.isDirectory() || entry.isSymbolicLink()) return []
    const candidate = path.join(taskRoot, entry.name)
    try {
      const stats = lstatSync(candidate)
      return [{ candidate, identity: { dev: stats.dev, ino: stats.ino } }]
    } catch (error) {
      if (error?.code === 'ENOENT') return []
      throw error
    }
  })
}

const identityKey = identity => `${String(identity.dev)}:${String(identity.ino)}`

export function createFilesystemRootOwner({
  mkdtempSyncImpl = mkdtempSync,
  openSyncImpl = openSync,
  fstatSyncImpl = fstatSync,
  closeSyncImpl = closeSync,
  rmSyncImpl = rmSync,
} = {}) {
  return Object.freeze({
    acquire(taskRoot, nonce) {
      const before = new Set(directDirectoryIdentities(taskRoot).map(entry => (
        identityKey(entry.identity)
      )))
      const canonicalPath = mkdtempSyncImpl(path.join(taskRoot, `${RUNNER_ROOT_PREFIX}${nonce}-`))
      let descriptor = null
      let identity = null
      let deleted = false
      let closed = false
      try {
        descriptor = openSyncImpl(canonicalPath, 'r')
        const bound = fstatSyncImpl(descriptor)
        if (!bound.isDirectory()) throw new Error('Phase7B root ownership primitive is invalid')
        identity = Object.freeze({ dev: bound.dev, ino: bound.ino })
        if (!sameIdentity(lstatSync(canonicalPath), identity)) {
          throw new Error('Phase7B root acquisition identity drifted')
        }
        const introduced = directDirectoryIdentities(taskRoot).filter(entry => (
          !before.has(identityKey(entry.identity))
        ))
        if (
          introduced.length !== 1
          || !sameIdentity(introduced[0].identity, identity)
          || normalize(introduced[0].candidate) !== normalize(canonicalPath)
        ) throw new Error('Phase7B root acquisition observed ambiguous new identities')
      } catch (primary) {
        const errors = [primary]
        if (descriptor !== null) {
          try { closeSyncImpl(descriptor) } catch (cleanup) { errors.push(cleanup) }
        }
        const error = errors.length === 1
          ? primary
          : new AggregateError(errors, 'Phase7B root acquisition and handle cleanup failed')
        error.phase7bResourceCounts = Object.freeze({ rootCount: 1, artifactCount: 0 })
        throw error
      }
      return {
        canonicalPath,
        identity,
        get closed() { return closed },
        get deleted() { return deleted },
        resolveOwned() {
          const matches = directIdentityMatches(taskRoot, identity)
          if (matches.length > 1) throw new Error('Phase7B owned root identity is ambiguous')
          return matches[0] || null
        },
        deleteOwned(candidate) {
          if (closed || !sameIdentity(fstatSyncImpl(descriptor), identity)) {
            throw new Error('Phase7B root ownership handle identity drifted')
          }
          const resolved = this.resolveOwned()
          if (!resolved || normalize(resolved) !== normalize(candidate)) {
            throw new Error('Phase7B owned root is outside its validated task parent')
          }
          if (!sameIdentity(lstatSync(resolved), identity)) {
            throw new Error('Phase7B owned root identity drifted before deletion')
          }
          rmSyncImpl(resolved, { recursive: true, maxRetries: 5, retryDelay: 200 })
          if (existsSync(resolved)) throw new Error('Phase7B runner root remained')
          deleted = true
        },
        close() {
          if (closed) return
          closeSyncImpl(descriptor)
          closed = true
        },
      }
    },
  })
}

const defaultRootOwner = createFilesystemRootOwner()

export function createBackendLaunch({ ownerNonce, port }) {
  if (!/^[a-f0-9]{32}$/u.test(ownerNonce) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new TypeError('Phase7B backend launch contract is invalid')
  }
  return { args: ['-c', BACKEND_SOURCE, ownerNonce, String(port)] }
}

function validateContract(environment) {
  const taskRoot = environment[TASK_ROOT_KEY]
  const nonce = environment[TASK_NONCE_KEY]
  if (
    environment.MYSQL_DB !== DATABASE
    || environment.MARKET_SCHEDULER_ENABLED !== 'false'
    || typeof nonce !== 'string'
    || !/^[a-f0-9]{32}$/u.test(nonce)
    || typeof taskRoot !== 'string'
    || !path.isAbsolute(taskRoot)
  ) throw new Error('Phase7B browser contract is invalid')
  const stats = lstatSync(taskRoot)
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new Error('Phase7B task root is not an owned directory')
  }
  if (normalize(realpathSync(taskRoot)) !== normalize(taskRoot)) {
    throw new Error('Phase7B task root identity is invalid')
  }
  return { nonce, taskRoot: path.resolve(taskRoot) }
}

export function createRunnerRoot(taskRoot, nonce, {
  writeFileSyncImpl = writeFileSync,
  rootOwner = defaultRootOwner,
} = {}) {
  if (typeof rootOwner?.acquire !== 'function') {
    throw new TypeError('Phase7B root ownership primitive is invalid')
  }
  const lease = rootOwner.acquire(taskRoot, nonce)
  if (
    typeof lease?.resolveOwned !== 'function'
    || typeof lease?.deleteOwned !== 'function'
    || typeof lease?.close !== 'function'
  ) throw new TypeError('Phase7B root lease is invalid')
  const runnerRoot = lease.resolveOwned()
  if (!runnerRoot || normalize(path.dirname(runnerRoot)) !== normalize(realpathSync(taskRoot))) {
    throw new Error('Phase7B owned root is outside its validated task parent')
  }
  const artifactRoot = path.join(runnerRoot, 'artifacts')
  const resultPath = path.join(runnerRoot, 'result.json')
  const viteConfigPath = path.join(runnerRoot, 'vite.config.mjs')
  try {
    mkdirSync(artifactRoot)
    writeFileSyncImpl(path.join(runnerRoot, 'ownership'), nonce, {
      encoding: 'utf8', flag: 'wx',
    })
    return {
      artifactRoot, resultPath, runnerRoot, viteConfigPath,
      lease,
    }
  } catch (error) {
    const errors = [error]
    try {
      const owned = lease.resolveOwned()
      if (!owned) throw new Error('Phase7B owned root is outside its validated task parent')
      lease.deleteOwned(owned)
    } catch (cleanup) { errors.push(cleanup) }
    try { lease.close() } catch (cleanup) { errors.push(cleanup) }
    if (errors.length === 1) throw error
    throw new AggregateError(errors, 'Phase7B root setup and rollback failed')
  }
}

function writeViteConfig(viteConfigPath, runnerRoot, apiUrl) {
  const baseConfig = pathToFileURL(path.join(frontend, 'vite.config.js')).href
  writeFileSync(viteConfigPath, [
    `import base from ${JSON.stringify(baseConfig)}`,
    'export default {',
    '  ...base,',
    `  cacheDir: ${JSON.stringify(path.join(runnerRoot, 'vite-cache'))},`,
    `  server: { ...(base.server || {}), proxy: { '/api': ${JSON.stringify(apiUrl)} } },`,
    '}',
    '',
  ].join('\n'), { encoding: 'utf8', flag: 'wx' })
}

function auditBrowserReport(roots) {
  const report = JSON.parse(readFileSync(roots.resultPath, 'utf8'))
  const suites = Array.isArray(report.suites) ? report.suites : []
  const specs = suites.flatMap(suite => Array.isArray(suite.specs) ? suite.specs : [])
  const tests = specs.flatMap(spec => Array.isArray(spec.tests) ? spec.tests : [])
  if (tests.length !== 1 || tests.some(item => item.status !== 'expected')) {
    throw new Error('Phase7B formal scenario evidence is invalid')
  }
}

export function createRuntimeAudit(child) {
  const counts = { providerCalls: 0, outboundRequests: 0, writeRequests: 0 }
  let buffered = ''
  let finished = false
  let auditError = null
  const consume = final => {
    const lines = buffered.split(/\r?\n/u)
    const remainder = lines.pop() || ''
    buffered = final ? '' : remainder
    for (const line of lines) {
      if (!line) continue
      if (line === PROVIDER_MARKER) counts.providerCalls += 1
      else if (line === OUTBOUND_MARKER) counts.outboundRequests += 1
      else if (line === WRITE_MARKER) counts.writeRequests += 1
      else auditError ??= new Error('Phase7B backend emitted unexpected standard output')
    }
    if (final && remainder) {
      auditError ??= new Error('Phase7B backend audit output was truncated')
    }
  }
  const onData = chunk => { buffered += chunk.toString('utf8'); consume(false) }
  child.stdout?.on('data', onData)
  return {
    finish() {
      if (!finished) {
        finished = true
        child.stdout?.off('data', onData)
        consume(true)
      }
      if (auditError) throw auditError
      return { ...counts }
    },
    snapshot() { return { ...counts } },
  }
}

function assertRuntimeAuditZero(audit) {
  const { providerCalls, outboundRequests, writeRequests } = audit.finish()
  if (providerCalls !== 0 || outboundRequests !== 0 || writeRequests !== 0) {
    throw new Error('Phase7B runtime audit was not zero')
  }
}

async function waitForBackendOwner(url, nonce, { timeoutMs, signal }) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (signal?.aborted) throw signal.reason
    try {
      const response = await fetch(url, { signal })
      const body = await response.json()
      if (
        response.status === 200
        && response.headers.get('x-phase7b-browser-owner') === nonce
        && JSON.stringify(body) === '{"ok":true}'
      ) return
    } catch {
      if (signal?.aborted) throw signal.reason
    }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Phase7B backend ownership check timed out')
}

async function waitForViteOwner(url, nonce, { timeoutMs, signal }) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (signal?.aborted) throw signal.reason
    try {
      const response = await fetch(url, { signal })
      if (response.ok && (await response.json())?.browserRunNonce === nonce) return
    } catch { if (signal?.aborted) throw signal.reason }
    await new Promise(resolve => setTimeout(resolve, 100))
  }
  throw new Error('Phase7B Vite ownership check timed out')
}

async function waitForPortRelease(port) {
  await new Promise((resolve, reject) => {
    const probe = net.createServer()
    const timer = setTimeout(() => {
      probe.close()
      reject(new Error('Phase7B owned port remained bound'))
    }, 10_000)
    probe.once('error', error => { clearTimeout(timer); reject(error) })
    probe.listen({ host: '127.0.0.1', port, exclusive: true }, () => {
      probe.close(error => { clearTimeout(timer); if (error) reject(error); else resolve() })
    })
  })
}

export function removeRunnerRoot(roots, taskRoot, nonce) {
  void nonce
  const errors = []
  const owned = roots.lease.resolveOwned()
  if (!owned || normalize(path.dirname(owned)) !== normalize(realpathSync(taskRoot))) {
    try { roots.lease.close() } catch (error) { errors.push(error) }
    const outside = new Error('Phase7B owned root is outside its validated task parent')
    if (errors.length) throw new AggregateError([outside, ...errors], 'Phase7B root recovery failed')
    throw outside
  }
  try {
    roots.lease.deleteOwned(owned)
  } catch (error) {
    errors.push(error)
  }
  try { roots.lease.close() } catch (error) { errors.push(error) }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase7B root cleanup failed')
}

export function auditRunnerRootArtifacts(roots, taskRoot) {
  const owned = roots.lease.resolveOwned()
  if (!owned || normalize(path.dirname(owned)) !== normalize(realpathSync(taskRoot))) {
    throw new Error('Phase7B owned root is outside its validated task parent')
  }
  const cache = path.join(owned, 'vite-cache')
  const temp = existsSync(cache)
    ? readdirSync(cache, { withFileTypes: true }).filter(entry => (
      entry.isDirectory() && entry.name.startsWith('deps_temp_')
    ))
    : []
  if (temp.length !== 0) throw new Error('Phase7B Vite deps_temp_ residue was not zero')
}

export function resourceCounts(roots) {
  if (!roots || roots.lease?.deleted) return { rootCount: 0, artifactCount: 0 }
  let owned = null
  try { owned = roots.lease?.resolveOwned?.() || null } catch { owned = null }
  if (!owned) return { rootCount: 1, artifactCount: 1 }
  const artifactCount = [
    path.join(owned, path.basename(roots.artifactRoot)),
    path.join(owned, path.basename(roots.resultPath)),
  ].filter(existsSync).length
  return { rootCount: 1, artifactCount }
}

function stageError(stage, cause) {
  const error = new Error('Phase7B browser stage failed', { cause })
  error.phase7bStage = SAFE_STAGES.has(stage) ? stage : 'contract'
  return error
}

function nestedResourceCounts(error) {
  const counts = { rootCount: 0, artifactCount: 0 }
  const visit = value => {
    if (!value || typeof value !== 'object') return
    const observed = value.phase7bResourceCounts
    if (Number.isInteger(observed?.rootCount) && observed.rootCount >= 0) {
      counts.rootCount = Math.max(counts.rootCount, observed.rootCount)
    }
    if (Number.isInteger(observed?.artifactCount) && observed.artifactCount >= 0) {
      counts.artifactCount = Math.max(counts.artifactCount, observed.artifactCount)
    }
    if (value.cause) visit(value.cause)
    if (value instanceof AggregateError) value.errors.forEach(visit)
  }
  visit(error)
  return counts
}

async function atStage(stage, action) {
  try { return await action() } catch (cause) { throw stageError(stage, cause) }
}

export async function runPhase7B({
  environment = process.env,
  log = console.log,
  deadlines = {},
  dependencies = {},
} = {}) {
  const deps = {
    validateContract,
    createRunnerRoot,
    reserveLocalPort,
    writeViteConfig,
    createBackendEnvironment,
    runtimeSensitiveValues,
    backendNonce: () => randomUUID().replaceAll('-', '').toLowerCase(),
    createBackendLaunch,
    startOwnedServer,
    createRuntimeAudit,
    runBoundedOperation,
    waitForBackendOwner,
    waitForViteOwner,
    runBoundedOwnedCommand,
    auditBrowserReport,
    stopOwnedServer,
    assertRuntimeAuditZero,
    waitForPortRelease,
    auditRunnerRootArtifacts,
    removeRunnerRoot,
    resourceCounts,
    ...dependencies,
  }
  const limits = { ...DEFAULT_DEADLINES, ...deadlines }
  const servers = []
  const reservations = []
  const released = new Set()
  const ports = []
  let roots = null
  let contract = null
  let primaryError = null
  let runtimeAudit = null
  let finalResourceCounts = { rootCount: 0, artifactCount: 0 }
  const cleanupErrors = []
  const release = async reservation => {
    if (released.has(reservation)) return
    await reservation.release()
    released.add(reservation)
  }
  try {
    contract = await atStage('contract', () => deps.validateContract(environment))
    roots = await atStage('root-setup', () => deps.createRunnerRoot(contract.taskRoot, contract.nonce))
    for (let index = 0; index < 2; index += 1) {
      const reservation = await atStage('port-reservation', () => deps.reserveLocalPort())
      reservations.push(reservation)
      ports.push(reservation.port)
    }
    if (new Set(ports).size !== 2) throw stageError('port-reservation', new Error())
    const [apiPort, vitePort] = ports
    const apiUrl = `http://127.0.0.1:${apiPort}`
    const viteUrl = `http://127.0.0.1:${vitePort}`
    await atStage('vite-start', () => deps.writeViteConfig(roots.viteConfigPath, roots.runnerRoot, apiUrl))
    const backendEnvironment = await atStage('backend-start', () => deps.createBackendEnvironment(environment))
    const sensitiveValues = await atStage('backend-start', () => deps.runtimeSensitiveValues(backendEnvironment))
    const backendOwnerNonce = await atStage('backend-start', () => deps.backendNonce())
    const backendLaunch = await atStage('backend-start', () => deps.createBackendLaunch({ ownerNonce: backendOwnerNonce, port: apiPort }))
    await release(reservations[0])
    const backend = await atStage('backend-start', () => deps.startOwnedServer(
      environment.PYTHON || 'python', backendLaunch.args,
      options(repositoryRoot, backendEnvironment), { label: 'Phase7B API', sensitiveValues },
    ))
    runtimeAudit = await atStage('backend-start', () => deps.createRuntimeAudit(backend.child))
    backend.auditors = [runtimeAudit]
    servers.push(backend)
    await atStage('backend-start', () => deps.runBoundedOperation(
      'Phase7B backend health', limits.healthMs, limits.settleMs,
      signal => deps.waitForBackendOwner(`${apiUrl}/api/health`, backendOwnerNonce, {
        timeoutMs: limits.healthMs, signal,
      }),
      [backend.state],
    ))
    await release(reservations[1])
    const viteEnvironment = {
      ...environment,
      M2_BROWSER_RUN_NONCE: contract.nonce,
      VITE_API_BASE_URL: `${apiUrl}/api`,
    }
    const vite = await atStage('vite-start', () => deps.startOwnedServer(
      process.execPath,
      [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'],
      options(frontend, viteEnvironment), { label: 'Phase7B Vite', sensitiveValues },
    ))
    servers.push(vite)
    await atStage('vite-start', () => deps.runBoundedOperation(
      'Phase7B Vite health', limits.healthMs, limits.settleMs,
      signal => deps.waitForViteOwner(`${viteUrl}/__m2-browser-owner`, contract.nonce, {
        timeoutMs: limits.healthMs, signal,
      }),
      [vite.state],
    ))
    const browserEnvironment = {
      ...stripCaseInsensitive(environment, [TASK_ROOT_KEY, TASK_NONCE_KEY]),
      PLAYWRIGHT_BASE_URL: viteUrl,
      BROWSER_ALLOWED_ORIGINS: JSON.stringify([viteUrl, apiUrl]),
      BROWSER_OWNED_ROOT: roots.runnerRoot,
      BROWSER_ARTIFACT_ROOT: roots.artifactRoot,
      BROWSER_RESULT_PATH: roots.resultPath,
    }
    await atStage('browser-test', () => deps.runBoundedOwnedCommand(
      process.execPath,
      [path.join(frontend, 'node_modules', 'playwright', 'cli.js'), 'test', `e2e/${FORMAL_SPECS[0]}`, '--config', `e2e/${FORMAL_CONFIG}`],
      options(frontend, browserEnvironment),
      {
        label: 'Phase7B browser test', timeoutMs: limits.browserMs,
        settleMs: limits.settleMs, stopTimeoutMs: limits.stopMs,
        sensitiveValues, states: servers,
      },
    ))
    await atStage('runtime-audit', () => deps.auditBrowserReport(roots))
  } catch (error) {
    primaryError = error
  } finally {
    for (const server of [...servers].reverse()) {
      try { await atStage('server-cleanup', () => deps.stopOwnedServer(server, { timeoutMs: limits.stopMs })) } catch (error) { cleanupErrors.push(error) }
    }
    if (runtimeAudit) {
      try { await atStage('runtime-audit', () => deps.assertRuntimeAuditZero(runtimeAudit)) } catch (error) { cleanupErrors.push(error) }
    }
    for (const reservation of reservations) {
      try { await release(reservation) } catch (cause) { cleanupErrors.push(stageError('port-cleanup', cause)) }
    }
    for (const port of ports) {
      try { await atStage('port-cleanup', () => deps.waitForPortRelease(port)) } catch (error) { cleanupErrors.push(error) }
    }
    if (roots && contract) {
      try { await atStage('root-cleanup', () => deps.auditRunnerRootArtifacts(roots, contract.taskRoot)) } catch (error) { cleanupErrors.push(error) }
      try { await atStage('root-cleanup', () => deps.removeRunnerRoot(roots, contract.taskRoot, contract.nonce)) } catch (error) { cleanupErrors.push(error) }
    }
    try {
      const observed = deps.resourceCounts(roots)
      const inherited = nestedResourceCounts(primaryError)
      finalResourceCounts = {
        rootCount: Math.max(observed.rootCount, inherited.rootCount),
        artifactCount: Math.max(observed.artifactCount, inherited.artifactCount),
      }
    } catch (cause) {
      finalResourceCounts = roots
        ? { rootCount: 1, artifactCount: 1 }
        : { rootCount: 0, artifactCount: 0 }
      cleanupErrors.push(stageError('root-cleanup', cause))
    }
  }
  const errors = [primaryError, ...cleanupErrors].filter(Boolean)
  let failure = null
  if (errors.length === 1) failure = errors[0]
  if (errors.length > 1) failure = new AggregateError(errors, 'Phase7B browser and cleanup failed')
  if (failure) {
    failure.phase7bResourceCounts = Object.freeze({ ...finalResourceCounts })
    throw failure
  }
  log(renderSummary(safeSummary({ resourceCounts: finalResourceCounts })))
  return 0
}

function firstStage(error) {
  if (!error || typeof error !== 'object') return 'contract'
  if (typeof error.phase7bStage === 'string') return error.phase7bStage
  if (error instanceof AggregateError) {
    for (const nested of error.errors) {
      const found = firstStage(nested)
      if (found) return found
    }
  }
  return firstStage(error.cause)
}

export function renderFailureSummary(error) {
  return renderSummary(safeSummary({
    firstStage: firstStage(error),
    firstCause: 'stage-failed',
    resourceCounts: error?.phase7bResourceCounts,
  }))
}

const isEntrypoint = (() => {
  try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)) } catch { return false }
})()
if (isEntrypoint) {
  runPhase7B().then(value => { process.exitCode = value }).catch(error => {
    console.error(renderFailureSummary(error))
    process.exitCode = 1
  })
}

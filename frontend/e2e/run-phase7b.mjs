import {
  existsSync, lstatSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync,
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
const INTERNAL_EVIDENCE_MARKER = 'PHASE7B_BROWSER_INTERNAL_EVIDENCE='
const SAFE_FAILURE_LINE = 'phase7b browser lifecycle failed'
const PROVIDER_MARKER = 'PHASE7B_PROVIDER_CALL'
const OUTBOUND_MARKER = 'PHASE7B_OUTBOUND_REQUEST'
const WRITE_MARKER = 'PHASE7B_WRITE_REQUEST'
const SAFE_STAGES = new Set([
  'contract', 'root-setup', 'port-reservation', 'backend-start', 'vite-start',
  'browser-test', 'runtime-audit', 'server-cleanup', 'port-cleanup', 'artifact-cleanup',
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

export function internalEvidence() {
  return {
    firstStage: null,
    firstCause: null,
    scenarioCount: 1,
    providerCalls: 0,
    outboundRequests: 0,
    processCount: 0,
    portCount: 0,
    artifactCount: 0,
  }
}

function compareUnicodeCodePoints(left, right) {
  const leftPoints = Array.from(left, value => value.codePointAt(0))
  const rightPoints = Array.from(right, value => value.codePointAt(0))
  for (let index = 0; index < Math.min(leftPoints.length, rightPoints.length); index += 1) {
    if (leftPoints[index] !== rightPoints[index]) return leftPoints[index] - rightPoints[index]
  }
  return leftPoints.length - rightPoints.length
}

export function canonicalJson(value) {
  const active = new Set()
  const serialize = item => {
    if (item === null || typeof item === 'boolean' || typeof item === 'string') {
      return JSON.stringify(item)
    }
    if (typeof item === 'number') {
      if (!Number.isFinite(item)) throw new TypeError('Phase7B evidence is not strict JSON')
      return JSON.stringify(item)
    }
    if (typeof item !== 'object') throw new TypeError('Phase7B evidence is not strict JSON')
    if (active.has(item)) throw new TypeError('Phase7B evidence is not strict JSON')
    active.add(item)
    try {
      if (Array.isArray(item)) {
        for (let index = 0; index < item.length; index += 1) {
          if (!Object.hasOwn(item, index)) throw new TypeError('Phase7B evidence is not strict JSON')
        }
        return `[${item.map(serialize).join(',')}]`
      }
      const prototype = Object.getPrototypeOf(item)
      if (prototype !== Object.prototype && prototype !== null) {
        throw new TypeError('Phase7B evidence is not strict JSON')
      }
      return `{${Object.keys(item).sort(compareUnicodeCodePoints).map(key => (
        `${JSON.stringify(key)}:${serialize(item[key])}`
      )).join(',')}}`
    } finally {
      active.delete(item)
    }
  }
  return serialize(value)
}

export function renderInternalEvidence(evidence) {
  return `${INTERNAL_EVIDENCE_MARKER}${canonicalJson(evidence)}`
}

export function renderSafeFailure(error) {
  void error
  return SAFE_FAILURE_LINE
}

export function createBackendLaunch({ ownerNonce, port }) {
  if (!/^[a-f0-9]{32}$/u.test(ownerNonce) || !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new TypeError('Phase7B backend launch contract is invalid')
  }
  return { args: ['-c', BACKEND_SOURCE, ownerNonce, String(port)] }
}

export function validateBorrowedContract(environment) {
  const taskRoot = environment[TASK_ROOT_KEY]
  const nonce = environment[TASK_NONCE_KEY]
  if (
    environment.MYSQL_DB !== DATABASE
    || environment.MARKET_SCHEDULER_ENABLED !== 'false'
    || typeof nonce !== 'string'
    || !/^[a-f0-9]{32}$/u.test(nonce)
    || typeof taskRoot !== 'string'
    || !path.isAbsolute(taskRoot)
    || taskRoot !== path.resolve(taskRoot)
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

export function createBorrowedRunnerPaths(taskRoot, nonce, {
  mkdirSyncImpl = mkdirSync,
} = {}) {
  if (!/^[a-f0-9]{32}$/u.test(nonce)) throw new TypeError('Phase7B browser contract is invalid')
  const runnerRoot = path.resolve(taskRoot)
  if (normalize(realpathSync(runnerRoot)) !== normalize(runnerRoot)) {
    throw new Error('Phase7B task root identity is invalid')
  }
  const stats = lstatSync(runnerRoot)
  if (!stats.isDirectory() || stats.isSymbolicLink()) {
    throw new Error('Phase7B task root is not an owned directory')
  }
  const artifactRoot = path.join(runnerRoot, 'artifacts')
  const cacheRoot = path.join(runnerRoot, 'vite-cache')
  const resultPath = path.join(runnerRoot, 'result.json')
  const viteConfigPath = path.join(runnerRoot, 'vite.config.mjs')
  try {
    mkdirSyncImpl(artifactRoot)
    return Object.freeze({ artifactRoot, cacheRoot, resultPath, runnerRoot, viteConfigPath })
  } catch (error) {
    const errors = [error]
    try { rmSync(artifactRoot, { recursive: true, force: true }) } catch (cleanup) { errors.push(cleanup) }
    if (errors.length === 1) throw error
    throw new AggregateError(errors, 'Phase7B artifact setup and rollback failed')
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

function assertFixedBorrowedPaths(roots) {
  const runnerRoot = path.resolve(roots.runnerRoot)
  const expected = {
    artifactRoot: path.join(runnerRoot, 'artifacts'),
    cacheRoot: path.join(runnerRoot, 'vite-cache'),
    resultPath: path.join(runnerRoot, 'result.json'),
    viteConfigPath: path.join(runnerRoot, 'vite.config.mjs'),
  }
  for (const [name, value] of Object.entries(expected)) {
    if (normalize(roots[name]) !== normalize(value) || normalize(path.dirname(value)) !== normalize(runnerRoot)) {
      throw new Error('Phase7B borrowed artifact path is invalid')
    }
  }
  return expected
}

export function cleanupBorrowedArtifacts(roots) {
  const paths = assertFixedBorrowedPaths(roots)
  const errors = []
  for (const candidate of [
    paths.artifactRoot, paths.cacheRoot, paths.resultPath, paths.viteConfigPath,
  ]) {
    try { rmSync(candidate, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }) } catch (error) { errors.push(error) }
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase7B artifact cleanup failed')
}

export function auditBorrowedArtifacts(roots) {
  const paths = assertFixedBorrowedPaths(roots)
  const count = Object.values(paths).filter(existsSync).length
  if (count !== 0) throw new Error('Phase7B borrowed artifact residue was not zero')
  return count
}

function stageError(stage, cause) {
  const error = new Error('Phase7B browser stage failed', { cause })
  error.phase7bStage = SAFE_STAGES.has(stage) ? stage : 'contract'
  return error
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
    validateBorrowedContract,
    createBorrowedRunnerPaths,
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
    cleanupBorrowedArtifacts,
    auditBorrowedArtifacts,
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
  const cleanupErrors = []
  const release = async reservation => {
    if (released.has(reservation)) return
    await reservation.release()
    released.add(reservation)
  }
  try {
    contract = await atStage('contract', () => deps.validateBorrowedContract(environment))
    roots = await atStage('root-setup', () => deps.createBorrowedRunnerPaths(contract.taskRoot, contract.nonce))
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
    servers.push(backend)
    runtimeAudit = await atStage('runtime-audit', () => deps.createRuntimeAudit(backend.child))
    backend.auditors = [runtimeAudit]
    await atStage('backend-start', () => deps.runBoundedOperation(
      'Phase7B backend health', limits.healthMs, limits.settleMs,
      signal => deps.waitForBackendOwner(`${apiUrl}/api/health`, backendOwnerNonce, {
        timeoutMs: limits.healthMs, signal,
      }),
      [backend.state],
    ))
    await release(reservations[1])
    const viteEnvironment = {
      ...stripCaseInsensitive(environment, [TASK_ROOT_KEY, TASK_NONCE_KEY]),
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
    if (roots) {
      try { await atStage('artifact-cleanup', () => deps.cleanupBorrowedArtifacts(roots)) } catch (error) { cleanupErrors.push(error) }
      try { await atStage('artifact-cleanup', () => deps.auditBorrowedArtifacts(roots)) } catch (error) { cleanupErrors.push(error) }
    }
  }
  const errors = [primaryError, ...cleanupErrors].filter(Boolean)
  let failure = null
  if (errors.length === 1) failure = errors[0]
  if (errors.length > 1) failure = new AggregateError(errors, 'Phase7B browser and cleanup failed')
  if (failure) throw failure
  log(renderInternalEvidence(internalEvidence()))
  return 0
}

const isEntrypoint = (() => {
  try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)) } catch { return false }
})()
if (isEntrypoint) {
  runPhase7B().then(value => { process.exitCode = value }).catch(error => {
    void error
    console.error(renderSafeFailure(error))
    process.exitCode = 1
  })
}

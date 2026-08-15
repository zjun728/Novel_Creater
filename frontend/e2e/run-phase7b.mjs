import {
  existsSync, lstatSync, mkdirSync, readFileSync, readdirSync, realpathSync,
  rmSync, writeFileSync,
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

export function safeSummary({ firstStage = null, firstCause = null } = {}) {
  return {
    firstStage,
    firstCause,
    scenarioCount: 1,
    providerCalls: 0,
    outboundRequests: 0,
    processCount: 0,
    portCount: 0,
    rootCount: 0,
    artifactCount: 0,
  }
}

export function renderSummary(summary) {
  return `${SUMMARY_MARKER}${JSON.stringify(summary)}`
}

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
} = {}) {
  const runnerRoot = path.join(taskRoot, `${RUNNER_ROOT_PREFIX}${nonce}`)
  if (normalize(path.dirname(runnerRoot)) !== normalize(realpathSync(taskRoot))) {
    throw new Error('Phase7B runner root escaped its task root')
  }
  mkdirSync(runnerRoot)
  const owner = lstatSync(runnerRoot)
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
      runnerRootIdentity: Object.freeze({ dev: owner.dev, ino: owner.ino }),
    }
  } catch (error) {
    const current = lstatSync(runnerRoot)
    if (
      current.dev !== owner.dev
      || current.ino !== owner.ino
      || current.isSymbolicLink()
      || !current.isDirectory()
    ) throw new AggregateError([error], 'Phase7B root setup lost cleanup authority')
    rmSync(runnerRoot, { recursive: true, maxRetries: 5, retryDelay: 200 })
    throw error
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
  const expected = path.join(taskRoot, `${RUNNER_ROOT_PREFIX}${nonce}`)
  const stats = lstatSync(roots.runnerRoot)
  if (
    roots.runnerRoot !== expected
    || stats.dev !== roots.runnerRootIdentity?.dev
    || stats.ino !== roots.runnerRootIdentity?.ino
    || stats.isSymbolicLink()
    || !stats.isDirectory()
    || normalize(realpathSync(roots.runnerRoot)) !== normalize(expected)
  ) throw new Error('Phase7B runner root lost ownership')
  const cache = path.join(roots.runnerRoot, 'vite-cache')
  const temp = existsSync(cache)
    ? readdirSync(cache, { withFileTypes: true }).filter(entry => (
      entry.isDirectory() && entry.name.startsWith('deps_temp_')
    ))
    : []
  const errors = []
  if (temp.length !== 0) errors.push(new Error('Phase7B Vite deps_temp_ residue was not zero'))
  try {
    rmSync(roots.runnerRoot, { recursive: true, maxRetries: 5, retryDelay: 200 })
    if (existsSync(roots.runnerRoot)) throw new Error('Phase7B runner root remained')
  } catch (error) {
    errors.push(error)
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase7B root audit and cleanup failed')
}

function stageError(stage, cause) {
  const error = new Error('Phase7B browser stage failed', { cause })
  error.phase7bStage = SAFE_STAGES.has(stage) ? stage : 'contract'
  return error
}

async function atStage(stage, action) {
  try { return await action() } catch (cause) { throw stageError(stage, cause) }
}

export async function runPhase7B({ environment = process.env, log = console.log, deadlines = {} } = {}) {
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
    contract = await atStage('contract', () => validateContract(environment))
    roots = await atStage('root-setup', () => createRunnerRoot(contract.taskRoot, contract.nonce))
    for (let index = 0; index < 2; index += 1) {
      const reservation = await atStage('port-reservation', () => reserveLocalPort())
      reservations.push(reservation)
      ports.push(reservation.port)
    }
    if (new Set(ports).size !== 2) throw stageError('port-reservation', new Error())
    const [apiPort, vitePort] = ports
    const apiUrl = `http://127.0.0.1:${apiPort}`
    const viteUrl = `http://127.0.0.1:${vitePort}`
    writeViteConfig(roots.viteConfigPath, roots.runnerRoot, apiUrl)
    const backendEnvironment = createBackendEnvironment(environment)
    const sensitiveValues = runtimeSensitiveValues(backendEnvironment)
    const backendOwnerNonce = randomUUID().replaceAll('-', '').toLowerCase()
    const backendLaunch = createBackendLaunch({ ownerNonce: backendOwnerNonce, port: apiPort })
    await release(reservations[0])
    const backend = startOwnedServer(
      environment.PYTHON || 'python',
      backendLaunch.args,
      options(repositoryRoot, backendEnvironment),
      { label: 'Phase7B API', sensitiveValues },
    )
    runtimeAudit = createRuntimeAudit(backend.child)
    backend.auditors = [runtimeAudit]
    servers.push(backend)
    await atStage('backend-start', () => runBoundedOperation(
      'Phase7B backend health', limits.healthMs, limits.settleMs,
      signal => waitForBackendOwner(`${apiUrl}/api/health`, backendOwnerNonce, {
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
    const vite = startOwnedServer(
      process.execPath,
      [path.join(frontend, 'node_modules', 'vite', 'bin', 'vite.js'), '--config', roots.viteConfigPath, '--host', '127.0.0.1', '--port', String(vitePort), '--strictPort'],
      options(frontend, viteEnvironment),
      { label: 'Phase7B Vite', sensitiveValues },
    )
    servers.push(vite)
    await atStage('vite-start', () => runBoundedOperation(
      'Phase7B Vite health', limits.healthMs, limits.settleMs,
      async signal => {
        const deadline = Date.now() + limits.healthMs
        while (Date.now() < deadline) {
          if (signal.aborted) throw signal.reason
          try {
            const response = await fetch(`${viteUrl}/__m2-browser-owner`, { signal })
            if (response.ok && (await response.json())?.browserRunNonce === contract.nonce) return
          } catch { if (signal.aborted) throw signal.reason }
          await new Promise(resolve => setTimeout(resolve, 100))
        }
        throw new Error('Phase7B Vite ownership check timed out')
      },
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
    await atStage('browser-test', () => runBoundedOwnedCommand(
      process.execPath,
      [path.join(frontend, 'node_modules', 'playwright', 'cli.js'), 'test', `e2e/${FORMAL_SPECS[0]}`, '--config', `e2e/${FORMAL_CONFIG}`],
      options(frontend, browserEnvironment),
      {
        label: 'Phase7B browser test', timeoutMs: limits.browserMs,
        settleMs: limits.settleMs, stopTimeoutMs: limits.stopMs,
        sensitiveValues, states: servers,
      },
    ))
    await atStage('runtime-audit', () => auditBrowserReport(roots))
  } catch (error) {
    primaryError = error
  } finally {
    for (const server of [...servers].reverse()) {
      try { await atStage('server-cleanup', () => stopOwnedServer(server, { timeoutMs: limits.stopMs })) } catch (error) { cleanupErrors.push(error) }
    }
    if (runtimeAudit) {
      try { await atStage('runtime-audit', () => assertRuntimeAuditZero(runtimeAudit)) } catch (error) { cleanupErrors.push(error) }
    }
    for (const reservation of reservations) {
      try { await release(reservation) } catch (cause) { cleanupErrors.push(stageError('port-cleanup', cause)) }
    }
    for (const port of ports) {
      try { await atStage('port-cleanup', () => waitForPortRelease(port)) } catch (error) { cleanupErrors.push(error) }
    }
    if (roots && contract) {
      try { await atStage('root-cleanup', () => removeRunnerRoot(roots, contract.taskRoot, contract.nonce)) } catch (error) { cleanupErrors.push(error) }
    }
  }
  const errors = [primaryError, ...cleanupErrors].filter(Boolean)
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) throw new AggregateError(errors, 'Phase7B browser and cleanup failed')
  log(renderSummary(safeSummary()))
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

const isEntrypoint = (() => {
  try { return realpathSync(process.argv[1]) === realpathSync(fileURLToPath(import.meta.url)) } catch { return false }
})()
if (isEntrypoint) {
  runPhase7B().then(value => { process.exitCode = value }).catch(error => {
    console.error(renderSummary(safeSummary({ firstStage: firstStage(error), firstCause: 'stage-failed' })))
    process.exitCode = 1
  })
}

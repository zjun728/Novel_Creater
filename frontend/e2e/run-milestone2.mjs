import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import {
  mkdtempSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import os from 'node:os'
import net from 'node:net'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { createServerLogObserver } from './server-log-observer.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'


export const REQUIRED_TEST_VARIABLES = [
  'TEST_MYSQL_HOST',
  'TEST_MYSQL_PORT',
  'TEST_MYSQL_USER',
  'TEST_MYSQL_PASSWORD',
]
export const DISPOSABLE_DATABASE = /^novel_creator_test_[a-f0-9]{32}$/
export const BROWSER_SECRET_SENTINEL = 'browser-secret-must-not-leak'
export const BROWSER_PRIVATE_PROVIDER_URL = 'https://private-provider.example/v1'
export const BROWSER_CORPUS_ROOT_SENTINEL = 'C:/private/corpus-root-must-not-leak'
export const SCENARIOS = new Set(['foundation', 'manual', 'recovery', 'settings'])
export const FORMAL_SPECS = Object.freeze([
  Object.freeze({
    path: 'e2e/m2-foundation-regression.spec.ts',
    scenario: 'foundation',
  }),
  Object.freeze({
    path: 'e2e/m2-wizard-manual.spec.ts',
    scenario: 'manual',
  }),
  Object.freeze({
    path: 'e2e/m2-wizard-recovery.spec.ts',
    scenario: 'recovery',
  }),
  Object.freeze({
    path: 'e2e/m2-settings-assets-corpus.spec.ts',
    scenario: 'settings',
  }),
])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const CORPUS_PREFIX = 'novel-creator-m2-corpus-'
const SYNTHETIC_CORPUS = `第一章 潮线之外
暮色里的测量塔只记录合成世界的风向。值守员岑禾发现，纸带上多出一组尚未被命名的潮汐刻度。

第二章 静默航标
清晨，岑禾沿盐白色堤岸校准航标。远处无人岛回送三次蓝光，像在邀请她核对一条从不存在的航线。
`


export function validateTestEnvironment(environment = process.env) {
  const missing = REQUIRED_TEST_VARIABLES.filter(name => !environment[name])
  if (missing.length) {
    throw new Error(`Browser MySQL requires explicit variables: ${missing.join(', ')}`)
  }
  const port = Number(environment.TEST_MYSQL_PORT)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('TEST_MYSQL_PORT must be an integer between 1 and 65535')
  }
}


export function assertDatabaseName(databaseName) {
  if (typeof databaseName !== 'string' || !DISPOSABLE_DATABASE.test(databaseName)) {
    throw new Error(`Refusing non-disposable browser database: ${String(databaseName)}`)
  }
}


export function createDatabaseName(uuidFactory = randomUUID) {
  const databaseName = `novel_creator_test_${uuidFactory().replaceAll('-', '').toLowerCase()}`
  assertDatabaseName(databaseName)
  return databaseName
}


export function reserveLocalPort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer()
    const onError = error => reject(error)
    server.unref()
    server.once('error', onError)
    server.listen({ host: '127.0.0.1', port: 0, exclusive: true }, () => {
      server.off('error', onError)
      const address = server.address()
      if (!address || typeof address === 'string') {
        server.close()
        reject(new Error('local port reservation did not return a TCP port'))
        return
      }
      let released = false
      resolve({
        port: address.port,
        release() {
          if (released) return Promise.resolve()
          released = true
          return new Promise((releaseResolve, releaseReject) => {
            server.close(error => {
              if (error) releaseReject(error)
              else releaseResolve()
            })
          })
        },
      })
    })
  })
}


export function buildChildEnvironment(environment, databaseName, corpusRoot) {
  validateTestEnvironment(environment)
  assertDatabaseName(databaseName)
  if (typeof corpusRoot !== 'string' || !path.isAbsolute(corpusRoot)) {
    throw new Error('M2 browser corpus root must be an absolute temporary directory')
  }
  const clean = Object.fromEntries(
    Object.entries(environment).filter(([name]) => !name.startsWith('MYSQL_')),
  )
  return {
    ...clean,
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName,
    BROWSER_TEST_DATABASE: databaseName,
    CORPUS_ROOT: corpusRoot,
    BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL: corpusRoot,
    BROWSER_SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL,
    BROWSER_CORPUS_ROOT_SENTINEL,
  }
}


export function validateSpecs(specs) {
  if (!Array.isArray(specs) || specs.length !== FORMAL_SPECS.length) {
    throw new Error('M2 browser requires the exact explicit closed formal spec list')
  }
  return specs.map((spec, index) => {
    const expected = FORMAL_SPECS[index]
    const keys = spec && typeof spec === 'object'
      ? Object.keys(spec).sort()
      : []
    if (
      keys.length !== 2
      || keys[0] !== 'path'
      || keys[1] !== 'scenario'
      || spec.path !== expected.path
      || spec.scenario !== expected.scenario
    ) {
      throw new Error('M2 browser spec path and scenario must match the closed formal map')
    }
    return { path: expected.path, scenario: expected.scenario }
  })
}


export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList)) {
    throw new TypeError('M2 browser CLI arguments must be an array')
  }
  if (argumentsList.length !== 0) {
    throw new Error('M2 browser CLI does not accept spec paths')
  }
  return FORMAL_SPECS.map(spec => ({ ...spec }))
}


function assertExternalCorpusRoot(corpusRoot) {
  if (!path.isAbsolute(corpusRoot)) {
    throw new Error('M2 browser corpus root must be absolute')
  }
  const relative = path.relative(repositoryRoot, corpusRoot)
  if (relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative))) {
    throw new Error('M2 browser corpus root must be outside the repository')
  }
}


function childOptions(cwd, env) {
  return {
    cwd,
    env,
    shell: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  }
}


export function defaultRun(command, args, options, {
  sensitiveValues = [],
  signal,
} = {}) {
  return new Promise(resolve => {
    const child = spawn(command, args, options)
    const logObserver = createServerLogObserver(child, { sensitiveValues })
    let spawnError = null
    let closed = false
    let forcedStopTimer = null
    const removeAbortListener = () => signal?.removeEventListener('abort', stopChild)
    const stopChild = () => {
      if (closed || (child.exitCode !== null && child.exitCode !== undefined)) return
      try {
        if (child.kill('SIGTERM') === false && !spawnError) {
          spawnError = new Error('process rejected abort signal')
        }
      } catch (error) {
        if (!spawnError) spawnError = error
      }
      forcedStopTimer = setTimeout(() => {
        if (closed) return
        try {
          child.kill('SIGKILL')
        } catch (error) {
          if (!spawnError) spawnError = error
        }
      }, 5_000)
      forcedStopTimer.unref?.()
    }
    child.once('error', error => {
      spawnError = error
    })
    child.once('close', code => {
      closed = true
      clearTimeout(forcedStopTimer)
      removeAbortListener()
      resolve({ status: code, error: spawnError, logObserver })
    })
    if (signal?.aborted) stopChild()
    else signal?.addEventListener('abort', stopChild, { once: true })
  })
}


const childLifecycles = new WeakMap()


function trackChildLifecycle(child, label) {
  if (!child || (typeof child !== 'object' && typeof child !== 'function')) {
    return {
      child,
      label,
      supportsEvents: false,
      stopRequested: false,
      earlyFailure: null,
      earlyFailureObserved: false,
      failurePromise: new Promise(() => {}),
      closePromise: Promise.resolve(),
    }
  }
  const existing = childLifecycles.get(child)
  if (existing) return existing
  const supportsEvents = typeof child.once === 'function'
  let resolveFailure
  let resolveClose
  const state = {
    child,
    label,
    supportsEvents,
    exitSeen: false,
    closeSeen: false,
    exitCode: null,
    signal: null,
    childError: null,
    stopRequested: false,
    earlyFailure: null,
    earlyFailureObserved: false,
    failurePromise: new Promise(resolve => { resolveFailure = resolve }),
    closePromise: supportsEvents
      ? new Promise(resolve => { resolveClose = resolve })
      : Promise.resolve(),
  }
  let failureReported = false
  const reportFailure = error => {
    if (state.stopRequested || failureReported) return
    failureReported = true
    state.earlyFailure = error
    resolveFailure(error)
  }
  if (supportsEvents) {
    child.once('error', error => {
      state.childError = error
      reportFailure(new Error(`${label} server emitted an error before browser completion`))
    })
    child.once('exit', (code, signal) => {
      state.exitSeen = true
      state.exitCode = code
      state.signal = signal
      reportFailure(new Error(
        `${label} server exited before browser completion with status ${String(code)}`,
      ))
    })
    child.once('close', (code, signal) => {
      state.closeSeen = true
      if (!state.exitSeen) {
        state.exitCode = code
        state.signal = signal
        reportFailure(new Error(
          `${label} server closed before browser completion with status ${String(code)}`,
        ))
      }
      resolveClose()
    })
  }
  childLifecycles.set(child, state)
  return state
}


function detectEarlyLifecycleFailure(state) {
  if (!state || state.stopRequested) return state?.earlyFailure || null
  if (state.earlyFailure) return state.earlyFailure
  if (state.childError) {
    state.earlyFailure = new Error(
      `${state.label} server emitted an error before browser completion`,
    )
    return state.earlyFailure
  }
  const childExitCode = state.child?.exitCode
  const exited = state.exitSeen
    || state.closeSeen
    || (childExitCode !== null && childExitCode !== undefined)
  if (!exited) return null
  const exitCode = state.exitCode ?? childExitCode
  state.exitCode = exitCode
  state.earlyFailure = new Error(
    `${state.label} server exited before browser completion with status ${String(exitCode)}`,
  )
  return state.earlyFailure
}


function markStopRequested(state) {
  const earlyFailure = detectEarlyLifecycleFailure(state)
  state.stopRequested = true
  return earlyFailure
}


function waitForLifecycleClose(state, timeoutMs) {
  if (!state.supportsEvents || state.closeSeen) return Promise.resolve()
  return new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`${state.label} server close timed out`)),
      timeoutMs,
    )
    state.closePromise.then(() => {
      clearTimeout(timer)
      resolve()
    })
  })
}


async function defaultStop(child) {
  if (!child) return
  const state = trackChildLifecycle(child, 'owned')
  const earlyFailure = markStopRequested(state)
  const exitedBeforeStop = Boolean(earlyFailure)
  if (!exitedBeforeStop && child.kill('SIGTERM') === false) {
    throw new Error('server rejected stop signal')
  }
  try {
    await waitForLifecycleClose(state, 5_000)
  } catch (gracefulError) {
    if (!state.closeSeen) child.kill('SIGKILL')
    try {
      await waitForLifecycleClose(state, 5_000)
    } catch (forcedError) {
      throw new AggregateError(
        [gracefulError, forcedError],
        'server graceful and forced stop both failed',
      )
    }
  }
  if (earlyFailure && !state.earlyFailureObserved) {
    state.earlyFailureObserved = true
    throw earlyFailure
  }
}


const defaultProcessRunner = {
  run: defaultRun,
  start(command, args, options, { label = 'owned' } = {}) {
    const child = spawn(command, args, options)
    trackChildLifecycle(child, label)
    return child
  },
  stop: defaultStop,
}


export async function waitForOwnedUrl(url, {
  expectedNonce,
  fetchImpl = fetch,
  timeoutMs = 30_000,
  intervalMs = 100,
  signal,
} = {}) {
  if (typeof expectedNonce !== 'string' || expectedNonce.length === 0) {
    throw new TypeError('owned browser health requires a non-empty nonce')
  }
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (signal?.aborted) throw abortReason(signal)
    const remainingMs = deadline - Date.now()
    const requestController = new AbortController()
    const forwardAbort = () => requestController.abort(abortReason(signal))
    signal?.addEventListener('abort', forwardAbort, { once: true })
    const requestTimer = setTimeout(
      () => requestController.abort(new Error('owned health request timed out')),
      Math.max(1, Math.min(remainingMs, 2_000)),
    )
    try {
      const response = await awaitAbortable(
        () => fetchImpl(url, { signal: requestController.signal }),
        requestController.signal,
      )
      if (response.ok) {
        const body = await awaitAbortable(
          () => response.json(),
          requestController.signal,
        )
        if (body?.browserRunNonce === expectedNonce) return
      }
    } catch {
      if (signal?.aborted) throw abortReason(signal)
      // A refused connection is expected while the owned process starts.
    } finally {
      clearTimeout(requestTimer)
      signal?.removeEventListener('abort', forwardAbort)
    }
    const sleepMs = Math.min(intervalMs, Math.max(0, deadline - Date.now()))
    if (sleepMs > 0) await sleepWithAbort(sleepMs, signal)
  }
  throw new Error('timed out waiting for runner-owned browser server to prove ownership')
}


function abortReason(signal) {
  if (signal?.reason instanceof Error) return signal.reason
  const error = new Error('operation aborted')
  error.name = 'AbortError'
  return error
}


function awaitAbortable(operation, signal) {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(abortReason(signal))
      return
    }
    let settled = false
    const finish = callback => value => {
      if (settled) return
      settled = true
      signal.removeEventListener('abort', onAbort)
      callback(value)
    }
    const onAbort = () => finish(reject)(abortReason(signal))
    signal.addEventListener('abort', onAbort, { once: true })
    Promise.resolve().then(operation).then(finish(resolve), finish(reject))
  })
}


function sleepWithAbort(timeoutMs, signal) {
  if (!signal) return new Promise(resolve => setTimeout(resolve, timeoutMs))
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(abortReason(signal))
      return
    }
    const onAbort = () => {
      clearTimeout(timer)
      signal.removeEventListener('abort', onAbort)
      reject(abortReason(signal))
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort)
      resolve()
    }, timeoutMs)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}


function processError(label, result) {
  if (result?.error) {
    return new Error(`${label} process failed to start`, { cause: result.error })
  }
  if (result?.status !== 0) {
    return new Error(`${label} process exited with status ${String(result?.status)}`)
  }
  return null
}


export function browserSensitiveValues(environment, databaseName, corpusRoot) {
  return runtimeSensitiveValues(buildChildEnvironment(environment, databaseName, corpusRoot))
}


function scanProcessResult(result, values) {
  if (!result?.logObserver) return null
  const scan = result.logObserver.finish(values)
  if (scan.matchCount !== 0) {
    return new Error(`process log sensitive match count was ${scan.matchCount}`)
  }
  return null
}


function assertProcessResult(label, result, values) {
  const errors = []
  const executionError = processError(label, result)
  if (executionError) errors.push(executionError)
  try {
    const scanError = scanProcessResult(result, values)
    if (scanError) errors.push(scanError)
  } catch (error) {
    errors.push(error)
  }
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(
      errors,
      `${executionError?.message || label}; process log scan also failed`,
    )
  }
}


function assertServicesStillLive(states) {
  for (const state of states) {
    const earlyFailure = detectEarlyLifecycleFailure(state)
    if (!earlyFailure) continue
    state.earlyFailureObserved = true
    throw earlyFailure
  }
}


export async function runWhileServicesLive(operation, states, {
  settleAbortedOperation,
} = {}) {
  const operationController = new AbortController()
  const operationOutcome = Promise.resolve()
    .then(() => operation(operationController.signal))
    .then(
      value => ({ kind: 'operation', value }),
      error => ({ kind: 'operation', error }),
    )
  const serviceFailure = Promise.race(
    states.map(state => state.failurePromise.then(error => ({ state, error }))),
  ).then(({ state, error }) => ({ kind: 'service', state, error }))
  const outcome = await Promise.race([operationOutcome, serviceFailure])
  if (outcome.kind === 'service') {
    outcome.state.earlyFailureObserved = true
    operationController.abort(outcome.error)
    const settledOperation = await operationOutcome
    const settleErrors = []
    if (
      settledOperation.error
      && settledOperation.error !== outcome.error
      && settledOperation.error?.name !== 'AbortError'
    ) {
      settleErrors.push(settledOperation.error)
    }
    if (settleAbortedOperation) {
      try {
        await settleAbortedOperation(settledOperation)
      } catch (error) {
        settleErrors.push(error)
      }
    }
    if (settleErrors.length > 0) {
      throw new AggregateError(
        [outcome.error, ...settleErrors],
        'M2 server failed while the active operation was settling',
      )
    }
    throw outcome.error
  }
  if (outcome.error) throw outcome.error
  assertServicesStillLive(states)
  return outcome.value
}


export function assertOwnedCorpusRoot(corpusRoot, corpusPrefix, tempParent = os.tmpdir()) {
  if (typeof corpusRoot !== 'string' || typeof corpusPrefix !== 'string') {
    throw new TypeError('owned corpus root and prefix must be strings')
  }
  const resolvedParent = path.resolve(tempParent)
  const resolvedPrefix = path.resolve(corpusPrefix)
  const resolvedRoot = path.resolve(corpusRoot)
  const prefixName = path.basename(resolvedPrefix)
  const rootName = path.basename(resolvedRoot)
  if (
    path.dirname(resolvedPrefix) !== resolvedParent
    || !prefixName.startsWith(CORPUS_PREFIX)
    || prefixName.length === CORPUS_PREFIX.length
    || resolvedRoot === resolvedParent
    || path.dirname(resolvedRoot) !== resolvedParent
    || !rootName.startsWith(prefixName)
    || rootName.length === prefixName.length
  ) {
    throw new Error('M2 owned corpus root must be this run\'s mkdtemp result')
  }
  return resolvedRoot
}


async function runOneSpec({
  spec,
  environment,
  databaseNameFactory,
  mkdtempImpl,
  writeFileImpl,
  rmImpl,
  processRunner,
  waitForUrlImpl,
  serverLogObserverFactory,
  portReservationFactory,
  nonceFactory,
  assertExternalCorpusRootImpl,
}) {
  const databaseName = databaseNameFactory()
  assertDatabaseName(databaseName)
  const python = environment.PYTHON || 'python'
  const prepareArgs = [
    '-m',
    'backend.scripts.prepare_milestone2_browser_db',
    '--database',
    databaseName,
    '--scenario',
    spec.scenario,
  ]
  const cleanupArgs = [...prepareArgs, '--drop']
  const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
  const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')
  const bodyErrors = []
  const serverErrors = []
  let backend = null
  let vite = null
  let backendLogs = null
  let viteLogs = null
  let backendState = null
  let viteState = null
  let corpusRoot = null
  let corpusRootOwned = false
  let childEnvironment = null
  let values = []
  let databaseLifecycleStarted = false
  let corpusPrefix = null
  const reservations = []
  const releasedReservations = new Set()
  const tempParent = path.resolve(os.tmpdir())

  const releaseReservation = async reservation => {
    if (!reservation || releasedReservations.has(reservation)) return
    releasedReservations.add(reservation)
    await reservation.release()
  }

  try {
    const nonce = nonceFactory()
    if (
      typeof nonce !== 'string'
      || nonce.length === 0
      || !/^[A-Za-z0-9_-]+$/.test(nonce)
    ) {
      throw new TypeError('M2 browser run nonce must be a non-empty path-safe string')
    }
    corpusPrefix = path.join(tempParent, `${CORPUS_PREFIX}${nonce}-`)
    assertExternalCorpusRoot(tempParent)
    corpusRoot = mkdtempImpl(corpusPrefix)
    corpusRoot = assertOwnedCorpusRoot(corpusRoot, corpusPrefix, tempParent)
    corpusRootOwned = true
    assertExternalCorpusRootImpl(corpusRoot)
    const backendReservation = await portReservationFactory()
    reservations.push(backendReservation)
    const viteReservation = await portReservationFactory()
    reservations.push(viteReservation)
    for (const reservation of reservations) {
      if (
        !Number.isInteger(reservation?.port)
        || reservation.port < 1
        || reservation.port > 65535
        || typeof reservation.release !== 'function'
      ) {
        throw new TypeError('M2 browser port reservation is invalid')
      }
    }
    if (backendReservation.port === viteReservation.port) {
      throw new Error('M2 browser backend and Vite ports must be distinct')
    }
    const backendUrl = `http://127.0.0.1:${backendReservation.port}`
    const viteUrl = `http://127.0.0.1:${viteReservation.port}`
    childEnvironment = {
      ...buildChildEnvironment(environment, databaseName, corpusRoot),
      M2_BROWSER_RUN_NONCE: nonce,
      VITE_API_BASE_URL: `${backendUrl}/api`,
      PLAYWRIGHT_BASE_URL: viteUrl,
    }
    values = runtimeSensitiveValues(childEnvironment)
    const corpusFile = path.join(corpusRoot, 'synthetic-browser-corpus.txt')
    writeFileImpl(corpusFile, SYNTHETIC_CORPUS, 'utf8')
    databaseLifecycleStarted = true
    const preparation = await processRunner.run(
      python,
      prepareArgs,
      childOptions(repositoryRoot, childEnvironment),
      { sensitiveValues: values },
    )
    assertProcessResult('database preparation', preparation, values)

    await releaseReservation(backendReservation)
    backend = processRunner.start(
      python,
      [
        '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1',
        '--port', String(backendReservation.port),
      ],
      childOptions(repositoryRoot, childEnvironment),
      { label: 'backend' },
    )
    backendState = trackChildLifecycle(backend, 'backend')
    backendLogs = serverLogObserverFactory(backend, { sensitiveValues: values })
    await releaseReservation(viteReservation)
    vite = processRunner.start(
      process.execPath,
      [
        viteCli, '--host', '127.0.0.1', '--port', String(viteReservation.port),
        '--strictPort',
      ],
      childOptions(frontendRoot, childEnvironment),
      { label: 'vite' },
    )
    viteState = trackChildLifecycle(vite, 'vite')
    viteLogs = serverLogObserverFactory(vite, { sensitiveValues: values })
    const states = [backendState, viteState]
    await runWhileServicesLive(
      signal => waitForUrlImpl(`${backendUrl}/api/health`, {
        expectedNonce: nonce,
        signal,
      }),
      states,
    )
    await runWhileServicesLive(
      signal => waitForUrlImpl(`${viteUrl}/__m2-browser-owner`, {
        expectedNonce: nonce,
        signal,
      }),
      states,
    )

    const browser = await runWhileServicesLive(
      signal => processRunner.run(
        process.execPath,
        [playwrightCli, 'test', spec.path, '--config', 'playwright.m2.config.ts'],
        childOptions(frontendRoot, childEnvironment),
        { sensitiveValues: values, signal },
      ),
      states,
      {
        settleAbortedOperation(settledOperation) {
          if (!settledOperation.value) return
          const scanError = scanProcessResult(settledOperation.value, values)
          if (scanError) throw scanError
        },
      },
    )
    assertProcessResult('browser test', browser, values)
  } catch (error) {
    bodyErrors.push(error)
  } finally {
    for (const [child, state] of [[vite, viteState], [backend, backendState]]) {
      if (!child) continue
      const earlyFailure = markStopRequested(state)
      if (earlyFailure && !state.earlyFailureObserved) {
        state.earlyFailureObserved = true
        serverErrors.push(earlyFailure)
      }
      try {
        await processRunner.stop(child)
      } catch (error) {
        serverErrors.push(error)
      }
      if (state?.supportsEvents) {
        try {
          await waitForLifecycleClose(state, 5_000)
        } catch (error) {
          serverErrors.push(error)
        }
      }
    }
    for (const reservation of reservations) {
      try {
        await releaseReservation(reservation)
      } catch (error) {
        serverErrors.push(error)
      }
    }
    for (const observer of [backendLogs, viteLogs]) {
      if (!observer) continue
      try {
        const scan = observer.finish(values)
        if (scan.matchCount !== 0) {
          serverErrors.push(
            new Error(`server log sensitive match count was ${scan.matchCount}`),
          )
        }
      } catch (error) {
        serverErrors.push(error)
      }
    }

    if (databaseLifecycleStarted) {
      try {
        const cleanup = await processRunner.run(
          python,
          cleanupArgs,
          childOptions(repositoryRoot, childEnvironment),
          { sensitiveValues: values },
        )
        assertProcessResult('database cleanup', cleanup, values)
      } catch (error) {
        bodyErrors.push({ cleanup: true, error })
      }
    }

    if (corpusRootOwned) {
      try {
        const ownedRoot = assertOwnedCorpusRoot(corpusRoot, corpusPrefix, tempParent)
        await rmImpl(ownedRoot, { recursive: true, force: true })
      } catch (error) {
        bodyErrors.push({ directoryCleanup: true, error })
      }
    }
  }

  const errors = []
  const ordinaryBodyErrors = bodyErrors.filter(item => !item?.cleanup && !item?.directoryCleanup)
  errors.push(...ordinaryBodyErrors)
  if (serverErrors.length === 1) errors.push(serverErrors[0])
  if (serverErrors.length > 1) {
    errors.push(new AggregateError(serverErrors, 'M2 browser server stop or scan failed'))
  }
  errors.push(...bodyErrors.filter(item => item?.cleanup).map(item => item.error))
  errors.push(...bodyErrors.filter(item => item?.directoryCleanup).map(item => item.error))
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(errors, 'M2 browser body and cleanup operations failed')
  }
}


export async function runMilestone2({
  specs,
  environment = process.env,
  databaseNameFactory = createDatabaseName,
  mkdtempImpl = mkdtempSync,
  writeFileImpl = writeFileSync,
  rmImpl = rmSync,
  processRunner = defaultProcessRunner,
  waitForUrlImpl = waitForOwnedUrl,
  serverLogObserverFactory = createServerLogObserver,
  portReservationFactory = reserveLocalPort,
  nonceFactory = randomUUID,
  assertExternalCorpusRootImpl = assertExternalCorpusRoot,
} = {}) {
  validateTestEnvironment(environment)
  const closedSpecs = validateSpecs(specs)
  const usedDatabases = new Set()
  const independentDatabaseNameFactory = () => {
    const databaseName = databaseNameFactory()
    assertDatabaseName(databaseName)
    if (usedDatabases.has(databaseName)) {
      throw new Error('Every M2 spec requires an independent disposable database')
    }
    usedDatabases.add(databaseName)
    return databaseName
  }
  for (const spec of closedSpecs) {
    await runOneSpec({
      spec,
      environment,
      databaseNameFactory: independentDatabaseNameFactory,
      mkdtempImpl,
      writeFileImpl,
      rmImpl,
      processRunner,
      waitForUrlImpl,
      serverLogObserverFactory,
      portReservationFactory,
      nonceFactory,
      assertExternalCorpusRootImpl,
    })
  }
  return 0
}


const isMain = process.argv[1]
  && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  let specs
  try {
    specs = resolveCommandLineSpecs(process.argv.slice(2))
  } catch {
    console.error('M2 browser runner does not accept spec paths.')
    process.exitCode = 2
  }
  if (specs) runMilestone2({ specs }).then(
    status => { process.exitCode = status },
    () => {
      console.error('M2 browser runner failed.')
      process.exitCode = 1
    },
  )
}

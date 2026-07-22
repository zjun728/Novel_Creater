import { randomUUID } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  assertDatabaseName as assertProductShellDatabaseName,
  createDatabaseName as createProductShellDatabaseName,
  defaultProcessRunner as neutralDefaultProcessRunner,
  normalizedDeadlines as neutralNormalizedDeadlines,
  ownedChildOptions as neutralOwnedChildOptions,
  REQUIRED_TEST_VARIABLES,
  reserveLocalPort,
  runBoundedOwnedCommand,
  spawnOwnedChild as neutralSpawnOwnedChild,
  startOwnedServer as startNeutralOwnedServer,
  stopOwnedServer as stopNeutralOwnedServer,
  terminateOwnedProcessTree as neutralTerminateOwnedProcessTree,
  validateTestEnvironment,
  waitForOwnedServer,
  waitForOwnedUrl,
} from './support/product-runner.mjs'
import { createServerLogObserver } from './server-log-observer.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'


export {
  assertProductShellDatabaseName,
  createProductShellDatabaseName,
  REQUIRED_TEST_VARIABLES,
  neutralOwnedChildOptions as ownedChildOptions,
  neutralSpawnOwnedChild as spawnOwnedChild,
  neutralTerminateOwnedProcessTree as terminateOwnedProcessTree,
}

export const FORMAL_SPECS = Object.freeze([
  'e2e/product-shell-lifecycle.spec.ts',
])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
export const PRODUCT_SHELL_SECRET_SENTINEL = 'product-shell-browser-secret-sentinel'
export const BASE_ENV_ALLOWLIST = Object.freeze([
  'PATH',
  'Path',
  'PATHEXT',
  'SystemRoot',
  'SYSTEMROOT',
  'WINDIR',
  'COMSPEC',
  'ComSpec',
  'TEMP',
  'TMP',
  'TMPDIR',
  'HOME',
  'USERPROFILE',
  'LOCALAPPDATA',
  'APPDATA',
  'VIRTUAL_ENV',
  'PYTHONPATH',
  'PYTHONHOME',
  'PYTHONUTF8',
  'PYTHONIOENCODING',
  'PLAYWRIGHT_BROWSERS_PATH',
  'LANG',
  'LC_ALL',
  'TZ',
])
export const DEFAULT_RUNNER_DEADLINES = Object.freeze({
  prepareMs: 60_000,
  healthMs: 45_000,
  browserMs: 180_000,
  cleanupMs: 60_000,
  stopMs: 5_000,
  settleMs: 15_000,
})


export function validateSpecs(specs) {
  if (
    !Array.isArray(specs)
    || specs.length !== FORMAL_SPECS.length
    || specs.some((spec, index) => spec !== FORMAL_SPECS[index])
  ) {
    throw new Error('Product-shell browser requires the exact formal spec path')
  }
  return [...FORMAL_SPECS]
}


export function resolveCommandLineSpecs(argumentsList) {
  if (!Array.isArray(argumentsList)) {
    throw new TypeError('Product-shell browser CLI arguments must be an array')
  }
  if (argumentsList.length !== 0) {
    throw new Error('Product-shell browser runner does not accept spec paths')
  }
  return [...FORMAL_SPECS]
}


function childOptions(cwd, env) {
  return neutralOwnedChildOptions({
    cwd,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
}


function allowlistedBaseEnvironment(environment) {
  return Object.fromEntries(
    BASE_ENV_ALLOWLIST
      .filter(name => Object.hasOwn(environment, name))
      .map(name => [name, environment[name]]),
  )
}


function buildProcessEnvironments(environment, databaseName, backendUrl, viteUrl, nonce) {
  validateTestEnvironment(environment)
  assertProductShellDatabaseName(databaseName)
  const base = allowlistedBaseEnvironment(environment)
  const prepare = {
    ...base,
    TEST_MYSQL_HOST: environment.TEST_MYSQL_HOST,
    TEST_MYSQL_PORT: environment.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: environment.TEST_MYSQL_USER,
    TEST_MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
  }
  const backend = {
    ...base,
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName,
    M2_BROWSER_RUN_NONCE: nonce,
  }
  const vite = {
    ...base,
    M2_BROWSER_RUN_NONCE: nonce,
    VITE_API_BASE_URL: `${backendUrl}/api`,
  }
  const browser = {
    ...base,
    PLAYWRIGHT_BASE_URL: viteUrl,
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_SECRET_SENTINEL: PRODUCT_SHELL_SECRET_SENTINEL,
  }
  return {
    prepare,
    backend,
    vite,
    browser,
    sensitiveController: {
      MYSQL_HOST: environment.TEST_MYSQL_HOST,
      MYSQL_PORT: environment.TEST_MYSQL_PORT,
      MYSQL_USER: environment.TEST_MYSQL_USER,
      MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
      MYSQL_DB: databaseName,
      BROWSER_TEST_DATABASE: databaseName,
      BROWSER_SECRET_SENTINEL: PRODUCT_SHELL_SECRET_SENTINEL,
    },
  }
}


async function runOneSpec({
  spec,
  environment,
  databaseNameFactory,
  portReservationFactory,
  processRunner,
  waitForUrlImpl,
  serverLogObserverFactory,
  nonceFactory,
  deadlines,
}) {
  const databaseName = databaseNameFactory()
  assertProductShellDatabaseName(databaseName)
  const nonce = nonceFactory()
  if (
    typeof nonce !== 'string'
    || nonce.length === 0
    || !/^[A-Za-z0-9_-]+$/u.test(nonce)
  ) {
    throw new TypeError('Product-shell browser nonce must be a path-safe string')
  }

  const reservations = []
  const released = new Set()
  const bodyErrors = []
  const cleanupErrors = []
  const serverErrors = []
  const ownedServers = []
  let databaseLifecycleStarted = false
  let processEnvironments
  let sensitiveValues = []

  const releaseReservation = async reservation => {
    if (!reservation || released.has(reservation)) return
    released.add(reservation)
    await reservation.release()
  }

  try {
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
        throw new TypeError('Product-shell browser port reservation is invalid')
      }
    }
    if (backendReservation.port === viteReservation.port) {
      throw new Error('Product-shell backend and Vite ports must be distinct')
    }

    const backendUrl = `http://127.0.0.1:${backendReservation.port}`
    const viteUrl = `http://127.0.0.1:${viteReservation.port}`
    processEnvironments = buildProcessEnvironments(
      environment,
      databaseName,
      backendUrl,
      viteUrl,
      nonce,
    )
    sensitiveValues = runtimeSensitiveValues(processEnvironments.sensitiveController)
    const python = environment.PYTHON || 'python'
    const prepareArgs = [
      '-m',
      'backend.scripts.prepare_product_shell_browser_db',
      '--database',
      databaseName,
    ]
    const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')
    const viteCli = path.join(frontendRoot, 'node_modules', 'vite', 'bin', 'vite.js')

    databaseLifecycleStarted = true
    await runBoundedOwnedCommand(
      python,
      prepareArgs,
      childOptions(repositoryRoot, processEnvironments.prepare),
      {
        label: 'database preparation',
        sensitiveValues,
        timeoutMs: deadlines.prepareMs,
        settleMs: deadlines.settleMs,
        stopTimeoutMs: deadlines.stopMs,
        processRunner,
      },
    )

    await releaseReservation(backendReservation)
    const backend = startNeutralOwnedServer(
      python,
      [
        '-m',
        'uvicorn',
        'backend.main:app',
        '--host',
        '127.0.0.1',
        '--port',
        String(backendReservation.port),
      ],
      childOptions(repositoryRoot, processEnvironments.backend),
      {
        label: 'backend',
        sensitiveValues,
        processRunner,
        serverLogObserverFactory,
      },
    )
    ownedServers.push(backend)

    await releaseReservation(viteReservation)
    const vite = startNeutralOwnedServer(
      process.execPath,
      [
        viteCli,
        '--host',
        '127.0.0.1',
        '--port',
        String(viteReservation.port),
        '--strictPort',
      ],
      childOptions(frontendRoot, processEnvironments.vite),
      {
        label: 'vite',
        sensitiveValues,
        processRunner,
        serverLogObserverFactory,
      },
    )
    ownedServers.push(vite)

    await waitForOwnedServer(backend, `${backendUrl}/api/health`, {
      expectedNonce: nonce,
      timeoutMs: deadlines.healthMs,
      settleMs: deadlines.settleMs,
      waitForUrlImpl,
      states: ownedServers,
    })
    await waitForOwnedServer(vite, `${viteUrl}/__m2-browser-owner`, {
      expectedNonce: nonce,
      timeoutMs: deadlines.healthMs,
      settleMs: deadlines.settleMs,
      waitForUrlImpl,
      states: ownedServers,
    })

    await runBoundedOwnedCommand(
      process.execPath,
      [
        playwrightCli,
        'test',
        spec,
        '--config',
        'playwright.product-shell.config.ts',
      ],
      childOptions(frontendRoot, processEnvironments.browser),
      {
        label: 'browser test',
        sensitiveValues,
        timeoutMs: deadlines.browserMs,
        settleMs: deadlines.settleMs,
        stopTimeoutMs: deadlines.stopMs,
        processRunner,
        states: ownedServers,
      },
    )
  } catch (error) {
    bodyErrors.push(error)
  } finally {
    for (const server of [...ownedServers].reverse()) {
      try {
        await stopNeutralOwnedServer(server, {
          sensitiveValues,
          timeoutMs: deadlines.stopMs,
        })
      } catch (error) {
        serverErrors.push(error)
      }
    }
    for (const reservation of reservations) {
      try {
        await releaseReservation(reservation)
      } catch (error) {
        serverErrors.push(error)
      }
    }
    if (databaseLifecycleStarted) {
      try {
        const python = environment.PYTHON || 'python'
        await runBoundedOwnedCommand(
          python,
          [
            '-m',
            'backend.scripts.prepare_product_shell_browser_db',
            '--database',
            databaseName,
            '--drop',
          ],
          childOptions(repositoryRoot, processEnvironments.prepare),
          {
            label: 'database cleanup',
            sensitiveValues,
            timeoutMs: deadlines.cleanupMs,
            settleMs: deadlines.settleMs,
            stopTimeoutMs: deadlines.stopMs,
            processRunner,
          },
        )
      } catch (error) {
        cleanupErrors.push(error)
      }
    }
  }

  const errors = [...bodyErrors]
  if (serverErrors.length === 1) errors.push(serverErrors[0])
  if (serverErrors.length > 1) {
    errors.push(new AggregateError(serverErrors, 'owned server stop or log scan failed'))
  }
  errors.push(...cleanupErrors)
  if (errors.length === 1) throw errors[0]
  if (errors.length > 1) {
    throw new AggregateError(errors, 'Product-shell browser body and cleanup failed')
  }
}


export async function runProductShell({
  specs = FORMAL_SPECS,
  environment = process.env,
  databaseNameFactory = createProductShellDatabaseName,
  portReservationFactory = reserveLocalPort,
  processRunner = neutralDefaultProcessRunner,
  waitForUrlImpl = waitForOwnedUrl,
  serverLogObserverFactory = createServerLogObserver,
  nonceFactory = randomUUID,
  deadlines,
} = {}) {
  validateTestEnvironment(environment)
  const formalSpecs = validateSpecs(specs)
  const runnerDeadlines = neutralNormalizedDeadlines(deadlines)
  const usedDatabases = new Set()
  const independentDatabaseNameFactory = () => {
    const databaseName = databaseNameFactory()
    assertProductShellDatabaseName(databaseName)
    if (usedDatabases.has(databaseName)) {
      throw new Error('Every product-shell spec requires a fresh disposable database')
    }
    usedDatabases.add(databaseName)
    return databaseName
  }
  for (const spec of formalSpecs) {
    await runOneSpec({
      spec,
      environment,
      databaseNameFactory: independentDatabaseNameFactory,
      portReservationFactory,
      processRunner,
      waitForUrlImpl,
      serverLogObserverFactory,
      nonceFactory,
      deadlines: runnerDeadlines,
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
    console.error('Product-shell browser runner does not accept spec paths.')
    process.exitCode = 2
  }
  if (specs) {
    runProductShell({ specs }).then(
      status => { process.exitCode = status },
      () => {
        console.error('Product-shell browser runner failed.')
        process.exitCode = 1
      },
    )
  }
}

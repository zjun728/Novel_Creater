import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import {
  assertDatabaseName as assertProductShellDatabaseName,
  createDatabaseName as createProductShellDatabaseName,
  defaultRun,
  REQUIRED_TEST_VARIABLES,
  reserveLocalPort,
  validateTestEnvironment,
  waitForOwnedUrl,
} from './run-milestone2.mjs'
import { createServerLogObserver } from './server-log-observer.mjs'
import { runtimeSensitiveValues } from './runtime-observer.mjs'


export {
  assertProductShellDatabaseName,
  createProductShellDatabaseName,
  REQUIRED_TEST_VARIABLES,
}

export const FORMAL_SPECS = Object.freeze([
  'e2e/product-shell-lifecycle.spec.ts',
])

const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')
const SECRET_SENTINEL = 'product-shell-browser-secret-sentinel'


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
  return {
    cwd,
    env,
    shell: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  }
}


function buildChildEnvironment(environment, databaseName, backendUrl, viteUrl, nonce) {
  validateTestEnvironment(environment)
  assertProductShellDatabaseName(databaseName)
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
    BROWSER_SECRET_SENTINEL: SECRET_SENTINEL,
    M2_BROWSER_RUN_NONCE: nonce,
    VITE_API_BASE_URL: `${backendUrl}/api`,
    PLAYWRIGHT_BASE_URL: viteUrl,
  }
}


function processFailure(label, result, sensitiveValues) {
  const errors = []
  if (result?.error) {
    errors.push(new Error(`${label} process failed to start`, { cause: result.error }))
  } else if (result?.status !== 0) {
    errors.push(new Error(`${label} process exited with status ${String(result?.status)}`))
  }
  if (result?.logObserver) {
    const scan = result.logObserver.finish(sensitiveValues)
    if (scan.matchCount !== 0) {
      errors.push(new Error(`${label} process log contained runtime-sensitive values`))
    }
  }
  if (errors.length === 1) return errors[0]
  if (errors.length > 1) {
    return new AggregateError(errors, `${label} process and log scan failed`)
  }
  return null
}


async function waitForChildClose(child, timeoutMs = 5_000) {
  if (!child || child.exitCode !== null && child.exitCode !== undefined) return
  await new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error('owned server did not close before timeout')),
      timeoutMs,
    )
    child.once('close', () => {
      clearTimeout(timer)
      resolve()
    })
  })
}


const defaultProcessRunner = {
  run: defaultRun,
  start(command, args, options) {
    return spawn(command, args, options)
  },
  async stop(child) {
    if (!child) return
    if (child.exitCode === null || child.exitCode === undefined) {
      if (child.kill('SIGTERM') === false) {
        throw new Error('owned server rejected stop signal')
      }
    }
    try {
      await waitForChildClose(child)
    } catch (gracefulError) {
      if (child.exitCode === null || child.exitCode === undefined) {
        child.kill('SIGKILL')
      }
      try {
        await waitForChildClose(child)
      } catch (forcedError) {
        throw new AggregateError(
          [gracefulError, forcedError],
          'owned server graceful and forced stop both failed',
        )
      }
    }
  },
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
  const children = []
  const serverObservers = []
  let databaseLifecycleStarted = false
  let childEnvironment
  let sensitiveValues = []

  const releaseReservation = async reservation => {
    if (!reservation || released.has(reservation)) return
    released.add(reservation)
    await reservation.release()
  }

  try {
    const backendReservation = await portReservationFactory()
    const viteReservation = await portReservationFactory()
    reservations.push(backendReservation, viteReservation)
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
    childEnvironment = buildChildEnvironment(
      environment,
      databaseName,
      backendUrl,
      viteUrl,
      nonce,
    )
    sensitiveValues = runtimeSensitiveValues(childEnvironment)
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
    const preparation = await processRunner.run(
      python,
      prepareArgs,
      childOptions(repositoryRoot, childEnvironment),
      { sensitiveValues },
    )
    const preparationError = processFailure(
      'database preparation',
      preparation,
      sensitiveValues,
    )
    if (preparationError) throw preparationError

    await releaseReservation(backendReservation)
    const backend = processRunner.start(
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
      childOptions(repositoryRoot, childEnvironment),
      { label: 'backend' },
    )
    children.push(backend)
    serverObservers.push(serverLogObserverFactory(backend, { sensitiveValues }))

    await releaseReservation(viteReservation)
    const vite = processRunner.start(
      process.execPath,
      [
        viteCli,
        '--host',
        '127.0.0.1',
        '--port',
        String(viteReservation.port),
        '--strictPort',
      ],
      childOptions(frontendRoot, childEnvironment),
      { label: 'vite' },
    )
    children.push(vite)
    serverObservers.push(serverLogObserverFactory(vite, { sensitiveValues }))

    await waitForUrlImpl(`${backendUrl}/api/health`, {
      expectedNonce: nonce,
    })
    await waitForUrlImpl(`${viteUrl}/__m2-browser-owner`, {
      expectedNonce: nonce,
    })

    const browser = await processRunner.run(
      process.execPath,
      [
        playwrightCli,
        'test',
        spec,
        '--config',
        'playwright.product-shell.config.ts',
      ],
      childOptions(frontendRoot, childEnvironment),
      { sensitiveValues },
    )
    const browserError = processFailure('browser test', browser, sensitiveValues)
    if (browserError) throw browserError
  } catch (error) {
    bodyErrors.push(error)
  } finally {
    for (const child of [...children].reverse()) {
      try {
        await processRunner.stop(child)
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
    for (const observer of serverObservers) {
      try {
        const scan = observer.finish(sensitiveValues)
        if (scan.matchCount !== 0) {
          serverErrors.push(
            new Error('owned server log contained runtime-sensitive values'),
          )
        }
      } catch (error) {
        serverErrors.push(error)
      }
    }
    if (databaseLifecycleStarted) {
      try {
        const python = environment.PYTHON || 'python'
        const cleanup = await processRunner.run(
          python,
          [
            '-m',
            'backend.scripts.prepare_product_shell_browser_db',
            '--database',
            databaseName,
            '--drop',
          ],
          childOptions(repositoryRoot, childEnvironment),
          { sensitiveValues },
        )
        const cleanupError = processFailure(
          'database cleanup',
          cleanup,
          sensitiveValues,
        )
        if (cleanupError) cleanupErrors.push(cleanupError)
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
  processRunner = defaultProcessRunner,
  waitForUrlImpl = waitForOwnedUrl,
  serverLogObserverFactory = createServerLogObserver,
  nonceFactory = randomUUID,
} = {}) {
  validateTestEnvironment(environment)
  const formalSpecs = validateSpecs(specs)
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

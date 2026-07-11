import { spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const REQUIRED_TEST_VARIABLES = [
  'TEST_MYSQL_HOST',
  'TEST_MYSQL_PORT',
  'TEST_MYSQL_USER',
  'TEST_MYSQL_PASSWORD',
]
const DISPOSABLE_DATABASE = /^novel_creator_test_[a-f0-9]{32}$/
const BROWSER_SECRET_SENTINEL = 'browser-secret-must-not-leak'
const BROWSER_PRIVATE_PROVIDER_URL = 'https://private-provider.example/v1'
const frontendRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const repositoryRoot = path.resolve(frontendRoot, '..')

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
  const databaseName = `novel_creator_test_${uuidFactory().replaceAll('-', '')}`
  assertDatabaseName(databaseName)
  return databaseName
}

export function buildChildEnvironment(environment, databaseName) {
  validateTestEnvironment(environment)
  assertDatabaseName(databaseName)
  const childEnvironment = Object.fromEntries(
    Object.entries(environment).filter(([name]) => !name.startsWith('MYSQL_')),
  )
  return {
    ...childEnvironment,
    MYSQL_HOST: environment.TEST_MYSQL_HOST,
    MYSQL_PORT: environment.TEST_MYSQL_PORT,
    MYSQL_USER: environment.TEST_MYSQL_USER,
    MYSQL_PASSWORD: environment.TEST_MYSQL_PASSWORD,
    MYSQL_DB: databaseName,
    BROWSER_TEST_DATABASE: databaseName,
    BROWSER_SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL,
  }
}

function processError(label, result) {
  if (result?.error) {
    return new Error(`${label} process failed to start: ${result.error.message}`, {
      cause: result.error,
    })
  }
  if (result?.status !== 0) {
    return new Error(`${label} process exited with status ${String(result?.status)}`)
  }
  return null
}

function spawnOptions(cwd, env) {
  return {
    cwd,
    env,
    shell: false,
    stdio: 'inherit',
  }
}

export function runMilestone1({
  environment = process.env,
  databaseNameFactory = createDatabaseName,
  spawnSyncImpl = spawnSync,
} = {}) {
  validateTestEnvironment(environment)
  const databaseName = databaseNameFactory()
  assertDatabaseName(databaseName)
  const childEnvironment = buildChildEnvironment(environment, databaseName)
  const python = environment.PYTHON || 'python'
  const prepareArgs = [
    '-m',
    'backend.scripts.prepare_milestone1_browser_db',
    '--database',
    databaseName,
  ]
  const cleanupArgs = [...prepareArgs, '--drop']
  const playwrightCli = path.join(frontendRoot, 'node_modules', 'playwright', 'cli.js')

  let bodyError = null
  let cleanupError = null
  try {
    const preparation = spawnSyncImpl(
      python,
      prepareArgs,
      spawnOptions(repositoryRoot, childEnvironment),
    )
    const preparationError = processError('database preparation', preparation)
    if (preparationError) throw preparationError

    const browser = spawnSyncImpl(
      process.execPath,
      [playwrightCli, 'test', 'e2e/milestone1.spec.ts'],
      spawnOptions(frontendRoot, childEnvironment),
    )
    const browserError = processError('browser test', browser)
    if (browserError) throw browserError
  } catch (error) {
    bodyError = error
  } finally {
    try {
      const cleanup = spawnSyncImpl(
        python,
        cleanupArgs,
        spawnOptions(repositoryRoot, childEnvironment),
      )
      cleanupError = processError('cleanup', cleanup)
    } catch (error) {
      cleanupError = error
    }
  }

  if (bodyError && cleanupError) {
    throw new AggregateError(
      [bodyError, cleanupError],
      `M1 browser test and cleanup both failed for ${databaseName}`,
    )
  }
  if (bodyError) throw bodyError
  if (cleanupError) throw cleanupError
  return 0
}

const isMain = process.argv[1]
  && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  try {
    process.exitCode = runMilestone1()
  } catch (error) {
    console.error(error instanceof AggregateError ? error : error.message)
    process.exitCode = 1
  }
}

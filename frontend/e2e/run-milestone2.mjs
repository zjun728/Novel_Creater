import { spawn } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import {
  mkdtempSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { createServerLogObserver } from './server-log-observer.mjs'


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


function defaultRun(command, args, options, { sensitiveValues = [] } = {}) {
  return new Promise(resolve => {
    const child = spawn(command, args, options)
    const logObserver = createServerLogObserver(child, { sensitiveValues })
    let spawnError = null
    child.once('error', error => {
      spawnError = error
    })
    child.once('close', code => {
      resolve({ status: code, error: spawnError, logObserver })
    })
  })
}


function waitForClose(child, timeoutMs) {
  if (child.exitCode !== null && child.exitCode !== undefined) return Promise.resolve()
  return new Promise((resolve, reject) => {
    let timer
    const clean = () => {
      clearTimeout(timer)
      child.off?.('close', onClose)
      child.off?.('error', onError)
    }
    const onClose = () => {
      clean()
      resolve()
    }
    const onError = error => {
      clean()
      reject(error)
    }
    child.once?.('close', onClose)
    child.once?.('error', onError)
    timer = setTimeout(() => {
      clean()
      reject(new Error('server stop timed out'))
    }, timeoutMs)
  })
}


async function defaultStop(child) {
  if (!child || (child.exitCode !== null && child.exitCode !== undefined)) return
  if (child.kill('SIGTERM') === false) throw new Error('server rejected stop signal')
  try {
    await waitForClose(child, 5_000)
  } catch (gracefulError) {
    if (child.exitCode === null || child.exitCode === undefined) child.kill('SIGKILL')
    try {
      await waitForClose(child, 5_000)
    } catch (forcedError) {
      throw new AggregateError(
        [gracefulError, forcedError],
        'server graceful and forced stop both failed',
      )
    }
  }
}


const defaultProcessRunner = {
  run: defaultRun,
  start(command, args, options) {
    return spawn(command, args, options)
  },
  stop: defaultStop,
}


export async function waitForUrl(url, {
  fetchImpl = fetch,
  timeoutMs = 30_000,
  intervalMs = 100,
} = {}) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    try {
      const response = await fetchImpl(url)
      if (response.ok) return
    } catch {
      // A refused connection is expected while the owned process starts.
    }
    await new Promise(resolve => setTimeout(resolve, intervalMs))
  }
  throw new Error('owned browser server did not become healthy before timeout')
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


function sensitiveValues(corpusRoot) {
  return [
    BROWSER_SECRET_SENTINEL,
    BROWSER_PRIVATE_PROVIDER_URL,
    BROWSER_CORPUS_ROOT_SENTINEL,
    corpusRoot,
  ]
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
}) {
  const databaseName = databaseNameFactory()
  assertDatabaseName(databaseName)
  const corpusRoot = mkdtempImpl(path.join(os.tmpdir(), CORPUS_PREFIX))
  assertExternalCorpusRoot(corpusRoot)
  const childEnvironment = buildChildEnvironment(environment, databaseName, corpusRoot)
  const values = sensitiveValues(corpusRoot)
  const corpusFile = path.join(corpusRoot, 'synthetic-browser-corpus.txt')
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

  try {
    writeFileImpl(corpusFile, SYNTHETIC_CORPUS, 'utf8')
    const preparation = await processRunner.run(
      python,
      prepareArgs,
      childOptions(repositoryRoot, childEnvironment),
      { sensitiveValues: values },
    )
    assertProcessResult('database preparation', preparation, values)

    backend = processRunner.start(
      python,
      ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000'],
      childOptions(repositoryRoot, childEnvironment),
    )
    backendLogs = serverLogObserverFactory(backend, { sensitiveValues: values })
    vite = processRunner.start(
      process.execPath,
      [viteCli, '--host', '127.0.0.1', '--port', '5173', '--strictPort'],
      childOptions(frontendRoot, childEnvironment),
    )
    viteLogs = serverLogObserverFactory(vite, { sensitiveValues: values })
    await waitForUrlImpl('http://127.0.0.1:8000/api/health')
    await waitForUrlImpl('http://127.0.0.1:5173')

    const browser = await processRunner.run(
      process.execPath,
      [playwrightCli, 'test', spec.path, '--config', 'playwright.m2.config.ts'],
      childOptions(frontendRoot, childEnvironment),
      { sensitiveValues: values },
    )
    assertProcessResult('browser test', browser, values)
  } catch (error) {
    bodyErrors.push(error)
  } finally {
    for (const child of [vite, backend]) {
      if (!child) continue
      try {
        await processRunner.stop(child)
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

    try {
      await rmImpl(corpusRoot, { recursive: true, force: true })
    } catch (error) {
      bodyErrors.push({ directoryCleanup: true, error })
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
  waitForUrlImpl = waitForUrl,
  serverLogObserverFactory = createServerLogObserver,
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

import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { runSuites } from '../run-tests.mjs'

const scriptsDirectory = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const repositoryRoot = path.dirname(scriptsDirectory)
const runnerModule = '../../frontend/e2e/run-product-shell.mjs'
const DATABASE_A = 'novel_creator_test_0123456789abcdef0123456789abcdef'
const DATABASE_B = 'novel_creator_test_fedcba9876543210fedcba9876543210'
const TEST_ENVIRONMENT = Object.freeze({
  TEST_MYSQL_HOST: '127.0.0.1',
  TEST_MYSQL_PORT: '33060',
  TEST_MYSQL_USER: 'root',
  TEST_MYSQL_PASSWORD: 'test-only-secret',
  MYSQL_HOST: 'product-host',
  MYSQL_PORT: '3306',
  MYSQL_USER: 'product-user',
  MYSQL_PASSWORD: 'product-secret',
  MYSQL_DB: 'novel_creator',
})

function fakeResult(status = 0) {
  return {
    status,
    error: null,
    logObserver: {
      finish(values) {
        assert.ok(values.includes(TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD))
        return { matchCount: 0, truncated: false }
      },
    },
  }
}

function fakeChild(label) {
  const child = new EventEmitter()
  child.label = label
  child.stdout = new EventEmitter()
  child.stderr = new EventEmitter()
  child.exitCode = null
  return child
}

function createHarness({
  databases = [DATABASE_A],
  ports = [41001, 41002],
  browserStatus = 0,
} = {}) {
  const events = []
  const databaseQueue = [...databases]
  const portQueue = [...ports]
  const children = []
  const observerFinishes = []
  const processRunner = {
    async run(command, args, options, runtime) {
      events.push({ kind: 'run', command, args: [...args], options, runtime })
      if (args.some(argument => /playwright[\\/]cli\.js$/u.test(String(argument)))) {
        return fakeResult(browserStatus)
      }
      return fakeResult()
    },
    start(command, args, options, metadata) {
      const child = fakeChild(metadata.label)
      children.push(child)
      events.push({ kind: 'start', command, args: [...args], options, metadata, child })
      return child
    },
    async stop(child) {
      events.push({ kind: 'stop', child })
    },
  }
  const reservations = []
  const portReservationFactory = async () => {
    const port = portQueue.shift()
    const reservation = {
      port,
      releaseCalls: 0,
      async release() {
        this.releaseCalls += 1
      },
    }
    reservations.push(reservation)
    return reservation
  }
  const healthCalls = []
  const waitForUrlImpl = async (url, options) => {
    healthCalls.push({ url, options })
  }
  const serverLogObserverFactory = (_child, { sensitiveValues }) => ({
    finish(values) {
      observerFinishes.push({ sensitiveValues, values })
      return { matchCount: 0, truncated: false }
    },
  })

  return {
    children,
    databaseNameFactory() {
      return databaseQueue.shift()
    },
    events,
    healthCalls,
    observerFinishes,
    portReservationFactory,
    processRunner,
    reservations,
    serverLogObserverFactory,
    waitForUrlImpl,
  }
}

test('product-shell runner exports one exact frozen formal spec', async () => {
  const runner = await import(runnerModule)

  assert.deepEqual(
    runner.FORMAL_SPECS,
    Object.freeze(['e2e/product-shell-lifecycle.spec.ts']),
  )
  assert.equal(Object.isFrozen(runner.FORMAL_SPECS), true)
  assert.deepEqual(runner.resolveCommandLineSpecs([]), [
    'e2e/product-shell-lifecycle.spec.ts',
  ])
  assert.throws(
    () => runner.resolveCommandLineSpecs(['e2e/other.spec.ts']),
    /does not accept spec paths/i,
  )
  assert.throws(
    () => runner.validateSpecs(['../../arbitrary.spec.ts']),
    /exact|formal|path/i,
  )
})

test('missing TEST_MYSQL authority fails before database, port, or process ownership starts', async () => {
  const runner = await import(runnerModule)

  for (const missingName of runner.REQUIRED_TEST_VARIABLES) {
    const environment = { ...TEST_ENVIRONMENT }
    delete environment[missingName]
    let databaseCalls = 0
    let portCalls = 0
    let processCalls = 0

    await assert.rejects(
      runner.runProductShell({
        specs: runner.FORMAL_SPECS,
        environment,
        databaseNameFactory() {
          databaseCalls += 1
          return DATABASE_A
        },
        portReservationFactory: async () => {
          portCalls += 1
          return { port: 41001, release: async () => {} }
        },
        processRunner: {
          run() { processCalls += 1 },
          start() { processCalls += 1 },
          stop() { processCalls += 1 },
        },
      }),
      new RegExp(missingName),
    )
    assert.equal(databaseCalls, 0)
    assert.equal(portCalls, 0)
    assert.equal(processCalls, 0)
  }
})

test('generated database names are exact lowercase disposable names', async () => {
  const runner = await import(runnerModule)
  const generated = runner.createProductShellDatabaseName(
    () => '01234567-89AB-CDEF-0123-456789ABCDEF',
  )

  assert.equal(generated, DATABASE_A)
  assert.match(generated, /^novel_creator_test_[a-f0-9]{32}$/)
  for (const unsafe of [
    'novel_creator',
    'novel_creater',
    '../novel_creator_test_0123456789abcdef0123456789abcdef',
    'novel_creator_test_0123456789ABCDEF0123456789ABCDEF',
  ]) {
    assert.throws(
      () => runner.assertProductShellDatabaseName(unsafe),
      /non-disposable/i,
    )
  }
})

test('one formal spec owns one fresh database, two distinct ports, nonce health, logs, and cleanup', async () => {
  const runner = await import(runnerModule)
  const harness = createHarness()

  assert.equal(await runner.runProductShell({
    specs: runner.FORMAL_SPECS,
    environment: TEST_ENVIRONMENT,
    databaseNameFactory: harness.databaseNameFactory,
    portReservationFactory: harness.portReservationFactory,
    processRunner: harness.processRunner,
    waitForUrlImpl: harness.waitForUrlImpl,
    serverLogObserverFactory: harness.serverLogObserverFactory,
    nonceFactory: () => 'product-shell-owner',
  }), 0)

  const runs = harness.events.filter(event => event.kind === 'run')
  const starts = harness.events.filter(event => event.kind === 'start')
  const stops = harness.events.filter(event => event.kind === 'stop')
  assert.equal(runs.length, 3)
  assert.equal(starts.length, 2)
  assert.deepEqual(starts.map(event => event.metadata.label), ['backend', 'vite'])
  assert.deepEqual(stops.map(event => event.child), harness.children.toReversed())

  const prepare = runs[0]
  const browser = runs[1]
  const cleanup = runs[2]
  assert.deepEqual(
    prepare.args.slice(0, 4),
    ['-m', 'backend.scripts.prepare_product_shell_browser_db', '--database', DATABASE_A],
  )
  assert.deepEqual(cleanup.args, [...prepare.args, '--drop'])
  assert.match(browser.args.join(' '), /product-shell-lifecycle\.spec\.ts/)
  assert.match(browser.args.join(' '), /playwright\.product-shell\.config\.ts/)

  const childEnvironment = starts[0].options.env
  assert.equal(childEnvironment.MYSQL_HOST, TEST_ENVIRONMENT.TEST_MYSQL_HOST)
  assert.equal(childEnvironment.MYSQL_PORT, TEST_ENVIRONMENT.TEST_MYSQL_PORT)
  assert.equal(childEnvironment.MYSQL_USER, TEST_ENVIRONMENT.TEST_MYSQL_USER)
  assert.equal(childEnvironment.MYSQL_PASSWORD, TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD)
  assert.equal(childEnvironment.MYSQL_DB, DATABASE_A)
  assert.equal(childEnvironment.BROWSER_TEST_DATABASE, DATABASE_A)
  assert.equal(childEnvironment.M2_BROWSER_RUN_NONCE, 'product-shell-owner')
  assert.equal(childEnvironment.MYSQL_DB === TEST_ENVIRONMENT.MYSQL_DB, false)

  assert.deepEqual(harness.reservations.map(item => item.port), [41001, 41002])
  assert.equal(harness.reservations.every(item => item.releaseCalls === 1), true)
  assert.deepEqual(
    harness.healthCalls.map(call => [call.url, call.options.expectedNonce]),
    [
      ['http://127.0.0.1:41001/api/health', 'product-shell-owner'],
      ['http://127.0.0.1:41002/__m2-browser-owner', 'product-shell-owner'],
    ],
  )
  assert.equal(harness.observerFinishes.length, 2)
  for (const scan of harness.observerFinishes) {
    assert.deepEqual(scan.values, scan.sensitiveValues)
    assert.ok(scan.values.includes(TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD))
    assert.ok(scan.values.includes(DATABASE_A))
  }
})

test('separate product-shell executions receive different databases', async () => {
  const runner = await import(runnerModule)
  const usedDatabases = []

  for (const database of [DATABASE_A, DATABASE_B]) {
    const harness = createHarness({ databases: [database] })
    await runner.runProductShell({
      specs: runner.FORMAL_SPECS,
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: harness.databaseNameFactory,
      portReservationFactory: harness.portReservationFactory,
      processRunner: harness.processRunner,
      waitForUrlImpl: harness.waitForUrlImpl,
      serverLogObserverFactory: harness.serverLogObserverFactory,
      nonceFactory: () => `owner-${usedDatabases.length}`,
    })
    const prepare = harness.events.find(event => event.kind === 'run')
    usedDatabases.push(prepare.args.at(-1))
  }

  assert.deepEqual(usedDatabases, [DATABASE_A, DATABASE_B])
  assert.equal(new Set(usedDatabases).size, 2)
})

test('browser failure still stops only owned children and drops only this database', async () => {
  const runner = await import(runnerModule)
  const harness = createHarness({ browserStatus: 7 })

  await assert.rejects(
    runner.runProductShell({
      specs: runner.FORMAL_SPECS,
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: harness.databaseNameFactory,
      portReservationFactory: harness.portReservationFactory,
      processRunner: harness.processRunner,
      waitForUrlImpl: harness.waitForUrlImpl,
      serverLogObserverFactory: harness.serverLogObserverFactory,
      nonceFactory: () => 'browser-failure-owner',
    }),
    /browser.*status 7/i,
  )

  const stops = harness.events.filter(event => event.kind === 'stop')
  const cleanup = harness.events
    .filter(event => event.kind === 'run')
    .find(event => event.args.includes('--drop'))
  assert.deepEqual(stops.map(event => event.child), harness.children.toReversed())
  assert.deepEqual(
    cleanup.args,
    [
      '-m',
      'backend.scripts.prepare_product_shell_browser_db',
      '--database',
      DATABASE_A,
      '--drop',
    ],
  )
})

test('dispatcher exposes a closed product-shell suite and fails before spawn without test MySQL', () => {
  const rootPackage = JSON.parse(readFileSync(path.join(repositoryRoot, 'package.json'), 'utf8'))
  const frontendPackage = JSON.parse(
    readFileSync(path.join(repositoryRoot, 'frontend', 'package.json'), 'utf8'),
  )
  assert.equal(
    rootPackage.scripts['test:browser:product-shell'],
    'node scripts/run-tests.mjs browser-product-shell',
  )
  assert.equal(frontendPackage.scripts['test:e2e:product-shell'], 'node e2e/run-product-shell.mjs')

  const environment = { ...TEST_ENVIRONMENT }
  delete environment.TEST_MYSQL_PASSWORD
  const calls = []
  let stderr = ''
  const exitCode = runSuites(['browser-product-shell'], {
    environment,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
    stderr: { write(chunk) { stderr += chunk } },
  })

  assert.equal(exitCode, 2)
  assert.deepEqual(calls, [])
  assert.match(stderr, /TEST_MYSQL_PASSWORD/)
  assert.doesNotMatch(stderr, new RegExp(TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD, 'u'))
})

test('dispatcher starts only the narrow product-shell runner after validating its formal spec', () => {
  const calls = []
  let stderr = ''
  const exitCode = runSuites(['browser-product-shell'], {
    environment: TEST_ENVIRONMENT,
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
    stderr: { write(chunk) { stderr += chunk } },
  })

  assert.equal(exitCode, 0, stderr)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0].args, ['frontend/e2e/run-product-shell.mjs'])
  assert.equal(calls[0].options.shell, false)
})

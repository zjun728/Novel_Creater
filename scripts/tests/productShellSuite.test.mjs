import assert from 'node:assert/strict'
import { spawn } from 'node:child_process'
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
  PATH: 'C:\\test-tools',
  SystemRoot: 'C:\\Windows',
  TEMP: 'C:\\Temp',
  TMP: 'C:\\Temp',
  USERPROFILE: 'C:\\Users\\browser-test',
  APPDATA: 'C:\\Users\\browser-test\\AppData\\Roaming',
  LOCALAPPDATA: 'C:\\Users\\browser-test\\AppData\\Local',
  PLAYWRIGHT_BROWSERS_PATH: 'C:\\playwright-browsers',
  PYTHONPATH: 'C:\\test-python-path',
  TEST_MYSQL_HOST: '127.0.0.1',
  TEST_MYSQL_PORT: '33060',
  TEST_MYSQL_USER: 'root',
  TEST_MYSQL_PASSWORD: 'test-only-secret',
  MYSQL_HOST: 'product-host',
  MYSQL_PORT: '3306',
  MYSQL_USER: 'product-user',
  MYSQL_PASSWORD: 'product-secret',
  MYSQL_DB: 'novel_creator',
  GITHUB_TOKEN: 'unrelated-parent-secret',
  AWS_SECRET_ACCESS_KEY: 'unrelated-cloud-secret',
})

function fakeResult(status = 0, { finishError = null } = {}) {
  return {
    status,
    error: null,
    logObserver: {
      finish(values) {
        assert.ok(values.includes(TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD))
        if (finishError) throw finishError
        return { matchCount: 0, truncated: false }
      },
    },
  }
}

function fakeChild(label, pid) {
  const child = new EventEmitter()
  child.label = label
  child.pid = pid
  child.stdout = new EventEmitter()
  child.stderr = new EventEmitter()
  child.exitCode = null
  child.closed = false
  return child
}

function closeFakeChild(child, code = 0, { emitExit = true } = {}) {
  if (child.closed) return
  child.exitCode = code
  if (emitExit) child.emit('exit', code, null)
  child.stdout.emit('end')
  child.stderr.emit('end')
  child.closed = true
  child.emit('close', code, null)
}

function createHarness({
  databases = [DATABASE_A],
  ports = [41001, 41002],
  browserStatus = 0,
  browserLogScanError = null,
  hangPhase = '',
  healthMode = 'resolve',
  serverFailure = null,
} = {}) {
  const events = []
  const databaseQueue = [...databases]
  const portQueue = [...ports]
  const children = []
  const observerFinishes = []
  const processRunner = {
    async run(command, args, options, runtime) {
      events.push({ kind: 'run', command, args: [...args], options, runtime })
      const isBrowser = args.some(argument => /playwright[\\/]cli\.js$/u.test(String(argument)))
      const isCleanup = args.includes('--drop')
      const phase = isBrowser ? 'browser' : isCleanup ? 'cleanup' : 'prepare'
      if (hangPhase === phase) return new Promise(() => {})
      if (isBrowser) {
        return fakeResult(browserStatus, { finishError: browserLogScanError })
      }
      return fakeResult()
    },
    start(command, args, options, metadata) {
      const child = fakeChild(metadata.label, 5300 + children.length)
      children.push(child)
      events.push({ kind: 'start', command, args: [...args], options, metadata, child })
      if (serverFailure?.label === metadata.label) {
        if (serverFailure.kind === 'error') child.on('error', () => {})
        queueMicrotask(() => {
          if (serverFailure.kind === 'error') {
            child.emit('error', new Error('synthetic spawn failure containing no credentials'))
            closeFakeChild(child, 1, { emitExit: false })
            return
          }
          closeFakeChild(child, serverFailure.code ?? 3)
        })
      }
      return child
    },
    async stop(child) {
      events.push({ kind: 'stop', child })
      closeFakeChild(child)
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
    if (healthMode === 'hang') return new Promise(() => {})
  }
  const serverLogObserverFactory = (child, { sensitiveValues }) => ({
    finish(values) {
      assert.equal(child.closed, true, 'server logs must be scanned only after close/drain')
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

function assertExactEnvironment(actual, expected) {
  assert.deepEqual(
    Object.fromEntries(Object.entries(actual).sort(([left], [right]) => left.localeCompare(right))),
    Object.fromEntries(Object.entries(expected).sort(([left], [right]) => left.localeCompare(right))),
  )
}

function boundedTestDeadlines() {
  return {
    prepareMs: 10,
    healthMs: 10,
    browserMs: 10,
    cleanupMs: 10,
    stopMs: 20,
    settleMs: 10,
  }
}

async function settleWithin(promise, timeoutMs = 500) {
  let timer
  try {
    return await Promise.race([
      promise.then(
        value => ({ status: 'resolved', value }),
        error => ({ status: 'rejected', error }),
      ),
      new Promise(resolve => {
        timer = setTimeout(() => resolve({ status: 'watchdog' }), timeoutMs)
      }),
    ])
  } finally {
    clearTimeout(timer)
  }
}

function processExists(pid) {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    if (error?.code === 'ESRCH') return false
    throw error
  }
}

async function waitForProcessGone(pid, timeoutMs = 750) {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (!processExists(pid)) return true
    await new Promise(resolve => setTimeout(resolve, 20))
  }
  return !processExists(pid)
}

async function terminateOwnedTestPid(pid) {
  if (!Number.isSafeInteger(pid) || pid <= 0 || !processExists(pid)) return
  await new Promise((resolve, reject) => {
    const terminator = spawn(
      'taskkill',
      ['/PID', String(pid), '/T', '/F'],
      {
        shell: false,
        windowsHide: true,
        stdio: 'ignore',
      },
    )
    terminator.once('error', reject)
    terminator.once('close', status => {
      if (status === 0 || !processExists(pid)) resolve()
      else reject(new Error('owned test descendant cleanup failed'))
    })
  })
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

test('second port reservation failure releases the first before DB or process start', async () => {
  const runner = await import(runnerModule)
  let reservationCalls = 0
  let releaseCalls = 0
  let processCalls = 0

  await assert.rejects(
    runner.runProductShell({
      specs: runner.FORMAL_SPECS,
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: () => DATABASE_A,
      portReservationFactory: async () => {
        reservationCalls += 1
        if (reservationCalls === 2) throw new Error('synthetic second reservation failure')
        return {
          port: 41001,
          async release() { releaseCalls += 1 },
        }
      },
      processRunner: {
        run() { processCalls += 1 },
        start() { processCalls += 1 },
        stop() { processCalls += 1 },
      },
    }),
    /second reservation failure/i,
  )
  assert.equal(reservationCalls, 2)
  assert.equal(releaseCalls, 1)
  assert.equal(processCalls, 0)
})

test('Windows ownership keeps child configuration out of the PowerShell command line', async () => {
  const runner = await import(runnerModule)
  const secretValue = 'owned-child-stdin-secret'
  const command = 'C:\\owned-tools\\child.exe'
  const commandArgument = '--owned-child-argument'
  let invocation
  let configuration = ''
  const supervisor = fakeChild('windows job supervisor', 5400)
  supervisor.stdin = new EventEmitter()
  supervisor.stdin.end = value => { configuration += String(value) }

  const result = runner.spawnOwnedChild(
    command,
    [commandArgument],
    {
      cwd: repositoryRoot,
      env: {
        Path: 'C:\\Windows\\System32',
        SystemRoot: 'C:\\Windows',
        MYSQL_PASSWORD: secretValue,
      },
      stdio: ['ignore', 'pipe', 'pipe'],
    },
    {
      platform: 'win32',
      spawnImpl(spawnCommand, args, options) {
        invocation = { spawnCommand, args, options }
        return supervisor
      },
    },
  )

  assert.equal(result, supervisor)
  assert.equal(invocation.spawnCommand, 'powershell.exe')
  assert.equal(invocation.options.shell, false)
  assert.equal(invocation.options.windowsHide, true)
  assert.equal(invocation.options.detached, false)
  assert.equal(invocation.args.includes('-EncodedCommand'), true)
  const commandLine = JSON.stringify({
    command: invocation.spawnCommand,
    arguments: invocation.args,
  })
  assert.doesNotMatch(commandLine, new RegExp(secretValue, 'u'))
  assert.doesNotMatch(commandLine, new RegExp(command.replaceAll('\\', '\\\\'), 'u'))
  assert.doesNotMatch(commandLine, new RegExp(commandArgument, 'u'))
  assert.deepEqual(invocation.options.env, {
    Path: 'C:\\Windows\\System32',
    SystemRoot: 'C:\\Windows',
    MYSQL_PASSWORD: secretValue,
  })

  const parsedConfiguration = JSON.parse(configuration)
  assert.equal(parsedConfiguration.command, command)
  assert.deepEqual(parsedConfiguration.arguments, [commandArgument])
  assert.equal(Object.hasOwn(parsedConfiguration, 'environment'), false)
})

test('real Windows ownership kills a long-lived descendant after its parent exits', {
  skip: process.platform !== 'win32',
}, async () => {
  const runner = await import(runnerModule)
  const descendantSource = [
    "const net = require('node:net')",
    'const server = net.createServer()',
    "server.listen(0, '127.0.0.1', () => process.stdout.write('READY\\n'))",
    'setInterval(() => {}, 1000)',
  ].join('\n')
  const parentSource = [
    "const { spawn } = require('node:child_process')",
    `const child = spawn(process.execPath, ['-e', ${JSON.stringify(descendantSource)}], {`,
    "  detached: true, windowsHide: true, stdio: ['ignore', 'pipe', 'ignore']",
    '})',
    'child.unref()',
    "child.stdout.once('data', () => {",
    "  require('node:fs').writeSync(2, 'OWNED_STDERR_READY\\n')",
    '  process.stdout.write(String(child.pid))',
    '  process.exit(23)',
    '})',
  ].join('\n')
  const options = {
    cwd: repositoryRoot,
    env: {
      PATH: process.env.PATH || process.env.Path,
      Path: process.env.Path,
      SystemRoot: process.env.SystemRoot,
      TEMP: process.env.TEMP,
      TMP: process.env.TMP,
    },
    shell: false,
    windowsHide: true,
    detached: false,
    stdio: ['ignore', 'pipe', 'pipe'],
  }
  const startOwned = runner.spawnOwnedChild || ((
    command,
    args,
    childOptions,
  ) => spawn(command, args, runner.ownedChildOptions(childOptions, 'win32')))
  let descendantPid = 0
  try {
    const parent = startOwned(process.execPath, ['-e', parentSource], options, {
      platform: 'win32',
    })
    let output = ''
    let errorOutput = ''
    parent.stdout.on('data', chunk => { output += chunk.toString('utf8') })
    parent.stderr.on('data', chunk => { errorOutput += chunk.toString('utf8') })
    const parentStatus = await new Promise((resolve, reject) => {
      parent.once('error', reject)
      parent.once('close', resolve)
    })
    descendantPid = Number.parseInt(output.trim(), 10)
    assert.equal(parentStatus, 23)
    assert.match(errorOutput, /OWNED_STDERR_READY/u)
    assert.equal(Number.isSafeInteger(descendantPid) && descendantPid > 0, true)
    assert.equal(
      await waitForProcessGone(descendantPid),
      true,
      'runner-owned descendant survived its parent',
    )
  } finally {
    await terminateOwnedTestPid(descendantPid)
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

  const baseEnvironment = Object.fromEntries(
    runner.BASE_ENV_ALLOWLIST
      .filter(name => Object.hasOwn(TEST_ENVIRONMENT, name))
      .map(name => [name, TEST_ENVIRONMENT[name]]),
  )
  assertExactEnvironment(prepare.options.env, {
    ...baseEnvironment,
    TEST_MYSQL_HOST: TEST_ENVIRONMENT.TEST_MYSQL_HOST,
    TEST_MYSQL_PORT: TEST_ENVIRONMENT.TEST_MYSQL_PORT,
    TEST_MYSQL_USER: TEST_ENVIRONMENT.TEST_MYSQL_USER,
    TEST_MYSQL_PASSWORD: TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD,
  })
  assertExactEnvironment(starts[0].options.env, {
    ...baseEnvironment,
    MYSQL_HOST: TEST_ENVIRONMENT.TEST_MYSQL_HOST,
    MYSQL_PORT: TEST_ENVIRONMENT.TEST_MYSQL_PORT,
    MYSQL_USER: TEST_ENVIRONMENT.TEST_MYSQL_USER,
    MYSQL_PASSWORD: TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD,
    MYSQL_DB: DATABASE_A,
    M2_BROWSER_RUN_NONCE: 'product-shell-owner',
  })
  assertExactEnvironment(starts[1].options.env, {
    ...baseEnvironment,
    M2_BROWSER_RUN_NONCE: 'product-shell-owner',
    VITE_API_BASE_URL: 'http://127.0.0.1:41001/api',
  })
  assertExactEnvironment(browser.options.env, {
    ...baseEnvironment,
    PLAYWRIGHT_BASE_URL: 'http://127.0.0.1:41002',
    BROWSER_TEST_DATABASE: DATABASE_A,
    BROWSER_SECRET_SENTINEL: runner.PRODUCT_SHELL_SECRET_SENTINEL,
  })
  assertExactEnvironment(cleanup.options.env, prepare.options.env)
  for (const event of [...runs, ...starts]) {
    assert.equal('GITHUB_TOKEN' in event.options.env, false)
    assert.equal('AWS_SECRET_ACCESS_KEY' in event.options.env, false)
    assert.equal(
      Object.values(event.options.env).includes(TEST_ENVIRONMENT.MYSQL_PASSWORD),
      false,
    )
  }
  assert.equal('TEST_MYSQL_PASSWORD' in starts[0].options.env, false)
  assert.equal('TEST_MYSQL_PASSWORD' in starts[1].options.env, false)
  assert.equal('MYSQL_PASSWORD' in starts[1].options.env, false)
  assert.equal('MYSQL_PASSWORD' in browser.options.env, false)

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

test('browser execution and log-scan failures are aggregated before owned cleanup', async () => {
  const runner = await import(runnerModule)
  const harness = createHarness({
    browserStatus: 7,
    browserLogScanError: new Error('synthetic log scan failure'),
  })

  await assert.rejects(
    runner.runProductShell({
      specs: runner.FORMAL_SPECS,
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: harness.databaseNameFactory,
      portReservationFactory: harness.portReservationFactory,
      processRunner: harness.processRunner,
      waitForUrlImpl: harness.waitForUrlImpl,
      serverLogObserverFactory: harness.serverLogObserverFactory,
      nonceFactory: () => 'aggregate-owner',
    }),
    error => {
      assert.ok(error instanceof AggregateError)
      assert.match(error.errors.map(item => item.message).join('\n'), /browser.*status 7/i)
      assert.match(error.errors.map(item => item.message).join('\n'), /browser.*log scan/i)
      return true
    },
  )
  assert.deepEqual(
    harness.events.filter(event => event.kind === 'stop').map(event => event.child),
    harness.children.toReversed(),
  )
  assert.ok(harness.events.some(event => event.kind === 'run' && event.args.includes('--drop')))
})

for (const [label, serverFailure, expected] of [
  [
    'backend async spawn error',
    { label: 'backend', kind: 'error' },
    /backend.*error|backend.*failed/i,
  ],
  [
    'Vite async spawn error',
    { label: 'vite', kind: 'error' },
    /vite.*error|vite.*failed/i,
  ],
  [
    'backend early exit',
    { label: 'backend', kind: 'exit', code: 19 },
    /backend.*19|backend.*exit/i,
  ],
]) {
  test(`${label} is controlled and still stops owned children and drops the database`, async () => {
    const runner = await import(runnerModule)
    const harness = createHarness({
      healthMode: 'hang',
      serverFailure,
    })

    const outcome = await settleWithin(runner.runProductShell({
      specs: runner.FORMAL_SPECS,
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: harness.databaseNameFactory,
      portReservationFactory: harness.portReservationFactory,
      processRunner: harness.processRunner,
      waitForUrlImpl: harness.waitForUrlImpl,
      serverLogObserverFactory: harness.serverLogObserverFactory,
      nonceFactory: () => 'server-failure-owner',
      deadlines: boundedTestDeadlines(),
    }))
    assert.equal(outcome.status, 'rejected', `${label} must reject before the watchdog`)
    assert.match(String(outcome.error?.message), expected)

    const stops = harness.events.filter(event => event.kind === 'stop')
    const cleanup = harness.events.find(event => (
      event.kind === 'run' && event.args.includes('--drop')
    ))
    assert.deepEqual(stops.map(event => event.child), harness.children.toReversed())
    assert.ok(cleanup)
  })
}

test('owned process options and terminators target only a validated owned process tree', async () => {
  const runner = await import(runnerModule)
  const windowsOptions = runner.ownedChildOptions({ shell: true }, 'win32')
  const posixOptions = runner.ownedChildOptions({ shell: true }, 'linux')
  assert.equal(windowsOptions.shell, false)
  assert.equal(windowsOptions.detached, false)
  assert.equal(windowsOptions.windowsHide, true)
  assert.equal(posixOptions.shell, false)
  assert.equal(posixOptions.detached, true)

  const windowsChild = fakeChild('windows-owned', 7311)
  const taskkillCalls = []
  await runner.terminateOwnedProcessTree(windowsChild, {
    platform: 'win32',
    timeoutMs: 50,
    spawnImpl(command, args, options) {
      const terminator = fakeChild('taskkill', 8112)
      taskkillCalls.push({ command, args, options })
      queueMicrotask(() => {
        closeFakeChild(windowsChild)
        closeFakeChild(terminator)
      })
      return terminator
    },
  })
  assert.deepEqual(taskkillCalls, [{
    command: 'taskkill',
    args: ['/PID', '7311', '/T', '/F'],
    options: {
      shell: false,
      windowsHide: true,
      stdio: 'ignore',
    },
  }])
  assert.equal(windowsChild.closed, true)

  const posixChild = fakeChild('posix-owned', 7312)
  const groupSignals = []
  await runner.terminateOwnedProcessTree(posixChild, {
    platform: 'linux',
    timeoutMs: 50,
    killImpl(pid, signal) {
      groupSignals.push([pid, signal])
      queueMicrotask(() => closeFakeChild(posixChild))
    },
  })
  assert.deepEqual(groupSignals, [[-7312, 'SIGTERM']])
  assert.equal(posixChild.closed, true)

  let unsafeTerminatorCalls = 0
  const unsafeChild = fakeChild('unsafe', 0)
  await assert.rejects(
    runner.terminateOwnedProcessTree(
      unsafeChild,
      {
        platform: 'win32',
        spawnImpl() {
          unsafeTerminatorCalls += 1
        },
      },
    ),
    /owned.*pid|pid.*owned|positive integer/i,
  )
  assert.equal(unsafeTerminatorCalls, 0)
})

for (const phase of ['prepare', 'health', 'browser', 'cleanup']) {
  test(`hanging ${phase} operation is bounded and preserves owned cleanup`, async () => {
    const runner = await import(runnerModule)
    const harness = createHarness({
      hangPhase: phase === 'health' ? '' : phase,
      healthMode: phase === 'health' ? 'hang' : 'resolve',
    })
    const outcome = await settleWithin(runner.runProductShell({
      specs: runner.FORMAL_SPECS,
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: harness.databaseNameFactory,
      portReservationFactory: harness.portReservationFactory,
      processRunner: harness.processRunner,
      waitForUrlImpl: harness.waitForUrlImpl,
      serverLogObserverFactory: harness.serverLogObserverFactory,
      nonceFactory: () => `${phase}-deadline-owner`,
      deadlines: boundedTestDeadlines(),
    }))

    assert.equal(outcome.status, 'rejected', `${phase} must reject before the watchdog`)
    assert.match(String(outcome.error?.message), new RegExp(`${phase}|timed out|deadline`, 'i'))
    const cleanupRuns = harness.events.filter(event => (
      event.kind === 'run' && event.args.includes('--drop')
    ))
    if (phase !== 'cleanup') assert.equal(cleanupRuns.length, 1)
    if (phase === 'prepare') {
      assert.equal(harness.events.filter(event => event.kind === 'start').length, 0)
    } else {
      assert.deepEqual(
        harness.events.filter(event => event.kind === 'stop').map(event => event.child),
        harness.children.toReversed(),
      )
    }
  })
}

test('product-shell spec releases held DELETE and preserves body plus audit failures', () => {
  const source = readFileSync(
    path.join(repositoryRoot, 'frontend', 'e2e', 'product-shell-lifecycle.spec.ts'),
    'utf8',
  )

  assert.match(source, /assertExactWrites\s*\(/u)
  assert.match(source, /finally\s*\{[^}]*releasePendingDelete\(\)[^}]*unroute/su)
  assert.match(source, /bodyError/su)
  assert.match(source, /auditError/su)
  assert.match(source, /new AggregateError\s*\(\s*\[\s*bodyError\s*,\s*auditError\s*\]/su)
  assert.match(source, /consoleErrors[^]*deliberate 404\/500[^]*toEqual\(\[/u)
  assert.match(source, /requestFailures[^]*toEqual\(\[\]\)/u)
  assert.match(source, /responseFailures/u)
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

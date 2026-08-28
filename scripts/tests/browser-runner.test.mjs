import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { PassThrough } from 'node:stream'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { createServerLogObserver } from '../../frontend/e2e/server-log-observer.mjs'

import {
  assertDatabaseName,
  assertOwnedRoot,
  createOwnedRoot,
  createDatabaseName,
  processFailure,
  REQUIRED_TEST_VARIABLES,
  runOwnedProductLifecycle,
  removeOwnedRoot,
  validateTestEnvironment,
} from '../../frontend/e2e/support/product-runner.mjs'


const TEST_ENVIRONMENT = Object.freeze({
  TEST_MYSQL_HOST: '127.0.0.1',
  TEST_MYSQL_PORT: '33060',
  TEST_MYSQL_USER: 'root',
  TEST_MYSQL_PASSWORD: 'test-only',
})
const repositoryRoot = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  '..',
  '..',
)


test('all formal browser runners delegate process and server lifecycle to neutral support', () => {
  const runnerPaths = [
    'frontend/e2e/run-product-shell.mjs',
    'frontend/e2e/run-phase2a.mjs',
    'frontend/e2e/run-phase2b.mjs',
    'frontend/e2e/run-phase2c.mjs',
  ]
  const requiredImports = [
    'runBoundedOwnedCommand',
    'startOwnedServer',
    'waitForOwnedServer',
    'stopOwnedServer',
  ]
  const forbiddenLocals = [
    'runOwnedCommand',
    'startOwnedServer',
    'waitForServer',
    'stopOwnedServer',
    'waitForClose',
    'waitForCloseAndDrain',
  ]

  for (const runnerPath of runnerPaths) {
    const source = readFileSync(path.join(repositoryRoot, runnerPath), 'utf8')
    assert.match(source, /from ['"]\.\/support\/product-runner\.mjs['"]/u)
    for (const name of requiredImports) {
      assert.match(source, new RegExp(`\\b${name}\\b`, 'u'), `${runnerPath} must import ${name}`)
    }
    for (const name of forbiddenLocals) {
      assert.doesNotMatch(
        source,
        new RegExp(`(?:function|const)\\s+${name}\\b`, 'u'),
        `${runnerPath} must not define ${name}`,
      )
    }
  }
})


test('neutral bounded command and owned server APIs preserve timeout, health, drain, scan, and error semantics', async () => {
  const support = await import('../../frontend/e2e/support/product-runner.mjs')
  for (const name of [
    'runBoundedOwnedCommand',
    'startOwnedServer',
    'waitForOwnedServer',
    'scanOwnedServer',
    'stopOwnedServer',
  ]) assert.equal(typeof support[name], 'function', `missing neutral ${name}`)

  const events = []
  const child = new EventEmitter()
  child.pid = 7301
  child.exitCode = null
  child.stdout = new PassThrough()
  child.stderr = new PassThrough()
  const processRunner = {
    async run(_command, _args, _options, runtime) {
      events.push(['run', runtime.label])
      return {
        status: 0,
        error: null,
        logObserver: { finish: () => ({ matchCount: 0 }) },
      }
    },
    start(_command, _args, _options, runtime) {
      events.push(['start', runtime.label])
      return child
    },
    async stop(target) {
      events.push(['stop', target.pid])
      target.exitCode = 0
      target.emit('exit', 0, null)
      target.emit('close', 0, null)
    },
  }
  const observerFactory = target => ({
    finish(values) {
      assert.equal(target.exitCode, 0, 'scan must happen after process close/drain')
      events.push(['scan', [...values]])
      return { matchCount: 0 }
    },
  })

  await support.runBoundedOwnedCommand('node', ['ok'], {}, {
    label: 'bounded fixture',
    sensitiveValues: ['sentinel'],
    timeoutMs: 50,
    settleMs: 10,
    processRunner,
  })
  await assert.rejects(
    support.runBoundedOwnedCommand('node', ['hang'], {}, {
      label: 'bounded timeout fixture',
      timeoutMs: 5,
      settleMs: 10,
      stopTimeoutMs: 10,
      processRunner: {
        ...processRunner,
        run(_command, _args, _options, runtime) {
          return new Promise((resolve, reject) => {
            runtime.signal.addEventListener('abort', () => reject(runtime.signal.reason), {
              once: true,
            })
          })
        },
      },
    }),
    /bounded timeout fixture deadline exceeded/u,
  )
  const server = support.startOwnedServer('node', ['server'], {}, {
    label: 'backend',
    sensitiveValues: ['sentinel'],
    processRunner,
    serverLogObserverFactory: observerFactory,
  })
  await support.waitForOwnedServer(server, 'http://127.0.0.1:41001/health', {
    expectedNonce: 'owned-nonce',
    timeoutMs: 50,
    waitForUrlImpl: async () => { events.push(['health']) },
  })
  await support.stopOwnedServer(server, {
    sensitiveValues: ['sentinel'],
    timeoutMs: 50,
  })
  assert.deepEqual(events, [
    ['run', 'bounded fixture'],
    ['start', 'backend'],
    ['health'],
    ['stop', 7301],
    ['scan', ['sentinel']],
  ])

  const earlyChild = new EventEmitter()
  earlyChild.pid = 7302
  earlyChild.exitCode = null
  earlyChild.stdout = new PassThrough()
  earlyChild.stderr = new PassThrough()
  const earlyServer = support.startOwnedServer('node', ['early'], {}, {
    label: 'vite',
    processRunner: {
      ...processRunner,
      start: () => earlyChild,
      async stop() {},
    },
    serverLogObserverFactory: () => ({ finish: () => ({ matchCount: 0 }) }),
  })
  const health = support.waitForOwnedServer(earlyServer, 'http://127.0.0.1:41002/health', {
    expectedNonce: 'owned-nonce',
    timeoutMs: 50,
    waitForUrlImpl: async () => new Promise(() => {}),
  })
  earlyChild.exitCode = 19
  earlyChild.emit('exit', 19, null)
  earlyChild.emit('close', 19, null)
  await assert.rejects(health, /vite.*19|vite.*exit/iu)

  const stopFailure = new Error('synthetic stop failure')
  const scanFailure = new Error('synthetic scan failure')
  const failedChild = {
    pid: 7303,
    exitCode: 0,
    stdout: new PassThrough(),
    stderr: new PassThrough(),
  }
  const failedServer = support.startOwnedServer('node', ['failed'], {}, {
    label: 'failed server',
    processRunner: {
      ...processRunner,
      start: () => failedChild,
      async stop() { throw stopFailure },
    },
    serverLogObserverFactory: () => ({ finish() { throw scanFailure } }),
  })
  await assert.rejects(
    support.stopOwnedServer(failedServer, { timeoutMs: 50 }),
    error => {
      assert.ok(error instanceof AggregateError)
      assert.deepEqual(error.errors, [stopFailure, scanFailure])
      return true
    },
  )

  const singleChild = { pid: 7304, exitCode: 0 }
  const singleServer = support.startOwnedServer('node', ['single'], {}, {
    label: 'single server',
    processRunner: {
      ...processRunner,
      start: () => singleChild,
      async stop() {},
    },
    serverLogObserverFactory: () => ({ finish() { throw scanFailure } }),
  })
  await assert.rejects(
    support.stopOwnedServer(singleServer, { timeoutMs: 50 }),
    error => error === scanFailure,
  )
})


test('owned command preserves one abort stop rejection by identity', async () => {
  const { runOwnedCommand } = await import(
    '../../frontend/e2e/support/product-runner.mjs'
  )
  const child = new EventEmitter()
  child.pid = 7401
  child.exitCode = null
  child.stdout = new PassThrough()
  child.stderr = new PassThrough()
  const stopFailure = new Error('synthetic abort stop rejection')
  const controller = new AbortController()
  controller.abort(new Error('synthetic abort'))

  const result = await runOwnedCommand('node', ['ignored'], {}, {
    label: 'abort stop fixture',
    signal: controller.signal,
    spawnOwnedChildImpl: () => child,
    terminateOwnedProcessTreeImpl: async target => {
      assert.equal(target, child)
      throw stopFailure
    },
  })

  assert.equal(result.status, null)
  assert.equal(result.error, stopFailure)
  assert.equal(result.error instanceof AggregateError, false)
})


for (const signalName of ['SIGINT', 'SIGTERM']) {
  test(`neutral public helpers propagate ${signalName} external abort promptly`, async () => {
    const support = await import('../../frontend/e2e/support/product-runner.mjs')
    const reason = new Error(`external-stop-${signalName}`)
    const commandController = new AbortController()
    const commandStarted = Date.now()
    setTimeout(() => commandController.abort(reason), 50)
    await assert.rejects(
      support.runBoundedOwnedCommand(
        process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' },
        { label: `external ${signalName}`, timeoutMs: 5_000, settleMs: 1_000,
          stopTimeoutMs: 1_000, signal: commandController.signal },
      ),
      error => error === reason,
    )
    assert.ok(Date.now() - commandStarted < 2_500)

    const healthController = new AbortController()
    setTimeout(() => healthController.abort(reason), 50)
    await assert.rejects(
      support.waitForOwnedServer(
        { label: 'external health', state: { failurePromise: new Promise(() => {}) } },
        'http://127.0.0.1:1/health',
        { expectedNonce: 'nonce', timeoutMs: 5_000, settleMs: 1_000,
          signal: healthController.signal, waitForUrlImpl: async () => new Promise(() => {}) },
      ),
      error => error === reason,
    )
  })
}


test('neutral runner requires every explicit disposable MySQL variable', () => {
  assert.deepEqual(REQUIRED_TEST_VARIABLES, [
    'TEST_MYSQL_HOST',
    'TEST_MYSQL_PORT',
    'TEST_MYSQL_USER',
    'TEST_MYSQL_PASSWORD',
  ])
  for (const name of REQUIRED_TEST_VARIABLES) {
    const environment = { ...TEST_ENVIRONMENT }
    delete environment[name]
    assert.throws(() => validateTestEnvironment(environment), new RegExp(name, 'u'))
  }
  assert.doesNotThrow(() => validateTestEnvironment(TEST_ENVIRONMENT))
})


test('neutral runner creates only exact random disposable database names', () => {
  const name = createDatabaseName(() => '01234567-89AB-CDEF-0123-456789ABCDEF')
  assert.equal(name, 'novel_creator_test_0123456789abcdef0123456789abcdef')
  assert.doesNotThrow(() => assertDatabaseName(name))
  for (const unsafe of [
    'novel_creator',
    'novel_creator_test_short',
    'novel_creator_test_0123456789abcdef0123456789abcdeg',
  ]) {
    assert.throws(() => assertDatabaseName(unsafe), /disposable/u)
  }
})


test('neutral runner creates and removes only its exact temporary root', () => {
  const root = createOwnedRoot('novel-creator-phase2c-')
  assert.equal(assertOwnedRoot(root, 'novel-creator-phase2c-'), root)
  assert.throws(
    () => assertOwnedRoot(root, 'novel-creator-other-'),
    /temporary namespace/u,
  )
  removeOwnedRoot(root, 'novel-creator-phase2c-')
})


test('neutral lifecycle cleans servers in reverse then reservations, database, and root', async () => {
  const events = []
  await runOwnedProductLifecycle({
    async body(lifecycle) {
      lifecycle.setRoot('owned-root')
      lifecycle.setDatabase('disposable-db')
      lifecycle.registerReservation('backend-port')
      lifecycle.registerReservation('vite-port')
      lifecycle.registerServer('backend')
      lifecycle.registerServer('vite')
    },
    async stopServer(server) { events.push(`stop:${server}`) },
    async releaseReservation(reservation) { events.push(`release:${reservation}`) },
    async dropDatabase(database) { events.push(`drop:${database}`) },
    async removeRoot(root) { events.push(`remove:${root}`) },
  })
  assert.deepEqual(events, [
    'stop:vite',
    'stop:backend',
    'release:backend-port',
    'release:vite-port',
    'drop:disposable-db',
    'remove:owned-root',
  ])
})


test('neutral lifecycle rethrows one error unchanged and aggregates multiple cleanup errors', async () => {
  const bodyFailure = new Error('body')
  await assert.rejects(runOwnedProductLifecycle({
    async body() { throw bodyFailure },
    async stopServer() {},
    async releaseReservation() {},
    async dropDatabase() {},
    async removeRoot() {},
  }), error => error === bodyFailure)

  const stopFailure = new Error('stop')
  const dropFailure = new Error('drop')
  await assert.rejects(runOwnedProductLifecycle({
    async body(lifecycle) {
      lifecycle.setDatabase('db')
      lifecycle.registerServer('server')
      throw bodyFailure
    },
    async stopServer() { throw stopFailure },
    async releaseReservation() {},
    async dropDatabase() { throw dropFailure },
    async removeRoot() {},
  }), error => {
    assert.ok(error instanceof AggregateError)
    assert.deepEqual(error.errors, [bodyFailure, stopFailure, dropFailure])
    return true
  })
})


test('neutral process failure preserves process and fail-closed log scan errors', () => {
  const child = new EventEmitter()
  child.stdout = new PassThrough()
  child.stderr = new PassThrough()
  const sentinel = 'do-not-print-this-value'
  const observer = createServerLogObserver(child, { sensitiveValues: [sentinel] })
  child.stderr.write(sentinel)
  const failure = processFailure('browser', {
    status: 1,
    logObserver: observer,
  }, [sentinel])
  assert.ok(failure instanceof AggregateError)
  assert.equal(failure.errors.length, 2)
  assert.equal(String(failure).includes(sentinel), false)
})

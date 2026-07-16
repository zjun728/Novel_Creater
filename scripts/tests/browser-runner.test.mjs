import assert from 'node:assert/strict'
import { EventEmitter, getEventListeners } from 'node:events'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import {
  buildChildEnvironment,
  createDatabaseName,
  runMilestone1,
  validateTestEnvironment,
} from '../../frontend/e2e/run-milestone1.mjs'

const M2_MODULE = '../../frontend/e2e/run-milestone2.mjs'

const DATABASE = 'novel_creator_test_0123456789abcdef0123456789abcdef'
const TEST_ENVIRONMENT = {
  PATH: 'test-path',
  TEST_MYSQL_HOST: '127.0.0.1',
  TEST_MYSQL_PORT: '33060',
  TEST_MYSQL_USER: 'root',
  TEST_MYSQL_PASSWORD: 'test-only',
  MYSQL_HOST: 'product-host',
  MYSQL_PORT: '3306',
  MYSQL_USER: 'product-user',
  MYSQL_PASSWORD: 'product-password',
  MYSQL_DB: 'novel_creator',
}
const FORMAL_SPECS = [
  { path: 'e2e/m2-foundation-regression.spec.ts', scenario: 'foundation' },
  { path: 'e2e/m2-wizard-manual.spec.ts', scenario: 'manual' },
  { path: 'e2e/m2-wizard-recovery.spec.ts', scenario: 'recovery' },
  { path: 'e2e/m2-settings-assets-corpus.spec.ts', scenario: 'settings' },
]

const ownedCorpusRoot = (nonce, suffix = 'fixture') => path.join(
  path.resolve(os.tmpdir()),
  `novel-creator-m2-corpus-${nonce}-${suffix}`,
)

test('requires every explicit disposable MySQL variable', () => {
  const environment = { ...TEST_ENVIRONMENT }
  delete environment.TEST_MYSQL_PASSWORD

  assert.throws(
    () => validateTestEnvironment(environment),
    /TEST_MYSQL_PASSWORD/,
  )
})

test('creates an exact disposable database name', () => {
  const databaseName = createDatabaseName(() => '01234567-89ab-cdef-0123-456789abcdef')

  assert.equal(databaseName, DATABASE)
})

test('maps only explicit test server values to the disposable backend database', () => {
  const childEnvironment = buildChildEnvironment(TEST_ENVIRONMENT, DATABASE)

  assert.equal(childEnvironment.MYSQL_HOST, TEST_ENVIRONMENT.TEST_MYSQL_HOST)
  assert.equal(childEnvironment.MYSQL_PORT, TEST_ENVIRONMENT.TEST_MYSQL_PORT)
  assert.equal(childEnvironment.MYSQL_USER, TEST_ENVIRONMENT.TEST_MYSQL_USER)
  assert.equal(childEnvironment.MYSQL_PASSWORD, TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD)
  assert.equal(childEnvironment.MYSQL_DB, DATABASE)
  assert.equal(childEnvironment.BROWSER_TEST_DATABASE, DATABASE)
  assert.equal(childEnvironment.PATH, 'test-path')
})

test('always drops the database and preserves browser plus cleanup failures', () => {
  const calls = []
  const spawnSyncImpl = (command, args, options) => {
    calls.push({ command, args, options })
    if (args.includes('--drop')) return { status: 9 }
    if (args.includes('test')) return { status: 7 }
    return { status: 0 }
  }

  assert.throws(
    () => runMilestone1({
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: () => DATABASE,
      spawnSyncImpl,
    }),
    error => {
      assert(error instanceof AggregateError)
      assert.equal(error.errors.length, 2)
      assert.match(error.errors[0].message, /browser.*7/i)
      assert.match(error.errors[1].message, /cleanup.*9/i)
      return true
    },
  )

  assert.equal(calls.length, 3)
  assert.equal(calls.every(call => call.options.shell === false), true)
  assert.equal(calls[0].args.includes('--database'), true)
  assert.equal(calls[1].args.includes('e2e/milestone1.spec.ts'), true)
  assert.equal(calls[2].args.includes('--drop'), true)
})

test('M2 child environment strips parent MySQL authority and adds fixed sentinels', async () => {
  const { buildChildEnvironment: buildM2ChildEnvironment } = await import(M2_MODULE)
  const child = buildM2ChildEnvironment(TEST_ENVIRONMENT, DATABASE, 'C:\\Temp\\m2-corpus-a')

  assert.equal(child.MYSQL_HOST, TEST_ENVIRONMENT.TEST_MYSQL_HOST)
  assert.equal(child.MYSQL_PORT, TEST_ENVIRONMENT.TEST_MYSQL_PORT)
  assert.equal(child.MYSQL_USER, TEST_ENVIRONMENT.TEST_MYSQL_USER)
  assert.equal(child.MYSQL_PASSWORD, TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD)
  assert.equal(child.MYSQL_DB, DATABASE)
  assert.equal(child.CORPUS_ROOT, 'C:\\Temp\\m2-corpus-a')
  assert.equal(child.BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL, child.CORPUS_ROOT)
  assert.equal(child.BROWSER_SECRET_SENTINEL, 'browser-secret-must-not-leak')
  assert.equal(child.BROWSER_PRIVATE_PROVIDER_URL, 'https://private-provider.example/v1')
  assert.equal(child.BROWSER_CORPUS_ROOT_SENTINEL, 'C:/private/corpus-root-must-not-leak')
  assert.equal(child.PATH, 'test-path')
  assert.notEqual(child.MYSQL_HOST, TEST_ENVIRONMENT.MYSQL_HOST)
})

test('M2 sensitive values cover database password and raw plus encoded DSNs', async () => {
  const { browserSensitiveValues, buildChildEnvironment } = await import(M2_MODULE)
  const { runtimeSensitiveValues } = await import('../../frontend/e2e/runtime-observer.mjs')
  const environment = {
    ...TEST_ENVIRONMENT,
    TEST_MYSQL_USER: 'browser:user',
    TEST_MYSQL_PASSWORD: 'p@ss:/word',
  }
  const corpusRoot = 'C:\\Temp\\novel-creator-m2-corpus-sensitive'
  const values = browserSensitiveValues(environment, DATABASE, corpusRoot)

  assert.deepEqual(
    values,
    runtimeSensitiveValues(buildChildEnvironment(environment, DATABASE, corpusRoot)),
  )

  assert.equal(values.includes(DATABASE), true)
  assert.equal(values.includes(environment.TEST_MYSQL_PASSWORD), true)
  assert.equal(values.includes(
    `mysql://${environment.TEST_MYSQL_USER}:${environment.TEST_MYSQL_PASSWORD}`
      + `@${environment.TEST_MYSQL_HOST}:${environment.TEST_MYSQL_PORT}/${DATABASE}`,
  ), true)
  assert.equal(values.includes(
    `mysql://${encodeURIComponent(environment.TEST_MYSQL_USER)}`
      + `:${encodeURIComponent(environment.TEST_MYSQL_PASSWORD)}`
      + `@${environment.TEST_MYSQL_HOST}:${environment.TEST_MYSQL_PORT}/${DATABASE}`,
  ), true)
  assert.equal(values.includes(environment.TEST_MYSQL_HOST), false)
  assert.equal(values.includes(environment.TEST_MYSQL_USER), false)
})

test('M2 runner gives every injected spec an isolated database and external corpus', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  const calls = []
  const roots = [
    ownedCorpusRoot('owner-a'),
    ownedCorpusRoot('owner-b'),
    ownedCorpusRoot('owner-c'),
    ownedCorpusRoot('owner-d'),
  ]
  const databases = [
    DATABASE,
    'novel_creator_test_fedcba9876543210fedcba9876543210',
    'novel_creator_test_11111111111111111111111111111111',
    'novel_creator_test_22222222222222222222222222222222',
  ]
  const ports = [41001, 41002, 41003, 41004, 41005, 41006, 41007, 41008]
  const pendingPorts = [...ports]
  const releasedPorts = []
  const nonces = ['owner-a', 'owner-b', 'owner-c', 'owner-d']
  const pendingNonces = [...nonces]
  const processRunner = {
    async run(command, args, options) {
      calls.push({ type: 'run', command, args, options })
      return { status: 0 }
    },
    start(command, args, options) {
      const child = { command, args, options }
      calls.push({ type: 'start', child })
      return child
    },
    async stop(child) {
      calls.push({ type: 'stop', child })
    },
  }
  const observed = []
  const writes = []
  const removed = []

  assert.equal(await runMilestone2({
    specs: FORMAL_SPECS,
    environment: TEST_ENVIRONMENT,
    databaseNameFactory: () => databases.shift(),
    mkdtempImpl: prefix => {
      assert.match(prefix, /novel-creator-m2-corpus-owner-[a-d]-$/)
      return roots.shift()
    },
    writeFileImpl: (file, body, encoding) => writes.push({ file, body, encoding }),
    rmImpl: (root, options) => removed.push({ root, options }),
    processRunner,
    portReservationFactory: async () => {
      const port = pendingPorts.shift()
      return { port, release: async () => { releasedPorts.push(port) } }
    },
    nonceFactory: () => pendingNonces.shift(),
    waitForUrlImpl: async (url, options) => calls.push({ type: 'health', url, options }),
    serverLogObserverFactory: child => ({
      finish(sensitiveValues) {
        observed.push({ child, sensitiveValues })
        return { matchCount: 0, truncated: false }
      },
    }),
  }), 0)

  assert.equal(writes.length, 4)
  assert.equal(writes.every(write => write.file.endsWith('synthetic-browser-corpus.txt')), true)
  assert.equal(writes.every(write => write.encoding === 'utf8'), true)
  assert.equal(writes.every(write => write.body.includes('第一章') && write.body.includes('第二章')), true)
  assert.deepEqual(removed.map(item => item.root), [
    ownedCorpusRoot('owner-a'),
    ownedCorpusRoot('owner-b'),
    ownedCorpusRoot('owner-c'),
    ownedCorpusRoot('owner-d'),
  ])
  assert.equal(removed.every(item => item.options.recursive && item.options.force), true)

  const starts = calls.filter(call => call.type === 'start')
  assert.equal(starts.length, 8)
  assert.equal(starts.every(call => call.child.options.shell === false), true)
  assert.equal(starts.every(call => (
    JSON.stringify(call.child.options.stdio) === JSON.stringify(['ignore', 'pipe', 'pipe'])
  )), true)
  assert.equal(calls.filter(call => call.type === 'health').length, 8)
  assert.deepEqual(releasedPorts, ports)
  assert.equal(calls.filter(call => call.type === 'stop').length, 8)

  const backendStarts = starts.filter(call => call.child.args.includes('uvicorn'))
  const viteStarts = starts.filter(call => call.child.args.some(arg => String(arg).includes('vite')))
  assert.deepEqual(backendStarts.map(call => Number(call.child.args.at(-1))), [41001, 41003, 41005, 41007])
  assert.deepEqual(viteStarts.map(call => Number(call.child.args[call.child.args.indexOf('--port') + 1])), [41002, 41004, 41006, 41008])
  for (const [index, call] of backendStarts.entries()) {
    assert.equal(call.child.options.env.M2_BROWSER_RUN_NONCE, nonces[index])
    assert.equal(call.child.options.env.VITE_API_BASE_URL, `http://127.0.0.1:${ports[index * 2]}/api`)
    assert.equal(call.child.options.env.PLAYWRIGHT_BASE_URL, `http://127.0.0.1:${ports[index * 2 + 1]}`)
  }
  const healthCalls = calls.filter(call => call.type === 'health')
  for (const [index, nonce] of nonces.entries()) {
    assert.equal(healthCalls[index * 2].url, `http://127.0.0.1:${ports[index * 2]}/api/health`)
    assert.equal(healthCalls[index * 2 + 1].url, `http://127.0.0.1:${ports[index * 2 + 1]}/__m2-browser-owner`)
    assert.equal(healthCalls[index * 2].options.expectedNonce, nonce)
    assert.equal(healthCalls[index * 2 + 1].options.expectedNonce, nonce)
  }

  const runs = calls.filter(call => call.type === 'run')
  assert.equal(runs.filter(call => call.args.includes('--drop')).length, 4)
  assert.equal(runs.filter(call => call.args.includes('playwright.m2.config.ts')).length, 4)
  assert.equal(runs.every(call => call.options.shell === false), true)
  assert.equal(observed.length, 8)
  assert.equal(observed[0].sensitiveValues.includes(ownedCorpusRoot('owner-a')), true)
  assert.equal(observed[2].sensitiveValues.includes(ownedCorpusRoot('owner-b')), true)
  assert.equal(observed[4].sensitiveValues.includes(ownedCorpusRoot('owner-c')), true)
  assert.equal(observed[6].sensitiveValues.includes(ownedCorpusRoot('owner-d')), true)
})

test('owned health wait ignores a healthy response from the wrong process', async () => {
  const { waitForOwnedUrl } = await import(M2_MODULE)
  const seen = []
  const responses = ['wrong-owner', 'expected-owner']

  await waitForOwnedUrl('http://127.0.0.1:45678/api/health', {
    expectedNonce: 'expected-owner',
    intervalMs: 0,
    timeoutMs: 100,
    fetchImpl: async url => {
      seen.push(url)
      const browserRunNonce = responses.shift()
      return { ok: true, json: async () => ({ ok: true, browserRunNonce }) }
    },
  })

  assert.equal(seen.length, 2)
})

test('owned health wait aborts a hanging fetch within its total deadline', async () => {
  const { waitForOwnedUrl } = await import(M2_MODULE)
  let abortCount = 0
  const startedAt = Date.now()
  let watchdog

  try {
    await assert.rejects(Promise.race([
      waitForOwnedUrl('http://127.0.0.1:45678/api/health', {
        expectedNonce: 'expected-owner',
        intervalMs: 1,
        timeoutMs: 40,
        fetchImpl: (_url, { signal } = {}) => new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            abortCount += 1
            const error = new Error('request aborted')
            error.name = 'AbortError'
            reject(error)
          }, { once: true })
        }),
      }),
      new Promise((_, reject) => {
        watchdog = setTimeout(() => reject(new Error('test watchdog expired')), 250)
      }),
    ]), /timed out waiting/i)
  } finally {
    clearTimeout(watchdog)
  }

  assert.equal(abortCount, 1)
  assert.equal(Date.now() - startedAt < 200, true)
})

test('owned health wait aborts a hanging JSON body within its total deadline', async () => {
  const { waitForOwnedUrl } = await import(M2_MODULE)
  let bodyAbortCount = 0
  const startedAt = Date.now()
  let watchdog

  try {
    await assert.rejects(Promise.race([
      waitForOwnedUrl('http://127.0.0.1:45678/api/health', {
        expectedNonce: 'expected-owner',
        intervalMs: 1,
        timeoutMs: 40,
        fetchImpl: async (_url, { signal } = {}) => ({
          ok: true,
          json: () => new Promise((_resolve, reject) => {
            signal?.addEventListener('abort', () => {
              bodyAbortCount += 1
              const error = new Error('body aborted')
              error.name = 'AbortError'
              reject(error)
            }, { once: true })
          }),
        }),
      }),
      new Promise((_, reject) => {
        watchdog = setTimeout(() => reject(new Error('test watchdog expired')), 250)
      }),
    ]), /timed out waiting/i)
  } finally {
    clearTimeout(watchdog)
  }

  assert.equal(bodyAbortCount, 1)
  assert.equal(Date.now() - startedAt < 200, true)
})

test('owned health wait composes an external cancellation signal with its request deadline', async () => {
  const { waitForOwnedUrl } = await import(M2_MODULE)
  const controller = new AbortController()
  let requestAborted = false
  let watchdog

  setTimeout(() => controller.abort(new Error('service failed')), 20)
  try {
    await assert.rejects(Promise.race([
      waitForOwnedUrl('http://127.0.0.1:45678/api/health', {
        expectedNonce: 'expected-owner',
        intervalMs: 1,
        timeoutMs: 10_000,
        signal: controller.signal,
        fetchImpl: (_url, { signal } = {}) => new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            requestAborted = true
            const error = new Error('request aborted')
            error.name = 'AbortError'
            reject(error)
          }, { once: true })
        }),
      }),
      new Promise((_, reject) => {
        watchdog = setTimeout(() => reject(new Error('test watchdog expired')), 250)
      }),
    ]), error => error?.name === 'AbortError' || /service failed/i.test(String(error)))
  } finally {
    clearTimeout(watchdog)
  }

  assert.equal(requestAborted, true)
})

test('service-live operation cannot outrun a same-tick recorded code-zero exit', async () => {
  const { runWhileServicesLive } = await import(M2_MODULE)
  const earlyFailure = new Error('backend server exited before completion with status 0')
  const state = {
    label: 'backend',
    child: { exitCode: null },
    exitSeen: false,
    closeSeen: false,
    exitCode: null,
    earlyFailure: null,
    failurePromise: new Promise(() => {}),
  }

  await assert.rejects(runWhileServicesLive(async () => {
    state.child.exitCode = 0
    state.exitSeen = true
    state.exitCode = 0
    state.earlyFailure = earlyFailure
    return 'operation-result'
  }, [state]), /backend.*status 0/i)
})

test('default process run aborts its child, waits for close, and preserves observation data', async () => {
  const { defaultRun } = await import(M2_MODULE)
  const controller = new AbortController()
  let watchdog
  const abortTimer = setTimeout(() => controller.abort(new Error('service failed')), 30)

  try {
    const result = await Promise.race([
      defaultRun(
        process.execPath,
        ['-e', 'setInterval(() => {}, 1000)'],
        {
          cwd: process.cwd(),
          env: { ...process.env },
          shell: false,
          stdio: ['ignore', 'pipe', 'pipe'],
        },
        { signal: controller.signal, sensitiveValues: [] },
      ),
      new Promise((_, reject) => {
        watchdog = setTimeout(() => reject(new Error('child close watchdog expired')), 3_000)
      }),
    ])
    assert.notEqual(result.status, 0)
    assert.equal(Object.hasOwn(result, 'error'), true)
    assert.deepEqual(result.logObserver.finish([]), { matchCount: 0, truncated: false })
  } finally {
    clearTimeout(abortTimer)
    clearTimeout(watchdog)
  }
})

test('default process run settles boundedly when forced termination never closes the child', async t => {
  const { defaultRun } = await import(M2_MODULE)
  const scenarios = [
    {
      name: 'both signals accepted without close',
      kill: () => true,
    },
    {
      name: 'both signals rejected without close',
      kill: () => false,
    },
    {
      name: 'forced signal throws without close',
      kill: signal => {
        if (signal === 'SIGKILL') throw new Error('injected forced termination failure')
        return true
      },
    },
  ]

  for (const scenario of scenarios) {
    await t.test(scenario.name, async () => {
      const child = new EventEmitter()
      child.stdout = new EventEmitter()
      child.stderr = new EventEmitter()
      child.exitCode = null
      const killCalls = []
      child.kill = signal => {
        killCalls.push(signal)
        return scenario.kill(signal)
      }
      const controller = new AbortController()
      let watchdog

      try {
        const resultPromise = defaultRun(
          process.execPath,
          ['-e', 'setInterval(() => {}, 1000)'],
          { shell: false, stdio: ['ignore', 'pipe', 'pipe'] },
          {
            signal: controller.signal,
            sensitiveValues: ['bounded-observer-secret'],
            spawnImpl: () => child,
            abortGraceMs: 5,
            finalCloseMs: 5,
          },
        )
        child.stdout.emit('data', Buffer.from('bounded-observer-secret', 'utf8'))
        controller.abort(new Error('service failed'))
        const result = await Promise.race([
          resultPromise,
          new Promise((_, reject) => {
            watchdog = setTimeout(
              () => reject(new Error('bounded abort settlement watchdog expired')),
              250,
            )
          }),
        ])

        assert.deepEqual(killCalls, ['SIGTERM', 'SIGKILL'])
        assert.equal(result.status, null)
        assert.match(String(result.error), /abort.*close|close.*abort/i)
        assert.equal(String(result.error).includes('bounded-observer-secret'), false)
        assert.deepEqual(result.logObserver.finish(['bounded-observer-secret']), {
          matchCount: 1,
          truncated: false,
        })
        assert.equal(getEventListeners(controller.signal, 'abort').length, 0)
        await new Promise(resolve => setTimeout(resolve, 25))
        assert.deepEqual(killCalls, ['SIGTERM', 'SIGKILL'])
      } finally {
        clearTimeout(watchdog)
      }
    })
  }
})

test('M2 runner fails on early child exit, waits for close-tail scan, and still cleans up', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  const password = '中文密钥不可泄漏'
  const environment = { ...TEST_ENVIRONMENT, TEST_MYSQL_PASSWORD: password }
  const children = []
  const removed = []
  const runs = []
  const stops = []
  let nextPort = 42000

  function fakeChild(label) {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.exitCode = null
    child.label = label
    return child
  }

  const processRunner = {
    async run(_command, args) {
      runs.push(args)
      return {
        status: 0,
        logObserver: { finish: () => ({ matchCount: 0, truncated: false }) },
      }
    },
    start(_command, args) {
      const child = fakeChild(args.includes('uvicorn') ? 'backend' : 'vite')
      children.push(child)
      if (child.label === 'backend') {
        setTimeout(() => {
          child.exitCode = 7
          child.emit('exit', 7, null)
        }, 1)
        setTimeout(() => child.stdout.emit('data', Buffer.from(password, 'utf8')), 10)
        setTimeout(() => child.emit('close', 7, null), 15)
      }
      return child
    },
    async stop(child) {
      stops.push(child.label)
      if (child.exitCode === null) {
        child.exitCode = 0
        child.emit('exit', 0, null)
        child.emit('close', 0, null)
      }
    },
  }

  await assert.rejects(runMilestone2({
    environment,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => DATABASE,
    mkdtempImpl: () => ownedCorpusRoot('early-exit-owner'),
    writeFileImpl: () => {},
    rmImpl: (root, options) => removed.push({ root, options }),
    processRunner,
    portReservationFactory: async () => ({ port: ++nextPort, release: async () => {} }),
    nonceFactory: () => 'early-exit-owner',
    waitForUrlImpl: async () => new Promise(resolve => setTimeout(resolve, 3)),
  }), error => {
    const messages = []
    const collect = current => {
      messages.push(String(current))
      for (const nested of current?.errors || []) collect(nested)
    }
    collect(error)
    const rendered = messages.join('\n')
    assert.match(rendered, /backend.*exit.*7/i)
    assert.match(rendered, /sensitive match count was 1/i)
    assert.equal(rendered.includes(password), false)
    return true
  })

  assert.equal(runs.some(args => args.includes('--drop')), true)
  assert.deepEqual(stops.sort(), ['backend', 'vite'])
  assert.equal(removed.length, 1)
})

test('M2 runner rejects when browser success is immediately followed by a code-zero server exit', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  let backend
  const children = []
  let runCount = 0
  let databaseIndex = 0

  const fakeChild = label => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.exitCode = null
    child.label = label
    children.push(child)
    return child
  }

  const cleanResult = () => ({
    status: 0,
    logObserver: { finish: () => ({ matchCount: 0, truncated: false }) },
  })
  const processRunner = {
    run(_command, args) {
      runCount += 1
      if (!args.includes('test')) return Promise.resolve(cleanResult())
      return Promise.resolve().then(() => {
        queueMicrotask(() => queueMicrotask(() => {
          backend.exitCode = 0
          backend.emit('exit', 0, null)
          backend.emit('close', 0, null)
        }))
        return cleanResult()
      })
    },
    start(_command, args) {
      const child = fakeChild(args.includes('uvicorn') ? 'backend' : 'vite')
      if (child.label === 'backend') backend = child
      return child
    },
    async stop(child) {
      if (child.exitCode === null) {
        child.exitCode = 0
        child.emit('exit', 0, null)
        child.emit('close', 0, null)
      }
    },
  }

  await assert.rejects(runMilestone2({
    environment: TEST_ENVIRONMENT,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => (
      `novel_creator_test_${String(++databaseIndex).padStart(32, '0')}`
    ),
    mkdtempImpl: () => ownedCorpusRoot('browser-success-owner'),
    writeFileImpl: () => {},
    rmImpl: () => {},
    processRunner,
    portReservationFactory: (() => {
      let port = 43000
      return async () => ({ port: ++port, release: async () => {} })
    })(),
    nonceFactory: () => 'browser-success-owner',
    waitForUrlImpl: async () => {},
    serverLogObserverFactory: () => ({ finish: () => ({ matchCount: 0 }) }),
  }), /backend.*status 0/i)

  assert.equal(runCount >= 3, true)
  assert.equal(children.length, 2)
})

test('M2 runner settles operation-win browser logs before cleanup and aggregates an early exit scan failure', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  const events = []
  let backend
  let nextPort = 43500

  const cleanResult = logObserver => ({ status: 0, logObserver })
  const processRunner = {
    async run(_command, args) {
      if (args.includes('--drop')) {
        events.push('db-cleanup')
        return cleanResult()
      }
      if (!args.includes('test')) return cleanResult()
      backend.exitCode = 0
      return cleanResult({
        finish() {
          events.push('browser-log-finish')
          return { matchCount: 1, truncated: false }
        },
      })
    },
    start(_command, args) {
      const child = new EventEmitter()
      child.stdout = new EventEmitter()
      child.stderr = new EventEmitter()
      child.exitCode = null
      child.closedForTest = false
      child.label = args.includes('uvicorn') ? 'backend' : 'vite'
      if (child.label === 'backend') backend = child
      return child
    },
    async stop(child) {
      if (child.closedForTest) return
      child.closedForTest = true
      child.exitCode ??= 0
      child.emit('exit', child.exitCode, null)
      child.emit('close', child.exitCode, null)
    },
  }

  await assert.rejects(runMilestone2({
    environment: TEST_ENVIRONMENT,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => DATABASE,
    mkdtempImpl: () => ownedCorpusRoot('operation-win-scan-owner'),
    writeFileImpl: () => {},
    rmImpl: () => { events.push('corpus-rm') },
    processRunner,
    portReservationFactory: async () => ({ port: ++nextPort, release: async () => {} }),
    nonceFactory: () => 'operation-win-scan-owner',
    waitForUrlImpl: async () => {},
    serverLogObserverFactory: () => ({ finish: () => ({ matchCount: 0 }) }),
  }), error => {
    const messages = []
    const collect = current => {
      messages.push(String(current))
      for (const nested of current?.errors || []) collect(nested)
    }
    collect(error)
    const rendered = messages.join('\n')
    assert.match(rendered, /backend.*status 0/i)
    assert.match(rendered, /sensitive match count was 1/i)
    return true
  })

  assert.deepEqual(events, [
    'browser-log-finish',
    'db-cleanup',
    'corpus-rm',
  ])
})

test('M2 runner does not mistake normal requested code-zero stops for early exits', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  let databaseIndex = 0
  let corpusIndex = 0
  let nextPort = 44000
  const stopped = []
  const processRunner = {
    async run() {
      return {
        status: 0,
        logObserver: { finish: () => ({ matchCount: 0, truncated: false }) },
      }
    },
    start(_command, args) {
      const child = new EventEmitter()
      child.stdout = new EventEmitter()
      child.stderr = new EventEmitter()
      child.exitCode = null
      child.label = args.includes('uvicorn') ? 'backend' : 'vite'
      return child
    },
    async stop(child) {
      stopped.push(child.label)
      child.exitCode = 0
      child.emit('exit', 0, null)
      child.emit('close', 0, null)
    },
  }

  assert.equal(await runMilestone2({
    environment: TEST_ENVIRONMENT,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => (
      `novel_creator_test_${String(++databaseIndex).padStart(32, '0')}`
    ),
    mkdtempImpl: () => ownedCorpusRoot('normal-stop-owner', `fixture-${++corpusIndex}`),
    writeFileImpl: () => {},
    rmImpl: () => {},
    processRunner,
    portReservationFactory: async () => ({ port: ++nextPort, release: async () => {} }),
    nonceFactory: () => 'normal-stop-owner',
    waitForUrlImpl: async () => {},
    serverLogObserverFactory: () => ({ finish: () => ({ matchCount: 0 }) }),
  }), 0)

  assert.equal(stopped.length, 8)
})

test('M2 runner aborts and settles a losing browser operation before cleanup', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  const events = []
  let backend
  let nextPort = 45000

  const fakeChild = label => {
    const child = new EventEmitter()
    child.stdout = new EventEmitter()
    child.stderr = new EventEmitter()
    child.exitCode = null
    child.label = label
    return child
  }
  const cleanResult = logObserver => ({ status: 0, logObserver })
  const processRunner = {
    run(_command, args, _options, { signal } = {}) {
      if (args.includes('--drop')) {
        events.push('db-cleanup')
        return Promise.resolve(cleanResult())
      }
      if (!args.includes('test')) return Promise.resolve(cleanResult())

      return new Promise(resolve => {
        let completed = false
        const complete = label => {
          if (completed) return
          completed = true
          clearTimeout(naturalClose)
          events.push(label)
          resolve(cleanResult({
            finish() {
              events.push('browser-log-finish')
              return { matchCount: 0, truncated: false }
            },
          }))
        }
        signal?.addEventListener('abort', () => {
          events.push('browser-terminate')
          setTimeout(() => complete('browser-close'), 5)
        }, { once: true })
        const naturalClose = setTimeout(() => complete('browser-natural-close'), 80)
        queueMicrotask(() => {
          backend.exitCode = 7
          backend.emit('exit', 7, null)
          backend.emit('close', 7, null)
        })
      })
    },
    start(_command, args) {
      const child = fakeChild(args.includes('uvicorn') ? 'backend' : 'vite')
      if (child.label === 'backend') backend = child
      return child
    },
    async stop(child) {
      if (child.exitCode === null) {
        child.exitCode = 0
        child.emit('exit', 0, null)
        child.emit('close', 0, null)
      }
    },
  }

  await assert.rejects(runMilestone2({
    environment: TEST_ENVIRONMENT,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => DATABASE,
    mkdtempImpl: () => ownedCorpusRoot('abort-browser-owner'),
    writeFileImpl: () => {},
    rmImpl: () => { events.push('corpus-rm') },
    processRunner,
    portReservationFactory: async () => ({ port: ++nextPort, release: async () => {} }),
    nonceFactory: () => 'abort-browser-owner',
    waitForUrlImpl: async () => {},
    serverLogObserverFactory: () => ({ finish: () => ({ matchCount: 0 }) }),
  }), /backend.*7/i)
  await new Promise(resolve => setTimeout(resolve, 100))

  const positions = [
    'browser-terminate',
    'browser-close',
    'browser-log-finish',
    'db-cleanup',
    'corpus-rm',
  ].map(event => events.indexOf(event))
  assert.equal(positions.every(position => position >= 0), true, events.join(' -> '))
  assert.deepEqual([...positions].sort((a, b) => a - b), positions, events.join(' -> '))
})

test('M2 runner aborts and settles a hanging health wait before cleanup', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  const events = []
  let backend
  let nextPort = 46000

  const processRunner = {
    async run(_command, args) {
      if (args.includes('--drop')) events.push('db-cleanup')
      return {
        status: 0,
        logObserver: { finish: () => ({ matchCount: 0, truncated: false }) },
      }
    },
    start(_command, args) {
      const child = new EventEmitter()
      child.stdout = new EventEmitter()
      child.stderr = new EventEmitter()
      child.exitCode = null
      child.label = args.includes('uvicorn') ? 'backend' : 'vite'
      if (child.label === 'backend') backend = child
      return child
    },
    async stop(child) {
      if (child.exitCode === null) {
        child.exitCode = 0
        child.emit('exit', 0, null)
        child.emit('close', 0, null)
      }
    },
  }
  let healthCalls = 0
  const waitForUrlImpl = (_url, { signal } = {}) => {
    healthCalls += 1
    setTimeout(() => {
      backend.exitCode = 9
      backend.emit('exit', 9, null)
      backend.emit('close', 9, null)
    }, 1)
    return new Promise((_resolve, reject) => {
      signal?.addEventListener('abort', () => {
        events.push('health-abort')
        const error = new Error('health aborted')
        error.name = 'AbortError'
        reject(error)
      }, { once: true })
    }).finally(() => { events.push('health-settle') })
  }

  await assert.rejects(runMilestone2({
    environment: TEST_ENVIRONMENT,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => DATABASE,
    mkdtempImpl: () => ownedCorpusRoot('abort-health-owner'),
    writeFileImpl: () => {},
    rmImpl: () => { events.push('corpus-rm') },
    processRunner,
    portReservationFactory: async () => ({ port: ++nextPort, release: async () => {} }),
    nonceFactory: () => 'abort-health-owner',
    waitForUrlImpl,
    serverLogObserverFactory: () => ({ finish: () => ({ matchCount: 0 }) }),
  }), /backend.*9/i)

  assert.equal(healthCalls, 1)
  assert.deepEqual(events, [
    'health-abort',
    'health-settle',
    'db-cleanup',
    'corpus-rm',
  ])
})

test('M2 runner removes an owned temp directory when post-create validation fails', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  const removed = []
  let validatorCalls = 0

  await assert.rejects(runMilestone2({
    environment: TEST_ENVIRONMENT,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => DATABASE,
    mkdtempImpl: () => ownedCorpusRoot('invalidated-owner'),
    writeFileImpl: () => {},
    rmImpl: (root, options) => removed.push({ root, options }),
    assertExternalCorpusRootImpl: () => {
      validatorCalls += 1
      throw new Error('injected post-create validation failure')
    },
    nonceFactory: () => 'invalidated-owner',
  }), /post-create validation failure/i)

  assert.equal(validatorCalls, 1)
  assert.deepEqual(removed, [{
    root: ownedCorpusRoot('invalidated-owner'),
    options: { recursive: true, force: true },
  }])
})

test('Vite exposes the owner nonce only through its conditional runner middleware', async () => {
  const { m2BrowserOwnershipPlugin } = await import('../../frontend/vite.config.js')
  const registrations = []
  const plugin = m2BrowserOwnershipPlugin('vite-owner-123')
  plugin.configureServer({
    middlewares: { use: (route, handler) => registrations.push({ route, handler }) },
  })
  assert.equal(registrations.length, 1)
  assert.equal(registrations[0].route, '/__m2-browser-owner')

  const headers = new Map()
  let body = ''
  registrations[0].handler(
    { method: 'GET' },
    {
      setHeader: (name, value) => headers.set(name, value),
      end: value => { body = value },
    },
    () => { throw new Error('owned GET must not fall through') },
  )
  assert.equal(headers.get('content-type'), 'application/json; charset=utf-8')
  assert.deepEqual(JSON.parse(body), { browserRunNonce: 'vite-owner-123' })
})

test('M2 runner preserves body, server stop, DB cleanup, and directory cleanup errors', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  let runCount = 0
  const processRunner = {
    async run(_command, args) {
      runCount += 1
      if (args.includes('--drop')) return { status: 13 }
      if (args.includes('test')) return { status: 11 }
      return { status: 0 }
    },
    start() { return {} },
    async stop() { throw new Error('injected stop failure') },
  }

  await assert.rejects(
    runMilestone2({
      specs: FORMAL_SPECS,
      environment: TEST_ENVIRONMENT,
      databaseNameFactory: () => DATABASE,
      mkdtempImpl: () => ownedCorpusRoot('errors-owner'),
      writeFileImpl: () => {},
      rmImpl: () => { throw new Error('injected directory cleanup failure') },
      processRunner,
      waitForUrlImpl: async () => {},
      nonceFactory: () => 'errors-owner',
      serverLogObserverFactory: () => ({ finish: () => ({ matchCount: 0 }) }),
    }),
    error => {
      assert(error instanceof AggregateError)
      assert.equal(error.errors.length, 4)
      assert.match(error.errors[0].message, /browser.*11/i)
      assert.match(error.errors[1].message, /stop/i)
      assert.match(error.errors[2].message, /cleanup.*13/i)
      assert.match(error.errors[3].message, /directory cleanup/i)
      return true
    },
  )
  assert.equal(runCount, 3)
})

test('M2 runner requires the exact formal spec list', async () => {
  const { runMilestone2, validateSpecs } = await import(M2_MODULE)

  await assert.rejects(runMilestone2({ environment: TEST_ENVIRONMENT }), /explicit.*spec/i)
  assert.throws(() => validateSpecs([
    ...FORMAL_SPECS.slice(0, 3),
    { path: '../outside.spec.ts', scenario: 'unknown' },
  ]), /closed|formal|spec/i)
})

test('M2 runner rejects duplicate injected databases across specs', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  let rootCount = 0
  await assert.rejects(
    runMilestone2({
      environment: TEST_ENVIRONMENT,
      specs: FORMAL_SPECS,
      databaseNameFactory: () => DATABASE,
      mkdtempImpl: prefix => `${prefix}${++rootCount}`,
      writeFileImpl: () => {},
      rmImpl: () => {},
      processRunner: {
        async run() { return { status: 0 } },
        start() { return {} },
        async stop() {},
      },
      waitForUrlImpl: async () => {},
      serverLogObserverFactory: () => ({ finish: () => ({ matchCount: 0 }) }),
    }),
    /independent.*database/i,
  )
  assert.equal(rootCount, 1)
})

test('M2 runner rejects and never removes unowned or suffix-free corpus paths', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  const tempParent = path.resolve(os.tmpdir())
  const nonce = 'path-audit-owner'
  const invalidRoots = [
    tempParent,
    path.join(tempParent, 'unrelated-directory'),
    path.resolve(tempParent, '..', 'arbitrary-m2-audit-directory'),
    path.join(tempParent, `novel-creator-m2-corpus-${nonce}-`),
  ]

  for (const invalidRoot of invalidRoots) {
    const removed = []
    let writes = 0
    await assert.rejects(
      runMilestone2({
        environment: TEST_ENVIRONMENT,
        specs: FORMAL_SPECS,
        databaseNameFactory: () => DATABASE,
        mkdtempImpl: () => invalidRoot,
        writeFileImpl: () => { writes += 1 },
        rmImpl: (root, options) => removed.push({ root, options }),
        nonceFactory: () => nonce,
      }),
      /owned corpus/i,
    )
    assert.equal(writes, 0)
    assert.deepEqual(removed, [])
  }
})

test('M2 runner scans bounded browser output even when Playwright fails', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  let browserScanned = false
  const processRunner = {
    async run(_command, args) {
      if (!args.includes('test')) return { status: 0 }
      return {
        status: 17,
        logObserver: {
          finish() {
            browserScanned = true
            return { matchCount: 0 }
          },
        },
      }
    },
    start() { return {} },
    async stop() {},
  }
  await assert.rejects(runMilestone2({
    environment: TEST_ENVIRONMENT,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => DATABASE,
    mkdtempImpl: () => ownedCorpusRoot('scan-failure-owner'),
    writeFileImpl: () => {},
    rmImpl: () => {},
    processRunner,
    waitForUrlImpl: async () => {},
    nonceFactory: () => 'scan-failure-owner',
    serverLogObserverFactory: () => ({ finish: () => ({ matchCount: 0 }) }),
  }), /browser.*17/i)
  assert.equal(browserScanned, true)
})

test('M2 server scan failures report only a count without echoing sensitive values', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  let observerCount = 0
  let scannedValues = []
  const processRunner = {
    async run() {
      return {
        status: 0,
        logObserver: { finish: () => ({ matchCount: 0, truncated: false }) },
      }
    },
    start() { return {} },
    async stop() {},
  }

  await assert.rejects(runMilestone2({
    environment: TEST_ENVIRONMENT,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => DATABASE,
    mkdtempImpl: () => ownedCorpusRoot('log-leak-owner'),
    writeFileImpl: () => {},
    rmImpl: () => {},
    processRunner,
    waitForUrlImpl: async () => {},
    nonceFactory: () => 'log-leak-owner',
    serverLogObserverFactory: (_child, { sensitiveValues }) => {
      const observerIndex = ++observerCount
      scannedValues = sensitiveValues
      return {
        finish: () => ({
          matchCount: observerIndex === 1 ? 1 : 0,
          truncated: true,
        }),
      }
    },
  }), error => {
    const rendered = String(error)
    assert.match(rendered, /sensitive match count was 1/i)
    assert.equal(rendered.includes(TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD), false)
    assert.equal(rendered.includes(DATABASE), false)
    assert.equal(rendered.includes('mysql://'), false)
    return true
  })
  assert.equal(scannedValues.includes(TEST_ENVIRONMENT.TEST_MYSQL_PASSWORD), true)
  assert.equal(scannedValues.includes(DATABASE), true)
  assert.equal(scannedValues.some(value => value.startsWith('mysql://')), true)
})

import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
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
    'C:\\Temp\\novel-creator-m2-corpus-a',
    'C:\\Temp\\novel-creator-m2-corpus-b',
    'C:\\Temp\\novel-creator-m2-corpus-c',
    'C:\\Temp\\novel-creator-m2-corpus-d',
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
      assert.match(prefix, /novel-creator-m2-corpus-$/)
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
    'C:\\Temp\\novel-creator-m2-corpus-a',
    'C:\\Temp\\novel-creator-m2-corpus-b',
    'C:\\Temp\\novel-creator-m2-corpus-c',
    'C:\\Temp\\novel-creator-m2-corpus-d',
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
  assert.equal(observed[0].sensitiveValues.includes('C:\\Temp\\novel-creator-m2-corpus-a'), true)
  assert.equal(observed[2].sensitiveValues.includes('C:\\Temp\\novel-creator-m2-corpus-b'), true)
  assert.equal(observed[4].sensitiveValues.includes('C:\\Temp\\novel-creator-m2-corpus-c'), true)
  assert.equal(observed[6].sensitiveValues.includes('C:\\Temp\\novel-creator-m2-corpus-d'), true)
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
    mkdtempImpl: () => 'C:\\Temp\\novel-creator-m2-corpus-early-exit',
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

test('M2 runner removes an owned temp directory when post-create validation fails', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  const removed = []
  let validatorCalls = 0

  await assert.rejects(runMilestone2({
    environment: TEST_ENVIRONMENT,
    specs: FORMAL_SPECS,
    databaseNameFactory: () => DATABASE,
    mkdtempImpl: () => 'C:\\Temp\\novel-creator-m2-corpus-invalidated',
    writeFileImpl: () => {},
    rmImpl: (root, options) => removed.push({ root, options }),
    assertExternalCorpusRootImpl: () => {
      validatorCalls += 1
      throw new Error('injected post-create validation failure')
    },
  }), /post-create validation failure/i)

  assert.equal(validatorCalls, 1)
  assert.deepEqual(removed, [{
    root: 'C:\\Temp\\novel-creator-m2-corpus-invalidated',
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
      mkdtempImpl: () => 'C:\\Temp\\novel-creator-m2-corpus-errors',
      writeFileImpl: () => {},
      rmImpl: () => { throw new Error('injected directory cleanup failure') },
      processRunner,
      waitForUrlImpl: async () => {},
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
      mkdtempImpl: () => `C:\\Temp\\novel-creator-m2-corpus-${++rootCount}`,
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

test('M2 runner never recursively removes a path that fails external-root validation', async () => {
  const { runMilestone2 } = await import(M2_MODULE)
  const removed = []
  await assert.rejects(
    runMilestone2({
      environment: TEST_ENVIRONMENT,
      specs: FORMAL_SPECS,
      databaseNameFactory: () => DATABASE,
      mkdtempImpl: () => process.cwd(),
      rmImpl: (root, options) => removed.push({ root, options }),
    }),
    /outside the repository/i,
  )
  assert.deepEqual(removed, [])
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
    mkdtempImpl: () => 'C:\\Temp\\novel-creator-m2-corpus-scan-failure',
    writeFileImpl: () => {},
    rmImpl: () => {},
    processRunner,
    waitForUrlImpl: async () => {},
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
    mkdtempImpl: () => 'C:\\Temp\\novel-creator-m2-corpus-log-leak',
    writeFileImpl: () => {},
    rmImpl: () => {},
    processRunner,
    waitForUrlImpl: async () => {},
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

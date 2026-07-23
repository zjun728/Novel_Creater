import assert from 'node:assert/strict'
import {
  existsSync,
  lstatSync,
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { discoverTestFiles, runSuites } from '../run-tests.mjs'

const scriptsDirectory = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const repositoryRoot = path.dirname(scriptsDirectory)
const runnerPath = path.join(scriptsDirectory, 'run-tests.mjs')

test('package scripts retain earlier and Phase 2C gates while full Phase 2 is default', () => {
  const rootPackage = JSON.parse(readFileSync(path.join(repositoryRoot, 'package.json'), 'utf8'))
  const frontendPackage = JSON.parse(
    readFileSync(path.join(repositoryRoot, 'frontend', 'package.json'), 'utf8'),
  )

  assert.equal(rootPackage.scripts['test:browser'], 'node scripts/run-tests.mjs browser-phase2')
  assert.equal(rootPackage.scripts['test:browser:m2'], undefined)
  assert.equal(rootPackage.scripts['test:milestone1'], 'node scripts/run-tests.mjs m1-regression')
  assert.equal(rootPackage.scripts['test:milestone2'], undefined)
  assert.equal(
    rootPackage.scripts['test:browser:phase2a'],
    'node scripts/run-tests.mjs browser-phase2a',
  )
  assert.equal(
    rootPackage.scripts['test:browser:phase2c'],
    'node scripts/run-tests.mjs browser-phase2c',
  )
  assert.equal(
    rootPackage.scripts['test:browser:phase2'],
    'node scripts/run-tests.mjs browser-phase2',
  )
  assert.equal(rootPackage.scripts.build, 'npm --prefix frontend run build')
  assert.equal(frontendPackage.scripts['test:e2e:m1'], 'node e2e/run-milestone1.mjs')
  assert.equal(frontendPackage.scripts['test:e2e:m2'], undefined)
  assert.equal(frontendPackage.scripts['test:e2e:phase2a'], 'node e2e/run-phase2a.mjs')
  assert.equal(frontendPackage.scripts['test:e2e:phase2c'], 'node e2e/run-phase2c.mjs')
  assert.equal(frontendPackage.scripts['test:e2e:phase2'], 'node e2e/run-phase2.mjs')
  assert.equal(frontendPackage.scripts['test:e2e'], 'node e2e/run-phase2.mjs')
})

test('discovers only explicit test modules in stable order', () => {
  const directory = mkdtempSync(path.join(scriptsDirectory, 'test-discovery-'))

  try {
    writeFileSync(path.join(directory, 'z-last.test.mjs'), '')
    writeFileSync(path.join(directory, 'a-first.test.mjs'), '')
    writeFileSync(path.join(directory, 'notes.mjs'), '')
    writeFileSync(path.join(directory, 'almost.test.js'), '')
    mkdirSync(path.join(directory, 'nested.test.mjs'))

    assert.deepEqual(discoverTestFiles(directory), [
      path.join(directory, 'a-first.test.mjs'),
      path.join(directory, 'z-last.test.mjs'),
    ])
  } finally {
    rmSync(directory, { recursive: true, force: true })
  }
})

for (const requested of [[], ['unknown']]) {
  const label = requested.length === 0 ? 'an empty suite list' : 'an unknown suite'

  test(`returns exit code 2 and usage for ${label}`, () => {
    const result = spawnSync(process.execPath, [runnerPath, ...requested], {
      cwd: path.dirname(scriptsDirectory),
      encoding: 'utf8',
      shell: false,
    })

    assert.equal(result.status, 2)
    assert.match(result.stderr, /^usage: node scripts\/run-tests\.mjs /)
  })
}

test('can be imported without executing the command-line entrypoint', async () => {
  const module = await import(pathToFileURL(runnerPath))
  assert.equal(typeof module.discoverTestFiles, 'function')
})

test('reports a diagnostic when a child command cannot start', () => {
  const missingCommand = 'writer-core-command-that-does-not-exist'
  const result = spawnSync(process.execPath, [runnerPath, 'unit'], {
    cwd: path.dirname(scriptsDirectory),
    encoding: 'utf8',
    env: { ...process.env, PYTHON: missingCommand },
    shell: false,
  })

  assert.notEqual(result.status, 0)
  assert.match(result.stderr, new RegExp(`Failed to start ${missingCommand}`))
  assert.match(result.stderr, /ENOENT/)
})

test('uses the injected child process runner', () => {
  const calls = []
  const exitCode = runSuites(['browser'], {
    spawnSyncImpl(command, args, options) {
      calls.push({ command, args, options })
      return { status: 0 }
    },
  })

  assert.equal(exitCode, 0)
  assert.equal(calls.length, 1)
  assert.equal(calls[0].command, process.execPath)
  assert.deepEqual(calls[0].args, ['frontend/e2e/run-milestone1.mjs'])
  assert.equal(calls[0].options.shell, false)
})

const requiredIntegrationEnvironment = {
  TEST_MYSQL_HOST: '127.0.0.1',
  TEST_MYSQL_PORT: '33060',
  TEST_MYSQL_USER: 'root',
  TEST_MYSQL_PASSWORD: 'test-only-secret',
}

const approvedPytestTempStages = Object.freeze({
  m1Regression: path.join('.codex-test-artifacts', 'pytest', 'm1-regression'),
  unitApi: path.join('.codex-test-artifacts', 'pytest', 'unit-api'),
  integration: path.join('.codex-test-artifacts', 'pytest', 'integration'),
})

function pytestBasetemp(call) {
  const index = call.args.indexOf('--basetemp')
  if (index === -1 || index + 1 >= call.args.length) return null
  assert.equal(call.args.indexOf('--basetemp', index + 1), -1)
  return call.args[index + 1]
}

function pytestBasetempLabel(args) {
  const stage = pytestBasetemp({ args })
  return stage === null ? 'missing-basetemp' : path.basename(stage)
}

function assertApprovedPytestStage(stage) {
  assert.equal(Object.values(approvedPytestTempStages).includes(stage), true)
  assert.doesNotMatch(stage, /keep-me/u)
}

const noOpPytestTempLifecycle = Object.freeze({
  prepare() {},
  cleanupStage() {},
  cleanupAll() {},
})

const tempSecretSentinel = 'temp-secret-sentinel'
const lifecycleFailureEnvironment = Object.freeze({
  ...requiredIntegrationEnvironment,
  TEST_MYSQL_PASSWORD: tempSecretSentinel,
})

function captureStderr() {
  let value = ''
  return {
    stream: { write(chunk) { value += chunk } },
    value() { return value },
  }
}

function assertSafeLifecycleStderr(stderr, expectedCode, expectedStage) {
  assert.doesNotMatch(stderr, new RegExp(tempSecretSentinel, 'u'))
  assert.doesNotMatch(stderr, /TEST_MYSQL_|127\.0\.0\.1|33060/iu)
  assert.match(stderr, new RegExp(`\\[${expectedCode}\\] stage=${expectedStage}(?: |\\n|$)`, 'u'))
  for (const line of stderr.trim().split(/\r?\n/u).filter(Boolean)) {
    assert.match(
      line,
      /^\[PYTEST_[A-Z_]+\] stage=(?:m1-regression|unit-api|integration)(?: (?:code|status)=[A-Z0-9_-]+)?$/u,
    )
  }
}

function createFormalFakeRoot({ pytestNamespaceAsFile = false } = {}) {
  const rootDirectory = mkdtempSync(path.join(scriptsDirectory, 'pytest-lifecycle-root-'))
  const scriptTests = path.join(rootDirectory, 'scripts', 'tests')
  const frontendTests = path.join(rootDirectory, 'frontend', 'tests', 'unit')
  const artifactRoot = path.join(rootDirectory, '.codex-test-artifacts')
  const pytestNamespace = path.join(artifactRoot, 'pytest')
  const keepEvidence = path.join(artifactRoot, 'keep-me', 'evidence.txt')

  mkdirSync(scriptTests, { recursive: true })
  mkdirSync(frontendTests, { recursive: true })
  mkdirSync(path.dirname(keepEvidence), { recursive: true })
  writeFileSync(path.join(scriptTests, 'formal.test.mjs'), '')
  writeFileSync(path.join(frontendTests, 'formal.test.mjs'), '')
  writeFileSync(keepEvidence, 'preserve this evidence')

  if (pytestNamespaceAsFile) {
    writeFileSync(pytestNamespace, 'block pytest namespace creation')
  } else {
    const staleEvidence = path.join(
      rootDirectory,
      approvedPytestTempStages.unitApi,
      'stale.txt',
    )
    mkdirSync(path.dirname(staleEvidence), { recursive: true })
    writeFileSync(staleEvidence, 'remove stale pytest content')
  }

  return { keepEvidence, pytestNamespace, rootDirectory }
}

function createReparsePointFixture(location) {
  const rootDirectory = mkdtempSync(path.join(scriptsDirectory, 'pytest-reparse-root-'))
  const externalDirectory = mkdtempSync(path.join(scriptsDirectory, 'pytest-reparse-external-'))
  const scriptTests = path.join(rootDirectory, 'scripts', 'tests')
  const frontendTests = path.join(rootDirectory, 'frontend', 'tests', 'unit')
  const artifactRoot = path.join(rootDirectory, '.codex-test-artifacts')
  const pytestNamespace = path.join(artifactRoot, 'pytest')
  const stage = path.join(pytestNamespace, 'unit-api')
  const sentinel = path.join(externalDirectory, 'external-sentinel.txt')

  mkdirSync(scriptTests, { recursive: true })
  mkdirSync(frontendTests, { recursive: true })
  writeFileSync(path.join(scriptTests, 'formal.test.mjs'), '')
  writeFileSync(path.join(frontendTests, 'formal.test.mjs'), '')
  writeFileSync(sentinel, 'preserve external evidence')

  const link = { artifactRoot, pytestNamespace, stage }[location]
  mkdirSync(path.dirname(link), { recursive: true })
  symlinkSync(externalDirectory, link, 'junction')

  return { externalDirectory, link, rootDirectory, sentinel }
}

for (const missingName of Object.keys(requiredIntegrationEnvironment)) {
  test(`integration fails closed before pytest when ${missingName} is missing`, () => {
    const environment = { ...requiredIntegrationEnvironment }
    delete environment[missingName]
    const calls = []
    let stderr = ''

    const exitCode = runSuites(['integration'], {
      environment,
      spawnSyncImpl(command, args, options) {
        calls.push({ command, args, options })
        return { status: 0 }
      },
      stderr: { write(chunk) { stderr += chunk } },
    })

    assert.equal(exitCode, 2)
    assert.deepEqual(calls, [])
    assert.match(stderr, new RegExp(`requires explicit variables: ${missingName}`))
    assert.doesNotMatch(stderr, /test-only-secret/)
  })
}

for (const suite of [
  'browser',
  'browser-product-shell',
  'browser-phase2a',
  'browser-phase2b',
  'browser-phase2c',
]) {
  test(`${suite} fails closed before child execution without explicit browser MySQL`, () => {
    const environment = { ...requiredIntegrationEnvironment }
    delete environment.TEST_MYSQL_PASSWORD
    const calls = []
    let stderr = ''

    const exitCode = runSuites([suite], {
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
  })
}

test('prepares and cleans the fixed pytest stage around a successful child', () => {
  const events = []
  const exitCode = runSuites(['integration'], {
    environment: requiredIntegrationEnvironment,
    pytestTempLifecycle: {
      prepare(_rootDirectory, stage) {
        assertApprovedPytestStage(stage)
        assert.equal(stage, approvedPytestTempStages.integration)
        events.push(`prepare:${path.basename(stage)}`)
      },
      cleanupStage(_rootDirectory, stage) {
        assertApprovedPytestStage(stage)
        assert.equal(stage, approvedPytestTempStages.integration)
        events.push(`cleanup:${path.basename(stage)}`)
      },
      cleanupAll() {
        events.push('cleanup-all')
      },
    },
    spawnSyncImpl(_command, args) {
      events.push(`spawn:${pytestBasetempLabel(args)}`)
      return { status: 0 }
    },
  })

  assert.equal(exitCode, 0)
  assert.deepEqual(events, [
    'prepare:integration',
    'spawn:integration',
    'cleanup:integration',
    'cleanup-all',
  ])
})

test('a pytest temp preparation failure prevents spawn and still cleans all stages', () => {
  const events = []
  const stderr = captureStderr()
  const exitCode = runSuites(['integration'], {
    environment: lifecycleFailureEnvironment,
    pytestTempLifecycle: {
      prepare(_rootDirectory, stage) {
        assertApprovedPytestStage(stage)
        assert.equal(stage, approvedPytestTempStages.integration)
        events.push(`prepare:${path.basename(stage)}`)
        throw new Error(`synthetic preparation failure: ${tempSecretSentinel}`)
      },
      cleanupStage(_rootDirectory, stage) {
        events.push(`unexpected-cleanup:${path.basename(stage)}`)
      },
      cleanupAll() {
        events.push('cleanup-all')
      },
    },
    spawnSyncImpl() {
      events.push('spawn')
      return { status: 0 }
    },
    stderr: stderr.stream,
  })

  assert.notEqual(exitCode, 0)
  assert.deepEqual(events, ['prepare:integration', 'cleanup-all'])
  assertSafeLifecycleStderr(stderr.value(), 'PYTEST_TEMP_PREPARE_FAILED', 'integration')
})

for (const scenario of [
  {
    name: 'a non-zero pytest child',
    childResult: { status: 7 },
    expectedExitCode: 7,
    expectedErrorCode: 'PYTEST_CHILD_FAILED',
  },
  {
    name: 'a pytest spawn error',
    childResult: {
      status: null,
      error: Object.assign(
        new Error(`synthetic spawn failure: ${tempSecretSentinel}`),
        { code: 'ESYNTHETIC' },
      ),
    },
    expectedExitCode: 1,
    expectedErrorCode: 'PYTEST_CHILD_START_FAILED',
  },
]) {
  test(`${scenario.name} cleans the stage and aggregate namespace`, () => {
    const events = []
    const stderr = captureStderr()
    const exitCode = runSuites(['integration'], {
      environment: lifecycleFailureEnvironment,
      pytestTempLifecycle: {
        prepare(_rootDirectory, stage) {
          assertApprovedPytestStage(stage)
          events.push(`prepare:${path.basename(stage)}`)
        },
        cleanupStage(_rootDirectory, stage) {
          assertApprovedPytestStage(stage)
          events.push(`cleanup:${path.basename(stage)}`)
        },
        cleanupAll() {
          events.push('cleanup-all')
        },
      },
      spawnSyncImpl(_command, args) {
        events.push(`spawn:${pytestBasetempLabel(args)}`)
        return scenario.childResult
      },
      stderr: stderr.stream,
    })

    assert.equal(exitCode, scenario.expectedExitCode)
    assert.deepEqual(events, [
      'prepare:integration',
      'spawn:integration',
      'cleanup:integration',
      'cleanup-all',
    ])
    assertSafeLifecycleStderr(stderr.value(), scenario.expectedErrorCode, 'integration')
  })
}

test('a pytest stage cleanup failure still runs cleanup-all and returns non-zero', () => {
  const events = []
  const stderr = captureStderr()
  const exitCode = runSuites(['integration'], {
    environment: lifecycleFailureEnvironment,
    pytestTempLifecycle: {
      prepare(_rootDirectory, stage) {
        assertApprovedPytestStage(stage)
        events.push(`prepare:${path.basename(stage)}`)
      },
      cleanupStage(_rootDirectory, stage) {
        assertApprovedPytestStage(stage)
        events.push(`cleanup:${path.basename(stage)}`)
        throw new Error(`synthetic cleanup failure: ${tempSecretSentinel}`)
      },
      cleanupAll() {
        events.push('cleanup-all')
      },
    },
    spawnSyncImpl(_command, args) {
      events.push(`spawn:${pytestBasetempLabel(args)}`)
      return { status: 0 }
    },
    stderr: stderr.stream,
  })

  assert.notEqual(exitCode, 0)
  assert.deepEqual(events, [
    'prepare:integration',
    'spawn:integration',
    'cleanup:integration',
    'cleanup-all',
  ])
  assertSafeLifecycleStderr(stderr.value(), 'PYTEST_TEMP_CLEANUP_FAILED', 'integration')
})

for (const scenario of [
  {
    name: 'turns a successful child into a failure',
    childResult: { status: 0 },
    expectedExitCode: 1,
    expectedErrorCodes: ['PYTEST_TEMP_CLEANUP_ALL_FAILED'],
  },
  {
    name: 'preserves an existing child failure status',
    childResult: { status: 7 },
    expectedExitCode: 7,
    expectedErrorCodes: ['PYTEST_CHILD_FAILED', 'PYTEST_TEMP_CLEANUP_ALL_FAILED'],
  },
]) {
  test(`a cleanup-all failure ${scenario.name} without leaking secrets`, () => {
    const events = []
    const stderr = captureStderr()
    const exitCode = runSuites(['integration'], {
      environment: lifecycleFailureEnvironment,
      pytestTempLifecycle: {
        prepare(_rootDirectory, stage) {
          assertApprovedPytestStage(stage)
          events.push(`prepare:${path.basename(stage)}`)
        },
        cleanupStage(_rootDirectory, stage) {
          assertApprovedPytestStage(stage)
          events.push(`cleanup:${path.basename(stage)}`)
        },
        cleanupAll() {
          events.push('cleanup-all')
          throw new Error(`synthetic aggregate cleanup failure: ${tempSecretSentinel}`)
        },
      },
      spawnSyncImpl(_command, args) {
        events.push(`spawn:${pytestBasetempLabel(args)}`)
        return scenario.childResult
      },
      stderr: stderr.stream,
    })

    assert.equal(exitCode, scenario.expectedExitCode)
    assert.deepEqual(events, [
      'prepare:integration',
      'spawn:integration',
      'cleanup:integration',
      'cleanup-all',
    ])
    for (const errorCode of scenario.expectedErrorCodes) {
      assertSafeLifecycleStderr(stderr.value(), errorCode, 'integration')
    }
  })
}

for (const scenario of [
  {
    name: 'success',
    result: { status: 0 },
    expectedExitCode: 0,
  },
  {
    name: 'child non-zero',
    result: { status: 7 },
    expectedExitCode: 7,
    expectedErrorCode: 'PYTEST_CHILD_FAILED',
  },
  {
    name: 'spawn error',
    result: {
      status: null,
      error: Object.assign(
        new Error(`default spawn failure: ${tempSecretSentinel}`),
        { code: 'ESYNTHETIC' },
      ),
    },
    expectedExitCode: 1,
    expectedErrorCode: 'PYTEST_CHILD_START_FAILED',
  },
]) {
  test(`the default lifecycle preserves unrelated evidence after ${scenario.name}`, () => {
    const fixture = createFormalFakeRoot()
    const stderr = captureStderr()

    try {
      const exitCode = runSuites(['unit'], {
        rootDirectory: fixture.rootDirectory,
        environment: lifecycleFailureEnvironment,
        spawnSyncImpl() {
          return scenario.result
        },
        stderr: stderr.stream,
      })

      assert.equal(exitCode, scenario.expectedExitCode)
      assert.equal(existsSync(fixture.keepEvidence), true)
      if (scenario.expectedErrorCode) {
        assertSafeLifecycleStderr(stderr.value(), scenario.expectedErrorCode, 'unit-api')
      } else {
        assert.equal(stderr.value(), '')
      }
      assert.equal(existsSync(fixture.pytestNamespace), false)
    } finally {
      rmSync(fixture.rootDirectory, { recursive: true, force: true })
    }
  })
}

test('a default preparation failure spawns no child and redacts its environment', () => {
  const fixture = createFormalFakeRoot({ pytestNamespaceAsFile: true })
  const stderr = captureStderr()
  let spawnCount = 0

  try {
    const exitCode = runSuites(['unit'], {
      rootDirectory: fixture.rootDirectory,
      environment: lifecycleFailureEnvironment,
      spawnSyncImpl() {
        spawnCount += 1
        return { status: 0 }
      },
      stderr: stderr.stream,
    })

    assert.notEqual(exitCode, 0)
    assert.equal(spawnCount, 0)
    assert.equal(existsSync(fixture.keepEvidence), true)
    assert.equal(existsSync(fixture.pytestNamespace), false)
    assertSafeLifecycleStderr(stderr.value(), 'PYTEST_TEMP_PREPARE_FAILED', 'unit-api')
  } finally {
    rmSync(fixture.rootDirectory, { recursive: true, force: true })
  }
})

for (const location of ['artifactRoot', 'pytestNamespace', 'stage']) {
  test(`the default lifecycle rejects a ${location} junction without touching its target`, () => {
    const fixture = createReparsePointFixture(location)
    const stderr = captureStderr()
    let spawnCount = 0

    try {
      const exitCode = runSuites(['unit'], {
        rootDirectory: fixture.rootDirectory,
        environment: lifecycleFailureEnvironment,
        spawnSyncImpl() {
          spawnCount += 1
          return { status: 0 }
        },
        stderr: stderr.stream,
      })

      assert.notEqual(exitCode, 0)
      assert.equal(spawnCount, 0)
      assert.equal(existsSync(fixture.externalDirectory), true)
      assert.equal(existsSync(fixture.sentinel), true)
      assert.equal(existsSync(fixture.link), true)
      assert.equal(lstatSync(fixture.link).isSymbolicLink(), true)
      assertSafeLifecycleStderr(stderr.value(), 'PYTEST_TEMP_PREPARE_FAILED', 'unit-api')
      assert.doesNotMatch(stderr.value(), new RegExp(escapeRegExp(fixture.externalDirectory), 'iu'))
    } finally {
      try {
        rmSync(fixture.externalDirectory, { recursive: true, force: true })
      } finally {
        rmSync(fixture.rootDirectory, { recursive: true, force: true })
      }
    }
  })
}

test('browser-phase2c rejects a root missing its formal spec before child execution', () => {
  const rootDirectory = mkdtempSync(path.join(scriptsDirectory, 'formal-browser-root-'))
  const e2eDirectory = path.join(rootDirectory, 'frontend', 'e2e')

  try {
    mkdirSync(e2eDirectory, { recursive: true })
    mkdirSync(path.join(rootDirectory, 'scripts', 'tests'), { recursive: true })
    mkdirSync(path.join(rootDirectory, 'frontend', 'tests', 'unit'), { recursive: true })
    const calls = []
    let stderr = ''
    const exitCode = runSuites(['browser-phase2c'], {
      rootDirectory,
      environment: requiredIntegrationEnvironment,
      spawnSyncImpl(command, args, options) {
        calls.push({ command, args, options })
        return { status: 0 }
      },
      stderr: { write(chunk) { stderr += chunk } },
    })

    assert.equal(exitCode, 2)
    assert.deepEqual(calls, [])
    assert.match(stderr, /missing formal test/i)
    assert.match(stderr, /phase2c-contract\.spec\.ts/)
  } finally {
    rmSync(rootDirectory, { recursive: true, force: true })
  }
})

for (const scenario of [
  {
    suite: 'unit',
    emptyDirectory: path.join('scripts', 'tests'),
    populatedDirectory: path.join('frontend', 'tests', 'unit'),
  },
  {
    suite: 'frontend-unit',
    emptyDirectory: path.join('frontend', 'tests', 'unit'),
    populatedDirectory: path.join('scripts', 'tests'),
  },
]) {
  test(`${scenario.suite} fails closed when its formal test directory is empty`, () => {
    const rootDirectory = mkdtempSync(path.join(scriptsDirectory, 'dispatcher-root-'))
    const emptyDirectory = path.join(rootDirectory, scenario.emptyDirectory)
    const populatedDirectory = path.join(rootDirectory, scenario.populatedDirectory)

    try {
      mkdirSync(emptyDirectory, { recursive: true })
      mkdirSync(populatedDirectory, { recursive: true })
      writeFileSync(path.join(populatedDirectory, 'formal.test.mjs'), '')
      writeFileSync(path.join(rootDirectory, 'rogue.test.mjs'), 'throw new Error("must not run")')

      const calls = []
      let stderr = ''
      const exitCode = runSuites([scenario.suite], {
        rootDirectory,
        spawnSyncImpl(command, args, options) {
          calls.push({ command, args, options })
          return { status: 0 }
        },
        stderr: { write(chunk) { stderr += chunk } },
      })

      assert.equal(exitCode, 2)
      assert.deepEqual(calls, [])
      assert.match(stderr, new RegExp(`No formal tests found in ${escapeRegExp(emptyDirectory)}`))
    } finally {
      rmSync(rootDirectory, { recursive: true, force: true })
    }
  })
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

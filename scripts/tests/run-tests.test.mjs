import assert from 'node:assert/strict'
import {
  mkdtempSync,
  mkdirSync,
  readFileSync,
  rmSync,
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

test('package scripts expose only the frozen M1 and M2 entrypoints', () => {
  const rootPackage = JSON.parse(readFileSync(path.join(repositoryRoot, 'package.json'), 'utf8'))
  const frontendPackage = JSON.parse(
    readFileSync(path.join(repositoryRoot, 'frontend', 'package.json'), 'utf8'),
  )

  assert.equal(rootPackage.scripts['test:browser'], 'node scripts/run-tests.mjs browser-m2')
  assert.equal(rootPackage.scripts['test:browser:m2'], 'node scripts/run-tests.mjs browser-m2')
  assert.equal(rootPackage.scripts['test:milestone1'], 'node scripts/run-tests.mjs m1-regression')
  assert.equal(rootPackage.scripts['test:milestone2'], 'node scripts/run-tests.mjs milestone2')
  assert.equal(frontendPackage.scripts['test:e2e:m1'], 'node e2e/run-milestone1.mjs')
  assert.equal(frontendPackage.scripts['test:e2e:m2'], 'node e2e/run-milestone2.mjs')
  assert.equal(frontendPackage.scripts['test:e2e'], 'node e2e/run-milestone2.mjs')
})

test('M2 CLI and exported validator own the exact formal spec map', async () => {
  const runner = await import('../../frontend/e2e/run-milestone2.mjs')
  const expected = [
    { path: 'e2e/m2-foundation-regression.spec.ts', scenario: 'foundation' },
    { path: 'e2e/m2-wizard-manual.spec.ts', scenario: 'manual' },
    { path: 'e2e/m2-wizard-recovery.spec.ts', scenario: 'recovery' },
    { path: 'e2e/m2-settings-assets-corpus.spec.ts', scenario: 'settings' },
  ]

  assert.deepEqual(runner.FORMAL_SPECS, expected)
  assert.deepEqual(runner.resolveCommandLineSpecs([]), expected)
  assert.deepEqual(runner.validateSpecs(expected), expected)
  assert.throws(
    () => runner.resolveCommandLineSpecs(['e2e/arbitrary.spec.ts']),
    /does not accept spec paths/i,
  )
  assert.throws(
    () => runner.validateSpecs([
      ...expected.slice(0, 3),
      { path: 'e2e/arbitrary.spec.ts', scenario: 'settings' },
    ]),
    /closed|formal|spec/i,
  )
  assert.throws(
    () => runner.validateSpecs([...expected.slice(0, 3), expected[0]]),
    /closed|formal|spec/i,
  )
  assert.throws(
    () => runner.validateSpecs([
      expected[0],
      { ...expected[1], scenario: 'recovery' },
      expected[2],
      expected[3],
    ]),
    /closed|formal|spec/i,
  )
  assert.throws(
    () => runner.validateSpecs(expected.slice(0, 3)),
    /closed|formal|spec/i,
  )
  assert.throws(
    () => runner.validateSpecs([expected[1], expected[0], expected[2], expected[3]]),
    /closed|formal|spec/i,
  )
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

for (const suite of ['browser', 'browser-m2', 'milestone2']) {
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

test('milestone2 composes retained M1, unit API, integration, and M2 browser in order', () => {
  function capture(requested) {
    const calls = []
    let stderr = ''
    const exitCode = runSuites(requested, {
      environment: requiredIntegrationEnvironment,
      spawnSyncImpl(command, args, options) {
        calls.push({ command, args, options })
        return { status: 0 }
      },
      stderr: { write(chunk) { stderr += chunk } },
    })
    assert.equal(exitCode, 0, stderr)
    return calls
  }

  const retainedM1 = capture(['m1-regression'])
  const unitApi = capture(['unit'])
  const integration = capture(['integration'])
  const browserM2 = capture(['browser-m2'])
  const milestone2 = capture(['milestone2'])

  assert.deepEqual(milestone2, [
    ...retainedM1,
    ...unitApi,
    ...integration,
    ...browserM2,
  ])
  const retainedText = JSON.stringify(retainedM1)
  assert.match(retainedText, /test_schema_version\.py/)
  assert.match(retainedText, /m1Navigation\.test\.mjs/)
  assert.doesNotMatch(retainedText, /writer-core-v1\.0|milestone1\.spec|run-milestone1/)

  const formalCommandText = JSON.stringify(milestone2)
  assert.doesNotMatch(
    formalCommandText,
    /scripts[\\/]run-tests\.mjs|[\\/]tmp[\\/]|phase-e|e\.23|run-milestone1|milestone1\.spec/iu,
  )
  assert.equal(milestone2.every(call => call.options.shell === false), true)
})

test('browser-m2 rejects a root missing any formal spec before child execution', () => {
  const rootDirectory = mkdtempSync(path.join(scriptsDirectory, 'formal-browser-root-'))
  const e2eDirectory = path.join(rootDirectory, 'frontend', 'e2e')
  const presentSpecs = [
    'm2-foundation-regression.spec.ts',
    'm2-wizard-recovery.spec.ts',
    'm2-settings-assets-corpus.spec.ts',
  ]

  try {
    mkdirSync(e2eDirectory, { recursive: true })
    mkdirSync(path.join(rootDirectory, 'scripts', 'tests'), { recursive: true })
    mkdirSync(path.join(rootDirectory, 'frontend', 'tests', 'unit'), { recursive: true })
    for (const file of presentSpecs) writeFileSync(path.join(e2eDirectory, file), '')
    const calls = []
    let stderr = ''
    const exitCode = runSuites(['browser-m2'], {
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
    assert.match(stderr, /m2-wizard-manual\.spec\.ts/)
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

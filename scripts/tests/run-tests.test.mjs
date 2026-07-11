import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { discoverTestFiles, runSuites } from '../run-tests.mjs'

const scriptsDirectory = path.dirname(path.dirname(fileURLToPath(import.meta.url)))
const runnerPath = path.join(scriptsDirectory, 'run-tests.mjs')

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

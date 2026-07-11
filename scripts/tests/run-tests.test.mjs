import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import test from 'node:test'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { discoverTestFiles } from '../run-tests.mjs'

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

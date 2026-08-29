import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import path from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

test('official frontend unit entrypoint executes Node tests', () => {
  assert.equal(process.release.name, 'node')
})

test('official inventory names the unique Phase 8A Playwright specification', () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..', '..')
  const runner = readFileSync(path.join(root, 'scripts', 'run-tests.mjs'), 'utf8')
  const declaration = 'frontend/e2e/phase8a/manuscript-productization.spec.mjs'
  assert.equal(runner.split(declaration).length - 1, 1)
  assert.equal(existsSync(path.join(root, declaration)), true)
})

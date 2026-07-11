import assert from 'node:assert/strict'
import test from 'node:test'

test('official frontend unit entrypoint executes Node tests', () => {
  assert.equal(process.release.name, 'node')
})

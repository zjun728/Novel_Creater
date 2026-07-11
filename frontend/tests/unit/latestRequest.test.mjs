import assert from 'node:assert/strict'
import test from 'node:test'

import { createLatestRequestGuard } from '../../src/utils/latestRequest.js'

test('only the latest request generation may commit state', () => {
  const guard = createLatestRequestGuard()
  const first = guard.begin()
  const second = guard.begin()

  assert.equal(guard.isCurrent(first), false)
  assert.equal(guard.isCurrent(second), true)
})

test('invalidating a request prevents late completion after unmount', () => {
  const guard = createLatestRequestGuard()
  const request = guard.begin()

  guard.invalidate()

  assert.equal(guard.isCurrent(request), false)
})

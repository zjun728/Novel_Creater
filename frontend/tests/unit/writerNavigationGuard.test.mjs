import test from 'node:test'
import assert from 'node:assert/strict'
import { canLeaveWriter } from '../../src/application/writer/writerNavigationGuard.js'

test('unsaved corrections can cancel navigation while failed draft persistence always blocks it', async () => {
  let prompted = 0
  const options = { canNavigate: async () => true, dirty: () => true, confirmDiscard: () => { prompted++; return false } }
  assert.equal(await canLeaveWriter(options), false)
  assert.equal(prompted, 1)
  assert.equal(await canLeaveWriter({ ...options, canNavigate: async () => false }), false)
  assert.equal(prompted, 1)
  assert.equal(await canLeaveWriter({ ...options, confirmDiscard: () => true }), true)
  assert.equal(await canLeaveWriter({ ...options, dirty: () => false }), true)
  assert.equal(prompted, 1)
})

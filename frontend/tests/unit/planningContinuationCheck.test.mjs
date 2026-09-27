import test from 'node:test'
import assert from 'node:assert/strict'
import { createPlanningContinuationCheck } from '../../src/application/planning/planningContinuationCheck.js'

test('read-only check does not replace drafts and ignores late project responses', async () => {
  let project = 'a'; let release
  const local = { title: '未保存修改' }
  const check = createPlanningContinuationCheck({ projectId: () => project,
    load: id => id === 'a' ? new Promise(resolve => { release = resolve }) : Promise.resolve({ projectId: id, status: 'ready', actions: [] }) })
  const first = check.reload(); project = 'b'; await check.reload()
  release({ projectId: 'a', status: 'ready', actions: [{ mode: 'next_block' }] }); await first
  assert.equal(check.result.value.projectId, 'b')
  assert.deepEqual(local, { title: '未保存修改' })
})

test('failed refresh never leaves executable stale actions', async () => {
  let fail = false
  const check = createPlanningContinuationCheck({ projectId: () => 'a', load: async () => {
    if (fail) throw new Error('private detail')
    return { projectId: 'a', status: 'ready', actions: [{ mode: 'next_block' }] }
  } })
  await check.reload(); fail = true; await check.reload()
  assert.equal(check.result.value, null)
  assert.ok(check.error.value)
  assert.ok(!check.error.value.includes('private detail'))
})

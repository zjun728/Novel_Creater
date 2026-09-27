import assert from 'node:assert/strict'
import test from 'node:test'
import { createTopicRevision } from '../../src/application/topics/topicRevision.js'
import { CANDIDATE_FIELDS } from '../../src/application/topics/topicContracts.js'

const payload = Object.fromEntries(CANDIDATE_FIELDS.map(key => [key, '内容']))
const version = { version: 1, payload, discussionId: 'discussion', basis: { message: { id: 'message' }, evidence: [] } }
test('manual revision pins the current head while preserving the selected historical payload and source', async () => {
  let captured
  const controller = createTopicRevision({ api: { saveCandidate: async (id, command) => { captured = { id, command }; return { candidateId: 'c', version: 4 } } }, keyFactory: () => 'key' })
  controller.begin('candidate', { id: 'c', currentVersion: 3 }, version)
  controller.draft.value.title = '修订标题'
  await controller.save()
  assert.equal(captured.command.expectedVersion, 3)
  assert.equal(captured.command.messageId, 'message')
  assert.equal(captured.command.payload.title, '修订标题')
  assert.equal(version.payload.title, '内容')
  assert.equal(controller.draft.value, null)
})
test('unknown outcome keeps edits and reuses idempotency; changed content gets a fresh key', async () => {
  const keys = []; let count = 0
  const controller = createTopicRevision({ api: { saveCandidate: async (_id, data) => { keys.push(data.idempotencyKey); throw new Error('offline') } }, keyFactory: () => String(++count) })
  controller.begin('candidate', { id: 'c', currentVersion: 1 }, version)
  controller.draft.value.title = '修改'
  await controller.save(); await controller.save()
  assert.deepEqual(keys, ['1', '1'])
  assert.equal(controller.draft.value.title, '修改')
  controller.draft.value.title = '新修改'; await controller.save()
  assert.deepEqual(keys, ['1', '1', '2'])
})
test('copy omits the existing identity and version', async () => {
  let captured
  const controller = createTopicRevision({ api: { saveCandidate: async (_id, data) => { captured = data; return { candidateId: 'copy', version: 1 } } } })
  controller.begin('candidate', { id: 'c', currentVersion: 2 }, version)
  await controller.save({ copy: true })
  assert.equal('candidateId' in captured, false)
  assert.equal('expectedVersion' in captured, false)
})
test('incomplete content never invokes a save', async () => {
  let calls = 0
  const controller = createTopicRevision({ api: { saveCandidate: () => { calls += 1 } } })
  controller.begin('candidate', { id: 'c', currentVersion: 1 }, version)
  controller.draft.value.title = ' '
  await controller.save()
  assert.equal(calls, 0)
  assert.match(controller.message.value, /补齐/)
})

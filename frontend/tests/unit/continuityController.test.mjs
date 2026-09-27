import assert from 'node:assert/strict'
import test from 'node:test'
import { authorValue, createContinuityController } from '../../src/application/continuity/continuityController.js'

const page = (projectId, kind = 'facts') => ({ projectId, kind, items: [], entity: null, revision: 0, nextOffset: null })
test('late project result cannot replace the active continuity page', async () => {
  let resolve
  const controller = createContinuityController({ api: { continuity: { records: id => id === 'old' ? new Promise(r => { resolve = r }) : Promise.resolve(page(id)) } } })
  const old = controller.load('old', { kind: 'facts' })
  await controller.load('new', { kind: 'facts' })
  resolve(page('old')); await old
  assert.equal(controller.state.value.data.projectId, 'new')
})
test('wrong entity and changed revision do not display stale facts', async () => {
  const controller = createContinuityController({ api: { continuity: { records: async () => page('p') } } })
  await controller.load('p', { kind: 'facts', entity_id: 'person' })
  assert.equal(controller.state.value.status, 'error')
  assert.equal(controller.state.value.data, null)
})
test('error copy does not echo provider or database messages', async () => {
  const controller = createContinuityController({ api: { continuity: { records: async () => { throw { code: 'snapshot_changed', message: 'SECRET' } } } } })
  await controller.load('p', { kind: 'state' })
  assert.match(controller.state.value.message, /刷新/)
  assert.doesNotMatch(controller.state.value.message, /SECRET/)
})
test('a subsequent page from a different revision is rejected', async () => {
  const controller = createContinuityController({ api: { continuity: { records: async () => page('p') } } })
  await controller.load('p', { kind: 'facts', offset: 30, revision: 3 })
  assert.equal(controller.state.value.status, 'error')
  assert.equal(controller.state.value.data, null)
})
test('author values translate progress and hide identifier properties', () => {
  assert.deepEqual(authorValue({ summary: '船已靠岸', status: 'advanced', targetId: 'uuid', targetType: 'story_block' }), ['说明：船已靠岸', '状态：已推进', '规划层级：故事块'])
})

test('history rejects a different field or entity even within the requested project', async () => {
  for (const item of [{ field: 'arc.goal', entityId: 'hero' }, { field: 'arc.trust', entityId: 'other' }]) {
    const controller = createContinuityController({ api: { continuity: { records: async () => ({ ...page('p'), entity: { id: 'hero' }, items: [item] }) } } })
    await controller.load('p', { kind: 'facts', entity_id: 'hero', field_path: 'arc.trust' })
    assert.equal(controller.state.value.status, 'error')
  }
})
test('global history cannot include entity events', async () => {
  const controller = createContinuityController({ api: { continuity: { records: async () => ({ ...page('p'), items: [{ field: 'plot.mystery', entityId: 'hero' }] }) } } })
  await controller.load('p', { kind: 'facts', global_only: true, field_path: 'plot.mystery' })
  assert.equal(controller.state.value.status, 'error')
})

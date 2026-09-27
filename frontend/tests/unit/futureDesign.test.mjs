import assert from 'node:assert/strict'
import test from 'node:test'
import { activeDesignNodes, bibleDesignSections, createFutureDesignController } from '../../src/application/continuity/futureDesign.js'

const page = (id = 'p', revision = 0) => ({ projectId: id, revision, association: 'explicit', entityId: null, linkedPlots: [], bible: { content: { protagonist: '江越计划学会信任' } }, planning: null })
test('future design preserves author text without associating names or exposing IDs', () => {
  assert.deepEqual(bibleDesignSections({ coreCast: [{ id: 'entity-secret', text: '江越的兄长' }], unknown: 'hidden' }), [{ key: 'coreCast', title: '核心人物', items: ['江越的兄长'] }])
  assert.deepEqual(activeDesignNodes([{ id: 'old', lifecycle: 'retired' }, { id: 'current', lifecycle: 'active' }]).map(item => item.id), ['current'])
})
test('revision zero confirmed design is readable and passes a pinned request', async () => {
  let args
  const controller = createFutureDesignController({ api: { continuity: { futureDesign: async (...input) => { args = input; return page() } } } })
  await controller.load('p', 0)
  assert.equal(controller.state.value.status, 'ready')
  assert.deepEqual(args.slice(0, 2), ['p', { revision: 0 }])
})
test('late future design cannot leak the previous project into the active project', async () => {
  let resolve
  const controller = createFutureDesignController({ api: { continuity: { futureDesign: id => id === 'old' ? new Promise(r => { resolve = r }) : Promise.resolve(page(id)) } } })
  const old = controller.load('old', 0)
  await controller.load('new', 0); resolve(page('old')); await old
  assert.equal(controller.state.value.data.projectId, 'new')
})
test('wrong identity, revision, invented association and malformed content are rejected', async () => {
  for (const invalid of [page('other'), page('p', 1), { ...page(), association: 'matched_by_name' }, { ...page(), bible: { content: [] } }]) {
    const controller = createFutureDesignController({ api: { continuity: { futureDesign: async () => invalid } } })
    await controller.load('p', 0)
    assert.equal(controller.state.value.status, 'error'); assert.equal(controller.state.value.data, null)
  }
})
test('clear invalidates an in-flight response and failures never echo server details', async () => {
  let reject
  const controller = createFutureDesignController({ api: { continuity: { futureDesign: () => new Promise((_, r) => { reject = r }) } } })
  const pending = controller.load('p', 0); controller.clear(); reject({ message: 'SQL secret' }); await pending
  assert.equal(controller.state.value.status, 'idle')
  const retry = controller.load('p', 0); reject({ code: 'snapshot_changed', message: 'SQL secret' }); await retry
  assert.match(controller.state.value.message, /重新读取/); assert.doesNotMatch(controller.state.value.message, /SQL/)
})

test('linked plans request explicit identity and reject a same-name different entity', async () => {
  let sent
  const controller = createFutureDesignController({ api: { continuity: { futureDesign: async (_id, filters) => {
    sent = filters
    return { ...page(), entityId: 'hero', linkedPlots: [{ lifecycle: 'active', characterDesign: { entityId: 'other', displayName: '同名人物' } }] }
  } } } })
  await controller.load('p', 0, 'hero')
  assert.deepEqual(sent, { revision: 0, entity_id: 'hero' })
  assert.equal(controller.state.value.status, 'error')
})

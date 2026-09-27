import assert from 'node:assert/strict'
import test from 'node:test'
import { api } from '../../src/api/db/client.js'

const node = { id: 'local-node', title: '决定救人', stage: '主动选择', goal: '救出兄长', belief: '', relationship: '', ability: '', expectedChapter: 4 }
async function request(plot) {
  const original = globalThis.fetch
  let sent
  globalThis.fetch = async (_url, options) => { sent = JSON.parse(options.body); return new Response('{}', { status: 200, headers: { 'content-type': 'application/json' } }) }
  try {
    await api.planning.saveDraft('p', 'd', { expectedDraftRevision: 1, expectedDraftHash: 'a'.repeat(64), idempotencyKey: 'save-character', content: { activeStoryBlockRef: null, volumes: [], plots: [plot], storyBlocks: [] } })
    return sent.content.plots[0]
  } finally { globalThis.fetch = original }
}
test('actual planning request preserves explicit binding and every node dimension', async () => {
  const design = { entityId: 'hero', displayName: '沈砚', nodes: [node] }
  const sent = await request({ title: '人物线', characterDesign: design })
  assert.deepEqual(sent.characterDesign, design)
})
test('legacy plot remains absent while explicit design removal and unbound design survive transport', async () => {
  assert.equal(Object.hasOwn(await request({ title: '旧情节' }), 'characterDesign'), false)
  assert.equal((await request({ characterDesign: null })).characterDesign, null)
  assert.equal((await request({ characterDesign: { entityId: null, displayName: '未出场人物', nodes: [] } })).characterDesign.entityId, null)
})
test('nested transport excludes unrelated properties and rejects invalid chapter number', async () => {
  const sent = await request({ characterDesign: { entityId: 'hero', displayName: '沈砚', secret: 'do-not-send', nodes: [{ ...node, internal: 'do-not-send' }] } })
  assert.doesNotMatch(JSON.stringify(sent), /do-not-send/)
  await assert.rejects(request({ characterDesign: { entityId: 'hero', displayName: '沈砚', nodes: [{ ...node, expectedChapter: 1.5 }] } }), /character node/)
})

import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import { parse, compileScript } from '@vue/compiler-sfc'
import { ref, computed, reactive } from 'vue'
import { canonicalPlanningContentForUi } from '../../src/stores/planningStore.js'

import { characterDesignIssues } from '../../src/application/planning/planningWorkspaceController.js'

const source = await readFile(new URL('../../src/components/planning/CharacterDesignEditor.vue', import.meta.url), 'utf8')
const script = compileScript(parse(source).descriptor, { id: 'character-design' }).content
  .replace(/^import .*$/gm, '').replace('export default', 'return')
const component = api => new Function('ref', 'computed', 'watch', 'onBeforeUnmount', 'api', 'characterDesignIssues', script)(ref, computed, () => {}, () => {}, api, characterDesignIssues)
function mount({ value, disabled = false, entities = async () => ({ projectId: 'p', revision: 1, items: [], nextOffset: null }) } = {}) {
  const props = reactive({ modelValue: value, disabled, projectId: 'p' }), emitted = []
  const editor = component({ continuity: { entities } }).setup(props, { expose() {}, emit(event, value) { emitted.push(value); props.modelValue = value } })
  return { props, emitted, editor }
}
const design = () => ({ entityId: null, displayName: '未出场人物', nodes: [] })
test('legacy plots retain absent characterDesign; canonical conversion preserves explicit design', () => {
  const content = { plots: [{ id: 'old', title: '旧规划' }, { id: 'new', characterDesign: design() }] }
  const result = canonicalPlanningContentForUi(content)
  assert.equal(Object.hasOwn(result.plots[0], 'characterDesign'), false)
  assert.deepEqual(result.plots[1].characterDesign, design())
  result.plots[1].characterDesign.displayName = 'changed'
  assert.equal(content.plots[1].characterDesign.displayName, '未出场人物')
})
test('explicit creation, editing, stable node ordering and removal preserve immutable inputs', () => {
  const { editor, props, emitted } = mount()
  assert.equal(emitted.length, 0)
  editor.addDesign(); editor.addNode(); editor.addNode()
  const original = props.modelValue, [first, second] = original.nodes
  editor.editNode(first.id, 'goal', '保护同伴')
  assert.equal(original.nodes[0].goal, '')
  editor.moveNode(0, 1)
  assert.deepEqual(props.modelValue.nodes.map(n => n.id), [second.id, first.id])
  assert.equal(props.modelValue.nodes[1].goal, '保护同伴')
  editor.removeNode(second.id)
  assert.equal(props.modelValue.nodes.length, 1)
})
test('readonly and busy protection rejects all mutations; node maximum is enforced', () => {
  const { editor, props, emitted } = mount({ value: { ...design(), nodes: [{ id: 'n', title: '节点' }] }, disabled: true })
  editor.addNode(); editor.editNode('n', 'title', '改写'); editor.removeNode('n'); editor.change({ entityId: 'fake' })
  assert.equal(emitted.length, 0)
  props.disabled = false; props.modelValue.nodes = Array.from({ length: 50 }, (_, i) => ({ id: String(i) }))
  editor.addNode(); assert.equal(emitted.length, 0)
})
test('search requests only people with revision pagination; names never associate automatically', async () => {
  const calls = []
  const { editor, props, emitted } = mount({ value: design(), entities: async (id, options) => { calls.push(options); return { projectId: id, revision: 4, items: [{ id: 'person-1', name: '未出场人物', type: 'person' }], nextOffset: options.offset ? null : 20 } } })
  editor.query.value = '未出场人物'; await editor.search()
  assert.equal(emitted.length, 0)
  editor.selectPerson({ id: 'unknown', name: '未出场人物' }); assert.equal(emitted.length, 0)
  editor.selectPerson(editor.people.value[0]); assert.equal(props.modelValue.entityId, 'person-1')
  await editor.search(20)
  assert.deepEqual(calls[1], { entity_type: 'person', query: '未出场人物', offset: 20, revision: 4 })
})
test('stale search responses and revision mismatch cannot offer incorrect associations', async () => {
  let resolveFirst
  const { editor } = mount({ value: design(), entities: (id, options) => options.query === 'first' ? new Promise(resolve => { resolveFirst = resolve }) : Promise.resolve({ projectId: id, revision: 2, items: [{ id: 'new', name: '新人物', type: 'person' }], nextOffset: null }) })
  editor.query.value = 'first'; const first = editor.search()
  editor.query.value = 'second'; await editor.search()
  resolveFirst({ projectId: 'p', revision: 1, items: [{ id: 'old' }], nextOffset: null }); await first
  assert.equal(editor.people.value[0].id, 'new')
  editor.revision.value = 1; await editor.search(20)
  assert.equal(editor.people.value.length, 0)
  assert.match(editor.error.value, /重新搜索/)
})

test('incomplete plans explain required details and can be removed without losing readonly protection', () => {
  const { editor, props, emitted } = mount({ value: design() })
  assert.match(editor.issues.value.join(' '), /至少添加一个变化节点/)
  editor.addNode()
  assert.match(editor.issues.value.join(' '), /至少填写阶段/)
  editor.editNode(props.modelValue.nodes[0].id, 'goal', '救助同伴')
  assert.deepEqual(editor.issues.value, [])
  props.disabled = true; const count = emitted.length; editor.removeDesign()
  assert.equal(emitted.length, count)
  props.disabled = false; editor.removeDesign(); assert.equal(props.modelValue, null)
})
test('invalid non-person results cannot be offered for association', async () => {
  for (const item of [{ id: 'x', name: '地点', type: 'place' }, { id: '', name: '人物', type: 'person' }, { id: 'x', name: '', type: 'person' }, null]) {
    const { editor, emitted } = mount({ value: design(), entities: async () => ({ projectId: 'p', revision: 1, items: [item], nextOffset: null }) })
    await editor.search(); assert.equal(editor.people.value.length, 0); assert.equal(emitted.length, 0)
    assert.match(editor.error.value, /重新搜索/)
  }
})

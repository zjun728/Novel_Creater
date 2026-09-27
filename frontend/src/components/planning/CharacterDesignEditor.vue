<script setup>
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { api } from '../../api/db/client.js'
import { characterDesignIssues } from '../../application/planning/planningWorkspaceController.js'

const props = defineProps({ modelValue: { type: Object, default: undefined }, projectId: { type: String, default: '' }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const issues = computed(() => characterDesignIssues(props.modelValue))
const dimensions = [['stage', '计划阶段'], ['goal', '目标'], ['belief', '信念'], ['relationship', '关系'], ['ability', '能力']]
const query = ref(''), people = ref([]), nextOffset = ref(null), revision = ref(null), loading = ref(false), error = ref('')
let generation = 0
let searchedQuery = ''
watch(() => props.projectId, () => { generation++; people.value = []; nextOffset.value = null; revision.value = null; query.value = ''; error.value = ''; loading.value = false })
onBeforeUnmount(() => { generation++ })
function change(patch) {
  if (!props.disabled && props.modelValue) emit('update:modelValue', { ...props.modelValue, ...patch })
}
function addDesign() {
  if (!props.disabled && !props.modelValue) emit('update:modelValue', { entityId: null, displayName: '新人物计划', nodes: [] })
}
function removeDesign() {
  if (!props.disabled && props.modelValue) emit('update:modelValue', null)
}
function addNode() {
  if (props.disabled || !props.modelValue || props.modelValue.nodes.length >= 50) return
  change({ nodes: [...props.modelValue.nodes, { id: crypto.randomUUID(), title: '新变化节点', stage: '', goal: '', belief: '', relationship: '', ability: '', expectedChapter: null }] })
}
function editNode(id, field, value) {
  change({ nodes: props.modelValue.nodes.map(node => node.id === id ? { ...node, [field]: value } : node) })
}
function moveNode(index, direction) {
  const nodes = [...props.modelValue.nodes], target = index + direction
  if (target < 0 || target >= nodes.length) return
  ;[nodes[index], nodes[target]] = [nodes[target], nodes[index]]
  change({ nodes })
}
function removeNode(id) { change({ nodes: props.modelValue.nodes.filter(node => node.id !== id) }) }
async function search(offset = 0) {
  if (!props.projectId || props.disabled) return
  const id = props.projectId, request = ++generation, expectedRevision = revision.value
  if (!offset) searchedQuery = query.value
  loading.value = true; error.value = ''
  if (!offset) { people.value = []; nextOffset.value = null; revision.value = null }
  try {
    const page = await api.continuity.entities(id, { entity_type: 'person', query: searchedQuery, offset, ...(offset ? { revision: expectedRevision } : {}) })
    if (request !== generation || id !== props.projectId) return
    if (page.projectId !== id || !Array.isArray(page.items) || page.items.some(item => !item || typeof item.id !== 'string' || !item.id.trim() || typeof item.name !== 'string' || !item.name.trim() || item.type !== 'person') || !Number.isSafeInteger(page.revision) || page.revision < 0 || (offset && page.revision !== expectedRevision) || (page.nextOffset !== null && (!Number.isSafeInteger(page.nextOffset) || page.nextOffset <= offset))) throw new Error('Invalid page')
    people.value = page.items; nextOffset.value = page.nextOffset; revision.value = page.revision
  } catch {
    if (request === generation) { people.value = []; nextOffset.value = null; error.value = '人物列表未能加载，请重新搜索。' }
  } finally { if (request === generation) loading.value = false }
}
function selectPerson(person) {
  const selected = people.value.find(item => item.id === person.id)
  if (props.disabled || !selected) return
  change({ entityId: selected.id, displayName: selected.name })
}
</script>

<template>
  <section class="character-design" aria-label="人物变化计划">
    <header><div><h3>人物变化计划</h3><p>规划人物将经历的变化；实际变化在章节定稿后回看。</p></div><button v-if="!modelValue" type="button" :disabled="disabled" @click="addDesign">添加人物计划</button><button v-else type="button" :disabled="disabled" @click="removeDesign">移除人物计划</button></header>
    <template v-if="modelValue">
      <aside v-if="issues.length" class="validation" role="status"><strong>确认前还需补充</strong><ul><li v-for="issue in issues" :key="issue">{{ issue }}</li></ul></aside>
      <fieldset :disabled="disabled">
        <label>计划人物名称<input :value="modelValue.displayName" maxlength="200" required @input="change({ displayName: $event.target.value })"></label>
        <div class="binding">
          <strong>{{ modelValue.entityId ? '已明确关联正文人物' : '尚未关联正文人物' }}</strong>
          <p>{{ modelValue.entityId ? '关联保存在本次规划中，确认后可与该人物的实际变化对照。' : '人物尚未出场时可以先规划，正文出现后再明确选择关联。' }}</p>
          <button v-if="modelValue.entityId" type="button" :disabled="disabled" @click="change({ entityId: null })">解除关联</button>
          <div class="search"><label>查找正文人物<input v-model="query" placeholder="输入姓名查找" @keydown.enter.prevent="search()"></label><button type="button" :disabled="disabled || loading || !projectId" @click="search()">{{ loading ? '查找中…' : '查找人物' }}</button></div>
          <p v-if="error" role="alert">{{ error }}</p>
          <p v-if="revision !== null && !loading && !people.length && !error">未找到正文人物。可以保留未关联计划，待人物出场后再关联。</p>
          <ul v-if="people.length"><li v-for="person in people" :key="person.id"><span>{{ person.name }}<small v-if="person.aliases?.length">（{{ person.aliases.join('、') }}）</small></span><button type="button" :disabled="disabled || loading" @click="selectPerson(person)">{{ modelValue.entityId === person.id ? '已关联' : '关联此人物' }}</button></li></ul>
          <button v-if="nextOffset !== null" type="button" :disabled="disabled || loading" @click="search(nextOffset)">下一页人物</button>
        </div>
        <article v-for="(node, index) in modelValue.nodes" :key="node.id" class="node">
          <div class="node-heading"><span>变化节点 {{ index + 1 }}</span><div><button type="button" :disabled="disabled || index === 0" @click="moveNode(index, -1)">上移节点</button><button type="button" :disabled="disabled || index === modelValue.nodes.length - 1" @click="moveNode(index, 1)">下移节点</button><button type="button" :disabled="disabled" @click="removeNode(node.id)">移除节点</button></div></div>
          <div class="node-fields"><label>节点名称<input :value="node.title" maxlength="200" required @input="editNode(node.id, 'title', $event.target.value)"></label><label>预计章节（可留空）<input type="number" min="1" step="1" :value="node.expectedChapter ?? ''" @input="editNode(node.id, 'expectedChapter', $event.target.value === '' ? null : Number($event.target.value))"></label><label v-for="[field, label] in dimensions" :key="field">{{ label }}<textarea :value="node[field]" maxlength="4000" rows="2" @input="editNode(node.id, field, $event.target.value)" /></label></div>
        </article>
        <button type="button" :disabled="disabled || modelValue.nodes.length >= 50" @click="addNode">添加变化节点</button>
      </fieldset>
    </template>
  </section>
</template>

<style scoped>
.validation{padding:12px;margin-bottom:14px;border-left:3px solid var(--nc-vermilion);background:var(--nc-canvas);color:var(--nc-muted);font-size:12px}.validation ul{margin-bottom:0}.validation li{display:block}
.character-design{margin-top:20px;padding-top:18px;border-top:2px solid var(--nc-border)}
header,.node-heading,.search,li{display:flex;align-items:center;justify-content:space-between;gap:12px}h3{margin:0;font:600 20px Georgia,'Noto Serif SC',serif}p{margin:6px 0 12px;color:var(--nc-muted);font-size:12px;line-height:1.7}
fieldset{display:grid;gap:14px;border:0;padding:0;margin:0}label{display:grid;gap:6px;color:var(--nc-muted);font-size:12px}.binding,.node{padding:14px;border:1px solid var(--nc-border);border-radius:6px;background:var(--nc-paper)}.binding strong,.node-heading{font-size:13px}.search label{flex:1}.search{align-items:end}.node-heading{margin-bottom:12px}.node-heading>div{display:flex;gap:6px}.node-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.node-fields label:last-child{grid-column:1/-1}input,textarea{width:100%;box-sizing:border-box;padding:9px 11px;border:1px solid var(--nc-border);border-radius:5px;background:var(--nc-paper);color:var(--nc-ink);font:inherit;resize:vertical}button{padding:7px 10px;border:1px solid var(--nc-border);border-radius:5px;background:var(--nc-paper);color:var(--nc-ink);cursor:pointer}button:disabled{opacity:.45;cursor:not-allowed}ul{list-style:none;margin:12px 0;padding:0}li{padding:7px 0;border-bottom:1px solid var(--nc-border)}
</style>

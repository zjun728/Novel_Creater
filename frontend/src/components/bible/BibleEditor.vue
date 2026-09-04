<script setup>
import { computed, ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: Object, default: null },
  activeSection: { type: String, default: 'premise' },
  editingSection: { type: String, default: '' },
  disabled: Boolean,
  readOnly: Boolean,
})
const emit = defineEmits(['update:modelValue', 'navigate-section', 'begin-section-edit', 'complete-section-edit'])

const sections = Object.freeze([
  { key: 'premise', label: '作品承诺', description: '说清这部作品为读者提供的核心体验与长线期待。', fields: [['premiseAndPromise', '作品承诺', 'scalar']] },
  { key: 'world_rules', label: '世界规则', description: '列出不可随意破坏的世界运行规则。', fields: [['worldRules', '世界规则', 'list']] },
  { key: 'progression', label: '力量／成长体系', description: '定义成长阶梯、代价、上限与突破条件。', fields: [['powerOrProgressionSystem', '力量／成长体系', 'scalar']] },
  { key: 'core_characters', label: '主角与核心人物', description: '定义主角驱动力、核心关系与角色分工。', fields: [['protagonist', '主角', 'scalar'], ['coreCast', '核心人物', 'list']] },
  { key: 'factions', label: '势力', description: '记录主要势力的目标、资源与对立关系。', fields: [['factions', '势力', 'list']] },
  { key: 'long_term_conflicts', label: '长期冲突', description: '建立可支撑长篇推进的核心矛盾与升级路径。', fields: [['longTermConflicts', '长期冲突', 'list']] },
  { key: 'relationships', label: '关系动力', description: '记录人物关系的张力、交换与变化方向。', fields: [['relationshipDynamics', '关系动力', 'list']] },
  { key: 'tone_boundaries', label: '基调与叙事边界', description: '统一文风、视角、情绪强度和禁区。', fields: [['toneAndNarrativeBoundaries', '基调与叙事边界', 'scalar']] },
  { key: 'continuity_guardrails', label: '连贯性护栏', description: '标明后续创作中必须维持的事实与逻辑边界。', fields: [['continuityGuardrails', '连贯性护栏', 'list']] },
  { key: 'open_questions', label: '开放设计问题', description: '收集尚未定案、需要在后续规划中回答的问题。', fields: [['openDesignQuestions', '开放设计问题', 'list']] },
])
const clone = input => input == null ? {} : JSON.parse(JSON.stringify(input))
const workCopy = ref(clone(props.modelValue))
watch(() => props.modelValue, modelValue => { workCopy.value = clone(modelValue) }, { deep: true })
const value = computed(() => workCopy.value)

function update(field, next) {
  workCopy.value = { ...value.value, [field]: next }
  emit('update:modelValue', clone(workCopy.value))
}
function updateItem(field, index, text) {
  const rows = [...(value.value[field] || [])]
  rows[index] = { ...rows[index], text }
  update(field, rows)
}
function addItem(field) {
  const rows = [...(value.value[field] || [])]
  const used = new Set(rows.map(row => row?.id))
  let number = 1
  while (used.has(`design-${field}-${number}`)) number += 1
  update(field, [...rows, { id: `design-${field}-${number}`, text: '' }])
}
function removeItem(field, index) { update(field, (value.value[field] || []).filter((_, row) => row !== index)) }
function hasContent(section) {
  return section.fields.some(([field, , type]) => type === 'list'
    ? (value.value[field] || []).some(item => String(item?.text || '').trim())
    : Boolean(String(value.value[field] || '').trim()))
}
function readableItems(field) {
  return (value.value[field] || []).filter(item => String(item?.text || '').trim())
}
function finishSection() { emit('complete-section-edit', clone(value.value)) }
</script>

<template>
  <article class="bible-editor" aria-label="创作圣经完整文档">
    <section
      v-for="(section, index) in sections"
      :id="`bible-section-${section.key}`"
      :key="section.key"
      class="bible-section"
      :class="{ 'bible-section--active': section.key === activeSection }"
      tabindex="-1"
      @click="emit('navigate-section', section.key)"
    >
      <header class="bible-section__header">
        <p>{{ String(index + 1).padStart(2, '0') }}</p>
        <div><h2>{{ section.label }}</h2><p>{{ section.description }}</p></div>
        <span>{{ hasContent(section) ? '已填写' : '待补充' }}</span>
      </header>

      <div v-for="[field, label, type] in section.fields" :key="field" class="bible-field">
        <h3 v-if="section.fields.length > 1">{{ label }}</h3>
        <template v-if="readOnly">
          <p v-if="type === 'scalar' && value[field]" class="bible-field__text">{{ value[field] }}</p>
          <ol v-else-if="type === 'list' && readableItems(field).length" class="bible-field__list"><li v-for="item in readableItems(field)" :key="item.id">{{ item.text }}</li></ol>
          <p v-else class="bible-field__empty">尚未填写</p>
        </template>
        <template v-else-if="editingSection === section.key">
          <textarea v-if="type === 'scalar'" :value="value[field] || ''" :disabled="disabled" :aria-label="label" @input="update(field, $event.target.value)" />
          <template v-else>
            <label v-for="(item, itemIndex) in value[field] || []" :key="item.id" class="bible-list-row">
              <span>{{ item.id }}</span>
              <textarea :value="item.text" :disabled="disabled" @input="updateItem(field, itemIndex, $event.target.value)" />
              <button type="button" :disabled="disabled" @click.stop="removeItem(field, itemIndex)">删除</button>
            </label>
            <button type="button" :disabled="disabled" @click.stop="addItem(field)">新增{{ label }}</button>
          </template>
        </template>
        <template v-else>
          <p v-if="type === 'scalar' && value[field]" class="bible-field__text">{{ value[field] }}</p>
          <ol v-else-if="type === 'list' && (value[field] || []).length" class="bible-field__list"><li v-for="item in value[field]" :key="item.id">{{ item.text }}</li></ol>
          <p v-else class="bible-field__empty">尚未填写。{{ section.description }}</p>
        </template>
      </div>

      <footer v-if="!readOnly && section.key === activeSection" class="bible-section__actions">
        <button v-if="editingSection !== section.key" type="button" :disabled="disabled" @click.stop="emit('begin-section-edit', section.key)">编辑本区</button>
        <button v-else type="button" :disabled="disabled" @click.stop="finishSection">完成本区编辑</button>
      </footer>
    </section>
  </article>
</template>

<style scoped>
.bible-editor { display:grid; min-width:0; }
.bible-section { min-width:0; padding:clamp(22px,4vw,38px); border-bottom:1px solid var(--nc-border); scroll-margin-top:22px; }
.bible-section:last-child { border-bottom:0; }
.bible-section--active { box-shadow:inset 3px 0 var(--nc-vermilion); }
.bible-section:focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:-4px; }
.bible-section__header { display:grid; grid-template-columns:auto minmax(0,1fr) auto; gap:14px; align-items:start; margin-bottom:18px; }
.bible-section__header > p { margin:3px 0 0; color:var(--nc-vermilion); font:700 11px Georgia,serif; letter-spacing:.14em; }
.bible-section__header h2 { margin:0; font:600 clamp(22px,3vw,30px)/1.25 Georgia,'Noto Serif SC',serif; }
.bible-section__header div p { margin:7px 0 0; color:var(--nc-muted); font-size:13px; line-height:1.65; }
.bible-section__header > span { color:var(--nc-muted); font-size:11px; white-space:nowrap; }
.bible-field { display:grid; min-width:0; gap:8px; margin-top:14px; }
.bible-field h3 { margin:0; color:var(--nc-vermilion); font:700 11px Georgia,'Noto Serif SC',serif; letter-spacing:.12em; }
.bible-field textarea { min-height:94px; resize:vertical; border:1px solid var(--nc-border); border-radius:2px; padding:12px; color:var(--nc-ink); background:var(--nc-paper); font:15px/1.72 Georgia,'Noto Serif SC',serif; }
.bible-field textarea:disabled { color:var(--nc-muted); background:color-mix(in srgb,var(--nc-paper) 88%,var(--nc-canvas)); }
.bible-field__text,.bible-field__list { margin:0; color:var(--nc-ink); font:15px/1.8 Georgia,'Noto Serif SC',serif; white-space:pre-wrap; }
.bible-field__list { display:grid; gap:7px; padding-left:1.3rem; }
.bible-field__empty { margin:0; padding:12px; color:var(--nc-muted); border-left:2px solid var(--nc-border); font-size:13px; line-height:1.7; }
.bible-list-row { display:grid; grid-template-columns:minmax(82px,.28fr) minmax(0,1fr) auto; gap:8px; align-items:start; }
.bible-list-row > span { padding-top:12px; color:var(--nc-muted); font-size:11px; overflow-wrap:anywhere; }
.bible-editor button { min-height:38px; border:1px solid var(--nc-border); padding:7px 12px; color:var(--nc-ink); background:var(--nc-paper); font:600 13px Georgia,'Noto Serif SC',serif; cursor:pointer; }
.bible-editor button:focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:2px; }
.bible-section__actions { display:flex; justify-content:flex-end; margin-top:18px; }
@media (max-width:620px) { .bible-section { padding:20px 16px; } .bible-section__header { grid-template-columns:auto minmax(0,1fr); } .bible-section__header > span { grid-column:2; } .bible-list-row { grid-template-columns:1fr; } }
</style>

<script setup>
import { computed } from 'vue'

const props = defineProps({ modelValue: { type: Object, default: null }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])

const scalarFields = [
  ['premiseAndPromise', '作品承诺'], ['powerOrProgressionSystem', '力量／成长体系'],
  ['protagonist', '主角'], ['toneAndNarrativeBoundaries', '叙事语气与边界'],
]
const arrayFields = [
  ['worldRules', '世界规则'], ['coreCast', '核心人物'], ['factions', '势力'],
  ['longTermConflicts', '长期冲突'], ['relationshipDynamics', '关系动力'],
  ['continuityGuardrails', '连续性护栏'], ['openDesignQuestions', '开放设计问题'],
]
const value = computed(() => props.modelValue || {})
let nextItemId = 0
function update(field, next) { emit('update:modelValue', { ...value.value, [field]: next }) }
function updateItem(field, index, text) {
  const rows = [...(value.value[field] || [])]
  rows[index] = { ...rows[index], text }
  update(field, rows)
}
function addItem(field) {
  const rows = [...(value.value[field] || [])]
  nextItemId += 1
  update(field, [...rows, { id: `design-${nextItemId}`, text: '' }])
}
function removeItem(field, index) { update(field, (value.value[field] || []).filter((_, row) => row !== index)) }
</script>

<template>
  <section class="bible-editor" aria-label="创作圣经编辑器">
    <label v-for="[key, label] in scalarFields" :key="key" class="paper-field">
      <span>{{ label }}</span>
      <textarea :value="value[key] || ''" :disabled="disabled" @input="update(key, $event.target.value)" />
    </label>
    <section v-for="[key, label] in arrayFields" :key="key" class="paper-list">
      <h2>{{ label }}</h2>
      <label v-for="(item, index) in value[key] || []" :key="item.id" class="paper-field">
        <span>{{ item.id }}</span>
        <textarea :value="item.text" :disabled="disabled" @input="updateItem(key, index, $event.target.value)" />
        <button type="button" :disabled="disabled" @click="removeItem(key, index)">删除</button>
      </label>
      <button type="button" :disabled="disabled" @click="addItem(key)">新增{{ label }}</button>
    </section>
  </section>
</template>

<style scoped>
.bible-editor { display:grid; gap:18px; }
.paper-field,.paper-list { display:grid; gap:7px; }
.paper-field > span,.paper-list h2 { color:#8b3028; font:700 11px Georgia,'Noto Serif SC',serif; letter-spacing:.12em; }
.paper-list h2 { margin:7px 0 0; font-size:13px; }
textarea { min-height:78px; resize:vertical; border:1px solid #cdbda5; border-radius:4px; padding:11px; color:#32291f; background:#fffcf5; font:15px/1.65 Georgia,'Noto Serif SC',serif; }
textarea:disabled { color:#70655a; background:#f4eee2; }
</style>

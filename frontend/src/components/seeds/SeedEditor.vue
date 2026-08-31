<script setup>
import { NButton, NInput } from 'naive-ui'
import { limitUnicodeScalarText, unicodeScalarLength } from '@/utils/unicodeScalarText.js'

const props = defineProps({ modelValue: { type: Object, required: true }, section: { type: Object, required: true }, busy: { type: Boolean, default: false }, readOnly: { type: Boolean, default: false } })
const emit = defineEmits(['update:modelValue', 'complete', 'cancel'])
const allFields = Object.freeze(['title', 'genre', 'logline', 'protagonist', 'desire', 'coreConflict', 'worldPressure', 'openingHook', 'differentiation', 'targetAudience', 'storyPromise', 'longFormPotential', 'marketBasis'])
const maxInputCodeUnits = 4000
function update(key, value) { try { const bounded = limitUnicodeScalarText(String(value ?? ''), 2000).value; emit('update:modelValue', Object.fromEntries(allFields.map(field => [field, field === key ? bounded : String(props.modelValue?.[field] || '')]))) } catch {} }
function scalarCount(value) { try { return unicodeScalarLength(String(value ?? '')) } catch { return 0 } }
function complete() { emit('complete') }
</script>

<template>
  <form class="seed-editor" @submit.prevent="complete">
    <p>正在校订「{{ section.title }}」。完成本区编辑仅更新本地工作副本。</p>
    <label v-for="[key, label] in section.fields" :key="key"><strong>{{ label }}</strong><n-input :value="modelValue[key] || ''" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" :maxlength="maxInputCodeUnits" :show-count="false" :disabled="busy || readOnly" :placeholder="['targetAudience','storyPromise','longFormPotential','marketBasis'].includes(key) ? '建议补充' : ''" @update:value="update(key, $event)" /><output class="seed-editor__count" aria-live="polite">{{ unicodeScalarLength(String(modelValue[key] || '')) }} / 2000</output></label>
    <footer><n-button :disabled="busy" @click.prevent="emit('cancel')">取消</n-button><n-button type="primary" attr-type="submit" :disabled="busy || readOnly">完成本区编辑</n-button></footer>
  </form>
</template>

<style scoped>.seed-editor{display:grid;gap:13px}.seed-editor>p{margin:0;color:var(--nc-muted);font:12px/1.65 Georgia,'Noto Serif SC',serif}.seed-editor label{display:grid;gap:6px}.seed-editor strong{color:var(--nc-vermilion);font:700 12px Georgia,'Noto Serif SC',serif}.seed-editor__count{justify-self:end;color:var(--nc-muted);font-size:11px}.seed-editor footer{display:flex;justify-content:flex-end;gap:8px}</style>

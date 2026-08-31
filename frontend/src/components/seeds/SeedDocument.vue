<script setup>
import { computed } from 'vue'
import { NButton } from 'naive-ui'

import FoundationDocumentSection from '@/components/foundation/FoundationDocumentSection.vue'
import { presentSeedProvenance } from './seedProvenancePresenter.js'

const props = defineProps({ seed: { type: Object, required: true }, payload: { type: Object, default: null }, activeSection: { type: String, default: '' }, readOnly: { type: Boolean, default: false } })
const emit = defineEmits(['edit-section'])

const sections = Object.freeze([
  { key: 'positioning', title: '作品定位', eyebrow: 'POSITIONING', fields: [['title', '标题'], ['genre', '题材'], ['targetAudience', '目标读者']] },
  { key: 'core', title: '故事核心', eyebrow: 'CORE', fields: [['logline', '一句话故事'], ['protagonist', '主角'], ['desire', '核心欲望'], ['coreConflict', '核心冲突']] },
  { key: 'pressure', title: '开篇与压力', eyebrow: 'PRESSURE', fields: [['worldPressure', '世界压力'], ['openingHook', '开篇钩子']] },
  { key: 'promise', title: '差异与承诺', eyebrow: 'PROMISE', fields: [['differentiation', '差异化'], ['storyPromise', '故事承诺'], ['longFormPotential', '长篇潜力'], ['marketBasis', '市场依据']] },
])
const optionalFields = new Set(['targetAudience', 'storyPromise', 'longFormPotential', 'marketBasis'])
const documentPayload = computed(() => props.payload || props.seed.payload || {})
const canEdit = computed(() => !props.readOnly && props.seed.status === 'candidate' && props.seed.capabilities?.canEdit === true)
const source = computed(() => presentSeedProvenance(props.seed.provenance))

function valueFor(key) {
  const value = documentPayload.value[key]
  if (String(value || '').trim()) return value
  if (props.readOnly && optionalFields.has(key) && !props.seed.recordedFields?.includes(key)) return '该历史版本未记录'
  return '建议补充'
}

</script>

<template>
  <article class="seed-document" aria-label="项目种子完整文档">
    <header class="seed-document__title"><p>SEED / AUTHOR DOCUMENT</p><h2 id="seed-document-heading" tabindex="-1">{{ documentPayload.title || '未命名项目种子' }}</h2><span v-if="seed.isSelected">当前选定 · 已冻结</span><span v-else-if="readOnly">只读修订</span><span v-else>候选修订 · 可校订</span></header>
    <FoundationDocumentSection v-for="section in sections" :key="section.key" :target-id="`seed-${section.key}`" :title="section.title" :eyebrow="section.eyebrow" :read-only="!canEdit || activeSection !== section.key" :class="{ 'seed-document__section--editing': activeSection === section.key }">
      <template #read><div class="seed-document__section-read"><n-button v-if="canEdit && activeSection !== section.key" size="small" @click="emit('edit-section', section.key)">编辑本区</n-button><dl><div v-for="[key, label] in section.fields" :key="key"><dt>{{ label }}</dt><dd :class="{ 'seed-document__suggestion': !documentPayload[key] }">{{ valueFor(key) }}</dd></div></dl></div></template>
      <template #edit><slot name="editor" :section="section" /></template>
    </FoundationDocumentSection>
    <section class="seed-document__source"><p>来源与诊断</p><span>{{ source.label }}</span><small>种子修订：{{ seed.revision }}</small><small v-for="item in source.basis" :key="item">{{ item }}</small><small v-for="note in (seed.provenance?.publicNotes || [])" :key="note">{{ note }}</small></section>
  </article>
</template>

<style scoped>
.seed-document{color:var(--nc-ink);font-family:Georgia,'Noto Serif SC',serif}.seed-document__title{padding:clamp(24px,5vw,46px);border-bottom:2px solid var(--nc-vermilion)}.seed-document__title p,.seed-document__source p{margin:0;color:var(--nc-vermilion);font:700 10px Georgia,'Noto Serif SC',serif;letter-spacing:.17em}.seed-document__title h2{margin:8px 0;font-size:clamp(30px,5vw,48px);font-weight:600}.seed-document__title span{color:var(--nc-muted);font-size:13px}.seed-document :deep(.foundation-document-section){border-bottom:1px solid var(--nc-border)}.seed-document :deep(.foundation-document-section+.foundation-document-section){border-top:0}.seed-document__section-read>button{float:right;margin:0 0 12px 18px}.seed-document dl{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:18px 28px;margin:0}.seed-document dl>div{min-width:0}.seed-document dt{margin-bottom:5px;color:var(--nc-vermilion);font:700 12px/1.5 Georgia,'Noto Serif SC',serif}.seed-document dd{margin:0;white-space:pre-line;font:15px/1.8 Georgia,'Noto Serif SC',serif}.seed-document__suggestion{color:var(--nc-muted);font-style:italic}.seed-document__source{display:grid;gap:7px;padding:26px clamp(22px,4vw,42px);background:color-mix(in srgb,var(--nc-paper) 78%,var(--nc-canvas))}.seed-document__source span{font-size:13px}.seed-document__source small{color:var(--nc-muted);font:12px/1.65 Georgia,'Noto Serif SC',serif}@media(max-width:620px){.seed-document dl{grid-template-columns:1fr}.seed-document__section-read>button{float:none;margin:0 0 14px}}
</style>

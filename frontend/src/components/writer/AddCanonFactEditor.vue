<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { authorFactEvidenceRange, buildAuthorCanonFact, candidateSourceParagraphs } from '../../application/writer/addCanonFact.js'

const props = defineProps({
  candidateContent: { type: String, required: true },
  chapterNumber: { type: Number, required: true },
  entities: { type: Array, default: () => [] },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['add', 'dirty-change'])
const entityId = ref('')
const factKind = ref('dynamic_event')
const fieldPath = ref('author.observation')
const value = ref('')
const startId = ref('')
const endId = ref('')
const pending = ref(false)
const error = ref('')
let generation = 0
const paragraphs = computed(() => {
  try { return candidateSourceParagraphs(props.candidateContent) } catch { return [] }
})
const preview = computed(() => {
  try { return authorFactEvidenceRange(props.candidateContent, startId.value, endId.value).excerpt } catch { return '' }
})
const blocked = computed(() => props.disabled || pending.value || !paragraphs.value.length
  || !Number.isSafeInteger(props.chapterNumber) || props.chapterNumber < 1)
const dirty = computed(() => Boolean(value.value || entityId.value || fieldPath.value !== 'author.observation'
  || factKind.value !== 'dynamic_event' || startId.value !== (paragraphs.value[0]?.id || '')
  || endId.value !== (paragraphs.value[0]?.id || '')))
watch(dirty, flag => emit('dirty-change', flag), { immediate: true, flush: 'sync' })
function reset() {
  entityId.value = ''; factKind.value = 'dynamic_event'; fieldPath.value = 'author.observation'; value.value = ''
  startId.value = paragraphs.value[0]?.id || ''; endId.value = startId.value; error.value = ''
}
watch(() => JSON.stringify([props.candidateContent, props.chapterNumber, props.entities.map(item => item.id)]), () => {
  generation += 1
  reset()
}, { immediate: true, flush: 'sync' })
onBeforeUnmount(() => { generation += 1; emit('dirty-change', false) })
async function addFact() {
  if (blocked.value) return
  const token = generation
  pending.value = true; error.value = ''
  try {
    const item = await buildAuthorCanonFact({
      candidateContent: props.candidateContent, chapterNumber: props.chapterNumber, entities: props.entities,
      entityId: entityId.value || null, factKind: factKind.value, fieldPath: fieldPath.value,
      value: value.value, startId: startId.value, endId: endId.value,
    })
    if (token !== generation || props.disabled) return
    emit('add', item)
    reset()
  } catch {
    if (token === generation) error.value = '请填写事实内容，并选择有效、正向的原文段落范围。'
  } finally { pending.value = false }
}
function paragraphLabel(paragraph) {
  return `${paragraph.id} · ${Array.from(paragraph.text).slice(0, 48).join('')}${Array.from(paragraph.text).length > 48 ? '…' : ''}`
}
</script>

<template>
  <section class="author-fact" aria-label="作者补录事实">
    <h4>补录正文事实</h4>
    <p class="author-fact__hint">对照候选原文补充遗漏信息。添加后，使用“保存修正”一并保存。</p>
    <fieldset :disabled="blocked">
      <div class="author-fact__row">
        <label>关联实体<select v-model="entityId" aria-label="补录事实关联实体"><option value="">不关联特定实体</option><option v-for="entity in entities" :key="entity.id" :value="entity.id">{{ entity.canonicalName || entity.name || entity.label || entity.id }}</option></select></label>
        <label>事实类型<select v-model="factKind" aria-label="补录事实类型"><option value="dynamic_event">已发生的事件</option><option value="claim">人物说法或推测</option><option value="stable_definition">稳定设定</option></select></label>
      </div>
      <label>事实名称（记录字段）<input v-model="fieldPath" aria-label="补录事实名称" maxlength="200" /></label>
      <label>具体事实<textarea v-model="value" aria-label="补录事实内容" rows="3" maxlength="4000" placeholder="只记录所选原文能够支持的事实。" /></label>
      <div class="author-fact__row">
        <label>原文起始段落<select v-model="startId" aria-label="补录事实起始段落"><option v-for="paragraph in paragraphs" :key="paragraph.id" :value="paragraph.id">{{ paragraphLabel(paragraph) }}</option></select></label>
        <label>原文结束段落<select v-model="endId" aria-label="补录事实结束段落"><option v-for="paragraph in paragraphs" :key="paragraph.id" :value="paragraph.id">{{ paragraphLabel(paragraph) }}</option></select></label>
      </div>
      <div class="author-fact__evidence" aria-label="补录事实原文预览"><strong>原文证据</strong><pre v-if="preview">{{ preview }}</pre><p v-else>请选择从前到后的原文段落。</p></div>
      <p v-if="error" role="alert">{{ error }}</p>
      <button type="button" :disabled="blocked || !preview || !value.trim() || !fieldPath.trim()" @click="addFact">{{ pending ? '正在添加…' : '添加事实' }}</button>
    </fieldset>
  </section>
</template>

<style scoped>
.author-fact{margin:18px 0;padding:18px;border:1px solid var(--nc-border,#d8d0c2);background:var(--nc-paper,#faf8f2);color:var(--nc-ink,#3e362d)}
.author-fact h4{margin:0 0 6px;font-size:15px}.author-fact__hint{font-size:12px;line-height:1.7;color:var(--nc-muted,#756b5e);margin:0 0 14px}
.author-fact fieldset{border:0;padding:0;margin:0;min-width:0}.author-fact label{display:grid;gap:6px;min-width:0;font-size:12px;font-weight:600;margin-bottom:12px}.author-fact__row{display:grid;grid-template-columns:1fr 1fr;gap:14px}
.author-fact input,.author-fact select,.author-fact textarea{box-sizing:border-box;width:100%;min-width:0;padding:8px;border:1px solid var(--nc-border,#d8d0c2);background:var(--nc-paper,#fff);color:inherit;font:inherit}.author-fact textarea{resize:vertical}.author-fact__evidence{padding:12px;margin-bottom:12px;background:var(--nc-canvas,#f1ede4);font-size:12px}.author-fact__evidence pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:220px;overflow:auto;font:inherit;line-height:1.8;margin:8px 0 0}
.author-fact button{padding:8px 14px;border:1px solid var(--nc-vermilion,#994833);background:transparent;color:var(--nc-vermilion,#994833);font:inherit;cursor:pointer}.author-fact :disabled{cursor:default;opacity:.6}.author-fact :is(input,select,textarea,button):focus-visible{outline:2px solid var(--nc-vermilion,#994833);outline-offset:2px}.author-fact [role=alert]{font-size:12px;color:#913e30}@media(max-width:700px){.author-fact__row{grid-template-columns:1fr;gap:0}}
</style>

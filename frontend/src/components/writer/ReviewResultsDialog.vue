<script setup>
import { computed } from 'vue'
import { NButton, NModal } from 'naive-ui'
import { evidenceExcerpt } from '../../application/writer/finalizationEvidence.js'
import ReviewDisputePanel from './ReviewDisputePanel.vue'
import { latestDispute } from '../../utils/reviewReference.js'

const props = defineProps({
  show: Boolean,
  chapterNumber: { type: Number, default: 0 },
  title: { type: String, default: '' },
  report: { type: Object, default: null },
  blocks: { type: Array, default: () => [] },
  content: { type: String, default: '' },
  disabled: Boolean,
  stale: Boolean,
  canAdjust: Boolean,
  canCheckChanges: Boolean,
  canDecide: Boolean,
  decisions: { type: Object, default: () => ({ revision: 0, ignoredFindingIds: [] }) },
  error: { type: String, default: '' },
  loadEvidence: Function,
  saveDispute: Function,
})
const emit = defineEmits(['update:show', 'locate', 'adjust', 'check-changes', 'decide', 'reload'])
const dimensions = {
  plot_effectiveness: '情节有效性', content_richness: '内容丰富度', character_vitality: '人物表现',
  dialogue_credibility: '对白可信度', emotional_naturalness: '情感自然度', continuity: '连续性',
  pacing: '叙事节奏', style_stability: '风格稳定性', ai_flavor: '表达自然度', reading_motivation: '阅读吸引力',
}
const findings = computed(() => props.report?.findings || [])
const ignored = item => (props.decisions?.ignoredFindingIds || []).includes(item.id)
const severityLabel = item => ({ required: '必须调整', suggested: '建议调整', optional: '可忽略' })[item.severity] || '建议调整（旧报告未分级）'
const retained = item => latestDispute(props.decisions, item.id)?.action === 'retain'
const requiredCount = computed(() => props.blocks.length + findings.value.filter(item => item.severity === 'required' && !retained(item)).length)
const suggestedCount = computed(() => findings.value.filter(item => !item.severity || item.severity === 'suggested').length)
const optionalCount = computed(() => findings.value.filter(item => item.severity === 'optional' && !ignored(item)).length)
const ignoredCount = computed(() => findings.value.filter(ignored).length)
const groups = computed(() => {
  const result = new Map()
  for (const item of findings.value) {
    const key = item.dimension || 'other'
    if (!result.has(key)) result.set(key, { key, label: dimensions[key] || '其他建议', items: [] })
    result.get(key).items.push(item)
  }
  return [...result.values()]
})
function excerpt(item) { return evidenceExcerpt(props.content, item.evidence) }
function preview(item) {
  const text = Array.from(excerpt(item) || '')
  return text.length > 160 ? `${text.slice(0, 160).join('')}…` : text.join('')
}
function act(event, item) {
  if (props.disabled || props.stale) return
  if (event === 'adjust' && !props.canAdjust) return
  if (event === 'check-changes' && (!props.canCheckChanges || requiredCount.value)) return
  emit('update:show', false)
  emit(event, item)
}
</script>

<template>
  <n-modal :show="show" @update:show="emit('update:show', $event)">
    <section class="review-dialog" role="dialog" aria-modal="true" aria-labelledby="review-results-title">
      <header>
        <h2 id="review-results-title">第 {{ chapterNumber }} 章 · {{ title || '本章审查结果' }}</h2>
        <p class="review-counts">必须调整 {{ requiredCount }} 项 · 建议调整 {{ suggestedCount }} 项 · 可忽略 {{ optionalCount }} 项<span v-if="ignoredCount"> · 已忽略 {{ ignoredCount }} 项</span></p>
      </header>
      <div class="review-dialog-body">
        <div v-if="error" class="review-notice" role="alert">{{ error }} <n-button size="small" :disabled="disabled" @click="emit('reload')">重新读取审稿</n-button></div>
        <p v-if="stale" class="review-notice" role="status">正文或审稿依据已变化，本次结果仅供回看。请重新审稿。</p>
        <section v-if="blocks.length" aria-label="必须处理">
          <h3>必须处理</h3>
          <article v-for="item in blocks" :key="item.code" class="review-result review-result--block">
            <h4>{{ item.message }}</h4>
            <p v-if="excerpt(item)">原文：“{{ preview(item) }}”</p>
            <details v-if="Array.from(excerpt(item) || '').length > 160"><summary>展开完整原文</summary><p>{{ excerpt(item) }}</p></details>
          </article>
        </section>
        <p v-if="report?.status !== 'completed'" class="review-notice" role="status">质量审查未完成，不能将空列表理解为审查通过。</p>
        <section v-for="group in groups" :key="group.key" :aria-label="group.label">
          <h3>{{ group.label }} · {{ group.items.length }} 项</h3>
          <article v-for="item in group.items" :key="item.id" class="review-result" :class="{ 'review-result--block': item.severity === 'required', 'review-result--ignored': ignored(item) }">
            <h4>{{ retained(item) ? '作者保留原稿（原意见：必须调整）' : ignored(item) ? '已忽略' : severityLabel(item) }} · {{ item.reason }}</h4>
            <p v-if="excerpt(item)">原文：“{{ preview(item) }}”</p>
            <p v-else class="review-notice">原文片段不可用，请重新核对候选稿。</p>
            <details v-if="Array.from(excerpt(item) || '').length > 160"><summary>展开完整原文</summary><p>{{ excerpt(item) }}</p></details>
            <p>{{ item.suggestedAction }}</p>
            <n-button size="small" :disabled="disabled || stale || !item.evidence || !excerpt(item)" @click="act('locate', item)">定位原文并修改</n-button>
            <n-button v-if="item.severity === 'optional'" size="small" :disabled="disabled || stale || !canDecide" @click="emit('decide', item.id, !ignored(item))">{{ ignored(item) ? '恢复采用' : '忽略此建议' }}</n-button>
            <ReviewDisputePanel v-if="loadEvidence && saveDispute" :key="item.id" :finding="item" :decisions="decisions" :disabled="disabled || stale || !canDecide" :load-evidence="loadEvidence" :save-dispute="saveDispute" />
          </article>
        </section>
        <p v-if="report?.status === 'completed' && !findings.length && !blocks.length">没有发现审查问题；定稿前仍需核对本章事实和进度变更。</p>
      </div>
      <footer>
        <p class="review-notice">确定性问题必须修复。模型必须调整意见可修改后重审，或逐条记录依据并由作者确认保留原稿；修改正文后需重新审稿。</p>
        <div class="review-dialog-actions">
          <n-button @click="emit('update:show', false)">关闭</n-button>
          <n-button color="#934735" :disabled="disabled || stale || !canAdjust" @click="act('adjust')">基于审稿意见调整</n-button>
          <n-button :disabled="disabled || stale || !canCheckChanges || !!requiredCount" @click="act('check-changes')">核对定稿变更</n-button>
        </div>
      </footer>
    </section>
  </n-modal>
</template>

<style scoped>
.review-dialog { box-sizing: border-box; display: flex; flex-direction: column; width: min(860px, calc(100vw - 32px)); height: min(680px, calc(100dvh - 48px)); padding: 24px 28px; border-radius: 6px; background: #fffefa; color: #302d28; }
header, footer { flex: none; }
h2 { margin: 0; font-size: 25px; line-height: 1.65; font-weight: 500; overflow-wrap: anywhere; }
.review-counts { margin: 10px 0 20px; color: #934735; font-size: 15px; }
.review-dialog-body { flex: 1; min-height: 0; overflow: auto; overscroll-behavior: contain; }
h3 { margin: 0 0 8px; font-size: 14px; color: #6f685e; }
.review-result { margin-bottom: 12px; padding: 14px 16px; border-radius: 6px; background: #f5f2eb; overflow-wrap: anywhere; }
h4 { margin: 0 0 10px; font-size: 16px; font-weight: 500; }
.review-result--block h4 { color: #934735; }
.review-result--ignored { border: 1px dashed #b6ada1; color: #6f685e; }
.review-result p { margin: 6px 0; font-size: 14px; line-height: 1.65; white-space: pre-wrap; }
summary { cursor: pointer; color: #6f685e; font-size: 13px; margin: 8px 0; }
.review-notice { color: #6f685e; font-size: 13px; line-height: 1.65; }
.review-dialog-actions { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 18px; }
.review-dialog-actions :deep(button) { min-height: 40px; }
@media (max-width: 600px) { .review-dialog { padding: 18px; } h2 { font-size: 20px; } .review-dialog-actions { gap: 8px; margin-top: 8px; } }
</style>

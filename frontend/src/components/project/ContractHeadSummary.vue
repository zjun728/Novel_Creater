<script setup>
import { computed } from 'vue'
import { NAlert, NDescriptions, NDescriptionsItem, NTag } from 'naive-ui'

const props = defineProps({
  head: { type: Object, required: true },
})
const source = computed(() => props.head)

function shortHash(value) {
  const text = String(value || '')
  return text ? `${text.slice(0, 12)}…` : '—'
}

</script>

<template>
  <article class="head-summary">
    <div class="seal-column" aria-hidden="true"><span>契</span><span>约</span><small>REV {{ source.revision }}</small></div>
    <div class="summary-main">
      <header>
        <div><p>IMMUTABLE CONTRACT HEAD</p><h3>已确认，作为项目永久基线</h3></div>
        <n-tag :type="source.contractReady ? 'success' : 'warning'" round>
          {{ source.contractReady ? '冻结完整' : '需要复核' }}
        </n-tag>
      </header>

      <n-alert v-if="source.reasons?.length" type="warning" title="当前契约未就绪">
        {{ source.reasons.join('、') }}
      </n-alert>

      <n-descriptions :column="2" bordered label-placement="left" size="small" class="facts">
        <n-descriptions-item label="正式修订">R{{ source.revision }}</n-descriptions-item>
        <n-descriptions-item label="当前状态">等待滚动规划</n-descriptions-item>
        <n-descriptions-item label="种子修订">{{ source.seedRef?.revisionId || '—' }}</n-descriptions-item>
        <n-descriptions-item label="种子摘要">{{ shortHash(source.seedRef?.contentHash) }}</n-descriptions-item>
        <n-descriptions-item label="发动机批次">{{ source.engineRef?.batchId || '—' }}</n-descriptions-item>
        <n-descriptions-item label="发动机摘要">{{ shortHash(source.engineRef?.contentHash) }}</n-descriptions-item>
        <n-descriptions-item label="模型绑定">R{{ source.bindingRef?.revision ?? '—' }}</n-descriptions-item>
        <n-descriptions-item label="绑定摘要">{{ shortHash(source.bindingRef?.contentHash) }}</n-descriptions-item>
        <n-descriptions-item label="风格模板">{{ source.styleRefs?.length || 0 }} 套</n-descriptions-item>
        <n-descriptions-item label="经验卡 / 语料">{{ source.experienceCardRefs?.length || 0 }} / {{ source.corpusSourceRefs?.length || 0 }}</n-descriptions-item>
      </n-descriptions>

      <footer>
        <div><strong>签印后的修订不可覆盖</strong><p>这份契约永久保留，可通过修订历史查阅。</p></div>
      </footer>
    </div>
  </article>
</template>

<style scoped>
.head-summary { display: grid; grid-template-columns: 92px 1fr; min-height: 360px; }
.seal-column { display: flex; align-items: center; flex-direction: column; padding: 30px 12px; color: #fff8eb; background: #923a2e; }
.seal-column > span { font-family: 'Noto Serif SC', serif; font-size: 29px; line-height: 1.15; }
.seal-column small { margin-top: auto; font: 700 9px Georgia, serif; letter-spacing: .12em; writing-mode: vertical-rl; }
.summary-main { padding: 30px; }
.summary-main header, .summary-main footer { display: flex; align-items: center; justify-content: space-between; gap: 24px; }
.summary-main header p { margin: 0; color: #9c3d2f; font: 700 10px Georgia, serif; letter-spacing: .14em; }
.summary-main h3 { margin: 5px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 26px; }
.facts { margin-top: 24px; }
.summary-main footer { align-items: flex-end; margin-top: 26px; padding-top: 22px; border-top: 1px solid #d9ccb7; }
.summary-main footer strong { font-family: 'Noto Serif SC', serif; font-size: 14px; }
.summary-main footer p { margin: 5px 0 0; color: #7b7062; font-size: 12px; }
@media (max-width: 620px) { .head-summary { grid-template-columns: 1fr; } .seal-column { align-items: center; flex-direction: row; gap: 4px; padding: 12px 18px; } .seal-column > span { font-size: 20px; } .seal-column small { margin: 0 0 0 auto; writing-mode: horizontal-tb; } .summary-main { padding: 22px 18px; } .summary-main footer { align-items: stretch; flex-direction: column; } }
</style>

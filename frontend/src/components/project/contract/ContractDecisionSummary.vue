<script setup>
const props = defineProps({
  creationContract: { type: Object, default: null },
  styleContract: { type: Object, default: null },
  likes: { type: Array, default: null },
  dislikes: { type: Array, default: null },
  heading: { type: String, default: '作者决策摘要' },
  compact: { type: Boolean, default: false },
})

function readable(value) {
  if (value === undefined || value === null || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.map(readable).join('；') : '—'
  if (typeof value === 'object') {
    if (value.role || value.purpose) return `${value.role || '未命名角色'}：${value.purpose || '未填作用'}`
    return JSON.stringify(value)
  }
  return String(value)
}

function count(value) {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString() : '—'
}

function wordRange(value) {
  if (!Array.isArray(value) || value.length !== 2) return '—'
  return `${count(value[0])} ～ ${count(value[1])} 字`
}
</script>

<template>
  <section class="decision-summary" :class="{ 'decision-summary--compact': props.compact }">
    <header class="decision-summary__heading">
      <span>AUTHOR DECISIONS</span>
      <h4>{{ props.heading }}</h4>
    </header>

    <details :open="!props.compact" class="decision-group">
      <summary>创作坐标与容量</summary>
      <dl class="decision-grid">
        <div><dt>渠道</dt><dd>{{ readable(props.creationContract?.channelProfileKey) }}</dd></div>
        <div><dt>题材</dt><dd>{{ readable(props.creationContract?.genreProfileKey) }}</dd></div>
        <div><dt>质量章程</dt><dd>{{ readable(props.creationContract?.qualityCharterVersion) }}</dd></div>
        <div><dt>目标总字数</dt><dd>{{ count(props.creationContract?.targetTotalWords) }} 字</dd></div>
        <div><dt>预计卷数</dt><dd>{{ count(props.creationContract?.expectedVolumeCount) }} 卷</dd></div>
        <div><dt>预计章数</dt><dd>{{ count(props.creationContract?.expectedChapterCount) }} 章</dd></div>
        <div><dt>单章字数</dt><dd>{{ wordRange(props.creationContract?.chapterWordRangePreference) }}</dd></div>
        <div class="decision-grid__wide"><dt>禁止方向</dt><dd>{{ readable(props.creationContract?.prohibitedDirections) }}</dd></div>
        <div class="decision-grid__wide"><dt>作者备注</dt><dd>{{ readable(props.creationContract?.authorNotes) }}</dd></div>
      </dl>
    </details>

    <details :open="!props.compact" class="decision-group">
      <summary>故事发动机</summary>
      <dl class="decision-grid">
        <div><dt>方案名称</dt><dd>{{ readable(props.creationContract?.selectedEngine?.name) }}</dd></div>
        <div><dt>故事出发点</dt><dd>{{ readable(props.creationContract?.selectedSeed?.title) }}</dd></div>
        <div class="decision-grid__wide"><dt>种子一句话</dt><dd>{{ readable(props.creationContract?.selectedSeed?.logline) }}</dd></div>
        <div class="decision-grid__wide"><dt>故事承诺</dt><dd>{{ readable(props.creationContract?.selectedEngine?.storyPromise) }}</dd></div>
        <div><dt>主角欲望</dt><dd>{{ readable(props.creationContract?.selectedEngine?.protagonistDesire) }}</dd></div>
        <div><dt>持续压力</dt><dd>{{ readable(props.creationContract?.selectedEngine?.sustainedPressure) }}</dd></div>
        <div><dt>成长方向</dt><dd>{{ readable(props.creationContract?.selectedEngine?.growthDirection) }}</dd></div>
        <div><dt>冲突循环</dt><dd>{{ readable(props.creationContract?.selectedEngine?.conflictLoop) }}</dd></div>
        <div><dt>群像角色</dt><dd>{{ readable(props.creationContract?.selectedEngine?.ensembleRoles) }}</dd></div>
        <div><dt>优势与代价</dt><dd>{{ readable(props.creationContract?.selectedEngine?.advantageAndCost) }}</dd></div>
        <div><dt>满足感来源</dt><dd>{{ readable(props.creationContract?.selectedEngine?.satisfactionSources) }}</dd></div>
        <div><dt>长篇变化</dt><dd>{{ readable(props.creationContract?.selectedEngine?.longFormVariation) }}</dd></div>
        <div><dt>结局锚点</dt><dd>{{ readable(props.creationContract?.selectedEngine?.endingAnchor) }}</dd></div>
        <div><dt>发动机风险</dt><dd>{{ readable(props.creationContract?.selectedEngine?.risks) }}</dd></div>
        <div class="decision-grid__wide"><dt>差异化</dt><dd>{{ readable(props.creationContract?.selectedEngine?.differentiation) }}</dd></div>
      </dl>
    </details>

    <details :open="!props.compact" class="decision-group">
      <summary>风格契约</summary>
      <dl class="decision-grid">
        <div><dt>阅读体验</dt><dd>{{ readable(props.styleContract?.readingExperience) }}</dd></div>
        <div><dt>叙事距离</dt><dd>{{ readable(props.styleContract?.narrativeDistance) }}</dd></div>
        <div><dt>句段节奏</dt><dd>{{ readable(props.styleContract?.sentenceParagraphRhythm) }}</dd></div>
        <div><dt>用词密度</dt><dd>{{ readable(props.styleContract?.dictionDensity) }}</dd></div>
        <div><dt>对话与潜台词</dt><dd>{{ readable(props.styleContract?.dialogueAndSubtext) }}</dd></div>
        <div><dt>人物声音</dt><dd>{{ readable(props.styleContract?.characterVoices) }}</dd></div>
        <div><dt>情绪与内心</dt><dd>{{ readable(props.styleContract?.emotionAndInteriority) }}</dd></div>
        <div><dt>动作·解释·环境</dt><dd>{{ readable(props.styleContract?.actionExplanationEnvironment) }}</dd></div>
        <div><dt>主规则</dt><dd>{{ readable(props.styleContract?.primaryRules) }}</dd></div>
        <div><dt>次要风味</dt><dd>{{ readable(props.styleContract?.secondaryFlavor) }}</dd></div>
        <div class="decision-grid__wide"><dt>风格风险</dt><dd>{{ readable(props.styleContract?.risks) }}</dd></div>
      </dl>
    </details>

    <details :open="!props.compact" class="decision-group decision-group--preference">
      <summary>作者偏好</summary>
      <dl class="decision-grid">
        <div><dt>喜欢</dt><dd>{{ readable(props.likes) }}</dd></div>
        <div><dt>避开</dt><dd>{{ readable(props.dislikes) }}</dd></div>
      </dl>
    </details>
  </section>
</template>

<style scoped>
.decision-summary {
  margin-top: 18px;
  border: 1px solid var(--rule, #d8cbb7);
  border-radius: 10px;
  color: var(--ink, #302a23);
  background: var(--paper, #fffdf8);
  overflow: hidden;
}
.decision-summary__heading { padding: 15px 17px 12px; border-bottom: 1px solid var(--rule, #d8cbb7); }
.decision-summary__heading span { color: var(--cinnabar, #9a3f32); font: 700 11px Georgia, serif; letter-spacing: .14em; }
.decision-summary__heading h4 { margin: 4px 0 0; color: var(--ink, #302a23); font: 650 16px 'Noto Serif SC', serif; }
.decision-group { border-bottom: 1px solid var(--rule, #d8cbb7); }
.decision-group:last-child { border-bottom: 0; }
.decision-group summary { padding: 11px 17px; color: var(--jade, #47675a); font: 650 13px 'Noto Serif SC', serif; cursor: pointer; }
.decision-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin: 0; padding: 0 1px 1px; background: var(--rule, #d8cbb7); }
.decision-grid > div { min-width: 0; padding: 11px 15px; background: var(--paper, #fffdf8); }
.decision-grid__wide { grid-column: 1 / -1; }
.decision-grid dt { color: var(--muted, #756a5d); font-size: 11px; }
.decision-grid dd { margin: 4px 0 0; font-size: 12px; line-height: 1.65; overflow-wrap: anywhere; white-space: pre-wrap; }
.decision-summary--compact .decision-group:not(.decision-group--preference) summary { background: color-mix(in srgb, var(--paper, #fffdf8) 92%, var(--jade, #47675a)); }
@media (max-width: 620px) {
  .decision-grid { grid-template-columns: 1fr; }
  .decision-grid__wide { grid-column: auto; }
}
</style>

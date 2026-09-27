<script setup>
import { computed, useId } from 'vue'
import { authorValue, recordLabel } from '../../application/continuity/continuityController.js'

const props = defineProps({ state: { type: Object, required: true } })
defineEmits(['retry'])
const titleId = useId()
const review = computed(() => props.state.data)
const confirmedEvents = computed(() => (review.value?.canonEvents || []).filter(item => item.factKind !== 'claim'))
const eventGroups = computed(() => [
  { key: 'facts', title: '已确认事实', empty: '本章没有新增已确认事实。', items: confirmedEvents.value },
  { key: 'state', title: '本章实体状态变化', empty: '本章没有实体状态变化。', items: confirmedEvents.value.filter(item => item.entityId !== null) },
  { key: 'claims', title: '已记录说法', note: '记录角色或叙述中的说法，不作为已证实的客观事实。', empty: '本章没有新增说法记录。', items: (review.value?.canonEvents || []).filter(item => item.factKind === 'claim') },
  { key: 'clues', title: '线索与伏笔', empty: '本章没有线索或伏笔变化。', items: confirmedEvents.value.filter(item => item.fieldPath.startsWith('plot.') && !item.fieldPath.startsWith('plot.progress.')) },
  { key: 'arcs', title: '人物弧光变化', empty: '本章没有人物弧光变化。', items: confirmedEvents.value.filter(item => item.entityId !== null && item.fieldPath.startsWith('arc.')) },
])
const dimensionLabel = value => ({ plot_effectiveness: '情节有效性', content_richness: '内容充实度', character_vitality: '人物鲜活度', dialogue_credibility: '对白可信度', emotional_naturalness: '情感自然度', continuity: '连续性', pacing: '叙事节奏', style_stability: '风格稳定性', ai_flavor: 'AI 痕迹', reading_motivation: '阅读动力' })[value] || '质量建议'
const blockLabel = value => ({ canon_conflict: '已发生事实冲突', timeline_conflict: '时间线冲突', state_conflict: '状态冲突', empty_candidate: '正文为空', technical_truncation: '正文不完整', candidate_hash_drift: '正文版本变化', session_drift: '写作状态变化', planning_drift: '规划依据变化', outline_drift: '小纲依据变化', deterministic_copy: '内容重复', precheck_incomplete: '检查未完成' })[value] || '定稿检查'
const targetLabel = item => `${({ volume: '分卷', plot: '情节线', story_block: '故事块', stage: '阶段', scene_task: '场景任务' })[item.targetType] || '规划项'} · ${item.targetTitle || '名称暂不可用'}`
const progressLabel = value => ({ started: '已开始', advanced: '已推进', completed: '已完成' })[value] || '状态暂不可用'
const fieldLabel = value => ({ title: '名称', coreChange: '核心变化', mainPressure: '主要压力', ensembleFocus: '群像重点', forbiddenEvents: '禁止提前发生事项', storyQuestion: '故事悬念', futureDirection: '后续方向', expectedPayoff: '预期回收', relatedCharacters: '相关人物', entrySituation: '进入情境', blockGoal: '故事块目标', expectedChange: '预期变化', openQuestions: '待解决问题', involvedCharacters: '参与人物', purpose: '阶段目标', dramaticQuestion: '戏剧问题', task: '场景任务', completionEvidence: '完成依据' })[value] || '规划内容'
const valueText = value => authorValue(value).join('；') || '无'
</script>

<template>
  <section class="final-review-summary" :aria-labelledby="titleId" :aria-busy="state.status === 'loading'">
    <h2 :id="titleId">定稿审查记录</h2>
    <p v-if="state.status === 'loading'" class="final-review-summary__empty" role="status">正在读取本章定稿审查记录…</p>
    <div v-else-if="state.status === 'error'" class="final-review-summary__error" role="alert">
      <p>{{ state.message }}</p><button id="final-review-retry" type="button" @click="$emit('retry')">重新读取审查记录</button>
    </div>
    <template v-else-if="review">
      <p class="final-review-summary__source">来源：第 {{ review.chapterNumber }} 章定稿 · 只读记录</p>
      <p class="final-review-summary__intro">以下为本章定稿时保留的审查与已确认变更。历史状态反映本章当时的变化；后续章节可能继续改变状态。</p>
      <p class="final-review-summary__abstract">{{ review.summary || '本章未记录审查摘要。' }}</p>

      <section class="final-review-summary__section" aria-label="质量审查">
        <h3>质量审查 <span>{{ review.qualityReport.status === 'completed' ? '已完成' : '未完成' }}</span></h3>
        <p class="final-review-summary__hint">质量建议供回看参考，不等同于已确认事实。</p>
        <p v-if="review.qualityReport.status === 'quality_not_completed'" class="final-review-summary__empty">本章质量审查未完成，暂无质量结论。</p>
        <p v-else-if="!review.qualityReport.findings.length" class="final-review-summary__empty">本章没有记录质量改进建议。</p>
        <article v-for="finding in review.qualityReport.findings" :key="finding.id" class="final-review-summary__item">
          <h4>{{ dimensionLabel(finding.dimension) }}</h4>
          <p>{{ finding.reason }}</p><p><strong>改进建议：</strong>{{ finding.suggestedAction }}</p>
          <details><summary>查看第 {{ review.chapterNumber }} 章正文依据</summary><blockquote>{{ finding.evidence.excerpt }}</blockquote><p>{{ finding.evidence.rationale }}</p></details>
        </article>
        <details class="final-review-summary__checks"><summary>定稿检查记录（{{ review.qualityReport.deterministicBlocks.length }} 项）</summary>
          <p v-if="!review.qualityReport.deterministicBlocks.length" class="final-review-summary__empty">没有记录阻断项。</p>
          <article v-for="(block, index) in review.qualityReport.deterministicBlocks" :key="index" class="final-review-summary__item"><h4>{{ blockLabel(block.code) }}</h4><p>{{ block.message }}</p><blockquote v-if="block.evidence">{{ block.evidence.excerpt }}</blockquote><p v-else class="final-review-summary__hint">该检查没有正文定位。</p></article>
        </details>
      </section>

      <section v-for="group in eventGroups" :key="group.key" class="final-review-summary__section" :aria-label="group.title">
        <h3>{{ group.title }} <span>{{ group.items.length }} 项</span></h3>
        <p v-if="group.note" class="final-review-summary__hint">{{ group.note }}</p>
        <p v-if="!group.items.length" class="final-review-summary__empty">{{ group.empty }}</p>
        <article v-for="item in group.items" :key="item.id" class="final-review-summary__item">
          <h4>{{ item.entityName || (item.entityId ? '相关实体名称暂不可用' : '全局记录') }} · {{ recordLabel(item.fieldPath) }}</h4>
          <p><span v-if="item.assertionOperator === 'not_equals'" class="final-review-summary__negation">{{ item.factKind === 'claim' ? '说法中的否定：' : '已确认不成立：' }}</span>{{ valueText(item.value) }}</p>
          <details><summary>查看第 {{ review.chapterNumber }} 章正文依据</summary><blockquote>{{ item.evidence.excerpt }}</blockquote><p>{{ item.evidence.rationale }}</p></details>
        </article>
      </section>

      <section class="final-review-summary__section" aria-label="实际故事进度">
        <h3>实际故事进度 <span>{{ review.storyProgressEvents.length }} 项</span></h3>
        <p v-if="!review.storyProgressEvents.length" class="final-review-summary__empty">本章没有确认故事进度变化。</p>
        <article v-for="item in review.storyProgressEvents" :key="item.id" class="final-review-summary__item">
          <h4>{{ targetLabel(item) }} <span>{{ progressLabel(item.status) }}</span></h4>
          <details><summary>查看第 {{ review.chapterNumber }} 章正文依据</summary><blockquote>{{ item.evidence.excerpt }}</blockquote><p>{{ item.evidence.rationale }}</p></details>
        </article>
      </section>

      <section class="final-review-summary__section" aria-label="未来规划调整">
        <h3>未来规划调整 <span>{{ review.planningPatches.length }} 项</span></h3>
        <p class="final-review-summary__hint">这些调整在本章定稿时应用于后续计划，不表示对应情节已经发生。</p>
        <p v-if="!review.planningPatches.length" class="final-review-summary__empty">本章没有调整未来规划。</p>
        <article v-for="item in review.planningPatches" :key="item.id" class="final-review-summary__item">
          <h4>{{ targetLabel(item) }}</h4><p><strong>{{ fieldLabel(item.fieldPath) }}：</strong>{{ valueText(item.replacement) }}</p>
          <details><summary>查看第 {{ review.chapterNumber }} 章正文依据</summary><blockquote>{{ item.evidence.excerpt }}</blockquote><p>{{ item.evidence.rationale }}</p></details>
        </article>
      </section>
      <details class="final-review-summary__diagnostics"><summary>记录来源详情</summary><dl><dt>来源章节</dt><dd>第 {{ review.chapterNumber }} 章</dd><dt>定稿记录</dt><dd>{{ review.finalizationId }}</dd><dt>事实版本</dt><dd>{{ review.canonRevision }}</dd></dl></details>
    </template>
  </section>
</template>

<style scoped>
.final-review-summary{color:var(--nc-ink);line-height:1.75;overflow-wrap:anywhere}.final-review-summary h2{margin:0;font-family:Georgia,'Noto Serif SC',serif}.final-review-summary__source{color:var(--nc-vermilion);font-weight:700}.final-review-summary__intro,.final-review-summary__hint,.final-review-summary__empty{color:var(--nc-muted)}.final-review-summary__abstract{padding:16px 20px;background:var(--nc-canvas);border-left:3px solid var(--nc-vermilion)}.final-review-summary__section{padding:20px 0;border-top:1px solid var(--nc-border)}.final-review-summary h3{display:flex;gap:12px;align-items:center;margin:0 0 12px}.final-review-summary h3 span,.final-review-summary h4 span{font-size:13px;font-weight:400;color:var(--nc-muted)}.final-review-summary h4{margin:0 0 8px}.final-review-summary__item{padding:16px 20px;margin-top:12px;background:var(--nc-canvas);border:1px solid var(--nc-border)}.final-review-summary__item p{margin:8px 0}.final-review-summary summary{cursor:pointer;min-height:36px;display:list-item;align-content:center;color:var(--nc-vermilion)}.final-review-summary blockquote{margin:12px 0;padding:12px 16px;border-left:2px solid var(--nc-border);white-space:pre-wrap;background:var(--nc-paper)}.final-review-summary__checks{margin-top:16px}.final-review-summary__negation{font-weight:700}.final-review-summary__diagnostics{padding-top:16px;border-top:1px solid var(--nc-border)}.final-review-summary__diagnostics dl{display:grid;grid-template-columns:100px minmax(0,1fr);gap:8px}.final-review-summary__diagnostics dd{margin:0}.final-review-summary__error button{min-height:44px;padding:0 16px;color:var(--nc-vermilion);background:var(--nc-paper);border:1px solid var(--nc-border);cursor:pointer}.final-review-summary :is(button,summary):focus-visible{outline:2px solid var(--nc-vermilion);outline-offset:3px}
</style>

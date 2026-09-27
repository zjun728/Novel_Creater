<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate, useRouter } from 'vue-router'
import { TOPIC_GENRES, TOPIC_QUICK_GENRES, createTopicSuggestionController, enterBlankTopicDiscussion } from '../../application/topics/topicSuggestionController.js'
import { useMarketSourceStore } from '../../stores/marketSourceStore.js'
import { useTopicCenterStore } from '../../stores/topicCenterStore.js'
import { readTopicDraft, writeTopicDraft } from './topicDiscussionDraftSession'
import { topicDiscussionsPath } from '../../router/projectRoutes.js'

const topics = useTopicCenterStore()
const router = useRouter()
const emit = defineEmits(['busy'])
const { state, selectGenre, generate } = createTopicSuggestionController({ market: useMarketSourceStore(), topics })

const result = computed(() => state.lastResult?.result)
const suggestions = computed(() => result.value?.directionSuggestions || [])
const selectedCategory = computed(() => ({ 东方玄幻: '玄幻', 修真: '仙侠修真', 穿越: '历史' }[state.genre] || state.genre))
async function discussSuggestion(suggestion) {
  const saved = state.lastResult
  if (!saved || state.busy) return
  try {
    await topics.openDiscussion(saved.discussionId)
    topics.selectedEvidence = saved.evidence.map(item => ({ ...item }))
    topics.discussionSubject = null
    topics.discussionRecommendation = { discussionId: saved.discussionId, title: suggestion.title }
    if (!readTopicDraft(saved.discussionId)) writeTopicDraft(saved.discussionId, `请围绕“${suggestion.title}”继续讨论。`)
    await router.push(topicDiscussionsPath())
  } catch { state.error = '讨论读取失败，建议已保留，请重试。' }
}
async function directDiscussion() {
  if (!state.busy && enterBlankTopicDiscussion(topics)) await router.push({ path: topicDiscussionsPath(), query: { new: '1' } })
}
watch(() => state.busy, value => emit('busy', value), { flush: 'sync' })
onBeforeRouteLeave(() => !state.busy)
onBeforeRouteUpdate(() => !state.busy)
function beforeUnload(event) { if (state.busy) { event.preventDefault(); event.returnValue = '' } }
globalThis.window?.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => globalThis.window?.removeEventListener('beforeunload', beforeUnload))
function timeLabel(value) {
  const ms = value < 10_000_000_000 ? value * 1000 : value
  return new Date(ms).toLocaleString('zh-CN')
}
</script>

<template>
  <section class="suggestion-start" aria-label="热门选题建议" :aria-busy="state.busy">
    <section class="genre-panel" aria-label="创作类型选择">
      <p class="genre-label">创作类型 · 单选</p>
      <div class="genre-options" role="group" aria-label="小说类型">
        <button v-for="genre in TOPIC_GENRES" :key="genre" :aria-pressed="selectedCategory === genre" :disabled="state.busy" @click="selectGenre(genre)">{{ genre }}</button>
      </div>
      <div class="quick-genres"><span>快捷方向</span><button v-for="genre in TOPIC_QUICK_GENRES" :key="genre" :aria-pressed="state.genre === genre" :disabled="state.busy" @click="selectGenre(genre)">{{ genre }}</button><span class="current-genre">当前：{{ state.genre }}</span></div>
    </section>

    <section v-if="suggestions.length" class="results" aria-label="本次创作建议">
      <div class="results-heading"><h2>{{ state.lastResult.genre }} · 本次创作建议</h2><span class="result-provenance" :title="state.lastResult.sources.map(source => `${source.name} ${timeLabel(source.capturedAt)}`).join('；')">来源与获取时间：<span v-for="source in state.lastResult.sources" :key="source.name">{{ source.name }} {{ timeLabel(source.capturedAt) }} </span></span></div>
      <div class="suggestion-cards">
        <article v-for="(suggestion, index) in suggestions" :key="index">
          <h3 :title="suggestion.title">{{ suggestion.title }}</h3><span class="suggestion-genre">{{ suggestion.genreOpportunity }}</span>
          <p>{{ suggestion.readerPromise }}</p><p class="long-form">长篇空间：{{ suggestion.longFormPotential || suggestion.differentiation }}</p>
          <button class="primary" :disabled="state.busy || topics.sending" @click="discussSuggestion(suggestion)">围绕此建议讨论</button>
        </article>
      </div>
    </section>
    <section v-else class="start-state" aria-labelledby="suggestion-start-title">
      <span class="state-label">{{ state.busy ? '正在生成' : state.error ? '本次生成未完成' : '已选择 · 尚未开始' }}</span>
      <h2 id="suggestion-start-title">为“{{ state.genre }}”寻找可写的方向</h2>
      <p>系统将分析可用的市场参考，为你整理读者期待、创作切入点和适合长篇发展的选题建议。</p>
      <p>确认类型后，点击下方按钮开始生成。</p>
      <small>切换类型不会自动抓取市场，也不会调用 AI。</small>
    </section>
    <div v-if="state.stage || state.error" class="generation-status">
      <p v-if="state.stage" role="status">{{ state.stage }}</p><p v-if="state.error" role="alert">{{ state.error }}</p>
    </div>
    <aside class="direct-discussion"><div><strong>已经有自己的想法？</strong><p>从一个灵感开始，与 AI 一起推演故事的可能。</p></div><button :disabled="state.busy || topics.sending" @click="directDiscussion">直接 AI 讨论</button></aside>
    <details v-if="state.sources.length || state.lastResult?.sources.length" class="source-results"><summary>本次市场采集结果与依据</summary>
      <p>参考来自综合或男女频榜单，不代表所选题材的完整市场排名。</p>
      <ul><li v-for="source in (state.sources.length ? state.sources : state.lastResult.sources)" :key="source.name">{{ source.name }} · {{ source.succeeded ? `已获取，快照时间 ${timeLabel(source.capturedAt)}` : '本次失败，未纳入建议依据' }}</li></ul>
    </details>
    <footer class="suggestion-actions"><span>{{ suggestions.length ? '切换类型后，需点击按钮重新生成；已有讨论记录会保留。' : '点击按钮后才开始市场抓取与建议生成。' }}</span><button class="primary" :disabled="state.busy || topics.sending || state.outcomeUnknown" @click="generate">{{ state.busy ? '正在生成…' : suggestions.length ? '重新生成选题建议' : '开始生成选题建议' }}</button></footer>
  </section>
</template>

<style scoped>
.suggestion-start{display:grid;gap:20px;min-width:0;color:#302d28}.genre-panel,.start-state,.direct-discussion,.suggestion-cards article{border:1px solid #ddd5c8;border-radius:6px;background:#fffefa}.genre-panel{padding:16px 18px 10px}.genre-label{line-height:18px;margin:0 0 10px;color:#6f685e;font-size:13px}.genre-options{display:grid;grid-template-columns:repeat(8,minmax(0,1fr));gap:8px 11px}button{font:inherit;cursor:pointer;border:1px solid #ddd5c8;color:inherit;background:#f5f2eb;border-radius:6px}button:disabled{opacity:.55;cursor:default}.genre-options button{height:32px;padding:0 4px;font-size:13px}.genre-options button[aria-pressed=true]{background:#934735;border-color:#934735;color:#fffefa}.quick-genres{display:flex;align-items:center;gap:18px;min-height:30px;margin-top:8px;font-size:12px;color:#6f685e}.quick-genres button{border:0;background:none;padding:0;color:#934735}.quick-genres button[aria-pressed=true]{text-decoration:underline}.current-genre{margin-left:auto}.start-state{min-height:282px;padding:24px}.state-label{display:inline-block;padding:4px 10px;border-radius:4px;background:#f3eee5;color:#6f685e;font-size:12px}h2{margin:18px 0;font:600 28px/1.5 'Noto Serif SC','Songti SC',serif}.start-state p{font-size:16px;line-height:1.8;margin:5px 0}.start-state small{display:block;margin-top:22px;color:#6f685e;font-size:13px}.direct-discussion{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:10px 18px;min-height:66px}.direct-discussion strong{font-size:16px;font-weight:500}.direct-discussion p{font-size:12px;color:#6f685e;margin:4px 0 0}.direct-discussion>button{background:#fffefa;display:grid;place-items:center;width:252px;min-height:44px;border:1px solid #ddd5c8;border-radius:8px;color:#934735;text-decoration:none}.suggestion-actions{position:fixed;z-index:15;bottom:0;left:224px;right:0;height:76px;padding:14px 36px;display:flex;align-items:center;justify-content:space-between;gap:20px;background:#fffefa;border-top:1px solid #ddd5c8}.suggestion-actions>span{font-size:13px;color:#6f685e}.primary{min-height:46px;background:#934735;border-color:#934735;color:#fffefa;border-radius:10px;padding:10px 20px}.suggestion-actions button{width:264px;flex-shrink:0}.results-heading{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:8px}.results-heading h2{margin:0;font-size:22px}.result-provenance{max-width:55%;text-align:right;line-height:1.6;max-height:32px;overflow:hidden}.result-provenance>span{display:inline-block;margin-left:8px}.results-heading span,.source-results,.generation-status{font-size:12px;color:#6f685e}.suggestion-cards{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}.suggestion-cards article{padding:20px;display:flex;flex-direction:column;height:246px}.suggestion-cards h3{flex-shrink:0;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;font:600 24px/1.4 'Noto Serif SC','Songti SC',serif;margin:0 0 8px;overflow-wrap:anywhere}.suggestion-genre{flex-shrink:0;display:-webkit-box;-webkit-line-clamp:1;-webkit-box-orient:vertical;overflow:hidden;color:#934735;font-size:13px}.suggestion-cards p{margin:10px 0 8px;font-size:14px;line-height:1.7;overflow-wrap:anywhere}.suggestion-cards p{flex-shrink:0;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.suggestion-cards .long-form{-webkit-line-clamp:1;margin-top:auto;font-size:12px;color:#6f685e}.suggestion-cards button{margin-top:8px;flex-shrink:0;width:100%}.generation-status p{margin:0;line-height:1.7}[role=alert]{color:#934735}.source-results summary{cursor:pointer}
@media(max-width:1119px){.suggestion-actions{left:72px}}
@media(max-width:720px){.genre-options{grid-template-columns:repeat(4,minmax(0,1fr))}.quick-genres{gap:12px;flex-wrap:wrap}.current-genre{width:100%;margin-left:0}.suggestion-cards{grid-template-columns:1fr}.direct-discussion{align-items:stretch;flex-direction:column}.direct-discussion>button{width:auto}.suggestion-actions{left:72px;padding:12px 16px;height:auto}.suggestion-actions>span{display:none}.suggestion-actions button{width:100%}.results-heading{align-items:start;flex-direction:column}.start-state{padding:20px}.start-state h2{font-size:24px}}
@media(min-width:1120px) and (max-height:820px){.suggestion-start{gap:14px}.genre-panel{padding:12px 18px 8px}.genre-label{margin-bottom:8px}.genre-options{gap:6px 11px}.genre-options button{height:28px}.quick-genres{min-height:24px;margin-top:4px}.results-heading h2{font-size:20px}.results-heading{margin-bottom:6px}.result-provenance{max-height:28px;font-size:11px}.suggestion-cards article{height:214px;padding:16px 18px}.suggestion-cards h3{font-size:21px;line-height:28px;margin-bottom:5px}.suggestion-cards p{font-size:13px;line-height:20px;margin:7px 0}.suggestion-cards .long-form{font-size:11px;line-height:18px;margin-top:auto}.suggestion-cards button{min-height:38px;padding:7px 12px;margin-top:5px}.direct-discussion{min-height:60px;padding:7px 18px}.direct-discussion>button{min-height:40px}.start-state{min-height:240px}}
@media(max-width:760px){.suggestion-actions{left:0}}
</style>

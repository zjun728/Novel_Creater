<script setup>
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NResult, NSkeleton } from 'naive-ui'
import FinalChapterArticle from '../components/manuscript/FinalChapterArticle.vue'
import FinalOutlinePanel from '../components/manuscript/FinalOutlinePanel.vue'
import { api } from '../api/db/client.js'
import { chapterDataMatchesRoute, createManuscriptController } from '../application/manuscript/manuscriptController.js'
import { createNovelDownloadController } from '../application/downloads/novelDownloadController.js'
import { useOperationStore } from '../stores/operationStore.js'
import { finalChapterPath, manuscriptPath, parsePositiveChapterNumber } from '../router/projectRoutes.js'
import { MANUSCRIPT_HISTORY_CONTEXT } from '../application/manuscript/manuscriptHistory.js'

const route = useRoute(); const router = useRouter(); const manuscript = createManuscriptController({ api })
const manuscriptHistory = inject(MANUSCRIPT_HISTORY_CONTEXT, null)
const titleRef = ref(null)
function saveDownload(url, filename) {
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.hidden = true
  document.body.append(link)
  try { link.click() } finally { link.remove() }
}
const download = createNovelDownloadController({ api, operationStore: useOperationStore(), createObjectURL: blob => URL.createObjectURL(blob), revokeObjectURL: value => URL.revokeObjectURL(value), saveBlob: saveDownload })
const projectId = computed(() => String(route.params.projectId || ''))
const chapterNumber = computed(() => { try { return parsePositiveChapterNumber(route.params.chapterNumber) } catch { return null } })
const view = computed(() => route.query.view === 'outline' ? 'outline' : 'text')
const data = computed(() => manuscript.content.value.data)
const status = computed(() => manuscript.content.value.status)
const preparation = computed(() => manuscript.preparation.value)
const isArchived = computed(() => data.value?.lifecycle === 'archived' || preparation.value.status === 'archived')
const chapterCanDownload = computed(() => data.value && download.options.value?.available && download.options.value.chapters.some(item => item.number === data.value.chapter.number))
function setView(next) { return router.push({ query: { ...route.query, view: next } }) }
async function retryContent() {
  if (!chapterNumber.value) return false
  await manuscript.loadContent(projectId.value, chapterNumber.value, { force: true })
  await nextTick()
  await manuscriptHistory?.viewRendered(route)
  if (data.value && !download.options.value) await loadOptions()
  return data.value !== null
}
function retryPreparation() { return manuscript.loadPreparation(projectId.value) }
function loadOptions() { return download.loadOptions(projectId.value).catch(() => false) }
async function loadReader(id, number) {
  download.selectProject(id)
  download.resetTransient()
  if (!number) {
    await manuscript.loadContent(id, 0)
    return
  }
  const contentRequest = manuscript.loadContent(id, number)
  void manuscript.loadPreparation(id)
  await contentRequest
  if (id !== projectId.value || number !== chapterNumber.value) return
  await nextTick()
  if (id !== projectId.value || number !== chapterNumber.value) return
  const scroller = titleRef.value?.closest?.('.product-app-shell__content')
  await manuscriptHistory?.viewRendered(route)
  if (!manuscriptHistory) {
    titleRef.value?.focus?.({ preventScroll: true })
    if (scroller?.scrollTo) scroller.scrollTo({ top: 0, behavior: 'auto' })
    else if (scroller) scroller.scrollTop = 0
  }
  if (data.value && !download.options.value) void loadOptions()
}
async function downloadChapter(format) { if (data.value) { try { await download.download(projectId.value, { scope: 'chapter', chapterNumber: data.value.chapter.number, format }) } catch {} } }
watch([projectId, chapterNumber], ([id, number]) => { void loadReader(id, number) }, { immediate: true })
watch(() => route.query.view, async value => {
  if (value !== undefined && value !== 'text' && value !== 'outline') {
    await router.replace({ query: { ...route.query, view: 'text' } })
    return
  }
  if (!chapterDataMatchesRoute(data.value, projectId.value, chapterNumber.value)) return
  await nextTick()
  await manuscriptHistory?.viewRendered(route)
}, { immediate: true })
onBeforeUnmount(() => { manuscript.dispose(); download.dispose() })
</script>
<template>
  <section class="final-reader" aria-labelledby="final-reader-title" :aria-busy="status === 'loading'">
    <router-link id="final-reader-directory-back" class="final-reader__back" :to="manuscriptPath(projectId)">返回作品目录</router-link>
    <header class="final-reader__header">
      <p class="final-reader__eyebrow">FINAL MANUSCRIPT</p>
      <h1 id="final-reader-title" ref="titleRef" tabindex="-1">{{ data ? `第 ${data.chapter.number} 章 · ${data.chapter.title}` : '章节定稿' }}</h1>
      <p v-if="data" class="final-reader__meta">第{{ data.volume.order }}卷 · {{ data.volume.title }} · {{ data.chapter.scalarCount.toLocaleString('zh-CN') }} 字 · <time :datetime="data.chapter.finalizedAt">{{ new Date(data.chapter.finalizedAt).toLocaleDateString('zh-CN') }}</time></p>
    </header>
    <section v-if="status === 'loading' && !data" class="final-reader__sheet"><n-skeleton text :repeat="5" /></section>
    <section v-else-if="status === 'missing-project'" class="final-reader__notice"><p>项目不存在或已被删除。</p><router-link id="final-reader-project-library" to="/projects">返回项目库</router-link></section>
    <section v-else-if="status === 'missing-chapter'" class="final-reader__notice"><p>该章节不属于作品稿件。</p><router-link id="final-reader-missing-directory" :to="manuscriptPath(projectId)">返回作品目录</router-link></section>
    <n-result v-else-if="status === 'integrity-failure'" class="final-reader__notice" status="error" title="章节定稿暂时不可用" description="为保护定稿内容，当前无法展示正文或小纲。"><template #footer><p v-if="manuscript.content.value.correlationId" class="final-reader__reference">参考编号：{{ manuscript.content.value.correlationId }}</p><n-button id="final-reader-integrity-retry" @click="retryContent">重新读取</n-button></template></n-result>
    <n-result v-else-if="status === 'invalid-address'" class="final-reader__notice" status="error" title="章节地址无效" description="请从作品目录选择要阅读的定稿章节。"><template #footer><router-link id="final-reader-invalid-directory" :to="manuscriptPath(projectId)">返回作品目录</router-link></template></n-result>
    <section v-else-if="data" class="final-reader__sheet">
      <div class="final-reader__tabs" aria-label="阅读内容"><button id="final-reader-view-text" type="button" :aria-pressed="view === 'text'" @click="setView('text')">正文</button><button id="final-reader-view-outline" type="button" :aria-pressed="view === 'outline'" @click="setView('outline')">本章小纲</button></div>
      <details v-if="chapterCanDownload" class="final-reader__download" :aria-busy="download.busy.value"><summary id="final-reader-download" :aria-disabled="download.busy.value" @click="download.busy.value && $event.preventDefault()">下载本章定稿</summary><div><button v-for="format in download.options.value.formats" :id="`final-reader-download-${format}`" :key="format" type="button" :disabled="download.busy.value" :aria-label="`下载第 ${data.chapter.number} 章定稿 ${format === 'markdown' ? 'Markdown' : 'TXT'}`" @click="downloadChapter(format)">下载 {{ format === 'markdown' ? 'Markdown' : 'TXT' }}</button></div></details>
      <p v-if="download.error.value" class="final-reader__local-error" role="alert">{{ download.error.value }}<button v-if="!download.options.value" id="final-reader-options-retry" type="button" @click="loadOptions">重新读取下载选项</button></p>
      <p v-if="status === 'unavailable'" class="final-reader__local-error" role="alert">正文暂时无法更新，已保留当前已验证内容。<button id="final-reader-content-retry" type="button" @click="retryContent">重新读取正文</button></p>
      <final-chapter-article v-if="view === 'text'" :content="data.chapter.content" />
      <final-outline-panel v-else :outline="data.outline" />
      <nav aria-label="章节导航"><router-link v-if="data.navigation.previousChapterNumber" id="final-reader-previous" :to="finalChapterPath(projectId, data.navigation.previousChapterNumber)">上一篇</router-link><router-link id="final-reader-directory" :to="manuscriptPath(projectId)">目录</router-link><router-link v-if="data.navigation.nextChapterNumber" id="final-reader-next" :to="finalChapterPath(projectId, data.navigation.nextChapterNumber)">下一篇</router-link></nav>
    </section>
    <section v-else class="final-reader__notice"><p>正文暂时无法读取。</p><button id="final-reader-fallback-retry" type="button" @click="retryContent">重新读取正文</button></section>
    <section v-if="!isArchived && !['idle', 'loading', 'invalid-address', 'missing-project'].includes(status)" class="final-reader__continuation" aria-label="当前创作任务">
      <router-link v-if="preparation.status === 'ready'" id="final-reader-current-action" class="final-reader__action" :to="preparation.nextAction.targetPath">{{ preparation.nextAction.label }}</router-link>
      <p v-else-if="preparation.status === 'loading'" class="final-reader__preparation" role="status">正在读取当前创作位置</p>
      <p v-else-if="preparation.status === 'unavailable'" class="final-reader__local-error">创作状态暂时无法读取。<button id="final-reader-preparation-retry" type="button" @click="retryPreparation">重新读取创作状态</button></p>
    </section>
  </section>
</template>
<style scoped>
.final-reader { min-width: 0; min-height: 100%; padding: clamp(24px, 5vw, 64px); overflow-wrap: anywhere; color: var(--nc-ink); background: var(--nc-canvas); }
.final-reader__back { display: flex; width: min(760px, 100%); min-height: 44px; margin: 0 auto 12px; align-items: center; }
.final-reader__header, .final-reader__sheet, .final-reader__notice, .final-reader__continuation { width: min(760px, 100%); margin: 0 auto; padding: clamp(24px, 4vw, 48px); border: 1px solid var(--nc-border); background: var(--nc-paper); box-shadow: 0 24px 64px rgba(58, 43, 27, .07); }
.final-reader__sheet, .final-reader__notice, .final-reader__continuation { margin-top: 16px; }
.final-reader__eyebrow { margin: 0 0 10px; color: var(--nc-vermilion); font: 700 11px Georgia, serif; letter-spacing: .16em; }
.final-reader h1 { margin: 0; font: 600 clamp(32px, 6vw, 52px) Georgia, 'Noto Serif SC', serif; }
.final-reader__meta, .final-reader__preparation, .final-reader__reference { color: var(--nc-muted); line-height: 1.75; }
.final-reader__action { display: inline-flex; min-height: 44px; padding: 0 16px; align-items: center; color: var(--nc-paper); background: var(--nc-ink); text-decoration: none; }
.final-reader__tabs { display: flex; gap: 8px; margin: 24px 0; }
.final-reader__tabs button, .final-reader__download summary, .final-reader__download button { min-height: 44px; padding: 0 14px; border: 1px solid var(--nc-border); color: var(--nc-ink); background: var(--nc-paper); cursor: pointer; }
.final-reader__tabs button[aria-pressed="true"] { color: var(--nc-paper); background: var(--nc-ink); }
.final-reader__download { margin: 0 0 24px; border: 1px solid var(--nc-border); }
.final-reader__download summary { display: flex; align-items: center; border: 0; }
.final-reader__download[open] summary { border-bottom: 1px solid var(--nc-border); }
.final-reader__download > div { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px; }
.final-reader__local-error { color: var(--nc-muted); line-height: 1.75; }
.final-reader__local-error button { min-height: 44px; margin-left: 8px; border: 0; color: var(--nc-vermilion); background: transparent; text-decoration: underline; cursor: pointer; }
.final-reader nav { display: flex; justify-content: space-between; gap: 12px; margin-top: 32px; }
.final-reader nav a { display: inline-flex; min-width: 44px; min-height: 44px; align-items: center; justify-content: center; }
.final-reader :is(a, button, summary):focus-visible { outline: 2px solid var(--nc-vermilion); outline-offset: 3px; }
.final-reader :is(a, button, summary) { min-height: 44px; }
.final-reader__notice :is(a, button), .final-reader__local-error button { display: inline-flex; align-items: center; }
.final-reader__back, .final-reader nav a, .final-reader__notice a { color: var(--nc-vermilion); font-weight: 700; text-underline-offset: 4px; }
.final-reader__action:hover { color: var(--nc-paper); background: var(--nc-vermilion); }
.final-reader :is(button, summary, nav a):hover { border-color: var(--nc-vermilion); }
@media (max-width: 560px) {
  .final-reader { padding: 12px; }
  .final-reader__header, .final-reader__sheet, .final-reader__notice, .final-reader__continuation { padding: 18px; }
  .final-reader__tabs, .final-reader__download > div { display: grid; }
  .final-reader__tabs button, .final-reader__download button { width: 100%; }
  .final-reader__sheet :deep(.final-outline-panel) { padding: 0; border: 0; }
}
@media (prefers-reduced-motion: reduce) {
  .final-reader, .final-reader * { scroll-behavior: auto !important; transition: none !important; animation: none !important; }
}
</style>

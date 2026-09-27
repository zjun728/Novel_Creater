<script setup>
import FinalChapterVersions from '../components/manuscript/FinalChapterVersions.vue'
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NModal, NResult, NSkeleton } from 'naive-ui'
import FinalChapterArticle from '../components/manuscript/FinalChapterArticle.vue'
import FinalOutlinePanel from '../components/manuscript/FinalOutlinePanel.vue'
import FinalReviewSummary from '../components/manuscript/FinalReviewSummary.vue'
import WorkbenchToolTabs from '../components/writer/WorkbenchToolTabs.vue'
import WorkbenchChapterNavigation from '../components/writer/WorkbenchChapterNavigation.vue'
import { api } from '../api/db/client.js'
import { chapterDataMatchesRoute, createManuscriptController } from '../application/manuscript/manuscriptController.js'
import { createFinalReviewController } from '../application/manuscript/finalReviewController.js'
import { createNovelDownloadController } from '../application/downloads/novelDownloadController.js'
import { useOperationStore } from '../stores/operationStore.js'
import { finalChapterPath, manuscriptPath, parsePositiveChapterNumber, planningStoryBlocksPath } from '../router/projectRoutes.js'
import { MANUSCRIPT_HISTORY_CONTEXT } from '../application/manuscript/manuscriptHistory.js'

const route = useRoute(); const router = useRouter(); const manuscript = createManuscriptController({ api })
const manuscriptHistory = inject(MANUSCRIPT_HISTORY_CONTEXT, null)
const titleRef = ref(null)
const outlineDialogOpen = ref(false)
const reviewDialogOpen = ref(false)
const activeTool = ref('reference')
const detailsVisible = ref(true)
const toolScroller = ref(null)
const toolScrollPositions = {}
async function openTool(key) {
  toolScrollPositions[activeTool.value] = toolScroller.value?.scrollTop || 0
  activeTool.value = key
  await nextTick()
  if (toolScroller.value && activeTool.value === key) toolScroller.value.scrollTop = toolScrollPositions[key] || 0
}
watch(activeTool, value => {
  if (value === 'review' && finalReview.state.value.status === 'idle') void loadFinalReview()
})
const finalReview = createFinalReviewController({ api })
function loadFinalReview() { return finalReview.load(projectId.value, chapterNumber.value) }
watch(reviewDialogOpen, value => {
  if (value && finalReview.state.value.status === 'idle') void loadFinalReview()
})
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
let routeGeneration = 0
let contentCycle = 0
let settledCycle = 0
let activePreparationRequest = Promise.resolve()
let closed = false

function isActiveRoute(generation, id, number) {
  return !closed
    && generation === routeGeneration
    && id === projectId.value
    && number === chapterNumber.value
}

function routeSnapshot() {
  return {
    fullPath: String(route.fullPath || ''),
    path: String(route.path || ''),
    name: route.name,
    params: { ...route.params },
    query: { ...route.query },
  }
}

function contentReadyForRoute(id, number) {
  if (['idle', 'loading'].includes(status.value)) return false
  return data.value ? chapterDataMatchesRoute(data.value, id, number) : true
}

function isActiveContentCycle(cycle, generation, id, number) {
  return cycle === contentCycle
    && isActiveRoute(generation, id, number)
    && contentReadyForRoute(id, number)
}

async function settleHistoryWhenAuxiliaryReady(cycle, generation, id, number, requests, notifySettled) {
  await Promise.allSettled(requests)
  if (!isActiveContentCycle(cycle, generation, id, number)) return false
  await nextTick()
  if (!isActiveContentCycle(cycle, generation, id, number)) return false
  settledCycle = cycle
  if (notifySettled) await manuscriptHistory?.viewRendered(routeSnapshot(), { settled: true })
  return isActiveContentCycle(cycle, generation, id, number)
}

function beginHistorySettlement(cycle, generation, id, number, preparationRequest, notifySettled) {
  const optionsRequest = data.value && !download.options.value
    ? loadOptions()
    : Promise.resolve(download.options.value)
  void settleHistoryWhenAuxiliaryReady(cycle, generation, id, number, [preparationRequest, optionsRequest], notifySettled)
}

function setView(next) { return router.push({ query: { ...route.query, view: next } }) }
async function retryContent() {
  const id = projectId.value
  const number = chapterNumber.value
  const generation = routeGeneration
  const cycle = ++contentCycle
  settledCycle = 0
  if (!number || !isActiveRoute(generation, id, number)) return false
  await manuscript.loadContent(id, number, { force: true })
  if (!isActiveContentCycle(cycle, generation, id, number)) return false
  await nextTick()
  if (!isActiveContentCycle(cycle, generation, id, number)) return false
  const historyApplied = await manuscriptHistory?.viewRendered(routeSnapshot())
  if (!isActiveContentCycle(cycle, generation, id, number)) return false
  beginHistorySettlement(cycle, generation, id, number, activePreparationRequest, historyApplied === false)
  return true
}
function retryPreparation() { return manuscript.loadPreparation(projectId.value) }
function loadOptions() { return download.loadOptions(projectId.value).catch(() => false) }
async function loadReader(id, number) {
  for (const key of Object.keys(toolScrollPositions)) delete toolScrollPositions[key]
  activeTool.value = 'reference'
  outlineDialogOpen.value = false
  reviewDialogOpen.value = false
  finalReview.reset()
  const generation = ++routeGeneration
  const cycle = ++contentCycle
  settledCycle = 0
  download.selectProject(id)
  download.resetTransient()
  if (!number) {
    await manuscript.loadContent(id, 0)
    if (!isActiveContentCycle(cycle, generation, id, number)) return
    await nextTick()
    if (!isActiveContentCycle(cycle, generation, id, number)) return
    const historyApplied = await manuscriptHistory?.viewRendered(routeSnapshot())
    if (!isActiveContentCycle(cycle, generation, id, number)) return
    beginHistorySettlement(cycle, generation, id, number, Promise.resolve(), historyApplied === false)
    return
  }
  const contentRequest = manuscript.loadContent(id, number)
  const preparationRequest = manuscript.loadPreparation(id)
  activePreparationRequest = preparationRequest
  await contentRequest
  if (!isActiveContentCycle(cycle, generation, id, number)) return
  await nextTick()
  if (!isActiveContentCycle(cycle, generation, id, number)) return
  const scroller = titleRef.value?.closest?.('.product-app-shell__content')
  const historyApplied = await manuscriptHistory?.viewRendered(routeSnapshot())
  if (!isActiveContentCycle(cycle, generation, id, number)) return
  if (!manuscriptHistory) {
    titleRef.value?.focus?.({ preventScroll: true })
    if (scroller?.scrollTo) scroller.scrollTo({ top: 0, behavior: 'auto' })
    else if (scroller) scroller.scrollTop = 0
  }
  beginHistorySettlement(cycle, generation, id, number, preparationRequest, historyApplied === false)
}
async function downloadChapter(format) { if (data.value) { try { await download.download(projectId.value, { scope: 'chapter', chapterNumber: data.value.chapter.number, format }) } catch {} } }
watch([projectId, chapterNumber], ([id, number]) => { void loadReader(id, number) }, { immediate: true })
watch(() => route.query.view, async value => {
  if (value !== undefined && value !== 'text' && value !== 'outline') {
    await router.replace({ query: { ...route.query, view: 'text' } })
    return
  }
  const id = projectId.value
  const number = chapterNumber.value
  const generation = routeGeneration
  if (!chapterDataMatchesRoute(data.value, id, number)) return
  await nextTick()
  if (!isActiveRoute(generation, id, number) || !chapterDataMatchesRoute(data.value, id, number)) return
  await manuscriptHistory?.viewRendered(routeSnapshot(), { settled: settledCycle === contentCycle })
}, { immediate: true })
onBeforeUnmount(() => {
  closed = true
  routeGeneration += 1
  contentCycle += 1
  manuscript.dispose()
  download.dispose()
  finalReview.dispose()
})
</script>
<template>
  <section class="final-reader" aria-labelledby="final-reader-title" :aria-busy="status === 'loading'">
    <workbench-chapter-navigation v-if="chapterNumber" :project-id="projectId" :chapter-number="chapterNumber" />
    <div class="final-reader__body">
    <router-link id="final-reader-directory-back" class="final-reader__back" :to="manuscriptPath(projectId)">返回作品目录</router-link>
    <header class="final-reader__header">
      <p class="final-reader__eyebrow">FINAL MANUSCRIPT</p>
      <h1 id="final-reader-title" ref="titleRef" tabindex="-1">{{ data ? `第 ${data.chapter.number} 章 · ${data.chapter.title}` : '章节定稿' }}</h1>
      <p v-if="data" class="final-reader__meta">已定稿 · 正文与小纲只读 · 第{{ data.volume.order }}卷 · {{ data.volume.title }} · {{ data.chapter.scalarCount.toLocaleString('zh-CN') }} 字 · <time :datetime="data.chapter.finalizedAt">{{ new Date(data.chapter.finalizedAt).toLocaleDateString('zh-CN') }}</time></p>
    </header>
    <section v-if="!['idle', 'loading', 'invalid-address', 'missing-project'].includes(status)" class="final-reader__continuation" aria-label="当前创作任务">
      <div class="final-reader__tools">
        <button v-if="data" type="button" @click="outlineDialogOpen = true">放大查看本章小纲</button>
        <router-link v-if="!isArchived && preparation.status === 'ready'" id="final-reader-current-action" class="final-reader__action" :to="preparation.nextAction.targetPath">{{ preparation.nextAction.label }}</router-link>
        <button v-else-if="!isArchived && preparation.status === 'unavailable'" id="final-reader-preparation-retry" class="final-reader__action" type="button" @click="retryPreparation">{{ preparation.nextAction?.label || '重新读取创作状态' }}</button>
        <button v-if="data" id="final-reader-review" type="button" @click="reviewDialogOpen = true">查看定稿审查</button>
      </div>
      <p v-if="!isArchived && preparation.status === 'ready'" class="final-reader__preparation">{{ preparation.nextAction.description }}</p>
      <p v-else-if="!isArchived && preparation.status === 'loading'" class="final-reader__preparation" role="status">正在读取当前创作位置</p>
      <p v-else-if="!isArchived && preparation.status === 'unavailable'" class="final-reader__local-error" role="status">{{ preparation.nextAction?.description || '创作状态暂时无法读取。' }}</p>
    </section>
    <section v-if="status === 'loading' && !data" class="final-reader__sheet"><n-skeleton text :repeat="5" /></section>
    <section v-else-if="status === 'missing-project'" class="final-reader__notice"><p>项目不存在或已被删除。</p><router-link id="final-reader-project-library" to="/projects">返回项目库</router-link></section>
    <section v-else-if="status === 'missing-chapter'" class="final-reader__notice"><p>该章节不属于作品稿件。</p><router-link id="final-reader-missing-directory" :to="manuscriptPath(projectId)">返回作品目录</router-link></section>
    <n-result v-else-if="status === 'integrity-failure'" class="final-reader__notice" status="error" title="章节定稿暂时不可用" description="为保护定稿内容，当前无法展示正文或小纲。"><template #footer><n-button id="final-reader-integrity-retry" @click="retryContent">重新读取</n-button></template></n-result>
    <n-result v-else-if="status === 'invalid-address'" class="final-reader__notice" status="error" title="章节地址无效" description="请从作品目录选择要阅读的定稿章节。"><template #footer><router-link id="final-reader-invalid-directory" :to="manuscriptPath(projectId)">返回作品目录</router-link></template></n-result>
    <section v-else-if="data" class="final-reader__sheet" :class="{ 'tools-hidden': !detailsVisible }">
      <div class="final-reader__document">

      <n-modal v-model:show="outlineDialogOpen" preset="card" title="定稿小纲（只读）" style="width:880px;max-width:calc(100vw - 64px)" content-style="max-height:calc(100vh - 200px);overflow-y:auto">
        <final-outline-panel :outline="data.outline" />
      </n-modal>
      <n-modal v-model:show="reviewDialogOpen" preset="card" title="定稿审查（只读）" style="width:1040px;max-width:calc(100vw - 96px)" content-style="max-height:calc(100vh - 200px);overflow-y:auto">
        <final-review-summary :state="finalReview.state.value" @retry="loadFinalReview" />
      </n-modal>
      <div class="final-reader__tabs" aria-label="阅读内容"><button id="final-reader-view-text" type="button" :aria-pressed="view === 'text'" @click="setView('text')">正文</button><button id="final-reader-view-outline" type="button" :aria-pressed="view === 'outline'" @click="setView('outline')">本章小纲</button></div>
      <details v-if="chapterCanDownload" class="final-reader__download" :aria-busy="download.busy.value"><summary id="final-reader-download" :aria-disabled="download.busy.value" @click="download.busy.value && $event.preventDefault()">下载本章定稿</summary><div><button v-for="format in download.options.value.formats" :id="`final-reader-download-${format}`" :key="format" type="button" :disabled="download.busy.value" :aria-label="`下载第 ${data.chapter.number} 章定稿 ${format === 'markdown' ? 'Markdown' : 'TXT'}`" @click="downloadChapter(format)">下载 {{ format === 'markdown' ? 'Markdown' : 'TXT' }}</button></div></details>
      <p v-if="download.error.value" class="final-reader__local-error" role="alert">{{ download.error.value }}<button v-if="!download.options.value" id="final-reader-options-retry" type="button" @click="loadOptions">重新读取下载选项</button></p>
      <p v-if="status === 'unavailable'" class="final-reader__local-error" role="alert">正文暂时无法更新，已保留当前已验证内容。<button id="final-reader-content-retry" type="button" @click="retryContent">重新读取正文</button></p>
      <final-chapter-article v-if="view === 'text'" :content="data.chapter.content" />
      <final-outline-panel v-else :outline="data.outline" />
      <nav aria-label="章节导航"><router-link v-if="data.navigation.previousChapterNumber" id="final-reader-previous" :to="finalChapterPath(projectId, data.navigation.previousChapterNumber)">上一篇</router-link><router-link id="final-reader-directory" :to="manuscriptPath(projectId)">目录</router-link><router-link v-if="data.navigation.nextChapterNumber" id="final-reader-next" :to="finalChapterPath(projectId, data.navigation.nextChapterNumber)">下一篇</router-link></nav>
      </div>
      <aside class="final-reader__tool-region">
        <button :aria-expanded="detailsVisible" @click="detailsVisible = !detailsVisible">{{ detailsVisible ? '收起工具区' : '展开工具区' }}</button>
        <div v-show="detailsVisible" ref="toolScroller" class="final-reader__tool-scroll">
          <workbench-tool-tabs :model-value="activeTool" prefix="reader-tool" @update:model-value="openTool" />
          <section v-show="activeTool === 'assistant'" id="reader-tool-panel-assistant" role="tabpanel" aria-labelledby="reader-tool-tab-assistant"><p>正在阅读已定稿章节，正文只读。通过目录返回当前创作章后可使用 AI 修改。</p></section>
          <section v-show="activeTool === 'review'" id="reader-tool-panel-review" role="tabpanel" aria-labelledby="reader-tool-tab-review"><final-review-summary v-if="finalReview.state.value.status !== 'idle'" :state="finalReview.state.value" @retry="loadFinalReview" /></section>
          <section v-show="activeTool === 'reference'" id="reader-tool-panel-reference" role="tabpanel" aria-labelledby="reader-tool-tab-reference"><final-outline-panel :outline="data.outline" /></section>
          <section v-show="activeTool === 'versions'" id="reader-tool-panel-versions" role="tabpanel" aria-labelledby="reader-tool-tab-versions"><p>正在阅读：第 {{ data.chapter.number }} 章定稿 · {{ data.chapter.scalarCount }} 字</p><FinalChapterVersions v-if="activeTool === 'versions'" :key="`${projectId}:${chapterNumber}`" :project-id="projectId" :chapter-number="chapterNumber" :final-content="data.chapter.content" /></section>
        </div>
      </aside>
    </section>
    <section v-else class="final-reader__notice"><p>正文暂时无法读取。</p><button id="final-reader-fallback-retry" type="button" @click="retryContent">重新读取正文</button></section>
    <footer v-if="data && !isArchived" class="final-reader__planning-shortcut">
      <span>后续创作以当前实际进度为准；检查不会更改已有安排。</span>
      <router-link id="final-reader-check-continuation" :to="`${planningStoryBlocksPath(projectId)}#continuation`">检查后续安排</router-link>
    </footer>

    </div>
  </section>
</template>
<style scoped>
.final-reader__planning-shortcut { display:flex; flex-shrink:0; flex-wrap:wrap; gap:12px; align-items:center; justify-content:space-between; padding:14px 20px; margin-top:12px; background:var(--nc-paper); border:1px solid var(--nc-border); border-radius:6px; color:var(--nc-muted); font-size:13px; }
.final-reader__planning-shortcut a { display:inline-flex; align-items:center; padding:0 18px; border:1px solid var(--nc-border); border-radius:6px; color:var(--nc-ink); text-decoration:none; }
.final-reader { display:grid; grid-template-columns:200px minmax(0,1fr); gap:24px; height:100%; min-width:0; min-height:0; padding:0 24px 0 0; overflow:hidden; color:var(--nc-ink); background:var(--nc-canvas); }
.final-reader__body { min-width:0; min-height:0; display:flex; flex-direction:column; padding:16px 0; }
.final-reader :deep(.chapter-navigation) { width:200px; height:100%; overflow-y:auto; }
.final-reader__back { display: flex; width: min(760px, 100%); min-height: 44px; margin: 0 auto 12px; align-items: center; }
.final-reader__header, .final-reader__sheet, .final-reader__notice, .final-reader__continuation { width: min(760px, 100%); margin: 0 auto; padding: clamp(24px, 4vw, 48px); border: 1px solid var(--nc-border); background: var(--nc-paper); box-shadow: 0 24px 64px rgba(58, 43, 27, .07); }
.final-reader__sheet, .final-reader__notice, .final-reader__continuation { margin-top: 16px; }
.final-reader__eyebrow { margin: 0 0 10px; color: var(--nc-vermilion); font: 700 11px Georgia, serif; letter-spacing: .16em; }
.final-reader h1 { margin: 0; font: 600 clamp(32px, 6vw, 52px) Georgia, 'Noto Serif SC', serif; }
.final-reader__meta, .final-reader__preparation { color: var(--nc-muted); line-height: 1.75; }
.final-reader__action { display: inline-flex; min-height: 44px; padding: 0 16px; align-items: center; color: var(--nc-paper); background: var(--nc-vermilion); border-radius:6px; text-decoration: none; }
.final-reader__tabs { display: flex; gap: 8px; margin: 24px 0; }
.final-reader__tools{display:flex;gap:8px;flex-wrap:wrap}.final-reader__tools button{min-height:44px;padding:0 14px;border:1px solid var(--nc-border);color:var(--nc-ink);background:var(--nc-paper);cursor:pointer}
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
.final-reader__continuation { flex-shrink:0; }
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
.final-reader__header { padding:0; border:0; background:transparent; box-shadow:none; width:100%; }
.final-reader__eyebrow { display:none; }
.final-reader h1 { font-size:26px; }
.final-reader__back { width:100%; min-height:26px; margin-bottom:8px; }
.final-reader__sheet { display:grid; grid-template-columns:minmax(0,1fr) 320px; gap:20px; flex:1; min-height:0; width:100%; padding:0; border:0; background:transparent; box-shadow:none; }
.final-reader__sheet.tools-hidden { grid-template-columns:minmax(0,1fr) auto; }
.final-reader__document { min-height:0; overflow:auto; padding:20px; border:1px solid var(--nc-border); background:var(--nc-paper); }
.final-reader__tool-region { display:flex; flex-direction:column; min-height:0; gap:8px; }
.final-reader__tool-region > button { align-self:flex-end; }
.final-reader__tool-scroll { min-height:0; overflow:auto; border:1px solid var(--nc-border); background:var(--nc-paper); }
.final-reader__tool-scroll [role=tabpanel] { padding:12px; line-height:1.8; }
.final-reader__tool-scroll :deep(.final-outline-panel) { padding:0; border:0; }
.final-reader__continuation { width:100%; padding:8px 0 0; border:0; box-shadow:none; background:transparent; }
.final-reader__continuation .final-reader__tools { display:flex; flex-wrap:wrap; align-items:center; gap:12px; margin:0; }
.final-reader__continuation .final-reader__action { color:var(--nc-paper); background:var(--nc-vermilion); border-color:var(--nc-vermilion); }
.final-reader__continuation p { margin:8px 0 12px; }
</style>

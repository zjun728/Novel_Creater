<script setup>
import { computed, inject, nextTick, onBeforeUnmount, watch } from 'vue'
import { NButton, NResult, NSkeleton } from 'naive-ui'
import { useRoute } from 'vue-router'

import ManuscriptChapterList from '../components/manuscript/ManuscriptChapterList.vue'
import { api } from '../api/db/client.js'
import { createManuscriptController } from '../application/manuscript/manuscriptController.js'
import { createNovelDownloadController } from '../application/downloads/novelDownloadController.js'
import { useOperationStore } from '../stores/operationStore.js'
import { MANUSCRIPT_HISTORY_CONTEXT } from '../application/manuscript/manuscriptHistory.js'

const route = useRoute()
const projectId = computed(() => String(route.params.projectId || ''))
const manuscript = createManuscriptController({ api })
const manuscriptHistory = inject(MANUSCRIPT_HISTORY_CONTEXT, null)

function saveDownload(objectUrl, filename) {
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  link.hidden = true
  document.body.append(link)
  link.click()
  link.remove()
}

const download = createNovelDownloadController({
  api,
  operationStore: useOperationStore(),
  createObjectURL: blob => URL.createObjectURL(blob),
  revokeObjectURL: objectUrl => URL.revokeObjectURL(objectUrl),
  saveBlob: saveDownload,
})
const directory = computed(() => manuscript.content.value.data)
const preparation = computed(() => manuscript.preparation.value)
const isArchived = computed(() => directory.value?.lifecycle === 'archived' || preparation.value.status === 'archived')
const hasChapters = computed(() => (directory.value?.summary?.finalChapterCount || 0) > 0)
const downloadableChapters = computed(() => (download.options.value?.chapters || []).map(item => item.number))
let routeGeneration = 0
let closed = false

function isActiveRoute(generation, id) {
  return !closed && generation === routeGeneration && id === projectId.value
}

async function loadProjectFlow(id, { force = false, resetDownloads = false } = {}) {
  const generation = ++routeGeneration
  if (resetDownloads) download.selectProject(id)
  await manuscript.loadDirectory(id, { force })
  if (!isActiveRoute(generation, id)) return
  if (directory.value?.lifecycle === 'active') {
    await manuscript.loadPreparation(id)
    if (!isActiveRoute(generation, id)) return
  }
  if (hasChapters.value) {
    try { await download.loadOptions(id) } catch {}
  }
  if (!isActiveRoute(generation, id)) return
  await nextTick()
  if (!isActiveRoute(generation, id)) return
  await manuscriptHistory?.viewRendered(route, { settled: true })
}
function loadPreparation() { return manuscript.loadPreparation(projectId.value) }
function loadOptions() { return download.loadOptions(projectId.value).catch(() => false) }
async function downloadBook(format) { try { await download.download(projectId.value, { scope: 'book', format }) } catch {} }
async function downloadVolume(volumeId, format) { try { await download.download(projectId.value, { scope: 'volume', volumeId, format }) } catch {} }
async function downloadChapter(chapterNumber, format) { try { await download.download(projectId.value, { scope: 'chapter', chapterNumber, format }) } catch {} }
function retryContent() { return loadProjectFlow(projectId.value, { force: true }) }

watch(projectId, id => { void loadProjectFlow(id, { resetDownloads: true }) }, { immediate: true })
onBeforeUnmount(() => {
  closed = true
  routeGeneration += 1
  manuscript.dispose()
  download.dispose()
})
</script>

<template>
  <section class="manuscript-index" aria-labelledby="manuscript-index-title" :aria-busy="manuscript.content.value.status === 'loading'">
    <header class="manuscript-index__sheet manuscript-index__header">
      <p class="manuscript-index__eyebrow">FINAL MANUSCRIPT</p>
      <h1 id="manuscript-index-title" tabindex="-1">作品稿件</h1>
    </header>
    <section v-if="manuscript.content.value.status === 'loading' && !directory" class="manuscript-index__sheet">
      <n-skeleton text width="22%" /><n-skeleton text :repeat="5" />
    </section>
    <section v-else-if="manuscript.content.value.status === 'missing-project'" class="manuscript-index__sheet"><p>项目不存在或已被删除。</p><router-link id="manuscript-index-project-library" to="/projects">返回项目库</router-link></section>
    <n-result v-else-if="['integrity-failure', 'invalid-address'].includes(manuscript.content.value.status)" class="manuscript-index__sheet" status="error" title="作品稿件暂时不可用" description="为保护已定稿内容，当前无法展示目录。">
      <template #footer><n-button id="manuscript-index-integrity-retry" type="primary" @click="retryContent">重新读取</n-button></template>
    </n-result>
    <section v-else-if="manuscript.content.value.status === 'unavailable' && !directory" class="manuscript-index__sheet"><p>目录暂时无法读取。</p><button id="manuscript-index-unavailable-retry" type="button" @click="retryContent">重新读取</button></section>
    <section v-else-if="directory" class="manuscript-index__sheet" aria-labelledby="manuscript-index-title">
      <p class="manuscript-index__title">{{ directory.title }}</p>
      <dl v-if="directory" class="manuscript-index__summary" aria-label="稿件统计">
        <div><dt>已定稿</dt><dd>{{ directory.summary.finalChapterCount.toLocaleString('zh-CN') }} 章</dd></div>
        <div><dt>字数</dt><dd>{{ directory.summary.totalScalarCount.toLocaleString('zh-CN') }}</dd></div>
      </dl>

      <p v-if="isArchived" class="manuscript-index__readonly">项目已归档，稿件仅供阅读与下载。</p>
      <p v-else-if="['loading', 'idle'].includes(preparation.status)" role="status">正在读取当前创作位置</p>
      <template v-else-if="preparation.status === 'ready'"><p>当前创作位置：{{ preparation.nextAction.label }}</p><router-link id="manuscript-index-current-action" class="manuscript-index__action" :to="preparation.nextAction.targetPath">{{ preparation.nextAction.label }}</router-link></template>
      <div v-else-if="preparation.status === 'unavailable'" class="manuscript-index__local-error">创作状态暂时无法读取。<button id="manuscript-index-preparation-retry" type="button" @click="loadPreparation">重新读取</button></div>

      <details v-if="hasChapters && download.options.value?.available && download.options.value.formats.length" class="manuscript-download-menu" :aria-busy="download.busy.value">
        <summary id="manuscript-index-download" :aria-disabled="download.busy.value" @click="download.busy.value && $event.preventDefault()">下载定稿</summary>
        <div class="manuscript-download-menu__actions">
          <button v-for="format in download.options.value.formats" :id="`manuscript-index-download-book-${format}`" :key="`book:${format}`" type="button" :disabled="download.busy.value" :aria-label="`下载整本定稿 ${format === 'markdown' ? 'Markdown' : 'TXT'}`" @click="downloadBook(format)">下载整本定稿 {{ format === 'markdown' ? 'Markdown' : 'TXT' }}</button>
          <template v-for="volume in download.options.value.volumes" :key="volume.id"><button v-for="format in download.options.value.formats" :id="`manuscript-index-download-volume-${volume.order}-${format}`" :key="`${volume.id}:${format}`" type="button" :disabled="download.busy.value" :aria-label="`下载第${volume.order}卷 ${format === 'markdown' ? 'Markdown' : 'TXT'}`" @click="downloadVolume(volume.id, format)">下载第{{ volume.order }}卷 {{ format === 'markdown' ? 'Markdown' : 'TXT' }}</button></template>
        </div>
        <p v-if="download.busy.value" role="status">正在准备下载</p>
      </details>
      <p v-if="download.error.value" class="manuscript-index__local-error" role="alert">{{ download.error.value }}<button v-if="!download.options.value" id="manuscript-index-options-retry" type="button" @click="loadOptions">重新读取</button></p>

      <p v-if="manuscript.content.value.status === 'empty'" class="manuscript-index__empty">还没有已定稿章节</p>
      <manuscript-chapter-list v-else :project-id="projectId" :volumes="directory.volumes" :formats="download.options.value?.available ? download.options.value.formats : []" :downloadable-chapters="downloadableChapters" :download-chapter="downloadChapter" :busy="download.busy.value" />
      <div v-if="manuscript.content.value.status === 'unavailable'" class="manuscript-index__local-error" role="alert">目录暂时无法更新，已保留可安全显示的内容。<button id="manuscript-index-content-retry" type="button" @click="retryContent">重新读取</button></div>
    </section>
  </section>
</template>

<style scoped>
.manuscript-index { min-width:0; min-height:100%; padding:clamp(24px,5vw,64px); overflow-wrap:anywhere; color:var(--nc-ink); background:var(--nc-canvas); }
.manuscript-index__sheet { width:min(1040px,100%); min-width:0; margin:auto; padding:clamp(26px,5vw,54px); border:1px solid var(--nc-border); background:var(--nc-paper); box-shadow:0 24px 64px rgba(58,43,27,.07); }
.manuscript-index__eyebrow { margin:0 0 10px; color:var(--nc-vermilion); font:700 11px Georgia,serif; letter-spacing:.16em; }
h1 { margin:0; font:600 clamp(34px,6vw,58px) Georgia,'Noto Serif SC',serif; }
.manuscript-index__title { margin:12px 0 0; color:var(--nc-muted); font:500 18px Georgia,'Noto Serif SC',serif; }
.manuscript-index__summary { display:flex; gap:28px; margin:26px 0; }.manuscript-index__summary div { display:grid; gap:4px; }.manuscript-index__summary dt { color:var(--nc-muted); font-size:12px; }.manuscript-index__summary dd { margin:0; font:700 18px Georgia,'Noto Serif SC',serif; }
.manuscript-index__action {
  display: inline-flex;
  min-height: 44px;
  align-items: center;
  padding: 0 16px;
  border: 1px solid var(--nc-ink);
  color: var(--nc-paper);
  background: var(--nc-ink);
  text-decoration: none;
  font: 600 14px Georgia, 'Noto Serif SC', serif;
}
.manuscript-download-menu {
  margin: 22px 0;
  border: 1px solid var(--nc-border);
  background: var(--nc-paper);
}
.manuscript-download-menu summary {
  min-height: 44px;
  padding: 0 14px;
  display: flex;
  align-items: center;
  color: var(--nc-ink);
  cursor: pointer;
  font: 600 14px Georgia, 'Noto Serif SC', serif;
}
.manuscript-download-menu[open] summary { border-bottom: 1px solid var(--nc-border); }
.manuscript-download-menu__actions { display: flex; flex-wrap: wrap; gap: 8px; padding: 12px; }
.manuscript-download-menu button { min-height: 44px; padding: 0 12px; border: 1px solid var(--nc-border); color: var(--nc-ink); background: var(--nc-paper); cursor: pointer; }
.manuscript-index__readonly,.manuscript-index__empty { margin:22px 0; color:var(--nc-muted); line-height:1.8; }.manuscript-index__empty { padding:28px 0; border-top:1px solid var(--nc-border); }
.manuscript-index__local-error { margin:18px 0; color:var(--nc-muted); line-height:1.7; }.manuscript-index__local-error button { margin-left:8px; border:0; color:var(--nc-vermilion); background:transparent; text-decoration:underline; cursor:pointer; }
.manuscript-index :is(a,button):focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:3px; }
.manuscript-index :is(a,button,summary) { min-height:44px; }
.manuscript-index :is(a,button) { display:inline-flex; align-items:center; }
@media (max-width: 760px) { .manuscript-index { padding:12px; } .manuscript-index__sheet { padding:clamp(18px,5vw,28px); } .manuscript-index__summary { flex-wrap:wrap; } .manuscript-download-menu__actions { display: grid; } .manuscript-download-menu button { width: 100%; white-space:normal; } }
@media (prefers-reduced-motion: reduce) { .manuscript-index, .manuscript-index * { scroll-behavior:auto !important; transition:none !important; animation:none !important; } }
</style>

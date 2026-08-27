<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { NButton, NResult, NSkeleton } from 'naive-ui'
import { useRoute } from 'vue-router'

import ManuscriptChapterList from '../components/manuscript/ManuscriptChapterList.vue'
import { api } from '../api/db/client.js'
import { createManuscriptController } from '../application/manuscript/manuscriptController.js'
import { createNovelDownloadController } from '../application/downloads/novelDownloadController.js'
import { useOperationStore } from '../stores/operationStore.js'

const route = useRoute()
const projectId = computed(() => String(route.params.projectId || ''))
const manuscript = createManuscriptController({ api })

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
const chapterOptions = computed(() => new Set((download.options.value?.chapters || []).map(item => item.number)))
const selectedFormat = ref('')

async function loadDirectory(force = false) { await manuscript.loadDirectory(projectId.value, { force }) }
async function loadPreparation() { await manuscript.loadPreparation(projectId.value) }
async function loadOptions() { if (hasChapters.value) { try { await download.loadOptions(projectId.value) } catch {} } }
async function downloadBook() { if (selectedFormat.value) { try { await download.download(projectId.value, { scope: 'book', format: selectedFormat.value }) } catch {} } }
async function downloadVolume(volumeId) { if (selectedFormat.value) { try { await download.download(projectId.value, { scope: 'volume', volumeId, format: selectedFormat.value }) } catch {} } }
async function downloadChapter(chapterNumber) {
  const format = selectedFormat.value
  if (format && chapterOptions.value.has(chapterNumber)) { try { await download.download(projectId.value, { scope: 'chapter', chapterNumber, format }) } catch {} }
}
function retryContent() { void loadDirectory(true) }

watch(projectId, async () => {
  download.selectProject(projectId.value)
  selectedFormat.value = ''
  await loadDirectory()
  if (directory.value?.lifecycle === 'active') await loadPreparation()
  if (hasChapters.value) await loadOptions()
}, { immediate: true })
onBeforeUnmount(() => { manuscript.dispose(); download.dispose() })
</script>

<template>
  <section class="manuscript-index" aria-labelledby="manuscript-index-title" :aria-busy="manuscript.content.value.status === 'loading'">
    <header class="manuscript-index__sheet manuscript-index__header">
      <p class="manuscript-index__eyebrow">FINAL MANUSCRIPT</p>
      <h1 id="manuscript-index-title">作品稿件</h1>
    </header>
    <section v-if="manuscript.content.value.status === 'loading' && !directory" class="manuscript-index__sheet">
      <n-skeleton text width="22%" /><n-skeleton text :repeat="5" />
    </section>
    <section v-else-if="manuscript.content.value.status === 'missing-project'" class="manuscript-index__sheet"><p>项目不存在或已被删除。</p><router-link to="/projects">返回项目库</router-link></section>
    <n-result v-else-if="['integrity-failure', 'invalid-address'].includes(manuscript.content.value.status)" status="error" title="作品稿件暂时不可用" description="为保护已定稿内容，当前无法展示目录。">
      <template #footer><n-button type="primary" @click="retryContent">重新读取</n-button></template>
    </n-result>
    <section v-else class="manuscript-index__sheet" aria-labelledby="manuscript-index-title">
      <p class="manuscript-index__title">{{ directory?.title || '正在整理稿件目录' }}</p>
      <dl v-if="directory" class="manuscript-index__summary" aria-label="稿件统计">
        <div><dt>已定稿</dt><dd>{{ directory.summary.finalChapterCount }} 章</dd></div>
        <div><dt>字数</dt><dd>{{ directory.summary.totalScalarCount }}</dd></div>
      </dl>

      <p v-if="isArchived" class="manuscript-index__readonly">项目已归档，稿件仅供阅读与下载。</p>
      <router-link v-else-if="preparation.status === 'ready'" class="manuscript-index__action" :to="preparation.nextAction.targetPath">{{ preparation.nextAction.label }}</router-link>
      <div v-else-if="preparation.status === 'unavailable'" class="manuscript-index__local-error">创作状态暂时无法读取。<button type="button" @click="loadPreparation">重新读取</button></div>

      <div v-if="hasChapters && download.options.value?.available" class="manuscript-index__downloads" :aria-busy="download.busy.value">
        <label for="manuscript-download-format">下载格式</label>
        <select id="manuscript-download-format" v-model="selectedFormat"><option value="">选择下载格式</option><option v-for="format in download.options.value.formats" :key="format" :value="format">{{ format === 'markdown' ? 'Markdown' : 'TXT' }}</option></select>
        <template v-if="selectedFormat"><button type="button" :disabled="download.busy.value" @click="downloadBook">下载整本定稿</button><button v-for="volume in download.options.value.volumes" :key="volume.id" type="button" :disabled="download.busy.value" @click="downloadVolume(volume.id)">下载第{{ volume.order }}卷</button></template>
        <p v-if="download.busy.value" role="status">正在准备下载</p>
      </div>
      <p v-if="download.error.value" class="manuscript-index__local-error" role="alert">下载选项暂时无法加载。<button type="button" @click="loadOptions">重新读取</button></p>

      <p v-if="manuscript.content.value.status === 'empty'" class="manuscript-index__empty">还没有已定稿章节</p>
      <manuscript-chapter-list v-else-if="directory" :project-id="projectId" :volumes="directory.volumes" :download-chapter="downloadChapter" :can-download-chapter="number => Boolean(selectedFormat) && chapterOptions.has(number)" />
      <div v-if="manuscript.content.value.status === 'unavailable'" class="manuscript-index__local-error" role="alert">目录暂时无法更新，已保留可安全显示的内容。<button type="button" @click="retryContent">重新读取</button></div>
    </section>
  </section>
</template>

<style scoped>
.manuscript-index { min-height:100%; padding:clamp(24px,5vw,64px); color:var(--nc-ink); background:var(--nc-canvas); }
.manuscript-index__sheet { width:min(1040px,100%); margin:auto; padding:clamp(26px,5vw,54px); border:1px solid var(--nc-border); background:var(--nc-paper); box-shadow:0 24px 64px rgba(58,43,27,.07); }
.manuscript-index__eyebrow { margin:0 0 10px; color:var(--nc-vermilion); font:700 11px Georgia,serif; letter-spacing:.16em; }
h1 { margin:0; font:600 clamp(34px,6vw,58px) Georgia,'Noto Serif SC',serif; }
.manuscript-index__title { margin:12px 0 0; color:var(--nc-muted); font:500 18px Georgia,'Noto Serif SC',serif; }
.manuscript-index__summary { display:flex; gap:28px; margin:26px 0; }.manuscript-index__summary div { display:grid; gap:4px; }.manuscript-index__summary dt { color:var(--nc-muted); font-size:12px; }.manuscript-index__summary dd { margin:0; font:700 18px Georgia,'Noto Serif SC',serif; }
.manuscript-index__action,.manuscript-index__downloads > button { display:inline-flex; min-height:44px; align-items:center; padding:0 16px; border:1px solid var(--nc-ink); color:var(--nc-paper); background:var(--nc-ink); text-decoration:none; font:600 14px Georgia,'Noto Serif SC',serif; }
.manuscript-index__downloads { margin:18px 0; }.manuscript-index__readonly,.manuscript-index__empty { margin:22px 0; color:var(--nc-muted); line-height:1.8; }.manuscript-index__empty { padding:28px 0; border-top:1px solid var(--nc-border); }
.manuscript-index__local-error { margin:18px 0; color:var(--nc-muted); line-height:1.7; }.manuscript-index__local-error button { margin-left:8px; border:0; color:var(--nc-vermilion); background:transparent; text-decoration:underline; cursor:pointer; }
.manuscript-index :is(a,button):focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:3px; }
</style>

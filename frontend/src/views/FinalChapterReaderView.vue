<script setup>
import { computed, onBeforeUnmount, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NResult, NSkeleton } from 'naive-ui'
import FinalChapterArticle from '../components/manuscript/FinalChapterArticle.vue'
import FinalOutlinePanel from '../components/manuscript/FinalOutlinePanel.vue'
import { api } from '../api/db/client.js'
import { createManuscriptController } from '../application/manuscript/manuscriptController.js'
import { createNovelDownloadController } from '../application/downloads/novelDownloadController.js'
import { useOperationStore } from '../stores/operationStore.js'
import { finalChapterPath, manuscriptPath, parsePositiveChapterNumber } from '../router/projectRoutes.js'

const route = useRoute(); const router = useRouter(); const manuscript = createManuscriptController({ api })
function saveDownload(url, filename) {
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.hidden = true
  document.body.append(link)
  link.click()
  link.remove()
}
const download = createNovelDownloadController({ api, operationStore: useOperationStore(), createObjectURL: blob => URL.createObjectURL(blob), revokeObjectURL: value => URL.revokeObjectURL(value), saveBlob: saveDownload })
const projectId = computed(() => String(route.params.projectId || ''))
const chapterNumber = computed(() => { try { return parsePositiveChapterNumber(route.params.chapterNumber) } catch { return null } })
const view = computed(() => route.query.view === 'outline' ? 'outline' : 'text')
const data = computed(() => manuscript.content.value.data)
const status = computed(() => manuscript.content.value.status)
const preparation = computed(() => manuscript.preparation.value)
const chapterCanDownload = computed(() => data.value && download.options.value?.available && download.options.value.chapters.some(item => item.number === data.value.chapter.number))
function setView(next) { router.push({ query: next === 'text' ? {} : { view: next } }) }
function retry() { if (chapterNumber.value) return manuscript.loadContent(projectId.value, chapterNumber.value, { force: true }) }
async function loadReader(id, number) {
  download.selectProject(id)
  if (!number) {
    await manuscript.loadContent(id, 0)
    return
  }
  await manuscript.loadContent(id, number)
  if (id !== projectId.value || number !== chapterNumber.value) return
  void manuscript.loadPreparation(id)
  if (data.value) { try { await download.loadOptions(id) } catch {} }
}
async function downloadChapter(format) { if (data.value) { try { await download.download(projectId.value, { scope: 'chapter', chapterNumber: data.value.chapter.number, format }) } catch {} } }
watch([projectId, chapterNumber], ([id, number]) => { void loadReader(id, number) }, { immediate: true })
watch(() => route.query.view, value => { if (value !== undefined && value !== 'text' && value !== 'outline') router.replace({ query: {} }) }, { immediate: true })
onBeforeUnmount(() => { manuscript.dispose(); download.dispose() })
</script>
<template>
  <section class="final-reader" aria-labelledby="final-reader-title" :aria-busy="status === 'loading'">
    <router-link :to="manuscriptPath(projectId)">返回作品目录</router-link>
    <header><p>FINAL MANUSCRIPT</p><h1 id="final-reader-title">{{ data ? `第 ${data.chapter.number} 章 · ${data.chapter.title}` : '章节定稿' }}</h1></header>
    <section v-if="status === 'loading' && !data"><n-skeleton text :repeat="5" /></section>
    <section v-else-if="status === 'missing-chapter'" class="final-reader__notice"><p>该章节不属于作品稿件。</p><router-link :to="manuscriptPath(projectId)">返回作品目录</router-link><router-link v-if="preparation.status === 'ready'" :to="preparation.nextAction.targetPath">{{ preparation.nextAction.label }}</router-link></section>
    <n-result v-else-if="['integrity-failure', 'invalid-address'].includes(status)" status="error" title="章节定稿暂时不可用" description="为保护定稿内容，当前无法展示正文或小纲。"><template #footer><n-button @click="retry">重新读取</n-button></template></n-result>
    <section v-else-if="data" class="final-reader__sheet"><p>第{{ data.volume.order }}卷 · {{ data.volume.title }} · {{ data.chapter.scalarCount }} 字 · <time :datetime="data.chapter.finalizedAt">{{ new Date(data.chapter.finalizedAt).toLocaleDateString('zh-CN') }}</time></p><router-link v-if="preparation.status === 'ready' && data.lifecycle === 'active'" class="final-reader__action" :to="preparation.nextAction.targetPath">{{ preparation.nextAction.label }}</router-link><div class="final-reader__tabs"><button type="button" :aria-pressed="view === 'text'" @click="setView('text')">正文</button><button type="button" :aria-pressed="view === 'outline'" @click="setView('outline')">本章小纲</button></div><details v-if="chapterCanDownload" class="final-reader__download"><summary>下载本章定稿</summary><button v-for="format in download.options.value.formats" :key="format" type="button" :disabled="download.busy.value" @click="downloadChapter(format)">下载 {{ format === 'markdown' ? 'Markdown' : 'TXT' }}</button></details><p v-if="download.error.value" role="alert">{{ download.error.value }}</p><final-chapter-article v-if="view === 'text'" :content="data.chapter.content" /><final-outline-panel v-else :outline="data.outline" /><nav aria-label="章节导航"><router-link v-if="data.navigation.previousChapterNumber" :to="finalChapterPath(projectId, data.navigation.previousChapterNumber)">上一篇</router-link><router-link :to="manuscriptPath(projectId)">目录</router-link><router-link v-if="data.navigation.nextChapterNumber" :to="finalChapterPath(projectId, data.navigation.nextChapterNumber)">下一篇</router-link></nav></section>
    <section v-else class="final-reader__notice"><p>正文暂时无法读取。</p><button type="button" @click="retry">重新读取</button></section>
  </section>
</template>
<style scoped>
.final-reader { min-height: 100%; padding: clamp(24px, 5vw, 64px); color: var(--nc-ink); background: var(--nc-canvas); }.final-reader > a, .final-reader nav a { color: var(--nc-vermilion); font-weight: 700; }.final-reader header, .final-reader__sheet, .final-reader__notice { width: min(760px, 100%); margin: 0 auto; padding: clamp(24px, 4vw, 48px); border: 1px solid var(--nc-border); background: var(--nc-paper); }.final-reader header p { color: var(--nc-vermilion); font: 700 11px Georgia, serif; letter-spacing: .16em; }.final-reader h1 { margin: 0; font: 600 clamp(32px, 6vw, 52px) Georgia, 'Noto Serif SC', serif; }.final-reader__tabs { display: flex; gap: 8px; margin: 24px 0; }.final-reader__tabs button { min-height: 44px; padding: 0 14px; border: 1px solid var(--nc-border); background: var(--nc-paper); }.final-reader__tabs button[aria-pressed="true"] { color: var(--nc-paper); background: var(--nc-ink); }.final-reader nav { display: flex; justify-content: space-between; gap: 12px; margin-top: 32px; }
</style>

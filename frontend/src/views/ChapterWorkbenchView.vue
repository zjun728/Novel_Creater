<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api/db/client.js'
import { chapterWriterPath, parsePositiveChapterNumber } from '../router/projectRoutes.js'
import ChapterWriterView from './ChapterWriterView.vue'
import FinalChapterReaderView from './FinalChapterReaderView.vue'

const route = useRoute()
const entry = ref(null)
const loading = ref(true)
const message = ref('')
const projectId = computed(() => String(route.params.projectId || ''))
let generation = 0
let abort = null
async function load() {
  const token = ++generation
  abort?.abort()
  abort = new AbortController()
  entry.value = null
  loading.value = true
  message.value = ''
  try {
    const number = parsePositiveChapterNumber(route.params.chapterNumber)
    const result = await api.workbench.bootstrap(projectId.value, number, { signal: abort.signal })
    if (token !== generation) return
    const expected = number < result.authoritative_chapter ? 'historical' : number === result.authoritative_chapter ? 'current' : 'future'
    if (result.project_id !== projectId.value || result.requested_chapter !== number
      || !Number.isSafeInteger(result.authoritative_chapter) || result.authoritative_chapter < 1
      || result.mode !== expected) throw new Error('invalid entry')
    entry.value = result
  } catch (error) {
    if (token === generation) message.value = error?.code === 'WorkbenchProjectMissing' ? '项目不存在。' : '章节暂时无法读取，请重试。'
  } finally { if (token === generation) loading.value = false }
}
watch([projectId, () => route.params.chapterNumber], load, { immediate: true })
// A finalized writer can explicitly enter its reader at the same canonical
// address. Ordinary historical text/outline switching stays local to the reader.
watch(() => route.query.view, value => { if (value && entry.value?.mode === 'current') void load() })
onBeforeUnmount(() => { generation += 1; abort?.abort() })
</script>

<template>
  <section v-if="loading" class="workbench-notice" role="status">正在读取章节位置…</section>
  <section v-else-if="message" class="workbench-notice" role="alert"><h1>章节暂时无法打开</h1><p>{{ message }}</p><button @click="load">重新读取</button></section>
  <final-chapter-reader-view v-else-if="entry?.mode === 'historical'" />
  <section v-else-if="entry?.mode === 'current' && !entry.session && entry.canon_projection_synchronized === false" class="workbench-notice" role="status"><h1>进度同步尚未完成</h1><p>已定稿正文保持只读。同步完成后才能开始下一章。</p><button @click="load">查询进度同步</button></section>
  <chapter-writer-view v-else-if="entry?.mode === 'current'" @read-finalized="load" />
  <section v-else class="workbench-notice"><h1>请先完成当前章节</h1><p>后续章节仍在故事规划中，完成当前章后再进入写作。</p><router-link :to="chapterWriterPath(projectId, entry.authoritative_chapter)">前往第 {{ entry.authoritative_chapter }} 章</router-link></section>
</template>

<style scoped>
.workbench-notice{padding:48px;color:var(--nc-ink);background:var(--nc-canvas);min-height:100%}.workbench-notice p{line-height:1.8}.workbench-notice a{color:var(--nc-vermilion)}.workbench-notice button{padding:10px 18px;border:1px solid var(--nc-border);background:var(--nc-paper);color:inherit;cursor:pointer}
</style>

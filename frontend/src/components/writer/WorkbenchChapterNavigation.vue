<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../../api/db/client.js'
import { chapterWriterPath, finalChapterPath } from '../../router/projectRoutes.js'

const props = defineProps({ projectId: { type: String, required: true }, chapterNumber: { type: Number, required: true }, refreshToken: { type: Number, default: 0 } })
const collapsed = ref(false)
const volumes = ref([])
const selected = ref('')
const currentVolume = ref('')
const currentChapter = ref(null)
const chapters = ref([])
const cursor = ref(null)
const busy = ref(false)
const message = ref('')
let generation = 0
let pageGeneration = 0
let abort = null
async function loadPage(next = null) {
  const token = ++pageGeneration
  const project = props.projectId
  const volume = selected.value
  busy.value = true
  message.value = ''
  chapters.value = []
  cursor.value = null
  try {
    const result = await api.workbench.chapters(project, volume, next ? { cursor: next } : {})
    if (token !== pageGeneration) return
    if (result.project_id !== project || result.volume?.id !== volume || !Array.isArray(result.chapters)) throw new Error('invalid page')
    chapters.value = result.chapters
    cursor.value = result.next_cursor
  } catch { if (token === pageGeneration) message.value = '章节目录暂时无法读取，请重新读取。' }
  finally { if (token === pageGeneration) busy.value = false }
}
async function load() {
  const token = ++generation
  pageGeneration += 1
  abort?.abort()
  abort = new AbortController()
  busy.value = true
  message.value = ''
  volumes.value = []
  chapters.value = []
  cursor.value = null
  currentChapter.value = null
  try {
    const [entry, summary] = await Promise.all([
      api.workbench.bootstrap(props.projectId, props.chapterNumber, { signal: abort.signal }),
      api.workbench.volumes(props.projectId, { signal: abort.signal }),
    ])
    if (token !== generation) return
    if (entry.project_id !== props.projectId || entry.requested_chapter !== props.chapterNumber
      || summary.project_id !== props.projectId || summary.authoritative_chapter !== entry.authoritative_chapter
      || !Array.isArray(summary.volumes)) throw new Error('invalid navigation')
    volumes.value = summary.volumes
    currentVolume.value = summary.volumes.find(item => item.contains_authoritative_chapter)?.volume.id || ''
    currentChapter.value = entry.authoritative_chapter
    selected.value = entry.volume?.id || currentVolume.value || ''
    if (selected.value) {
      const after = Math.max(0, props.chapterNumber - 25)
      await loadPage(after ? `${entry.canon_revision}:${entry.projection_revision}:${entry.authoritative_chapter}:${after}` : null)
    } else {
      message.value = '当前章节尚未分配卷，请先确认本章小纲，或手动选择要查看的卷。'
    }
  } catch { if (token === generation) message.value = '章节目录暂时无法读取，请重新读取。' }
  finally { if (token === generation) busy.value = false }
}
watch(() => [props.projectId, props.chapterNumber, props.refreshToken], load, { immediate: true })
onBeforeUnmount(() => { generation += 1; pageGeneration += 1; abort?.abort() })
</script>

<template>
  <aside class="chapter-navigation" :class="{ collapsed }" aria-label="按卷章节导航">
    <button :aria-expanded="!collapsed" aria-controls="workbench-chapter-directory" @click="collapsed = !collapsed">{{ collapsed ? '展开目录' : '收起目录' }}</button>
    <div v-show="!collapsed" id="workbench-chapter-directory">
      <h2>章节目录</h2>
      <router-link v-if="currentChapter" :to="chapterWriterPath(projectId, currentChapter)">定位当前第 {{ currentChapter }} 章</router-link>
      <label for="workbench-volume">选择卷</label>
      <select id="workbench-volume" v-model="selected" :disabled="busy" @change="loadPage()">
        <option disabled value="">请选择要查看的卷</option>
        <option v-for="item in volumes" :key="item.volume.id" :value="item.volume.id">{{ item.volume.order }} · {{ item.volume.title }}{{ item.contains_authoritative_chapter ? '（当前卷）' : '' }}</option>
      </select>
      <p v-if="busy" role="status">正在读取目录…</p>
      <p v-else-if="message" role="alert">{{ message }}</p>
      <p v-else-if="!chapters.length">本卷还没有可阅读或正在写作的章节。</p>
      <ol v-else>
        <li v-for="chapter in chapters" :key="chapter.chapter_number">
          <router-link :aria-current="chapter.chapter_number === chapterNumber ? 'page' : undefined" :to="chapter.mode === 'historical' ? finalChapterPath(projectId, chapter.chapter_number) : chapterWriterPath(projectId, chapter.chapter_number)">
            <small>第 {{ chapter.chapter_number }} 章 · {{ chapter.mode === 'historical' ? '已定稿' : '当前写作' }}</small><span>{{ chapter.title }}</span>
          </router-link>
        </li>
      </ol>
      <div class="page-buttons"><button :disabled="busy" @click="load">重新读取</button><button v-if="cursor" :disabled="busy" @click="loadPage(cursor)">下一页</button><button v-if="chapters[0]?.chapter_number > 1" :disabled="busy" @click="loadPage()">第一页</button></div>
    </div>
  </aside>
</template>

<style scoped>
.chapter-navigation{width:220px;padding:16px;background:var(--nc-paper);border:1px solid var(--nc-border);align-self:start;box-sizing:border-box}.chapter-navigation.collapsed{width:68px;padding:8px}.chapter-navigation h2{font-size:17px;margin:20px 0 12px}.chapter-navigation button,.chapter-navigation select{font:inherit;font-size:13px;color:var(--nc-ink);background:var(--nc-paper);border:1px solid var(--nc-border);padding:7px;cursor:pointer}.chapter-navigation label{display:block;font-size:12px;margin:20px 0 8px}.chapter-navigation select{width:100%;min-width:0}.chapter-navigation a{color:var(--nc-vermilion);font-size:13px;text-underline-offset:3px}.chapter-navigation ol{list-style:none;padding:0;margin:16px 0}.chapter-navigation li a{display:grid;gap:6px;padding:12px 6px;text-decoration:none;overflow-wrap:anywhere}.chapter-navigation li a[aria-current=page]{background:var(--nc-canvas);border-left:2px solid var(--nc-vermilion)}.chapter-navigation small{color:var(--nc-muted);font-size:11px}.chapter-navigation p{font-size:13px;line-height:1.8}.page-buttons{display:flex;flex-wrap:wrap;gap:6px}@media(max-width:900px){.chapter-navigation,.chapter-navigation.collapsed{width:100%}}
</style>

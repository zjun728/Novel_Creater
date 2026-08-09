<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import { api } from '../../api/db/client.js'
import { createNovelDownloadController } from '../../application/downloads/novelDownloadController.js'
import { useOperationStore } from '../../stores/operationStore.js'

const props = defineProps({
  projectId: { type: [String, Number], default: '' },
  title: { type: String, default: '' },
})

function saveDownload(objectUrl, filename) {
  const link = document.createElement('a')
  link.href = objectUrl
  link.download = filename
  link.hidden = true
  document.body.append(link)
  link.click()
  link.remove()
}

const operationStore = useOperationStore()
const controller = createNovelDownloadController({
  api,
  operationStore,
  createObjectURL: blob => URL.createObjectURL(blob),
  revokeObjectURL: objectUrl => URL.revokeObjectURL(objectUrl),
  saveBlob: saveDownload,
})
const scope = ref('book')
const format = ref('txt')
const volumeId = ref('')
const chapterNumber = ref(null)

const options = computed(() => controller.options.value)
const volumes = computed(() => options.value?.volumes || [])
const chapters = computed(() => options.value?.chapters || [])
const formats = computed(() => options.value?.formats || [])
const validVolume = computed(() => volumes.value.some(item => item.id === volumeId.value))
const validChapter = computed(() => chapters.value.some(item => item.number === chapterNumber.value))
const validScope = computed(() => (
  scope.value === 'book'
  || (scope.value === 'volume' && validVolume.value)
  || (scope.value === 'chapter' && validChapter.value)
))
const hasFinalChapters = computed(() => controller.available.value)
const selector = computed(() => {
  const value = { scope: scope.value, format: format.value }
  if (scope.value === 'volume') value.volumeId = volumeId.value
  if (scope.value === 'chapter') value.chapterNumber = chapterNumber.value
  return value
})
const canDownload = computed(() => (
  Boolean(props.projectId)
  && hasFinalChapters.value
  && formats.value.includes(format.value)
  && validScope.value
  && !controller.loading.value
  && !controller.busy.value
))
const actionLabel = computed(() => ({
  book: '下载整本定稿', volume: '下载分卷定稿', chapter: '下载章节定稿',
}[scope.value] || '下载定稿'))

function chooseFirstSafeSelector() {
  if (scope.value === 'volume') volumeId.value = volumes.value[0]?.id || ''
  if (scope.value === 'chapter') chapterNumber.value = chapters.value[0]?.number ?? null
}

function resetSafeDefaults() {
  if (!formats.value.includes(format.value)) format.value = formats.value.includes('txt')
    ? 'txt'
    : (formats.value[0] || '')
  chooseFirstSafeSelector()
}

function changeScope(event) {
  const nextScope = event?.target?.value
  scope.value = ['book', 'volume', 'chapter'].includes(nextScope) ? nextScope : 'book'
  chooseFirstSafeSelector()
}

function changeFormat(event) {
  const nextFormat = event?.target?.value
  if (formats.value.includes(nextFormat)) format.value = nextFormat
}

function changeVolume(event) {
  const nextVolumeId = event?.target?.value
  if (volumes.value.some(item => item.id === nextVolumeId)) volumeId.value = nextVolumeId
}

function changeChapter(event) {
  const nextNumber = Number(event?.target?.value)
  if (chapters.value.some(item => item.number === nextNumber)) chapterNumber.value = nextNumber
}

async function loadOptions() {
  if (!props.projectId) return
  try {
    await controller.loadOptions(String(props.projectId))
  } catch {
    // The controller provides the only safe, retryable error copy.
  }
}

async function download() {
  if (!canDownload.value) return
  try {
    await controller.download(String(props.projectId), selector.value)
  } catch {
    // The controller owns the fixed delivery error copy.
  }
}

watch(options, resetSafeDefaults)
onMounted(() => { void loadOptions() })
onBeforeUnmount(() => controller.dispose())
</script>

<template>
  <section class="novel-download-panel" aria-labelledby="novel-download-title">
    <div class="novel-download-panel__heading">
      <p>DELIVERY DESK · 定稿交付</p>
      <h2 id="novel-download-title">下载定稿</h2>
      <span v-if="title">{{ title }}</span>
    </div>

    <p v-if="!hasFinalChapters && !controller.loading.value && !controller.error.value" class="novel-download-panel__note">
      尚无已定稿章节，无法下载
    </p>
    <p v-else class="novel-download-panel__note">仅导出已确认的章节定稿，不包含工作稿或候选稿。</p>

    <div v-if="controller.error.value" class="novel-download-panel__error" role="alert">
      <span>{{ controller.error.value }}</span>
      <button type="button" class="novel-download-panel__retry" @click="loadOptions">重新读取</button>
    </div>

    <div class="novel-download-panel__controls" :aria-busy="controller.loading.value">
      <label>
        <span>范围</span>
        <select aria-label="下载范围" :value="scope" :disabled="controller.loading.value || controller.busy.value" @change="changeScope">
          <option value="book">整本</option>
          <option value="volume">分卷</option>
          <option value="chapter">章节</option>
        </select>
      </label>
      <label v-if="scope === 'volume'">
        <span>分卷</span>
        <select aria-label="选择分卷" :value="volumeId" :disabled="!volumes.length || controller.loading.value || controller.busy.value" @change="changeVolume">
          <option v-for="item in volumes" :key="item.id" :value="item.id">第{{ item.order }}卷 · {{ item.title }}</option>
        </select>
      </label>
      <label v-if="scope === 'chapter'">
        <span>章节</span>
        <select aria-label="选择章节" :value="chapterNumber ?? ''" :disabled="!chapters.length || controller.loading.value || controller.busy.value" @change="changeChapter">
          <option v-for="item in chapters" :key="item.number" :value="item.number">第{{ item.number }}章 · {{ item.title }}</option>
        </select>
      </label>
      <label>
        <span>格式</span>
        <select aria-label="下载格式" :value="format" :disabled="!formats.length || controller.loading.value || controller.busy.value" @change="changeFormat">
          <option v-for="item in formats" :key="item" :value="item">{{ item === 'markdown' ? 'Markdown' : 'TXT' }}</option>
        </select>
      </label>
      <button type="button" class="novel-download-panel__action" :disabled="!canDownload" @click="download">
        {{ controller.busy.value ? '正在生成下载…' : actionLabel }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.novel-download-panel { margin-top:32px; padding-top:24px; border-top:1px solid var(--nc-border); color:var(--nc-ink); }
.novel-download-panel__heading { display:grid; gap:4px; }
.novel-download-panel__heading p { margin:0; color:var(--nc-vermilion); font:700 10px Georgia, 'Noto Serif SC', serif; letter-spacing:.15em; }
.novel-download-panel__heading h2 { margin:0; font:600 22px Georgia, 'Noto Serif SC', serif; }
.novel-download-panel__heading span, .novel-download-panel__note { color:var(--nc-muted); font-size:13px; line-height:1.7; }
.novel-download-panel__note { margin:12px 0 0; }
.novel-download-panel__error { display:flex; align-items:center; gap:12px; margin-top:14px; color:#8f382c; font-size:13px; }
.novel-download-panel__retry { padding:0; border:0; color:inherit; background:transparent; font:inherit; text-decoration:underline; cursor:pointer; }
.novel-download-panel__controls { display:flex; flex-wrap:wrap; align-items:end; gap:12px; margin-top:18px; }
.novel-download-panel__controls label { display:grid; min-width:128px; gap:5px; color:var(--nc-muted); font-size:11px; letter-spacing:.06em; }
.novel-download-panel select { min-height:34px; padding:5px 26px 5px 9px; border:1px solid var(--nc-border); border-radius:3px; color:var(--nc-ink); background:var(--nc-paper); font:500 13px Georgia, 'Noto Serif SC', serif; }
.novel-download-panel__action { min-height:34px; padding:6px 13px; border:1px solid var(--nc-ink); border-radius:3px; color:var(--nc-paper); background:var(--nc-ink); font:650 13px Georgia, 'Noto Serif SC', serif; cursor:pointer; }
.novel-download-panel__action:disabled, .novel-download-panel select:disabled { opacity:.5; cursor:not-allowed; }
.novel-download-panel :is(select, button):focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:2px; }
@media (max-width:560px) { .novel-download-panel__controls > * { width:100%; } .novel-download-panel__action { width:100%; } }
</style>

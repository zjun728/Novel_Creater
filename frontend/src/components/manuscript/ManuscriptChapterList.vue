<script setup>
import { finalChapterPath } from '../../router/projectRoutes.js'

const props = defineProps({
  projectId: { type: String, required: true },
  volumes: { type: Array, default: () => [] },
  formats: { type: Array, default: () => [] },
  downloadableChapters: { type: Array, default: () => [] },
  downloadChapter: { type: Function, default: null },
  busy: { type: Boolean, default: false },
})

function dateLabel(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '定稿时间待确认' : date.toLocaleDateString('zh-CN')
}

function canDownload(chapterNumber) {
  return props.downloadableChapters.includes(chapterNumber) && props.formats.length > 0
}
</script>

<template>
  <div class="manuscript-chapter-list" aria-label="已定稿章节目录">
    <section v-for="(volume, volumeIndex) in volumes" :key="volume.id" class="manuscript-chapter-list__volume" :aria-labelledby="`volume-heading-${volumeIndex + 1}`">
      <h2 :id="`volume-heading-${volumeIndex + 1}`">第{{ volume.order }}卷 · {{ volume.title }}</h2>
      <ol class="manuscript-chapter-list__chapters">
        <li v-for="chapter in volume.chapters" :key="chapter.number" class="manuscript-chapter-list__row">
          <router-link class="manuscript-chapter-list__reader" :to="finalChapterPath(projectId, chapter.number)">
            <span class="manuscript-chapter-list__number">第 {{ chapter.number }} 章</span>
            <strong>{{ chapter.title }}</strong>
            <span>{{ chapter.scalarCount }} 字</span>
            <time :datetime="chapter.finalizedAt">{{ dateLabel(chapter.finalizedAt) }}</time>
            <span>已定稿</span>
          </router-link>
          <button v-if="canDownload(chapter.number) && formats.length === 1" type="button" class="manuscript-chapter-list__download" :disabled="busy" :aria-label="`下载第 ${chapter.number} 章定稿 ${formats[0] === 'markdown' ? 'Markdown' : 'TXT'}`" @click="downloadChapter(chapter.number, formats[0])">下载</button>
          <details v-else-if="canDownload(chapter.number)" class="manuscript-chapter-list__download-menu">
            <summary :aria-label="`下载第${chapter.number}章定稿`">下载</summary>
            <button v-for="format in formats" :key="format" type="button" :disabled="busy" :aria-label="`下载第 ${chapter.number} 章定稿 ${format === 'markdown' ? 'Markdown' : 'TXT'}`" @click="downloadChapter(chapter.number, format)">{{ format === 'markdown' ? 'Markdown' : 'TXT' }}</button>
          </details>
        </li>
      </ol>
    </section>
  </div>
</template>

<style scoped>
.manuscript-chapter-list { display:grid; gap:28px; }
.manuscript-chapter-list__volume h2 { margin:0 0 10px; color:var(--nc-ink); font:600 20px Georgia, 'Noto Serif SC', serif; }
.manuscript-chapter-list__chapters { display:grid; gap:8px; margin:0; padding:0; list-style:none; }
.manuscript-chapter-list__row { display:grid; grid-template-columns:minmax(0,1fr) auto; align-items:stretch; border:1px solid var(--nc-border); background:var(--nc-paper); }
.manuscript-chapter-list__reader { display:grid; grid-template-columns:auto minmax(12ch,1fr) auto auto auto; gap:12px; align-items:center; min-height:58px; padding:10px 14px; color:var(--nc-ink); text-decoration:none; }
.manuscript-chapter-list__reader:hover { background:rgba(154,72,58,.05); }
.manuscript-chapter-list__number, time, .manuscript-chapter-list__reader > span:not(.manuscript-chapter-list__number) { color:var(--nc-muted); font-size:13px; }
.manuscript-chapter-list__download, .manuscript-chapter-list__download-menu summary, .manuscript-chapter-list__download-menu button { min-width:52px; min-height:44px; border:0; border-left:1px solid var(--nc-border); color:var(--nc-vermilion); background:transparent; font:600 13px Georgia, 'Noto Serif SC', serif; cursor:pointer; }
.manuscript-chapter-list__download-menu { position:relative; }
.manuscript-chapter-list__download-menu summary { display:grid; place-items:center; list-style:none; }
.manuscript-chapter-list__download-menu summary::-webkit-details-marker { display:none; }
.manuscript-chapter-list__download-menu[open] > button { display:block; width:100%; border-top:1px solid var(--nc-border); }
.manuscript-chapter-list :is(a,button):focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:-2px; }
@media (max-width:760px) { .manuscript-chapter-list__reader { grid-template-columns:auto 1fr; } .manuscript-chapter-list__reader > :nth-child(n+3) { grid-column:2; } .manuscript-chapter-list__download { min-width:56px; } }
</style>

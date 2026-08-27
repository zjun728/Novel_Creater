<script setup>
import { computed } from 'vue'
import { manuscriptPath, parsePositiveChapterNumber } from '../router/projectRoutes.js'

const props = defineProps({ projectId: { type: String, required: true }, chapterNumber: { type: String, required: true } })
const directoryPath = computed(() => manuscriptPath(props.projectId))
const parsedChapterNumber = computed(() => {
  try { return parsePositiveChapterNumber(props.chapterNumber) } catch { return null }
})
</script>

<template>
  <section class="reader-pending" aria-labelledby="reader-pending-title">
    <p class="reader-pending__eyebrow">FINAL MANUSCRIPT</p>
    <h1 id="reader-pending-title">{{ parsedChapterNumber ? `第 ${parsedChapterNumber} 章定稿` : '章节地址无效' }}</h1>
    <p>{{ parsedChapterNumber ? '阅读内容正在接入。' : '无法识别该章节地址。' }}</p>
    <router-link :to="directoryPath">返回作品目录</router-link>
  </section>
</template>

<style scoped>
.reader-pending { min-height:100%; padding:clamp(28px,6vw,72px); color:var(--nc-ink); background:var(--nc-canvas); }
.reader-pending__eyebrow { color:var(--nc-vermilion); font:700 11px Georgia,serif; letter-spacing:.16em; }
h1 { font:600 clamp(34px,6vw,58px) Georgia,'Noto Serif SC',serif; }
a { color:var(--nc-vermilion); font-weight:700; }
</style>

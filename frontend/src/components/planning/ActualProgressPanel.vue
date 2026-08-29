<script setup>
import { computed } from 'vue'

import { presentActualProgress } from '../../application/planning/actualProgressPresentation.js'

const props = defineProps({
  items: { type: Array, default: () => [] },
  status: { type: Object, default: () => ({}) },
  planningContent: { type: Object, default: null },
})

const presentation = computed(() => presentActualProgress({
  items: props.items,
  status: props.status,
  planningContent: props.planningContent,
}))
</script>

<template>
  <aside class="actual-progress-panel" aria-labelledby="actual-progress-heading">
    <header>
      <p class="eyebrow">定稿进度 · 只读</p>
      <h2 id="actual-progress-heading">{{ presentation.heading }}</h2>
    </header>

    <p class="progress-message">{{ presentation.message }}</p>
    <ol v-if="presentation.rows.length" class="progress-list">
      <li v-for="row in presentation.rows" :key="row.key">
        <span>{{ row.chapterLabel }}</span>
        <span>{{ row.kindLabel }}</span>
        <span>{{ row.hierarchyLabel }}</span>
        <span>{{ row.statusLabel }}</span>
      </li>
    </ol>
    <p v-if="presentation.omittedRecognizedCount > 0" class="progress-note">
      还有 {{ presentation.omittedRecognizedCount }} 项较早进度未展开。
    </p>
    <p
      v-if="presentation.unrecognizedCount > 0 && presentation.state === 'recognized'"
      class="progress-note"
    >
      另有 {{ presentation.unrecognizedCount }} 项定稿进度已同步，暂时无法生成作者摘要。
    </p>
  </aside>
</template>

<style scoped>
.actual-progress-panel { margin:0 0 14px; padding:16px 18px; border:1px solid var(--nc-border); border-left:3px solid var(--nc-vermilion); background:var(--nc-paper); }
header { display:grid; gap:4px; }
.eyebrow { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.18em; }
h2 { margin:0; color:var(--nc-ink); font:600 22px Georgia,'Noto Serif SC',serif; }
.progress-message { margin:12px 0 0; color:var(--nc-ink); line-height:1.7; }
.progress-list { display:grid; gap:7px; margin:12px 0 0; padding:0; list-style:none; }
.progress-list li { display:grid; grid-template-columns:auto auto minmax(0,1fr) auto; gap:10px; align-items:baseline; padding:10px 12px; border:1px solid var(--nc-border); background:var(--nc-canvas); color:var(--nc-ink); line-height:1.55; }
.progress-list li span:nth-child(1), .progress-list li span:nth-child(2), .progress-list li span:nth-child(4) { color:var(--nc-muted); font-size:12px; white-space:nowrap; }
.progress-list li span:nth-child(3) { overflow-wrap:anywhere; }
.progress-note { margin:8px 0 0; color:var(--nc-muted); font-size:13px; line-height:1.6; }
</style>

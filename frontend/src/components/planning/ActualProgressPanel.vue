<script setup>
import { computed } from 'vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  status: { type: Object, default: () => ({}) },
})

const progressItems = computed(() => (
  Array.isArray(props.items) ? props.items : []
))
const canonRevision = computed(() => Number(props.status?.canonRevision || 0))
const projectionRevision = computed(() => Number(props.status?.projectionRevision || 0))
const rebuilding = computed(() => props.status?.synchronized === false)

function publicValue(value) {
  if (value == null) return 'null'
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return '（无法显示）'
  }
}

function progressItemKey(item) {
  return JSON.stringify([
    item.revisionNumber,
    item.subjectKey,
    item.entityId,
    item.fieldPath,
  ])
}
</script>

<template>
  <aside class="actual-progress-panel" aria-labelledby="actual-progress-heading">
    <header>
      <div>
        <p class="eyebrow">CANON PROJECTION · READ ONLY</p>
        <h2 id="actual-progress-heading">正文已发生</h2>
      </div>
      <p class="revisions">
        <span>Canon R{{ canonRevision }}</span>
        <span>Projection R{{ projectionRevision }}</span>
      </p>
    </header>

    <p v-if="rebuilding" class="projection-note">正文事实正在重建，暂不展示实际进度</p>
    <p v-else-if="canonRevision === 0" class="projection-note">尚无已定稿事实</p>
    <p v-else-if="!progressItems.length" class="projection-note">尚无可展示的正文事实</p>
    <ol v-else class="progress-list">
      <li v-for="item in progressItems" :key="progressItemKey(item)">
        <dl>
          <div><dt>事实主题</dt><dd>{{ item.subjectKey }}</dd></div>
          <div><dt>字段路径</dt><dd>{{ item.fieldPath }}</dd></div>
          <div class="value"><dt>正文事实</dt><dd>{{ publicValue(item.value) }}</dd></div>
        </dl>
      </li>
    </ol>
  </aside>
</template>

<style scoped>
.actual-progress-panel { margin:0 0 14px; padding:18px 20px; border:1px solid var(--nc-border); border-left:3px solid var(--nc-vermilion); background:var(--nc-paper); }
header { display:flex; align-items:start; justify-content:space-between; gap:16px; }
.eyebrow { margin:0; color:var(--nc-vermilion); font:700 10px Georgia,serif; letter-spacing:.18em; }
h2 { margin:5px 0 0; font:600 24px Georgia,'Noto Serif SC',serif; }
.revisions { display:grid; gap:3px; margin:1px 0 0; color:var(--nc-muted); font:600 11px Georgia,serif; text-align:right; white-space:nowrap; }
.projection-note { margin:14px 0 0; color:var(--nc-muted); line-height:1.7; }
.progress-list { display:grid; gap:8px; margin:14px 0 0; padding:0; list-style:none; }
.progress-list li { padding:12px; border:1px solid var(--nc-border); background:var(--nc-canvas); }
dl { display:grid; grid-template-columns:minmax(100px,.35fr) minmax(140px,.65fr) minmax(180px,1.4fr); gap:12px; margin:0; }
dt { color:var(--nc-muted); font-size:11px; }
dd { margin:4px 0 0; color:var(--nc-ink); line-height:1.6; overflow-wrap:anywhere; }
.value dd { white-space:pre-wrap; }
@media(max-width:760px){header{flex-direction:column}.revisions{text-align:left}dl{grid-template-columns:1fr}.progress-list li{padding:10px}}
</style>

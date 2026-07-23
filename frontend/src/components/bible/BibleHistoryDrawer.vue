<script setup>
import { onMounted } from 'vue'
const props = defineProps({ store: { type: Object, required: true }, projectId: { type: String, required: true }, open: Boolean, readOnly: Boolean })
const emit = defineEmits(['close', 'clone'])
onMounted(() => { if (props.open) void props.store.loadHistory(props.projectId, { limit: 20 }) })
function more() { void props.store.loadHistory(props.projectId, { limit: 20, beforeRevision: props.store.historyNextBeforeRevision, append: true }) }
</script>
<template>
  <aside v-if="open" class="history-overlay" role="dialog" aria-modal="true" aria-label="创作圣经历史">
    <section class="history-sheet"><button aria-label="关闭历史" @click="emit('close')">×</button><h2>修订历史</h2>
      <article v-for="item in store.history" :key="item.bibleRevisionId || item.revision"><strong>Revision {{ item.revision }}</strong><p>{{ item.status }} · {{ item.confirmedAt || '未确认' }}</p><button v-if="!readOnly && item.canClone" @click="emit('clone', item.revision)">Adjust Future Design</button></article>
      <button v-if="store.historyNextBeforeRevision !== null" @click="more">加载更早修订</button>
    </section>
  </aside>
</template>
<style scoped>
.history-overlay { position:fixed; inset:0; z-index:20; display:flex; justify-content:flex-end; background:rgba(39,28,20,.38); }.history-sheet { width:min(460px,100%); overflow:auto; padding:28px; color:#302a23; background:#fffaf0; box-shadow:-16px 0 48px rgba(38,25,15,.22); }.history-sheet article { margin:14px 0; padding:14px; border:1px solid #d8cbb7; }.history-sheet button { margin:6px 0; }
</style>

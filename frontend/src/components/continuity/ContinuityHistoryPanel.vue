<script setup>
import { onBeforeUnmount, watch } from 'vue'
import { api } from '../../api/db/client.js'
import { createContinuityController } from '../../application/continuity/continuityController.js'
import { finalChapterPath } from '../../router/projectRoutes.js'
import ContinuityRecordDetails from './ContinuityRecordDetails.vue'

const props = defineProps({ projectId: { type: String, required: true }, record: { type: Object, required: true }, revision: { type: Number, required: true } })
defineEmits(['close', 'evidence'])
const controller = createContinuityController({ api })
const state = controller.state
function load(offset = 0) {
  void controller.load(props.projectId, { kind: 'facts', field_path: props.record.field, ...(props.record.entityId ? { entity_id: props.record.entityId } : { global_only: true }), revision: props.revision, offset })
}
watch(() => [props.projectId, props.record.id, props.revision], () => load(), { immediate: true })
onBeforeUnmount(controller.dispose)
</script>
<template>
  <section class="history-panel" aria-label="变化历史" aria-live="polite">
    <header><h2>{{ record.entityName || '全书记录' }} · 变化历史</h2><button @click="$emit('close')">关闭历史</button></header>
    <p>按发生时间从新到旧排列，只展示这一项的已确认记录。</p>
    <p v-if="state.status === 'loading'" role="status">正在读取变化历史…</p>
    <div v-else-if="state.status === 'error'" role="alert"><p>{{ state.message }}</p><button @click="load()">重新读取历史</button></div>
    <template v-else-if="state.data">
      <p v-if="!state.data.items.length">暂无可核对的历史记录。</p>
      <article v-for="item in state.data.items" :key="item.id">
        <strong v-if="item.isClaim">人物说法 · 不等同客观事实</strong>
        <ContinuityRecordDetails :record="item" kind="facts" />
        <footer><router-link v-if="item.sourceChapter" :to="finalChapterPath(projectId, item.sourceChapter)">阅读第 {{ item.sourceChapter }} 章</router-link><button v-if="item.sourceEventId" @click="$emit('evidence', item.sourceEventId)">查看这次变化的原文</button></footer>
      </article>
      <footer><button @click="load()">返回最新记录</button><button v-if="state.data.nextOffset !== null" @click="load(state.data.nextOffset)">更早记录</button></footer>
    </template>
  </section>
</template>
<style scoped>
.history-panel{margin-top:24px;padding:22px;background:var(--nc-canvas);border:1px solid var(--nc-border)}header,footer{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}h2{font-size:17px;margin:0}.history-panel>p{color:var(--nc-muted);font-size:13px;line-height:1.8}article{padding:16px 0;border-bottom:1px solid var(--nc-border)}article strong{font-size:13px;color:var(--nc-vermilion)}footer{justify-content:flex-start;margin-top:16px}button{font:inherit;font-size:13px;cursor:pointer;padding:7px 10px;border:1px solid var(--nc-border);color:inherit;background:var(--nc-paper)}a{font-size:13px;color:var(--nc-vermilion)}a:focus-visible,button:focus-visible{outline:2px solid var(--nc-vermilion);outline-offset:3px}
</style>

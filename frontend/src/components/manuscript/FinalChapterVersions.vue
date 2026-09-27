<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { NModal } from 'naive-ui'
import { api } from '../../api/db/client.js'

const props = defineProps({ projectId: String, chapterNumber: Number, finalContent: String })
const candidates = ref([]), selected = ref(null), loading = ref(false), error = ref('')
let epoch = 0
async function load() {
  const request = ++epoch
  candidates.value = []; selected.value = null; error.value = ''; loading.value = true
  try {
    const result = await api.chapterSessions.get(props.projectId, props.chapterNumber)
    if (request !== epoch) return
    if (result.projectId !== props.projectId || result.session?.chapterNum !== props.chapterNumber
        || (result.candidates || []).some(item => item.projectId !== props.projectId || item.chapterSessionId !== result.session.id)) {
      throw new Error('稿件身份不匹配')
    }
    candidates.value = result.candidates || []
  } catch {
    if (request === epoch) error.value = '历史稿件暂时无法读取，请重试。'
  } finally { if (request === epoch) loading.value = false }
}
watch(() => [props.projectId, props.chapterNumber], load, { immediate: true })
onBeforeUnmount(() => { epoch += 1 })
</script>
<template>
  <section aria-label="定稿历史版本">
    <h3>历史版本 <span v-if="!loading && !error">（{{ candidates.length }}）</span></h3>
    <p>本章已定稿，可查阅和比较历史稿件，不能切换正文。</p>
    <p v-if="loading" role="status">正在读取历史稿件…</p>
    <p v-else-if="error" role="alert">{{ error }} <button @click="load">重试</button></p>
    <ol v-else-if="candidates.length">
      <li v-for="(candidate, index) in candidates" :key="candidate.id">
        <strong>保存稿 {{ index + 1 }}</strong><span>{{ Array.from(candidate.content).length }} 字</span>
        <button @click="selected = candidate">查看与定稿对比</button>
      </li>
    </ol>
    <p v-else>没有另外保存的历史稿件。</p>
    <n-modal :show="Boolean(selected)" preset="card" title="历史稿件与定稿对比" style="width:1060px;max-width:calc(100vw - 48px)" @update:show="selected = null">
      <div class="version-columns"><article><h3>历史保存稿</h3><pre tabindex="0">{{ selected?.content }}</pre></article><article><h3>当前定稿</h3><pre tabindex="0">{{ finalContent }}</pre></article></div>
      <p>仅供查阅，不改变定稿、规划或创作进度。</p>
      <button @click="selected = null">关闭对比</button>
    </n-modal>
  </section>
</template>
<style scoped>
li { display:grid; gap:8px; padding:12px 0; border-bottom:1px solid var(--nc-border); } ol { padding:0; list-style:none; }
button { padding:8px 12px; border:1px solid var(--nc-border); background:var(--nc-paper); color:var(--nc-vermilion); cursor:pointer; border-radius:6px; }
p,span { color:var(--nc-muted); font-size:13px; line-height:1.7; }
.version-columns { display:grid; grid-template-columns:1fr 1fr; gap:20px; }.version-columns article { min-width:0; }pre { white-space:pre-wrap; overflow-wrap:anywhere; max-height:60vh; overflow:auto; font:inherit; line-height:1.8; }
@media(max-width:700px) { .version-columns { grid-template-columns:1fr; } }
</style>

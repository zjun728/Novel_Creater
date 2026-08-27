<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../../api/db/client.js'
import { manuscriptPath } from '../../router/projectRoutes.js'
const props = defineProps({ projectId: { type: [String, Number], required: true } })
const count = ref(null)
const failed = ref(false)
let token = 0
let abort = null
async function load() {
  const id = String(props.projectId || '')
  const current = ++token
  abort?.abort()
  abort = new AbortController()
  count.value = null
  failed.value = false
  try {
    const data = await api.manuscripts.index(id, { signal: abort.signal })
    if (current === token && data.projectId === id) count.value = data.summary.finalChapterCount
    else if (current === token) failed.value = true
  } catch { if (current === token) failed.value = true }
}
watch(() => props.projectId, () => { void load() }, { immediate: true })
onBeforeUnmount(() => { token += 1; abort?.abort() })
</script>
<template>
  <span class="manuscript-summary-link">
    <router-link :to="manuscriptPath(String(projectId))">作品稿件 · {{ failed ? '暂时无法读取定稿数量' : count == null ? '正在读取定稿数量' : `已定稿 ${count} 章` }}</router-link>
    <button v-if="failed" type="button" aria-label="重新读取稿件摘要" @click="load">重试</button>
  </span>
</template>
<style scoped>
.manuscript-summary-link { display:inline-flex; gap:8px; align-items:center; }
.manuscript-summary-link a,.manuscript-summary-link button { color:var(--nc-vermilion); font-weight:700; }
.manuscript-summary-link button { border:0; background:none; text-decoration:underline; cursor:pointer; }
</style>

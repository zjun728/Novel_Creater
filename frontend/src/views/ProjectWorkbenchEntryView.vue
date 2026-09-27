<script setup>
import { ref, watch, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/db/client.js'
import { chapterWorkbenchPath } from '../router/projectRoutes.js'
import { mapProjectNextAction } from '../application/projects/projectNextAction.js'

const route = useRoute()
const router = useRouter()
const message = ref('正在读取创作进度…')
const action = ref(null)
const retryLabel = ref('重新读取')
let generation = 0
async function load() {
  const token = ++generation
  const projectId = String(route.params.projectId)
  action.value = null
  retryLabel.value = '重新读取'
  message.value = '正在读取创作进度…'
  try {
    const preparation = await api.projects.preparation(projectId)
    if (token !== generation) return
    const next = mapProjectNextAction(preparation)
    if (next.state === 'available' && next.chapterNumber) {
      await router.replace(chapterWorkbenchPath(projectId, next.chapterNumber))
      return
    }
    action.value = next.state === 'available' ? next : null
    retryLabel.value = next.label || '重新读取'
    message.value = next.description || (next.state === 'archived' ? '项目已归档，请从作品稿件阅读已完成章节。' : '完成当前创作准备后，即可进入章节工作台。')
  } catch { if (token === generation) message.value = '创作进度暂时无法读取，请重试。' }
}
watch(() => route.params.projectId, load, { immediate: true })
onBeforeUnmount(() => { generation += 1 })
</script>

<template>
  <section class="workbench-entry">
    <h1>工作台</h1>
    <p role="status">{{ message }}</p>
    <router-link v-if="action" :to="action.targetPath">{{ action.label }}</router-link>
    <button v-else type="button" @click="load">{{ retryLabel }}</button>
  </section>
</template>

<style scoped>
.workbench-entry { padding:32px; color:var(--nc-ink); }
.workbench-entry p { line-height:1.8; }
.workbench-entry a { color:var(--nc-vermilion); }
</style>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NSelect, NSpin, NTag } from 'naive-ui'
import { useProjectStore } from '@/stores/projectStore'
import { useProviderStore } from '@/stores/providerStore'
import { createLatestRequestGuard } from '@/utils/latestRequest'

const projectStore = useProjectStore()
const providerStore = useProviderStore()
const selectedProjectId = ref('')
const status = ref(null)
const loading = ref(false)
const error = ref('')
const projectsLoading = ref(false)
const projectsError = ref('')
const statusGuard = createLatestRequestGuard()
const projectsGuard = createLatestRequestGuard()

const taskLabels = {
  seed: '种子与选题', planning: '滚动规划', writing: '正文写作', audit: '质量审核',
  summary: '章节摘要', extraction: '状态提取', polish: '修订润色', market: '市场选题',
}
const projectOptions = computed(() => projectStore.projects.map(project => ({ label: project.title, value: project.id })))
const items = computed(() => status.value?.items || [])

async function loadStatus(projectId = selectedProjectId.value) {
  const requestGeneration = statusGuard.begin()
  status.value = null
  error.value = ''
  if (!projectId) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const nextStatus = await providerStore.getBindingStatus(projectId, { force: true })
    if (statusGuard.isCurrent(requestGeneration)) status.value = nextStatus
  } catch (loadError) {
    if (statusGuard.isCurrent(requestGeneration)) {
      error.value = loadError.message || '模型映射加载失败'
    }
  } finally {
    if (statusGuard.isCurrent(requestGeneration)) loading.value = false
  }
}

async function loadProjectsAndSelect(force = false) {
  const requestGeneration = projectsGuard.begin()
  projectsLoading.value = true
  projectsError.value = ''
  try {
    if (force || !projectStore.projects.length) await projectStore.loadProjects()
    if (!projectsGuard.isCurrent(requestGeneration)) return
    selectedProjectId.value = projectStore.currentProject?.id || projectStore.projects[0]?.id || ''
    if (!selectedProjectId.value) {
      statusGuard.invalidate()
      status.value = null
      loading.value = false
    }
  } catch (loadError) {
    if (projectsGuard.isCurrent(requestGeneration)) {
      projectsError.value = loadError.message || '项目列表加载失败'
      selectedProjectId.value = ''
      statusGuard.invalidate()
      status.value = null
      loading.value = false
    }
  } finally {
    if (projectsGuard.isCurrent(requestGeneration)) projectsLoading.value = false
  }
}

onMounted(loadProjectsAndSelect)
watch(selectedProjectId, projectId => loadStatus(projectId))
onBeforeUnmount(() => {
  projectsGuard.invalidate()
  statusGuard.invalidate()
})
</script>

<template>
  <div class="binding-reader">
    <n-alert v-if="projectsError" type="error" class="mb-3">
      {{ projectsError }}
      <template #action><n-button size="tiny" @click="loadProjectsAndSelect(true)">重试</n-button></template>
    </n-alert>
    <div v-if="projectOptions.length" class="binding-toolbar">
      <n-select v-model:value="selectedProjectId" :options="projectOptions" placeholder="选择项目查看映射" class="project-select" />
      <n-tag type="info" :bordered="false">M1 只读</n-tag>
    </div>
    <n-empty v-else-if="!projectsLoading && !projectsError" description="没有可查看的项目" class="empty-binding" />
    <n-spin v-if="projectOptions.length" :show="projectsLoading || loading">
      <n-alert v-if="error" type="error" class="mt-3">
        {{ error }}
        <template #action><n-button size="tiny" @click="loadStatus(selectedProjectId)">重试</n-button></template>
      </n-alert>
      <n-empty v-else-if="selectedProjectId && !items.length" description="当前项目没有可用模型映射" class="empty-binding" />
      <div v-else-if="items.length" class="binding-grid">
        <div v-for="item in items" :key="item.taskKey" class="binding-row">
          <span>{{ taskLabels[item.taskKey] || item.taskKey }}</span>
          <strong>{{ item.provider?.name || 'Provider 不可用' }}</strong>
          <small>{{ item.provider?.model || '未记录模型' }}</small>
        </div>
      </div>
    </n-spin>
  </div>
</template>

<style scoped>
.binding-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.project-select { width: min(320px, 100%); }
.binding-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(210px, 1fr)); gap: 9px; margin-top: 14px; }
.binding-row { display: grid; gap: 2px; padding: 11px 12px; border: 1px solid #e3dac8; border-radius: 8px; background: #fffdf8; }
.binding-row span { color: #817667; font-size: 12px; }
.binding-row strong { color: #37322b; font-size: 13px; }
.binding-row small { color: #9a8e7c; }
.empty-binding { padding: 22px 0; }
</style>

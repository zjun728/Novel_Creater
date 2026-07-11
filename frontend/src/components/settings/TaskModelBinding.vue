<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NSelect, NSpin, NTag } from 'naive-ui'
import { useProjectStore } from '@/stores/projectStore'
import { useProviderStore } from '@/stores/providerStore'

const projectStore = useProjectStore()
const providerStore = useProviderStore()
const selectedProjectId = ref('')
const status = ref(null)
const loading = ref(false)
const error = ref('')

const taskLabels = {
  seed: '种子与选题', planning: '滚动规划', writing: '正文写作', audit: '质量审核',
  summary: '章节摘要', extraction: '状态提取', polish: '修订润色', market: '市场选题',
}
const projectOptions = computed(() => projectStore.projects.map(project => ({ label: project.title, value: project.id })))
const items = computed(() => status.value?.items || [])

async function loadStatus() {
  if (!selectedProjectId.value) {
    status.value = null
    return
  }
  loading.value = true
  error.value = ''
  try {
    status.value = await providerStore.getBindingStatus(selectedProjectId.value, { force: true })
  } catch (loadError) {
    error.value = loadError.message || '模型映射加载失败'
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  if (!projectStore.projects.length) await projectStore.loadProjects()
  selectedProjectId.value = projectStore.currentProject?.id || projectStore.projects[0]?.id || ''
})
watch(selectedProjectId, loadStatus)
</script>

<template>
  <div class="binding-reader">
    <div class="binding-toolbar">
      <n-select v-model:value="selectedProjectId" :options="projectOptions" placeholder="选择项目查看映射" class="project-select" />
      <n-tag type="info" :bordered="false">M1 只读</n-tag>
    </div>
    <n-spin :show="loading">
      <n-alert v-if="error" type="error" class="mt-3">
        {{ error }}
        <template #action><n-button size="tiny" @click="loadStatus">重试</n-button></template>
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


<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { NAlert, NButton, NForm, NFormItem, NSelect, NSpace } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useProviderStore } from '@/stores/providerStore'
import { useProjectStore } from '@/stores/projectStore'

const providerStore = useProviderStore()
const projectStore = useProjectStore()
const message = useAppMessage()

const LAST_BINDING_PROJECT_KEY = 'novel_creator_last_binding_project_id'

const bindings = ref(providerStore.emptyBindings())
const selectedProjectId = ref(null)
const loadingBindings = ref(false)
const saving = ref(false)

const projectOptions = computed(() => {
  return projectStore.projects.map(project => ({
    label: project.title || '未命名项目',
    value: project.id
  }))
})

const providerOptions = computed(() => {
  return providerStore.providers.map(p => ({
    label: `${p.name} (${p.model})`,
    value: p.id
  }))
})

function readLastProjectId() {
  try {
    return window.localStorage.getItem(LAST_BINDING_PROJECT_KEY)
  } catch {
    return null
  }
}

function writeLastProjectId(projectId) {
  try {
    if (projectId) window.localStorage.setItem(LAST_BINDING_PROJECT_KEY, projectId)
  } catch {
    // localStorage 可能被浏览器隐私策略禁用，忽略即可。
  }
}

function pickInitialProjectId() {
  const currentId = projectStore.currentProject?.id
  if (currentId) return currentId

  const lastId = readLastProjectId()
  if (lastId && projectStore.projects.some(project => project.id === lastId)) return lastId

  return projectStore.projects[0]?.id || null
}

const taskLabels = {
  writingModelId: '正文创作',
  brainstormModelId: '脑洞发散',
  outlineModelId: '大纲规划',
  auditModelId: '审稿检查',
  summaryModelId: '摘要压缩',
  extractionModelId: '结构化提取',
  marketModelId: '选题分析',
  polishModelId: '润色改写'
}

async function loadProjectBindings(projectId) {
  if (!projectId) {
    bindings.value = providerStore.emptyBindings()
    return
  }

  loadingBindings.value = true
  try {
    const existing = await providerStore.getBindings(projectId)
    bindings.value = providerStore.normalizeBindings(existing)
    writeLastProjectId(projectId)
  } catch (e) {
    message.error('加载模型映射失败：' + e.message)
  } finally {
    loadingBindings.value = false
  }
}

onMounted(async () => {
  await Promise.all([
    providerStore.ensureProvidersLoaded(),
    projectStore.projects.length ? Promise.resolve() : projectStore.loadProjects()
  ])
  selectedProjectId.value = pickInitialProjectId()
  await loadProjectBindings(selectedProjectId.value)
})

watch(() => projectStore.currentProject?.id, async (newId) => {
  if (!newId) return
  selectedProjectId.value = newId
  await loadProjectBindings(newId)
})

watch(selectedProjectId, async (newId, oldId) => {
  if (newId === oldId) return
  await loadProjectBindings(newId)
})

async function handleSave() {
  if (!selectedProjectId.value) {
    message.warning('请先选择一个项目')
    return
  }
  saving.value = true
  try {
    await providerStore.saveBindings(selectedProjectId.value, bindings.value)
    message.success('任务模型映射保存成功')
  } catch (e) {
    message.error('保存失败：' + e.message)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div>
    <p class="text-sm text-gray-500 mb-4">
      为不同创作任务分配不同的 AI 模型。先在上方添加 Provider，然后在此处进行映射。
    </p>

    <n-alert type="info" class="mb-4" :show-icon="false">
      模型映射按项目保存。刷新设置页后会自动恢复上次配置的项目。
    </n-alert>

    <n-form v-if="providerStore.providers.length > 0 && projectOptions.length > 0">
      <n-form-item label="当前配置项目">
        <n-select
          v-model:value="selectedProjectId"
          :options="projectOptions"
          placeholder="选择要配置的项目"
          filterable
        />
      </n-form-item>

      <div class="grid grid-cols-2 gap-4">
        <n-form-item v-for="(label, key) in taskLabels" :key="key" :label="label">
          <n-select
            v-model:value="bindings[key]"
            :options="providerOptions"
            placeholder="选择模型"
            clearable
            :loading="loadingBindings"
            :disabled="!selectedProjectId"
          />
        </n-form-item>
      </div>
      <n-space justify="end">
        <n-button type="primary" :loading="saving" :disabled="!selectedProjectId" @click="handleSave">保存映射</n-button>
      </n-space>
    </n-form>

    <p v-else-if="providerStore.providers.length === 0" class="text-sm text-gray-400">
      暂无可用 Provider，请先在上方添加 AI 模型配置。
    </p>

    <p v-else class="text-sm text-gray-400">
      暂无项目，请先创建项目后再配置任务模型映射。
    </p>
  </div>
</template>


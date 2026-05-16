<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { NButton, NForm, NFormItem, NSelect, NSpace, useMessage } from 'naive-ui'
import { useProviderStore } from '@/stores/providerStore'
import { useProjectStore } from '@/stores/projectStore'

const providerStore = useProviderStore()
const projectStore = useProjectStore()
const message = useMessage()

const bindings = ref({
  writingModelId: null,
  brainstormModelId: null,
  outlineModelId: null,
  auditModelId: null,
  summaryModelId: null,
  extractionModelId: null,
  marketModelId: null,
  polishModelId: null
})

const saving = ref(false)

const providerOptions = computed(() => {
  return providerStore.providers.map(p => ({
    label: `${p.name} (${p.model})`,
    value: p.id
  }))
})

onMounted(async () => {
  if (projectStore.currentProject) {
    const existing = await providerStore.getBindings(projectStore.currentProject.id)
    if (existing) {
      bindings.value = { ...bindings.value, ...existing }
    }
  }
})

watch(() => projectStore.currentProject?.id, async (newId) => {
  if (newId) {
    const existing = await providerStore.getBindings(newId)
    if (existing) {
      bindings.value = { ...bindings.value, ...existing }
    } else {
      bindings.value = {
        writingModelId: null,
        brainstormModelId: null,
        outlineModelId: null,
        auditModelId: null,
        summaryModelId: null,
        extractionModelId: null,
        marketModelId: null,
        polishModelId: null
      }
    }
  }
})

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

async function handleSave() {
  if (!projectStore.currentProject) {
    message.warning('请先打开一个项目')
    return
  }
  saving.value = true
  try {
    await providerStore.saveBindings(projectStore.currentProject.id, bindings.value)
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

    <n-form v-if="providerStore.providers.length > 0">
      <div class="grid grid-cols-2 gap-4">
        <n-form-item v-for="(label, key) in taskLabels" :key="key" :label="label">
          <n-select
            v-model:value="bindings[key]"
            :options="providerOptions"
            placeholder="选择模型"
            clearable
          />
        </n-form-item>
      </div>
      <n-space justify="end">
        <n-button type="primary" :loading="saving" @click="handleSave">保存映射</n-button>
      </n-space>
    </n-form>

    <p v-else class="text-sm text-gray-400">
      暂无可用 Provider，请先在上方添加 AI 模型配置。
    </p>
  </div>
</template>

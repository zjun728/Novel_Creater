<script setup>
import { onMounted, ref } from 'vue'
import { NButton, NCard, NEmpty, NModal, NSpace, NTag, useDialog, NAlert, NInput, NSelect, NForm, NFormItem, NSwitch, NInputNumber, NIcon } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useProviderStore } from '@/stores/providerStore'
import { testConnection } from '@/api/ai'
import ProviderForm from './ProviderForm.vue'
import TaskModelBinding from './TaskModelBinding.vue'

const providerStore = useProviderStore()
const message = useAppMessage()
const dialog = useDialog()

const showForm = ref(false)
const editingProvider = ref(null)
const testingId = ref(null)
const testResults = ref({})

onMounted(async () => {
  await providerStore.loadProviders()
})

function openNew() {
  editingProvider.value = null
  showForm.value = true
}

function openEdit(provider) {
  editingProvider.value = { ...provider }
  showForm.value = true
}

async function handleSave(formData) {
  try {
    if (editingProvider.value?.id) {
      await providerStore.updateProvider({ ...editingProvider.value, ...formData })
      message.success('更新成功')
    } else {
      await providerStore.addProvider(formData)
      message.success('添加成功')
    }
    showForm.value = false
    editingProvider.value = null
  } catch (e) {
    message.error('保存失败：' + e.message)
  }
}

function handleDelete(provider) {
  dialog.warning({
    title: '确认删除',
    content: `确定要删除配置「${provider.name}」吗？`,
    positiveText: '确认',
    negativeText: '取消',
    onPositiveClick: async () => {
      await providerStore.deleteProvider(provider.id)
      message.success('已删除')
    }
  })
}

async function handleTest(provider) {
  testingId.value = provider.id
  testResults.value[provider.id] = { status: 'testing', message: '测试中...' }
  try {
    const result = await testConnection(provider)
    if (result.ok) {
      testResults.value[provider.id] = { status: 'success', message: '连接成功 ✓' }
      message.success(`${provider.name} 连接成功`)
    } else {
      testResults.value[provider.id] = { status: 'error', message: result.error || '连接失败' }
      message.error(`${provider.name} 连接失败`)
    }
  } catch (e) {
    testResults.value[provider.id] = { status: 'error', message: e.message }
    message.error(`${provider.name} 测试出错：${e.message}`)
  } finally {
    testingId.value = null
  }
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-4">
      <h3 class="text-lg font-semibold text-gray-800">AI Provider 配置</h3>
      <n-button type="primary" size="small" @click="openNew">新增 Provider</n-button>
    </div>

    <n-alert type="warning" class="mb-4">
      <template #header>API Key 安全提示</template>
      API Key 保存在本地 MySQL 数据库中。AI 请求从浏览器直连供应商，不经过后端代理。
    </n-alert>

    <n-empty v-if="providerStore.providers.length === 0" description="还没有配置 AI Provider" class="py-8" />

    <n-card
      v-for="provider in providerStore.providers"
      :key="provider.id"
      :title="provider.name"
      size="small"
      class="mb-3"
    >
      <template #header-extra>
        <n-tag :type="provider.providerType === 'anthropic' ? 'info' : 'default'" size="small">
          {{ provider.providerType }}
        </n-tag>
      </template>

      <div class="grid grid-cols-2 gap-2 text-sm mb-3">
        <div><span class="text-gray-400">模型：</span>{{ provider.model }}</div>
        <div><span class="text-gray-400">Base URL：</span>{{ provider.baseURL || '(默认)' }}</div>
        <div><span class="text-gray-400">流式：</span>{{ provider.stream ? '是' : '否' }}</div>
        <div><span class="text-gray-400">Temperature：</span>{{ provider.temperature }}</div>
      </div>

      <div v-if="testResults[provider.id]" class="mb-3">
        <n-tag
          :type="testResults[provider.id].status === 'success' ? 'success' : testResults[provider.id].status === 'testing' ? 'info' : 'error'"
          size="small"
        >
          {{ testResults[provider.id].message }}
        </n-tag>
      </div>

      <template #footer>
        <n-space justify="end">
          <n-button
            size="tiny"
            :loading="testingId === provider.id"
            :disabled="testingId === provider.id"
            @click="handleTest(provider)"
          >
            测试连接
          </n-button>
          <n-button size="tiny" @click="openEdit(provider)">编辑</n-button>
          <n-button size="tiny" type="error" quaternary @click="handleDelete(provider)">删除</n-button>
        </n-space>
      </template>
    </n-card>

    <!-- Provider 表单弹窗 -->
    <n-modal v-model:show="showForm" title="Provider 配置" preset="card" style="width: 600px">
      <ProviderForm :initial="editingProvider" @save="handleSave" @cancel="showForm = false" />
    </n-modal>

    <!-- 分隔线 -->
    <n-card title="任务模型映射" size="small" class="mt-6">
      <TaskModelBinding />
    </n-card>
  </div>
</template>


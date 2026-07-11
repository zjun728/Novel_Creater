<script setup>
import { onMounted, ref } from 'vue'
import { NAlert, NButton, NCard, NEmpty, NModal, NSpace, NTag, useDialog } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useProviderStore } from '@/stores/providerStore'
import ProviderForm from './ProviderForm.vue'
import TaskModelBinding from './TaskModelBinding.vue'

const providerStore = useProviderStore()
const message = useAppMessage()
const dialog = useDialog()
const showForm = ref(false)
const editingProvider = ref(null)
const loadError = ref('')

async function loadProviders() {
  loadError.value = ''
  try {
    await providerStore.loadProviders()
  } catch (error) {
    loadError.value = error.message || 'Provider 配置加载失败'
  }
}

onMounted(loadProviders)

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
      message.success('Provider 配置已更新')
    } else {
      await providerStore.addProvider(formData)
      message.success('Provider 配置已添加')
    }
    showForm.value = false
    editingProvider.value = null
  } catch (error) {
    message.error(`保存失败：${error.message}`)
  }
}

function handleDelete(provider) {
  dialog.warning({
    title: '确认删除',
    content: `确定删除「${provider.name}」吗？已有绑定会因此失效。`,
    positiveText: '删除',
    negativeText: '取消',
    onPositiveClick: async () => {
      await providerStore.deleteProvider(provider.id)
      message.success('Provider 已删除')
    },
  })
}
</script>

<template>
  <section class="provider-settings" aria-labelledby="provider-heading">
    <header class="section-heading">
      <div>
        <p class="eyebrow">本机模型档案</p>
        <h3 id="provider-heading">AI Provider 配置</h3>
      </div>
      <n-button type="primary" size="small" @click="openNew">新增 Provider</n-button>
    </header>

    <n-alert type="info" :bordered="false" class="mb-4">
      M1 只管理本机配置，不调用模型。密钥与真实 Base URL 始终留在后端，浏览器只显示是否已配置。
    </n-alert>
    <n-alert v-if="loadError" type="error" class="mb-4">
      {{ loadError }}
      <template #action><n-button size="tiny" @click="loadProviders">重试</n-button></template>
    </n-alert>

    <n-empty v-if="!providerStore.loading && !providerStore.providers.length" description="还没有 Provider 配置" class="empty-state" />
    <div v-else class="provider-list">
      <n-card v-for="provider in providerStore.providers" :key="provider.id" size="small" class="provider-card">
        <template #header>
          <div class="provider-title">
            <span>{{ provider.name }}</span>
            <n-tag size="small" :type="provider.enabled ? 'success' : 'default'">
              {{ provider.enabled ? '已启用' : '已停用' }}
            </n-tag>
          </div>
        </template>
        <div class="provider-meta">
          <div><span>模型</span><strong>{{ provider.model || '未填写' }}</strong></div>
          <div><span>类型</span><strong>{{ provider.providerType }}</strong></div>
          <div><span>API Key</span><strong>{{ provider.hasKey ? '已配置' : '未配置' }}</strong></div>
          <div><span>Base URL</span><strong>{{ provider.hasBaseURL ? '已配置' : '未配置' }}</strong></div>
        </div>
        <template #footer>
          <n-space justify="end">
            <n-button size="tiny" @click="openEdit(provider)">编辑</n-button>
            <n-button size="tiny" type="error" quaternary @click="handleDelete(provider)">删除</n-button>
          </n-space>
        </template>
      </n-card>
    </div>

    <n-card title="任务模型映射 · 只读" size="small" class="binding-card">
      <TaskModelBinding />
    </n-card>

    <n-modal v-model:show="showForm" preset="card" :title="editingProvider ? '编辑 Provider' : '新增 Provider'" style="width: min(640px, 94vw)">
      <ProviderForm :initial="editingProvider" @save="handleSave" @cancel="showForm = false" />
    </n-modal>
  </section>
</template>

<style scoped>
.provider-settings { color: #302d28; }
.section-heading { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin-bottom: 16px; }
.section-heading h3 { margin: 2px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 21px; }
.eyebrow { margin: 0; color: #8b6f47; font-size: 11px; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }
.provider-list { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
.provider-card { border-color: #dfd6c4; background: #fffdf8; }
.provider-title { display: flex; align-items: center; justify-content: space-between; gap: 12px; font-weight: 700; }
.provider-meta { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 18px; }
.provider-meta div { display: flex; flex-direction: column; gap: 2px; }
.provider-meta span { color: #81786b; font-size: 12px; }
.provider-meta strong { color: #38332c; font-size: 13px; font-weight: 600; }
.binding-card { margin-top: 20px; border-color: #dfd6c4; background: #faf7ef; }
.empty-state { padding: 30px 0; }
</style>


<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
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
const saving = ref(false)
const deletingId = ref('')
const formEpoch = ref(0)
const bindingRefreshKey = ref(0)
const bindingOperationBusy = ref(false)
const bindingDirty = ref(false)
const operationInFlight = computed(() => (
  saving.value
  || Boolean(deletingId.value)
  || providerStore.bindingSaving
  || bindingOperationBusy.value
))
const hasPendingChanges = computed(() => showForm.value || bindingDirty.value)
const providerActionBusy = computed(() => operationInFlight.value || bindingDirty.value)

async function loadProviders() {
  loadError.value = ''
  try {
    await providerStore.loadProviders()
  } catch (error) {
    loadError.value = error.message || 'Provider 配置加载失败'
  }
}

function handleBeforeUnload(event) {
  if (!hasPendingChanges.value && !operationInFlight.value) return
  event.preventDefault()
  event.returnValue = ''
}

function confirmRouteLeave() {
  if (operationInFlight.value) {
    message.warning('操作正在提交或核验，请等待结果明确后再离开设置页。')
    return false
  }
  if (!hasPendingChanges.value) return true
  if (typeof window === 'undefined') return false
  return window.confirm('当前有未保存的 Provider 表单或八项模型绑定。放弃这些修改并离开吗？')
}

onBeforeRouteLeave(() => confirmRouteLeave())
onMounted(() => {
  if (typeof window !== 'undefined') window.addEventListener('beforeunload', handleBeforeUnload)
  loadProviders()
})
onBeforeUnmount(() => {
  if (typeof window !== 'undefined') window.removeEventListener('beforeunload', handleBeforeUnload)
})

function openNew() {
  if (providerActionBusy.value) return
  editingProvider.value = null
  formEpoch.value += 1
  showForm.value = true
}

function openEdit(provider) {
  if (providerActionBusy.value) return
  editingProvider.value = { ...provider }
  formEpoch.value += 1
  showForm.value = true
}

function setFormVisibility(value) {
  if (!value && saving.value) return
  showForm.value = value
  if (!value) {
    editingProvider.value = null
    formEpoch.value += 1
  }
}

async function handleSave(formData) {
  if (providerActionBusy.value) return
  saving.value = true
  let saved = false
  try {
    if (editingProvider.value?.id) {
      await providerStore.updateProvider({ ...editingProvider.value, ...formData })
      message.success('Provider 配置已更新')
    } else {
      await providerStore.addProvider(formData)
      message.success('Provider 配置已添加')
    }
    bindingRefreshKey.value += 1
    saved = true
  } catch (error) {
    message.error(`保存失败：${error.message}`)
  } finally {
    saving.value = false
  }
  if (saved) setFormVisibility(false)
}

function handleDelete(provider) {
  if (providerActionBusy.value) return
  dialog.warning({
    title: '停用并清除私密配置',
    content: `此操作会软删除「${provider.name}」，服务端同时擦除 API Key 与 Base URL。引用它的项目绑定会变为不 Ready，需要重新选择 Provider。`,
    positiveText: '停用并清除',
    negativeText: '取消',
    onPositiveClick: async () => {
      if (deletingId.value) return false
      deletingId.value = provider.id
      try {
        await providerStore.deleteProvider(provider.id)
        bindingRefreshKey.value += 1
        message.success('Provider 已停用，私密配置已由服务端清除')
      } catch (error) {
        message.error(`停用失败：${error.message}`)
        return false
      } finally {
        deletingId.value = ''
      }
      return true
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
      <n-button type="primary" size="small" :disabled="providerActionBusy" @click="openNew">新增 Provider</n-button>
    </header>

    <n-alert type="info" :bordered="false" class="mb-4">
      浏览器只保留公开摘要与“是否已配置”标记；API Key 和 Base URL 不会出现在任何响应、列表或编辑回显中。
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
            <n-button size="tiny" :disabled="providerActionBusy" @click="openEdit(provider)">编辑</n-button>
            <n-button
              size="tiny"
              type="error"
              quaternary
              :loading="deletingId === provider.id"
              :disabled="providerActionBusy"
              @click="handleDelete(provider)"
            >停用并清除私密配置</n-button>
          </n-space>
        </template>
      </n-card>
    </div>

    <n-card title="项目任务模型绑定" size="small" class="binding-card">
      <TaskModelBinding
        :key="bindingRefreshKey"
        @busy-change="bindingOperationBusy = $event"
        @dirty-change="bindingDirty = $event"
      />
    </n-card>

    <n-modal
      :show="showForm"
      preset="card"
      :title="editingProvider ? '编辑 Provider' : '新增 Provider'"
      :mask-closable="!saving"
      :close-on-esc="!saving"
      :closable="!saving"
      style="width: min(640px, 94vw)"
      @update:show="setFormVisibility"
    >
      <ProviderForm
        :key="formEpoch"
        :initial="editingProvider"
        :saving="saving"
        @save="handleSave"
        @cancel="setFormVisibility(false)"
      />
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

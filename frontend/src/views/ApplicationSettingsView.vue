<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NSelect,
  NSpin,
  NTag,
} from 'naive-ui'

import { useAppMessage } from '@/composables/useAppMessage'
import { useApplicationSettingsStore } from '@/stores/applicationSettingsStore'
import { useProviderStore } from '@/stores/providerStore'


const applicationStore = useApplicationSettingsStore()
const providerStore = useProviderStore()
const message = useAppMessage()
const selectedFallback = ref(null)
const loadError = ref('')
const diagnosticsError = ref('')

const providerOptions = computed(() => {
  const options = providerStore.availableProviders.map(provider => ({
    label: `${provider.name} · ${provider.model}`,
    value: provider.id,
  }))
  const current = applicationStore.settings?.fallbackProvider
  if (
    current
    && !options.some(option => option.value === current.id)
  ) {
    options.unshift({
      label: `${current.name} · ${current.model}（当前不可用）`,
      value: current.id,
      disabled: true,
    })
  }
  return options
})
const settingsChanged = computed(
  () => (
    selectedFallback.value ?? null
  ) !== (
    applicationStore.settings?.fallbackProvider?.id ?? null
  ),
)

const diagnosticRows = computed(() => {
  const diagnostics = applicationStore.diagnostics
  if (!diagnostics) return []
  return [
    {
      key: 'schema',
      label: 'Schema manifest',
      value: diagnostics.schemaVersion,
      ready: diagnostics.schemaManifestMatch,
      state: diagnostics.schemaManifestMatch ? '匹配' : '不匹配',
    },
    {
      key: 'database',
      label: '数据库可达性',
      value: 'MySQL',
      ready: diagnostics.databaseReachable,
      state: diagnostics.databaseReachable ? '可达' : '不可达',
    },
    {
      key: 'corpus',
      label: '应用管理语料库',
      value: 'Managed corpus store',
      ready: diagnostics.managedCorpusStoreReady,
      state: diagnostics.managedCorpusStoreReady ? '就绪' : '未就绪',
    },
    {
      key: 'scheduler',
      label: '计划调度器',
      value: diagnostics.schedulerState,
      ready: diagnostics.schedulerEnabled,
      state: diagnostics.schedulerEnabled ? '已启用' : '未启用',
    },
    {
      key: 'version',
      label: '应用版本',
      value: diagnostics.applicationVersion,
      ready: true,
      state: '当前',
    },
  ]
})


watch(
  () => applicationStore.settings,
  settings => {
    selectedFallback.value = settings?.fallbackProvider?.id ?? null
  },
  { immediate: true },
)


async function loadSettings() {
  loadError.value = ''
  try {
    await Promise.all([
      providerStore.loadProviders(false),
      applicationStore.loadSettings(),
    ])
  } catch (failure) {
    loadError.value = failure.message || '应用默认设置加载失败'
  }
}


async function loadDiagnostics() {
  diagnosticsError.value = ''
  try {
    await applicationStore.loadDiagnostics()
  } catch (failure) {
    diagnosticsError.value = failure.message || '本机诊断加载失败'
  }
}


async function saveFallback() {
  if (!applicationStore.settings || applicationStore.saving) return
  try {
    await applicationStore.updateFallback(selectedFallback.value)
    message.success('新项目 fallback 模型已更新')
  } catch (failure) {
    message.error(failure.message || '默认模型保存失败')
  }
}


onMounted(() => {
  void loadSettings()
  void loadDiagnostics()
})
</script>

<template>
  <main class="application-route">
    <header class="route-heading">
      <p>LOCAL APPLICATION CONTROL</p>
      <h1>应用默认与诊断</h1>
      <span>只决定新项目在没有可继承 Ready 快照时使用的 fallback；最近 Ready 项目继承规则始终固定。</span>
      <nav aria-label="设置页面">
        <router-link to="/settings/providers">Provider 档案</router-link>
        <router-link to="/settings/application" aria-current="page">应用默认与诊断</router-link>
      </nav>
    </header>

    <section class="settings-grid">
      <article class="settings-sheet fallback-sheet">
        <div class="section-title">
          <div>
            <p>NEW PROJECT FALLBACK</p>
            <h2>新项目 fallback 模型</h2>
          </div>
          <n-tag
            v-if="applicationStore.settings?.fallbackProvider"
            :type="applicationStore.settings.fallbackProvider.ready ? 'success' : 'warning'"
          >
            {{ applicationStore.settings.fallbackProvider.ready ? 'Ready' : 'Not Ready' }}
          </n-tag>
        </div>

        <n-alert type="info" :bordered="false">
          新项目先继承最近的完整 Ready 项目快照；只有没有可继承快照时才读取这里。
        </n-alert>
        <n-alert v-if="loadError" type="error" class="state-alert">
          {{ loadError }}
          <template #action>
            <n-button size="small" @click="loadSettings">重试</n-button>
          </template>
        </n-alert>

        <n-spin :show="applicationStore.loading">
          <label class="fallback-field">
            <span>明确 fallback Provider / 模型</span>
            <n-select
              :value="selectedFallback"
              :options="providerOptions"
              :disabled="applicationStore.saving || !applicationStore.settings"
              clearable
              filterable
              placeholder="不指定；届时使用稳定顺序的第一个 Ready Provider"
              @update:value="selectedFallback = $event ?? null"
            />
            <small>列表只包含后端确认 Ready 的公开 Provider 名称和模型名。</small>
          </label>
          <footer class="sheet-actions">
            <span>settings revision {{ applicationStore.settings?.revision ?? '—' }}</span>
            <n-button
              type="primary"
              :loading="applicationStore.saving"
              :disabled="!settingsChanged || applicationStore.saving"
              @click="saveFallback"
            >
              保存 fallback
            </n-button>
          </footer>
        </n-spin>
      </article>

      <article class="settings-sheet diagnostics-sheet">
        <div class="section-title">
          <div>
            <p>SAFE DIAGNOSTICS</p>
            <h2>本机运行诊断</h2>
          </div>
          <n-button
            size="small"
            :loading="applicationStore.diagnosticsLoading"
            @click="loadDiagnostics"
          >
            刷新
          </n-button>
        </div>
        <p class="privacy-note">
          诊断只显示能力状态，不显示数据库地址、账号、DSN、文件路径、Provider 配置或异常正文。
        </p>
        <n-alert v-if="diagnosticsError" type="error" class="state-alert">
          {{ diagnosticsError }}
        </n-alert>
        <n-spin :show="applicationStore.diagnosticsLoading">
          <dl class="diagnostic-list">
            <div v-for="row in diagnosticRows" :key="row.key">
              <dt>
                <span>{{ row.label }}</span>
                <small>{{ row.value }}</small>
              </dt>
              <dd>
                <n-tag :type="row.ready ? 'success' : 'warning'" size="small">
                  {{ row.state }}
                </n-tag>
              </dd>
            </div>
          </dl>
        </n-spin>
      </article>
    </section>
  </main>
</template>

<style scoped>
.application-route { min-height: 100%; padding: clamp(22px, 4vw, 48px); color: #302a23; background: #f4efe4; }
.route-heading, .settings-grid { width: min(1120px, 100%); margin-inline: auto; }
.route-heading { padding-bottom: 24px; border-bottom: 1px solid #d4c7b2; }
.route-heading > p, .section-title p { margin: 0; color: #9a3f32; font: 700 10px Georgia, serif; letter-spacing: .17em; }
.route-heading h1 { margin: 8px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: clamp(32px, 5vw, 50px); font-weight: 600; }
.route-heading > span { display: block; max-width: 70ch; margin-top: 10px; color: #766c60; line-height: 1.7; }
.route-heading nav { display: flex; gap: 8px; margin-top: 18px; }
.route-heading nav a { padding: 7px 12px; border: 1px solid #d5c7b1; border-radius: 999px; color: #6f6153; font-size: 12px; text-decoration: none; }
.route-heading nav a[aria-current='page'] { border-color: #8f3d32; color: #7d3128; background: #efe2d3; }
.settings-grid { display: grid; grid-template-columns: minmax(0, 1.08fr) minmax(340px, .92fr); gap: 20px; margin-top: 24px; }
.settings-sheet { padding: clamp(18px, 3vw, 30px); border: 1px solid #d8cbb7; border-radius: 14px; background: #fffdf8; box-shadow: 0 20px 56px rgba(58, 43, 27, .06); }
.section-title { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.section-title h2 { margin: 5px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 23px; }
.fallback-field { display: grid; gap: 8px; margin-top: 22px; }
.fallback-field > span { color: #5f5448; font-size: 12px; font-weight: 750; }
.fallback-field small, .privacy-note { color: #85796a; font-size: 11px; line-height: 1.65; }
.sheet-actions { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-top: 24px; padding-top: 17px; border-top: 1px solid #e1d5c2; }
.sheet-actions span { color: #8a7d6d; font: 11px Georgia, serif; }
.privacy-note { margin: -4px 0 18px; }
.diagnostic-list { display: grid; gap: 0; margin: 0; }
.diagnostic-list > div { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 13px 0; border-top: 1px solid #e8dfd0; }
.diagnostic-list dt { display: grid; gap: 3px; }
.diagnostic-list dt span { font-size: 13px; font-weight: 700; }
.diagnostic-list dt small { color: #8a7d6d; font: 11px Georgia, serif; }
.diagnostic-list dd { margin: 0; }
.state-alert { margin: 14px 0; }
@media (max-width: 860px) {
  .settings-grid { grid-template-columns: 1fr; }
  .route-heading nav { flex-wrap: wrap; }
}
</style>

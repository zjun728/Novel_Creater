<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NSelect,
  NSpin,
  NTag,
} from 'naive-ui'

import { useRouter } from 'vue-router'
import { useAppMessage } from '@/composables/useAppMessage'
import { useApplicationSettingsStore } from '@/stores/applicationSettingsStore'
import { useProviderStore } from '@/stores/providerStore'


const router = useRouter()
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
      label: '资料结构',
      value: diagnostics.schemaVersion,
      ready: diagnostics.schemaManifestMatch,
      state: diagnostics.schemaManifestMatch ? '匹配' : '不匹配',
    },
    {
      key: 'database',
      label: '资料读取',
      value: 'MySQL',
      ready: diagnostics.databaseReachable,
      state: diagnostics.databaseReachable ? '可达' : '不可达',
    },
    {
      key: 'corpus',
      label: '语料读取',
      value: 'Managed corpus store',
      ready: diagnostics.managedCorpusStoreReady,
      state: diagnostics.managedCorpusStoreReady ? '就绪' : '未就绪',
    },
    {
      key: 'scheduler',
      label: '计划任务',
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
  if (!settingsChanged.value) { void router.push('/settings/providers'); return }
  try {
    await applicationStore.updateFallback(selectedFallback.value)
    message.success('新作品备用模型已更新')
    void router.push('/settings/providers')
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
  <section class="application-route">
    <header class="route-heading">

      <h1>应用默认与诊断</h1>
      <span>管理新作品的备用模型，查看本机运行状态。</span>
      <nav aria-label="设置页面">
        <router-link to="/settings/providers">服务商与模型</router-link>
        <router-link to="/settings/application" aria-current="page">应用默认与诊断</router-link>
      </nav>
    </header>

    <section class="settings-grid">
      <article class="settings-sheet fallback-sheet">
        <div class="section-title">
          <div>

            <h2>新作品备用模型</h2>
          </div>
          <n-tag
            v-if="applicationStore.settings?.fallbackProvider"
            :type="applicationStore.settings.fallbackProvider.ready ? 'success' : 'warning'"
          >
            {{ applicationStore.settings.fallbackProvider.ready ? '可用' : '不可用' }}
          </n-tag>
        </div>

        <n-alert type="info" :bordered="false">
          新作品优先继承最近一个配置完整可用的项目。没有可继承配置时，才使用这里的备用模型。
        </n-alert>
        <n-alert v-if="loadError" type="error" class="state-alert">
          {{ loadError }}
          <div class="alert-actions">
            <n-button size="small" @click="loadSettings">重试</n-button>
          </div>
        </n-alert>

        <n-spin :show="applicationStore.loading">
          <label class="fallback-field">
            <span>备用模型服务</span>
            <n-select
              :value="selectedFallback"
              :options="providerOptions"
              :disabled="applicationStore.saving || !applicationStore.settings"
              clearable
              filterable
              placeholder="不指定；使用首个可用服务"
              @update:value="selectedFallback = $event ?? null"
            />
            <small>列表显示当前可用的模型服务。</small>
          </label>

        </n-spin>
      </article>

      <article class="settings-sheet diagnostics-sheet">
        <div class="section-title">
          <div>

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
                <small v-if="row.key === 'version'">{{ row.value }}</small>
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
          <footer class="sheet-actions">
            <span>用于之后创建的新作品</span>
            <n-button
              type="primary"
              :loading="applicationStore.saving"
              :disabled="!applicationStore.settings || applicationStore.saving"
              @click="saveFallback"
            >
              保存并返回
            </n-button>
          </footer>
  </section>
</template>

<style scoped>
.application-route { min-height: 100%; padding: 24px 36px; color: #302a23; background: var(--nc-canvas); }
.route-heading, .settings-grid { width: min(1120px, 100%); margin-inline: auto; }
.route-heading { padding-bottom: 24px; border-bottom: 1px solid #d4c7b2; }
.route-heading > p, .section-title p { margin: 0; color: #9a3f32; font: 700 10px Georgia, serif; letter-spacing: .17em; }
.route-heading h1 { margin: 8px 0 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 30px; font-weight: 600; }
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
.sheet-actions{max-width:1120px;margin:24px auto 0;padding:18px 24px;background:var(--nc-paper)}
</style>

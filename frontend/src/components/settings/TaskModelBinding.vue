<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NSelect, NSpin, NTag } from 'naive-ui'
import { useProjectStore } from '@/stores/projectStore'
import { TASK_KEYS, useProviderStore } from '@/stores/providerStore'
import { createLatestRequestGuard } from '@/utils/latestRequest'

const projectStore = useProjectStore()
const providerStore = useProviderStore()
const emit = defineEmits(['busy-change', 'dirty-change'])
const selectedProjectId = ref('')
const binding = ref(null)
const status = ref(null)
const draftBindings = ref(Object.fromEntries(TASK_KEYS.map(taskKey => [taskKey, null])))
const loading = ref(false)
const error = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const requiresReload = ref(false)
const statusSaving = ref(false)
const projectsLoading = ref(false)
const projectsError = ref('')
const providersError = ref('')
const snapshotGuard = createLatestRequestGuard()
const projectsGuard = createLatestRequestGuard()
const saveGuard = createLatestRequestGuard()

const taskLabels = {
  seed: '种子与选题', planning: '滚动规划', writing: '正文写作', audit: '质量审核',
  summary: '章节摘要', extraction: '状态提取', polish: '修订润色', market: '市场选题',
}

const projectOptions = computed(() => projectStore.projects.map(project => ({
  label: project.title,
  value: project.id,
})))
const providerOptions = computed(() => providerStore.availableProviders.map(provider => ({
  label: `${provider.name} · ${provider.model}`,
  value: provider.id,
})))
const statusItems = computed(() => Object.fromEntries(
  (status.value?.items || []).map(item => [item.taskKey, item]),
))
const bindingComplete = computed(() => status.value?.bindingComplete === true)
const bindingReasons = computed(() => Array.isArray(status.value?.reasons) ? status.value.reasons : [])
const bindingReady = computed(() => status.value?.bindingReady === true && bindingReasons.value.length === 0)
const isSaving = computed(() => statusSaving.value || providerStore.bindingSaving)

const baselineBindings = computed(() => Object.fromEntries(TASK_KEYS.map(taskKey => {
  const item = binding.value?.items?.find(candidate => candidate.taskKey === taskKey)
  return [taskKey, item?.providerId ?? null]
})))
const hasChanges = computed(() => Boolean(binding.value) && TASK_KEYS.some(
  taskKey => (draftBindings.value[taskKey] ?? null) !== baselineBindings.value[taskKey],
))

function hydrateDraft(snapshot) {
  const byTask = new Map((snapshot?.items || []).map(item => [item.taskKey, item.providerId ?? null]))
  draftBindings.value = Object.fromEntries(TASK_KEYS.map(taskKey => [taskKey, byTask.get(taskKey) ?? null]))
}

function reasonDetail(reason) {
  const [code, taskKey] = String(reason || '').split(':', 2)
  const task = taskLabels[taskKey] || taskKey || '对应任务'
  const messages = {
    binding_incomplete: ['八项记录不完整', '重新加载后补齐全部八项，再整体保存。'],
    task_unbound: [`${task}尚未绑定`, '为这一项选择可用 Provider；也可保留未绑定，但项目不会 Ready。'],
    provider_unavailable: [`${task}的 Provider 不可用`, '检查 Provider 是否启用且已配置密钥和 Base URL，然后重新绑定。'],
    model_snapshot_mismatch: [`${task}的模型快照已变化`, '重新选择当前 Provider 并整体保存，冻结新的模型快照。'],
  }
  const [title, guidance] = messages[code] || ['后端判定绑定不可用', '按原因代码检查项目绑定后重新保存。']
  return { code: String(reason), title, guidance }
}

const reasonDetails = computed(() => bindingReasons.value.map(reasonDetail))

function updateBinding(taskKey, providerId) {
  if (isSaving.value || requiresReload.value) return
  draftBindings.value = { ...draftBindings.value, [taskKey]: providerId ?? null }
  saveError.value = ''
  saveSuccess.value = ''
}

function confirmDiscard() {
  if (!hasChanges.value) return true
  if (typeof window === 'undefined') return false
  return window.confirm('当前项目有尚未保存的八项绑定修改。放弃这些修改并继续吗？')
}

function requestProjectChange(projectId) {
  if (isSaving.value || projectId === selectedProjectId.value || !confirmDiscard()) return
  selectedProjectId.value = projectId
}

function reloadCurrent() {
  if (isSaving.value || !confirmDiscard()) return
  loadProject(selectedProjectId.value)
}

function handleBeforeUnload(event) {
  if (!hasChanges.value && !isSaving.value) return
  event.preventDefault()
  event.returnValue = ''
}

async function loadProject(projectId = selectedProjectId.value) {
  if (isSaving.value) return
  const requestGeneration = snapshotGuard.begin()
  saveGuard.invalidate()
  error.value = ''
  saveError.value = ''
  saveSuccess.value = ''
  requiresReload.value = false
  binding.value = null
  status.value = null
  hydrateDraft(null)
  if (!projectId) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const [nextBinding, nextStatus] = await Promise.all([
      providerStore.getBindings(projectId, { force: true }),
      providerStore.getBindingStatus(projectId, { force: true }),
    ])
    if (!snapshotGuard.isCurrent(requestGeneration) || selectedProjectId.value !== projectId) return
    binding.value = nextBinding
    status.value = nextStatus
    hydrateDraft(nextBinding)
  } catch (loadError) {
    if (snapshotGuard.isCurrent(requestGeneration)) {
      error.value = loadError.message || '模型绑定加载失败'
    }
  } finally {
    if (snapshotGuard.isCurrent(requestGeneration)) loading.value = false
  }
}

async function saveBindings() {
  if (!binding.value || loading.value || isSaving.value || requiresReload.value) return
  const projectId = selectedProjectId.value
  const requestGeneration = saveGuard.begin()
  statusSaving.value = true
  saveError.value = ''
  saveSuccess.value = ''
  let writeCompleted = false
  try {
    const saved = await providerStore.replaceBindings(projectId, {
      expectedRevision: binding.value.revision,
      entries: TASK_KEYS.map(taskKey => ({
        taskKey,
        providerId: draftBindings.value[taskKey] ?? null,
      })),
    })
    writeCompleted = true
    if (!saveGuard.isCurrent(requestGeneration) || selectedProjectId.value !== projectId) return
    binding.value = saved
    hydrateDraft(saved)
    const nextStatus = await providerStore.getBindingStatus(projectId, { force: true })
    if (!saveGuard.isCurrent(requestGeneration) || selectedProjectId.value !== projectId) return
    status.value = nextStatus
    saveSuccess.value = nextStatus.bindingReady
      ? '八项绑定已保存，后端确认当前项目 Ready。'
      : '八项绑定已保存；请按后端原因继续补齐，当前项目尚未 Ready。'
  } catch (saveFailure) {
    if (!saveGuard.isCurrent(requestGeneration)) return
    if (writeCompleted) {
      requiresReload.value = true
      saveError.value = '八项绑定已经保存，但最新 Ready 状态核验失败。请重新加载项目绑定，不要重复提交。'
    } else if (saveFailure?.status === 409) {
      requiresReload.value = true
      saveError.value = '绑定版本已经变化，系统没有覆盖新版本。请重新加载后再编辑。'
    } else {
      saveError.value = saveFailure.message || '模型绑定保存失败'
    }
  } finally {
    if (saveGuard.isCurrent(requestGeneration)) statusSaving.value = false
  }
}

async function loadProjectsAndProviders(force = false) {
  const requestGeneration = projectsGuard.begin()
  projectsLoading.value = true
  projectsError.value = ''
  providersError.value = ''
  const providerLoad = providerStore.loadProviders(force).catch(loadError => {
    if (projectsGuard.isCurrent(requestGeneration)) {
      providersError.value = loadError.message || 'Provider 公开摘要加载失败'
    }
  })
  try {
    if (force || !projectStore.projects.length) await projectStore.loadProjects()
    await providerLoad
    if (!projectsGuard.isCurrent(requestGeneration)) return
    const currentSelection = selectedProjectId.value
    const selectionStillExists = projectStore.projects.some(project => project.id === currentSelection)
    const nextProjectId = selectionStillExists
      ? currentSelection
      : (projectStore.currentProject?.id || projectStore.projects[0]?.id || '')
    if (nextProjectId !== currentSelection && currentSelection && !confirmDiscard()) return
    selectedProjectId.value = nextProjectId
    if (!nextProjectId) {
      snapshotGuard.invalidate()
      binding.value = null
      status.value = null
      loading.value = false
    }
  } catch (loadError) {
    if (projectsGuard.isCurrent(requestGeneration)) {
      projectsError.value = loadError.message || '项目列表加载失败'
      if (!selectedProjectId.value) {
        snapshotGuard.invalidate()
        binding.value = null
        status.value = null
        loading.value = false
      }
    }
    await providerLoad
  } finally {
    if (projectsGuard.isCurrent(requestGeneration)) projectsLoading.value = false
  }
}

onMounted(() => {
  if (typeof window !== 'undefined') window.addEventListener('beforeunload', handleBeforeUnload)
  loadProjectsAndProviders()
})
watch(selectedProjectId, projectId => loadProject(projectId))
watch(isSaving, value => emit('busy-change', value), { immediate: true })
watch(hasChanges, value => emit('dirty-change', value), { immediate: true })
onBeforeUnmount(() => {
  projectsGuard.invalidate()
  snapshotGuard.invalidate()
  saveGuard.invalidate()
  emit('busy-change', false)
  emit('dirty-change', false)
  if (typeof window !== 'undefined') window.removeEventListener('beforeunload', handleBeforeUnload)
})
</script>

<template>
  <section class="binding-ledger" aria-labelledby="binding-ledger-heading">
    <header class="ledger-heading">
      <div>
        <p class="folio">模型签押 · 八项同版</p>
        <h4 id="binding-ledger-heading">一次保存八项绑定</h4>
        <p>Complete 只表示八个任务都有记录（允许明确未绑定）；Ready 才表示八项都解析到当前可用模型。</p>
      </div>
      <div class="status-seals" aria-live="polite">
        <n-tag :type="bindingComplete ? 'success' : 'warning'" round>
          {{ bindingComplete ? 'Complete · 八项完整' : 'Incomplete · 记录不全' }}
        </n-tag>
        <n-tag :type="bindingReady ? 'success' : 'warning'" round>
          {{ bindingReady ? 'Ready · 可用于生成' : 'Not Ready · 暂不可生成' }}
        </n-tag>
      </div>
    </header>

    <n-alert v-if="projectsError" type="error" class="state-alert">
      {{ projectsError }}
      <template #action><n-button size="small" @click="loadProjectsAndProviders(true)">重试</n-button></template>
    </n-alert>
    <n-alert v-if="providersError" type="warning" class="state-alert">
      {{ providersError }}。当前不能选择 Provider，可稍后重新加载。
      <template #action><n-button size="small" @click="loadProjectsAndProviders(true)">重新加载</n-button></template>
    </n-alert>

    <div v-if="projectOptions.length" class="binding-toolbar">
      <label>
        <span>当前项目</span>
        <n-select
          :value="selectedProjectId"
          :options="projectOptions"
          :disabled="isSaving"
          placeholder="选择项目"
          @update:value="requestProjectChange"
        />
      </label>
      <p>切换项目会重新读取该项目的绑定修订，不沿用浏览器本地状态。</p>
    </div>

    <n-empty v-else-if="!projectsLoading && !projectsError" description="没有可配置的项目" class="empty-binding" />

    <n-spin v-if="projectOptions.length" :show="projectsLoading || loading">
      <n-alert v-if="error" type="error" class="state-alert">
        {{ error }}
        <template #action><n-button size="small" :disabled="isSaving" @click="reloadCurrent">重新加载</n-button></template>
      </n-alert>

      <template v-else-if="binding">
        <n-alert v-if="!providerOptions.length" type="warning" class="state-alert">
          没有可绑定的 Provider。请先启用一个已配置 API Key 与 Base URL 的 Provider。
        </n-alert>

        <div class="binding-grid">
          <article v-for="(taskKey, index) in TASK_KEYS" :key="taskKey" class="binding-row">
            <div class="task-number">{{ String(index + 1).padStart(2, '0') }}</div>
            <div class="task-copy">
              <strong>{{ taskLabels[taskKey] }}</strong>
              <small v-if="statusItems[taskKey]?.providerNameSnapshot">
                当前快照：{{ statusItems[taskKey].providerNameSnapshot }} · {{ statusItems[taskKey].modelNameSnapshot }}
              </small>
              <small v-else>当前快照：明确未绑定</small>
            </div>
            <n-select
              :value="draftBindings[taskKey]"
              :options="providerOptions"
              :disabled="loading || isSaving || requiresReload"
              clearable
              filterable
              placeholder="明确未绑定"
              @update:value="value => updateBinding(taskKey, value)"
            />
            <n-tag
              size="small"
              :type="statusItems[taskKey]?.resolutionStatus === 'bound' ? 'success' : 'default'"
              :bordered="false"
            >
              {{ statusItems[taskKey]?.resolutionStatus === 'bound' ? '已绑定' : '未绑定' }}
            </n-tag>
          </article>
        </div>

        <section v-if="reasonDetails.length" class="reason-sheet" aria-label="后端 Ready 判定原因">
          <header><strong>后端判定原因</strong><span>保存成功不等于 Ready</span></header>
          <ul>
            <li v-for="reason in reasonDetails" :key="reason.code">
              <div><strong>{{ reason.title }}</strong><code>{{ reason.code }}</code></div>
              <p>{{ reason.guidance }}</p>
            </li>
          </ul>
        </section>

        <n-alert v-if="saveError" type="error" class="state-alert" aria-live="assertive">
          {{ saveError }}
          <template v-if="requiresReload" #action>
            <n-button size="small" :disabled="isSaving" @click="reloadCurrent">重新加载项目绑定</n-button>
          </template>
        </n-alert>
        <n-alert v-if="saveSuccess" :type="bindingReady ? 'success' : 'info'" class="state-alert" aria-live="polite">
          {{ saveSuccess }}
        </n-alert>

        <footer class="ledger-actions">
          <div>
            <strong>原子替换</strong>
            <p>点击一次只发送一条 CAS 请求；未绑定项以 null 明确保存。</p>
          </div>
          <n-button
            type="primary"
            size="large"
            :loading="isSaving"
            :disabled="loading || isSaving || requiresReload || (!hasChanges && bindingReady)"
            @click="saveBindings"
          >{{ hasChanges ? '保存全部八项' : '重新签押当前八项' }}</n-button>
        </footer>
      </template>
    </n-spin>
  </section>
</template>

<style scoped>
.binding-ledger { color: #302d28; }
.ledger-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 22px; padding: 4px 2px 18px; border-bottom: 1px solid #d8ccb7; }
.ledger-heading h4 { margin: 3px 0 7px; color: #302b25; font-family: Georgia, 'Noto Serif SC', serif; font-size: 21px; font-weight: 700; }
.ledger-heading p { max-width: 680px; margin: 0; color: #786f62; font-size: 13px; line-height: 1.7; }
.folio { color: #8c6b3f !important; font-size: 10px !important; font-weight: 800; letter-spacing: .18em; text-transform: uppercase; }
.status-seals { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; padding-top: 4px; }
.binding-toolbar { display: grid; grid-template-columns: minmax(240px, 360px) 1fr; align-items: end; gap: 22px; margin: 18px 0; padding: 15px 17px; border: 1px solid #ded3bf; border-radius: 4px; background: #f7f1e5; }
.binding-toolbar label { display: grid; gap: 7px; }
.binding-toolbar label > span { color: #685d4f; font-size: 12px; font-weight: 700; }
.binding-toolbar p { margin: 0 0 5px; color: #897e6f; font-size: 12px; line-height: 1.6; }
.binding-grid { display: grid; gap: 1px; overflow: hidden; border: 1px solid #ddd1bb; border-radius: 5px; background: #ddd1bb; }
.binding-row { display: grid; grid-template-columns: 40px minmax(180px, .8fr) minmax(240px, 1fr) auto; align-items: center; gap: 14px; padding: 14px 16px; background: linear-gradient(90deg, #fffdf8, #fbf7ee); }
.task-number { color: #ad8a58; font-family: Georgia, serif; font-size: 13px; }
.task-copy { display: grid; gap: 4px; min-width: 0; }
.task-copy strong { color: #383128; font-family: Georgia, 'Noto Serif SC', serif; font-size: 14px; }
.task-copy small { overflow: hidden; color: #8a7d6c; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.reason-sheet { margin-top: 16px; padding: 16px 18px; border-left: 3px solid #a87c42; background: #f7f0e3; }
.reason-sheet header { display: flex; justify-content: space-between; gap: 12px; color: #594b39; }
.reason-sheet header span { color: #947d60; font-size: 11px; }
.reason-sheet ul { display: grid; gap: 10px; margin: 13px 0 0; padding: 0; list-style: none; }
.reason-sheet li { padding-top: 10px; border-top: 1px solid #e1d4bf; }
.reason-sheet li > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.reason-sheet code { color: #8d6740; font-size: 10px; }
.reason-sheet p { margin: 4px 0 0; color: #756a5d; font-size: 12px; line-height: 1.55; }
.state-alert { margin: 14px 0; }
.ledger-actions { display: flex; align-items: flex-end; justify-content: space-between; gap: 20px; margin-top: 18px; padding-top: 17px; border-top: 1px solid #d8ccb7; }
.ledger-actions strong { font-family: Georgia, 'Noto Serif SC', serif; font-size: 13px; }
.ledger-actions p { margin: 4px 0 0; color: #8a7d6d; font-size: 11px; }
.empty-binding { padding: 30px 0; }
@media (max-width: 800px) {
  .ledger-heading, .ledger-actions { align-items: stretch; flex-direction: column; }
  .status-seals { justify-content: flex-start; }
  .binding-toolbar { grid-template-columns: 1fr; }
  .binding-row { grid-template-columns: 32px 1fr auto; }
  .binding-row :deep(.n-select) { grid-column: 2 / -1; }
}
</style>

<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
} from 'vue'
import {
  NAlert,
  NButton,
  NSelect,
  NSpin,
  NTag,
} from 'naive-ui'

import {
  TASK_KEYS,
  useModelBindingStore,
} from '@/stores/modelBindingStore'
import { useProviderStore } from '@/stores/providerStore'
import { createLatestRequestGuard } from '@/utils/latestRequest'


const props = defineProps({
  projectId: {
    type: String,
    required: true,
  },
  readonly: {
    type: Boolean,
    default: false,
  },
})
const emit = defineEmits(['busy-change', 'dirty-change', 'saved', 'cancel'])
const providerStore = useProviderStore()
const modelBindingStore = useModelBindingStore()
const binding = ref(null)
const status = ref(null)
const draftBindings = ref(
  Object.fromEntries(TASK_KEYS.map(taskKey => [taskKey, null])),
)
const advanced = ref(false)
const loading = ref(false)
const error = ref('')
const saveError = ref('')
const saveSuccess = ref('')
const requiresReload = ref(false)
const savingStatus = ref(false)
const snapshotGuard = createLatestRequestGuard()
const saveGuard = createLatestRequestGuard()

const taskLabels = {
  market: '市场选题',
  seed: '种子与故事发动机',
  planning: '创作规划',
  writing: '正文写作',
  polish: '改写润色',
  audit: '质量审核',
  extraction: '定稿提取',
  summary: '上下文压缩',
}

const providerOptions = computed(
  () => providerStore.availableProviders.map(provider => ({
    label: `${provider.name} · ${provider.model}`,
    value: provider.id,
  })),
)
const statusItems = computed(() => Object.fromEntries(
  (status.value?.items || []).map(item => [item.taskKey, item]),
))
const bindingComplete = computed(
  () => status.value?.bindingComplete === true,
)
const bindingReasons = computed(
  () => Array.isArray(status.value?.reasons) ? status.value.reasons : [],
)
const bindingReady = computed(
  () => status.value?.bindingReady === true
    && bindingReasons.value.length === 0,
)
const isSaving = computed(
  () => savingStatus.value || modelBindingStore.bindingSaving,
)
const baselineBindings = computed(() => Object.fromEntries(
  TASK_KEYS.map(taskKey => {
    const item = binding.value?.items?.find(
      candidate => candidate.taskKey === taskKey,
    )
    return [taskKey, item?.providerId ?? null]
  }),
))
const hasChanges = computed(
  () => Boolean(binding.value) && TASK_KEYS.some(
    taskKey => (
      draftBindings.value[taskKey] ?? null
    ) !== baselineBindings.value[taskKey],
  ),
)
const simpleProviderIds = computed(
  () => new Set(TASK_KEYS.map(
    taskKey => draftBindings.value[taskKey] ?? null,
  )),
)
const simpleProviderId = computed(
  () => simpleProviderIds.value.size === 1
    ? [...simpleProviderIds.value][0]
    : undefined,
)
const mixedAdvancedSelection = computed(
  () => simpleProviderIds.value.size > 1,
)
const sourceDescription = computed(() => (
  binding.value?.sourceProjectId
    ? '已继承其他项目的模型配置，可按创作任务调整。'
    : '为规划、正文和其他创作任务选择模型。'
))


function hydrateDraft(snapshot) {
  const byTask = new Map(
    (snapshot?.items || []).map(
      item => [item.taskKey, item.providerId ?? null],
    ),
  )
  draftBindings.value = Object.fromEntries(
    TASK_KEYS.map(taskKey => [taskKey, byTask.get(taskKey) ?? null]),
  )
}


function applyAll(providerId) {
  if (props.readonly || isSaving.value || requiresReload.value) return
  draftBindings.value = Object.fromEntries(
    TASK_KEYS.map(taskKey => [taskKey, providerId ?? null]),
  )
  saveError.value = ''
  saveSuccess.value = ''
}


function updateBinding(taskKey, providerId) {
  if (props.readonly || isSaving.value || requiresReload.value) return
  draftBindings.value = {
    ...draftBindings.value,
    [taskKey]: providerId ?? null,
  }
  saveError.value = ''
  saveSuccess.value = ''
}


function reasonDetail(reason) {
  const [code, taskKey] = String(reason || '').split(':', 2)
  const task = taskLabels[taskKey] || taskKey || '对应任务'
  const messages = {
    binding_incomplete: ['任务配置不完整', '请重新加载配置。'],
    task_unbound: [`${task}尚未绑定`, '选择可用模型服务后保存配置。'],
    provider_unavailable: [`${task}的模型服务不可用`, '请检查服务连接，再保存配置。'],
    model_snapshot_mismatch: [`${task}的模型快照已变化`, '重新保存以冻结当前模型身份。'],
  }
  const [title, guidance] = messages[code]
    || ['后端判定绑定不可用', '按原因代码恢复后重新加载。']
  return { code: String(reason), title, guidance }
}


const reasonDetails = computed(
  () => bindingReasons.value.map(reasonDetail),
)


async function loadSnapshot() {
  const projectId = props.projectId
  const generation = snapshotGuard.begin()
  saveGuard.invalidate()
  loading.value = true
  error.value = ''
  saveError.value = ''
  saveSuccess.value = ''
  requiresReload.value = false
  binding.value = null
  status.value = null
  hydrateDraft(null)
  try {
    await providerStore.loadProviders(false)
    const nextStatus = await modelBindingStore.getBindingStatus(
      projectId,
      { force: true },
    )
    if (
      !snapshotGuard.isCurrent(generation)
      || props.projectId !== projectId
    ) return
    binding.value = nextStatus
    status.value = nextStatus
    hydrateDraft(nextStatus)
  } catch (failure) {
    if (snapshotGuard.isCurrent(generation)) {
      error.value = failure.message || '模型绑定加载失败'
    }
  } finally {
    if (snapshotGuard.isCurrent(generation)) loading.value = false
  }
}


async function saveBindings() {
  if (
    props.readonly
    || !binding.value
    || loading.value
    || isSaving.value
    || requiresReload.value
  ) return
  if (!hasChanges.value && bindingReady.value) { emit('saved'); return }
  const projectId = props.projectId
  const generation = saveGuard.begin()
  savingStatus.value = true
  saveError.value = ''
  saveSuccess.value = ''
  let writeCompleted = false
  let returnAfterSave = false
  try {
    const saved = await modelBindingStore.replaceBindings(projectId, {
      expectedRevision: binding.value.revision,
      entries: TASK_KEYS.map(taskKey => ({
        taskKey,
        providerId: draftBindings.value[taskKey] ?? null,
      })),
    })
    writeCompleted = true
    if (
      !saveGuard.isCurrent(generation)
      || props.projectId !== projectId
    ) return
    binding.value = saved
    hydrateDraft(saved)
    const nextStatus = await modelBindingStore.getBindingStatus(
      projectId,
      { force: true },
    )
    if (
      !saveGuard.isCurrent(generation)
      || props.projectId !== projectId
    ) return
    const changedAfterSave = (
      nextStatus.revision !== saved.revision
      || nextStatus.contentHash !== saved.contentHash
    )
    binding.value = nextStatus
    status.value = nextStatus
    hydrateDraft(nextStatus)
    if (changedAfterSave) {
      saveError.value = '保存后绑定又发生了变化；已加载服务器上的最新完整快照。'
    } else {
      saveSuccess.value = nextStatus.bindingReady
        ? '模型配置已保存，可以开始创作。'
        : '模型配置已保存；仍有任务需要配置可用服务。'
      if (nextStatus.bindingReady) returnAfterSave = true
    }
  } catch (failure) {
    if (!saveGuard.isCurrent(generation)) return
    if (writeCompleted) {
      requiresReload.value = true
      saveError.value = '配置已保存，但可用状态暂未确认。请重新加载，不要重复提交。'
    } else if (failure?.status === 409) {
      requiresReload.value = true
      saveError.value = '配置已被更新。请重新加载后再编辑。'
    } else {
      saveError.value = failure.message || '模型绑定保存失败'
    }
  } finally {
    if (saveGuard.isCurrent(generation)) {
      savingStatus.value = false
      if (returnAfterSave) { await nextTick(); emit('saved') }
    }
  }
}


function handleBeforeUnload(event) {
  if (!hasChanges.value && !isSaving.value) return
  event.preventDefault()
  event.returnValue = ''
}


watch(
  () => props.projectId,
  () => void loadSnapshot(),
)
watch(isSaving, value => emit('busy-change', value), { immediate: true })
watch(hasChanges, value => emit('dirty-change', value), { immediate: true })
onMounted(() => {
  globalThis.window?.addEventListener?.('beforeunload', handleBeforeUnload)
  void loadSnapshot()
})
onBeforeUnmount(() => {
  snapshotGuard.invalidate()
  saveGuard.invalidate()
  emit('busy-change', false)
  emit('dirty-change', false)
  globalThis.window?.removeEventListener?.('beforeunload', handleBeforeUnload)
})
</script>

<template>
  <section class="binding-ledger" aria-labelledby="binding-ledger-heading">
    <header class="ledger-heading">
      <div>

        <h2 id="binding-ledger-heading">创作使用的模型</h2>
        <p>{{ sourceDescription }}</p>
      </div>
      <div class="status-seals" aria-live="polite">
        <n-tag :type="bindingComplete ? 'success' : 'warning'" round>
          {{ bindingComplete ? '配置完整' : '配置未完成' }}
        </n-tag>
        <n-tag :type="bindingReady ? 'success' : 'warning'" round>
          {{ bindingReady ? '连接可用' : '连接待恢复' }}
        </n-tag>
      </div>
    </header>

    <n-alert v-if="readonly" type="warning" class="state-alert">
      已归档项目为只读状态。你可以查看绑定快照与原因，但不能保存修改。
    </n-alert>
    <n-alert v-if="error" type="error" class="state-alert">
      {{ error }}
      <div class="alert-actions">
        <n-button size="small" @click="loadSnapshot">重新加载</n-button>
      </div>
    </n-alert>

    <n-spin :show="loading">
      <template v-if="binding">
        <section class="simple-binding" aria-label="全部任务统一模型">
          <div>
            <span>模型服务</span>
            <strong>项目默认模型</strong>
            <p v-if="mixedAdvancedSelection">
              当前八项使用不同模型；选择后会统一覆盖草稿。
            </p>
            <p v-else>选择后应用于全部任务；下方可单独调整规划与正文模型。</p>
          </div>
          <n-select
            :value="simpleProviderId"
            :options="providerOptions"
            :disabled="readonly || loading || isSaving || requiresReload"
            clearable
            filterable
            :placeholder="mixedAdvancedSelection ? '已使用高级分配' : '明确未绑定'"
            @update:value="applyAll"
          />
        </section>

        <div class="primary-models">
          <label v-for="taskKey in ['planning', 'writing']" :key="taskKey">
            <span>{{ taskKey === 'planning' ? '规划模型' : '正文模型' }}</span>
            <n-select :value="draftBindings[taskKey]" :options="providerOptions"
              :disabled="readonly || loading || isSaving || requiresReload" clearable filterable
              placeholder="请选择模型" @update:value="value => updateBinding(taskKey, value)" />
          </label>
        </div>
        <h3>其他任务</h3>
        <p class="other-copy">选题、审查、记忆提取等任务可展开分别指定。</p>
        <button
          class="advanced-toggle"
          type="button"
          :aria-expanded="String(advanced)"
          @click="advanced = !advanced"
        >
          <span>{{ advanced ? '收起其他任务' : '展开其他任务配置' }}</span>
          <span aria-hidden="true">{{ advanced ? '−' : '+' }}</span>
        </button>

        <div v-if="advanced" class="binding-grid">
          <article
            v-for="(taskKey, index) in TASK_KEYS.filter(key => !['planning', 'writing'].includes(key))"
            :key="taskKey"
            class="binding-row"
          >
            <span class="task-number">{{ String(index + 1).padStart(2, '0') }}</span>
            <div class="task-copy">
              <strong>{{ taskLabels[taskKey] }}</strong>
              <small v-if="statusItems[taskKey]?.providerNameSnapshot">
                {{ statusItems[taskKey].providerNameSnapshot }}
                · {{ statusItems[taskKey].modelNameSnapshot }}
              </small>
              <small v-else>当前快照：明确未绑定</small>
            </div>
            <n-select
              :value="draftBindings[taskKey]"
              :options="providerOptions"
              :disabled="readonly || loading || isSaving || requiresReload"
              clearable
              filterable
              placeholder="明确未绑定"
              @update:value="value => updateBinding(taskKey, value)"
            />
          </article>
        </div>

        <section
          v-if="reasonDetails.length"
          class="reason-sheet"
          aria-label="模型连接状态"
        >
          <header>
            <strong>待处理的配置</strong>
            <span>以后端实时判定为准</span>
          </header>
          <ul>
            <li v-for="reason in reasonDetails" :key="reason.code">
              <div>
                <strong>{{ reason.title }}</strong>

              </div>
              <p>{{ reason.guidance }}</p>
            </li>
          </ul>
        </section>

        <n-alert
          v-if="saveError"
          type="error"
          class="state-alert"
          aria-live="assertive"
        >
          {{ saveError }}
          <div v-if="requiresReload" class="alert-actions">
            <n-button size="small" @click="loadSnapshot">重新加载</n-button>
          </div>
        </n-alert>
        <n-alert
          v-if="saveSuccess"
          :type="bindingReady ? 'success' : 'info'"
          class="state-alert"
          aria-live="polite"
        >
          {{ saveSuccess }}
        </n-alert>

        <p class="other-copy">密钥仅在服务设置中管理，不出现在作品内容中。</p>
        <router-link :to="{ path: '/settings/providers', query: { projectId } }">管理服务商与模型</router-link>
        <footer class="ledger-actions">
          <div>
            <strong>配置适用于后续请求</strong>
            <p>历史创作结果不受影响。</p>
          </div>
          <n-button :disabled="isSaving || loading" @click="emit('cancel')">取消</n-button>
          <n-button
            type="primary"
            size="large"
            :loading="isSaving"
            :disabled="
              readonly
              || loading
              || isSaving
              || requiresReload
            "
            @click="saveBindings"
          >
            保存配置并返回
          </n-button>
        </footer>
      </template>
    </n-spin>
  </section>
</template>

<style scoped>
.primary-models{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin:28px 0}.primary-models label{display:grid;gap:10px;color:var(--nc-muted);font-size:13px}.other-copy{color:var(--nc-muted);font-size:13px;line-height:1.8}.binding-ledger a{color:var(--nc-vermilion)}.ledger-actions>div{margin-right:auto}@media(max-width:700px){.primary-models{grid-template-columns:1fr}}

.binding-ledger { color: #302d28; }
.ledger-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 22px; padding-bottom: 20px; border-bottom: 1px solid #d8ccb7; }
.ledger-heading h2 { margin: 3px 0 7px; color: #302b25; font-family: Georgia, 'Noto Serif SC', serif; font-size: 25px; font-weight: 650; }
.ledger-heading p { max-width: 680px; margin: 0; color: #786f62; font-size: 13px; line-height: 1.7; }
.folio { color: #8f3d32 !important; font-size: 10px !important; font-weight: 800; letter-spacing: .18em; }
.status-seals { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; padding-top: 4px; }
.simple-binding { display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 420px); align-items: center; gap: 28px; margin-top: 20px; padding: 22px; border: 1px solid #d9c8ad; border-radius: 8px; background: linear-gradient(120deg, #fffdf8, #f4ead9); }
.simple-binding div { display: grid; gap: 5px; }
.simple-binding span { color: #99644d; font-size: 10px; font-weight: 800; letter-spacing: .12em; }
.simple-binding strong { font-family: Georgia, 'Noto Serif SC', serif; font-size: 18px; }
.simple-binding p { margin: 0; color: #807466; font-size: 12px; line-height: 1.6; }
.advanced-toggle { display: flex; width: 100%; align-items: center; justify-content: space-between; margin-top: 14px; padding: 12px 4px; border: 0; border-bottom: 1px solid #ddd1bb; color: #684b38; background: transparent; cursor: pointer; font: 700 13px Georgia, 'Noto Serif SC', serif; }
.advanced-toggle:focus-visible { outline: 3px solid rgba(143, 61, 50, .22); outline-offset: 2px; }
.binding-grid { display: grid; gap: 1px; overflow: hidden; margin-top: 12px; border: 1px solid #ddd1bb; border-radius: 5px; background: #ddd1bb; }
.binding-row { display: grid; grid-template-columns: 40px minmax(180px, .8fr) minmax(240px, 1fr); align-items: center; gap: 14px; padding: 14px 16px; background: #fffdf8; }
.task-number { color: #ad8a58; font-family: Georgia, serif; font-size: 13px; }
.task-copy { display: grid; min-width: 0; gap: 4px; }
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
@media (max-width: 800px) {
  .ledger-heading, .ledger-actions { align-items: stretch; flex-direction: column; }
  .status-seals { justify-content: flex-start; }
  .simple-binding { grid-template-columns: 1fr; }
  .binding-row { grid-template-columns: 32px 1fr; }
  .binding-row :deep(.n-select) { grid-column: 2; }
}

.ledger-heading{padding-bottom:12px}.ledger-heading h2{font-size:23px}.simple-binding{margin-top:16px;padding:14px 18px;background:var(--nc-paper)}.primary-models{margin:20px 0}.ledger-actions{position:sticky;bottom:0;background:var(--nc-paper);padding:16px 0;z-index:2}.binding-ledger h3{margin:14px 0 6px}
</style>

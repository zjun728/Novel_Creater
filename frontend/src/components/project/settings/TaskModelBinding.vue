<script setup>
import {
  computed,
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
const emit = defineEmits(['busy-change', 'dirty-change'])
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
    ? `继承自项目 ${binding.value.sourceProjectId} 的完整 Ready 快照；本项目绑定 revision ${binding.value.revision}。`
    : `本项目绑定 revision ${binding.value?.revision ?? '—'}；未继承其他项目快照。`
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
    binding_incomplete: ['八项记录不完整', '重新加载完整快照。'],
    task_unbound: [`${task}尚未绑定`, '选择 Ready Provider 后原子保存全部八项。'],
    provider_unavailable: [`${task}的 Provider 不可用`, '先恢复 Provider，再重新保存完整快照。'],
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
  const projectId = props.projectId
  const generation = saveGuard.begin()
  savingStatus.value = true
  saveError.value = ''
  saveSuccess.value = ''
  let writeCompleted = false
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
        ? '完整八项快照已保存，后端确认 Ready。'
        : '完整八项快照已保存；当前仍有待恢复项。'
    }
  } catch (failure) {
    if (!saveGuard.isCurrent(generation)) return
    if (writeCompleted) {
      requiresReload.value = true
      saveError.value = '快照已保存，但 Ready 核验结果未知。请重新加载，不要重复提交。'
    } else if (failure?.status === 409) {
      requiresReload.value = true
      saveError.value = '绑定 revision 已变化。请重新加载后再编辑。'
    } else {
      saveError.value = failure.message || '模型绑定保存失败'
    }
  } finally {
    if (saveGuard.isCurrent(generation)) savingStatus.value = false
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
        <p class="folio">PROJECT MODEL LEDGER</p>
        <h2 id="binding-ledger-heading">项目模型绑定</h2>
        <p>{{ sourceDescription }}</p>
      </div>
      <div class="status-seals" aria-live="polite">
        <n-tag :type="bindingComplete ? 'success' : 'warning'" round>
          {{ bindingComplete ? 'Complete · 八项完整' : 'Incomplete' }}
        </n-tag>
        <n-tag :type="bindingReady ? 'success' : 'warning'" round>
          {{ bindingReady ? 'Ready · 可调用' : 'Not Ready' }}
        </n-tag>
      </div>
    </header>

    <n-alert v-if="readonly" type="warning" class="state-alert">
      已归档项目为只读状态。你可以查看绑定快照与原因，但不能保存修改。
    </n-alert>
    <n-alert v-if="error" type="error" class="state-alert">
      {{ error }}
      <template #action>
        <n-button size="small" @click="loadSnapshot">重新加载</n-button>
      </template>
    </n-alert>

    <n-spin :show="loading">
      <template v-if="binding">
        <section class="simple-binding" aria-label="全部任务统一模型">
          <div>
            <span>默认 · 应用到全部八项</span>
            <strong>全部任务使用同一模型</strong>
            <p v-if="mixedAdvancedSelection">
              当前八项使用不同模型；选择后会统一覆盖草稿。
            </p>
            <p v-else>一次选择、一次 CAS，原子替换完整八项快照。</p>
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

        <button
          class="advanced-toggle"
          type="button"
          :aria-expanded="String(advanced)"
          @click="advanced = !advanced"
        >
          <span>{{ advanced ? '收起高级设置' : '高级设置 · 分别绑定八项' }}</span>
          <span aria-hidden="true">{{ advanced ? '−' : '+' }}</span>
        </button>

        <div v-if="advanced" class="binding-grid">
          <article
            v-for="(taskKey, index) in TASK_KEYS"
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
          aria-label="后端 Ready 判定原因"
        >
          <header>
            <strong>Readiness 恢复依据</strong>
            <span>以后端实时判定为准</span>
          </header>
          <ul>
            <li v-for="reason in reasonDetails" :key="reason.code">
              <div>
                <strong>{{ reason.title }}</strong>
                <code>{{ reason.code }}</code>
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
          <template v-if="requiresReload" #action>
            <n-button size="small" @click="loadSnapshot">重新加载</n-button>
          </template>
        </n-alert>
        <n-alert
          v-if="saveSuccess"
          :type="bindingReady ? 'success' : 'info'"
          class="state-alert"
          aria-live="polite"
        >
          {{ saveSuccess }}
        </n-alert>

        <footer class="ledger-actions">
          <div>
            <strong>Whole snapshot · revision {{ binding.revision }}</strong>
            <p>保存永远替换全部八项，不进行逐项修补。</p>
          </div>
          <n-button
            type="primary"
            size="large"
            :loading="isSaving"
            :disabled="
              readonly
              || loading
              || isSaving
              || requiresReload
              || (!hasChanges && bindingReady)
            "
            @click="saveBindings"
          >
            {{ hasChanges ? '保存完整八项' : '重新签押当前快照' }}
          </n-button>
        </footer>
      </template>
    </n-spin>
  </section>
</template>

<style scoped>
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
</style>

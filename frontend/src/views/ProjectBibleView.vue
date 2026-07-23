<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { bibleReasonLabel, createBibleWorkspaceController } from '../application/bible/bibleWorkspaceController.js'
import BibleEditor from '../components/bible/BibleEditor.vue'
import BibleHistoryDrawer from '../components/bible/BibleHistoryDrawer.vue'
import { createModalFocusManager } from '../components/common/modalFocusManager.js'
import { useRouteProject } from '../composables/useRouteProject.js'
import { useBibleStore } from '../stores/bibleStore.js'
import { useModelBindingStore } from '../stores/modelBindingStore.js'
import NotFoundView from './NotFoundView.vue'

const routeProject = useRouteProject()
const store = useBibleStore()
const bindingStore = useModelBindingStore()
const notice = ref('')
const authorInstructions = ref('')
const errorTarget = ref(null)
const confirmErrorTarget = ref(null)
const confirmTarget = ref(null)
const confirmDialog = ref(null)
const statusTarget = ref(null)
const teleportEnabled = typeof document !== 'undefined'
const projectId = computed(() => routeProject.project.value?.id || '')
const locked = computed(() => routeProject.state.value === 'archived' || store.readOnly)
const planningBinding = computed(() => (
  bindingStore.bindingStatus?.items?.find(item => item.taskKey === 'planning') || null
))
const planningBlocked = computed(() => (
  (bindingStore.bindingStatus?.reasons || []).some(reason => (
    reason === 'task_unbound:planning'
    || reason === 'provider_unavailable:planning'
    || reason === 'model_snapshot_mismatch:planning'
  ))
))
const planningReady = computed(() => (
  planningBinding.value?.resolutionStatus === 'bound' && !planningBlocked.value
))
const workspace = createBibleWorkspaceController({
  store,
  projectId: () => projectId.value,
  isArchived: () => routeProject.state.value === 'archived',
  planningReady: () => planningReady.value,
  focusError: () => {
    if (confirmOpen.value) confirmErrorTarget.value?.focus()
    else if (!historyOpen.value) errorTarget.value?.focus()
  },
  focusConfirm: () => confirmTarget.value?.focus(),
  focusStatus: () => statusTarget.value?.focus(),
  confirmLeave: () => window.confirm('存在未保存的创作圣经编辑。确定离开吗？'),
})
const { working, confirmOpen, historyOpen, errorSummary, recoveryCommand, busy, mode, activeStatus, editable, canSave, canConfirm, canGenerate, generationDisabledReason, confirmPreview, reasonLabels, cloneSource } = workspace
const editorDisabled = computed(() => busy.value)
const hasConflict = computed(() => errorSummary.value?.status === 409)
const globalError = computed(() => errorSummary.value && !confirmOpen.value && !historyOpen.value ? errorSummary.value : null)
const recoveryLabel = computed(() => ({
  hydrate: '重试加载',
  save: '重试保存',
  confirm: '重试确认',
  history: '重试历史',
  historyDetail: '重试历史详情',
  historyPage: '重试加载更多',
  reconcile: '重新核对当前状态',
  reloadAuthoritative: '重新加载权威版本',
})[recoveryCommand.value?.type] || '重新核对当前状态')
const confirmFocus = createModalFocusManager({
  getDialog: () => confirmDialog.value,
  getInitialFocus: () => confirmTarget.value,
})

async function hydrate() {
  if (!projectId.value) return
  await Promise.all([
    workspace.hydrate(),
    bindingStore.getBindingStatus(projectId.value, { force: true }).catch(() => null),
  ])
}
watch(() => [projectId.value, routeProject.state.value], () => {
  notice.value = ''
  authorInstructions.value = ''
  void hydrate().catch(() => {})
}, { immediate: true })
watch(confirmOpen, async open => {
  if (open) { await nextTick(); confirmFocus.mount() } else confirmFocus.unmount()
})

function edit(value) { workspace.edit(value) }
async function save() {
  try { if (await workspace.save()) notice.value = '草稿已保存' } catch {}
}
async function confirm() {
  try { if (await workspace.confirm()) notice.value = '已确认新的创作圣经修订' } catch {}
}
async function generate() {
  try {
    const attempt = await workspace.generate(authorInstructions.value)
    if (attempt?.status === 'succeeded') {
      notice.value = '已生成新的创作圣经草稿'
    } else if (attempt?.status === 'outcome_unknown') {
      notice.value = '生成结果尚未确认，请重新核对当前状态。'
    }
  } catch {}
}
async function clone(source) {
  try { if (await workspace.clone(source)) { historyOpen.value = false; notice.value = '已创建未来设计草稿' } } catch {}
}
function openHistory() { void workspace.openHistory().catch(() => {}) }
function showHistoryDetail(revision) { void workspace.showHistoryDetail(revision).catch(() => {}) }
function loadMoreHistory() { void workspace.loadMoreHistory().catch(() => {}) }
function confirmHydrateOverwrite() {
  return !store.dirty || window.confirm('重新加载将覆盖本地未保存内容。确定继续吗？')
}
async function retryFailure() {
  const type = recoveryCommand.value?.type
  if (!type) return
  if (['hydrate', 'reconcile', 'reloadAuthoritative'].includes(type) && !confirmHydrateOverwrite()) return
  try {
    const result = await workspace.retryFailure()
    if (result === undefined) return
    if (type === 'save') notice.value = '草稿已保存'
    else if (type === 'confirm') notice.value = '已确认新的创作圣经修订'
    else if (type === 'hydrate' || type === 'reconcile' || type === 'reloadAuthoritative') notice.value = '已重新加载权威版本'
  } catch {}
}
async function reloadAuthoritative() {
  if (!confirmHydrateOverwrite()) return
  try {
    const result = await workspace.hydrate()
    if (result !== undefined) notice.value = '已重新加载权威版本'
  } catch {}
}
function handleConfirmKeydown(event) {
  if (event.key === 'Escape') {
    event.preventDefault()
    if (!busy.value) workspace.closeConfirm()
    return
  }
  confirmFocus.trapTab(event)
}

onBeforeRouteLeave(() => workspace.requestLeave())
onBeforeRouteUpdate(() => workspace.requestLeave())
onMounted(() => window.addEventListener('beforeunload', workspace.beforeUnload))
onBeforeUnmount(() => { window.removeEventListener('beforeunload', workspace.beforeUnload); confirmFocus.unmount() })
</script>

<template>
  <main class="bible-page">
    <section v-if="globalError" ref="errorTarget" class="error-summary" tabindex="-1" role="alert" aria-live="assertive">
      <strong>{{ globalError.message }}</strong>
      <span v-if="globalError.correlationId">参考编号：{{ globalError.correlationId }}</span>
      <button v-if="hasConflict" type="button" @click="reloadAuthoritative">重新加载权威版本</button>
      <button v-else type="button" @click="retryFailure">{{ recoveryLabel }}</button>
    </section>
    <p v-if="notice" class="status-note" aria-live="polite">{{ notice }}</p>
    <section v-if="routeProject.state.value === 'loading'" class="sheet">正在装订创作圣经…</section>
    <not-found-view v-else-if="routeProject.state.value === 'missing'" title="项目不存在" description="无法打开创作圣经。" />
    <section v-else-if="routeProject.state.value === 'error'" class="sheet">项目加载失败。<button @click="routeProject.reload">重试</button></section>
    <section v-else class="sheet" :aria-busy="busy || undefined">
      <div class="workspace-content" :inert="busy || undefined">
        <header><p>CREATION BIBLE · {{ activeStatus || mode.toUpperCase() }}</p><h1 ref="statusTarget" tabindex="-1">{{ routeProject.project.value?.title }} 的创作圣经</h1><button :disabled="busy" @click="openHistory">修订历史</button></header>
        <aside class="ai-status" aria-label="AI 辅助状态">
          AI 辅助：{{ planningReady ? 'Ready' : 'Not Ready' }}（不影响手动保存与确认）
        </aside>
        <p v-for="reason in reasonLabels" :key="reason" class="status-note">{{ reason }}</p>
        <p v-if="mode === 'superseded'" class="status-note">此修订已被替代，内容仅供复制与查阅。</p>
        <p v-if="locked || mode === 'archived'" class="status-note">此项目或当前服务端状态为只读。</p>
        <bible-editor v-if="working" :model-value="working" :read-only="!editable" :disabled="editorDisabled" @update:model-value="edit" />
        <section v-if="editable" class="generation-panel" aria-label="AI 生成创作圣经">
          <label for="bible-author-instructions">作者补充要求（可选）</label>
          <textarea
            id="bible-author-instructions"
            v-model="authorInstructions"
            :disabled="busy"
            maxlength="4000"
            rows="3"
          />
          <button type="button" :disabled="!canGenerate" @click="generate">生成创作圣经</button>
          <p v-if="generationDisabledReason" class="status-note">{{ generationDisabledReason }}</p>
        </section>
        <footer v-if="editable"><button :disabled="!canSave" @click="save">手动保存</button><span v-if="store.dirty">请先保存后再确认</span><button :disabled="!canConfirm" @click="workspace.openConfirm($event.currentTarget)">预览并确认</button></footer>
        <button v-if="cloneSource" :disabled="busy" @click="clone(cloneSource)">调整未来设计</button>
        <Teleport to="body" :disabled="!teleportEnabled">
          <div v-if="confirmOpen" class="confirm-overlay">
            <section ref="confirmDialog" class="confirm-panel" role="dialog" aria-modal="true" aria-label="确认新的未来设计" @keydown="handleConfirmKeydown"><h2>确认新的未来设计</h2><section v-if="errorSummary" ref="confirmErrorTarget" class="modal-error-summary" tabindex="-1" role="alert" aria-live="assertive"><strong>{{ errorSummary.message }}</strong><span v-if="errorSummary.correlationId">参考编号：{{ errorSummary.correlationId }}</span><button v-if="hasConflict" type="button" :disabled="busy" @click="reloadAuthoritative">重新加载权威版本</button><button v-else type="button" :disabled="busy" @click="retryFailure">{{ recoveryLabel }}</button></section><p>确认会创建不可变修订。请核对已保存的完整快照。</p><bible-editor v-if="confirmPreview" :model-value="confirmPreview" read-only :disabled="busy" /><button ref="confirmTarget" @click="confirm">确认签印</button><button :disabled="busy" @click="workspace.closeConfirm">返回编辑</button></section>
          </div>
        </Teleport>
      </div>
      <div v-if="busy" class="busy-overlay" role="status" aria-live="polite" aria-busy="true">正在处理创作圣经…</div>
    </section>
    <bible-history-drawer :history="store.history" :history-next-before-revision="store.historyNextBeforeRevision" :history-detail="store.historyDetail" :open="historyOpen" :read-only="locked" :busy="busy" :error="errorSummary" :retry-label="recoveryLabel" :label-reason="bibleReasonLabel" @close="historyOpen = false" @clone="clone" @detail="showHistoryDetail" @more="loadMoreHistory" @retry="retryFailure" />
  </main>
</template>

<style scoped>
.bible-page { min-height:100%; padding:clamp(18px,4vw,54px); color:var(--nc-ink); background:var(--nc-canvas); }.sheet { position:relative; width:min(960px,100%); margin:auto; padding:clamp(22px,4vw,46px); border:1px solid var(--nc-border); background:repeating-linear-gradient(0deg,var(--nc-paper),var(--nc-paper) 27px,color-mix(in srgb,var(--nc-paper) 94%,var(--nc-canvas)) 28px); box-shadow:0 24px 64px color-mix(in srgb,var(--nc-ink) 11%,transparent); }.sheet header { display:flex; flex-wrap:wrap; align-items:end; gap:12px; border-bottom:2px solid var(--nc-vermilion); padding-bottom:16px; }.sheet header p { width:100%; margin:0; color:var(--nc-vermilion); font:700 11px Georgia,serif; letter-spacing:.16em; }.sheet h1 { flex:1; margin:0; font:600 clamp(30px,5vw,52px) Georgia,'Noto Serif SC',serif; }.sheet button { border:1px solid var(--nc-vermilion); padding:8px 12px; color:var(--nc-vermilion); background:var(--nc-paper); font:650 14px Georgia,'Noto Serif SC',serif; }.sheet footer { display:flex; gap:10px; margin-top:24px; }.status-note,.ai-status { padding:10px; border-left:3px solid var(--nc-vermilion); color:var(--nc-muted); }.ai-status { margin:14px 0; border-color:var(--nc-muted); background:color-mix(in srgb,var(--nc-paper) 92%,var(--nc-canvas)); }.generation-panel { display:grid; gap:8px; margin:16px 0; padding:14px; border:1px solid var(--nc-border); background:color-mix(in srgb,var(--nc-paper) 96%,var(--nc-canvas)); }.generation-panel textarea { resize:vertical; border:1px solid var(--nc-border); padding:10px; color:var(--nc-ink); background:var(--nc-paper); font:inherit; }.generation-panel button { justify-self:start; }.confirm-overlay { position:fixed; z-index:30; inset:0; display:grid; padding:24px; place-items:center; background:color-mix(in srgb,var(--nc-ink) 38%,transparent); }.confirm-panel,.error-summary { padding:18px; border:1px solid var(--nc-vermilion); background:var(--nc-paper); }.confirm-panel { width:min(900px,100%); max-height:calc(100vh - 48px); overflow:auto; color:var(--nc-ink); box-shadow:0 24px 64px color-mix(in srgb,var(--nc-ink) 22%,transparent); }.error-summary,.modal-error-summary { display:grid; gap:8px; color:var(--nc-ink); }.error-summary { width:min(960px,100%); margin:0 auto 12px; }.modal-error-summary { margin:12px 0; padding:12px; border:1px solid var(--nc-vermilion); background:color-mix(in srgb,var(--nc-paper) 92%,var(--nc-canvas)); }.busy-overlay { position:absolute; inset:0; display:grid; place-items:center; color:var(--nc-paper); background:color-mix(in srgb,var(--nc-ink) 55%,transparent); font-weight:700; } @media(max-width:620px){.bible-page{padding:12px}.sheet{padding:20px}.sheet footer{flex-direction:column}}
</style>

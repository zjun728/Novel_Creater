<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'

import { BIBLE_PROPOSAL_SCOPES } from '../application/bible/bibleProposalScopes.js'
import { createBibleWorkspaceController } from '../application/bible/bibleWorkspaceController.js'
import { bibleModeLabel } from '../application/bible/bibleStatusPresentation.js'
import BibleEditor from '../components/bible/BibleEditor.vue'
import BibleHistoryDrawer from '../components/bible/BibleHistoryDrawer.vue'
import BibleProposalReview from '../components/bible/BibleProposalReview.vue'
import FoundationConfirmationDialog from '../components/foundation/FoundationConfirmationDialog.vue'
import FoundationSectionIndex from '../components/foundation/FoundationSectionIndex.vue'
import FoundationStatusRail from '../components/foundation/FoundationStatusRail.vue'
import FoundationWorkspace from '../components/foundation/FoundationWorkspace.vue'
import { useRouteProject } from '../composables/useRouteProject.js'
import { useBibleStore } from '../stores/bibleStore.js'
import { useModelBindingStore } from '../stores/modelBindingStore.js'
import NotFoundView from './NotFoundView.vue'

const routeProject = useRouteProject()
const store = useBibleStore()
const bindingStore = useModelBindingStore()
const notice = ref('')
const authorInstructions = ref('')
const activeSection = ref('premise')
const editingSection = ref('')
const errorTarget = ref(null)
const confirmErrorTarget = ref(null)
const confirmTarget = ref(null)
const historyTrigger = ref(null)
const statusTarget = ref(null)
let historyRestoreTarget = null
const projectId = computed(() => routeProject.project.value?.id || '')
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
  bindingStore.bindingStatusFreshProjectId === projectId.value
  && bindingStore.bindingStatus?.projectId === projectId.value
  && bindingStore.bindingStatusLoading !== true
  && planningBinding.value?.resolutionStatus === 'bound'
  && !planningBlocked.value
))
const workspace = createBibleWorkspaceController({
  store,
  projectId: () => projectId.value,
  isArchived: () => routeProject.state.value === 'archived',
  planningReady: () => planningReady.value,
  focusError: () => {
    if (confirmOpen.value) confirmErrorTarget.value?.focus()
    else if (!historyOpen.value && !proposalOpen.value) errorTarget.value?.focus()
  },
  focusConfirm: () => confirmTarget.value?.focus(),
  focusStatus: () => statusTarget.value?.focus(),
  confirmLeave: () => window.confirm('存在未保存的创作圣经修改。确定离开吗？'),
})
const {
  working, confirmOpen, historyOpen, proposalOpen, proposalSnapshot, errorSummary,
  recoveryCommand, busy, mode, editable, canSave, saveDisabledReason, canConfirm, confirmPreview, reasonLabels,
} = workspace
const documentReadOnly = computed(() => !editable.value)
const modeLabel = computed(() => bibleModeLabel(mode.value))
const hasConflict = computed(() => errorSummary.value?.status === 409)
const globalError = computed(() => errorSummary.value && !confirmOpen.value && !historyOpen.value && !proposalOpen.value ? errorSummary.value : null)
const recoveryLabel = computed(() => ({
  hydrate: '重试加载', save: '重试保存', confirm: '重试确认', history: '重试历史',
  historyDetail: '重试历史详情', historyPage: '重试加载更多', reconcile: '重新核对当前状态',
  reloadAuthoritative: '重新加载权威版本',
})[recoveryCommand.value?.type] || '重新核对当前状态')
const sectionScopes = BIBLE_PROPOSAL_SCOPES.filter(scope => scope.key !== 'whole')
const sectionItems = computed(() => sectionScopes.map(scope => {
  const filled = scope.fields.some(field => Array.isArray(working.value?.[field])
    ? working.value[field].some(item => String(item?.text || '').trim())
    : Boolean(String(working.value?.[field] || '').trim()))
  return {
    key: scope.key,
    label: scope.label,
    targetId: `bible-section-${scope.key}`,
    status: scope.key === activeSection.value ? 'current' : filled ? 'filled' : 'empty',
    statusLabel: scope.key === activeSection.value ? '当前' : filled ? '已填写' : '待补充',
  }
}))
const sourceBasis = computed(() => workspace.activeBasis.value || {})
const draftVersion = computed(() => Number.isSafeInteger(store.draft?.draftVersion) ? store.draft.draftVersion : null)
const hasSavedDraft = computed(() => store.draft?.draft != null && Number(store.draft?.draftVersion || 0) > 0)
const summary = computed(() => ({
  world: working.value?.worldRules?.length || 0,
  cast: working.value?.coreCast?.length || 0,
  factions: working.value?.factions?.length || 0,
  questions: working.value?.openDesignQuestions?.length || 0,
}))
const confirmationAdapter = computed(() => ({
  snapshot: confirmPreview.value,
  draftVersion: draftVersion.value,
  contractBasis: sourceBasis.value,
  canConfirm: Boolean(canConfirm.value),
}))
const proposalScope = computed(() => hasSavedDraft.value ? activeSection.value : 'whole')
const canRequestProposal = computed(() => workspace.canPropose(proposalScope.value))
const proposalActionLabel = computed(() => hasSavedDraft.value ? 'AI 补充/重写本区' : 'AI 生成初稿')
const proposalDisabledReason = computed(() => {
  if (!editable.value) return '当前创作圣经不可编辑。'
  if (!planningReady.value) return '请先为 planning 任务配置可用模型。'
  if (busy.value) return '请等待当前操作完成。'
  if (!canRequestProposal.value && store.dirty) return '请先保存本地编辑，再请求 AI 建议。'
  if (!canRequestProposal.value) return '请先保存完整草稿，再请求本区 AI 建议。'
  return ''
})

async function hydrate() {
  if (!projectId.value) return
  await Promise.all([
    workspace.hydrate(),
    bindingStore.getBindingStatus(projectId.value, { force: true }).catch(() => null),
  ])
  if (editable.value) editingSection.value = activeSection.value
}
watch(() => [projectId.value, routeProject.state.value], () => {
  notice.value = ''; authorInstructions.value = ''; activeSection.value = 'premise'; editingSection.value = ''
  historyRestoreTarget = null
  void hydrate().catch(() => {})
}, { immediate: true })

function edit(value) { workspace.edit(value) }
function navigateSection(key) {
  activeSection.value = key
  if (editingSection.value && editingSection.value !== key) editingSection.value = ''
}
function beginSectionEdit(key) { if (editable.value && !busy.value) { activeSection.value = key; editingSection.value = key } }
function completeSectionEdit() { editingSection.value = ''; if (store.dirty) notice.value = '本区修改已保留在本地工作副本，尚未保存。' }
async function save() {
  try { if (await workspace.save()) notice.value = '草稿已保存' } catch {}
}
async function confirm() {
  try { if (await workspace.confirm()) { notice.value = '已确认为项目永久基线'; editingSection.value = '' } } catch {}
}
async function requestProposal(event) {
  notice.value = ''
  try { await workspace.propose(proposalScope.value, authorInstructions.value) } catch {}
}
function adoptProposal() {
  if (workspace.adoptProposal()) {
    editingSection.value = ''
    notice.value = '已采纳建议，存在未保存修改。'
  }
}
function cancelProposal() { workspace.cancelProposal() }
function openHistory(event) {
  const trigger = event?.currentTarget || historyTrigger.value
  historyRestoreTarget = trigger?.isConnected !== false ? trigger : null
  void workspace.openHistory().catch(() => {})
}
function closeHistory() {
  historyOpen.value = false
  const trigger = historyRestoreTarget
  historyRestoreTarget = null
  void nextTick().then(() => { if (trigger?.isConnected !== false) trigger?.focus?.() })
}
function showHistoryDetail(revision) { void workspace.showHistoryDetail(revision).catch(() => {}) }
function loadMoreHistory() { void workspace.loadMoreHistory().catch(() => {}) }
function confirmHydrateOverwrite() { return !store.dirty || window.confirm('重新加载将覆盖本地未保存内容。确定继续吗？') }
async function retryFailure() {
  const type = recoveryCommand.value?.type
  if (!type) return
  if (['hydrate', 'reconcile', 'reloadAuthoritative'].includes(type) && !confirmHydrateOverwrite()) return
  try {
    const result = await workspace.retryFailure()
    if (result === undefined) return
    if (type === 'save') notice.value = '草稿已保存'
    else if (type === 'confirm') notice.value = '已确认为项目永久基线'
    else if (['hydrate', 'reconcile', 'reloadAuthoritative'].includes(type)) {
      notice.value = '已重新加载权威版本'
      editingSection.value = editable.value ? activeSection.value : ''
    }
  } catch {}
}
async function reloadAuthoritative() {
  if (!confirmHydrateOverwrite()) return
  try {
    if (await workspace.hydrate() !== undefined) {
      notice.value = '已重新加载权威版本'
      editingSection.value = editable.value ? activeSection.value : ''
    }
  } catch {}
}

onBeforeRouteLeave(() => workspace.requestLeave())
onBeforeRouteUpdate(() => workspace.requestLeave())
onMounted(() => window.addEventListener('beforeunload', workspace.beforeUnload))
onBeforeUnmount(() => { historyRestoreTarget = null; window.removeEventListener('beforeunload', workspace.beforeUnload) })
</script>

<template>
  <section class="bible-page">
    <section v-if="globalError" ref="errorTarget" class="error-summary" tabindex="-1" role="alert" aria-live="assertive">
      <strong>{{ globalError.message }}</strong><span v-if="globalError.correlationId">参考编号：{{ globalError.correlationId }}</span>
      <button v-if="hasConflict" type="button" @click="reloadAuthoritative">重新加载权威版本</button><button v-else type="button" @click="retryFailure">{{ recoveryLabel }}</button>
    </section>
    <p v-if="notice" class="bible-notice" aria-live="polite">{{ notice }}</p>
    <section v-if="routeProject.state.value === 'loading'" class="bible-state">正在装订创作圣经…</section>
    <not-found-view v-else-if="routeProject.state.value === 'missing'" title="项目不存在" description="无法打开创作圣经。" />
    <section v-else-if="routeProject.state.value === 'error'" class="bible-state">项目加载失败。<button @click="routeProject.reload">重试</button></section>
    <section v-else class="bible-stage" :aria-busy="busy || undefined">
      <div class="workspace-content" :inert="busy || undefined">
        <FoundationWorkspace
          :title="`${routeProject.project.value?.title || ''} · 创作圣经`"
          purpose="在同一份完整文档中校订世界、人物、冲突与连贯性；确认后成为项目永久基线。"
          :status-label="modeLabel"
          :read-only="documentReadOnly"
        >
          <template #index><FoundationSectionIndex :items="sectionItems" :current-key="activeSection" @navigate="navigateSection" /></template>
          <template #document>
            <p v-if="store.baselineLocked" ref="statusTarget" class="document-note" tabindex="-1">已确认，作为项目永久基线。</p>
            <p v-if="mode === 'superseded'" class="document-note">此修订已被替代，内容仅供复制与查阅。</p>
            <p v-if="mode === 'archived'" class="document-note">此项目或当前服务端状态为只读。</p>
            <p v-if="working" class="document-kicker">完整内容</p>
            <BibleEditor
              v-if="working"
              :model-value="working"
              :active-section="activeSection"
              :editing-section="editingSection"
              :read-only="documentReadOnly"
              :disabled="busy"
              @update:model-value="edit"
              @navigate-section="navigateSection"
              @begin-section-edit="beginSectionEdit"
              @complete-section-edit="completeSectionEdit"
            />
          </template>
          <template #status>
            <FoundationStatusRail :read-only="documentReadOnly">
              <template #summary><strong>用途</strong><p>统一世界、人物、冲突与连续性，为分卷规划和逐章写作提供永久依据。</p><strong class="rail-heading">上游摘要</strong><p>采用已确认创作契约第 {{ sourceBasis.contractRevision ?? '—' }} 版。</p><strong class="rail-heading">完整度摘要</strong><dl class="summary-grid"><div><dt>世界规则</dt><dd>{{ summary.world }}</dd></div><div><dt>核心人物</dt><dd>{{ summary.cast }}</dd></div><div><dt>势力</dt><dd>{{ summary.factions }}</dd></div><div><dt>开放问题</dt><dd>{{ summary.questions }}</dd></div></dl></template>
              <template #status><strong>生命周期</strong><p>{{ modeLabel }}</p><strong class="rail-heading">可编辑性</strong><p>{{ documentReadOnly ? '全文只读' : store.dirty ? '可编辑 · 存在未保存修改' : '可编辑 · 当前草稿已保存' }}</p><p>草稿版本：{{ draftVersion ?? '—' }}</p><p v-if="!documentReadOnly">AI 辅助：{{ planningReady ? '已就绪' : '未就绪' }}（不影响手动保存与确认）</p></template>
              <template #source><strong>来源与诊断</strong><p>契约依据：第 {{ sourceBasis.contractRevision ?? '—' }} 版</p><p>创作契约来源：{{ sourceBasis.creationContractId || '未记录' }}</p><p>风格契约来源：{{ sourceBasis.styleContractId || '未记录' }}</p><p v-for="reason in reasonLabels" :key="reason">{{ reason }}</p><button ref="historyTrigger" type="button" :disabled="busy" @click="openHistory($event)">修订历史</button></template>
              <template #action>
                <label for="bible-author-instructions">作者补充要求（可选）</label><textarea id="bible-author-instructions" v-model="authorInstructions" :disabled="busy" maxlength="4000" rows="4" />
                <button type="button" :disabled="!canRequestProposal" @click="requestProposal">{{ proposalActionLabel }}</button><p v-if="proposalDisabledReason" class="action-note">{{ proposalDisabledReason }}</p>
                <button type="button" :disabled="!canSave" @click="save">手动保存</button><p v-if="saveDisabledReason" class="action-note">{{ saveDisabledReason }}</p>
                <span v-if="store.dirty">请先保存后再确认</span>
                <button type="button" :disabled="!canConfirm" @click="workspace.openConfirm($event.currentTarget)">预览并确认</button>
              </template>
            </FoundationStatusRail>
          </template>
        </FoundationWorkspace>
      </div>
      <div v-if="busy" class="busy-overlay" role="status" aria-live="polite" aria-busy="true">正在处理创作圣经…</div>
    </section>

    <FoundationConfirmationDialog :open="confirmOpen" :close-disabled="busy" title="确认创作圣经" @close="workspace.closeConfirm">
      <template #snapshot><section v-if="errorSummary" ref="confirmErrorTarget" class="modal-error-summary" tabindex="-1" role="alert" aria-live="assertive"><strong>{{ errorSummary.message }}</strong><span v-if="errorSummary.correlationId">参考编号：{{ errorSummary.correlationId }}</span><button v-if="hasConflict" type="button" :disabled="busy" @click="reloadAuthoritative">重新加载权威版本</button><button v-else type="button" :disabled="busy" @click="retryFailure">{{ recoveryLabel }}</button></section><p>确认后将作为项目永久基线。请核对已保存的完整快照。</p><BibleEditor v-if="confirmationAdapter.snapshot" :model-value="confirmationAdapter.snapshot" read-only :disabled="busy" /></template>
      <template #source><strong>契约依据</strong><p>草稿版本：{{ confirmationAdapter.draftVersion ?? '—' }}</p><p>契约版本：{{ confirmationAdapter.contractBasis.contractRevision ?? '—' }}</p><p>服务端确认能力：{{ confirmationAdapter.canConfirm ? '允许' : '不允许' }}</p><p v-for="reason in reasonLabels" :key="reason">{{ reason }}</p></template>
      <template #action><button type="button" :disabled="busy" @click="workspace.closeConfirm">返回编辑</button><button ref="confirmTarget" type="button" :disabled="!confirmationAdapter.canConfirm" @click="confirm">确认签印</button></template>
    </FoundationConfirmationDialog>
    <BibleProposalReview :open="proposalOpen" :snapshot="proposalSnapshot" :busy="busy" @adopt="adoptProposal" @cancel="cancelProposal" />
    <BibleHistoryDrawer :history="store.history" :history-next-before-revision="store.historyNextBeforeRevision" :history-detail="store.historyDetail" :open="historyOpen" :busy="busy" :error="errorSummary" :retry-label="recoveryLabel" @close="closeHistory" @detail="showHistoryDetail" @more="loadMoreHistory" @retry="retryFailure" />
  </section>
</template>

<style scoped>
.bible-page { position:relative; min-height:100%; color:var(--nc-ink); background:var(--nc-canvas); }
.bible-stage { position:relative; min-height:100%; }.workspace-content { min-height:100%; }
.bible-state,.error-summary { width:min(960px,calc(100% - 32px)); margin:24px auto; padding:18px; border:1px solid var(--nc-border); background:var(--nc-paper); }
.error-summary,.modal-error-summary { display:grid; gap:8px; }.error-summary { border-color:var(--nc-vermilion); }.modal-error-summary { margin:0 0 12px; padding:12px; border:1px solid var(--nc-vermilion); background:color-mix(in srgb,var(--nc-paper) 92%,var(--nc-canvas)); }
.bible-notice { position:sticky; z-index:8; top:8px; width:min(760px,calc(100% - 32px)); margin:8px auto -52px; padding:11px 14px; color:var(--nc-ink); border:1px solid var(--nc-border); background:var(--nc-paper); box-shadow:0 8px 24px color-mix(in srgb,var(--nc-ink) 10%,transparent); }
.document-note { margin:0; padding:12px clamp(22px,4vw,38px); color:var(--nc-muted); border-bottom:1px solid var(--nc-border); background:color-mix(in srgb,var(--nc-paper) 88%,var(--nc-canvas)); }
.document-kicker { margin:0; padding:18px clamp(22px,4vw,38px) 0; color:var(--nc-vermilion); font:700 10px Georgia,'Noto Serif SC',serif; letter-spacing:.16em; }.rail-heading { display:block; margin-top:12px; }
.summary-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:10px 0 0; }.summary-grid div { padding:8px; border:1px solid var(--nc-border); }.summary-grid dt { color:var(--nc-muted); font-size:11px; }.summary-grid dd { margin:3px 0 0; color:var(--nc-vermilion); font:700 20px Georgia,serif; }
.bible-page :deep(button) { min-height:38px; border:1px solid var(--nc-border); padding:7px 12px; color:var(--nc-ink); background:var(--nc-paper); font:600 13px Georgia,'Noto Serif SC',serif; cursor:pointer; }.bible-page :deep(button:disabled) { cursor:not-allowed; opacity:.48; }.bible-page :deep(button:focus-visible) { outline:2px solid var(--nc-vermilion); outline-offset:2px; }
.bible-page :deep(.foundation-status-rail textarea) { width:100%; resize:vertical; border:1px solid var(--nc-border); padding:9px; color:var(--nc-ink); background:var(--nc-paper); font:13px/1.55 Georgia,'Noto Serif SC',serif; }.bible-page :deep(.foundation-status-rail p) { margin:7px 0 0; line-height:1.55; }.action-note { color:var(--nc-muted); font-size:12px; }
.busy-overlay { position:absolute; z-index:10; inset:0; display:grid; place-items:center; color:var(--nc-paper); background:color-mix(in srgb,var(--nc-ink) 55%,transparent); font-weight:700; }
@media (max-width:760px) { .bible-notice { position:static; margin:8px auto; } }
</style>

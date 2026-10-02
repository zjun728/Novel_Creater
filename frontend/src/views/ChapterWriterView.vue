<script setup>
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import {
  onBeforeRouteLeave,
  onBeforeRouteUpdate,
  useRoute,
  useRouter,
} from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NInput,
  NModal,
  NResult,
  NSkeleton,
  NStatistic,
  NTag,
} from 'naive-ui'

import PlainTextDraftEditor from '@/components/writer/PlainTextDraftEditor.vue'
import FinalizationPanel from '@/components/writer/FinalizationPanel.vue'
import WorkbenchChapterNavigation from '@/components/writer/WorkbenchChapterNavigation.vue'
import WorkbenchToolTabs from '@/components/writer/WorkbenchToolTabs.vue'
import WorkbenchOutlineDialog from '@/components/writer/WorkbenchOutlineDialog.vue'
import { resolveReviewRange } from '@/application/writer/finalizationEvidence.js'
import { referenceFromReview } from '@/utils/reviewReference.js'
import { saveThenAdjustReview } from '@/application/writer/reviewAdjustment.js'
import { MANUSCRIPT_HISTORY_CONTEXT } from '@/application/manuscript/manuscriptHistory.js'
import { createWorkingDraftAutosave } from '@/application/writer/workingDraftAutosave'
import { createChapterWriterController } from '@/application/writer/chapterWriterController'
import { createFinalizationController } from '@/application/writer/finalizationController'
import { rewritePresets, appendRewritePreset } from '@/application/writer/rewritePresets'
import { canLeaveWriter } from '@/application/writer/writerNavigationGuard'
import { mapProjectNextAction } from '@/application/projects/projectNextAction'
import { api } from '@/api/db/client'
import { useChapterSessionStore } from '@/stores/chapterSessionStore'
import { createLatestRequestGuard } from '@/utils/latestRequest'
import {
  limitUnicodeScalarText,
  unicodeScalarLength,
} from '@/utils/unicodeScalarText'
import {
  finalChapterPath,
  planningOutlinesPath,
  projectOverviewPath,
} from '@/router/projectRoutes'

const route = useRoute()
const emit = defineEmits(['read-finalized'])
const manuscriptHistory = inject(MANUSCRIPT_HISTORY_CONTEXT, null)
const router = useRouter()
const chapterSessionStore = useChapterSessionStore()
const loadGuard = createLatestRequestGuard()

const loading = ref(true)
const pageError = ref('')
const actionError = ref('')
const outlineAuthority = ref(null)
const navigationRefreshToken = ref(0)
async function handleOutlineConfirmed() {
  await loadWorkspace(projectId.value, chapterNumber.value)
  navigationRefreshToken.value += 1
}
const contractWordRange = ref(null)
const lastSavedAt = ref('')
const detailsVisible = ref(true)
const activeTool = ref('assistant')
const toolScroller = ref(null)
const toolScrollPositions = {}
async function openTool(key) {
  toolScrollPositions[activeTool.value] = toolScroller.value?.scrollTop || 0
  activeTool.value = key
  detailsVisible.value = true
  await nextTick()
  if (toolScroller.value && activeTool.value === key) toolScroller.value.scrollTop = toolScrollPositions[key] || 0
}
const outlineDialogOpen = ref(false)
const reviewDirty = ref(false)
const draftEditor = ref(null)
const outlineEditor = ref(null)
const previewCandidate = ref(null)
const savedComparisonOpen = ref(false)
const regenerationOpen = ref(false)
const reviewAdjustment = ref(null)
const protectionBusy = ref(false)
const locateMessage = ref('')
const selectedFinding = ref('')
const reviewMatchesDraft = computed(() => {
  const review = finalization.review.value
  if (!review || finalization.finalized.value) return true
  const candidate = candidates.value.find(item => item.id === review.candidateId && item.contentHash === review.candidateHash && item.basisStatus === 'current')
  return Boolean(candidate && candidate.content === controller.editorText.value)
})
async function openOutlineEditor() {
  if (controller.actionBusy.value || controller.operationRetryAvailable.value || finalization.busy.value || protectionBusy.value || finalization.finalized.value) return
  if (reviewDirty.value && !window.confirm('修改小纲会使当前审稿失效。未保存的审稿修正将丢弃，是否继续？')) return
  try {
    if (session.value && !await autosave.flush()) return
    outlineDialogOpen.value = true
  } catch { actionError.value = '正文尚未保存，暂不能编辑小纲。请先重试保存。' }
}
async function locateFinding(item) {
  selectedFinding.value = item.id
  locateMessage.value = ''
  const review = finalization.review.value
  const candidate = candidates.value.find(value => value.id === review?.candidateId && value.contentHash === review?.candidateHash)
  const sourceText = controller.editorText.value
  try {
      const range = await resolveReviewRange({ prose: sourceText, candidate, review, evidence: item.evidence })
      await nextTick()
      if (selectedFinding.value !== item.id) return
    if (!range || controller.editorText.value !== sourceText || finalization.review.value !== review) {
      locateMessage.value = '正文已变化或原文证据不可用，请重新审稿或在正文中手动查找。'
      return
    }
    draftEditor.value.locateRange(range.startOffset, range.endOffset)
  } catch { locateMessage.value = '原文范围已失效，请重新审稿或手动查找。' }
}
async function confirmCandidateSwitch() {
  if (commandDisabled.value || protectionBusy.value || !previewCandidate.value) return
  actionError.value = ''
  protectionBusy.value = true
  try {
    const candidate = previewCandidate.value
    if (!await controller.saveCandidate()) throw new Error('save failed')
    if (!await controller.loadCandidate(candidate)) throw new Error('load failed')
    previewCandidate.value = null
  } catch { actionError.value = '切换未完成，当前正文和已有候选已保留，请重试。' }
  finally { protectionBusy.value = false }
}
async function confirmRegeneration(keep) {
  if (commandDisabled.value || protectionBusy.value) return
  actionError.value = ''
  protectionBusy.value = true
  try {
    if (keep && !await controller.saveCandidate()) throw new Error('save failed')
    regenerationOpen.value = false
    await performGeneration()
  } catch { actionError.value = '当前稿未能保存，尚未开始重新生成。' }
  finally { protectionBusy.value = false }
}


const projectId = computed(() => String(route.params.projectId || ''))
function openReviewAdjustment() {
  if (archived.value || commandDisabled.value || reviewDirty.value || !reviewMatchesDraft.value || finalization.finalized.value) return
  const reference = referenceFromReview(finalization.review.value)
  if (!reference) return
  actionError.value = ''
  reviewAdjustment.value = { reference, projectId: projectId.value, sessionId: session.value?.id, text: controller.editorText.value }
}
async function confirmReviewAdjustment() {
  if (archived.value || commandDisabled.value || !reviewAdjustment.value) return
  const captured = reviewAdjustment.value
  protectionBusy.value = true
  actionError.value = ''
  try {
    const result = await saveThenAdjustReview({
      reference: captured.reference,
      isCurrent: () => projectId.value === captured.projectId && session.value?.id === captured.sessionId
        && controller.editorText.value === captured.text && !reviewDirty.value && reviewMatchesDraft.value
        && !finalization.finalized.value && !archived.value
        && JSON.stringify(referenceFromReview(finalization.review.value)) === JSON.stringify(captured.reference),
      saveCandidate: () => controller.saveCandidate(),
      generate: async command => {
        reviewAdjustment.value = null
        const result = await controller.generateWorkingDraft(command)
        if (projectId.value === captured.projectId && session.value?.id === captured.sessionId) await finalization.load()
        return result
      },
    })
    if (!result) actionError.value = '整章调整未启动，请检查保存和生成状态；旧稿已保留。'
  } catch (error) { actionError.value = error?.message || '整章调整未完成，旧稿已保留，请核对状态。' }
  finally { protectionBusy.value = false }
}
const chapterNumber = computed(() => Number(route.params.chapterNumber))
const session = computed(() => chapterSessionStore.session)
const candidates = computed(() => chapterSessionStore.candidates)
const selectedCandidateIds = ref([])
const selectedCandidates = computed(() => candidates.value.filter(
  candidate => selectedCandidateIds.value.includes(candidate.id),
))
const comparisonPanes = computed(() => previewCandidate.value
  ? [
    { label: '待定稿', content: previewCandidate.value.content },
    { label: '当前正在使用的正文', content: controller.editorText.value },
  ]
  : selectedCandidates.value.map(candidate => ({
    label: `候选 ${candidates.value.findIndex(item => item.id === candidate.id) + 1}`,
    content: candidate.content,
  })))

function openCandidatePreview(candidate) {
  if (commandDisabled.value) return
  actionError.value = ''
  savedComparisonOpen.value = false
  previewCandidate.value = candidate
}

function closeComparison() {
  if (protectionBusy.value) return
  previewCandidate.value = null
  savedComparisonOpen.value = false
}
const confirmedOutline = computed(
  () => outlineAuthority.value?.confirmedOutline || null,
)
const outlineContent = computed(() => confirmedOutline.value?.content || null)
const planningContent = computed(
  () => outlineAuthority.value?.planningAuthority?.content || null,
)
const chapterConflict = computed(() => (
  outlineAuthority.value !== null
  && outlineAuthority.value.authoritativeChapterNumber !== chapterNumber.value
))
const archived = computed(() => outlineAuthority.value?.lifecycle === 'archived')
const outlinesPath = computed(() => planningOutlinesPath(projectId.value))

const autosave = createWorkingDraftAutosave({
  persist: snapshot => chapterSessionStore.saveWorkingDraft(
    projectId.value,
    snapshot,
  ),
})
const finalization = createFinalizationController({
  decideFinding: command => api.chapterSessions.decideFinding(projectId.value, session.value.id, command),
  disputeFinding: command => api.chapterSessions.disputeFinding(projectId.value, session.value.id, command),
  disputeEvidence: command => api.chapterSessions.disputeEvidence(projectId.value, session.value.id, command),
  getReview: () => api.chapterSessions.getFinalization(
    projectId.value,
    session.value.id,
  ),
  prepare: (candidateId, command) => api.chapterSessions.prepareFinalization(
    projectId.value,
    session.value.id,
    candidateId,
    command,
  ),
  correct: command => api.chapterSessions.correctFinalization(
    projectId.value,
    session.value.id,
    command,
  ),
  confirm: command => api.chapterSessions.confirmFinalization(
    projectId.value,
    session.value.id,
    command,
  ),
  cancel: command => api.chapterSessions.cancelFinalization(
    projectId.value,
    session.value.id,
    command,
  ),
  revoke: (attemptId, command) => api.chapterSessions.revokeFinalization(
    projectId.value, session.value.id, attemptId, command,
  ),
  getAttemptState: attemptId => api.chapterSessions.getFinalizationAttemptState(
    projectId.value, session.value.id, attemptId,
  ),
  commit: async (command, target) => {
    const committed = await api.chapterSessions.commitFinalization(
      target.projectId,
      target.sessionId,
      command,
    )
    return { ...committed, chapterNumber: target.chapterNumber }
  },
  onCommitted: async target => {
    try {
      const workspace = await chapterSessionStore.reloadCurrentWorkspace(target.projectId)
      if (workspace?.workingDraft) autosave.reset(workspace)
    } finally {
      if (projectId.value === target.projectId && chapterNumber.value === target.chapterNumber) {
        navigationRefreshToken.value += 1
      }
    }
  },
  getProjectId: () => projectId.value,
  getSessionId: () => session.value?.id,
  getChapterNumber: () => chapterNumber.value,
  reloadPreparation: projectId => api.projects.preparation(projectId),
  readFinalizedChapter: (projectId, chapterNumber) => api.manuscripts.chapter(
    projectId,
    chapterNumber,
  ),
  mapNextAction: mapProjectNextAction,
  finalizedChapterPath: (projectId, chapterNumber) => finalChapterPath(
    projectId,
    chapterNumber,
  ),
})
const controller = createChapterWriterController({
  autosave,
  writeBusy: () => chapterSessionStore.commandBusy || finalization.busy.value,
  freezeCandidate: command => chapterSessionStore.saveCandidate(projectId.value, command),
  loadCandidate: (candidateId, command) => chapterSessionStore.loadCandidate(
    projectId.value,
    candidateId,
    command,
  ),
  createDraftOperation: command => chapterSessionStore.createDraftOperation(
    projectId.value,
    command,
  ),
  readDraftOperation: operationId => chapterSessionStore.readDraftOperation(
    projectId.value,
    operationId,
  ),
  listDraftOperationEvents: (operationId, afterSequence) => chapterSessionStore.listDraftOperationEvents(
    projectId.value,
    operationId,
    afterSequence,
  ),
  cancelDraftOperation: operationId => chapterSessionStore.cancelDraftOperation(
    projectId.value,
    operationId,
  ),
  applyLocalPreview: command => chapterSessionStore.applyLocalPreview(projectId.value, command),
  undoLocalDraft: command => chapterSessionStore.undoLocalDraft(
    projectId.value,
    command,
  ),
  reloadWorkspace: () => chapterSessionStore.reloadCurrentWorkspace(projectId.value),
})
const validSelection = computed(() => {
  const value = controller.selection.value
  const startOffset = value?.startOffset
  const endOffset = value?.endOffset
  const selectedText = value?.selectedText
  const scalars = Array.from(controller.editorText.value)
  return Number.isInteger(startOffset)
    && startOffset >= 0
    && Number.isInteger(endOffset)
    && endOffset > startOffset
    && endOffset <= scalars.length
    && typeof selectedText === 'string'
    && selectedText.length > 0
    && scalars.slice(startOffset, endOffset).join('') === selectedText
})
const authorInstructionLimit = computed(() => validSelection.value ? 1_000 : 2_000)
const authorInstructionNotice = ref('')
const selectedRewritePreset = ref('改对白')
function fillRewritePreset() {
  const result = appendRewritePreset(controller.authorInstruction.value, selectedRewritePreset.value)
  if (result === null) {
    authorInstructionNotice.value = '加入预设将超过 1000 字，请先精简临时要求；原文已保留。'
    return
  }
  updateAuthorInstruction(result)
}
const authorInstructionCount = computed(
  () => unicodeScalarLength(controller.authorInstruction.value),
)

function updateAuthorInstruction(nextInstruction) {
  try {
    const limit = authorInstructionLimit.value
    const limited = limitUnicodeScalarText(String(nextInstruction ?? ''), limit)
    controller.setAuthorInstruction(limited.value)
    authorInstructionNotice.value = limited.truncated
      ? `已截断超过 ${limit} 个 Unicode 字符的内容。`
      : ''
  } catch {
    authorInstructionNotice.value = '输入包含无效字符，未接受。'
  }
}

const editorDisabled = computed(() => !session.value)
const editorReadonly = computed(() => (
  controller.actionBusy.value
  || protectionBusy.value
  || finalization.busy.value
  || finalization.finalized.value
))
const commandDisabled = computed(() => (
  !session.value
  || controller.operationRetryAvailable.value
  || protectionBusy.value
  || controller.actionBusy.value
  || chapterSessionStore.commandBusy
  || finalization.busy.value
  || finalization.finalized.value
))
const localCommandDisabled = computed(() => (
  commandDisabled.value
  || controller.pendingLocalPreview.value !== null
  || !validSelection.value
  || authorInstructionCount.value > 1_000
))

function candidateSelected(candidateId) {
  return selectedCandidateIds.value.includes(candidateId)
}

function candidateSelectionDisabled(candidateId) {
  return controller.actionBusy.value
    || chapterSessionStore.commandBusy
    || finalization.busy.value
    || finalization.finalized.value
    || (!candidateSelected(candidateId) && selectedCandidateIds.value.length >= 2)
}

function toggleCandidateSelection(candidateId) {
  if (candidateSelectionDisabled(candidateId)) return
  if (candidateSelected(candidateId)) {
    selectedCandidateIds.value = selectedCandidateIds.value.filter(
      value => value !== candidateId,
    )
    return
  }
  if (selectedCandidateIds.value.length >= 2) return
  selectedCandidateIds.value = [...selectedCandidateIds.value, candidateId]
}

function candidateCharacterCount(candidate) {
  return unicodeScalarLength(String(candidate.content ?? ''))
}

function formatCandidateTime(createdAt) {
  const date = new Date(createdAt)
  if (!Number.isFinite(date.getTime())) return '时间未知'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(date)
}

watch(candidates, nextCandidates => {
  const ids = new Set(nextCandidates.map(candidate => candidate.id))
  selectedCandidateIds.value = selectedCandidateIds.value.filter(
    candidateId => ids.has(candidateId),
  )
}, { flush: 'sync' })

function savedTime() {
  const now = new Date()
  return [now.getHours(), now.getMinutes(), now.getSeconds()]
    .map(value => String(value).padStart(2, '0'))
    .join(':')
}

function updateLastSavedAt() {
  if (session.value && Number.isInteger(autosave.persistedRevision.value)) {
    lastSavedAt.value = savedTime()
  }
}

watch(() => autosave.persistedRevision.value, updateLastSavedAt, { flush: 'sync' })

async function loadWorkspace(nextProjectId, nextChapterNumber, startSession = false) {
  controller.resetContext()
  finalization.reset()
  selectedCandidateIds.value = []
  activeTool.value = 'assistant'
  for (const key of Object.keys(toolScrollPositions)) delete toolScrollPositions[key]
  previewCandidate.value = null
  savedComparisonOpen.value = false
  regenerationOpen.value = false
  reviewAdjustment.value = null
  selectedFinding.value = ''
  locateMessage.value = ''
  outlineDialogOpen.value = false
  lastSavedAt.value = ''
  const targetProjectId = String(nextProjectId || '')
  const targetChapterNumber = Number(nextChapterNumber)
  const generation = loadGuard.begin()
  loading.value = true
  pageError.value = ''
  actionError.value = ''
  outlineAuthority.value = null
  contractWordRange.value = null
  reviewDirty.value = false
  try {
    const current = await chapterSessionStore.openAuthoritative(
      targetProjectId,
      targetChapterNumber,
      { startSession },
    )
    if (!loadGuard.isCurrent(generation) || current === null) return
    outlineAuthority.value = current
    if (startSession) navigationRefreshToken.value += 1
    if (chapterSessionStore.workspace?.workingDraft) {
      autosave.reset(chapterSessionStore.workspace)
      updateLastSavedAt()
      await finalization.load()
      void api.contracts.head(targetProjectId).then(head => {
        if (!loadGuard.isCurrent(generation)) return
        const range = head?.creationContract?.chapterWordRangePreference
        if (Array.isArray(range) && range.length === 2 && range.every(value => Number.isFinite(value) && value > 0)) contractWordRange.value = range
      }).catch(() => {})
      if (!loadGuard.isCurrent(generation)) return
      const activeDraftOperationId = chapterSessionStore.workspace?.activeDraftOperationId
      if (activeDraftOperationId && !finalization.finalized.value) {
        void controller.resumeDraftOperation(activeDraftOperationId).catch(() => {
          if (!loadGuard.isCurrent(generation)) return
          actionError.value = '生成失败'
        })
      }
    }
  } catch {
    if (!loadGuard.isCurrent(generation)) return
    pageError.value = '章节工作台加载失败，请稍后重试。'
  } finally {
    if (loadGuard.isCurrent(generation)) {
      loading.value = false
      const snapshot = { fullPath: route.fullPath, path: route.path, name: route.name, params: { ...route.params }, query: { ...route.query } }
      await nextTick()
      if (loadGuard.isCurrent(generation)) await manuscriptHistory?.viewRendered(snapshot, { settled: true })
    }
  }
}

async function generateWorkingDraft() {
  if (commandDisabled.value) return
  actionError.value = ''
  if (controller.editorText.value.trim()) { regenerationOpen.value = true; return }
  await performGeneration()
}

async function performGeneration() {
  actionError.value = ''
  try {
    const result = await controller.generateWorkingDraft()
    if (!result && !controller.operationStatusText.value) {
      actionError.value = '当前工作稿未能安全暂存，请稍后重试。'
    }
  } catch {
    if (!controller.operationStatusText.value) {
      actionError.value = '当前工作稿未能完成生成，请检查作者要求后重试。'
    }
  }
}

async function recoverPartialDraft() {
  actionError.value = ''
  try {
    const recovered = await controller.recoverPartialDraft()
    if (!recovered) actionError.value = '部分正文未能安全载入，请先确认当前工作稿已暂存。'
  } catch {
    actionError.value = '部分正文未能安全载入，请稍后重试。'
  }
}

async function retryUnknown() {
  actionError.value = ''
  try {
    await controller.retryUnknown()
  } catch {
    // Unknown retries retain the coordinator-owned key and fixed status text.
  }
}

async function stopGeneration() {
  actionError.value = ''
  try {
    await controller.cancelGeneration()
  } catch {
    if (!controller.operationStatusText.value) actionError.value = '生成失败'
  }
}

async function runSelectionOperation(operationType) {
  actionError.value = ''
  try {
    const result = await controller.runSelectionOperation(operationType)
    if (!result && !controller.operationStatusText.value) {
      actionError.value = '当前选区未能安全处理，请重新选择后重试。'
    }
  } catch {
    if (!controller.operationStatusText.value) {
      actionError.value = '当前选区 AI 操作未完成，请重新选择后重试。'
    }
  }
}

async function applyLocalPreview() {
  actionError.value = ''
  try {
    if (!await controller.applyLocalPreview()) {
      actionError.value = '正文已变化，当前建议不能采用，请取消后重新生成。'
    }
  } catch {
    actionError.value = '建议未能确认采用。请重试；正文版本冲突时请刷新核对。'
  }
}

async function undoLastLocal() {
  actionError.value = ''
  try {
    const result = await controller.undoLastLocal()
    if (!result) actionError.value = '本次 AI 修改已不能安全撤销。'
  } catch {
    actionError.value = '本次 AI 修改已不能安全撤销。'
  }
}

async function saveCandidate() {
  actionError.value = ''
  try {
    const result = await controller.saveCandidate()
    if (!result) actionError.value = '当前工作稿未能安全暂存，请稍后重试。'
  } catch {
    actionError.value = '当前工作稿未能保存为候选，请稍后重试。'
  }
}

async function loadCandidate(candidate) {
  actionError.value = ''
  try {
    const result = await controller.loadCandidate(candidate)
    if (!result) actionError.value = '候选稿未能安全载入，请稍后重试。'
  } catch {
    actionError.value = '候选稿未能安全载入，请刷新后重试。'
  }
}

async function retryAutosave() {
  try {
    await autosave.retry()
  } catch {
    // The editor keeps the precise failed/conflict persistence status visible.
  }
}

function backToProject() {
  if (controller.actionBusy.value || finalization.busy.value) return
  router.push(projectOverviewPath(projectId.value))
}

function guardBusyNavigation(event) {
  if (!controller.actionBusy.value && !finalization.busy.value) return
  event.preventDefault()
}

function beforeUnload(event) {
  event.preventDefault()
  event.returnValue = ''
  return ''
}

let beforeUnloadRegistered = false
function syncBeforeUnloadRisk(enabled) {
  if (typeof window === 'undefined' || enabled === beforeUnloadRegistered) return
  if (enabled) window.addEventListener('beforeunload', beforeUnload)
  else window.removeEventListener('beforeunload', beforeUnload)
  beforeUnloadRegistered = enabled
}
const stopBeforeUnloadRisk = watch(
  () => controller.beforeUnloadRisk.value || reviewDirty.value || protectionBusy.value,
  syncBeforeUnloadRisk,
  { immediate: true, flush: 'sync' },
)

watch([() => route.params.projectId, () => route.params.chapterNumber], ([nextProjectId, nextChapterNumber]) => {
  void loadWorkspace(String(nextProjectId || ''), Number(nextChapterNumber))
}, { immediate: true })

async function canLeaveWorkspace() {
  if (protectionBusy.value) return false
  if (outlineDialogOpen.value && !outlineEditor.value?.canClose()) return false
  return canLeaveWriter({
    canNavigate: () => controller.canNavigate(),
    dirty: () => reviewDirty.value,
    confirmDiscard: () => window.confirm('审查修正尚未保存。离开将丢弃这些修正，是否离开？'),
  })
}
onBeforeRouteUpdate(async () => await canLeaveWorkspace())
onBeforeRouteLeave(async () => await canLeaveWorkspace())

onBeforeUnmount(() => {
  stopBeforeUnloadRisk()
  syncBeforeUnloadRisk(false)
  loadGuard.invalidate()
  controller.dispose()
  finalization.dispose()
  autosave.dispose()
  chapterSessionStore.invalidate()
})
</script>

<template>
  <section class="writer-shell">
    <workbench-chapter-navigation :project-id="projectId" :chapter-number="chapterNumber" :refresh-token="navigationRefreshToken" />
    <div class="writer-body">
    <section v-if="loading" class="writer-loading" aria-busy="true" aria-label="正在加载章节工作台">
      <n-skeleton text width="28%" />
      <n-skeleton height="420px" />
    </section>

    <n-result v-else-if="pageError" status="error" title="章节工作台未能加载" :description="pageError" class="writer-result">
      <template #footer>
        <n-button :disabled="controller.actionBusy.value" @click="backToProject">返回项目</n-button>
        <n-button type="primary" @click="loadWorkspace(projectId, chapterNumber)">重试</n-button>
      </template>
    </n-result>

    <n-result v-else-if="chapterConflict" status="warning" title="章节地址与服务端权威不一致" description="当前地址不是服务端确认的权威章节；系统不会自动跳转，也不会读取或创建错误章节的会话。" class="writer-result">
      <router-link :to="outlineAuthority.targetPath">前往第 {{ outlineAuthority.authoritativeChapterNumber }} 章</router-link>
    </n-result>

    <n-result v-else-if="archived" status="info" title="项目已归档" description="章节与小纲仅供查看，归档项目不会读取或创建写作会话。" class="writer-result">
      <template #footer><n-button @click="backToProject">返回项目</n-button></template>
    </n-result>

    <template v-else>
      <header class="writer-hero">
        <div>

          <h1>第 {{ chapterNumber }} 章<span v-if="outlineContent?.title"> · {{ outlineContent.title }}</span></h1>
          <p>{{ finalization.finalized.value ? '已定稿 · 正文只读' : '工作稿 · 自动保存' }}</p>
        </div>
        <n-button :disabled="controller.actionBusy.value" @click="backToProject">返回项目</n-button>
      </header>

      <n-alert v-if="!outlineContent" type="warning" class="writer-alert" title="请先完成并确认本章小纲">
        本章小纲确认后才能生成正文。<n-button @click="openOutlineEditor">准备本章小纲</n-button>
      </n-alert>

      <div class="workspace-toolbar"><div class="workspace-display-controls" aria-label="章节操作">
        <n-button @click="openTool('reference')">{{ outlineContent ? '查看本章小纲' : '准备本章小纲' }}</n-button>
        <n-button type="primary" @click="openTool('review')">{{ finalization.finalized.value ? '定稿与进度' : '审查本章' }}</n-button>
        <n-button v-if="controller.operationCancellable.value" type="warning" @click="stopGeneration">停止生成</n-button>
        <n-button v-else :disabled="commandDisabled" @click="generateWorkingDraft">{{ controller.editorText.value ? '重新生成正文' : '生成正文' }}</n-button>

      </div>
      <div class="tool-region-controls" aria-label="章节工具显示"><span>章节工具</span><n-button class="tool-toggle" :aria-expanded="detailsVisible" @click="detailsVisible = !detailsVisible">{{ detailsVisible ? '收起工具区' : '展开工具区' }}</n-button></div></div>
      <section class="workspace-grid" :class="{ 'details-hidden': !detailsVisible }">
        <n-card class="editor-card" :bordered="false">
          <template #header>
            <div class="card-header">
              <div>
                <strong>当前正文</strong>
                <span v-if="session">第 {{ session.chapterNum }} 章</span>
                <span v-else>第 {{ chapterNumber }} 章 · 尚未创建章节会话</span>
              </div>
              <n-tag
                :type="finalization.finalized.value ? 'success' : session ? 'success' : 'default'"
                :bordered="false"
              >{{ finalization.finalized.value ? '已定稿' : session ? '创作中' : '待开始' }}</n-tag>
            </div>
          </template>

          <div v-if="session" class="editor-surface" :aria-busy="controller.actionBusy.value">
            <plain-text-draft-editor
              ref="draftEditor"
              :model-value="controller.editorText.value"
              :disabled="editorDisabled"
              :readonly="editorReadonly"
              :streaming="controller.streamingPreview.value !== null"
              :selection-range="controller.restoredSelection.value"
              :dirty="autosave.dirty.value"
              :status="autosave.status.value"
              :last-saved-at="lastSavedAt"
              placeholder="在这里手动输入、粘贴或继续编辑章节正文。AI 生成只会进入工作稿，不会自动保存候选。"
              @update:model-value="controller.edit"
              @selection-change="controller.setSelection"
              @retry="retryAutosave"
            />
            <section
              v-if="controller.replacementPreview.value !== null"
              class="replacement-preview"
              aria-live="polite"
              aria-label="替换内容预览"
            >
              <strong>局部 AI 修改预览</strong>
              <template v-if="controller.pendingLocalPreview.value">
                <p>原文</p>
                <pre>{{ controller.pendingLocalPreview.value.original }}</pre>
                <p>修改建议 · 采用后才会写入正文</p>
              </template>
              <pre>{{ controller.replacementPreview.value }}</pre>
              <div v-if="controller.pendingLocalPreview.value" class="preview-actions">
                <n-button type="primary" :disabled="commandDisabled || !controller.canApplyLocalPreview.value" @click="applyLocalPreview">采用修改</n-button>
                <n-button :disabled="controller.actionBusy.value" @click="controller.cancelLocalPreview">取消</n-button>
                <span v-if="!controller.canApplyLocalPreview.value && !controller.actionBusy.value">正文已变化，请重新生成建议。</span>
              </div>
            </section>
            <div
              v-if="controller.operationStatusText.value"
              class="draft-operation-layer"
              aria-live="polite"
              role="status"
            >
              <span>{{ controller.operationStatusText.value }}</span>
              <button
                v-if="controller.operationRetryAvailable.value"
                type="button"
                class="draft-operation-retry"
                @click="retryUnknown"
              >重试</button>
            </div>
          </div>
          <p v-else class="draft-empty">{{ outlineContent ? '本章小纲已确认，点击“开始本章写作”进入正文。' : '完成并确认本章小纲后，即可开始撰写正文。' }}</p>

          <n-alert
            v-if="controller.recoverablePartialDraft.value"
            type="warning"
            class="partial-draft-recovery"
            title="生成中断，部分正文仍可恢复"
          >
            已保留 {{ controller.recoverablePartialDraft.value.scalarCount }} 字部分正文。载入后可继续编辑；将替换当前工作稿。
            <div class="partial-draft-actions">
              <n-button secondary :disabled="commandDisabled" @click="recoverPartialDraft">载入部分稿</n-button>
            </div>
          </n-alert>

          <div class="editor-actions">
            <n-button v-if="controller.operationCancellable.value" type="warning" @click="stopGeneration">停止生成</n-button>
            <template v-else>
              <n-button v-if="!session" type="primary" :disabled="!outlineAuthority?.capabilities?.startSession || loading" :loading="loading" @click="loadWorkspace(projectId, chapterNumber, true)">{{ outlineAuthority?.capabilities?.startSession ? '开始本章写作' : '请先完成并确认本章小纲' }}</n-button>
              <n-button type="primary" secondary :disabled="commandDisabled" :loading="controller.actionBusy.value" @click="generateWorkingDraft">AI 生成工作稿</n-button>
              <n-button type="success" :disabled="commandDisabled" :loading="controller.actionBusy.value" @click="saveCandidate">保存为候选</n-button>
              <n-button v-if="controller.undoAvailable.value" secondary :disabled="commandDisabled" :loading="controller.actionBusy.value" @click="undoLastLocal">撤销本次 AI 修改</n-button>
            </template>
          </div>
          <p v-if="contractWordRange" class="muted">单章目标 {{ contractWordRange[0].toLocaleString() }}—{{ contractWordRange[1].toLocaleString() }} 字<span v-if="unicodeScalarLength(controller.editorText.value) > contractWordRange[1]"> · 已超出建议范围，可选择重新生成或继续审稿定稿。</span></p>
          <n-alert v-if="actionError" type="error" class="writer-action-error" title="章节操作未完成">{{ actionError }}</n-alert>
        </n-card>

        <aside ref="toolScroller" v-show="detailsVisible" class="side-stack">
          <workbench-tool-tabs :model-value="activeTool" :count="candidates.length" @update:model-value="openTool" />
          <section v-show="activeTool === 'assistant' || (activeTool === 'review' && validSelection)" class="tool-selection" aria-label="AI 修改工具">
            <div v-if="validSelection" class="selection-tools" aria-label="AI 选区工具">
              <span>已选择 {{ Array.from(controller.selection.value.selectedText).length }} 字</span>
              <n-button size="small" secondary :disabled="localCommandDisabled" :loading="controller.actionBusy.value" @click="runSelectionOperation('rewrite_selection')">AI 改写</n-button>
              <n-button size="small" secondary :disabled="localCommandDisabled" :loading="controller.actionBusy.value" @click="runSelectionOperation('polish_selection')">去 AI 味/润色</n-button>
              <n-button size="small" secondary :disabled="localCommandDisabled" :loading="controller.actionBusy.value" @click="runSelectionOperation('expand_selection')">AI 扩写</n-button>
              <n-button size="small" secondary :disabled="localCommandDisabled" :loading="controller.actionBusy.value" @click="runSelectionOperation('compress_selection')">AI 缩写</n-button>
            </div>
          <div class="generation-box">
            <div v-if="validSelection" class="selection-tools">
              <label for="rewrite-preset">选区改写预设</label>
              <select id="rewrite-preset" v-model="selectedRewritePreset" :disabled="localCommandDisabled">
                <option v-for="preset in rewritePresets" :key="preset.label" :value="preset.label">{{ preset.label }}</option>
              </select>
              <n-button size="small" :disabled="localCommandDisabled" @click="fillRewritePreset">填入改写要求</n-button>
              <span>可编辑后点击“AI 改写”生成建议。</span>
            </div>
            <label for="author-instruction">作者临时要求（可选）</label>
            <p id="author-instruction-help" class="author-instruction-count">已确认小纲、创作设定和连续性上下文会自动带入，无需重复填写。留空即可生成；这里只补充本次想调整的表达或节奏。</p>
            <n-input id="author-instruction" :input-props="{ 'aria-label': '作者临时要求', 'aria-describedby': 'author-instruction-help author-instruction-count' }" :value="controller.authorInstruction.value" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" aria-describedby="author-instruction-help author-instruction-count" placeholder="例如：多一点市井对话；放慢这段对话的节奏。" :disabled="commandDisabled" @update:value="updateAuthorInstruction" />
            <p id="author-instruction-count" class="author-instruction-count" aria-live="polite">{{ authorInstructionCount }} / {{ authorInstructionLimit }}<span v-if="authorInstructionNotice"> · {{ authorInstructionNotice }}</span></p>
          </div>

          </section>
          <section v-show="activeTool === 'review'" id="tool-panel-review" role="tabpanel" aria-labelledby="tool-tab-review" class="tool-panel">
          <p v-if="locateMessage" role="alert">{{ locateMessage }}</p>
          <finalization-panel
            v-if="session"
            :controller="finalization"
            :candidates="candidates"
            :planning-content="planningContent"
            :chapter-number="chapterNumber"
            :disabled="archived || protectionBusy || controller.operationRetryAvailable.value || controller.actionBusy.value || chapterSessionStore.commandBusy"
            :draft-stale="!reviewMatchesDraft"
            :selected-finding="selectedFinding"
            @adjust-review="openReviewAdjustment"
            @locate-finding="locateFinding"
            @read-finalized="emit('read-finalized')"
            @dirty-change="reviewDirty = $event"
          />
          <p v-if="!session" class="muted">确认小纲并撰写正文后，即可审查本章。</p>
          </section>
          <section v-show="activeTool === 'assistant'" id="tool-panel-assistant" role="tabpanel" aria-labelledby="tool-tab-assistant" class="tool-panel"><p class="muted">选中文字生成修改建议。先预览，点击“采用修改”后才写入正文；取消则保留原文。</p></section>
          <section v-show="activeTool === 'reference'" id="tool-panel-reference" role="tabpanel" aria-labelledby="tool-tab-reference" class="tool-panel">
          <p v-if="!outlineContent" class="muted">当前章尚无已确认小纲。</p>
          <n-button v-if="!finalization.finalized.value" :disabled="controller.actionBusy.value || finalization.busy.value || protectionBusy" @click="openOutlineEditor">{{ outlineContent ? '主动编辑小纲' : '生成与确认小纲' }}</n-button>
          <n-card v-if="outlineContent" title="已确认小纲（只读）" :bordered="false">
            <p class="outline-goal">{{ outlineContent.chapterGoal }}</p>
            <dl class="outline-summary">
              <div><dt>预计登场</dt><dd>{{ outlineContent.expectedCharacters?.join('、') || '—' }}</dd></div>
              <div><dt>承接线索</dt><dd>{{ outlineContent.continuation?.join('、') || '—' }}</dd></div>
              <div><dt>计划任务</dt><dd>{{ outlineContent.plannedTasks?.join('、') || '—' }}</dd></div>
              <div><dt>场景</dt><dd>{{ outlineContent.scenes?.join('、') || '—' }}</dd></div>
              <div><dt>禁止提前发生</dt><dd>{{ outlineContent.forbiddenEarlyEvents?.join('、') || '—' }}</dd></div>
            </dl>
          </n-card>

          <n-card title="本章权威基线" :bordered="false">
            <template v-if="session">
              <p class="muted">第 {{ session.chapterNum }} 章 · 状态：{{ session.status }}</p>
              <p class="muted">Planning R{{ session.planningRevision }}</p>
              <p class="small">Outline R{{ session.chapterOutlineRevision }} · StoryBlock R{{ session.storyBlockRevision }}</p>
            </template>
            <p v-else class="muted">确认本章小纲后，系统会在这里展示不可变的 Planning、StoryBlock 与 Outline 基线。</p>
          </n-card>

          </section>
          <section v-show="activeTool === 'versions'" id="tool-panel-versions" role="tabpanel" aria-labelledby="tool-tab-versions" class="tool-panel">
          <p class="muted">当前正在使用：正文工作稿 · {{ unicodeScalarLength(controller.editorText.value) }} 字</p>
          <n-card title="候选稿" :bordered="false">
            <n-statistic label="已保存候选" :value="candidates.length" />
            <ol v-if="candidates.length" class="candidate-list">
              <li v-for="(candidate, index) in candidates" :key="candidate.id" class="candidate-item">
                <label class="candidate-select">
                  <input
                    type="checkbox"
                    :checked="candidateSelected(candidate.id)"
                    :disabled="candidateSelectionDisabled(candidate.id)"
                    :aria-label="`选择候选 ${index + 1} 进行比较`"
                    @change="toggleCandidateSelection(candidate.id)"
                  >
                  <strong>候选 {{ index + 1 }}</strong>
                </label>
                <span class="candidate-basis" :class="candidate.basisStatus === 'current' ? 'candidate-basis--current' : 'candidate-basis--stale'">{{ candidate.basisStatus === 'current' ? '依据当前小纲' : '依据旧小纲，不能定稿' }}</span>
                <span class="candidate-meta">{{ candidateCharacterCount(candidate) }} 字 · {{ candidate.contentHash.slice(0, 8) }} · {{ formatCandidateTime(candidate.createdAt) }}</span>
                <n-button size="tiny" secondary :disabled="commandDisabled" :loading="controller.actionBusy.value" @click="openCandidatePreview(candidate)">查看与当前稿对比</n-button>
              </li>
            </ol>
            <p v-else class="muted">暂无候选。工作稿会自动暂存，按需保存为候选。</p>
            <n-button
              v-if="selectedCandidates.length === 2"
              class="saved-comparison-entry"
              :disabled="commandDisabled"
              @click="savedComparisonOpen = true"
            >对比所选两份候选稿</n-button>
          </n-card>
          </section>
        </aside>
      </section>
      <n-modal :show="Boolean(previewCandidate) || (savedComparisonOpen && selectedCandidates.length === 2)" preset="card" :title="previewCandidate ? '待定稿与当前正文对比' : '候选稿只读比较'" class="version-dialog" style="width:1060px;max-width:calc(100vw - 64px);height:min(680px,calc(100vh - 88px));background:var(--nc-paper);border-radius:6px;--n-title-font-size:25px" :mask-closable="!protectionBusy" :closable="!protectionBusy" :close-on-esc="!protectionBusy" @update:show="closeComparison">
        <p class="comparison-context">第 {{ chapterNumber }} 章 · 稿件对比</p>
        <div class="candidate-comparison" aria-label="稿件只读比较">
          <article v-for="pane in comparisonPanes" :key="pane.label" class="candidate-comparison-pane">
            <strong>{{ pane.label }}</strong><pre tabindex="0" :aria-label="pane.label">{{ pane.content || '暂无正文' }}</pre>
          </article>
        </div>
        <p class="comparison-notice">{{ previewCandidate ? '仅查看不会改变正文。确认切换前会先保存当前最新正文；保存失败时不会切换。' : '仅比较所选的两份已保存稿件，不会切换或修改当前正文。' }}</p>
        <n-alert v-if="previewCandidate && actionError" type="error" role="alert">{{ actionError }}</n-alert>
        <template #footer>
          <div class="comparison-actions">
            <n-button :disabled="protectionBusy" @click="closeComparison">关闭</n-button>
            <n-button v-if="previewCandidate" type="primary" :disabled="commandDisabled || protectionBusy" :loading="protectionBusy" @click="confirmCandidateSwitch">保留当前稿并确认切换</n-button>
          </div>
        </template>
      </n-modal>
      <n-modal :show="regenerationOpen" preset="card" title="重新生成正文" style="width:520px;max-width:calc(100vw - 64px)" :mask-closable="!protectionBusy" :closable="!protectionBusy" :close-on-esc="!protectionBusy" @update:show="!protectionBusy && (regenerationOpen = false)">
        <p>是否先将当前最新正文保存为待定稿？已有候选稿会保留。</p>
        <n-alert v-if="actionError" type="error" role="alert">{{ actionError }}</n-alert>
        <n-button :disabled="commandDisabled || protectionBusy" :loading="protectionBusy" @click="confirmRegeneration(true)">保留当前稿并重新生成</n-button>
        <n-button :disabled="commandDisabled || protectionBusy" @click="confirmRegeneration(false)">不保留本次正文，重新生成</n-button>
        <n-button :disabled="protectionBusy" @click="regenerationOpen = false">取消</n-button>
      </n-modal>
      <workbench-outline-dialog ref="outlineEditor" v-model:show="outlineDialogOpen" :project-id="projectId" :chapter-number="chapterNumber" @confirmed="handleOutlineConfirmed" />
      <n-modal :show="Boolean(reviewAdjustment)" preset="card" title="基于审稿意见调整整章" style="width:520px;max-width:calc(100vw - 64px)" :mask-closable="!protectionBusy" :closable="!protectionBusy" :close-on-esc="!protectionBusy" @update:show="!protectionBusy && (reviewAdjustment = null)">
        <p>先将当前正文保存为待定稿，再依据本稿未忽略的有效审稿意见调整整章。已忽略的建议不会采用。已有稿件会保留；调整后的正文需要重新审稿。</p>
        <n-alert v-if="actionError" type="error" role="alert">{{ actionError }}</n-alert>
        <n-button type="primary" color="#934735" :disabled="commandDisabled || reviewDirty || !reviewMatchesDraft" :loading="protectionBusy" @click="confirmReviewAdjustment">保存旧稿并按意见调整</n-button>
        <n-button :disabled="protectionBusy" @click="reviewAdjustment = null">取消</n-button>
      </n-modal>
    </template>
    </div>
  </section>
</template>

<style scoped>
.writer-shell { display:grid; grid-template-columns:200px minmax(0,1fr); gap:24px; height:100%; min-height:0; padding:0 24px 0 0; color:var(--nc-ink); background:var(--nc-canvas); overflow:hidden; }
.writer-body { min-width:0; min-height:0; display:flex; flex-direction:column; padding:20px 0 12px; }
.writer-shell :deep(.chapter-navigation) { width:200px; height:100%; overflow-y:auto; align-self:stretch; border-width:0 1px 0 0; }
.workspace-display-controls { display:flex; flex-wrap:wrap; gap:8px; margin:16px 0; }
.workspace-toolbar { display:grid; grid-template-columns:minmax(0,1fr) 320px; gap:20px; width:min(1180px,100%); margin:auto; }.tool-region-controls { display:flex; gap:12px; align-items:center; justify-content:space-between; color:var(--nc-muted); font-size:13px; } @media(max-width:900px) { .workspace-toolbar { grid-template-columns:1fr; gap:8px; } }
.workspace-grid.details-hidden { grid-template-columns:minmax(0,1fr); }
.tool-panel,.tool-selection { padding:12px; }
.tool-panel { overflow-wrap:anywhere; }
.tool-panel a { color:var(--nc-vermilion); }
.writer-loading, .writer-result, .writer-hero, .writer-alert, .workspace-grid { width: min(1180px, 100%); margin-inline: auto; }
.writer-loading { display: grid; gap: 20px; padding: 34px; border: 1px solid #ddd3c0; border-radius: 16px; background: #fffdf8; }
.writer-hero { display: flex; align-items: flex-end; justify-content: space-between; gap: 24px; padding-bottom: 0; }
.writer-navigation { display: flex; width: min(1180px, 100%); margin: 0 auto 16px; justify-content: flex-end; }
.writer-outline-link { color: #8b5c25; font-size: 13px; font-weight: 700; }
.eyebrow { margin: 0 0 8px; color: #967548; font-size: 10px; font-weight: 800; letter-spacing: .18em; }
h1 { margin: 0; font-family: Georgia, 'Noto Serif SC', serif; font-size: 26px; font-weight: 650; }
.writer-hero p:last-child { max-width: 64ch; margin: 12px 0 0; color: #786f62; line-height: 1.8; }
.writer-alert { margin-top: 20px; }
.workspace-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 20px; margin-top: 0; flex:1; min-height:0; }
.editor-card, .side-stack :deep(.n-card) { background: #fffdf8; box-shadow:none; }
.card-header { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.card-header strong { display: block; font-family: Georgia, 'Noto Serif SC', serif; font-size: 18px; }
.card-header span { color: #82786b; font-size: 12px; }
.editor-card { min-height:0; overflow:auto; border:1px solid var(--nc-border); border-radius:6px; }
.editor-card :deep(.n-card__content) { padding:12px; }
.editor-surface { position: relative; }
.editor-surface :deep(.plain-text-draft-editor) { overflow:auto; min-height:240px; height:calc(100vh - 355px); resize:none; font-size:17px; line-height:1.8; }
.draft-operation-layer { position: absolute; z-index: 2; top: 12px; right: 12px; display: flex; align-items: center; gap: 10px; max-width: calc(100% - 24px); max-height: 48px; overflow: auto; pointer-events: none; border: 1px solid rgba(150, 117, 72, .34); border-radius: 999px; padding: 8px 12px; color: #534535; background: rgba(255, 253, 248, .9); box-shadow: 0 8px 24px rgba(58, 48, 34, .1); font-size: 12px; font-weight: 700; }
.draft-operation-retry { pointer-events: auto; border: 0; padding: 0; color: #8b5c25; background: transparent; font: inherit; cursor: pointer; text-decoration: underline; }
.draft-operation-retry:focus-visible { outline: 2px solid #8b5c25; outline-offset: 3px; }
.selection-tools { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 10px; border-left: 3px solid #967548; padding: 8px 10px; background: #f8f1e5; }
.selection-tools > span { margin-right: 2px; color: #756858; font-size: 12px; font-weight: 700; }
.replacement-preview { margin-top: 10px; border: 1px solid #d8c7aa; border-radius: 8px; padding: 12px 14px; background: #f6efe2; box-shadow: inset 3px 0 0 #967548; }
.preview-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 14px; }
.replacement-preview strong { color: #76552f; font-size: 12px; letter-spacing: .08em; }
.replacement-preview pre { overflow: auto; max-height: 220px; margin: 8px 0 0; color: #40372d; white-space: pre-wrap; overflow-wrap: anywhere; font: 14px/1.8 Georgia, 'Noto Serif SC', serif; }
.draft-empty { min-height: 180px; display: grid; place-items: center; margin: 0; color: #81776a; border: 1px dashed #d7cbb8; border-radius: 10px; background: #fffefb; }
.partial-draft-recovery { margin-top: 14px; }
.partial-draft-actions { margin-top:10px; }
.generation-box { display: grid; gap: 8px; margin-top: 14px; }
.generation-box label { color: #70675c; font-size: 12px; font-weight: 700; }
.author-instruction-count { margin:0; color:var(--nc-muted); font-size:12px; line-height:1.7; text-align:left; }
.editor-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 16px; }
.writer-action-error { margin-top: 14px; }
.side-stack { min-height:0; overflow-y:auto; border:1px solid var(--nc-border); border-radius:6px; background:var(--nc-paper); }
.side-stack :deep(.n-card__content), .side-stack :deep(.n-card-header) { padding:12px 0; }
.muted { margin: 0; color: #81776a; line-height: 1.7; }
.small { margin: 10px 0 0; color: #9a8d7c; font-size: 12px; }
.outline-goal { margin: 0 0 14px; color: #433b32; font-family: Georgia, 'Noto Serif SC', serif; line-height: 1.7; }
.outline-summary { display: grid; gap: 12px; margin: 0; }
.outline-summary div { display: grid; gap: 3px; }
.outline-summary dt { color: #967548; font-size: 11px; font-weight: 800; letter-spacing: .08em; }
.outline-summary dd { margin: 0; color: #6f6559; font-size: 13px; line-height: 1.65; }
.candidate-list { display: grid; gap: 10px; margin: 14px 0 0; padding: 0; color: #675d51; font-size: 13px; list-style: none; }
.candidate-item { display: grid; gap: 7px; border: 1px solid #e1d6c4; border-radius: 9px; padding: 10px; background: #fffaf1; }
.candidate-select { display: flex; align-items: center; gap: 8px; color: #453b31; cursor: pointer; }
.candidate-select input { accent-color: #8b5c25; }
.candidate-basis { display: block; margin-top: 4px; font-size: 12px; }
.candidate-basis--current { color: #487252; }
.candidate-basis--stale { color: #a35b42; }
.candidate-meta { color: #8a7d6d; font-size: 11px; line-height: 1.5; }
.candidate-comparison { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:28px; border-top:1px solid var(--nc-border); padding-top:16px; }
.candidate-comparison-pane { min-width:0; }
.candidate-comparison-pane > strong { color:var(--nc-muted); font-size:13px; font-weight:400; }
.candidate-comparison-pane pre { overflow:auto; height:min(342px,calc(100vh - 370px)); margin:10px 0 0; padding:12px; border:1px solid var(--nc-border); border-radius:6px; color:var(--nc-ink); background:var(--nc-paper); white-space:pre-wrap; overflow-wrap:anywhere; font:15px/1.65 var(--font-sans, 'Noto Sans SC', sans-serif); }
.comparison-context, .comparison-notice { color:var(--nc-muted); font-size:14px; line-height:1.65; }
.comparison-context { margin:0 0 20px; }
.comparison-actions { display:flex; align-items:center; justify-content:space-between; gap:16px; }
.comparison-actions :deep(.n-button) { min-height:40px; border-radius:6px; }
.comparison-actions :deep(.n-button--primary-type) { background:var(--nc-vermilion); --n-border:1px solid var(--nc-vermilion); --n-border-hover:1px solid var(--nc-vermilion); --n-border-pressed:1px solid var(--nc-vermilion); --n-border-focus:1px solid var(--nc-vermilion); }
.comparison-actions :deep(.n-button--primary-type .n-button__border), .comparison-actions :deep(.n-button--primary-type .n-button__state-border) { border-color:var(--nc-vermilion); }
.saved-comparison-entry { margin-top:14px; }
@media (max-width: 900px) { .workspace-grid { grid-template-columns: 1fr; } .writer-hero { align-items: flex-start; flex-direction: column; } }
</style>

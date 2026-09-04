<script setup>
import { computed, nextTick, onServerPrefetch, ref, watch } from 'vue'
import { NAlert, NButton, NEmpty, NResult, NSkeleton, NSpin } from 'naive-ui'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'

import FoundationConfirmationDialog from '@/components/foundation/FoundationConfirmationDialog.vue'
import FoundationSectionIndex from '@/components/foundation/FoundationSectionIndex.vue'
import FoundationStatusRail from '@/components/foundation/FoundationStatusRail.vue'
import FoundationWorkspace from '@/components/foundation/FoundationWorkspace.vue'
import SeedCard from '@/components/seeds/SeedCard.vue'
import SeedDocument from '@/components/seeds/SeedDocument.vue'
import SeedEditor from '@/components/seeds/SeedEditor.vue'
import SeedOtherCandidatesDrawer from '@/components/seeds/SeedOtherCandidatesDrawer.vue'
import { presentSeedProvenance } from '@/components/seeds/seedProvenancePresenter.js'
import { useAppMessage } from '@/composables/useAppMessage'
import { useRouteProject } from '@/composables/useRouteProject'
import { useSeedStore } from '@/stores/seedStore'

const props = defineProps({ projectId: { type: String, required: true } })
const routeProject = useRouteProject()
const seedStore = useSeedStore()
const message = useAppMessage()
const loadError = ref('')
const openedSeedId = ref('')
const creatingCandidate = ref(false)
const createIdempotencyKey = ref('')
const activeSection = ref('')
const candidateWorkCopy = ref({})
const workCopyBase = ref(null)
const sectionEntrySnapshot = ref(null)
const authoritativeDraftAvailable = ref(false)
const selectionTarget = ref(null)
const lifecycleTarget = ref(null)
const conflictMessage = ref('')
const confirmationBlock = ref('')
const reconciliationRequired = ref(false)
const validationError = ref('')
const mutationStatus = ref('')
let workspaceProjectId = ''
let workspaceGeneration = 0
let authorizedRouteProjectId = ''
let candidateEpoch = 0

const readOnly = computed(() => routeProject.state.value === 'archived' || routeProject.project.value?.archivedAt != null)
const inspectableCandidates = computed(() => seedStore.seeds.filter(seed => !seed.isSelected && ['candidate', 'archived'].includes(seed.status)))
const activeCandidates = computed(() => inspectableCandidates.value.filter(seed => seed.status === 'candidate'))
const archivedCandidates = computed(() => inspectableCandidates.value.filter(seed => seed.status === 'archived'))
const openedCandidate = computed(() => inspectableCandidates.value.find(seed => seed.id === openedSeedId.value) || null)
const confirmedSeed = computed(() => seedStore.selectedSeed || seedStore.seeds.find(seed => seed.isSelected) || null)
const newCandidate = computed(() => creatingCandidate.value ? {
  id: '', status: 'candidate', revision: 0, payload: candidateWorkCopy.value,
  capabilities: { canEdit: true, canSelect: false }, provenance: { kind: 'manual', snapshots: [], publicNotes: [] },
} : null)
const editableSeed = computed(() => openedCandidate.value || (readOnly.value ? null : newCandidate.value))
const mainSeed = computed(() => confirmedSeed.value || editableSeed.value)
const mainReadOnly = computed(() => readOnly.value || Boolean(confirmedSeed.value) || mainSeed.value?.status === 'archived')
const lifecycleStatus = computed(() => {
  if (readOnly.value) return { label: '只读归档', description: '只读归档' }
  if (mainSeed.value?.status === 'archived') return { label: '只读归档', description: '只读归档' }
  if (confirmedSeed.value) return { label: '已确认 / 已冻结', description: '已确认并永久冻结' }
  if (mainSeed.value) return { label: '候选校订中', description: '候选校订中' }
  return { label: '等待选择候选', description: '等待选择候选' }
})
const documentReadOnly = computed(() => mainReadOnly.value || !seedStore.selectionHydrated)
const mainPayload = computed(() => confirmedSeed.value ? confirmedSeed.value.payload : (mainReadOnly.value ? mainSeed.value?.payload : candidateWorkCopy.value))
const localDirty = computed(() => Boolean(workCopyBase.value) && seedFields.some(key => String(candidateWorkCopy.value?.[key] || '').trim() !== String(workCopyBase.value.payload?.[key] || '').trim()))
const orphanedLocalDraft = computed(() => localDirty.value && (readOnly.value || Boolean(confirmedSeed.value)
  || (workCopyBase.value?.seedId && (!openedCandidate.value || openedCandidate.value.revision !== workCopyBase.value.revision))))
const authorActionsAvailable = computed(() => !readOnly.value && !confirmedSeed.value && seedStore.selectionHydrated)
const contextBusy = computed(() => seedStore.mutationBusy || seedStore.loading || seedStore.refreshing)
const canCreateCandidate = computed(() => authorActionsAvailable.value && !contextBusy.value)
const selectionReasons = computed(() => mainSeed.value?.capabilities?.selectionReasons || mainSeed.value?.capabilities?.reasons || seedStore.readiness.reasons || [])
const confirmationAdapter = computed(() => {
  const candidate = selectionTarget.value
  return {
    candidate,
    candidateRevision: candidate?.revision ?? null,
    payload: candidate?.payload || {},
    provenance: presentSeedProvenance(candidate?.provenance),
    canConfirm: Boolean(authorActionsAvailable.value && candidate?.capabilities?.canSelect),
  }
})
const confirmationFields = Object.freeze([['title', '标题'], ['genre', '题材'], ['logline', '一句话故事'], ['protagonist', '主角'], ['desire', '核心欲望'], ['coreConflict', '核心冲突'], ['worldPressure', '世界压力'], ['openingHook', '开篇钩子'], ['differentiation', '差异化'], ['targetAudience', '目标读者'], ['storyPromise', '故事承诺'], ['longFormPotential', '长篇潜力'], ['marketBasis', '市场依据']])
const seedFields = Object.freeze(confirmationFields.map(([key]) => key))
const sectionFieldKeys = Object.freeze({ positioning: ['title', 'genre', 'targetAudience'], core: ['logline', 'protagonist', 'desire', 'coreConflict'], pressure: ['worldPressure', 'openingHook'], promise: ['differentiation', 'storyPromise', 'longFormPotential', 'marketBasis'] })
const readinessReasonLabels = Object.freeze({ seed_not_selected: '尚未确认项目种子', creation_contract_missing: '尚未创建创作契约', selected_seed_drift: '选定种子已发生漂移', binding_not_verified: '项目绑定尚未验证' })

function sectionDisplayState(section) {
  const complete = (sectionFieldKeys[section] || []).every(key => String(mainPayload.value?.[key] || '').trim())
  return complete ? { status: 'filled', label: '已记录' } : { status: 'suggested', label: '可补充' }
}
const sectionItems = computed(() => [
  { key: 'positioning', label: '作品定位', targetId: 'seed-positioning', disabled: contextBusy.value, status: activeSection.value === 'positioning' ? 'current' : sectionDisplayState('positioning').status, statusLabel: activeSection.value === 'positioning' ? '编辑中' : sectionDisplayState('positioning').label },
  { key: 'core', label: '故事核心', targetId: 'seed-core', disabled: contextBusy.value, status: activeSection.value === 'core' ? 'current' : sectionDisplayState('core').status, statusLabel: activeSection.value === 'core' ? '编辑中' : sectionDisplayState('core').label },
  { key: 'pressure', label: '开篇与压力', targetId: 'seed-pressure', disabled: contextBusy.value, status: activeSection.value === 'pressure' ? 'current' : sectionDisplayState('pressure').status, statusLabel: activeSection.value === 'pressure' ? '编辑中' : sectionDisplayState('pressure').label },
  { key: 'promise', label: '差异与承诺', targetId: 'seed-promise', disabled: contextBusy.value, status: activeSection.value === 'promise' ? 'current' : sectionDisplayState('promise').status, statusLabel: activeSection.value === 'promise' ? '编辑中' : sectionDisplayState('promise').label },
])

function blankPayload() { return Object.fromEntries(seedFields.map(key => [key, ''])) }
function normalizedPayload(payload) { return Object.fromEntries(seedFields.map(key => [key, String(payload?.[key] || '').trim()])) }
function beginWorkCopy(seed = null) { const payload = normalizedPayload(seed?.payload); candidateWorkCopy.value = payload; workCopyBase.value = { seedId: String(seed?.id || ''), revision: Number(seed?.revision || 0), payload } }
function clearWorkCopy() { candidateWorkCopy.value = {}; workCopyBase.value = null }
function payloadComplete(payload) { return seedFields.slice(0, 9).every(key => String(payload?.[key] || '').trim()) }
function missingRequiredFields(payload) { return confirmationFields.slice(0, 9).filter(([key]) => !String(payload?.[key] || '').trim()).map(([, label]) => label) }
function newIdempotencyKey() { return `${globalThis.crypto.randomUUID().replaceAll('-', '')}${globalThis.crypto.randomUUID().replaceAll('-', '')}` }
function focusElement(id, scroll = false) { void nextTick(() => { const target = globalThis.document?.getElementById?.(id); if (scroll) { const reducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true; target?.scrollIntoView?.({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' }) }; target?.focus?.({ preventScroll: true }) }) }
function clearReconciledDraftState() { conflictMessage.value = ''; authoritativeDraftAvailable.value = false }
function rejectContextChange() { message.warning('当前操作尚未完成，请稍候'); return true }
function captureCandidateContext() { return { projectId: String(props.projectId), generation: workspaceGeneration, epoch: candidateEpoch, openedSeedId: openedSeedId.value, creating: creatingCandidate.value } }
function isCurrentCandidateContext(context) { return isCurrentWorkspace(context.projectId, context.generation) && candidateEpoch === context.epoch && openedSeedId.value === context.openedSeedId && creatingCandidate.value === context.creating }

function resetProjectWorkspace(projectId) { workspaceProjectId = String(projectId); workspaceGeneration += 1; candidateEpoch += 1; loadError.value = ''; openedSeedId.value = ''; creatingCandidate.value = false; createIdempotencyKey.value = ''; activeSection.value = ''; sectionEntrySnapshot.value = null; clearWorkCopy(); clearReconciledDraftState(); selectionTarget.value = null; lifecycleTarget.value = null; confirmationBlock.value = ''; reconciliationRequired.value = false; validationError.value = ''; mutationStatus.value = ''; seedStore.activateProject(projectId) }
function isCurrentWorkspace(projectId, generation) { return workspaceProjectId === String(projectId) && workspaceGeneration === generation }
function confirmDiscard() { return !localDirty.value || globalThis.confirm?.('当前候选有未保存修改，放弃修改吗？') === true }
function discardCurrent(action) { if (!confirmDiscard()) return false; activeSection.value = ''; sectionEntrySnapshot.value = null; clearWorkCopy(); clearReconciledDraftState(); action(); return true }
function startCandidate(seed) { if (contextBusy.value) return rejectContextChange(); if (!seed || confirmedSeed.value) return; discardCurrent(() => { candidateEpoch += 1; creatingCandidate.value = false; createIdempotencyKey.value = ''; openedSeedId.value = seed.id; beginWorkCopy(seed); activeSection.value = ''; confirmationBlock.value = ''; validationError.value = ''; focusElement('seed-document-heading') }) }
function startNewCandidate() { if (contextBusy.value) return rejectContextChange(); if (!canCreateCandidate.value) return; discardCurrent(() => { candidateEpoch += 1; creatingCandidate.value = true; createIdempotencyKey.value = newIdempotencyKey(); openedSeedId.value = ''; beginWorkCopy(); activeSection.value = ''; confirmationBlock.value = ''; validationError.value = ''; focusElement('seed-document-heading') }) }
function returnToList() { if (contextBusy.value) return rejectContextChange(); discardCurrent(() => { candidateEpoch += 1; openedSeedId.value = ''; creatingCandidate.value = false; createIdempotencyKey.value = ''; activeSection.value = ''; validationError.value = ''; focusElement('seed-candidate-list-heading') }) }
async function loadWorkspace(projectId = props.projectId) { const generation = workspaceGeneration; if (isCurrentWorkspace(projectId, generation)) loadError.value = ''; try { await seedStore.refresh(projectId); return isCurrentWorkspace(projectId, generation) } catch (failure) { if (isCurrentWorkspace(projectId, generation)) loadError.value = failure?.message || '项目种子加载失败'; return false } }
function allowNavigation() { if (seedStore.mutationBusy) { message.warning('种子操作正在进行，请等待完成后再离开。'); return false }; return confirmDiscard() }
watch(() => [props.projectId, routeProject.state.value], ([projectId, state]) => { if (!projectId) return; if (workspaceProjectId !== String(projectId)) { if (authorizedRouteProjectId === String(projectId)) authorizedRouteProjectId = ''; else if (!allowNavigation()) return; resetProjectWorkspace(projectId) }; if (['active', 'archived'].includes(state)) void loadWorkspace(projectId) }, { immediate: true })
onServerPrefetch(() => loadWorkspace(props.projectId))
onBeforeRouteLeave(() => allowNavigation())
onBeforeRouteUpdate(to => { if (!allowNavigation()) return false; authorizedRouteProjectId = String(to.params.projectId || ''); return true })

function captureSectionSnapshot(section) { sectionEntrySnapshot.value = { section, values: Object.fromEntries((sectionFieldKeys[section] || []).map(key => [key, candidateWorkCopy.value[key] || ''])) } }
function restoreSectionSnapshot() { if (sectionEntrySnapshot.value) candidateWorkCopy.value = { ...candidateWorkCopy.value, ...sectionEntrySnapshot.value.values } }
function sectionChanged() { return Boolean(sectionEntrySnapshot.value) && Object.entries(sectionEntrySnapshot.value.values).some(([key, value]) => String(candidateWorkCopy.value[key] || '') !== String(value || '')) }
function navigateSection(section) { if (contextBusy.value) return rejectContextChange(); if (mainReadOnly.value) { focusElement(`seed-${section}`, true); return }; editSection(section) }
function editSection(section) { if (contextBusy.value) return rejectContextChange(); if (!authorActionsAvailable.value || !mainSeed.value?.capabilities?.canEdit || mainReadOnly.value || section === activeSection.value) return; if (activeSection.value && sectionChanged()) { if (globalThis.confirm?.('当前分区有未完成修改，放弃本区修改吗？') !== true) return; restoreSectionSnapshot() }; activeSection.value = section; captureSectionSnapshot(section); focusElement(`seed-${section}`, true) }
function finishSection() { if (contextBusy.value) return rejectContextChange(); const section = activeSection.value; activeSection.value = ''; sectionEntrySnapshot.value = null; focusElement(`seed-${section}`, true) }
function cancelSection() { if (contextBusy.value) return rejectContextChange(); const section = activeSection.value; restoreSectionSnapshot(); activeSection.value = ''; sectionEntrySnapshot.value = null; focusElement(`seed-${section}`, true) }
async function saveSeed() {
  const editTarget = openedCandidate.value
  const payload = normalizedPayload(candidateWorkCopy.value)
  if (!authorActionsAvailable.value) return
  const missing = missingRequiredFields(payload)
  if (missing.length) { validationError.value = `请填写必填项：${missing.join('、')}`; return }
  validationError.value = ''
  if (creatingCandidate.value) {
    if (!canCreateCandidate.value || !localDirty.value) return
    const projectId = props.projectId; const generation = workspaceGeneration; const context = captureCandidateContext()
    mutationStatus.value = '正在创建候选种子'
    try {
      const created = await seedStore.createSeed(projectId, payload, { provenance: { kind: 'manual', snapshotIds: [], analysisId: null, inspirationAttemptId: null, publicNotes: [] }, idempotencyKey: createIdempotencyKey.value })
      if (isCurrentWorkspace(projectId, generation) && isCurrentCandidateContext(context)) { candidateEpoch += 1; creatingCandidate.value = false; createIdempotencyKey.value = ''; openedSeedId.value = created.id; beginWorkCopy(created); clearReconciledDraftState(); mutationStatus.value = '候选种子已创建'; message.success('候选种子已创建'); focusElement('seed-document-heading') }
    } catch (failure) { if (isCurrentWorkspace(projectId, generation) && isCurrentCandidateContext(context)) { mutationStatus.value = '候选种子创建失败'; if (!seedStore.selectionHydrated) reconciliationRequired.value = true; else message.error(failure?.message || '候选种子创建失败') } }
    return
  }
  if (!editTarget || mainReadOnly.value || !editTarget.capabilities?.canEdit || !localDirty.value) return
  const projectId = props.projectId; const generation = workspaceGeneration; const context = captureCandidateContext(); conflictMessage.value = ''; authoritativeDraftAvailable.value = false
  mutationStatus.value = '正在保存种子'
  try {
    const updated = await seedStore.updateSeed(projectId, editTarget.id, { payload, expectedSeedRevision: editTarget.revision, expectedSelectionRevision: seedStore.selectionRevision })
    if (isCurrentWorkspace(projectId, generation) && isCurrentCandidateContext(context)) { beginWorkCopy(updated); mutationStatus.value = '种子修订已保存'; message.success('种子修订已保存'); focusElement('seed-document-heading') }
  } catch (failure) {
    if (!isCurrentWorkspace(projectId, generation) || !isCurrentCandidateContext(context)) return
    mutationStatus.value = '种子保存失败'
    if (Number(failure?.status) === 409 || /conflict/i.test(String(failure?.code || ''))) { conflictMessage.value = '此候选已被其他修订更新。当前本地工作副本已保留。'; reconciliationRequired.value = !seedStore.selectionHydrated }
    if (!seedStore.selectionHydrated) { reconciliationRequired.value = true; return }
    message.error(failure?.message || '种子保存失败')
  }
}
async function lifecycle(seed, kind) {
  if (contextBusy.value) return rejectContextChange()
  if (!authorActionsAvailable.value) return
  const context = captureCandidateContext()
  const data = { expectedSeedRevision: seed.revision, expectedSelectionRevision: seedStore.selectionRevision }
  mutationStatus.value = kind === 'delete' ? '正在永久删除候选种子' : kind === 'archive' ? '正在归档候选种子' : '正在恢复候选种子'
  try {
    if (kind === 'archive') await seedStore.archiveSeed(props.projectId, seed.id, data)
    if (kind === 'restore') await seedStore.restoreSeed(props.projectId, seed.id, data)
    if (kind === 'delete') await seedStore.permanentlyDeleteSeed(props.projectId, seed.id, data)
    if (isCurrentCandidateContext(context) && openedSeedId.value === seed.id && kind !== 'restore') { candidateEpoch += 1; openedSeedId.value = ''; creatingCandidate.value = false; activeSection.value = ''; sectionEntrySnapshot.value = null; clearWorkCopy(); clearReconciledDraftState(); focusElement('seed-candidate-list-heading') }
    mutationStatus.value = kind === 'delete' ? '候选种子已永久删除' : kind === 'archive' ? '候选种子已归档' : '候选种子已恢复'
    return true
  } catch (failure) { mutationStatus.value = '候选种子操作失败'; if (!seedStore.selectionHydrated) { reconciliationRequired.value = true; if (kind === 'delete' && !seedStore.selectionHydrated) { lifecycleTarget.value = null; confirmationBlock.value = '删除结果尚未确认，请重新加载权威状态' } } else message.error(failure?.message || '候选操作失败'); return false }
}
function requestDelete(seed) { if (contextBusy.value) return rejectContextChange(); if (authorActionsAvailable.value && seed?.capabilities?.canPermanentlyDelete) lifecycleTarget.value = seed }
async function deleteSeed() { if (!lifecycleTarget.value) return; if (await lifecycle(lifecycleTarget.value, 'delete')) { lifecycleTarget.value = null; focusElement('seed-candidate-list-heading') } }
function closeLifecycleDialog() { if (!seedStore.mutationBusy) lifecycleTarget.value = null }
function discardOrphanedWorkCopy() { if (openedCandidate.value) beginWorkCopy(openedCandidate.value); else clearWorkCopy(); conflictMessage.value = ''; authoritativeDraftAvailable.value = false; validationError.value = ''; mutationStatus.value = '本地副本已放弃' }
async function reloadAuthoritative() {
  if (contextBusy.value) return rejectContextChange()
  const projectId = props.projectId; const generation = workspaceGeneration; const context = captureCandidateContext()
  const localPayload = normalizedPayload(candidateWorkCopy.value)
  const preserveLocal = localDirty.value
  loadError.value = ''
  try {
    await seedStore.refresh(projectId)
    if (!isCurrentWorkspace(projectId, generation) || !isCurrentCandidateContext(context)) return
    reconciliationRequired.value = false
    if (!preserveLocal) { conflictMessage.value = ''; authoritativeDraftAvailable.value = false; if (confirmedSeed.value) focusElement('seed-document-heading'); return }
    candidateWorkCopy.value = localPayload
    conflictMessage.value = '权威版本已更新，本地修改仍保留，请核对后保存'
    authoritativeDraftAvailable.value = Boolean(openedCandidate.value) && localDirty.value
    if (confirmedSeed.value) focusElement('seed-document-heading')
  } catch (failure) {
    if (isCurrentWorkspace(projectId, generation)) loadError.value = failure?.message || '权威状态重新加载失败'
  }
}
function adoptAuthoritativeVersion() { if (!authoritativeDraftAvailable.value || !openedCandidate.value || globalThis.confirm?.('将放弃本地修改并采用权威版本，无法撤销。继续吗？') !== true) return; beginWorkCopy(openedCandidate.value); authoritativeDraftAvailable.value = false; conflictMessage.value = ''; focusElement('seed-document-heading') }
function openConfirmation() { if (contextBusy.value) return rejectContextChange(); if (activeSection.value || localDirty.value) { confirmationBlock.value = '请先保存本地修改'; return }; if (!authorActionsAvailable.value) { confirmationBlock.value = '权威状态尚未加载，请重新加载权威状态'; return }; confirmationBlock.value = ''; selectionTarget.value = mainSeed.value }
async function selectSeed(seed) {
  if (contextBusy.value) return rejectContextChange()
  if (localDirty.value) { confirmationBlock.value = '请先保存本地修改'; selectionTarget.value = null; return }
  if (!authorActionsAvailable.value || !seed?.capabilities?.canSelect || seed.id !== mainSeed.value?.id || seed.revision !== mainSeed.value?.revision) return
  const projectId = props.projectId; const generation = workspaceGeneration; const context = captureCandidateContext()
  mutationStatus.value = '正在确认项目种子'
  try { await seedStore.selectSeed(projectId, { seedId: seed.id, expectedSeedRevision: seed.revision, expectedSelectionRevision: seedStore.selectionRevision }); if (isCurrentWorkspace(projectId, generation) && isCurrentCandidateContext(context)) { selectionTarget.value = null; mutationStatus.value = '项目种子已确认'; message.success(`已确认《${seed.payload?.title || '未命名种子'}》`); focusElement('seed-document-heading') } } catch (failure) { if (isCurrentWorkspace(projectId, generation) && isCurrentCandidateContext(context)) { selectionTarget.value = null; mutationStatus.value = '项目种子确认失败'; if (!seedStore.selectionHydrated) reconciliationRequired.value = true; else message.error(failure?.message || '种子确认失败'); focusElement('seed-document-heading') } }
}
function confirmSelection() { return selectSeed(confirmationAdapter.value.candidate) }
function closeSelectionDialog() { if (!seedStore.mutationBusy) selectionTarget.value = null }
</script>

<template>
  <section v-if="routeProject.state.value === 'loading'" class="seed-loading" aria-busy="true"><n-skeleton text width="32%" /><n-skeleton text :repeat="4" /></section>
  <section v-else-if="routeProject.state.value === 'missing'"><n-result status="404" title="项目不存在或已被删除" description="系统不会打开另一个项目作为替代。" /></section>
  <section v-else-if="routeProject.state.value === 'error'"><n-result status="error" title="项目暂时无法加载" :description="routeProject.error.value?.message || '请稍后重试'"><template #footer><n-button @click="routeProject.reload">重新加载项目</n-button></template></n-result></section>
  <FoundationWorkspace v-else title="创作种子" purpose="确认前逐区校订候选；确认后，所选修订将作为项目永久创作基线。" :status-label="lifecycleStatus.label" :read-only="mainReadOnly">
    <template #index><FoundationSectionIndex v-if="mainSeed" :items="sectionItems" :current-key="activeSection" :focus-on-navigate="false" @navigate="navigateSection" /><p v-else class="candidate-index">先选择一份候选，查看完整创作种子。</p></template>
    <template #document><n-alert v-if="readOnly" type="warning" :bordered="false">已归档 · 只读</n-alert><n-alert v-if="orphanedLocalDraft" type="warning" :bordered="false">本地未保存副本已保留，不作为当前权威内容。项目或候选恢复为可编辑状态后可继续校订。<template #action><n-button text @click="discardOrphanedWorkCopy">放弃本地副本</n-button></template></n-alert><n-alert v-if="loadError" type="error" :bordered="false">{{ loadError }}<template #action><n-button text @click="loadWorkspace()">重新加载种子</n-button></template></n-alert><n-alert v-if="reconciliationRequired" type="warning" :bordered="false">权威状态尚未加载；已保留当前本地工作副本，所有写入和确认操作均已停用。<template #action><n-button text :disabled="contextBusy" @click="reloadAuthoritative">重新加载权威状态</n-button></template></n-alert><n-alert v-if="conflictMessage" type="warning" :bordered="false">{{ conflictMessage }} <template #action><n-button text :disabled="contextBusy" @click="reloadAuthoritative">重新加载权威状态</n-button><n-button v-if="authoritativeDraftAvailable" text :disabled="contextBusy" @click="adoptAuthoritativeVersion">放弃本地修改并采用权威版本</n-button></template></n-alert><n-alert v-if="validationError" type="warning" :bordered="false">{{ validationError }}</n-alert><n-alert v-if="confirmationBlock" type="warning" :bordered="false">{{ confirmationBlock }}</n-alert><n-spin :show="seedStore.loading"><section v-if="!mainSeed && !seedStore.loading" class="candidate-list"><p>候选种子</p><h2 id="seed-candidate-list-heading" tabindex="-1">从一份候选开始校订</h2><n-button v-if="canCreateCandidate" type="primary" :disabled="contextBusy" @click="startNewCandidate">新建候选种子</n-button><p v-if="activeCandidates.length" class="candidate-list__group">待校订候选</p><SeedCard v-for="seed in activeCandidates" :key="seed.id" :seed="seed" :read-only="!authorActionsAvailable" :busy="contextBusy" @open="startCandidate" @archive="lifecycle($event, 'archive')" @restore="lifecycle($event, 'restore')" @delete="requestDelete" /><p v-if="archivedCandidates.length" class="candidate-list__group">已归档候选</p><SeedCard v-for="seed in archivedCandidates" :key="seed.id" :seed="seed" :read-only="!authorActionsAvailable" :busy="contextBusy" @open="startCandidate" @archive="lifecycle($event, 'archive')" @restore="lifecycle($event, 'restore')" @delete="requestDelete" /><n-empty v-if="!inspectableCandidates.length" description="还没有可查看的项目种子。" /></section><section v-else-if="mainSeed"><n-button v-if="!confirmedSeed" text :disabled="contextBusy" @click="returnToList">返回候选列表</n-button><p class="document-kicker">完整内容</p><SeedDocument :seed="mainSeed" :payload="mainPayload" :active-section="activeSection" :read-only="documentReadOnly" @edit-section="editSection"><template #editor="{ section }"><SeedEditor :model-value="candidateWorkCopy" :section="section" :busy="contextBusy" :read-only="documentReadOnly" @update:model-value="candidateWorkCopy = $event; validationError = ''" @complete="finishSection" @cancel="cancelSection" /></template></SeedDocument></section></n-spin></template>
    <template #status><p class="seed-live-status" role="status" aria-live="polite">{{ mutationStatus }}</p><FoundationStatusRail :read-only="documentReadOnly"><template #summary><strong>用途</strong><p>把作品定位与长篇承诺固定为后续创作的唯一源头。</p><strong class="rail-heading">上游摘要</strong><p>{{ mainSeed ? `${mainPayload?.title || '未命名种子'} · ${mainPayload?.genre || '题材待补充'}` : '尚未选择候选种子。' }}</p></template><template #status><strong>生命周期</strong><p>{{ lifecycleStatus.description }}</p><strong class="rail-heading">可编辑性</strong><p>{{ documentReadOnly ? '全文只读' : localDirty ? '可编辑 · 存在未保存修改' : '可编辑 · 当前修订已保存。' }}</p><p v-if="authorActionsAvailable && mainSeed?.capabilities?.canSelect">服务端允许确认</p><p v-else>{{ mainSeed ? (seedStore.selectionHydrated ? (selectionReasons.map(reason => readinessReasonLabels[reason] || '种子状态需要重新核对').join('；') || '服务端当前不允许确认') : '权威状态尚未加载') : '请先查看一份候选。' }}</p></template><template #source><strong>来源与诊断</strong><SeedOtherCandidatesDrawer v-if="confirmedSeed" :seeds="seedStore.seeds" /><template v-else>来源记录随候选保存；这里只展示作者可读结论，不展示内部字段名。</template></template><template #action><n-button v-if="authorActionsAvailable && mainSeed?.capabilities?.canEdit" :disabled="contextBusy || Boolean(activeSection) || !localDirty" @click="saveSeed">{{ creatingCandidate ? '创建候选种子' : '保存种子' }}</n-button><n-button v-if="authorActionsAvailable && mainSeed && !creatingCandidate" type="primary" :disabled="contextBusy || Boolean(activeSection) || localDirty || !mainSeed.capabilities?.canSelect" @click="openConfirmation">确认项目种子</n-button></template></FoundationStatusRail></template>
  </FoundationWorkspace>
  <FoundationConfirmationDialog v-if="selectionTarget" :open="Boolean(selectionTarget)" :close-disabled="seedStore.mutationBusy" title="确认项目种子" @close="closeSelectionDialog"><template #snapshot><p>请确认将要持久化选择的同一份种子修订。确认后保持在当前页面，且不可再编辑或切换。</p><p>种子修订：{{ confirmationAdapter.candidateRevision }}</p><dl class="confirmation-fields"><div v-for="[key, label] in confirmationFields" :key="key"><dt>{{ label }}</dt><dd>{{ confirmationAdapter.payload?.[key] || '建议补充' }}</dd></div></dl></template><template #source><strong>来源与诊断</strong><p>{{ confirmationAdapter.provenance.label }}</p><p>种子修订：{{ confirmationAdapter.candidateRevision }}</p><p v-for="item in confirmationAdapter.provenance.basis" :key="item">{{ item }}</p><p v-for="note in (confirmationAdapter.candidate?.provenance?.publicNotes || [])" :key="note">{{ note }}</p><p>{{ confirmationAdapter.canConfirm ? '服务端允许确认。' : '权威状态尚未加载，不能确认。' }}</p></template><template #action><n-button :disabled="seedStore.mutationBusy" @click="closeSelectionDialog">取消</n-button><n-button type="primary" :disabled="!confirmationAdapter.canConfirm" :loading="seedStore.mutationBusy" @click="confirmSelection">确认项目种子</n-button></template></FoundationConfirmationDialog>
  <FoundationConfirmationDialog v-if="lifecycleTarget" :open="Boolean(lifecycleTarget)" :close-disabled="contextBusy" title="永久删除候选种子" @close="closeLifecycleDialog"><template #snapshot><p>此操作会永久删除候选种子，无法恢复。</p><p>候选：{{ lifecycleTarget.payload?.title || '未命名候选' }}</p><p>种子修订：{{ lifecycleTarget.revision }}</p></template><template #source><p>只会删除当前显示的同一修订。</p></template><template #action><n-button :disabled="contextBusy" @click="closeLifecycleDialog">取消</n-button><n-button type="primary" :loading="contextBusy" @click="deleteSeed">永久删除</n-button></template></FoundationConfirmationDialog>
</template>

<style scoped>
.seed-loading{display:grid;gap:16px;padding:clamp(22px,4vw,52px)}.seed-live-status{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.candidate-index{margin:16px 0;color:var(--nc-muted);font:12px/1.65 Georgia,'Noto Serif SC',serif}.candidate-list{display:grid;gap:12px;padding:clamp(26px,6vw,68px)}.candidate-list>p,.document-kicker{margin:0;color:var(--nc-vermilion);font:700 10px Georgia,'Noto Serif SC',serif;letter-spacing:.16em}.document-kicker{padding:16px 38px 0}.candidate-list__group{padding-top:10px;border-top:1px solid var(--nc-border)}.candidate-list h2{margin:0 0 8px;font:600 clamp(28px,4vw,42px)/1.25 Georgia,'Noto Serif SC',serif}.foundation-status-rail p{margin:5px 0 0;color:var(--nc-muted);font:12px/1.65 Georgia,'Noto Serif SC',serif}.rail-heading{display:block;margin-top:14px}.confirmation-fields{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 15px;margin:14px 0 0}.confirmation-fields dt{color:var(--nc-vermilion);font-size:11px}.confirmation-fields dd{margin:2px 0 0;font:12px/1.5 Georgia,'Noto Serif SC',serif}@media(max-width:560px){.confirmation-fields{grid-template-columns:1fr}}
</style>

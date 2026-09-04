<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave, onBeforeRouteUpdate } from 'vue-router'
import { NAlert, NButton, NResult, NSkeleton, NTag } from 'naive-ui'

import FoundationDocumentSection from '@/components/foundation/FoundationDocumentSection.vue'
import FoundationConfirmationDialog from '@/components/foundation/FoundationConfirmationDialog.vue'
import FoundationSectionIndex from '@/components/foundation/FoundationSectionIndex.vue'
import FoundationStatusRail from '@/components/foundation/FoundationStatusRail.vue'
import FoundationWorkspace from '@/components/foundation/FoundationWorkspace.vue'
import { contractDocumentSections } from '@/application/contracts/contractDocumentSections.js'
import { projectSeedsPath } from '@/router/projectRoutes.js'
import { useCreationContractStore } from '@/stores/creationContractStore.js'
import { useSeedStore } from '@/stores/seedStore.js'
import { createLatestRequestGuard } from '@/utils/latestRequest.js'
import AssetScopeStep from './contract/AssetScopeStep.vue'
import CapacityStep from './contract/CapacityStep.vue'
import ContractDecisionSummary from './contract/ContractDecisionSummary.vue'
import ContractHistoryDrawer from './contract/ContractHistoryDrawer.vue'
import ContractPreviewStep from './contract/ContractPreviewStep.vue'
import StoryEngineStep from './contract/StoryEngineStep.vue'
import StyleSelectionStep from './contract/StyleSelectionStep.vue'

const props = defineProps({
  projectId: { type: String, required: true },
  project: { type: Object, default: null },
  readOnly: { type: Boolean, default: false },
})

const seedStore = useSeedStore()
const contractStore = useCreationContractStore()
const loadGuard = createLatestRequestGuard()
const loading = ref(true)
const loadError = ref('')
const loadErrorRegion = ref(null)
const activeSectionKey = ref('')
const childWriteBusy = ref(false)
const busyNotice = ref('')
const liveStatus = ref('')
const historyOpen = ref(false)
const reloadDecisionOpen = ref(false)
const reloadNoticeRegion = ref(null)

const sectionResponsibilities = Object.freeze({
  engine: '把已确认种子转成三套可比较的长篇发动机，并由作者明确采用一套。',
  capacity: '记录整书字数、卷章规模、单章范围与留给未来写作的作者备注。',
  assets: '明确冻结哪些经验卡和语料片段；推荐始终只是候选，不会自动纳入。',
  style: '先阅读完整风格样例和临时试写，再采用主风格、辅风格及作者偏好。',
  prohibitions: '把不应进入规划与正文的方向写成明确、可核对的边界。',
  preview: '以服务器返回的快照、摘要、冻结引用和就绪原因完成最终核对。',
})
const sectionPrerequisites = Object.freeze({
  engine: '前置条件：先确认一个当前有效的创作种子。',
  capacity: '前置条件：先依次保存故事发动机、风格方案和正式资产范围。',
  assets: '前置条件：先保存故事发动机和风格方案。',
  style: '前置条件：先保存故事发动机。',
  prohibitions: '前置条件：先依次保存故事发动机、风格方案和正式资产范围。',
  preview: '前置条件：先保存正式资产范围，由服务器开放完整预览。',
})
const reasonLabels = Object.freeze({
  contract_revision_replaced: '已被更新修订取代',
  selection_revision_changed: '种子选择代次已改变',
  selection_generation_superseded: '种子选择代次已改变',
  seed_drift: '种子身份已改变',
  engine_drift: '故事发动机已改变',
  style_drift: '风格模板已改变',
  asset_drift: '正式资产已改变',
  binding_drift: '模型绑定已改变',
  binding_incomplete: '八项模型任务尚未全部绑定',
  binding_not_ready: '模型绑定当前不可用',
  contract_missing: '尚未建立完整契约草稿',
  superseded: '已被后续状态取代',
})

const selectedSeed = computed(() => seedStore.selectedSeed)
const baselineLocked = computed(() => Number(contractStore.head?.revision || 0) > 0)
const hasArchivedSignedContract = computed(() => props.readOnly && baselineLocked.value)
const documentReadOnly = computed(() => props.readOnly || baselineLocked.value || !selectedSeed.value)
const interactionLocked = computed(() => contractStore.requiresReload)
const seedSummary = computed(() => {
  if (baselineLocked.value) {
    const head = contractStore.head || {}
    const frozen = head.creationContract?.selectedSeed || {}
    return {
      title: frozen.title,
      logline: frozen.logline,
      genre: frozen.genre,
      selectionRevision: head.selectionRevision,
      frozen: true,
    }
  }
  const seed = selectedSeed.value
  const payload = seed?.payload ?? seed ?? {}
  return {
    title: payload.title,
    logline: payload.logline,
    genre: payload.genre,
    revision: seed?.revision,
    selectionRevision: seedStore.selectionRevision,
    frozen: false,
  }
})
const archivedInvalidReasons = computed(() => {
  if (!hasArchivedSignedContract.value) return []
  const detailed = Array.isArray(contractStore.head?.supersededReasons)
    ? contractStore.head.supersededReasons
    : []
  const readiness = contractStore.readinessReasons.filter(reason => (
    reason !== 'superseded' || detailed.length === 0
  ))
  return [...new Set([...detailed, ...readiness])]
})
const selectionDrift = computed(() => {
  const savedSelectionRevision = Number(contractStore.draft?.selectionRevision || 0)
  if (!savedSelectionRevision || !selectedSeed.value) return false
  return savedSelectionRevision !== seedStore.selectionRevision
})
const styleDecision = computed(() => (
  baselineLocked.value
    ? contractStore.head?.styleContract
    : contractStore.previewResult?.styleContract
      || contractStore.draft?.documentProjection?.primaryStyle
))
const documentPayload = computed(() => {
  if (!baselineLocked.value) {
    const draft = contractStore.draft?.draft || {}
    const preview = contractStore.previewResult
    const hasProjection = Object.hasOwn(
      contractStore.draft || {}, 'documentProjection'
    )
    const projection = contractStore.draft?.documentProjection
    const creation = preview?.creationContract || {}
    const transientEngine = contractStore.engineBatch?.options?.find(option => (
      option.id === draft.engineOptionId && option.contentHash === draft.engineHash
    ))?.payload
    return {
      ...draft,
      ...creation,
      selectedEngine: creation.selectedEngine
        || (hasProjection ? projection?.selectedEngine : transientEngine),
      primaryStyleRef: projection?.primaryStyle
        ? { ...draft.primaryStyleRef, ...projection.primaryStyle }
        : draft.primaryStyleRef,
      secondaryStyleRef: projection?.secondaryStyle
        ? { ...draft.secondaryStyleRef, ...projection.secondaryStyle }
        : draft.secondaryStyleRef,
      likes: Array.isArray(preview?.likes) ? preview.likes : draft.likes,
      dislikes: Array.isArray(preview?.dislikes) ? preview.dislikes : draft.dislikes,
    }
  }
  const head = contractStore.head || {}
  const styles = Array.isArray(head.styleRefs) ? head.styleRefs : []
  return {
    ...(head.creationContract || {}),
    engineOptionId: head.engineRef?.id,
    engineHash: head.engineRef?.contentHash,
    primaryStyleRef: styles[0] || null,
    secondaryStyleRef: styles[1] || null,
    likes: Array.isArray(head.likes) ? head.likes : [],
    dislikes: Array.isArray(head.dislikes) ? head.dislikes : [],
    experienceCardRefs: Array.isArray(head.experienceCardRefs) ? head.experienceCardRefs : [],
    corpusSourceRefs: Array.isArray(head.corpusSourceRefs) ? head.corpusSourceRefs : [],
  }
})
const contractDocument = computed(() => contractDocumentSections({
  draftVersion: contractStore.activeDraftVersion,
  draftStage: contractStore.lastSavedStage,
  payload: documentPayload.value,
  selectionDrift: selectionDrift.value,
  serverCanConfirm: contractStore.serverCanConfirm,
  serverReasons: contractStore.serverReasons,
  serverCanEdit: contractStore.head?.canEdit,
  serverEditReasons: contractStore.head?.editReasons,
}))
const sections = computed(() => contractDocument.value.sections)
const writeBusy = computed(() => Boolean(
  childWriteBusy.value
  || contractStore.saving
  || contractStore.previewing
  || contractStore.confirming
  || contractStore.engineLoading
  || contractStore.reconciling
  || contractStore.styleTrialLoading,
))
const sectionItems = computed(() => sections.value.map(section => ({
  ...section,
  targetId: `contract-section-${section.key}`,
  disabled: writeBusy.value || interactionLocked.value,
  status: baselineLocked.value
    ? 'filled'
    : section.key === 'preview'
    ? (contractStore.previewing ? 'current' : section.status)
    : (activeSectionKey.value === section.key ? 'current' : section.status),
  statusLabel: baselineLocked.value
    ? '已签印'
    : section.key === 'preview'
    ? (contractStore.previewing ? '核对中' : contractStore.previewResult ? '已加载' : '待核对')
    : activeSectionKey.value === section.key
      ? '编辑中'
      : ({ filled: '已记录', suggested: section.open ? '待填写' : '待解锁', blocked: '服务端阻断' }[section.status] || '状态待核对'),
})))
const operationLabel = computed(() => {
  if (contractStore.confirming) return '正在签印创作契约'
  if (contractStore.styleTrialLoading) return '正在生成临时风格试写'
  if (contractStore.engineLoading || contractStore.reconciling) return '正在处理故事发动机'
  if (contractStore.previewing) return '正在核对冻结引用'
  return '正在保存创作契约草稿'
})
const workspaceStatus = computed(() => {
  if (hasArchivedSignedContract.value) return `最后签印的历史契约 · 第 ${contractStore.head.revision} 版`
  if (baselineLocked.value) return `已签印 · 第 ${contractStore.head.revision} 版`
  if (props.readOnly) return '只读档案'
  return contractDocument.value.draftVersion.value
    ? `草稿 · ${contractDocument.value.draftVersion.label} ${contractDocument.value.draftVersion.value}`
    : '尚未建立草稿'
})
const confirmationAdapter = computed(() => ({
  preview: contractStore.previewResult,
  draftVersion: contractStore.activeDraftVersion,
  contentHash: contractStore.draft?.contentHash || '',
  canConfirm: Boolean(contractStore.serverCanConfirm && !interactionLocked.value),
}))

function reasonLabel(reason) { return reasonLabels[reason] || '状态需要重新核对' }
function projectionUnavailable(reason) {
  return contractStore.draft?.documentProjection?.unavailableReasons?.includes(reason) === true
}
function focusControl(reference, options = { preventScroll: false }) {
  const target = typeof reference?.focus === 'function' ? reference : reference?.$el
  target?.focus?.(options)
}
function readable(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.length ? value.map(readable).join('；') : '未选择'
  if (typeof value === 'object') return value.name || value.title || '已记录结构化内容'
  return String(value)
}
const profileLabels = Object.freeze({
  serial: '长篇连载', 'serial-fiction': '长篇连载', historical: '历史', mystery: '悬疑',
  fantasy: '奇幻', xianxia: '仙侠', wuxia: '武侠', romance: '言情', urban: '都市',
  horror: '惊悚', science_fiction: '科幻', author: '作者指定片段', fragments: '指定片段', full: '完整引用',
})
function authorLabel(value) {
  const text = String(value || '').trim()
  if (!text) return '未标注'
  if (/^[\u3400-\u9fff]/u.test(text)) return text
  return profileLabels[text] || '已配置（详情见来源与诊断）'
}
function count(value) {
  const number = Number(value)
  return Number.isFinite(number) && number > 0 ? number.toLocaleString() : '—'
}
function wordRange(value) {
  return Array.isArray(value) && value.length === 2
    ? `${count(value[0])} ～ ${count(value[1])} 字`
    : '—'
}
function referenceLabel(value) {
  if (!value || typeof value !== 'object') return readable(value)
  const identity = value.name || value.title || '已冻结引用'
  const revision = value.revision ?? value.revisionId
  const role = value.selectionMode ? ` · ${authorLabel(value.selectionMode)}` : ''
  const fragments = Array.isArray(value.fragments) && value.fragments.length
    ? `（${value.fragments.map(fragment => (
        `位置 ${fragment.chapterCharStart ?? '—'}–${fragment.chapterCharEnd ?? '—'} · ${authorLabel(fragment.referenceUse)}`
      )).join('；')}）`
    : ''
  return `${identity}${revision ? ` · R${revision}` : ''}${role}${fragments}`
}
function sectionByKey(key) { return sections.value.find(section => section.key === key) }
function confirmDiscard() {
  if (documentReadOnly.value) return true
  if (writeBusy.value) {
    busyNotice.value = '正式操作正在提交，请等待结果明确后再切换分区或离开项目。'
    return false
  }
  if (!contractStore.hasUnsavedChanges) return true
  if (typeof window === 'undefined') return false
  const accepted = window.confirm('当前分区有尚未保存的修改。放弃这些修改并离开吗？')
  if (accepted) contractStore.discardUnsavedChanges()
  return accepted
}
function focusSection(key) {
  void nextTick(() => {
    const target = globalThis.document?.getElementById?.(`contract-section-${key}`)
    const reducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true
    target?.scrollIntoView?.({ block: 'start', behavior: reducedMotion ? 'auto' : 'smooth' })
    target?.focus?.({ preventScroll: true })
  })
}
function navigateSection(key) {
  const section = sectionByKey(key)
  if (!section || writeBusy.value) {
    busyNotice.value = writeBusy.value ? '正式操作正在提交，暂不能切换分区。' : ''
    return
  }
  if (interactionLocked.value) {
    busyNotice.value = '权威状态已变化；请先决定保留本地修改或放弃并重新加载。'
    focusControl(reloadNoticeRegion.value)
    return
  }
  if (key !== activeSectionKey.value && !confirmDiscard()) return
  busyNotice.value = ''
  const previewAvailable = section.key === 'preview'
    && (section.canPreview || Boolean(confirmationAdapter.value.preview))
  activeSectionKey.value = !documentReadOnly.value
    && section.open
    && (section.writeFields.length || previewAvailable)
    ? key
    : ''
  focusSection(key)
}
function requestAuthoritativeReload() {
  if (writeBusy.value) return
  if (contractStore.hasUnsavedChanges) {
    reloadDecisionOpen.value = true
    return
  }
  void loadWizard(props.projectId)
}
function keepLocalChanges() {
  reloadDecisionOpen.value = false
  liveStatus.value = '已保留本地修改；正式操作继续锁定，直到你放弃并重新加载。'
}
function discardAndReload() {
  contractStore.discardUnsavedChanges()
  reloadDecisionOpen.value = false
  void loadWizard(props.projectId)
}
function markWriteBusy(value) {
  childWriteBusy.value = value === true
  if (!childWriteBusy.value) busyNotice.value = ''
}
function markDirty(value) {
  if (documentReadOnly.value) return
  if (value) contractStore.markUnsavedChanges()
  else contractStore.discardUnsavedChanges()
}
function markEditing(sectionKey, value) {
  if (value === true) activeSectionKey.value = sectionKey
}
function handleSaved(sectionKey) {
  childWriteBusy.value = false
  busyNotice.value = ''
  liveStatus.value = `${sectionByKey(sectionKey)?.label || '本节'}已保存，页面位置保持不变。`
  contractStore.discardUnsavedChanges()
}
function handleConfirmed() {
  activeSectionKey.value = ''
  liveStatus.value = '创作契约已签印，全文现在只读。'
  contractStore.discardUnsavedChanges()
}
async function loadWizard(projectId) {
  if (writeBusy.value) {
    busyNotice.value = '正式操作正在提交，当前不能并发重新加载项目状态。'
    return
  }
  const generation = loadGuard.begin()
  loading.value = true
  loadError.value = ''
  childWriteBusy.value = false
  busyNotice.value = ''
  liveStatus.value = ''
  try {
    await Promise.all([
      seedStore.refresh(projectId),
      contractStore.load(projectId, { readOnly: props.readOnly }),
    ])
    if (!loadGuard.isCurrent(generation)) return
    if (!props.readOnly && contractStore.lastSavedStage === 'assets' && !baselineLocked.value) {
      try {
        await contractStore.preview(projectId)
      } catch (error) {
        if (loadGuard.isCurrent(generation) && !contractStore.requiresReload) {
          liveStatus.value = '草稿已载入；服务器暂时无法形成完整核对快照。'
        }
      }
      if (!loadGuard.isCurrent(generation)) return
    }
    activeSectionKey.value = ''
  } catch (error) {
    if (!loadGuard.isCurrent(generation)) return
    loadError.value = error?.message || '创作契约加载失败'
    await nextTick()
    focusControl(loadErrorRegion.value)
  } finally {
    if (loadGuard.isCurrent(generation)) loading.value = false
  }
}
function handleBeforeUnload(event) {
  if (!contractStore.hasUnsavedChanges && !writeBusy.value) return
  event.preventDefault()
  event.returnValue = ''
}

watch(() => [props.projectId, props.readOnly], ([projectId]) => {
  if (projectId) void loadWizard(String(projectId))
}, { immediate: true })
watch(() => contractStore.requiresReload, async locked => {
  if (!locked) return
  await nextTick()
  focusControl(reloadNoticeRegion.value)
})
if (typeof window !== 'undefined') window.addEventListener('beforeunload', handleBeforeUnload)
onBeforeRouteLeave(() => confirmDiscard())
onBeforeRouteUpdate(() => confirmDiscard())
onBeforeUnmount(() => {
  loadGuard.invalidate()
  contractStore.setReadOnly(false)
  if (typeof window !== 'undefined') window.removeEventListener('beforeunload', handleBeforeUnload)
})
</script>

<template>
  <FoundationWorkspace
    title="本书创作契约"
    purpose="把未来写作的边界、承诺与冻结引用写成一份连续稿簿；目录只在本文内定位，不切换页面。"
    :status-label="workspaceStatus"
    :read-only="documentReadOnly"
  >
    <template #index>
      <FoundationSectionIndex
        :items="sectionItems"
        :current-key="activeSectionKey"
        :focus-on-navigate="false"
        @navigate="navigateSection"
      />
    </template>

    <template #document>
      <div v-if="loading" class="contract-loading" aria-busy="true">
        <n-skeleton text width="42%" />
        <n-skeleton text :repeat="3" />
        <n-skeleton height="240px" />
      </div>
      <n-result
        v-else-if="loadError"
        ref="loadErrorRegion"
        tabindex="-1"
        status="error"
        title="创作契约未能加载"
        :description="loadError"
        class="contract-error"
        aria-live="assertive"
      >
        <template #footer><n-button type="primary" :disabled="writeBusy" @click="loadWizard(props.projectId)">重新加载并核对</n-button></template>
      </n-result>

      <template v-else>
        <aside v-if="selectedSeed || baselineLocked" class="seed-summary" :aria-label="seedSummary.frozen ? '签印时冻结的创作种子，只读摘要' : '已选创作种子，只读摘要'">
          <div>
            <span>上游摘要 · {{ seedSummary.frozen ? '签印冻结种子' : '当前确认种子' }}</span>
            <strong>{{ seedSummary.title }}</strong>
            <p>{{ seedSummary.logline }}</p>
          </div>
          <dl>
            <div><dt>{{ seedSummary.frozen ? '种子状态' : '种子修订' }}</dt><dd>{{ seedSummary.frozen ? '已冻结' : (seedSummary.revision ?? '—') }}</dd></div>
            <div><dt>题材</dt><dd>{{ seedSummary.genre || '未标注' }}</dd></div>
            <div><dt>选择代次</dt><dd>R{{ seedSummary.selectionRevision || '—' }}</dd></div>
          </dl>
        </aside>
        <n-result
          v-else
          status="warning"
          title="尚未选定创作种子"
          description="创作契约必须绑定一个当前有效的种子修订；这里不会重复提供种子选择。"
          class="seed-required"
        >
          <template #footer><router-link class="seed-cta" :to="projectSeedsPath(props.projectId)">前往种子</router-link></template>
        </n-result>

        <n-alert v-if="contractStore.requiresReload" ref="reloadNoticeRegion" tabindex="-1" type="warning" class="checkpoint-alert" aria-live="assertive">
          <p>草稿或冻结输入已经变化。系统不会静默覆盖；请重新加载并核对权威状态。</p>
          <n-button class="checkpoint-alert__action" text :disabled="writeBusy" @click="requestAuthoritativeReload">重新加载并核对</n-button>
        </n-alert>
        <n-alert v-if="selectionDrift" type="warning" class="checkpoint-alert" aria-live="assertive">
          当前草稿绑定的是旧种子修订。服务器只开放故事发动机，旧代次的冻结选择不会沿用。
        </n-alert>
        <p class="workspace-live" aria-live="polite">{{ busyNotice || liveStatus }}</p>

        <p class="document-kicker">完整内容</p>
        <FoundationDocumentSection
          v-for="section in sections"
          :key="section.key"
          :target-id="`contract-section-${section.key}`"
          :title="section.label"
          :eyebrow="`创作契约 · ${section.label}`"
          :read-only="documentReadOnly || !section.open || (section.key !== 'preview' && Boolean(section.blockedReasons.length))"
        >
          <template #read>
            <p class="section-responsibility">{{ sectionResponsibilities[section.key] }}</p>
            <dl v-if="section.key === 'engine'" class="section-readout">
              <div><dt>采用方案</dt><dd>{{ readable(documentPayload.selectedEngine?.name || (documentPayload.engineOptionId ? '已选择故事发动机' : '—')) }}</dd></div>
              <div><dt>版本校验</dt><dd>{{ documentPayload.engineHash ? '已由服务端核验' : '待核验' }}</dd></div>
              <div><dt>渠道</dt><dd>{{ authorLabel(documentPayload.channelProfileKey) }}</dd></div>
              <div><dt>题材</dt><dd>{{ authorLabel(documentPayload.genreProfileKey) }}</dd></div>
              <div class="section-readout__wide"><dt>方案名称</dt><dd>{{ readable(documentPayload.selectedEngine?.name) }}</dd></div>
              <div class="section-readout__wide"><dt>故事承诺</dt><dd>{{ readable(documentPayload.selectedEngine?.storyPromise) }}</dd></div>
              <div><dt>持续压力</dt><dd>{{ readable(documentPayload.selectedEngine?.sustainedPressure) }}</dd></div>
              <div><dt>冲突循环</dt><dd>{{ readable(documentPayload.selectedEngine?.conflictLoop) }}</dd></div>
              <div class="section-readout__wide"><dt>优势与代价</dt><dd>{{ readable(documentPayload.selectedEngine?.advantageAndCost) }}</dd></div>
            </dl>
            <p v-if="section.key === 'engine' && projectionUnavailable('engine_identity_unavailable')" class="projection-unavailable" role="status">已冻结的故事发动机正文当前无法核验；这里只保留服务器草稿中的身份与摘要。</p>
            <dl v-else-if="section.key === 'capacity'" class="section-readout">
              <div><dt>目标总字数</dt><dd>{{ count(documentPayload.targetTotalWords) }} 字</dd></div>
              <div><dt>预计卷数</dt><dd>{{ count(documentPayload.expectedVolumeCount) }} 卷</dd></div>
              <div><dt>预计章数</dt><dd>{{ count(documentPayload.expectedChapterCount) }} 章</dd></div>
              <div><dt>单章范围</dt><dd>{{ wordRange(documentPayload.chapterWordRangePreference) }}</dd></div>
              <div class="section-readout__wide"><dt>作者备注</dt><dd>{{ readable(documentPayload.authorNotes) }}</dd></div>
            </dl>
            <dl v-else-if="section.key === 'assets'" class="section-readout">
              <div><dt>经验卡</dt><dd>{{ documentPayload.experienceCardRefs?.length || 0 }} 张</dd></div>
              <div><dt>语料来源</dt><dd>{{ documentPayload.corpusSourceRefs?.length || 0 }} 份</dd></div>
              <div class="section-readout__wide"><dt>经验卡引用</dt><dd>{{ (documentPayload.experienceCardRefs || []).map(referenceLabel).join('；') || '未选择' }}</dd></div>
              <div class="section-readout__wide"><dt>语料引用与角色</dt><dd>{{ (documentPayload.corpusSourceRefs || []).map(referenceLabel).join('；') || '未选择' }}</dd></div>
            </dl>
            <dl v-else-if="section.key === 'style'" class="section-readout">
              <div><dt>主风格</dt><dd>{{ referenceLabel(documentPayload.primaryStyleRef) }}</dd></div>
              <div><dt>辅风格</dt><dd>{{ referenceLabel(documentPayload.secondaryStyleRef) }}</dd></div>
              <div><dt>喜欢</dt><dd>{{ readable(documentPayload.likes) }}</dd></div>
              <div><dt>避开</dt><dd>{{ readable(documentPayload.dislikes) }}</dd></div>
              <div v-if="styleDecision" class="section-readout__wide"><dt>阅读体验</dt><dd>{{ readable(styleDecision.readingExperience) }}</dd></div>
              <div v-if="styleDecision"><dt>叙事距离</dt><dd>{{ readable(styleDecision.narrativeDistance) }}</dd></div>
              <div v-if="styleDecision"><dt>句段节奏</dt><dd>{{ readable(styleDecision.sentenceParagraphRhythm) }}</dd></div>
            </dl>
            <p v-if="section.key === 'style' && projectionUnavailable('primary_style_identity_unavailable')" class="projection-unavailable" role="status">已冻结的主风格正文当前无法核验；这里只保留服务器草稿中的精确引用。</p>
            <dl v-else-if="section.key === 'prohibitions'" class="section-readout">
              <div class="section-readout__wide"><dt>禁止方向</dt><dd>{{ readable(documentPayload.prohibitedDirections) }}</dd></div>
            </dl>
            <template v-else-if="section.key === 'preview'">
              <ContractDecisionSummary
                v-if="baselineLocked"
                :creation-contract="contractStore.head?.creationContract"
                :style-contract="contractStore.head?.styleContract"
                :likes="contractStore.head?.likes"
                :dislikes="contractStore.head?.dislikes"
                heading="已签印的作者约定"
              />
            <p v-else class="preview-placeholder">服务器快照只在本节开放后加载；页面不会根据本地完整度推断可确认状态。</p>
            </template>
            <aside v-if="!baselineLocked && (!section.open || section.blockedReasons.length)" class="section-lock" role="note" :aria-label="`${section.label}锁定说明`">
              <strong>{{ section.blockedReasons.length ? '服务器阻断本节写入' : '本节等待服务端前置状态' }}</strong>
              <p>{{ sectionPrerequisites[section.key] }}</p>
              <ul v-if="section.blockedReasons.length">
                <li v-for="reason in section.blockedReasons" :key="reason">{{ reasonLabel(reason) }}</li>
              </ul>
            </aside>
            <n-button
              v-else-if="!documentReadOnly && section.writeFields.length && activeSectionKey !== section.key"
              class="section-edit-button"
              secondary
              :disabled="writeBusy || interactionLocked"
              @click="navigateSection(section.key)"
            >编辑本节</n-button>
          </template>

          <template #edit>
            <StoryEngineStep
              v-if="section.key === 'engine' && activeSectionKey === section.key && section.open && section.writeFields.length"
              :project-id="props.projectId"
              :project="props.project"
              :selected-seed="selectedSeed"
              :interaction-locked="interactionLocked"
              @editing-change="value => markEditing(section.key, value)"
              @saved="handleSaved(section.key)"
              @dirty-change="markDirty"
              @busy-change="markWriteBusy"
            />
            <CapacityStep
              v-else-if="section.key === 'capacity' && activeSectionKey === section.key && section.open && section.writeFields.length"
              :project-id="props.projectId"
              mode="capacity"
              :interaction-locked="interactionLocked"
              @editing-change="value => markEditing(section.key, value)"
              @saved="handleSaved(section.key)"
              @dirty-change="markDirty"
            />
            <AssetScopeStep
              v-else-if="section.key === 'assets' && activeSectionKey === section.key && section.open && section.writeFields.length"
              :project-id="props.projectId"
              :interaction-locked="interactionLocked"
              @editing-change="value => markEditing(section.key, value)"
              @saved="handleSaved(section.key)"
              @dirty-change="markDirty"
            />
            <StyleSelectionStep
              v-else-if="section.key === 'style' && activeSectionKey === section.key && section.open && section.writeFields.length"
              :project-id="props.projectId"
              :selection-revision="seedStore.selectionRevision"
              :interaction-locked="interactionLocked"
              @editing-change="value => markEditing(section.key, value)"
              @saved="handleSaved(section.key)"
              @dirty-change="markDirty"
            />
            <CapacityStep
              v-else-if="section.key === 'prohibitions' && activeSectionKey === section.key && section.open && section.writeFields.length"
              :project-id="props.projectId"
              mode="prohibitions"
              :interaction-locked="interactionLocked"
              @editing-change="value => markEditing(section.key, value)"
              @saved="handleSaved(section.key)"
              @dirty-change="markDirty"
            />
            <ContractPreviewStep
              v-else-if="section.key === 'preview' && activeSectionKey === section.key && section.open && (section.canPreview || contractStore.previewResult)"
              :project-id="props.projectId"
              :confirmation="confirmationAdapter"
              :interaction-locked="interactionLocked"
              @reload="requestAuthoritativeReload"
              @confirmed="handleConfirmed"
            />
          </template>
        </FoundationDocumentSection>
      </template>
    </template>

    <template #status>
      <FoundationStatusRail :read-only="documentReadOnly">
        <template #summary>
          <div class="status-summary">
            <strong>用途</strong>
            <p>把种子、故事发动机、长篇容量、正式资产与风格边界签印为后续创作依据。</p>
            <span v-if="baselineLocked">永久基线 · 第 {{ contractStore.head.revision }} 版</span>
            <span v-else>创作契约正文</span>
            <strong v-if="hasArchivedSignedContract">最后签印的历史契约</strong>
            <strong v-else-if="baselineLocked">已确认，作为项目永久基线</strong>
            <strong v-else>连续作者文档</strong>
            <p v-if="baselineLocked">这份修订只读且不可覆盖；全文保留签印时的冻结引用。</p>
            <dl v-if="documentPayload.targetTotalWords" class="capacity-summary">
              <div><dt>全书目标</dt><dd>{{ count(documentPayload.targetTotalWords) }} 字</dd></div>
              <div><dt>卷 / 章</dt><dd>{{ count(documentPayload.expectedVolumeCount) }} 卷 · {{ count(documentPayload.expectedChapterCount) }} 章</dd></div>
              <div><dt>单章范围</dt><dd>{{ wordRange(documentPayload.chapterWordRangePreference) }}</dd></div>
            </dl>
            <n-button v-if="baselineLocked" size="small" secondary @click="historyOpen = true">历史修订</n-button>
          </div>
        </template>
        <template #status>
          <strong>生命周期</strong>
          <p>{{ workspaceStatus }}</p>
          <p v-if="confirmationAdapter.draftVersion">草稿版本：{{ confirmationAdapter.draftVersion }}</p>
          <p v-if="!baselineLocked">完整性校验：{{ confirmationAdapter.contentHash ? '服务器已记录' : '等待服务器记录' }}</p>
          <strong class="rail-heading">可编辑性</strong>
          <p>{{ documentReadOnly ? '全文只读' : interactionLocked ? '等待重新核对权威状态' : '可按分区编辑并保存' }}</p>
          <n-tag v-if="selectionDrift" type="warning" :bordered="false">种子漂移</n-tag>
          <n-tag v-else-if="baselineLocked" type="success" :bordered="false">全文只读</n-tag>
          <n-tag v-else :type="contractStore.serverCanConfirm ? 'success' : 'default'" :bordered="false">
            {{ contractStore.serverCanConfirm ? '服务端允许确认' : '等待服务端就绪' }}
          </n-tag>
        </template>
        <template #source>
          <strong>来源与诊断</strong>
          <p><b>上游摘要：</b>{{ seedSummary.title || '尚未确认创作种子' }}{{ seedSummary.genre ? ` · ${seedSummary.genre}` : '' }}</p>
          <p>确认权限、冻结引用和阻断原因均来自服务器；本页只负责呈现，不从本地字段完整度推断。</p>
          <ul v-if="archivedInvalidReasons.length"><li v-for="reason in archivedInvalidReasons" :key="reason">{{ reasonLabel(reason) }}</li></ul>
        </template>
      </FoundationStatusRail>
    </template>
  </FoundationWorkspace>

  <aside v-if="writeBusy" class="contract-operation-overlay" role="status" aria-live="polite" aria-busy="true">
    <div><span aria-hidden="true">作</span><strong>{{ operationLabel }}</strong><small>请等待结果明确，期间不会切换分区。</small></div>
  </aside>
  <ContractHistoryDrawer v-model:show="historyOpen" :project-id="props.projectId" />
  <FoundationConfirmationDialog
    v-if="reloadDecisionOpen"
    :open="true"
    title="本地修改尚未保存"
    @close="keepLocalChanges"
  >
    <template #snapshot><strong>权威状态已变化</strong><p>重新加载会以服务器状态替换当前表单中的本地修改。</p></template>
    <template #source><p>选择“保留本地修改”会取消本次重新加载；正式操作仍保持锁定。选择“放弃并重新加载”才会清除本地修改并读取服务器。</p></template>
    <template #action>
      <n-button @click="keepLocalChanges">保留本地修改</n-button>
      <n-button type="primary" @click="discardAndReload">放弃并重新加载</n-button>
    </template>
  </FoundationConfirmationDialog>
</template>

<style scoped>
.contract-loading,.contract-error { padding:clamp(24px,4vw,44px); }.contract-loading { display:grid; gap:16px; }
.seed-summary { display:grid; grid-template-columns:minmax(0,1.6fr) minmax(240px,.75fr); gap:22px; padding:clamp(22px,4vw,38px); border-bottom:2px solid var(--nc-vermilion); background:color-mix(in srgb,var(--nc-paper) 93%,var(--nc-vermilion)); }
.seed-summary span,.status-summary>span { color:var(--nc-vermilion); font:700 10px Georgia,'Noto Serif SC',serif; letter-spacing:.16em; }.seed-summary strong { display:block; margin-top:7px; font:600 clamp(22px,3vw,31px)/1.25 Georgia,'Noto Serif SC',serif; }.seed-summary p { max-width:60ch; margin:8px 0 0; color:var(--nc-muted); line-height:1.75; }.seed-summary dl { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); margin:0; border:1px solid var(--nc-border); }.seed-summary dl div { min-width:0; padding:11px; border-left:1px solid var(--nc-border); }.seed-summary dl div:first-child { border-left:0; }.seed-summary dt { color:var(--nc-muted); font-size:10px; }.seed-summary dd { margin:4px 0 0; font:600 12px Georgia,'Noto Serif SC',serif; overflow-wrap:anywhere; }
.seed-required,.checkpoint-alert { margin:18px; }.checkpoint-alert p { margin:0; }.checkpoint-alert__action { margin-top:10px; }.seed-cta { display:inline-flex; min-height:40px; align-items:center; padding:0 15px; color:#fff; background:var(--nc-vermilion); text-decoration:none; }.seed-cta:focus-visible,.section-edit-button:focus-visible { outline:2px solid var(--nc-vermilion); outline-offset:3px; }
.workspace-live { min-height:1.4em; margin:0; padding:0 24px; color:var(--nc-muted); font-size:12px; line-height:1.5; }.section-responsibility { max-width:68ch; margin:0; color:var(--nc-muted); font:14px/1.8 Georgia,'Noto Serif SC',serif; }
.document-kicker { margin:0; padding:18px 30px 0; color:var(--nc-vermilion); font:700 10px Georgia,'Noto Serif SC',serif; letter-spacing:.16em; }.rail-heading { display:block; margin-top:12px; }
.section-readout { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:1px; margin:18px 0 0; padding:1px; background:var(--nc-border); }.section-readout>div { min-width:0; padding:12px 14px; background:var(--nc-paper); }.section-readout__wide { grid-column:1 / -1; }.section-readout dt { color:var(--nc-muted); font-size:11px; }.section-readout dd { margin:5px 0 0; font:600 13px/1.65 Georgia,'Noto Serif SC',serif; overflow-wrap:anywhere; }.projection-unavailable,.preview-placeholder { margin:18px 0 0; padding:14px; border-left:2px solid var(--nc-vermilion); color:var(--nc-muted); background:color-mix(in srgb,var(--nc-paper) 82%,var(--nc-canvas)); line-height:1.7; }
.section-lock { margin-top:18px; padding:15px 16px; border:1px solid var(--nc-border); border-left:3px solid var(--nc-vermilion); background:color-mix(in srgb,var(--nc-paper) 82%,var(--nc-canvas)); }.section-lock strong { font:600 14px Georgia,'Noto Serif SC',serif; }.section-lock p,.section-lock li { color:var(--nc-muted); font-size:12px; line-height:1.7; }.section-lock p { margin:7px 0 0; }.section-lock ul { margin:8px 0 0; padding-left:18px; }.section-lock code { color:var(--nc-vermilion); }.section-edit-button { margin-top:18px; }
.status-summary { display:grid; gap:7px; }.status-summary strong { font:600 16px/1.35 Georgia,'Noto Serif SC',serif; }.status-summary p { margin:0; color:var(--nc-muted); font-size:12px; line-height:1.65; }.capacity-summary { display:grid; gap:6px; margin:8px 0 0; padding-top:10px; border-top:1px solid var(--nc-border); }.capacity-summary div { display:grid; grid-template-columns:1fr; }.capacity-summary dt { color:var(--nc-muted); font-size:10px; }.capacity-summary dd { margin:2px 0 0; font:600 12px Georgia,'Noto Serif SC',serif; }.contract-operation-overlay { position:absolute; z-index:32; inset:auto 20px 20px auto; max-width:360px; padding:14px; border:1px solid var(--nc-vermilion); background:var(--nc-paper); box-shadow:0 16px 40px color-mix(in srgb,var(--nc-ink) 18%,transparent); }.contract-operation-overlay div { display:grid; grid-template-columns:auto 1fr; gap:3px 10px; }.contract-operation-overlay span { grid-row:1 / 3; display:grid; width:34px; height:34px; place-items:center; color:#fff; background:var(--nc-vermilion); font-family:Georgia,'Noto Serif SC',serif; }.contract-operation-overlay small { color:var(--nc-muted); }
@media (max-width:760px) { .seed-summary { grid-template-columns:1fr; }.seed-summary dl { grid-template-columns:1fr; }.seed-summary dl div { border-top:1px solid var(--nc-border); border-left:0; }.seed-summary dl div:first-child { border-top:0; }.section-readout { grid-template-columns:1fr; }.section-readout__wide { grid-column:auto; }.contract-operation-overlay { right:12px; bottom:12px; left:12px; max-width:none; } }
@media (prefers-reduced-motion:reduce) { .contract-operation-overlay,* { scroll-behavior:auto !important; transition:none !important; animation:none !important; } }
</style>

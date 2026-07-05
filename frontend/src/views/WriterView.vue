<script setup>
import {
  runSaveBeatPlanCommand,
} from '@/application/writer-flow/save-beat-plan-command'
import {
  runGenerateFromBeatPlanCommand,
} from '@/application/writer-flow/draft-generation-command'
import { runCreateVersionCommand } from '@/application/writer-flow/version-creation-command'
import { ref, onMounted, watch, computed, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton,
  NCard,
  NEmpty,
  NSpace,
  NInput,
  NTag,
  NModal,
  NSpin,
  NDivider,
  NDropdown,
  useDialog
} from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useProjectStore } from '@/stores/projectStore'
import { useWriterStore } from '@/stores/writerStore'
import { useNovelStore } from '@/stores/novelStore'
import { useSeedStore } from '@/stores/seedStore'
import { useMemoryStore } from '@/stores/memoryStore'
import { useSettingStore } from '@/stores/settingStore'
import { useVolumeStore } from '@/stores/volumeStore'
import { useStoryBlockStore, STORY_BLOCK_REVIEW_DECISION_LABELS } from '@/stores/storyBlockStore'
import {
  correctionTaskMode,
  isCorrectionTaskActiveForContext,
  isCorrectionTaskBlockingForGeneration,
  useCorrectionTaskStore
} from '@/stores/correctionTaskStore'
import { useCompareStore } from '@/stores/compareStore'
import { buildWritingContext } from '@/utils/contextBuilder'
import { assertContextPackHealthy } from '@/utils/contextPackV2'
import { auditIssueTypeLabel, auditSeverityLabel } from '@/utils/auditLabels'
import { api } from '@/api/db/client'
import { downloadFile, exportTxt, exportMarkdown } from '@/utils/export'
import { formatChapterDisplayTitle, getChapterTitleQuality, isDefaultChapterTitle } from '@/prompts/chapter'
import AIActionPanel from '@/components/writer/AIActionPanel.vue'
import ChapterVersionList from '@/components/writer/ChapterVersionList.vue'
import CreativeBible from '@/components/bible/CreativeBible.vue'
import CanonReviewPanel from '@/components/writer/CanonReviewPanel.vue'
import ContextMemoryPanel from '@/components/writer/ContextMemoryPanel.vue'
import StyleAnalysisPanel from '@/components/writer/StyleAnalysisPanel.vue'
import PacingChart from '@/components/writer/PacingChart.vue'
import CompareModal from '@/components/writer/CompareModal.vue'
import CompareInline from '@/components/writer/CompareInline.vue'
import FusionPanel from '@/components/writer/FusionPanel.vue'
import VersionDiffModal from '@/components/writer/VersionDiffModal.vue'
import ContextPreviewModal from '@/components/writer/ContextPreviewModal.vue'
import StoryBlockPanel from '@/components/writer/StoryBlockPanel.vue'
import { assessChapterWordCount, buildChapterWordTarget } from '@/utils/chapterWordTarget'
import {
  buildBlockStageSnapshot,
  findNextEditableStage
} from '@/utils/storyBlockSnapshot'
import {
  assessStoryBlockCloseDecision,
  filterExecutedCompletedStageIds,
  splitStoryBlockStagesByExecution,
  storyBlockStageId
} from '@/utils/storyBlockGranularity'
import {
  buildStageContinuationDiagnostics,
  enforceStageContinuationSettlement
} from '@/utils/storyBlockStageSettlement'
import {
  applyAuditReplacement,
  cleanAuditQuote,
  getAuditReplacement,
  locateAuditQuote
} from '@/utils/auditRevisionTools'
import {
  beginChapterFinalizationRun,
  markChapterFinalizationFailure,
  clearChapterFinalizationPending,
  endChapterFinalizationRun,
  getChapterFinalizationPending,
} from '@/utils/finalizationGuard'
import {
  checkChapterHardWordMinimum,
  checkCorrectionTaskBlocker,
  checkCurrentChapterWritable,
  checkPendingSettingChanges,
  checkPendingStoryMemory,
  checkPreviousChapterFinalized
} from '@/application/writer-flow/preconditions'
import {
  normalizeManualChapterTitle,
  runGenerateChapterTitleCommand,
  runSaveManualChapterTitleCommand,
  validateGenerateChapterTitleInput,
  validateManualChapterTitle
} from '@/application/writer-flow/chapter-title-command'
import {
  runLoadWriterChapterSession,
  runLoadWriterContextData
} from '@/application/writer-flow/context-session'
import { runEnsureBeatPlanCommand } from '@/application/writer-flow/beat-plan-command'
import { runFinalizeChapterCommand } from '@/application/writer-flow/finalization-command'
import { getFinalizationMarkerAction } from '@/application/writer-flow/finalization-marker-action'
import { normalizeStoryBlockReviewResult } from '@/prompts/storyBlockPrompt'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const writerStore = useWriterStore()
const novelStore = useNovelStore()
const seedStore = useSeedStore()
const memoryStore = useMemoryStore()
const settingStore = useSettingStore()
const volumeStore = useVolumeStore()
const storyBlockStore = useStoryBlockStore()
const correctionTaskStore = useCorrectionTaskStore()
const compareStore = useCompareStore()
const message = useAppMessage()
const dialog = useDialog()

const projectId = computed(() => route.params.projectId)
const chapterNum = ref(Number(route.params.chapterNum) || 1)
const editorContent = ref('')
const selectedText = ref('')
const hasSelection = ref(false)
const currentView = ref('writer')
const rightPanel = ref('tools')

const exportOptions = [
  { label: '导出 TXT', key: 'txt' },
  { label: '导出 Markdown', key: 'md' }
]

const showStyleModal = ref(false)
const showPacingModal = ref(false)
const showCompareModal = ref(false)
const compareContext = ref({})
const compareBeatPlan = ref('')
const showFusionPanel = ref(false)
const showDiffModal = ref(false)
const showContextPreview = ref(false)
const showBeatPlanModal = ref(false)
const showAuditModal = ref(false)
const readonlyAuditResult = ref(null)
const showUnsavedVersionModal = ref(false)
const auditRunning = ref(false)
const auditRevisionGenerating = ref(false)
const finalizeAuditInFlight = ref(false)
const finalizeSubmitting = ref(false)
const finalizationRetrying = ref(false)
const finalizationMarkerVersion = ref(0)
const durableFinalizationMarkers = ref([])
const chapterTitleGenerating = ref(false)
const showChapterTitleEditor = ref(false)
const chapterTitleDraft = ref('')
const chapterTitleSaving = ref(false)
const beatPlanText = ref('')
const beatPlanSavedText = ref('')
const beatPlanIntent = ref('single')
const beatPlanStageSnapshot = ref(null)
const streamingContent = ref(false)
const activeWriterAction = ref('')
const memoryProcessing = ref(false)
const chapterLoading = ref(false)
const contextLoading = ref(false)
const contextDataLoaded = ref(false)
const contextLoadError = ref('')
const showMemoryResult = ref(false)
const memoryResult = ref(null)
const contextPreview = ref({ context: {}, usedTokens: 0, maxTokens: 0, mode: 'chapter' })
const loadedEditorSnapshot = ref('')
const pendingVersionToLoad = ref(null)
const pendingFinalizeVersion = ref(null)
const previousChapterEnding = ref('')
const recentChapterEndings = ref([])
const auditIssueActions = ref({})
let autoSaveTimer = null

const beatPlanPrimaryText = computed(() => {
  if (beatPlanIntent.value === 'multi') return '生成多候选版本'
  if (beatPlanIntent.value === 'compare') return '开始多模型对比'
  return '开始生成本章'
})

const beatPlanDraftChanged = computed(() => {
  const draft = beatPlanText.value.trim()
  if (!draft) return false
  return draft !== beatPlanSavedText.value.trim()
})
const activeStoryBlock = computed(() => storyBlockStore.activeBlock)
const storyBlockPlanningBusy = computed(() => storyBlockStore.loading || storyBlockStore.aiPlanning)

const currentStoryBlockName = computed(() => {
  if (!activeStoryBlock.value) return '生成小纲前会创建故事块'
  return activeStoryBlock.value.title || activeStoryBlock.value.goal || `故事块 ${activeStoryBlock.value.blockNum || ''}`.trim()
})

const currentStoryBlockStageName = computed(() => {
  const snapshot = beatPlanStageSnapshot.value
  if (snapshot) return snapshot.stagePurpose || snapshot.stageId || '已保存阶段快照'
  const stage = activeStoryBlock.value ? findNextEditableStage(activeStoryBlock.value) : null
  return stage?.purpose || stage?.stagePurpose || stage?.id || '待生成小纲'
})

const currentStoryBlockStageSource = computed(() =>
  beatPlanStageSnapshot.value ? 'block_stage_snapshot' : '生成小纲前会创建故事块'
)

const beatPlanSourceValue = computed(() =>
  writerStore.beatPlanSource ||
  writerStore.beatPlanRecord?.beatPlanSource ||
  writerStore.beatPlanDiagnostics?.beatPlanSource ||
  writerStore.beatPlanQualityNotice?.source ||
  ''
)

const beatPlanSourceLabel = computed(() => ({
  ai_generated: 'AI 生成',
  ai_repaired: 'AI 修复',
  derived_from_story_block: '故事块派生',
  local_safety_requires_review: '需人工审阅',
  local_safety_rebuild: '需人工审阅',
  local_safety_rebuild_acknowledged: '需人工审阅'
}[beatPlanSourceValue.value] || ''))

const beatPlanSourceTagType = computed(() => {
  if (beatPlanSourceValue.value === 'derived_from_story_block') return 'info'
  if (beatPlanSourceValue.value === 'ai_repaired') return 'warning'
  if (beatPlanSourceValue.value === 'local_safety_requires_review' || beatPlanSourceValue.value === 'local_safety_rebuild') return 'error'
  return 'default'
})

const blockingAuditIssues = computed(() =>
  (memoryStore.lastAuditResult?.issues || []).filter(issue =>
    ['critical', 'major'].includes(issue.severity)
  )
)

const auditModalReport = computed(() =>
  currentChapterFinalized.value && !pendingFinalizeVersion.value
    ? readonlyAuditResult.value
    : memoryStore.lastAuditResult
)

const auditRevisionIssues = computed(() => memoryStore.lastAuditResult?.issues || [])

const hasAuditRevisionIssues = computed(() =>
  currentView.value === 'writer' &&
  !pendingFinalizeVersion.value &&
  !currentChapterFinalized.value &&
  auditRevisionIssues.value.length > 0
)

const comparisonIdSet = computed(() =>
  new Set(compareStore.comparisonVersions.map(version => version.id))
)

const editorDraftVersion = computed(() => {
  const content = editorContent.value?.trim()
  if (!content) return null
  return {
    id: '__current_editor_draft__',
    title: `第 ${chapterNum.value} 章 - 当前编辑器正文`,
    content,
    versionType: 'user_draft',
    promptBrief: '当前编辑器正文',
    createdAt: Date.now()
  }
})

function isBaselineCandidate(version) {
  const brief = String(version?.promptBrief || version?.prompt_brief || '')
  return !brief.includes('多候选生成') && !brief.includes('纠偏')
}

const diffBaseVersion = computed(() => {
  const finalVersion = writerStore.versions.find(version => version.versionType === 'final')
  if (finalVersion) return finalVersion

  if (editorDraftVersion.value) return editorDraftVersion.value

  const currentVersion = writerStore.currentVersion
  if (currentVersion?.id && !comparisonIdSet.value.has(currentVersion.id)) return currentVersion

  const baselineVersion = writerStore.versions.find(version =>
    version?.id &&
    !comparisonIdSet.value.has(version.id) &&
    isBaselineCandidate(version)
  ) || writerStore.versions.find(version =>
    version?.id &&
    !comparisonIdSet.value.has(version.id)
  )
  if (baselineVersion) return baselineVersion

  return null
})

const diffVersions = computed(() => {
  const versions = []
  const seen = new Set()
  const addVersion = version => {
    if (!version?.id || seen.has(version.id)) return
    seen.add(version.id)
    versions.push(version)
  }
  const base = diffBaseVersion.value
  addVersion(base)
  addVersion(editorDraftVersion.value)
  writerStore.versions.forEach(addVersion)
  compareStore.comparisonVersions.forEach(addVersion)
  return versions
})

const hasUnsavedVersionEdits = computed(() => {
  if (streamingContent.value) return false
  return (editorContent.value || '') !== (loadedEditorSnapshot.value || '')
})

const finalizedVersionId = computed(() =>
  writerStore.currentChapter?.finalVersionId ||
  writerStore.currentChapter?.final_version_id ||
  writerStore.versions.find(version => version.versionType === 'final')?.id ||
  ''
)
const currentChapterFinalized = computed(() => !!finalizedVersionId.value)
const latestChapter = computed(() =>
  [...(writerStore.chapters || [])]
    .sort((a, b) => Number(b.chapterNum || b.chapter_num || 0) - Number(a.chapterNum || a.chapter_num || 0))[0] || null
)
const canCreateNextChapter = computed(() => {
  if (!latestChapter.value) return true
  return isChapterFinalized(latestChapter.value)
})
const newChapterDisabledReason = computed(() =>
  canCreateNextChapter.value ? '' : '上一章未定稿，不能新建下一章。'
)

const writerActionLabels = {
  chapter: '正在生成本章',
  multi: '正在生成多候选版本',
  continue: '正在续写',
  expand: '正在扩写选区',
  compress: '正在压缩选区',
  rewrite: '正在改写选区'
}

const finalizationProcessingActive = computed(() =>
  finalizeSubmitting.value || finalizationRetrying.value || memoryProcessing.value || !!memoryStore.processing
)

const finalizationActionBusy = computed(() =>
  finalizeAuditInFlight.value || finalizationProcessingActive.value
)

const editorLocked = computed(() => !!activeWriterAction.value || writerStore.generating)

const editorLockText = computed(() =>
  currentChapterFinalized.value
    ? '本章已定稿，正文只读'
    :
  writerActionLabels[activeWriterAction.value] || 'AI 正在处理正文'
)

const currentVolume = computed(() =>
  volumeStore.volumes.find(volume =>
    chapterNum.value >= Number(volume.startChapter || 0) &&
    chapterNum.value <= Number(volume.endChapter || 0)
  )
)

function findVolumeForChapter(targetChapterNum) {
  const num = Number(targetChapterNum || 0)
  return volumeStore.volumes.find(volume =>
    num >= Number(volume.startChapter || 0) &&
    num <= Number(volume.endChapter || 0)
  )
}

const currentChapterTitleOnly = computed(() => {
  const chapter = writerStore.currentChapter || { chapterNum: chapterNum.value }
  return hasCustomChapterTitle(chapter)
    ? formatChapterDisplayTitle(chapter, { includeNumber: false })
    : ''
})

const chapterTitleActionText = computed(() =>
  currentChapterTitleOnly.value ? '重生成章名' : '生成章名'
)

const auditButtonText = computed(() =>
  currentChapterFinalized.value ? '本章审稿（只读）' : '本章审稿'
)

const auditModalTitle = computed(() => {
  if (pendingFinalizeVersion.value) return '定稿前一致性审稿报告'
  return currentChapterFinalized.value ? '定稿复查报告' : '本章一致性审稿报告'
})

function chapterListTitle(chapter) {
  return formatChapterDisplayTitle(chapter, { includeNumber: false })
}

function hasCustomChapterTitle(chapter) {
  return !isDefaultChapterTitle(chapter?.title, chapter?.chapterNum || chapter?.chapter_num)
}

const aiContextReady = computed(() =>
  contextDataLoaded.value &&
  !contextLoading.value &&
  !chapterLoading.value &&
  !finalizationProcessingActive.value
)

const pendingSettingChanges = computed(() =>
  settingStore.changeEvents.filter(event => (event.status || 'pending_review') === 'pending_review')
)

const pendingCanonFacts = computed(() =>
  novelStore.canonFacts.filter(fact => (fact.status || 'accepted') === 'pending_review')
)

const blockingFinalizationPending = computed(() => {
  finalizationMarkerVersion.value
  return findBlockingFinalizationPending()
})

const finalizationMarkerAction = computed(() =>
  getFinalizationMarkerAction(blockingFinalizationPending.value)
)

const postFinalizeFailed = computed(() =>
  Boolean(
    blockingFinalizationPending.value?.postFinalizeFailed ||
    blockingFinalizationPending.value?.retryablePostprocessFailure ||
    blockingFinalizationPending.value?.storyBlockSettlementFailure
  )
)

const aiContextStatusText = computed(() => {
  if (finalizationProcessingActive.value) return '正在提取定稿后的记忆和设定'
  if (chapterLoading.value) return '正在加载章节资料'
  if (contextLoading.value) return '正在加载创作上下文'
  if (contextLoadError.value) return `创作上下文加载失败：${contextLoadError.value}`
  if (!contextDataLoaded.value) return '创作上下文尚未就绪'
  return ''
})

onMounted(async () => {
  try {
    compareStore.clearComparison()
    if (!projectStore.currentProject || projectStore.currentProject.id !== projectId.value) {
      await projectStore.openProject(projectId.value)
    }
    await loadChapter()
    await loadContextData()
  } catch (e) {
    message.error('初始化写字台失败：' + e.message)
  }
})

watch(chapterNum, async (newNum) => {
  showBeatPlanModal.value = false
  showCompareModal.value = false
  showAuditModal.value = false
  memoryStore.lastAuditResult = null
  readonlyAuditResult.value = null
  auditIssueActions.value = {}
  beatPlanText.value = ''
  beatPlanSavedText.value = ''
  beatPlanStageSnapshot.value = null
  compareContext.value = {}
  compareBeatPlan.value = ''
  previousChapterEnding.value = ''
  recentChapterEndings.value = []
  compareStore.clearComparison()
  await loadChapter()
  router.replace(`/writer/${projectId.value}/${newNum}`)
})

async function loadContextData() {
  contextLoadError.value = ''
  contextLoading.value = true
  try {
    await runLoadWriterContextData({
      projectId: projectId.value,
      loaders: {
        loadBible: novelStore.loadBible,
        loadOutline: novelStore.loadOutline,
        loadCharacters: novelStore.loadCharacters,
        loadPlotThreads: novelStore.loadPlotThreads,
        loadCanonFacts: novelStore.loadCanonFacts,
        loadSettingEntities: settingStore.loadEntities,
        loadSettingRelations: settingStore.loadRelations,
        loadSettingChangeEvents: settingStore.loadChangeEvents,
        loadVolumes: volumeStore.loadVolumes,
        loadStoryBlocks: storyBlockStore.loadBlocks,
        loadCorrectionTasks: correctionTaskStore.loadTasks,
        loadSeeds: seedStore.loadSeeds
      }
    })
    await loadDurableFinalizationMarkers(projectId.value)
    contextDataLoaded.value = true
  } catch (e) {
    contextDataLoaded.value = false
    contextLoadError.value = e?.message || String(e)
    message.error(`创作上下文加载失败：${contextLoadError.value}`)
    throw e
  } finally {
    contextLoading.value = false
  }
}

async function loadChapter() {
  chapterLoading.value = true
  try {
    const session = await runLoadWriterChapterSession({
      projectId: projectId.value,
      chapterNum: chapterNum.value,
      loaders: {
        loadChapters: writerStore.loadChapters,
        loadBlocks: storyBlockStore.loadBlocks,
        getOrCreateChapter: writerStore.getOrCreateChapter,
        loadVersions: writerStore.loadVersions,
        loadChapterBeatPlan: writerStore.loadChapterBeatPlan,
        loadPreviousChapterEnding,
        loadRecentChapterEndings,
        loadTempDraft: writerStore.loadTempDraft
      }
    })
    beatPlanText.value = session.beatPlanText
    beatPlanSavedText.value = session.beatPlanSavedText
    beatPlanStageSnapshot.value = session.beatPlanStageSnapshot
    previousChapterEnding.value = session.previousChapterEnding
    recentChapterEndings.value = session.recentChapterEndings
    editorContent.value = session.editorContent
    loadedEditorSnapshot.value = session.loadedEditorSnapshot
    if (session.shouldUpdateCurrentVersion) {
      writerStore.currentVersion = session.currentVersion
    }
  } catch (e) {
    message.error('加载章节失败：' + e.message)
  } finally {
    chapterLoading.value = false
  }
}

async function loadPreviousChapterEnding() {
  if (chapterNum.value <= 1) return ''
  const previousChapter = writerStore.chapters.find(ch => Number(ch.chapterNum || 0) === chapterNum.value - 1)
  if (!previousChapter?.id) return ''

  try {
    const versions = await api.versions.list(projectId.value, previousChapter.id)
    const finalVersionId = previousChapter.finalVersionId || previousChapter.final_version_id
    const finalVersion = versions.find(version => version.id === finalVersionId || version.versionType === 'final')
    const sourceVersion = finalVersion
    const content = String(sourceVersion?.content || '').trim()
    if (!content) return ''
    return content.length > 1400 ? content.slice(-1400) : content
  } catch (e) {
    console.warn('加载上一章结尾失败:', e.message)
    return ''
  }
}

function extractChapterEndingSnippet(content, maxLength = 260) {
  const paragraphs = String(content || '')
    .split(/\n{2,}/)
    .map(item => item.trim())
    .filter(Boolean)
  if (!paragraphs.length) return ''

  const ending = paragraphs.slice(-2).join('\n\n')
  return ending.length > maxLength ? ending.slice(-maxLength) : ending
}

async function loadRecentChapterEndings(limit = 5) {
  if (chapterNum.value <= 1) return []
  const previousChapters = writerStore.chapters
    .filter(ch => Number(ch.chapterNum || ch.chapter_num || 0) < chapterNum.value)
    .sort((a, b) => Number(b.chapterNum || b.chapter_num || 0) - Number(a.chapterNum || a.chapter_num || 0))
    .slice(0, limit)

  const endings = await Promise.all(previousChapters.map(async chapter => {
    try {
      const versions = await api.versions.list(projectId.value, chapter.id)
      const finalVersionId = chapter.finalVersionId || chapter.final_version_id
      const finalVersion = versions.find(version => version.id === finalVersionId || version.versionType === 'final')
      const snippet = extractChapterEndingSnippet(finalVersion?.content)
      if (!snippet) return null
      return {
        chapterNum: Number(chapter.chapterNum || chapter.chapter_num || 0),
        ending: snippet
      }
    } catch (e) {
      console.warn('加载最近章节结尾失败:', e.message)
      return null
    }
  }))

  return endings
    .filter(Boolean)
    .sort((a, b) => Number(a.chapterNum || 0) - Number(b.chapterNum || 0))
}

function handleSelectionChange() {
  const textarea = document.querySelector('.writer-editor textarea')
  if (!textarea) return
  const start = textarea.selectionStart
  const end = textarea.selectionEnd
  selectedText.value = editorContent.value.substring(start, end)
  hasSelection.value = start !== end
}

function handleContentChange() {
  clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(async () => {
    await writerStore.saveTempDraft(projectId.value, chapterNum.value, editorContent.value)
  }, 2000)
}

async function handleGenerateChapterTitle() {
  if (chapterTitleGenerating.value || finalizationActionBusy.value) return
  const chapter = writerStore.currentChapter
  const content = editorContent.value.trim()
  const validation = validateGenerateChapterTitleInput({ chapter, content })
  if (!validation.ok && validation.code === 'chapterNotReady') {
    message.warning('当前章节还未加载完成，暂时不能生成章名')
    return
  }
  if (!validation.ok && validation.code === 'emptyContent') {
    message.warning('当前正文为空，无法生成章名')
    return
  }

  chapterTitleGenerating.value = true
  try {
    const result = await runGenerateChapterTitleCommand({
      projectId: projectId.value,
      chapter,
      chapterNum: chapterNum.value,
      content,
      chapterGoal: contextPreview.value?.context?.chapterGoal,
      beatPlan: beatPlanSavedText.value || beatPlanText.value,
      generateDefaultChapterTitle: writerStore.generateDefaultChapterTitle
    })
    if (!result.ok && result.code === 'chapterNotReady') {
      message.warning('当前章节还未加载完成，暂时不能生成章名')
      return
    }
    if (!result.ok && result.code === 'emptyContent') {
      message.warning('当前正文为空，无法生成章名')
      return
    }
    if (!result.ok && result.openEditor) {
      message.warning('AI 没有生成合格章名，请稍后重试或手动编辑章节标题')
      openChapterTitleEditor()
      return
    }
    if (!result.ok) return
    message.success(`章名已更新为《${result.title}》`)
  } catch (e) {
    message.error('生成章名失败：' + e.message)
  } finally {
    chapterTitleGenerating.value = false
  }
}

function openChapterTitleEditor() {
  const chapter = writerStore.currentChapter
  chapterTitleDraft.value = hasCustomChapterTitle(chapter)
    ? formatChapterDisplayTitle(chapter, { includeNumber: false })
    : ''
  showChapterTitleEditor.value = true
}

async function handleSaveManualChapterTitle() {
  const chapter = writerStore.currentChapter
  const title = normalizeManualChapterTitle(chapterTitleDraft.value)
  const validation = validateManualChapterTitle({
    chapter,
    chapterNum: chapterNum.value,
    title: chapterTitleDraft.value,
    assessTitle: getChapterTitleQuality
  })
  if (!validation.ok && validation.code === 'chapterNotReady') {
    message.warning('当前章节还未加载完成，暂时不能编辑章名')
    return
  }
  if (!validation.ok && validation.code === 'emptyTitle') {
    message.warning('章节标题不能为空')
    return
  }
  if (!validation.ok && validation.code === 'invalidManualTitleShape') {
    message.warning('章节标题建议控制在 30 个字以内，且不能换行')
    return
  }
  if (!validation.ok && validation.code === 'invalidTitlePolicy') {
    message.warning(`章节标题不可用：${validation.details.reason || '非法标题'}`)
    return
  }

  chapterTitleSaving.value = true
  try {
    const result = await runSaveManualChapterTitleCommand({
      projectId: projectId.value,
      chapter,
      chapterNum: chapterNum.value,
      draftTitle: chapterTitleDraft.value,
      assessTitle: getChapterTitleQuality,
      updateChapterTitle: writerStore.updateChapterTitle
    })
    if (!result.ok) return
    showChapterTitleEditor.value = false
    message.success(`章节标题已更新为《${result.title || title}》`)
  } catch (e) {
    message.error('保存章节标题失败：' + e.message)
  } finally {
    chapterTitleSaving.value = false
  }
}

function auditIssueKey(issue, idx) {
  return `${idx}:${issue?.location || issue?.description || ''}`
}

function auditIssueStatus(issue, idx) {
  return auditIssueActions.value[auditIssueKey(issue, idx)] || ''
}

function setAuditIssueStatus(issue, idx, status) {
  auditIssueActions.value = {
    ...auditIssueActions.value,
    [auditIssueKey(issue, idx)]: status
  }
}

function auditIssueQuote(issue) {
  return cleanAuditQuote(issue?.location || issue?.quote || issue?.evidence || '')
}

function auditIssueReplacement(issue) {
  return getAuditReplacement(issue)
}

function auditLocateWarning(reason) {
  if (reason === 'missing_location') return '这条审稿问题没有可定位的原文片段'
  if (reason === 'ambiguous') return '当前原文片段命中多个相似位置，请先定位确认或手动选区改写'
  return '当前正文中没有找到该原文片段，可能已经被修改过'
}

async function focusEditorRange(start, end) {
  await nextTick()
  const textarea = document.querySelector('.writer-editor textarea')
  if (!textarea) return false
  textarea.focus()
  textarea.setSelectionRange(start, end)
  selectedText.value = editorContent.value.substring(start, end)
  hasSelection.value = start !== end
  return true
}

async function locateAuditIssue(issue, idx) {
  const located = locateAuditQuote(editorContent.value, issue)
  if (!located.found) {
    setAuditIssueStatus(issue, idx, 'not_found')
    message.warning(auditLocateWarning(located.reason))
    return false
  }
  await focusEditorRange(located.index, located.index + located.quote.length)
  setAuditIssueStatus(issue, idx, 'located')
  return true
}

async function replaceAuditIssue(issue, idx) {
  if (!ensureCurrentChapterEditable('审稿建议替换')) return
  const replacement = auditIssueReplacement(issue)
  if (!replacement) {
    message.warning('这条审稿问题没有可直接替换的文本，请手动修改或重新审稿')
    return
  }
  const result = applyAuditReplacement(editorContent.value, issue, replacement)
  if (!result.ok) {
    setAuditIssueStatus(issue, idx, result.reason)
    message.warning(auditLocateWarning(result.reason))
    return
  }
  editorContent.value = result.content
  setAuditIssueStatus(issue, idx, 'applied')
  await focusEditorRange(result.index, result.index + result.replacement.length)
  handleContentChange()
  message.success('已替换该处审稿建议，当前正文已进入未另存状态')
}

function ignoreAuditIssue(issue, idx) {
  setAuditIssueStatus(issue, idx, 'ignored')
}

function clearAuditRevisionPanel() {
  memoryStore.lastAuditResult = null
  readonlyAuditResult.value = null
  auditIssueActions.value = {}
}

function getSelectedSeed() {
  return seedStore.seeds.find(seed => seed.status === 'selected')
}

function buildSequenceRules() {
  const rules = [
    '本章正文必须从本章时间线最早的可写场景开始。',
    '禁止用后续会议结论、追查结果、角色受伤或死亡后的余波作为开头，除非本章小纲第一条明确要求。',
    '每一段必须承接上一段的时间、地点或视角，不要突然跳到未铺垫的会议、审讯、复盘或事后结论。',
    '如果需要倒叙、插叙或闪回，必须先用当前场景落地，再自然切入。'
  ]
  if (chapterNum.value === 1) {
    rules.push('第一章必须从创作种子的开局钩子或主角初始处境开始，不要先写背景结论、势力会议或后续反应。')
  }
  return rules
}

function buildSeedContext(seed) {
  if (!seed) return null
  return {
    genre: seed.genre,
    logline: seed.logline,
    protagonist: seed.protagonist,
    desire: seed.desire,
    coreConflict: seed.coreConflict,
    worldPressure: seed.worldPressure,
    openingHook: seed.openingHook,
    styleTarget: seed.styleTarget,
    differentiation: seed.differentiation
  }
}

function buildFinalizationRerouteContext(results, version, finalizedChapterNum) {
  const nextChapterNum = Number(finalizedChapterNum || 0) + 1
  const content = String(version?.content || '')
  return {
    projectInfo: projectStore.currentProject,
    seedInfo: buildSeedContext(getSelectedSeed()),
    bibleInfo: novelStore.bible,
    finalizedChapterNum,
    currentChapterNum: nextChapterNum,
    finalizedChapterInfo: {
      chapterNum: finalizedChapterNum,
      title: writerStore.currentChapter?.title || '',
      summary: results?.summary || null,
      contentExcerpt: content.slice(0, 1800),
      ending: content.slice(-900)
    },
    factInfo: {
      extractedFacts: results?.facts || [],
      acceptedFacts: (novelStore.canonFacts || []).filter(fact => (fact.status || 'accepted') === 'accepted')
    },
    settingInfo: {
      pendingSettingChanges: results?.settingChanges || [],
      activeEntities: (settingStore.entities || []).filter(entity => (entity.status || 'active') === 'active')
    },
    currentVolumeInfo: findVolumeForChapter(nextChapterNum) || currentVolume.value || null,
    volumeInfo: volumeStore.volumes,
    existingOutlineInfo: novelStore.outline
  }
}

function buildBaseContext() {
  return buildBaseContextResult().context
}

async function loadDurableFinalizationMarkers(pid = projectId.value) {
  if (!pid) {
    durableFinalizationMarkers.value = []
    return []
  }
  try {
    const rows = await api.projectState.finalizationMarkers.list(pid)
    durableFinalizationMarkers.value = Array.isArray(rows) ? rows : []
  } catch (error) {
    if (isProjectStateMigrationUnavailable(error)) {
      durableFinalizationMarkers.value = []
      return []
    }
    throw error
  }
  return durableFinalizationMarkers.value
}

function isProjectStateMigrationUnavailable(error) {
  const message = String(error?.message || error || '').toLowerCase()
  const hasExplicitMigrationFlag = Boolean(error?.migrationUnavailable || error?.migration_unavailable)
  const mentionsProjectStateTable = (
    message.includes('finalization_markers') ||
    message.includes('project_health_checks')
  )
  const missingProjectStateTableError = mentionsProjectStateTable && (
    message.includes('no such table') ||
    message.includes("doesn't exist") ||
    message.includes('does not exist') ||
    message.includes('unknown table') ||
    message.includes('undefinedtable')
  )
  return (
    hasExplicitMigrationFlag ||
    message.includes('migrationunavailable') ||
    message.includes('migration unavailable') ||
    missingProjectStateTableError
  )
}

async function saveDurableFinalizationMarker(targetChapterNum, marker) {
  try {
    return await api.projectState.finalizationMarkers.save(projectId.value, targetChapterNum, marker)
  } catch (error) {
    if (isProjectStateMigrationUnavailable(error)) {
      return null
    }
    throw error
  }
}

function finalizationMarkerChapterNum(marker) {
  return Number(marker?.chapterNum || marker?.chapter_num || marker?.sourceChapterNum || marker?.source_chapter_num || 0)
}

function finalizationMarkerStatus(marker) {
  return String(marker?.commitStatus || marker?.commit_status || marker?.status || 'pending').trim().toLowerCase()
}

function isBlockingFinalizationMarker(marker) {
  const status = finalizationMarkerStatus(marker)
  return ['pending', 'in_progress', 'started', 'validated', 'half_success', 'failed_after_chapter_commit'].includes(status)
}

function findDurableFinalizationPending(num) {
  return (durableFinalizationMarkers.value || []).find(marker =>
    finalizationMarkerChapterNum(marker) === Number(num) && isBlockingFinalizationMarker(marker)
  ) || null
}

function durableFinalizationMarkerKey(marker) {
  return [
    finalizationMarkerChapterNum(marker),
    marker?.runId || marker?.run_id || '',
    marker?.finalizationId || marker?.finalization_id || ''
  ].join('|')
}

function upsertDurableFinalizationMarker(marker) {
  if (!marker) return
  const markerKey = durableFinalizationMarkerKey(marker)
  const existingIndex = durableFinalizationMarkers.value.findIndex(item =>
    durableFinalizationMarkerKey(item) === markerKey
  )
  if (existingIndex >= 0) {
    durableFinalizationMarkers.value.splice(existingIndex, 1, marker)
  } else {
    durableFinalizationMarkers.value.push(marker)
  }
}

function removeDurableFinalizationMarker(targetChapterNum, marker) {
  const markerKey = durableFinalizationMarkerKey(marker)
  durableFinalizationMarkers.value = (durableFinalizationMarkers.value || []).filter(item => {
    const sameChapter = finalizationMarkerChapterNum(item) === Number(targetChapterNum)
    const sameMarker = markerKey === durableFinalizationMarkerKey(item)
    return !(sameChapter && (sameMarker || isBlockingFinalizationMarker(item)))
  })
}

function collectContextFinalizationMarkers() {
  const markers = []
  const markerNums = new Set([Number(chapterNum.value)])
  for (const chapter of writerStore.chapters || []) {
    const num = Number(chapter.chapterNum || chapter.chapter_num || 0)
    if (num > 0 && num <= Number(chapterNum.value)) markerNums.add(num)
  }
  for (const marker of durableFinalizationMarkers.value || []) {
    const num = finalizationMarkerChapterNum(marker)
    if (num > 0 && num <= Number(chapterNum.value)) markerNums.add(num)
  }

  const seen = new Set()
  const pushMarker = marker => {
    if (!marker) return
    const num = finalizationMarkerChapterNum(marker)
    const key = [
      num,
      marker.runId || marker.run_id || '',
      marker.finalizationId || marker.finalization_id || '',
      finalizationMarkerStatus(marker)
    ].join('|')
    if (seen.has(key)) return
    seen.add(key)
    markers.push(marker)
  }

  for (const num of markerNums) {
    pushMarker(getChapterFinalizationPending(projectId.value, num))
  }
  for (const marker of durableFinalizationMarkers.value || []) {
    const num = finalizationMarkerChapterNum(marker)
    if (num > 0 && num <= Number(chapterNum.value)) pushMarker(marker)
  }
  return markers
}

function findBlockingFinalizationPending() {
  const nums = new Set([Number(chapterNum.value)])
  for (const chapter of writerStore.chapters || []) {
    const num = Number(chapter.chapterNum || chapter.chapter_num || 0)
    if (num > 0 && num <= Number(chapterNum.value)) nums.add(num)
  }
  for (const marker of durableFinalizationMarkers.value || []) {
    const num = finalizationMarkerChapterNum(marker)
    if (num > 0 && num <= Number(chapterNum.value)) nums.add(num)
  }

  for (const num of [...nums].sort((a, b) => a - b)) {
    const marker = getChapterFinalizationPending(projectId.value, num)
    if (marker) return marker
    const durableMarker = findDurableFinalizationPending(num)
    if (durableMarker) return durableMarker
  }
  return null
}

async function reconcileCompletedFinalizationMarker(marker, actionName = 'AI 操作') {
  const num = Number(marker?.chapterNum || 0)
  if (!num || !projectId.value) return false
  try {
    await Promise.allSettled([
      writerStore.loadChapters(projectId.value),
      settingStore.loadChangeEvents(projectId.value),
      novelStore.loadCanonFacts(projectId.value)
    ])

    const chapter = writerStore.chapters.find(ch => Number(ch.chapterNum || ch.chapter_num || 0) === num)
    if (!isChapterFinalized(chapter)) return false

    const hasPendingSettings = settingStore.changeEvents.some(event => (event.status || 'pending_review') === 'pending_review')
    const hasPendingFacts = novelStore.canonFacts.some(fact => (fact.status || 'accepted') === 'pending_review')
    if (hasPendingSettings || hasPendingFacts) return false

    const beat = await api.beatPlans.get(projectId.value, num).catch(() => null)
    if (!beat?.storyBlockId) return false
    const blocks = await storyBlockStore.loadBlocks(projectId.value).catch(() => [])
    const block = (blocks || []).find(item => item.id === beat.storyBlockId)
    const reviews = block?.reviewHistory || block?.review_history || []
    const hasStoryBlockReview = Array.isArray(reviews) && reviews.some(review =>
      review?.decision && Number(review.chapterNum || review.chapter_num || num) === num
    )
    if (!hasStoryBlockReview) return false

    clearChapterFinalizationPending(projectId.value, num)
    finalizationMarkerVersion.value += 1
    console.info(`已清理第 ${num} 章残留定稿后处理标记，允许继续${actionName}`)
    return true
  } catch (e) {
    console.warn(`检查第 ${num} 章定稿后处理标记失败`, e)
    return false
  }
}

async function ensureAiContextReady(actionName = 'AI 操作') {
  if (finalizationProcessingActive.value) {
    message.warning(
      `上一章或当前章节定稿后的记忆/设定提取仍在进行。请等待处理完成后再执行${actionName}，否则下一章可能读不到最新人物状态和设定变更。`,
      { title: '定稿后处理未完成' }
    )
    return false
  }

  const blockingFinalization = findBlockingFinalizationPending()
  if (blockingFinalization) {
    const reconciled = await reconcileCompletedFinalizationMarker(blockingFinalization, actionName)
    if (reconciled) return true
    message.warning(
      `第 ${blockingFinalization.chapterNum} 章定稿后记忆/设定提取失败或未完成，已阻止${actionName}。请先处理该章的定稿后提取结果，再继续后续章节，避免人物状态、设定库和长期记忆断层。`,
      { title: '定稿后处理未完成' }
    )
    return false
  }

  if (chapterLoading.value || contextLoading.value) {
    message.warning(`${aiContextStatusText.value || '资料加载中'}，请稍后再执行${actionName}`)
    return false
  }

  if (!contextDataLoaded.value) {
    try {
      await loadContextData()
    } catch (e) {
      message.error(`创作上下文加载失败，已阻止${actionName}：${e.message}`)
      return false
    }
  }

  if (!contextDataLoaded.value) {
    message.warning(`创作上下文尚未就绪，已阻止${actionName}`)
    return false
  }

  try {
    const result = buildBaseContextResult()
    assertContextPackHealthy(result.contextPack)
  } catch (e) {
    message.warning(
      `ContextPack 健康检查未通过，已阻止${actionName}：${e.message}`,
      { title: '创作上下文不可信' }
    )
    return false
  }

  return true
}

async function ensureNoPendingSettingChanges(actionName = 'AI 写作') {
  let pendingResult = checkPendingSettingChanges({ pendingSettingChanges: pendingSettingChanges.value })
  if (!pendingResult.ok) {
    message.warning(
      `设定库还有 ${pendingResult.details.count} 条待确认变更。${actionName}只会读取已确认的设定库和已确认事实，未确认的上一章人物状态、关系、地点、能力变化不会作为硬设定进入下一章。请先到“记忆/设定库”确认或拒绝这些变更，再继续生成，避免后续章节错乱。`,
      { title: '请先确认设定变更' }
    )
    return false
  }

  try {
    await settingStore.loadChangeEvents(projectId.value)
  } catch (e) {
    message.warning(`无法刷新待确认设定变更，已阻止${actionName}：${e.message}`)
    return false
  }

  pendingResult = checkPendingSettingChanges({ pendingSettingChanges: pendingSettingChanges.value })
  if (!pendingResult.ok) {
    message.warning(
      `设定库还有 ${pendingResult.details.count} 条待确认变更。请先确认或拒绝后再执行${actionName}。`,
      { title: '请先确认设定变更' }
    )
    return false
  }

  return true
}

async function ensureNoPendingStoryMemory(actionName = 'AI 写作') {
  let pendingResult = checkPendingStoryMemory({ pendingCanonFacts: pendingCanonFacts.value })
  if (!pendingResult.ok) {
    message.warning(
      `记忆里还有 ${pendingResult.details.count} 条待确认事实。${actionName}只会读取已确认事实，未确认的上一章事件、状态、伏笔或时间线不会进入下一章。请先到“记忆”确认或拒绝这些事实，再继续生成。`,
      { title: '请先确认记忆事实' }
    )
    return false
  }

  try {
    await novelStore.loadCanonFacts(projectId.value)
  } catch (e) {
    message.warning(`无法刷新待确认记忆事实，已阻止${actionName}：${e.message}`)
    return false
  }

  pendingResult = checkPendingStoryMemory({ pendingCanonFacts: pendingCanonFacts.value })
  if (!pendingResult.ok) {
    message.warning(
      `记忆里还有 ${pendingResult.details.count} 条待确认事实。请先确认或拒绝后再执行${actionName}。`,
      { title: '请先确认记忆事实' }
    )
    return false
  }

  return true
}

async function ensureCorrectionTasksAllowGeneration(actionName = 'AI 写作') {
  try {
    await correctionTaskStore.loadTasks(projectId.value)
  } catch (e) {
    message.warning(`无法刷新纠偏任务，已阻止${actionName}：${e.message}`)
    return false
  }

  const activeTasks = correctionTaskStore.tasks.filter(isCorrectionTaskActiveForContext)
  const blockers = activeTasks.filter(task =>
    isCorrectionTaskBlockingForGeneration(task) && correctionTaskAppliesToChapter(task, chapterNum.value)
  )
  const blockerResult = checkCorrectionTaskBlocker({ blockers })
  if (!blockerResult.ok) {
    message.warning(
      `当前存在 ${blockerResult.details.blockerCount} 条阻断型纠偏任务未处理。请先到「项目详情 > 6 纠偏任务」确认、完成或忽略后，再继续${actionName}。`,
      { title: '请先处理关键纠偏' }
    )
    return false
  }

  const softTasks = activeTasks.filter(task =>
    !isCorrectionTaskBlockingForGeneration(task) && correctionTaskAppliesToChapter(task, chapterNum.value)
  )
  if (softTasks.length) {
    message.info(
      `当前有 ${softTasks.length} 条软纠偏任务，会作为后续章节生成约束进入 AI 上下文，不会阻断${actionName}。`,
      { title: '软纠偏已纳入上下文' }
    )
  }

  return true
}

function correctionTaskAppliesToChapter(task, targetChapterNum) {
  const refs = (task.chapterRefs || [])
    .map(ref => Number(ref))
    .filter(ref => Number.isFinite(ref) && ref > 0)
  if (!refs.length) return true
  if (refs.includes(Number(targetChapterNum))) return true
  const mode = correctionTaskMode(task)
  return mode !== 'hard' && refs.some(ref => ref < Number(targetChapterNum))
}

function getChapterFinalVersionId(chapter) {
  return chapter?.finalVersionId || chapter?.final_version_id || ''
}

function isChapterFinalized(chapter) {
  return !!(
    chapter &&
    (
      chapter.status === 'final' ||
      getChapterFinalVersionId(chapter)
    )
  )
}

function ensureCurrentChapterEditable(actionName = 'AI 写作') {
  const result = checkCurrentChapterWritable({ currentChapterFinalized: currentChapterFinalized.value })
  if (result.ok) return true
  message.warning(
    `本章已经定稿，不能再执行${actionName}。定稿后的正文、小纲和版本已锁定，避免记忆、设定库和后续章节上下文发生错乱。`,
    { title: '本章已定稿' }
  )
  return false
}

async function ensurePreviousChapterFinalized(actionName = 'AI 写作') {
  if (chapterNum.value <= 1) return true

  let previousChapter = writerStore.chapters.find(ch => Number(ch.chapterNum || ch.chapter_num || 0) === chapterNum.value - 1)
  if (!previousChapter) {
    try {
      await writerStore.loadChapters(projectId.value)
      previousChapter = writerStore.chapters.find(ch => Number(ch.chapterNum || ch.chapter_num || 0) === chapterNum.value - 1)
    } catch (e) {
      message.warning(`无法检查上一章定稿状态，已阻止${actionName}：${e.message}`)
      return false
    }
  }

  const finalizedResult = checkPreviousChapterFinalized({
    chapterNum: chapterNum.value,
    previousChapter
  })
  if (!finalizedResult.ok) {
    message.warning(
      `第 ${chapterNum.value - 1} 章还没有定稿，不能继续执行第 ${chapterNum.value} 章的${actionName}。请先回到上一章选择最终版本并定稿，再继续生成下一章，避免章节衔接和人物状态断层。`,
      { title: '请先定稿上一章' }
    )
    return false
  }

  const previousProcessing =
    getChapterFinalizationPending(projectId.value, chapterNum.value - 1) ||
    findDurableFinalizationPending(chapterNum.value - 1)
  const pendingResult = checkPreviousChapterFinalized({
    chapterNum: chapterNum.value,
    previousChapter,
    previousFinalizationPending: previousProcessing
  })
  if (!pendingResult.ok) {
    const reconciled = await reconcileCompletedFinalizationMarker(previousProcessing, actionName)
    if (!reconciled) {
      message.warning(
        `第 ${chapterNum.value - 1} 章定稿后的记忆和设定变更还在提取中，暂时不能执行第 ${chapterNum.value} 章的${actionName}。请等提取完成，并处理待确认设定变更后再继续。`,
        { title: '上一章定稿后处理未完成' }
      )
      return false
    }
  }
  if (finalizationProcessingActive.value) {
    message.warning(
      `第 ${chapterNum.value - 1} 章定稿后的记忆和设定变更还在提取中，暂时不能执行第 ${chapterNum.value} 章的${actionName}。请等提取完成，并处理待确认设定变更后再继续。`,
      { title: '上一章定稿后处理未完成' }
    )
    return false
  }

  return true
}

function writeWriterContextDiagnostics(context = {}) {
  if (typeof window === 'undefined') return
  const companionVoiceCards = String(context.companionVoiceCards || '')
  window.__LONGFORM_WRITER_CONTEXT_DIAGNOSTICS__ = {
    chapterNum: Number(chapterNum.value),
    companionVoiceCardsInjected: Boolean(companionVoiceCards.trim()),
    companionVoiceCardNames: ['老陈', '小九', '老太太', '灰衣人', '徐主簿', '徐正清', '乙十七']
      .filter(name => companionVoiceCards.includes(name)),
    companionVoiceCardsLength: companionVoiceCards.length,
    sampleCardInjected: false,
    sampleCardId: '',
    sampleCardTitle: '',
    sampleCardType: '',
    sampleInjectionReason: '',
    microDemoChars: 0,
    sourceFieldsStripped: true,
    sampleLeakageDetected: false,
    updatedAt: new Date().toISOString()
  }
}

function buildBaseContextResult() {
  const finalizationMarkers = collectContextFinalizationMarkers()

  const result = buildWritingContext(
    novelStore,
    chapterNum.value,
    undefined,
    settingStore,
    volumeStore,
    correctionTaskStore,
    {
      storyBlock: activeStoryBlock.value,
      blockStageSnapshot: beatPlanStageSnapshot.value,
      chapters: writerStore.chapters,
      finalizationMarkers
    }
  )
  const seedContext = buildSeedContext(getSelectedSeed())
  if (seedContext) {
    result.context.seed = seedContext
    if (chapterNum.value === 1 && seedContext.openingHook) {
      result.context.openingAnchor = seedContext.openingHook
    }
  }
  result.context.sequenceRules = buildSequenceRules()
  if (previousChapterEnding.value) {
    result.context.previousChapterEnding = previousChapterEnding.value
  }
  if (recentChapterEndings.value.length) {
    result.context.recentChapterEndings = recentChapterEndings.value
  }
  if (activeStoryBlock.value) {
    result.context.storyBlock = activeStoryBlock.value
  }
  if (beatPlanStageSnapshot.value) {
    result.context.blockStageSnapshot = beatPlanStageSnapshot.value
  }
  const wordTarget = buildChapterWordTarget(projectStore.currentProject || {}, result.context.volumeStage)
  if (wordTarget) {
    result.context.wordTarget = wordTarget
  }
  writeWriterContextDiagnostics(result.context)
  return result
}

function buildConfirmedChapterContext(confirmedPlan) {
  const context = {
    ...buildBaseContext(),
    beatPlan: confirmedPlan,
    beatPlanConfirmedByUser: true,
    blockStageSnapshot: beatPlanStageSnapshot.value
  }
  writeWriterContextDiagnostics(context)
  return context
}

function buildPlanningContext() {
  const context = buildBaseContext()
  const draft = editorContent.value?.trim()
  if (draft) context.currentDraft = draft.length > 3000 ? draft.slice(-3000) : draft
  return context
}

function notifyWordCountIfNeeded(content, wordTarget = buildBaseContext().wordTarget) {
  const assessment = assessChapterWordCount(content, wordTarget)
  if (!assessment.message) return
  const options = { title: '章节字数提醒' }
  if (['hard_over', 'hard_under'].includes(assessment.level)) {
    message.warning(assessment.message, options)
  } else {
    message.info(assessment.message, options)
  }
}

function notifyGeneratedVersionsWordCount(versions, wordTarget = buildBaseContext().wordTarget) {
  const assessments = (versions || [])
    .map(version => assessChapterWordCount(version?.content, wordTarget))
    .filter(item => item.message)
  if (!assessments.length) return

  const hard = assessments.find(item => ['hard_over', 'hard_under'].includes(item.level))
  const selected = hard || assessments[0]
  const suffix = assessments.length > 1 ? `（另有 ${assessments.length - 1} 个候选也超出建议范围）` : ''
  const options = { title: '章节字数提醒' }
  if (selected.level === 'hard_over') {
    message.warning(`${selected.message}${suffix}`, options)
  } else {
    message.info(`${selected.message}${suffix}`, options)
  }
}

async function ensureChapterAboveHardWordMinBeforeFinalize(version) {
  const wordTarget = buildBaseContext().wordTarget
  const assessment = assessChapterWordCount(version?.content || '', wordTarget)
  const result = checkChapterHardWordMinimum({ assessment, wordTarget })
  if (result.ok) return true
  const error = new Error(`正文低于硬下限，请扩写或重新生成。本章约 ${result.details.count} 字，硬下限 ${result.details.hardMin} 字。`)
  error.code = 'chapter_below_hard_min'
  message.error(error.message, { title: '正文低于硬下限' })
  return false
}

function openContextPreview(mode = 'chapter') {
  if (!aiContextReady.value) {
    message.warning(aiContextStatusText.value || '创作上下文尚未就绪')
    return
  }
  const result = buildBaseContextResult()
  if (['planning', 'rewrite'].includes(mode)) {
    const draft = editorContent.value?.trim()
    if (draft) result.context.currentDraft = draft.length > 3000 ? draft.slice(-3000) : draft
  }
  contextPreview.value = {
    context: result.context,
    usedTokens: result.usedTokens,
    maxTokens: result.maxTokens,
    mode
  }
  showContextPreview.value = true
}

async function ensureStoryBlockReady(actionName = '小纲生成') {
  if (!projectId.value) return null
  await storyBlockStore.loadBlocks(projectId.value)
  let block = activeStoryBlock.value
  if (block && isStoryBlockReviewRequired(block)) {
    message.warning('当前故事块是 AI 规划失败后的人工占位，需要先审阅并确认故事块后再继续。', { title: '请先确认故事块' })
    return null
  }
  if (block) {
    block = await settleOpenStageContinuationBeforeBeatPlan(block, actionName) || block
  }
  if (block && findNextEditableStage(block)) return block
  if (block) {
    const extendedBlock = await ensureActiveBlockHasForwardStages(block, actionName)
    if (extendedBlock && findNextEditableStage(extendedBlock)) return extendedBlock
    message.warning('当前故事块没有可推进阶段，且无法安全补充后续阶段。请先审阅故事块目标或手动结束当前块。', { title: '故事块需要审阅' })
    return null
  }
  if (!await ensureAiContextReady(actionName)) return null

  block = await createStoryBlockWithAI(actionName)
  if (block && isStoryBlockReviewRequired(block)) return null
  return block
}

function isStoryBlockReviewRequired(block) {
  return Boolean(block?.lockState?.requiresReview)
}

async function settleOpenStageContinuationBeforeBeatPlan(block = {}, actionName = '小纲生成') {
  if (!block?.id || !projectId.value) return block
  const stage = findNextEditableStage(block)
  const stageId = storyBlockStageId(stage)
  if (!stageId) return block
  const diagnostics = buildStageContinuationDiagnostics({
    currentStageId: stageId,
    previousOpenStageId: stageId,
    reviewHistory: block.reviewHistory || block.review_history || []
  })
  if (!diagnostics.requiresSettlementBeforeNextBeatPlan) return block

  const snapshot = buildBlockStageSnapshot(block, stage, {
    capturedAt: Date.now(),
    settlementGuard: true
  })
  const settlementContext = {
    chapterNum: diagnostics.lastOpenChapterNum || Math.max(1, Number(chapterNum.value || 1) - 1),
    stageContinuationDepth: diagnostics.stageContinuationDepth,
    previousOpenStageId: diagnostics.previousOpenStageId,
    blockStageSnapshot: snapshot,
    storyBlock: block,
    finalizedSummary: buildStageSettlementSummary(block),
    previousChapterEnding: previousChapterEnding.value || ''
  }
  const settlementReview = enforceStageContinuationSettlement({
    decision: 'continue_current_block',
    completedStageIds: [],
    stageContinues: true,
    stageContinueReason: block.nextStageSuggestion || '同一故事块阶段已连续跨章继续，需要在生成下一章小纲前先结算。',
    reason: block.nextStageSuggestion || '同一故事块阶段已连续跨章继续，需要在生成下一章小纲前先结算。',
    remainingStages: [],
    carryOverToNextChapter: block.carryOverToNextChapter || [],
    closedBy: 'stage_continuation_guard'
  }, settlementContext)

  if (settlementReview.requiresReview || settlementReview.settlementDecision === 'blocked_for_manual_review') {
    message.warning('同一故事块阶段连续挂起过久，需要人工复核后再生成小纲。', { title: '故事块阶段需复核' })
    return {
      ...block,
      lockState: {
        ...(block.lockState || {}),
        requiresReview: true,
        reviewReason: 'stage_continuation_guard_blocked_for_manual_review'
      }
    }
  }

  await storyBlockStore.saveBlockReview(projectId.value, block.id, {
    chapterNum: settlementContext.chapterNum,
    decision: settlementReview.decision,
    review: {
      ...settlementReview,
      label: STORY_BLOCK_REVIEW_DECISION_LABELS[settlementReview.decision] || settlementReview.decision,
      blockStageSnapshot: snapshot,
      finalizedSummary: settlementContext.finalizedSummary,
      closedBy: settlementReview.closedBy || 'stage_continuation_guard'
    }
  })

  let reviewedBlock = await loadStoryBlockAfterReview(block.id, projectId.value) || block
  if (settlementReview.decision === 'adjust_remaining_stages') {
    const mergedStagePlan = mergeForwardStagePlan(reviewedBlock, settlementReview, snapshot)
    await storyBlockStore.updateRemainingStages(projectId.value, block.id, {
      stagePlan: extractEditableFutureStageUpdates(reviewedBlock, mergedStagePlan, settlementReview, snapshot),
      stagePlanPatchMode: 'editable_future_only',
      nextStageSuggestion: deriveNextStageSuggestion(reviewedBlock, settlementReview, snapshot) || settlementReview.nextStageSuggestion || reviewedBlock.nextStageSuggestion || '',
      unresolvedQuestions: settlementReview.unresolvedQuestions?.length ? settlementReview.unresolvedQuestions : (reviewedBlock.unresolvedQuestions || []),
      dontAdvanceYet: reviewedBlock.dontAdvanceYet || [],
      carryOverToNextChapter: settlementReview.carryOverToNextChapter || reviewedBlock.carryOverToNextChapter || [],
      capacityAssessment: reviewedBlock.capacityAssessment || 'normal'
    })
    reviewedBlock = await loadStoryBlockAfterReview(block.id, projectId.value) || reviewedBlock
  }

  message.info('已在生成小纲前结算连续开放的故事块阶段，后续从新阶段承接。', { title: '故事块阶段已结算' })
  return reviewedBlock
}

function buildStageSettlementSummary(block = {}) {
  const currentNum = Number(chapterNum.value || 0)
  const recentSummaries = (writerStore.chapters || [])
    .filter(chapter => Number(chapter.chapterNum || chapter.chapter_num || 0) < currentNum)
    .slice(-3)
    .map(chapter => `第 ${chapter.chapterNum || chapter.chapter_num} 章：${chapter.summary || ''}`)
  const recentReviewReasons = (block.reviewHistory || block.review_history || [])
    .slice(-4)
    .map(item => item.stageContinueReason || item.reason || item.completionEvidence || '')
    .filter(Boolean)
  return [...recentSummaries, ...recentReviewReasons, previousChapterEnding.value || ''].filter(Boolean).join('\n')
}

async function createStoryBlockWithAI(actionName = '故事块规划', options = {}) {
  const planningContext = buildStoryBlockPlanningContext(options)
  try {
    const plannedPayload = await storyBlockStore.planStoryBlockWithAI(projectId.value, planningContext)
    const block = await storyBlockStore.createStoryBlock(projectId.value, plannedPayload)
    message.success('已根据当前上下文规划故事块。后续只能更新未执行、未引用的剩余阶段。', { title: '故事块已规划' })
    return block
  } catch (e) {
    const fallbackPayload = {
      ...buildDefaultStoryBlockPayload(),
      lockState: {
        aiPlanningFallback: true,
        requiresReview: true,
        fallbackReason: e.message,
        actionName,
        planningDiagnostics: e.diagnostics || storyBlockStore.lastPlanningDiagnostics || null
      }
    }
    const block = await storyBlockStore.createStoryBlock(projectId.value, fallbackPayload)
    message.warning(`故事块 AI 规划失败，已创建人工占位故事块，请先审阅目标和阶段后再继续：${e.message}`, { title: '请审阅故事块占位' })
    return block
  }
}

function buildDefaultStoryBlockPayload() {
  const context = buildBaseContext()
  const volume = currentVolume.value || context.currentVolume || {}
  const volumeTitle = volume.title || context.volumeStage?.title || '当前卷'
  const goal = context.volumeStage?.coreGoal || volume.coreGoal || volume.goal || context.chapterGoal?.goal || '推进当前卷的下一段连续剧情'
  const previousEnding = previousChapterEnding.value || '从当前章节状态自然承接。'
  return {
    volumeId: volume.id || null,
    status: 'active',
    title: `${volumeTitle} · 第 ${chapterNum.value} 章起`,
    goal,
    storyFunction: '承接与推进',
    entryState: previousEnding,
    exitTarget: '完成一个读者能复述的阶段性变化，并自然交给后续章节。',
    mainPressure: context.volumeStage?.mainConflict || volume.mainConflict || '当前目标仍有阻力。',
    keyCharacters: context.volumeStage?.keyCharacters || [],
    stagePlan: [
      {
        id: `stage-${chapterNum.value}-1`,
        purpose: '承接当前局面并建立本故事块任务',
        sceneOrAction: '承接上一章结尾，让人物在具体场景中行动并面对阻力。',
        choice: '人物在压力下做出一个有代价的选择。',
        costOrConsequence: '留下关系、线索、危险、地点或目标上的可追踪变化。',
        status: 'planned'
      },
      {
        id: `stage-${chapterNum.value}-2`,
        purpose: '让核心压力升级并迫使人物改变策略',
        sceneOrAction: '围绕故事块目标推进下一次可写行动，暴露新的阻力或线索。',
        choice: '人物在保守与冒险之间做出选择。',
        costOrConsequence: '让目标、关系或处境发生不可忽略的变化。',
        status: 'planned'
      },
      {
        id: `stage-${chapterNum.value}-3`,
        purpose: '把本故事块推向自然完成、失败或明确转向',
        sceneOrAction: '收束当前任务的主要压力，并留下下一段剧情可承接的出口。',
        choice: '人物决定承担代价继续推进，或被迫转向新任务。',
        costOrConsequence: '形成清晰的任务结果、失败后果或新态势。',
        status: 'planned'
      }
    ],
    nextStageSuggestion: '先生成当前章小纲，完成当前阶段的行动、选择和代价。',
    unresolvedQuestions: context.volumeStage?.unresolvedItems || [],
    dontAdvanceYet: [],
    capacityAssessment: 'normal',
    chapterRefs: []
  }
}

function buildStoryBlockPlanningContext(options = {}) {
  const base = buildBaseContext()
  const acceptedFacts = (novelStore.canonFacts || [])
    .filter(fact => (fact.status || 'accepted') === 'accepted')
    .slice(-30)
  const recentSummaries = (writerStore.chapters || [])
    .filter(chapter => Number(chapter.chapterNum || chapter.chapter_num || 0) < Number(chapterNum.value))
    .slice(-5)
    .map(chapter => ({
      chapterNum: chapter.chapterNum || chapter.chapter_num,
      title: chapter.title || '',
      summary: chapter.summary || ''
    }))

  return {
    ...base,
    chapterNum: chapterNum.value,
    seed: base.seed || buildSeedContext(getSelectedSeed()),
    openingHook: base.openingHook || base.seed?.openingHook || buildSeedContext(getSelectedSeed())?.openingHook || '',
    openingAnchor: base.openingAnchor || base.seed?.openingHook || buildSeedContext(getSelectedSeed())?.openingHook || '',
    bible: novelStore.bible,
    currentVolume: currentVolume.value || base.currentVolume || base.volumeStage || {},
    volumeStage: base.volumeStage || currentVolume.value || {},
    volumePlanning: volumeStore.volumes || [],
    settingLibrary: {
      entities: (settingStore.entities || []).filter(entity => (entity.status || 'active') === 'active').slice(-40),
      relations: (settingStore.relations || []).slice(-40)
    },
    stateLedger: {
      canonFacts: acceptedFacts,
      plotThreads: (novelStore.plotThreads || []).filter(thread => ['planted', 'developing'].includes(thread.status || ''))
    },
    recentFacts: acceptedFacts,
    recentSummaries,
    recentChapterEndings: recentChapterEndings.value,
    previousChapterEnding: previousChapterEnding.value || '',
    chaseLoopDiagnostics: buildChaseLoopDiagnosticsForBeatPlan(),
    newBlockSeed: options.seed || null
  }
}

const CHASE_LOOP_DIAGNOSTIC_TERMS = ['追兵', '搜查', '撤离', '潜入', '地道', '追捕', '封锁', '逃', '躲']
const NON_CHASE_DIAGNOSTIC_TERMS = ['对峙', '谈判', '质问', '代价', '包扎', '休整', '设局', '布局', '核验', '验证', '规矩', '商盟']

function buildChaseLoopDiagnosticsForBeatPlan() {
  const recent = (writerStore.chapters || [])
    .filter(chapter => Number(chapter.chapterNum || chapter.chapter_num || 0) < Number(chapterNum.value))
    .slice(-3)
    .map(chapter => {
      const text = [
        chapter.title,
        chapter.summary,
        chapter.finalSummary,
        chapter.final_summary,
        chapter.ending,
        chapter.chapterEnding
      ].filter(Boolean).join(' ')
      const chaseCount = countDiagnosticTerms(text, CHASE_LOOP_DIAGNOSTIC_TERMS)
      const nonChaseCount = countDiagnosticTerms(text, NON_CHASE_DIAGNOSTIC_TERMS)
      return {
        chapterNum: chapter.chapterNum || chapter.chapter_num,
        chaseDominant: chaseCount > 0 && chaseCount >= nonChaseCount,
        chaseCount,
        nonChaseCount
      }
    })
  let consecutiveChaseDominant = 0
  for (let index = recent.length - 1; index >= 0; index -= 1) {
    if (!recent[index].chaseDominant) break
    consecutiveChaseDominant += 1
  }
  return {
    consecutiveChaseDominant,
    recentChapters: recent,
    preferredSceneFunctions: consecutiveChaseDominant >= 3
      ? ['active_setup', 'relationship_confrontation', 'consequence_scene', 'information_verification']
      : ['relationship_confrontation', 'consequence_scene', 'information_verification'],
    reason: consecutiveChaseDominant >= 3
      ? '最近三章疑似由追逃、搜查或撤离主导，下一章需要换成主动布局、关系对峙、代价后果或信息验证。'
      : ''
  }
}

function countDiagnosticTerms(text = '', terms = []) {
  const source = String(text || '')
  return terms.reduce((sum, term) => sum + source.split(term).length - 1, 0)
}

function captureCurrentBlockStageSnapshot(block = activeStoryBlock.value) {
  if (!block) return null
  const stage = findNextEditableStage(block)
  if (!stage) throw new Error('故事块没有可用于当前章的小纲阶段，请先完成当前故事块或开启新故事块。')
  return buildBlockStageSnapshot(block, stage || {}, { capturedAt: Date.now() })
}

async function ensureBeatPlan(force = false, options = {}) {
  const result = await runEnsureBeatPlanCommand({
    projectId: projectId.value,
    chapterNum: chapterNum.value,
    existingPlan: beatPlanText.value,
    force,
    beatPlanStageSnapshot: beatPlanStageSnapshot.value,
    options,
    callbacks: {
      ensureAiContextReady,
      ensureCurrentChapterEditable,
      ensurePreviousChapterFinalized,
      ensureNoPendingSettingChanges,
      ensureNoPendingStoryMemory,
      ensureCorrectionTasksAllowGeneration,
      ensureStoryBlockReady,
      captureCurrentBlockStageSnapshot,
      setBeatPlanStageSnapshot: (snapshot) => {
        beatPlanStageSnapshot.value = snapshot
      },
      buildBaseContext,
      buildChaseLoopDiagnosticsForBeatPlan,
      generateChapterBeatPlan: writerStore.generateChapterBeatPlan,
      setBeatPlanText: (text) => {
        beatPlanText.value = text
      },
      saveChapterBeatPlan: writerStore.saveChapterBeatPlan,
      buildBeatPlanStoryBlockMetadata,
      setBeatPlanSavedText: (text) => {
        beatPlanSavedText.value = text
      }
    }
  })
  if (result.code === 'generatedPlan' && writerStore.beatPlanQualityNotice?.source === 'local_safety_rebuild') {
    message.warning('AI 小纲质量不足，已生成安全小纲，请审阅后再生成正文。', { duration: 6000 })
  }
  return result.plan || ''
}

function buildBeatPlanStoryBlockMetadata() {
  const snapshot = beatPlanStageSnapshot.value || captureCurrentBlockStageSnapshot()
  beatPlanStageSnapshot.value = snapshot
  const source = beatPlanSourceValue.value || null
  return {
    storyBlockId: snapshot?.storyBlockId || activeStoryBlock.value?.id || null,
    blockStageId: snapshot?.stageId || null,
    blockStageSnapshot: snapshot || null,
    beatPlanSource: source,
    derivedFromStoryBlock: source === 'derived_from_story_block' || Boolean(writerStore.beatPlanDiagnostics?.derivedFromStoryBlock),
    derivedReason: writerStore.beatPlanDiagnostics?.derivedReason || writerStore.beatPlanQualityNotice?.derivedReason || ''
  }
}

async function handleUpdateRemainingStages() {
  const block = activeStoryBlock.value
  if (!block?.id) {
    await ensureStoryBlockReady('更新后续阶段')
    return
  }
  try {
    await storyBlockStore.updateRemainingStages(projectId.value, block.id, {
      stagePlan: block.stagePlan || [],
      nextStageSuggestion: block.nextStageSuggestion || '',
      unresolvedQuestions: block.unresolvedQuestions || [],
      dontAdvanceYet: block.dontAdvanceYet || [],
      capacityAssessment: block.capacityAssessment || 'normal'
    })
    message.success('后续阶段已刷新；已引用或已完成阶段保持锁定。')
  } catch (e) {
    message.error('更新后续阶段失败：' + e.message)
  }
}

async function handleConfirmStoryBlockReview() {
  const block = activeStoryBlock.value
  if (!block?.id) return
  try {
    await storyBlockStore.confirmStoryBlockReview(projectId.value, block.id, {
      reason: '用户已审阅 AI 失败后的人工占位故事块'
    })
    message.success('故事块已确认，可以继续生成小纲。')
  } catch (e) {
    message.error('确认故事块失败：' + e.message)
  }
}

function handleSplitUnfinalizedContent() {
  if (currentChapterFinalized.value) {
    message.warning('本章已定稿，只能在后续章节承接，不能拆分已定稿正文。')
    return
  }
  beatPlanIntent.value = 'single'
  showBeatPlanModal.value = true
  message.info('请在小纲中只保留当前章自然阶段，把未写内容顺延到下一章；不要机械按长度切开正文。', { title: '拆分未定稿内容' })
}

async function handleCloseStoryBlock() {
  const block = activeStoryBlock.value
  if (!block?.id) return
  try {
    await storyBlockStore.closeBlock(projectId.value, block.id, {
      reason: '用户提前结束当前块，后续由新故事块承接。',
      closeReason: 'user_manual_close',
      completionEvidence: '用户手动确认当前剧情任务提前结束，后续由新故事块承接。',
      singleChapterBlockReason: buildManualSingleChapterBlockReason(block),
      closedBy: 'user_manual',
      chapterRefs: block.chapterRefs || []
    })
    message.success('当前故事块已提前结束，可开启新故事块承接。')
  } catch (e) {
    message.error('提前结束当前块失败：' + e.message)
  }
}

async function handleOpenNewStoryBlock() {
  try {
    if (activeStoryBlock.value?.id) {
      await storyBlockStore.closeBlock(projectId.value, activeStoryBlock.value.id, {
        reason: '开启新故事块前关闭当前块。',
        closeReason: 'user_manual_close',
        completionEvidence: '用户手动确认当前故事块提前结束，并开启新故事块承接。',
        singleChapterBlockReason: buildManualSingleChapterBlockReason(activeStoryBlock.value),
        closedBy: 'user_manual',
        chapterRefs: activeStoryBlock.value.chapterRefs || []
      })
    }
    await createStoryBlockWithAI('开启新故事块')
    message.success('已开启新故事块')
  } catch (e) {
    message.error('开启新故事块失败：' + e.message)
  }
}

async function saveCurrentBeatPlan(showMessage = true) {
  return runSaveBeatPlanCommand({
    showMessage,
    getBeatPlanText: () => beatPlanText.value,
    getBeatPlanStageSnapshot: () => beatPlanStageSnapshot.value,
    getProjectId: () => projectId.value,
    getChapterNum: () => chapterNum.value,
    ensureCurrentChapterEditable,
    ensureStoryBlockReady,
    captureCurrentBlockStageSnapshot,
    setBeatPlanStageSnapshot: (snapshot) => {
      beatPlanStageSnapshot.value = snapshot
    },
    saveChapterBeatPlan: (...args) => writerStore.saveChapterBeatPlan(...args),
    buildBeatPlanStoryBlockMetadata,
    setBeatPlanText: (content) => {
      beatPlanText.value = content
    },
    setBeatPlanSavedText: (content) => {
      beatPlanSavedText.value = content
    },
    warning: message.warning,
    success: message.success,
    error: message.error,
  })
}

async function handlePlanBeats() {
  try {
    beatPlanIntent.value = 'single'
    const plan = await ensureBeatPlan(false)
    if (!plan) return
    showBeatPlanModal.value = true
  } catch (e) {
    message.error('小纲生成失败：' + e.message)
  }
}

async function handleRefreshBeatPlan() {
  try {
    const plan = await ensureBeatPlan(true, { persist: false })
    if (!plan) return
    showBeatPlanModal.value = true
    message.success('已重新生成小纲草稿，保存或生成正文后才会覆盖已保存小纲')
  } catch (e) {
    message.error('小纲重新生成失败：' + e.message)
  }
}

async function handleGenerate() {
  beatPlanIntent.value = 'single'
  const existingPlan = beatPlanText.value.trim()
  if (existingPlan) {
    await generateChapterFromPlan(existingPlan)
    return
  }
  try {
    const plan = await ensureBeatPlan(false)
    if (!plan) return
    showBeatPlanModal.value = true
    message.success('请先审阅本章小纲，确认后再生成正文')
  } catch (e) {
    message.error('小纲准备失败：' + e.message)
  }
}

async function generateChapterFromPlan(confirmedPlan) {
  if (!await ensureAiContextReady('正文生成')) return
  if (!ensureCurrentChapterEditable('正文生成')) return
  if (!await ensurePreviousChapterFinalized('正文生成')) return
  if (!await ensureNoPendingSettingChanges('正文生成')) return
  if (!await ensureNoPendingStoryMemory('正文生成')) return
  if (!await ensureCorrectionTasksAllowGeneration('正文生成')) return
  if (!beatPlanStageSnapshot.value) {
    const block = await ensureStoryBlockReady('正文生成')
    if (!block) return
    beatPlanStageSnapshot.value = captureCurrentBlockStageSnapshot(block)
    await writerStore.saveChapterBeatPlan(projectId.value, chapterNum.value, confirmedPlan, buildBeatPlanStoryBlockMetadata())
    beatPlanSavedText.value = confirmedPlan
  }
  try {
    activeWriterAction.value = 'chapter'
    streamingContent.value = true
    editorContent.value = ''
    const version = await writerStore.generateChapter(
      projectId.value,
      chapterNum.value,
      buildConfirmedChapterContext(confirmedPlan),
      null,
      fullContent => {
        editorContent.value = fullContent
      }
    )
    writerStore.currentVersion = version
    loadedEditorSnapshot.value = version.content || ''
    notifyWordCountIfNeeded(version.content, buildBaseContext().wordTarget)
    message.success('已按确认小纲生成章节')
  } catch (e) {
    if (e.code === 'BEAT_PLAN_LOCAL_SAFETY_REBUILD' || writerStore.beatPlanQualityNotice?.source === 'local_safety_rebuild') {
      const notice = writerStore.beatPlanQualityNotice
      if (notice?.content) {
        beatPlanText.value = notice.content
        showBeatPlanModal.value = true
      }
      message.warning('AI 小纲质量不足，已生成安全小纲，请审阅后再生成正文。', { duration: 6000 })
      return
    }
    if (e.code === 'draft_save_failed') {
      message.error('正文候选保存失败：' + e.message)
      return
    }
    message.error('按小纲生成失败：' + e.message)
  } finally {
    streamingContent.value = false
    if (activeWriterAction.value === 'chapter') activeWriterAction.value = ''
  }
}

function buildAuditStoryContext() {
  return {
    beatPlan: beatPlanSavedText.value || beatPlanText.value || writerStore.beatPlanRecord?.content || '',
    blockStageSnapshot: beatPlanStageSnapshot.value || writerStore.beatPlanRecord?.blockStageSnapshot || null,
    previousChapterEnding: previousChapterEnding.value || ''
  }
}

async function generateMultiVariantsFromPlan(confirmedPlan) {
  if (!await ensureAiContextReady('多候选生成')) return
  if (!ensureCurrentChapterEditable('多候选生成')) return
  if (!await ensurePreviousChapterFinalized('多候选生成')) return
  if (!await ensureNoPendingSettingChanges('多候选生成')) return
  if (!await ensureNoPendingStoryMemory('多候选生成')) return
  if (!await ensureCorrectionTasksAllowGeneration('多候选生成')) return
  const baselineDraft = editorContent.value?.trim()
  const hasBaselineDraft = !!baselineDraft
  const variantLabels = hasBaselineDraft
    ? ['强冲突版', '意外转向版']
    : ['稳妥推进版', '强冲突版', '意外转向版']
  try {
    activeWriterAction.value = 'multi'
    const versions = await writerStore.generateMultiVariants(
      projectId.value,
      chapterNum.value,
      {
        ...buildConfirmedChapterContext(confirmedPlan),
        variantLabels,
        baselineDraft: hasBaselineDraft ? baselineDraft.slice(0, 5000) : ''
      }
    )
    if (!hasBaselineDraft && versions.length > 0) {
      writerStore.currentVersion = versions[0]
      editorContent.value = versions[0].content
      loadedEditorSnapshot.value = versions[0].content || ''
    }
    notifyGeneratedVersionsWordCount(versions, buildBaseContext().wordTarget)
    message.success(hasBaselineDraft
      ? `已基于当前正文补充 ${versions.length} 个替代候选版本`
      : `基于小纲生成了 ${versions.length} 个候选版本，已默认载入第一版`
    )
  } catch (e) {
    message.error('多候选版本生成失败：' + e.message)
  } finally {
    if (activeWriterAction.value === 'multi') activeWriterAction.value = ''
  }
}

async function handleGenerateFromBeatPlan() {
  return runGenerateFromBeatPlanCommand({
    getBeatPlanIntent: () => beatPlanIntent.value,
    getBeatPlanText: () => beatPlanText.value,
    ensureCurrentChapterEditable,
    warning: message.warning,
    saveCurrentBeatPlan,
    setShowBeatPlanModal: (value) => {
      showBeatPlanModal.value = value
    },
    generateMultiVariantsFromPlan,
    openCompareWithPlan,
    generateChapterFromPlan,
  })
}

async function handleMultiVariant() {
  beatPlanIntent.value = 'multi'
  const existingPlan = beatPlanText.value.trim()
  if (existingPlan) {
    await generateMultiVariantsFromPlan(existingPlan)
    return
  }
  try {
    const plan = await ensureBeatPlan(false)
    if (!plan) return
    showBeatPlanModal.value = true
    message.success('请先审阅本章小纲，确认后再生成多候选版本')
  } catch (e) {
    message.error('小纲准备失败：' + e.message)
  }
}

async function handleContinue() {
  if (!await ensureAiContextReady('续写')) return
  if (!ensureCurrentChapterEditable('续写')) return
  if (!await ensurePreviousChapterFinalized('续写')) return
  if (!await ensureNoPendingSettingChanges('续写')) return
  if (!await ensureNoPendingStoryMemory('续写')) return
  if (!await ensureCorrectionTasksAllowGeneration('续写')) return
  try {
    activeWriterAction.value = 'continue'
    const result = await writerStore.continueWriting(editorContent.value, '自然续写，推进情节', null, buildPlanningContext())
    const content = typeof result === 'string'
      ? result
      : result?.content || result?.choices?.[0]?.message?.content || ''
    editorContent.value = editorContent.value + '\n\n' + content
    message.success('续写完成')
  } catch (e) {
    message.error('续写失败：' + e.message)
  } finally {
    if (activeWriterAction.value === 'continue') activeWriterAction.value = ''
  }
}

async function handleExpand() {
  if (!selectedText.value) {
    message.warning('请先选中要扩写的文字')
    return
  }
  if (!await ensureAiContextReady('扩写')) return
  if (!ensureCurrentChapterEditable('扩写')) return
  if (!await ensurePreviousChapterFinalized('扩写')) return
  if (!await ensureNoPendingSettingChanges('扩写')) return
  if (!await ensureNoPendingStoryMemory('扩写')) return
  if (!await ensureCorrectionTasksAllowGeneration('扩写')) return
  try {
    activeWriterAction.value = 'expand'
    const result = await writerStore.expandText(selectedText.value, buildPlanningContext())
    editorContent.value = editorContent.value.replace(selectedText.value, result)
    message.success('扩写完成')
  } catch (e) {
    message.error('扩写失败：' + e.message)
  } finally {
    if (activeWriterAction.value === 'expand') activeWriterAction.value = ''
  }
}

async function handleCompress() {
  if (!selectedText.value) {
    message.warning('请先选中要压缩的文字')
    return
  }
  if (!ensureCurrentChapterEditable('压缩')) return
  if (!await ensureCorrectionTasksAllowGeneration('压缩')) return
  try {
    activeWriterAction.value = 'compress'
    const result = await writerStore.compressText(selectedText.value)
    editorContent.value = editorContent.value.replace(selectedText.value, result)
    message.success('压缩完成')
  } catch (e) {
    message.error('压缩失败：' + e.message)
  } finally {
    if (activeWriterAction.value === 'compress') activeWriterAction.value = ''
  }
}

async function handleRewrite(mode) {
  if (!selectedText.value) {
    message.warning('请先选中要改写的文字')
    return
  }
  if (!await ensureAiContextReady('选区改写')) return
  if (!ensureCurrentChapterEditable('选区改写')) return
  if (!await ensurePreviousChapterFinalized('选区改写')) return
  if (!await ensureNoPendingSettingChanges('选区改写')) return
  if (!await ensureNoPendingStoryMemory('选区改写')) return
  if (!await ensureCorrectionTasksAllowGeneration('选区改写')) return
  try {
    activeWriterAction.value = 'rewrite'
    const baseContext = buildBaseContext()
    const result = await writerStore.rewriteSelection(selectedText.value, mode, {
      styleBible: novelStore.bible?.styleBible,
      styleStandardBrief: baseContext.styleStandardBrief,
      characters: novelStore.characters,
      settingLibrary: baseContext.settingLibrary,
      recentFacts: baseContext.recentFacts,
      volumeStage: baseContext.volumeStage,
      activeCorrectionTasks: baseContext.activeCorrectionTasks
    })
    editorContent.value = editorContent.value.replace(selectedText.value, result)
    selectedText.value = result
    message.success('改写完成')
  } catch (e) {
    message.error('改写失败：' + e.message)
  } finally {
    if (activeWriterAction.value === 'rewrite') activeWriterAction.value = ''
  }
}

async function openCompareWithPlan(confirmedPlan) {
  if (!aiContextReady.value) {
    message.warning(aiContextStatusText.value || '创作上下文尚未就绪')
    return
  }
  if (!ensureCurrentChapterEditable('多模型对比')) return
  if (!await ensurePreviousChapterFinalized('多模型对比')) return
  if (!await ensureNoPendingStoryMemory('多模型对比')) return
  if (!await ensureCorrectionTasksAllowGeneration('多模型对比')) return
  if (pendingSettingChanges.value.length > 0) {
    message.warning(
      `设定库还有 ${pendingSettingChanges.value.length} 条待确认变更。请先确认或拒绝后再开始多模型对比。`,
      { title: '请先确认设定变更' }
    )
    return
  }
  compareBeatPlan.value = confirmedPlan
  compareContext.value = buildConfirmedChapterContext(confirmedPlan)
  showCompareModal.value = true
}

async function handleCompare() {
  beatPlanIntent.value = 'compare'
  const existingPlan = beatPlanText.value.trim()
  if (existingPlan) {
    await openCompareWithPlan(existingPlan)
    return
  }
  try {
    const plan = await ensureBeatPlan(false)
    if (!plan) return
    showBeatPlanModal.value = true
    message.success('请先审阅本章小纲，确认后再开始多模型对比')
  } catch (e) {
    message.error('小纲准备失败：' + e.message)
  }
}

function handleOpenFusion() {
  showFusionPanel.value = true
}

function handleOpenDiff() {
  if (!diffBaseVersion.value) {
    message.warning('请先生成或输入一版正文作为基准版本')
    return
  }
  if (compareStore.comparisonVersions.length < 1) {
    message.warning('请先加入至少一个候选版本到对比池')
    return
  }
  if (diffVersions.value.length < 2) {
    message.warning('当前基准版本与对比版本相同，请再加入另一个候选，或先加载/生成一版原始正文作为基准')
    return
  }
  showDiffModal.value = true
}

function handleToggleVersionCompare(version) {
  compareStore.toggleVersion(version)
  const inPool = compareStore.comparisonVersions.some(item => item.id === version.id)
  message.success(inPool ? '已加入对比池' : '已从对比池移除')
}

async function handleStyleAnalysis() {
  if (!editorContent.value) {
    message.warning('请先生成或输入正文')
    return
  }
  showStyleModal.value = true
  try {
    await memoryStore.analyzeStyle(projectId.value, editorContent.value, chapterNum.value)
  } catch (e) {
    message.error('风格分析失败：' + e.message)
  }
}

async function handlePacingAnalysis() {
  if (!editorContent.value) {
    message.warning('请先生成或输入正文')
    return
  }
  showPacingModal.value = true
  try {
    await memoryStore.analyzePacing(projectId.value, editorContent.value, chapterNum.value)
  } catch (e) {
    message.error('节奏分析失败：' + e.message)
  }
}

async function handleAudit() {
  if (!editorContent.value) {
    message.warning('请先生成或输入正文')
    return
  }
  pendingFinalizeVersion.value = null
  memoryStore.lastAuditResult = null
  readonlyAuditResult.value = null
  auditIssueActions.value = {}
  auditRunning.value = true
  showAuditModal.value = true
  try {
    const report = await memoryStore.auditChapter(projectId.value, editorContent.value, chapterNum.value, buildAuditStoryContext())
    if (currentChapterFinalized.value) {
      readonlyAuditResult.value = report
      memoryStore.lastAuditResult = null
    }
  } catch (e) {
    message.error('审稿失败：' + e.message)
  } finally {
    auditRunning.value = false
  }
}

async function handleGenerateAuditRevisionVersion() {
  const report = memoryStore.lastAuditResult
  if (!report?.issues?.length) {
    message.warning('当前本章审稿报告没有可用于修订的问题项')
    return
  }
  if (!editorContent.value?.trim()) {
    message.warning('当前编辑器没有可修订的正文')
    return
  }
  if (currentChapterFinalized.value) {
    message.warning(
      '本章已经定稿，不能再生成正文修订版本。请把问题留给分卷/全局软纠偏，在后续章节中自然修复。',
      { title: '已定稿章节不做硬纠偏' }
    )
    return
  }
  if (!ensureCurrentChapterEditable('局部修订版本生成')) return
  try {
    auditRevisionGenerating.value = true
    const result = await writerStore.generateLocalCorrectionPatchCandidate(
      projectId.value,
      chapterNum.value,
      report.issues,
      editorContent.value
    )
    const version = result.version
    compareStore.clearComparison()
    compareStore.toggleVersion(version)
    pendingFinalizeVersion.value = null
    showAuditModal.value = false
    showDiffModal.value = true
    if (result.mode === 'draft_fallback') {
      message.warning(
        '局部补丁未能稳定命中正文，已生成审稿修订候选兜底版，并打开差异对比。请重点检查改动范围。',
        { title: '已生成兜底修订候选' }
      )
    } else {
      message.success(`已生成局部修订候选版本：应用 ${result.applied.length} 处，跳过 ${result.skipped.length} 处，并打开差异对比`)
    }
  } catch (e) {
    message.error('生成局部修订版本失败：' + e.message)
  } finally {
    auditRevisionGenerating.value = false
  }
}

function loadVersion(version) {
  if (hasUnsavedVersionEdits.value) {
    pendingVersionToLoad.value = version
    showUnsavedVersionModal.value = true
    return
  }
  applyVersionToEditor(version)
}

function applyVersionToEditor(version) {
  writerStore.currentVersion = version
  editorContent.value = version.content
  loadedEditorSnapshot.value = version.content || ''
  pendingVersionToLoad.value = null
}

async function saveEditorAsVersion() {
  if (!ensureCurrentChapterEditable('另存为版本')) return null
  const content = editorContent.value.trim()
  if (!content) {
    message.warning('当前编辑器没有可保存的正文')
    return null
  }
  const chapter = writerStore.currentChapter || await writerStore.getOrCreateChapter(projectId.value, chapterNum.value)
  const sourceTitle = writerStore.currentVersion?.title || `第 ${chapterNum.value} 章`
  const { version } = await runCreateVersionCommand({
    projectId: projectId.value,
    chapter,
    chapterNum: chapterNum.value,
    title: `${sourceTitle} - 用户草稿`,
    content,
    versionType: 'user_draft',
    promptBrief: writerStore.currentVersion?.id
      ? `基于版本「${sourceTitle}」手动编辑后另存`
      : '手动编辑后另存',
    createVersion: writerStore.createVersion
  })
  writerStore.currentVersion = version
  loadedEditorSnapshot.value = content
  await writerStore.saveTempDraft(projectId.value, chapterNum.value, content)
  message.success('已另存为用户草稿版本')
  return version
}

async function saveAndLoadPendingVersion() {
  const saved = await saveEditorAsVersion()
  if (!saved) return
  const target = pendingVersionToLoad.value
  showUnsavedVersionModal.value = false
  if (target) applyVersionToEditor(target)
}

function discardAndLoadPendingVersion() {
  const target = pendingVersionToLoad.value
  showUnsavedVersionModal.value = false
  if (target) applyVersionToEditor(target)
}

function cancelPendingVersionLoad() {
  pendingVersionToLoad.value = null
  showUnsavedVersionModal.value = false
}

async function handleFinalize(version) {
  if (finalizationActionBusy.value) {
    message.warning('定稿正在审稿或入库处理中，请等待当前处理完成后再操作。', { title: '定稿处理中' })
    return
  }
  if (finalizedVersionId.value) {
    message.warning('本章已经定稿。为避免重复提取记忆和覆盖最终版本，请先走纠偏/重修流程。')
    return
  }
  if (!await ensureCorrectionTasksAllowGeneration('定稿')) return
  if (!version?.content?.trim()) {
    message.warning('当前版本正文为空，不能定稿')
    return
  }
  if (!await ensureChapterAboveHardWordMinBeforeFinalize(version)) return
  pendingFinalizeVersion.value = version
  memoryStore.lastAuditResult = null
  finalizeAuditInFlight.value = true
  auditRunning.value = true
  showAuditModal.value = true
  try {
    const report = await memoryStore.auditChapter(projectId.value, version.content, chapterNum.value, buildAuditStoryContext())
    const hardIssues = (report?.issues || []).filter(issue => ['critical', 'major'].includes(issue.severity))
    if (hardIssues.length) {
      message.warning(
        `定稿前审稿发现 ${hardIssues.length} 个严重/主要问题，请先修订或确认仍然定稿。`,
        { title: '定稿前发现问题' }
      )
      return
    }
    const softIssues = (report?.issues || []).filter(issue => ['minor', 'suggestion'].includes(issue.severity))
    if (softIssues.length) {
      dialog.warning({
        title: '发现轻微审稿建议',
        content: `本章审稿发现 ${softIssues.length} 个轻微/建议类问题。可以继续定稿，也可以返回修改。`,
        positiveText: '继续定稿',
        negativeText: '返回修改',
        maskClosable: false,
        closeOnEsc: false,
        onPositiveClick: async () => {
          await performFinalize(version)
        },
        onNegativeClick: () => {
          pendingFinalizeVersion.value = null
        }
      })
      return
    }
    await performFinalize(version)
  } catch (e) {
    pendingFinalizeVersion.value = null
    showAuditModal.value = false
    message.error('定稿前审稿失败：' + e.message)
  } finally {
    auditRunning.value = false
    finalizeAuditInFlight.value = false
  }
}

async function performFinalize(version) {
  if (!version || finalizedVersionId.value) return
  const finalizedProjectId = projectId.value
  const finalizedChapterNum = chapterNum.value
  const correctionTaskIds = extractCorrectionTaskIds(version)
  finalizeSubmitting.value = true
  memoryProcessing.value = true
  try {
    const result = await runFinalizeChapterCommand({
      projectId: finalizedProjectId,
      chapterNum: finalizedChapterNum,
      version,
      correctionTaskIds,
      beginFinalizationRun: beginChapterFinalizationRun,
      finalizeVersion: writerStore.finalizeVersion,
      finishLinkedCorrectionTasks,
      clearTempDraft: writerStore.clearTempDraft,
      processChapterFinalization: memoryStore.processChapterFinalization,
      loadContextData,
      performStoryBlockReviewAfterFinalize,
      rerouteOutlineAfterFinalization: novelStore.rerouteOutlineAfterFinalization,
      buildRerouteContext: buildFinalizationRerouteContext,
      markFinalizationFailure: markChapterFinalizationFailure,
      endFinalizationRun: endChapterFinalizationRun,
      saveDurableFinalizationMarker,
      upsertDurableFinalizationMarker,
      onVersionFinalized: () => {
        pendingFinalizeVersion.value = null
        showAuditModal.value = false
        message.success('已定稿，正在提取记忆和设定变更...')
      },
      onLinkedCorrectionTaskFailure: (e) => {
        console.warn('关联纠偏任务状态更新失败:', e.message)
      },
      onClearTempDraftFailure: (e) => {
        console.warn('临时草稿清理失败:', e.message)
      },
      onMemoryProcessed: (results) => {
        memoryResult.value = results
        showMemoryResult.value = true
      },
      onStoryBlockReviewFailure: (e) => {
        console.warn('定稿后故事块回看失败:', e.message)
        message.warning(`定稿后故事块回看失败，可稍后在故事块面板继续：${e.message}`, { title: '故事块回看未完成' })
      },
      onRerouteWarning: (e) => {
        console.warn('定稿后滚动规划刷新失败:', e.message)
        message.warning(`定稿后滚动规划刷新失败，可在章节管理页手动重新生成：${e.message}`, { title: '滚动规划未刷新' })
      },
      onPostFinalizeFailure: () => {
        finalizationMarkerVersion.value += 1
      }
    })

    if (result.ok) {
      message.success(`定稿后处理完成：提取 ${result.factCount || 0} 条记忆事实，生成 ${result.settingChangeCount || 0} 条待确认设定变更`)
    } else if (result.code === 'finalization_run_blocked') {
      message.warning('本章定稿或定稿后入库正在处理中，请不要重复点击。', { title: '定稿处理中' })
    } else if (result.chapterFinalized) {
      message.warning('定稿后处理失败，已保留阻断标记，避免下一章读取不完整上下文：' + (result.message || result.error?.message || '未知错误'))
    } else {
      message.error('定稿失败：' + (result.message || result.error?.message || '未知错误'))
    }
  } finally {
    finalizeSubmitting.value = false
    memoryProcessing.value = false
  }
}

async function performStoryBlockReviewAfterFinalize(results, version, finalizedChapterNum, finalizedProjectId = projectId.value) {
  let snapshot = beatPlanStageSnapshot.value || writerStore.beatPlanRecord?.blockStageSnapshot
  if (!snapshot?.storyBlockId || !snapshot?.stageId) {
    const savedBeatPlan = await writerStore.loadChapterBeatPlan(finalizedProjectId, finalizedChapterNum)
    snapshot = savedBeatPlan?.blockStageSnapshot || snapshot
  }
  const blockId = snapshot?.storyBlockId || writerStore.beatPlanRecord?.storyBlockId || activeStoryBlock.value?.id
  if (!blockId) throw new Error('Story block review requires saved storyBlockId from chapter beat plan')
  if (!snapshot?.stageId) throw new Error('Story block review requires blockStageSnapshot.stageId')

  const blocks = await storyBlockStore.loadBlocks(finalizedProjectId).catch(() => storyBlockStore.blocks || [])
  const liveBlock = blocks.find(block => block.id === blockId) || activeStoryBlock.value || {}
  const stageContinuationDiagnostics = buildStageContinuationDiagnostics({
    currentStageId: snapshot.stageId,
    previousOpenStageId: snapshot.stageId,
    reviewHistory: liveBlock.reviewHistory || liveBlock.review_history || []
  })
  let rawReview = null
  try {
    rawReview = await storyBlockStore.reviewStoryBlockWithAI(finalizedProjectId, {
      chapterNum: finalizedChapterNum,
      finalizedSummary: results?.summary?.summary || results?.summary || '',
      chapterEnding: (version?.content || '').slice(-900),
      blockStageSnapshot: snapshot,
      storyBlock: liveBlock,
      stageContinuationDepth: stageContinuationDiagnostics.stageContinuationDepth,
      previousOpenStageId: stageContinuationDiagnostics.previousOpenStageId,
      stageContinuationDiagnostics,
      facts: results?.facts || [],
      settingChanges: results?.settingChanges || []
    })
  } catch (e) {
    rawReview = buildFallbackStoryBlockReviewAfterFailure(e, snapshot, liveBlock)
    message.warning(
      '故事块 AI 回看未在限定时间内完成，已保存保守前滚回看：当前阶段标记完成，后续从下一未完成阶段继续。',
      { title: '故事块回看已使用 fallback', duration: 8000 }
    )
  }
  const review = normalizeStoryBlockReviewForGranularity(
    normalizeReviewForStageProgress(rawReview, snapshot, liveBlock),
    snapshot,
    liveBlock,
    finalizedChapterNum
  )
  const label = STORY_BLOCK_REVIEW_DECISION_LABELS[review.decision] || review.decision
  const payload = {
    chapterNum: finalizedChapterNum,
    decision: review.decision,
    review: {
      ...review,
      label,
      blockStageSnapshot: snapshot,
      finalizedSummary: results?.summary?.summary || '',
      wordCount: version?.content?.length || 0,
      facts: results?.facts || [],
      settingChanges: results?.settingChanges || []
    }
  }

  await storyBlockStore.saveBlockReview(finalizedProjectId, blockId, payload)
  const reviewedBlock = await loadStoryBlockAfterReview(blockId, finalizedProjectId) || liveBlock

  if (review.decision === 'adjust_remaining_stages') {
    const mergedStagePlan = mergeForwardStagePlan(reviewedBlock, review, snapshot)
    await storyBlockStore.updateRemainingStages(finalizedProjectId, blockId, {
      stagePlan: extractEditableFutureStageUpdates(reviewedBlock, mergedStagePlan, review, snapshot),
      stagePlanPatchMode: 'editable_future_only',
      nextStageSuggestion: deriveNextStageSuggestion(reviewedBlock, review, snapshot) || reviewedBlock.nextStageSuggestion || '',
      unresolvedQuestions: review.unresolvedQuestions?.length ? review.unresolvedQuestions : (reviewedBlock.unresolvedQuestions || []),
      dontAdvanceYet: reviewedBlock.dontAdvanceYet || [],
      carryOverToNextChapter: review.carryOverToNextChapter || reviewedBlock.carryOverToNextChapter || [],
      capacityAssessment: reviewedBlock.capacityAssessment || 'normal'
    })
  } else if (review.decision === 'continue_current_block') {
    await storyBlockStore.updateRemainingStages(finalizedProjectId, blockId, {
      nextStageSuggestion: deriveNextStageSuggestion(reviewedBlock, review, snapshot) || reviewedBlock.nextStageSuggestion || '',
      unresolvedQuestions: review.unresolvedQuestions?.length ? review.unresolvedQuestions : (reviewedBlock.unresolvedQuestions || []),
      dontAdvanceYet: reviewedBlock.dontAdvanceYet || [],
      carryOverToNextChapter: review.carryOverToNextChapter || reviewedBlock.carryOverToNextChapter || [],
      capacityAssessment: reviewedBlock.capacityAssessment || 'normal'
    })
  } else if (review.decision === 'split_unfinalized_content') {
    const carryOverToNextChapter = normalizeCarryOverReviewItems(review, reviewedBlock)
    await storyBlockStore.updateRemainingStages(finalizedProjectId, blockId, {
      nextStageSuggestion: review.nextStageSuggestion || reviewedBlock.nextStageSuggestion || '本章已定稿，拆分建议转入后续章节承接。',
      unresolvedQuestions: review.unresolvedQuestions?.length ? review.unresolvedQuestions : (reviewedBlock.unresolvedQuestions || []),
      dontAdvanceYet: reviewedBlock.dontAdvanceYet || [],
      carryOverToNextChapter,
      capacityAssessment: reviewedBlock.capacityAssessment || 'normal'
    })
    message.info('本章已定稿，拆分建议已转为后续章节承接事项。', { title: '已转为后续承接' })
  } else if (review.decision === 'complete_current_block') {
    await storyBlockStore.completeBlock(finalizedProjectId, blockId, {
      reason: review.reason || '当前故事块已在本章自然完成。',
      closeReason: 'block_goal_completed',
      completionEvidence: review.completionEvidence || review.reason || '当前故事块已在本章自然完成。',
      singleChapterBlockReason: review.singleChapterBlockReason || '',
      closedBy: 'ai_review',
      chapterRefs: [finalizedChapterNum],
      blockCloseReasonType: review.blockCloseReasonType || '',
      earlyCloseAllowed: review.earlyCloseAllowed,
      earlyCloseEvidence: review.earlyCloseEvidence || review.completionEvidence || review.reason || '',
      invalidatedStageIds: review.invalidatedStageIds || [],
      closedUnexecutedStageIds: review.closedUnexecutedStageIds || []
    })
  } else if (review.decision === 'open_new_block') {
    await storyBlockStore.closeBlock(finalizedProjectId, blockId, {
      reason: review.reason || '后续方向变化较大，提前结束当前块并开启新故事块。',
      closeReason: 'direction_changed',
      completionEvidence: review.completionEvidence || review.reason || '后续方向变化较大，当前故事块不再适用。',
      singleChapterBlockReason: review.singleChapterBlockReason || '',
      closedBy: 'ai_review',
      chapterRefs: [finalizedChapterNum],
      blockCloseReasonType: review.blockCloseReasonType || '',
      earlyCloseAllowed: review.earlyCloseAllowed,
      earlyCloseEvidence: review.earlyCloseEvidence || review.completionEvidence || review.reason || '',
      invalidatedStageIds: review.invalidatedStageIds || [],
      closedUnexecutedStageIds: review.closedUnexecutedStageIds || []
    })
    await createStoryBlockWithAI('开启新故事块', {
      seed: {
        ...(review.newBlockSeed || {}),
        entryState: results?.summary?.summary || snapshot?.stageCostOrConsequence || '承接上一故事块完成后的新局面。'
      }
    })
  }

  await storyBlockStore.loadBlocks(finalizedProjectId)
  return review
}

async function loadStoryBlockAfterReview(blockId, targetProjectId = projectId.value) {
  const blocks = await storyBlockStore.loadBlocks(targetProjectId)
  return blocks.find(block => block.id === blockId) || null
}

function buildFallbackStoryBlockReviewAfterFailure(error, snapshot = {}, block = {}) {
  const stageId = String(snapshot?.stageId || '').trim()
  return {
    decision: 'continue_current_block',
    completedStageIds: stageId ? [stageId] : [],
    stageContinues: false,
    remainingStages: [],
    nextStageSuggestion: '',
    unresolvedQuestions: Array.isArray(block?.unresolvedQuestions) ? block.unresolvedQuestions : [],
    carryOverToNextChapter: [],
    newBlockSeed: null,
    reason: '故事块 AI 回看失败或超时；按 v1 前滚边界保守处理：当前快照阶段视为已完成，下一章进入下一未完成阶段。',
    aiReviewFallback: true,
    aiReviewError: error?.message || String(error || ''),
    aiReviewDiagnostics: error?.diagnostics || storyBlockStore.lastReviewDiagnostics || null,
    completionEvidence: '',
    singleChapterBlockReason: '',
    closedBy: 'system_fallback',
    source: 'story_block_review_ai_failure_fallback'
  }
}

function normalizeReviewForStageProgress(review = {}, snapshot = {}, block = {}) {
  const normalized = {
    ...review,
    completedStageIds: Array.isArray(review.completedStageIds) ? [...review.completedStageIds] : [],
    stageContinues: review.stageContinues === true
  }
  const currentStageId = String(snapshot?.stageId || '').trim()
  const shouldCompleteCurrentStage = ['continue_current_block', 'adjust_remaining_stages', 'complete_current_block', 'open_new_block'].includes(normalized.decision)
    && currentStageId
    && !normalized.stageContinues
  if (shouldCompleteCurrentStage && !normalized.completedStageIds.map(String).includes(currentStageId)) {
    normalized.completedStageIds.push(currentStageId)
  }
  if (normalized.stageContinues) {
    const stageContinueReason = getStoryBlockStageContinueReason(normalized)
    normalized.stageContinueReason = stageContinueReason
    if (stageContinueReason && !normalized.reason) normalized.reason = stageContinueReason
  }
  if (!normalized.stageContinues) {
    normalized.nextStageSuggestion = deriveNextStageSuggestion(block, normalized, snapshot) || normalized.nextStageSuggestion || ''
  }
  normalized.completedStageIds = filterExecutedCompletedStageIds(normalized, block, snapshot)
  return clampEquivalentCompletionReview(normalized, snapshot)
}

function clampEquivalentCompletionReview(review = {}, snapshot = {}) {
  if (review.settlementDecision !== 'completed_by_equivalent_story_function') return review
  const currentStageId = String(snapshot?.stageId || review.blockStageId || '').trim()
  const attemptedIds = Array.isArray(review.completedStageIds) ? review.completedStageIds.map(String).filter(Boolean) : []
  const attemptedFutureClose = attemptedIds.some(stageId => currentStageId && stageId !== currentStageId)
  return {
    ...review,
    completedStageIds: currentStageId ? [currentStageId] : [],
    equivalentCompletionScope: 'current_stage_only',
    futureStageOverClosed: false,
    preventedFutureStageOverClose: Boolean(review.preventedFutureStageOverClose || attemptedFutureClose),
    needsFutureStageReplan: Boolean(review.needsFutureStageReplan || review.futureStageTouched || attemptedFutureClose),
    replanRemainingStages: Boolean(review.replanRemainingStages || review.futureStageTouched || attemptedFutureClose)
  }
}

function getStoryBlockStageContinueReason(review = {}) {
  return String(review.stageContinueReason || review.stage_continue_reason || review.reason || '').trim()
}

function normalizeStoryBlockReviewForGranularity(review = {}, snapshot = {}, block = {}, finalizedChapterNum = null) {
  const normalized = {
    ...review,
    completionEvidence: String(review.completionEvidence || '').trim(),
    singleChapterBlockReason: String(review.singleChapterBlockReason || '').trim(),
    closedBy: review.closedBy || 'ai_review',
    completedStageIds: filterExecutedCompletedStageIds(review, block, snapshot),
    invalidatedStageIds: Array.isArray(review.invalidatedStageIds) ? [...review.invalidatedStageIds] : [],
    closedUnexecutedStageIds: Array.isArray(review.closedUnexecutedStageIds) ? [...review.closedUnexecutedStageIds] : []
  }
  const wantsClose = ['complete_current_block', 'open_new_block'].includes(normalized.decision)
  const closeAssessment = wantsClose
    ? assessStoryBlockCloseDecision(normalized, block, snapshot)
    : { earlyCloseAllowed: true, blockCloseReasonType: 'not_closing', earlyCloseEvidence: '' }
  normalized.blockCloseReasonType = closeAssessment.blockCloseReasonType
  normalized.earlyCloseAllowed = closeAssessment.earlyCloseAllowed
  normalized.earlyCloseEvidence = closeAssessment.earlyCloseEvidence

  if (wantsClose && !closeAssessment.earlyCloseAllowed) {
    const nextStage = findNextStageAfterReview(block, normalized, snapshot)
    normalized.granularityAdjusted = true
    normalized.granularityAdjustmentReason = closeAssessment.genericOnly
      ? '故事块关闭理由过于泛化，未证明块目标完成或剩余阶段失效。'
      : '故事块提前关闭证据不足。'
    normalized.completionEvidence = ''
    normalized.singleChapterBlockReason = ''
    normalized.closedUnexecutedStageIds = []
    normalized.invalidatedStageIds = []
    normalized.blockCloseReasonType = closeAssessment.blockCloseReasonType
    if (nextStage) {
      normalized.decision = 'continue_current_block'
      normalized.reason = ['故事块完成证据不足，已转为继续当前故事块。', normalized.reason].filter(Boolean).join(' ')
    } else {
      normalized.decision = 'adjust_remaining_stages'
      normalized.remainingStages = ensureReviewHasForwardStages(normalized, block, snapshot, finalizedChapterNum)
      normalized.reason = ['故事块完成证据不足且阶段耗尽，已转为补充未执行阶段。', normalized.reason].filter(Boolean).join(' ')
    }
  }

  if (normalized.decision === 'adjust_remaining_stages') {
    normalized.remainingStages = ensureReviewHasForwardStages(normalized, block, snapshot, finalizedChapterNum)
  }

  if (['complete_current_block', 'open_new_block'].includes(normalized.decision)) {
    normalized.closedBy = normalized.closedBy || 'ai_review'
    const stageSplit = splitStoryBlockStagesByExecution(block, normalized, snapshot)
    normalized.completedStageIds = stageSplit.completedStages.map(storyBlockStageId).filter(Boolean)
    normalized.invalidatedStageIds = stageSplit.invalidatedStages.map(storyBlockStageId).filter(Boolean)
    normalized.closedUnexecutedStageIds = stageSplit.closedUnexecutedStages.map(storyBlockStageId).filter(Boolean)
    if (storyBlockCoveredChapterCount(block, finalizedChapterNum) <= 1 && !normalized.singleChapterBlockReason) {
      normalized.singleChapterBlockReason = normalized.completionEvidence || normalized.reason || '短过渡或短冲突块已自然结束。'
    }
  }
  return clampEquivalentCompletionReview(normalized, snapshot)
}

function hasStoryBlockCompletionEvidence(review = {}) {
  const evidence = String(review.completionEvidence || '').trim()
  if (evidence.length >= 8) return true
  const reason = String(review.reason || '').trim()
  return /目标已完成|目标失败|任务完成|任务失败|自然结束|明确转向|重大转向|外力打断|新任务|新地点|新敌我态势/.test(reason)
}

function storyBlockCoveredChapterCount(block = {}, extraChapterNum = null) {
  const refs = new Set((Array.isArray(block.chapterRefs) ? block.chapterRefs : []).map(String).filter(Boolean))
  for (const stage of Array.isArray(block.stagePlan) ? block.stagePlan : []) {
    for (const ref of Array.isArray(stage.chapterRefs) ? stage.chapterRefs : []) refs.add(String(ref))
    const completedChapter = stage.completedChapterNum || stage.completed_chapter_num
    if (completedChapter) refs.add(String(completedChapter))
  }
  if (extraChapterNum) refs.add(String(extraChapterNum))
  return refs.size
}

function buildManualSingleChapterBlockReason(block = {}) {
  return storyBlockCoveredChapterCount(block) <= 1
    ? '用户手动确认这是单章过渡、短冲突或外力转向块。'
    : ''
}

async function ensureActiveBlockHasForwardStages(block = {}, actionName = '小纲生成') {
  if (!block?.id || !projectId.value) return null
  const stagePlan = appendForwardStagesForActiveBlock(block, null, actionName)
  if (!stagePlan.length || JSON.stringify(stagePlan) === JSON.stringify(block.stagePlan || [])) return null
  try {
    const updated = await storyBlockStore.updateRemainingStages(projectId.value, block.id, {
      stagePlan,
      nextStageSuggestion: buildForwardStageSuggestion(block, actionName),
      unresolvedQuestions: block.unresolvedQuestions || [],
      dontAdvanceYet: block.dontAdvanceYet || [],
      carryOverToNextChapter: block.carryOverToNextChapter || [],
      capacityAssessment: block.capacityAssessment || 'normal'
    })
    message.info('当前故事块阶段已耗尽，但块目标未确认完成；已滚动补充未执行阶段继续承接。', { title: '故事块继续推进' })
    return updated
  } catch (e) {
    console.warn('[story-block] extend active block stages failed', e)
    return null
  }
}

function ensureReviewHasForwardStages(review = {}, block = {}, snapshot = {}, finalizedChapterNum = null) {
  const existing = normalizeReviewRemainingStages(review.remainingStages || [])
  if (existing.length) return existing
  return appendForwardStagesForActiveBlock(block, snapshot, `第 ${finalizedChapterNum || '?'} 章回看`).filter(stage =>
    canEditStoryBlockStageForReview(stage, new Set([snapshot?.stageId].filter(Boolean).map(String)))
  )
}

function appendForwardStagesForActiveBlock(block = {}, snapshot = {}, actionName = '故事块推进') {
  const stages = Array.isArray(block.stagePlan) ? [...block.stagePlan] : []
  const hasEditable = stages.some(stage => canEditStoryBlockStageForReview(stage))
  if (hasEditable) return stages
  const baseIndex = stages.length + 1
  const seed = sanitizeStageSeed(block, snapshot, actionName)
  return [
    ...stages,
    {
      id: `stage-roll-${chapterNum.value || 'next'}-${baseIndex}`,
      purpose: seed.purpose,
      sceneOrAction: seed.sceneOrAction,
      choice: seed.choice,
      costOrConsequence: seed.costOrConsequence,
      status: 'planned',
      generatedBy: 'granularity_roll_forward'
    },
    {
      id: `stage-roll-${chapterNum.value || 'next'}-${baseIndex + 1}`,
      purpose: '检查本故事块目标是否已经完成、失败或需要重大转向',
      sceneOrAction: '让人物面对当前任务的直接结果，并形成清晰的新态势。',
      choice: '人物选择继续追索、承担代价收束，或被迫转入新任务。',
      costOrConsequence: '给出可验证的完成证据、失败后果或外力打断原因。',
      status: 'planned',
      generatedBy: 'granularity_roll_forward'
    }
  ]
}

function sanitizeStageSeed(block = {}, snapshot = {}, actionName = '故事块推进') {
  snapshot = snapshot || {}
  const goal = block.goal || snapshot.stagePurpose || '推进当前故事块目标'
  const pressure = block.mainPressure || snapshot.externalPressure || '当前压力继续升级'
  const exitTarget = block.exitTarget || '形成清晰的任务结果或下一段承接点'
  return {
    purpose: `继续推进：${String(goal).slice(0, 48)}`,
    sceneOrAction: `${actionName}前先承接现有压力：${String(pressure).slice(0, 60)}`,
    choice: snapshot.stageChoice || '人物在继续推进与转向应对之间做出有代价的选择。',
    costOrConsequence: snapshot.stageCostOrConsequence || `逼近或检验故事块出口：${String(exitTarget).slice(0, 60)}`
  }
}

function buildForwardStageSuggestion(block = {}, actionName = '故事块推进') {
  return [
    '继续当前故事块，不因单章结束而新开块。',
    block.goal ? `块目标：${block.goal}` : '',
    block.mainPressure ? `压力：${block.mainPressure}` : '',
    actionName ? `触发动作：${actionName}` : ''
  ].filter(Boolean).join(' ')
}

function deriveNextStageSuggestion(block = {}, review = {}, snapshot = {}) {
  if (review.stageContinues) return review.nextStageSuggestion || block.nextStageSuggestion || ''
  const nextStage = findNextStageAfterReview(block, review, snapshot)
  if (!nextStage) return review.nextStageSuggestion || ''
  const stageId = nextStage.id || nextStage.stageId || ''
  const purpose = nextStage.purpose || nextStage.stagePurpose || nextStage.goal || ''
  const action = nextStage.sceneOrAction || nextStage.action || nextStage.description || ''
  return [`下一阶段：${stageId}`, purpose, action].filter(Boolean).join(' - ')
}

function findNextStageAfterReview(block = {}, review = {}, snapshot = {}) {
  const completedIds = new Set()
  for (const item of Array.isArray(block.completedStages) ? block.completedStages : []) {
    if (item && typeof item === 'object' && item.id) completedIds.add(String(item.id))
    else if (item) completedIds.add(String(item))
  }
  for (const stageId of Array.isArray(review.completedStageIds) ? review.completedStageIds : []) {
    if (stageId) completedIds.add(String(stageId))
  }
  const currentStageId = snapshot?.stageId ? String(snapshot.stageId) : ''
  if (currentStageId && !review.stageContinues) completedIds.add(currentStageId)
  return (Array.isArray(block.stagePlan) ? block.stagePlan : []).find(stage => {
    const stageId = String(stage?.id || stage?.stageId || '')
    if (!stageId || completedIds.has(stageId)) return false
    if (['completed', 'closed', 'skipped', 'closed_unexecuted', 'skipped_by_block_close', 'invalidated'].includes(String(stage.status || ''))) return false
    if (Array.isArray(stage.chapterRefs) && stage.chapterRefs.length) return false
    return true
  }) || null
}

function normalizeCarryOverReviewItems(review = {}, block = {}) {
  const items = Array.isArray(review.carryOverToNextChapter) ? review.carryOverToNextChapter : []
  const fallbackItems = [
    review.nextStageSuggestion,
    review.reason
  ].filter(Boolean)
  const existing = Array.isArray(block.carryOverToNextChapter) ? block.carryOverToNextChapter : []
  return [...existing, ...(items.length ? items : fallbackItems)].filter(Boolean)
}

function mergeForwardStagePlan(block = {}, review = {}, snapshot = {}) {
  const existingStages = Array.isArray(block.stagePlan) ? block.stagePlan : []
  const lockedStageIds = new Set([
    snapshot?.stageId,
    ...(Array.isArray(review.completedStageIds) ? review.completedStageIds : [])
  ].filter(Boolean).map(String))
  const incomingStages = normalizeReviewRemainingStages(review.remainingStages || [])
  const incomingById = new Map(incomingStages.filter(stage => stage.id).map(stage => [String(stage.id), stage]))
  const usedIncomingIds = new Set()
  const merged = []

  for (const stage of existingStages) {
    const stageId = String(stage?.id || '')
    const locked = !canEditStoryBlockStageForReview(stage, lockedStageIds)
    if (locked) {
      merged.push(stage)
      continue
    }
    const replacement = incomingById.get(stageId)
    if (replacement) {
      merged.push(replacement)
      usedIncomingIds.add(stageId)
    }
  }

  for (const stage of incomingStages) {
    if (stage.id && usedIncomingIds.has(String(stage.id))) continue
    merged.push(stage)
  }

  return merged.length ? merged : existingStages
}

function extractEditableFutureStageUpdates(block = {}, mergedStagePlan = [], review = {}, snapshot = {}) {
  const existingStages = Array.isArray(block.stagePlan) ? block.stagePlan : []
  const existingById = new Map(existingStages.filter(stage => stage?.id).map(stage => [String(stage.id), stage]))
  const lockedStageIds = new Set([
    snapshot?.stageId,
    ...(Array.isArray(review.completedStageIds) ? review.completedStageIds : [])
  ].filter(Boolean).map(String))
  return (Array.isArray(mergedStagePlan) ? mergedStagePlan : [])
    .filter(stage => {
      const stageId = String(stage?.id || '')
      const existing = existingById.get(stageId)
      if (!existing) return true
      return canEditStoryBlockStageForReview(existing, lockedStageIds)
    })
}

function normalizeReviewRemainingStages(stages = []) {
  return stages
    .map((stage, index) => {
      const item = typeof stage === 'object' && stage ? stage : { purpose: String(stage || '') }
      return {
        id: item.id || `stage-review-${Date.now()}-${index + 1}`,
        purpose: item.purpose || item.stagePurpose || item.goal || '',
        sceneOrAction: item.sceneOrAction || item.action || item.description || '',
        choice: item.choice || '',
        costOrConsequence: item.costOrConsequence || item.consequence || item.cost || '',
        status: item.status === 'completed' ? 'planned' : (item.status || 'planned')
      }
    })
    .filter(stage => stage.purpose || stage.sceneOrAction)
}

function canEditStoryBlockStageForReview(stage = {}, lockedStageIds = new Set()) {
  const id = String(stage.id || '')
  if (id && lockedStageIds.has(id)) return false
  if (stage.status === 'completed') return false
  if (stage.locked || stage.lockedByBeatPlan || stage.lockedByFinalChapter) return false
  if (Array.isArray(stage.chapterRefs) && stage.chapterRefs.length) return false
  return true
}

async function loadFinalizedVersionForPostprocess(targetChapterNum) {
  let chapter = writerStore.chapters.find(ch => Number(ch.chapterNum || ch.chapter_num || 0) === Number(targetChapterNum))
  if (!chapter) {
    await writerStore.loadChapters(projectId.value)
    chapter = writerStore.chapters.find(ch => Number(ch.chapterNum || ch.chapter_num || 0) === Number(targetChapterNum))
  }
  if (!chapter?.id) throw new Error(`找不到第 ${targetChapterNum} 章`)

  const versions = await api.versions.list(projectId.value, chapter.id)
  const finalVersionId = chapter.finalVersionId || chapter.final_version_id
  const finalVersion = versions.find(version => version.id === finalVersionId)
    || versions.find(version => (version.versionType || version.version_type) === 'final')
  if (!finalVersion?.content?.trim()) {
    throw new Error(`第 ${targetChapterNum} 章没有可用于提取的最终正文`)
  }
  return { chapter, version: finalVersion }
}

async function retryFinalizationPostprocess(targetChapterNum) {
  const num = Number(targetChapterNum || blockingFinalizationPending.value?.chapterNum || chapterNum.value)
  if (!num || finalizationProcessingActive.value) return

  const localMarker = getChapterFinalizationPending(projectId.value, num)
  const durableMarker = findDurableFinalizationPending(num)
  const marker = localMarker || durableMarker
  if (!marker) {
    message.info(`第 ${num} 章没有待重试的定稿后处理`)
    return
  }
  if (await reconcileCompletedFinalizationMarker(marker, '后续章节生成')) {
    message.success(`第 ${num} 章定稿后处理状态已确认完成，残留标记已清理`)
    return
  }
  const markerAction = getFinalizationMarkerAction(marker)
  if (!markerAction.canRetryPostprocess) {
    message.warning(
      markerAction.warning || `第 ${num} 章定稿后处理不能通过通用记忆/设定重试恢复，请先处理阻断来源。`,
      { title: '定稿后处理不可通用重试' }
    )
    return
  }

  let finalizationRun = null
  let retryVersionId = ''
  let completed = false
  finalizationRetrying.value = true
  memoryProcessing.value = true
  try {
    const { version } = await loadFinalizedVersionForPostprocess(num)
    retryVersionId = version.id
    finalizationRun = beginChapterFinalizationRun(projectId.value, num, version.id, { allowExistingPending: true })
    if (!finalizationRun.started) {
      throw new Error(finalizationRun.reason === 'already_running'
        ? '该章节定稿后处理正在执行中，请等待当前处理完成'
        : '无法接管定稿后处理，请刷新页面后重试')
    }

    message.info(`正在重试第 ${num} 章定稿后的记忆和设定提取...`)
    const results = await memoryStore.processChapterFinalization(projectId.value, version.content, num, {
      sourceVersionId: version.id,
      runId: finalizationRun.runId,
      finalizationId: finalizationRun.finalizationId
    })
    const requiredFailures = (results.errors || []).filter(error => error.required)
    if (requiredFailures.length) {
      throw new Error(requiredFailures.map(error => `${error.step}: ${error.message}`).join('；'))
    }

    memoryResult.value = results
    showMemoryResult.value = true
    await loadContextData()

    if (num === chapterNum.value) {
      await loadChapter()
    }

    completed = true
    message.success(`第 ${num} 章定稿后处理已重试完成：记忆 ${results.facts?.length || 0} 条，设定候选 ${results.settingChanges?.length || 0} 条`)
  } catch (e) {
    markChapterFinalizationFailure(projectId.value, num, e)
    finalizationMarkerVersion.value += 1
    message.error(`重试第 ${num} 章定稿后处理失败：${e.message}`)
  } finally {
    const durableCloseoutRunId = marker.runId || marker.run_id || finalizationRun?.runId || ''
    const durableCloseoutFinalizationId = marker.finalizationId || marker.finalization_id || finalizationRun?.finalizationId || ''
    try {
      const savedDurableMarker = await saveDurableFinalizationMarker(num, {
        sourceChapterNum: num,
        sourceVersionId: retryVersionId || marker.sourceVersionId || marker.source_version_id || '',
        runId: durableCloseoutRunId,
        finalizationId: durableCloseoutFinalizationId,
        commitStatus: completed ? 'committed' : 'failed_after_chapter_commit',
        reason: completed ? 'finalization postprocess retry completed' : 'finalization postprocess retry failed',
        provenance: {
          sourceChapterNum: num,
          sourceVersionId: retryVersionId || marker.sourceVersionId || marker.source_version_id || '',
          runId: durableCloseoutRunId,
          finalizationId: durableCloseoutFinalizationId,
          commitStatus: completed ? 'committed' : 'failed_after_chapter_commit'
        }
      })
      if (savedDurableMarker) upsertDurableFinalizationMarker(savedDurableMarker)
    } catch (durableSaveError) {
      console.warn('Durable finalization marker save failed', durableSaveError)
    }
    if (completed) removeDurableFinalizationMarker(num, marker)
    if (finalizationRun?.started) {
      endChapterFinalizationRun(finalizationRun.runKey, projectId.value, num, {
        keepPending: !completed,
        commitStatus: !completed ? 'failed_after_chapter_commit' : 'pending',
        sourceVersionId: retryVersionId,
        runId: finalizationRun.runId,
        finalizationId: finalizationRun.finalizationId
      })
    }
    finalizationRetrying.value = false
    memoryProcessing.value = false
  }
}

async function handleForceFinalizePending() {
  const version = pendingFinalizeVersion.value
  if (!version) return
  await performFinalize(version)
}

function handleAuditModalVisibleChange(value) {
  showAuditModal.value = value
  if (!value && pendingFinalizeVersion.value && !auditRevisionGenerating.value) {
    pendingFinalizeVersion.value = null
  }
}

function closeAuditModal() {
  pendingFinalizeVersion.value = null
  if (currentChapterFinalized.value) readonlyAuditResult.value = null
  showAuditModal.value = false
}

function extractCorrectionTaskIds(version) {
  if ((version.versionType || version.version_type) !== 'correction_candidate') return []
  const brief = version.promptBrief || version.prompt_brief || ''
  return Array.from(brief.matchAll(/\[correctionTaskId:([0-9a-fA-F-]{36})\]/g))
    .map(match => match[1])
    .filter(Boolean)
}

async function finishLinkedCorrectionTasks(taskIds) {
  const ids = Array.from(new Set(taskIds || []))
  if (!ids.length) return
  try {
    await Promise.all(ids.map(taskId =>
      correctionTaskStore.updateTask(projectId.value, taskId, { status: 'done' })
    ))
  } catch (e) {
    message.warning('定稿已完成，但部分关联纠偏任务状态更新失败：' + e.message)
  }
}

async function handleDeleteVersion(version) {
  if (!ensureCurrentChapterEditable('删除版本')) return
  await writerStore.deleteVersion(version.id)
  if (writerStore.currentVersion?.id === version.id) {
    writerStore.currentVersion = null
    editorContent.value = ''
    loadedEditorSnapshot.value = ''
  }
  message.success('版本已删除')
}

async function handleManualSave() {
  await saveEditorAsVersion()
}

function handleExportSelect(key) {
  if (key === 'txt') handleExportTxt()
  else if (key === 'md') handleExportMd()
}

async function handleExportTxt() {
  try {
    const content = await exportTxt(projectId.value)
    downloadFile(content, `${projectStore.currentProject?.title || 'novel'}.txt`)
    message.success('TXT 导出成功')
  } catch (e) {
    message.error('导出失败：' + e.message)
  }
}

async function handleExportMd() {
  try {
    const content = await exportMarkdown(projectId.value)
    downloadFile(content, `${projectStore.currentProject?.title || 'novel'}.md`, 'text/markdown')
    message.success('Markdown 导出成功')
  } catch (e) {
    message.error('导出失败：' + e.message)
  }
}

function goToChapter(num) {
  if (num < 1) return
  chapterNum.value = num
}

function handleCreateNextChapter() {
  if (!canCreateNextChapter.value) {
    message.warning(newChapterDisabledReason.value, { title: '不能新建下一章' })
    return
  }
  goToChapter((writerStore.chapters.length || 0) + 1)
}

function handleContextNavigate(item) {
  showContextPreview.value = false
  if (!item?.targetTab) return
  router.push({
    path: `/project/${projectId.value}`,
    query: { tab: item.targetTab }
  })
}
</script>

<template>
  <div v-if="projectStore.currentProject" class="writer-desk h-full flex flex-col">
    <div class="flex items-center justify-between px-4 py-2 border-b bg-white">
      <div class="min-w-0">
        <div class="flex items-center gap-3 flex-wrap">
          <h2 class="text-lg font-bold text-gray-800">{{ projectStore.currentProject.title }}</h2>
          <n-tag size="small">第 {{ chapterNum }} 章</n-tag>
          <n-tag v-if="currentVolume" size="small" type="info" :bordered="false">
            {{ currentVolume.title || `第 ${currentVolume.volumeNum} 卷` }}
          </n-tag>
          <n-tag v-if="beatPlanSavedText" size="small" type="success" :bordered="false">已有小纲</n-tag>
          <n-tag v-if="beatPlanSourceLabel" size="small" :type="beatPlanSourceTagType" :bordered="false">
            小纲：{{ beatPlanSourceLabel }}
          </n-tag>
          <n-tag v-if="!aiContextReady" size="small" type="warning" :bordered="false">
            {{ aiContextStatusText }}
          </n-tag>
          <n-tag v-if="postFinalizeFailed" size="small" type="error" :bordered="false">
            {{ finalizationMarkerAction.tagText || '定稿后处理待重试' }}
          </n-tag>
          <n-spin v-if="finalizationProcessingActive" size="tiny" />
        </div>
        <div class="story-block-context-strip">
          <span>当前故事块：{{ currentStoryBlockName }}</span>
          <span>当前阶段：{{ currentStoryBlockStageName }}</span>
          <span>当前阶段来源：{{ currentStoryBlockStageSource }}</span>
        </div>
        <div v-if="currentChapterTitleOnly" class="chapter-title-line" :title="currentChapterTitleOnly">
          《{{ currentChapterTitleOnly }}》
        </div>
      </div>
      <n-space>
        <n-button size="small" @click="router.push(`/project/${projectId}`)">项目详情</n-button>
        <n-button
          size="small"
          secondary
          :loading="chapterTitleGenerating"
          :disabled="finalizationActionBusy || !editorContent.trim()"
          @click="handleGenerateChapterTitle"
        >
          {{ chapterTitleActionText }}
        </n-button>
        <n-button
          size="small"
          secondary
          :disabled="!writerStore.currentChapter?.id || finalizationActionBusy"
          @click="openChapterTitleEditor"
        >
          编辑章名
        </n-button>
        <n-button
          v-if="blockingFinalizationPending && finalizationMarkerAction.canRetryPostprocess"
          size="small"
          type="warning"
          secondary
          :loading="finalizationRetrying"
          :disabled="finalizationActionBusy"
          @click="retryFinalizationPostprocess(blockingFinalizationPending.chapterNum)"
        >
          {{ finalizationMarkerAction.buttonText }}
        </n-button>
        <n-button size="small" @click="handleAudit" :loading="auditRunning">{{ auditButtonText }}</n-button>
        <n-button
          size="small"
          :type="currentView === 'bible' ? 'primary' : 'default'"
          @click="currentView = currentView === 'writer' ? 'bible' : 'writer'"
        >
          {{ currentView === 'writer' ? '圣经' : '写字台' }}
        </n-button>
        <n-button
          size="small"
          :type="currentView === 'memory' ? 'primary' : 'default'"
          @click="currentView = 'memory'"
        >
          记忆
        </n-button>
        <n-dropdown trigger="click" :options="exportOptions" @select="handleExportSelect">
          <n-button size="small">导出</n-button>
        </n-dropdown>
        <n-button size="small" type="primary" :disabled="!editorContent.trim() || currentChapterFinalized" @click="handleManualSave">另存为版本</n-button>
      </n-space>
    </div>

    <div v-if="currentView === 'writer'" class="flex-1 flex overflow-hidden">
      <div class="w-44 border-r bg-gray-50 p-2 overflow-y-auto flex-shrink-0">
        <h4 class="text-xs font-semibold text-gray-500 mb-2 px-1">章节</h4>
        <div class="space-y-0.5">
          <div
            v-for="ch in writerStore.chapters"
            :key="ch.id"
            :class="[
              'px-2 py-1 rounded text-xs cursor-pointer transition-colors',
              ch.chapterNum === chapterNum ? 'bg-blue-100 text-blue-700 font-medium' : 'hover:bg-gray-100 text-gray-600'
            ]"
            @click="goToChapter(ch.chapterNum)"
          >
            <span class="truncate block">第 {{ ch.chapterNum }} 章</span>
            <span
              v-if="hasCustomChapterTitle(ch)"
              class="truncate block text-[11px] leading-4 text-gray-500"
              :title="chapterListTitle(ch)"
            >
              {{ chapterListTitle(ch) }}
            </span>
            <div class="flex gap-1 mt-0.5">
              <n-tag v-if="ch.status === 'final'" type="success" size="tiny" :bordered="false">定</n-tag>
              <span v-if="ch.summary" class="text-gray-400 truncate block text-[10px]">{{ ch.summary }}</span>
            </div>
          </div>
        </div>
        <n-button
          size="tiny"
          block
          class="mt-2"
          :disabled="!canCreateNextChapter"
          :title="newChapterDisabledReason"
          @click="handleCreateNextChapter"
        >
          + 新章节
        </n-button>
      </div>

      <div class="flex-1 flex flex-col overflow-hidden">
        <div class="flex-1 p-4 overflow-y-auto relative">
          <n-input
            v-model:value="editorContent"
            type="textarea"
            placeholder="在此输入正文，或使用右侧 AI 工具生成..."
            :rows="0"
            class="writer-editor h-full"
            :readonly="editorLocked || currentChapterFinalized"
            :input-props="{ style: 'min-height: 100%' }"
            @update:value="handleContentChange"
            @select="handleSelectionChange"
            @blur="handleSelectionChange"
          />
          <div v-if="editorLocked" class="editor-lock-mask">
            <n-spin size="small" />
            <div class="text-sm font-medium text-gray-700">{{ editorLockText }}</div>
            <div class="text-xs text-gray-500">请等待 AI 完成后再编辑或切换内容</div>
          </div>
          <div v-else-if="currentChapterFinalized" class="editor-readonly-note">
            <span>本章已定稿，正文只读</span>
            <span>可滚动、选中和复制；不能再编辑、生成、改写或另存版本。</span>
          </div>
        </div>
        <div class="px-4 py-1.5 border-t bg-gray-50 text-xs text-gray-400 flex justify-between">
          <div class="flex items-center gap-2">
            <span>字数：{{ editorContent?.length || 0 }}</span>
            <span v-if="streamingContent" class="text-green-500 animate-pulse">流式生成中...</span>
          </div>
          <span v-if="hasSelection" class="text-blue-500">已选中 {{ selectedText?.length || 0 }} 字符</span>
          <span v-if="writerStore.tempDraft?.savedAt">
            上次自动保存：{{ new Date(writerStore.tempDraft.savedAt).toLocaleTimeString('zh-CN') }}
          </span>
        </div>
      </div>

      <div class="w-72 border-l bg-gray-50 p-2 overflow-y-auto flex-shrink-0 space-y-2">
        <div class="flex gap-1 mb-2">
          <n-button size="tiny" :type="rightPanel === 'tools' ? 'primary' : 'default'" @click="rightPanel = 'tools'" block>AI 工具</n-button>
          <n-button size="tiny" :type="rightPanel === 'memory' ? 'primary' : 'default'" @click="rightPanel = 'memory'" block>上下文</n-button>
        </div>

        <div v-if="rightPanel === 'tools'" class="space-y-2">
          <StoryBlockPanel
            :block="activeStoryBlock"
            :loading="storyBlockPlanningBusy"
            :disabled="finalizationActionBusy || streamingContent"
            @update-remaining-stages="handleUpdateRemainingStages"
            @split-unfinalized-content="handleSplitUnfinalizedContent"
            @close-block="handleCloseStoryBlock"
            @open-new-block="handleOpenNewStoryBlock"
            @confirm-block="handleConfirmStoryBlockReview"
          />

          <div class="grid grid-cols-1 gap-1">
            <n-button size="tiny" secondary block :disabled="!aiContextReady" @click="openContextPreview('chapter')">
              {{ aiContextReady ? '预览 AI 上下文' : '上下文加载中' }}
            </n-button>
          </div>

          <AIActionPanel
            :generating="writerStore.generating"
            :planning="writerStore.beatPlanning"
            :active-action="activeWriterAction"
            :context-ready="aiContextReady"
            :disabled-reason="aiContextStatusText"
            :has-beat-plan="!!beatPlanSavedText"
            :has-content="!!editorContent"
            :has-selection="hasSelection"
            :chapter-finalized="currentChapterFinalized"
            @plan-beats="handlePlanBeats"
            @generate="handleGenerate"
            @multi-variant="handleMultiVariant"
            @continue="handleContinue"
            @expand="handleExpand"
            @compress="handleCompress"
            @rewrite-dialog="handleRewrite('dialogue')"
            @rewrite-conflict="handleRewrite('conflict')"
            @rewrite-psychology="handleRewrite('psychology')"
            @rewrite-web-style="handleRewrite('webStyle')"
            @rewrite-literary="handleRewrite('literary')"
            @polish="handleRewrite('polish')"
            @compare="handleCompare"
          />

          <div v-if="hasAuditRevisionIssues" class="audit-revision-panel">
            <div class="audit-revision-head">
              <div>
                <div class="audit-revision-title">审稿修改建议</div>
                <div class="audit-revision-desc">定位原文后逐条替换；替换只改这一处正文。</div>
              </div>
              <n-button size="tiny" quaternary @click="clearAuditRevisionPanel">清空</n-button>
            </div>
            <div class="audit-revision-list">
              <div
                v-for="(issue, idx) in auditRevisionIssues"
                :key="auditIssueKey(issue, idx)"
                class="audit-revision-card"
                :class="{
                  'is-applied': auditIssueStatus(issue, idx) === 'applied',
                  'is-ignored': auditIssueStatus(issue, idx) === 'ignored',
                  'is-missing': auditIssueStatus(issue, idx) === 'not_found'
                }"
              >
                <div class="audit-revision-tags">
                  <n-tag size="tiny" :type="issue.severity === 'critical' ? 'error' : issue.severity === 'major' ? 'warning' : 'default'">
                    {{ auditSeverityLabel(issue.severity) }}
                  </n-tag>
                  <n-tag size="tiny" :bordered="false">{{ auditIssueTypeLabel(issue.type) }}</n-tag>
                  <n-tag v-if="auditIssueStatus(issue, idx) === 'applied'" size="tiny" type="success" :bordered="false">已替换</n-tag>
                  <n-tag v-else-if="auditIssueStatus(issue, idx) === 'ignored'" size="tiny" :bordered="false">已忽略</n-tag>
                  <n-tag v-else-if="auditIssueStatus(issue, idx) === 'not_found'" size="tiny" type="warning" :bordered="false">未定位</n-tag>
                </div>
                <div class="audit-revision-problem">{{ issue.description }}</div>
                <div v-if="auditIssueQuote(issue)" class="audit-revision-quote">
                  <span>原文</span>
                  <p>{{ auditIssueQuote(issue) }}</p>
                </div>
                <div v-if="issue.suggestion" class="audit-revision-suggestion">
                  <span>建议</span>
                  <p>{{ issue.suggestion }}</p>
                </div>
                <div v-if="auditIssueReplacement(issue)" class="audit-revision-replacement">
                  <span>替换为</span>
                  <p>{{ auditIssueReplacement(issue) }}</p>
                </div>
                <div v-else class="audit-revision-empty">
                  本条审稿没有返回可直接替换文本，可定位后手动修改，或重新审稿。
                </div>
                <div class="audit-revision-actions">
                  <n-button size="tiny" @click="locateAuditIssue(issue, idx)">定位原文</n-button>
                  <n-button
                    size="tiny"
                    type="primary"
                    :disabled="!auditIssueReplacement(issue) || currentChapterFinalized || auditIssueStatus(issue, idx) === 'applied'"
                    @click="replaceAuditIssue(issue, idx)"
                  >
                    替换
                  </n-button>
                  <n-button size="tiny" secondary @click="ignoreAuditIssue(issue, idx)">忽略</n-button>
                </div>
              </div>
            </div>
          </div>

          <n-divider style="margin: 6px 0" />

          <div class="flex gap-1">
            <n-button size="tiny" quaternary @click="handleStyleAnalysis" :loading="memoryStore.styleAnalyzing" :disabled="!editorContent">
              风格分析
            </n-button>
            <n-button size="tiny" quaternary @click="handlePacingAnalysis" :loading="memoryStore.pacingAnalyzing" :disabled="!editorContent">
              节奏分析
            </n-button>
          </div>

          <n-divider style="margin: 6px 0" />

          <ChapterVersionList
            :versions="writerStore.versions"
            :current-version-id="writerStore.currentVersion?.id"
            :final-version-id="finalizedVersionId"
            :comparison-version-ids="compareStore.comparisonVersions.map(version => version.id)"
            :finalize-disabled="finalizationActionBusy"
            @load="loadVersion"
            @delete="handleDeleteVersion"
            @finalize="handleFinalize"
            @compare="handleToggleVersionCompare"
          />

          <CompareInline @load-version="loadVersion" />

          <div v-if="compareStore.comparisonVersions.length >= 1 && diffBaseVersion" class="pt-1">
            <div class="grid grid-cols-1 gap-1">
              <n-button size="tiny" type="info" secondary block @click="handleOpenDiff">
                差异对比
              </n-button>
            </div>
          </div>

          <div v-if="compareStore.comparisonVersions.length >= 2" class="pt-1">
            <div class="grid grid-cols-1 gap-1">
              <n-button size="tiny" type="warning" block @click="handleOpenFusion">
                融合多模型版本
              </n-button>
            </div>
          </div>
        </div>

        <div v-if="rightPanel === 'memory'" class="space-y-2">
          <n-button size="tiny" secondary block :disabled="!aiContextReady" @click="openContextPreview('planning')">
            {{ aiContextReady ? '预览本章 AI 上下文' : '上下文加载中' }}
          </n-button>
          <ContextMemoryPanel />
          <n-divider style="margin: 8px 0" />
          <CanonReviewPanel />
        </div>
      </div>
    </div>

    <div v-if="currentView === 'bible'" class="flex-1 overflow-y-auto p-4">
      <CreativeBible :project-id="projectId" />
    </div>

    <div v-if="currentView === 'memory'" class="flex-1 overflow-y-auto p-4">
      <div class="max-w-3xl mx-auto space-y-4">
        <CanonReviewPanel />
        <n-card title="角色与伏笔" size="small">
          <ContextMemoryPanel />
        </n-card>
      </div>
    </div>

    <n-modal
      v-model:show="showBeatPlanModal"
      title="本章小纲确认"
      preset="card"
      class="beat-plan-modal"
      style="width: min(760px, 92vw); max-height: 85vh;"
      content-style="padding-bottom: 0;"
    >
      <div class="beat-plan-modal-body">
        <div class="rounded border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs leading-6 text-emerald-800">
          先确认这一章的剧情节拍，再生成正文。重新生成只会替换当前弹窗草稿，不会覆盖已保存小纲；点“保存小纲”或“开始生成本章”后才会写入。
        </div>
        <div v-if="beatPlanDraftChanged" class="rounded border border-amber-100 bg-amber-50 px-3 py-2 text-xs leading-6 text-amber-700">
          当前小纲与已保存版本不同。关闭弹窗不会自动保存，确认使用前请保存或直接开始生成本章。
        </div>
        <div v-if="beatPlanSourceLabel" class="text-xs text-gray-500">
          小纲来源：{{ beatPlanSourceLabel }}
        </div>

        <n-input
          v-model:value="beatPlanText"
          type="textarea"
          class="beat-plan-input"
          placeholder="这里会显示 AI 生成的本章小纲，也可以手动补充或重排节拍..."
          :autosize="{ minRows: 12, maxRows: 18 }"
          :disabled="currentChapterFinalized"
        />
      </div>

      <template #footer>
        <div class="beat-plan-modal-footer">
          <n-button size="small" :disabled="!beatPlanText.trim() || writerStore.beatPlanning || streamingContent || currentChapterFinalized" @click="saveCurrentBeatPlan(true)">
            保存小纲
          </n-button>
          <n-button size="small" :loading="writerStore.beatPlanning" :disabled="streamingContent || !aiContextReady || currentChapterFinalized" @click="handleRefreshBeatPlan">
            重新生成小纲
          </n-button>
          <n-button size="small" type="primary" :loading="streamingContent" :disabled="!beatPlanText.trim() || writerStore.beatPlanning || !aiContextReady || currentChapterFinalized" @click="handleGenerateFromBeatPlan">
            {{ beatPlanPrimaryText }}
          </n-button>
        </div>
      </template>
    </n-modal>

    <n-modal
      v-model:show="showChapterTitleEditor"
      title="编辑章名"
      preset="card"
      style="width: 460px; max-width: 92vw;"
      :mask-closable="!chapterTitleSaving"
      :close-on-esc="!chapterTitleSaving"
    >
      <div class="space-y-3">
        <n-input
          v-model:value="chapterTitleDraft"
          placeholder="输入目录中显示的章节标题"
          maxlength="30"
          show-count
          @keyup.enter="handleSaveManualChapterTitle"
        />
        <p class="text-xs text-gray-500 leading-5">
          章名只影响目录和导出标题，不会修改已定稿正文、记忆或设定库。
        </p>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <n-button size="small" :disabled="chapterTitleSaving" @click="showChapterTitleEditor = false">取消</n-button>
          <n-button size="small" type="primary" :loading="chapterTitleSaving" @click="handleSaveManualChapterTitle">保存章名</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal
      :show="showAuditModal"
      :title="auditModalTitle"
      preset="card"
      class="audit-report-modal"
      style="width: min(860px, 92vw); max-height: 86vh;"
      content-style="padding-bottom: 0;"
      @update:show="handleAuditModalVisibleChange"
    >
      <n-spin :show="auditRunning">
        <div v-if="auditModalReport" class="audit-report-body space-y-4">
          <div
            v-if="pendingFinalizeVersion && blockingAuditIssues.length"
            class="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800"
          >
            定稿前审稿发现严重/主要问题，系统暂未锁定正文。你可以先生成修订版本，或确认仍然定稿；返回修改则不会定稿。
          </div>
          <div
            v-if="currentChapterFinalized && !pendingFinalizeVersion"
            class="rounded border border-gray-200 bg-gray-50 px-3 py-2 text-sm leading-6 text-gray-600"
          >
            本章已定稿，当前报告为只读复查，仅供查看：不会修改正文、版本、记忆、设定库或纠偏任务，也不会进入后续写作上下文。
          </div>
          <n-card size="small" title="总体评价">
            <p class="text-sm">{{ auditModalReport.overallAssessment }}</p>
          </n-card>

          <div v-if="auditModalReport.issues?.length > 0">
            <h4 class="text-sm font-semibold mb-2">发现 {{ auditModalReport.issues.length }} 个问题</h4>
            <div class="space-y-2">
              <div
                v-for="(issue, idx) in auditModalReport.issues"
                :key="idx"
                class="p-3 rounded border text-sm"
                :class="{
                  'border-red-200 bg-red-50': issue.severity === 'critical',
                  'border-orange-200 bg-orange-50': issue.severity === 'major',
                  'border-yellow-100 bg-yellow-50': issue.severity === 'minor',
                  'border-gray-200': issue.severity === 'suggestion'
                }"
              >
                <div class="flex items-center gap-2 mb-1">
                  <n-tag :type="issue.severity === 'critical' ? 'error' : issue.severity === 'major' ? 'warning' : 'default'" size="tiny">
                    {{ auditSeverityLabel(issue.severity) }}
                  </n-tag>
                  <n-tag size="tiny" :bordered="false">{{ auditIssueTypeLabel(issue.type) }}</n-tag>
                </div>
                <p class="text-gray-800 font-medium">{{ issue.description }}</p>
                <p v-if="issue.location" class="text-gray-400 text-xs mt-1">位置：{{ issue.location }}</p>
                <p v-if="issue.suggestion" class="text-blue-600 text-xs mt-1">建议：{{ issue.suggestion }}</p>
                <p v-if="issue.reason" class="text-gray-500 text-xs mt-1">原因：{{ issue.reason }}</p>
              </div>
            </div>
          </div>
          <n-empty v-else description="未发现明显问题" size="small" />

          <div class="space-y-3 text-sm">
            <div class="rounded border border-gray-100 bg-gray-50 px-3 py-2">
              <div class="text-gray-400 mb-1">风格一致性</div>
              <div class="text-gray-700 leading-6">{{ auditModalReport.styleConsistency }}</div>
            </div>
            <div class="rounded border border-gray-100 bg-gray-50 px-3 py-2">
              <div class="text-gray-400 mb-1">角色一致性</div>
              <div class="text-gray-700 leading-6">{{ auditModalReport.characterConsistency }}</div>
            </div>
          </div>
          <div v-if="auditModalReport.recommendations?.length">
            <h4 class="text-sm font-semibold mb-1">建议</h4>
            <ul class="text-sm text-gray-600 list-disc pl-4">
              <li v-for="(rec, idx) in auditModalReport.recommendations" :key="idx">{{ rec }}</li>
            </ul>
          </div>
        </div>
        <n-empty v-if="!auditRunning && !auditModalReport" description="点击审稿按钮查看报告" size="small" />
      </n-spin>
      <template #footer>
        <div class="flex justify-end gap-2">
          <n-button
            v-if="auditModalReport?.issues?.length && !currentChapterFinalized"
            size="small"
            type="primary"
            secondary
            :loading="auditRevisionGenerating"
            @click="handleGenerateAuditRevisionVersion"
          >
            生成局部修订版本
          </n-button>
          <n-button
            v-if="pendingFinalizeVersion && blockingAuditIssues.length"
            size="small"
            type="warning"
            :disabled="auditRunning || auditRevisionGenerating || finalizationActionBusy"
            :loading="finalizationProcessingActive"
            @click="handleForceFinalizePending"
          >
            仍然定稿
          </n-button>
          <n-button v-if="auditModalReport?.issues?.length && currentChapterFinalized" size="small" disabled>
            已定稿，仅查看
          </n-button>
          <n-button size="small" @click="closeAuditModal">{{ pendingFinalizeVersion ? '返回修改' : '关闭' }}</n-button>
        </div>
      </template>
    </n-modal>

    <n-modal
      v-model:show="showUnsavedVersionModal"
      title="当前编辑尚未另存为版本"
      preset="card"
      style="width: 520px; max-width: 92vw;"
      :mask-closable="false"
      :close-on-esc="false"
      @close="cancelPendingVersionLoad"
    >
      <div class="space-y-3 text-sm text-gray-700 leading-6">
        <p>
          你已经修改了左侧编辑器内容，但这些改动目前只在临时草稿中，不会自动覆盖原候选版本。
        </p>
        <p>
          切换到其他版本前，建议先另存为一个“用户草稿”版本，方便后续对比、定稿或回溯。
        </p>
      </div>
      <template #footer>
        <div class="flex justify-end gap-2">
          <n-button size="small" @click="cancelPendingVersionLoad">继续编辑</n-button>
          <n-button size="small" @click="discardAndLoadPendingVersion">不另存，直接切换</n-button>
          <n-button size="small" type="primary" @click="saveAndLoadPendingVersion">另存为版本后切换</n-button>
        </div>
      </template>
    </n-modal>

    <StyleAnalysisPanel
      v-if="showStyleModal"
      :project-id="projectId"
      @close="showStyleModal = false"
    />

    <n-modal v-model:show="showPacingModal" title="章节节奏分析" preset="card" style="width: 640px; max-height: 80vh;">
      <n-spin :show="memoryStore.pacingAnalyzing">
        <PacingChart v-if="memoryStore.lastPacingAnalysis" :pacing="memoryStore.lastPacingAnalysis" />
        <n-empty v-if="!memoryStore.pacingAnalyzing && !memoryStore.lastPacingAnalysis" description="暂无分析结果" size="small" />
      </n-spin>
    </n-modal>

    <CompareModal
      v-if="showCompareModal"
      :project-id="projectId"
      :chapter-num="chapterNum"
      :context="compareContext"
      :beat-plan="compareBeatPlan"
      @close="showCompareModal = false"
    />

    <FusionPanel
      v-if="showFusionPanel"
      :project-id="projectId"
      :chapter-num="chapterNum"
      @close="showFusionPanel = false"
    />

    <VersionDiffModal
      v-if="showDiffModal"
      :base-version="diffBaseVersion"
      :versions="diffVersions"
      @load-version="loadVersion"
      @close="showDiffModal = false"
    />

    <ContextPreviewModal
      v-if="showContextPreview"
      :context="contextPreview.context"
      :mode="contextPreview.mode"
      :used-tokens="contextPreview.usedTokens"
      :max-tokens="contextPreview.maxTokens"
      @navigate="handleContextNavigate"
      @close="showContextPreview = false"
    />

    <div v-if="finalizationProcessingActive" class="finalization-processing-mask">
      <div class="finalization-processing-card">
        <n-spin size="medium" />
        <div class="finalization-processing-title">正在提取定稿后的记忆和设定</div>
        <div class="finalization-processing-desc">
          请等待处理完成。完成前会锁定章节切换和 AI 生成，避免下一章读不到最新人物状态、关系或设定变更。
        </div>
      </div>
    </div>
  </div>

  <div v-else class="p-6">
    <n-empty description="请先选择一个项目">
      <template #action>
        <n-button @click="router.push('/')">返回项目库</n-button>
      </template>
    </n-empty>
  </div>
</template>

<style scoped>
.writer-desk {
  height: calc(100vh - 56px);
  position: relative;
}

.writer-editor :deep(textarea) {
  min-height: 400px !important;
  font-family: 'Georgia', 'Noto Serif SC', serif;
  font-size: 15px;
  line-height: 1.8;
  resize: none;
  border: none !important;
  box-shadow: none !important;
}

.writer-editor :deep(textarea):focus {
  box-shadow: none !important;
}

.editor-lock-mask {
  position: absolute;
  inset: 16px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  border: 0;
  border-radius: 6px;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
  pointer-events: none;
}

.editor-lock-mask :deep(.n-spin-body) {
  --n-color: #e2e8f0;
}

.editor-lock-mask .text-gray-700 {
  color: #f8fafc !important;
}

.editor-lock-mask .text-gray-500 {
  color: #e2e8f0 !important;
}

.editor-readonly-note {
  position: absolute;
  top: 12px;
  right: 42px;
  z-index: 2;
  display: flex;
  flex-direction: column;
  gap: 2px;
  max-width: 300px;
  padding: 6px 8px;
  border: 1px solid rgba(16, 185, 129, 0.25);
  border-radius: 6px;
  background: rgba(236, 253, 245, 0.62);
  color: #047857;
  font-size: 11px;
  line-height: 1.45;
  pointer-events: none;
  box-shadow: 0 4px 12px rgba(15, 23, 42, 0.04);
}

.editor-readonly-note span:first-child {
  font-weight: 600;
}

.story-block-context-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-top: 5px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
}

.chapter-title-line {
  margin-top: 4px;
  max-width: min(720px, 70vw);
  color: #334155;
  font-size: 13px;
  line-height: 1.5;
  white-space: normal;
  word-break: break-word;
}

.audit-revision-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  padding: 8px;
}

.audit-revision-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.audit-revision-title {
  color: #1f2937;
  font-size: 13px;
  font-weight: 700;
}

.audit-revision-desc {
  margin-top: 2px;
  color: #8a94a6;
  font-size: 11px;
  line-height: 1.5;
}

.audit-revision-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 360px;
  overflow-y: auto;
  padding-right: 2px;
}

.audit-revision-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border: 1px solid #fee2e2;
  border-radius: 6px;
  background: #fff7f7;
  padding: 8px;
}

.audit-revision-card.is-applied {
  border-color: #bbf7d0;
  background: #f0fdf4;
}

.audit-revision-card.is-ignored {
  border-color: #e5e7eb;
  background: #f9fafb;
  opacity: 0.75;
}

.audit-revision-card.is-missing {
  border-color: #fde68a;
  background: #fffbeb;
}

.audit-revision-tags,
.audit-revision-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.audit-revision-problem {
  color: #374151;
  font-size: 12px;
  font-weight: 600;
  line-height: 1.6;
}

.audit-revision-quote,
.audit-revision-suggestion,
.audit-revision-replacement {
  border-radius: 5px;
  padding: 6px;
}

.audit-revision-quote {
  border: 1px solid #fecaca;
  background: #fff1f2;
}

.audit-revision-suggestion {
  border: 1px solid #bfdbfe;
  background: #eff6ff;
}

.audit-revision-replacement {
  border: 1px solid #bbf7d0;
  background: #f0fdf4;
}

.audit-revision-quote span,
.audit-revision-suggestion span,
.audit-revision-replacement span {
  display: inline-block;
  margin-bottom: 4px;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}

.audit-revision-quote p,
.audit-revision-suggestion p,
.audit-revision-replacement p {
  margin: 0;
  color: #334155;
  font-size: 12px;
  line-height: 1.65;
  white-space: pre-wrap;
}

.audit-revision-empty {
  color: #9ca3af;
  font-size: 11px;
  line-height: 1.6;
}

.finalization-processing-mask {
  position: fixed;
  inset: 0;
  z-index: 3000;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  background: rgba(0, 0, 0, 0.4);
  backdrop-filter: none;
  -webkit-backdrop-filter: none;
}

.finalization-processing-card {
  width: min(520px, 92vw);
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 28px 32px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 20px 50px rgba(15, 23, 42, 0.22);
  text-align: center;
}

.finalization-processing-title {
  font-size: 16px;
  font-weight: 700;
  color: #111827;
}

.finalization-processing-desc {
  max-width: 420px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.7;
}

.audit-report-modal :deep(.n-card__content) {
  max-height: calc(86vh - 88px);
  overflow: hidden;
}

.audit-report-body {
  max-height: calc(86vh - 118px);
  overflow-y: auto;
  padding-right: 6px;
  padding-bottom: 16px;
}

.beat-plan-modal-body {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: calc(85vh - 170px);
  overflow: hidden;
}

.beat-plan-input {
  min-height: 0;
}

.beat-plan-input :deep(textarea) {
  max-height: 52vh;
  overflow-y: auto !important;
  line-height: 1.75;
}

.beat-plan-modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}
</style>

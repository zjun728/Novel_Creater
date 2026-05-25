<script setup>
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
import {
  correctionTaskMode,
  isCorrectionTaskActiveForContext,
  isCorrectionTaskBlockingForGeneration,
  useCorrectionTaskStore
} from '@/stores/correctionTaskStore'
import { useCompareStore } from '@/stores/compareStore'
import { buildWritingContext } from '@/utils/contextBuilder'
import { auditIssueTypeLabel, auditSeverityLabel } from '@/utils/auditLabels'
import { api } from '@/api/db/client'
import { downloadFile, exportTxt, exportMarkdown } from '@/utils/export'
import { formatChapterDisplayTitle, isDefaultChapterTitle } from '@/prompts/chapter'
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
import { assessChapterWordCount, buildChapterWordTarget } from '@/utils/chapterWordTarget'
import {
  applyAuditReplacement,
  cleanAuditQuote,
  getAuditReplacement,
  locateAuditQuote
} from '@/utils/auditRevisionTools'
import {
  beginChapterFinalizationRun,
  endChapterFinalizationRun,
  getChapterFinalizationPending,
} from '@/utils/finalizationGuard'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const writerStore = useWriterStore()
const novelStore = useNovelStore()
const seedStore = useSeedStore()
const memoryStore = useMemoryStore()
const settingStore = useSettingStore()
const volumeStore = useVolumeStore()
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
const showUnsavedVersionModal = ref(false)
const auditRunning = ref(false)
const auditRevisionGenerating = ref(false)
const finalizeAuditInFlight = ref(false)
const finalizeSubmitting = ref(false)
const beatPlanText = ref('')
const beatPlanSavedText = ref('')
const beatPlanIntent = ref('single')
const streamingContent = ref(false)
const activeWriterAction = ref('')
const memoryProcessing = ref(false)
const chapterLoading = ref(false)
const contextLoading = ref(false)
const contextDataLoaded = ref(false)
const showMemoryResult = ref(false)
const memoryResult = ref(null)
const contextPreview = ref({ context: {}, usedTokens: 0, maxTokens: 0, mode: 'chapter' })
const loadedEditorSnapshot = ref('')
const pendingVersionToLoad = ref(null)
const pendingFinalizeVersion = ref(null)
const previousChapterEnding = ref('')
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

const blockingAuditIssues = computed(() =>
  (memoryStore.lastAuditResult?.issues || []).filter(issue =>
    ['critical', 'major'].includes(issue.severity)
  )
)

const auditRevisionIssues = computed(() => memoryStore.lastAuditResult?.issues || [])

const hasAuditRevisionIssues = computed(() =>
  currentView.value === 'writer' &&
  !pendingFinalizeVersion.value &&
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

const writerActionLabels = {
  chapter: '正在生成本章',
  multi: '正在生成多候选版本',
  continue: '正在续写',
  expand: '正在扩写选区',
  compress: '正在压缩选区',
  rewrite: '正在改写选区'
}

const finalizationProcessingActive = computed(() =>
  finalizeSubmitting.value || memoryProcessing.value || !!memoryStore.processing
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

const currentChapterDisplayTitle = computed(() =>
  formatChapterDisplayTitle(writerStore.currentChapter || { chapterNum: chapterNum.value }, { chapterNum: chapterNum.value })
)

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

const aiContextStatusText = computed(() => {
  if (finalizationProcessingActive.value) return '正在提取定稿后的记忆和设定'
  if (chapterLoading.value) return '正在加载章节资料'
  if (contextLoading.value) return '正在加载创作上下文'
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
  auditIssueActions.value = {}
  beatPlanText.value = ''
  beatPlanSavedText.value = ''
  compareContext.value = {}
  compareBeatPlan.value = ''
  previousChapterEnding.value = ''
  compareStore.clearComparison()
  await loadChapter()
  router.replace(`/writer/${projectId.value}/${newNum}`)
})

async function loadContextData() {
  contextLoading.value = true
  try {
    await Promise.all([
      novelStore.loadBible(projectId.value),
      novelStore.loadOutline(projectId.value),
      novelStore.loadCharacters(projectId.value),
      novelStore.loadPlotThreads(projectId.value),
      novelStore.loadCanonFacts(projectId.value),
      settingStore.loadEntities(projectId.value),
      settingStore.loadRelations(projectId.value),
      settingStore.loadChangeEvents(projectId.value),
      volumeStore.loadVolumes(projectId.value),
      correctionTaskStore.loadTasks(projectId.value),
      seedStore.loadSeeds(projectId.value)
    ])
    contextDataLoaded.value = true
  } finally {
    contextLoading.value = false
  }
}

async function loadChapter() {
  chapterLoading.value = true
  try {
    await writerStore.loadChapters(projectId.value)
    const chapter = await writerStore.getOrCreateChapter(projectId.value, chapterNum.value)
    await writerStore.loadVersions(projectId.value, chapter.id)
    const savedBeatPlan = await writerStore.loadChapterBeatPlan(projectId.value, chapterNum.value)
    beatPlanText.value = savedBeatPlan?.content || ''
    beatPlanSavedText.value = savedBeatPlan?.content || ''
    previousChapterEnding.value = await loadPreviousChapterEnding()

    const draft = await writerStore.loadTempDraft(projectId.value, chapterNum.value)
    if (draft?.content) {
      editorContent.value = draft.content
      loadedEditorSnapshot.value = draft.content
    } else if (chapter.finalVersionId) {
      const final = writerStore.versions.find(version => version.id === chapter.finalVersionId)
      editorContent.value = final?.content || ''
      writerStore.currentVersion = final || null
      loadedEditorSnapshot.value = editorContent.value
    } else if (writerStore.versions.length > 0) {
      writerStore.currentVersion = writerStore.versions[0]
      editorContent.value = writerStore.versions[0].content
      loadedEditorSnapshot.value = editorContent.value
    } else {
      editorContent.value = ''
      writerStore.currentVersion = null
      loadedEditorSnapshot.value = ''
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

function buildBaseContext() {
  return buildBaseContextResult().context
}

async function ensureAiContextReady(actionName = 'AI 操作') {
  if (finalizationProcessingActive.value) {
    message.warning(
      `上一章或当前章节定稿后的记忆/设定提取仍在进行。请等待处理完成后再执行${actionName}，否则下一章可能读不到最新人物状态和设定变更。`,
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

  return true
}

async function ensureNoPendingSettingChanges(actionName = 'AI 写作') {
  if (pendingSettingChanges.value.length > 0) {
    message.warning(
      `设定库还有 ${pendingSettingChanges.value.length} 条待确认变更。${actionName}只会读取已确认的设定库和已确认事实，未确认的上一章人物状态、关系、地点、能力变化不会作为硬设定进入下一章。请先到“记忆/设定库”确认或拒绝这些变更，再继续生成，避免后续章节错乱。`,
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

  if (pendingSettingChanges.value.length > 0) {
    message.warning(
      `设定库还有 ${pendingSettingChanges.value.length} 条待确认变更。请先确认或拒绝后再执行${actionName}。`,
      { title: '请先确认设定变更' }
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
  if (blockers.length) {
    message.warning(
      `当前存在 ${blockers.length} 条阻断型纠偏任务未处理。请先到「项目详情 > 6 纠偏任务」确认、完成或忽略后，再继续${actionName}。`,
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
  if (!currentChapterFinalized.value) return true
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

  if (!isChapterFinalized(previousChapter)) {
    message.warning(
      `第 ${chapterNum.value - 1} 章还没有定稿，不能继续执行第 ${chapterNum.value} 章的${actionName}。请先回到上一章选择最终版本并定稿，再继续生成下一章，避免章节衔接和人物状态断层。`,
      { title: '请先定稿上一章' }
    )
    return false
  }

  const previousProcessing = getChapterFinalizationPending(projectId.value, chapterNum.value - 1)
  if (previousProcessing || finalizationProcessingActive.value) {
    message.warning(
      `第 ${chapterNum.value - 1} 章定稿后的记忆和设定变更还在提取中，暂时不能执行第 ${chapterNum.value} 章的${actionName}。请等提取完成，并处理待确认设定变更后再继续。`,
      { title: '上一章定稿后处理未完成' }
    )
    return false
  }

  return true
}

function buildBaseContextResult() {
  const result = buildWritingContext(
    novelStore,
    chapterNum.value,
    undefined,
    settingStore,
    volumeStore,
    correctionTaskStore
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
  const wordTarget = buildChapterWordTarget(projectStore.currentProject || {}, result.context.volumeStage)
  if (wordTarget) {
    result.context.wordTarget = wordTarget
  }
  return result
}

function buildConfirmedChapterContext(confirmedPlan) {
  return {
    ...buildBaseContext(),
    beatPlan: confirmedPlan
  }
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

async function ensureBeatPlan(force = false, options = {}) {
  const { persist = true } = options
  if (!await ensureAiContextReady('小纲生成')) return ''
  const existingPlan = beatPlanText.value.trim()
  if (existingPlan && !force) return existingPlan
  if (!ensureCurrentChapterEditable('小纲生成')) return ''
  if (!await ensurePreviousChapterFinalized('小纲生成')) return ''
  if (!await ensureNoPendingSettingChanges('小纲生成')) return ''
  if (!await ensureCorrectionTasksAllowGeneration('小纲生成')) return ''
  beatPlanText.value = await writerStore.generateChapterBeatPlan(projectId.value, chapterNum.value, buildBaseContext())
  if (persist && beatPlanText.value.trim()) {
    await writerStore.saveChapterBeatPlan(projectId.value, chapterNum.value, beatPlanText.value)
    beatPlanSavedText.value = beatPlanText.value.trim()
  }
  return beatPlanText.value
}

async function saveCurrentBeatPlan(showMessage = true) {
  if (!ensureCurrentChapterEditable('保存小纲')) return false
  const content = beatPlanText.value.trim()
  if (!content) {
    message.warning('请先生成或填写本章小纲')
    return false
  }
  try {
    await writerStore.saveChapterBeatPlan(projectId.value, chapterNum.value, content)
    beatPlanText.value = content
    beatPlanSavedText.value = content
    if (showMessage) message.success('本章小纲已保存')
    return true
  } catch (e) {
    message.error('保存小纲失败：' + e.message)
    return false
  }
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
  if (!await ensureCorrectionTasksAllowGeneration('正文生成')) return
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
    message.error('按小纲生成失败：' + e.message)
  } finally {
    streamingContent.value = false
    if (activeWriterAction.value === 'chapter') activeWriterAction.value = ''
  }
}

async function generateMultiVariantsFromPlan(confirmedPlan) {
  if (!await ensureAiContextReady('多候选生成')) return
  if (!ensureCurrentChapterEditable('多候选生成')) return
  if (!await ensurePreviousChapterFinalized('多候选生成')) return
  if (!await ensureNoPendingSettingChanges('多候选生成')) return
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
  if (!ensureCurrentChapterEditable(beatPlanIntent.value === 'multi' ? '多候选生成' : beatPlanIntent.value === 'compare' ? '多模型对比' : '正文生成')) return
  const confirmedPlan = beatPlanText.value.trim()
  if (!confirmedPlan) {
    message.warning('请先生成或填写本章小纲')
    return
  }
  const saved = await saveCurrentBeatPlan(false)
  if (!saved) return
  showBeatPlanModal.value = false
  if (beatPlanIntent.value === 'multi') {
    await generateMultiVariantsFromPlan(confirmedPlan)
  } else if (beatPlanIntent.value === 'compare') {
    await openCompareWithPlan(confirmedPlan)
  } else {
    await generateChapterFromPlan(confirmedPlan)
  }
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
  if (!await ensureCorrectionTasksAllowGeneration('选区改写')) return
  try {
    activeWriterAction.value = 'rewrite'
    const baseContext = buildBaseContext()
    const result = await writerStore.rewriteSelection(selectedText.value, mode, {
      styleBible: novelStore.bible?.styleBible,
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
  auditIssueActions.value = {}
  auditRunning.value = true
  showAuditModal.value = true
  try {
    await memoryStore.auditChapter(projectId.value, editorContent.value, chapterNum.value)
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
  const version = await writerStore.createVersion(projectId.value, chapter.id, chapterNum.value, {
    title: `${sourceTitle} - 用户草稿`,
    content,
    versionType: 'user_draft',
    promptBrief: writerStore.currentVersion?.id
      ? `基于版本「${sourceTitle}」手动编辑后另存`
      : '手动编辑后另存'
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
  pendingFinalizeVersion.value = version
  memoryStore.lastAuditResult = null
  finalizeAuditInFlight.value = true
  auditRunning.value = true
  showAuditModal.value = true
  try {
    const report = await memoryStore.auditChapter(projectId.value, version.content, chapterNum.value)
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
  const finalizationRun = beginChapterFinalizationRun(finalizedProjectId, finalizedChapterNum, version.id)
  if (!finalizationRun.started) {
    message.warning('本章定稿或定稿后入库正在处理中，请不要重复点击。', { title: '定稿处理中' })
    return
  }
  const correctionTaskIds = extractCorrectionTaskIds(version)
  finalizeSubmitting.value = true
  memoryProcessing.value = true
  try {
    await writerStore.finalizeVersion(version)
    pendingFinalizeVersion.value = null
    showAuditModal.value = false
    message.success('已定稿，正在提取记忆和设定变更...')

    try {
      await finishLinkedCorrectionTasks(correctionTaskIds)
    } catch (e) {
      console.warn('关联纠偏任务状态更新失败:', e.message)
    }
    try {
      await writerStore.clearTempDraft(finalizedProjectId, finalizedChapterNum)
    } catch (e) {
      console.warn('临时草稿清理失败:', e.message)
    }
    const results = await memoryStore.processChapterFinalization(finalizedProjectId, version.content, finalizedChapterNum)
    memoryResult.value = results
    showMemoryResult.value = true
    await loadContextData()

    const factCount = results.facts?.length || 0
    const settingChangeCount = results.settingChanges?.length || 0
    message.success(`定稿后处理完成：提取 ${factCount} 条记忆事实，生成 ${settingChangeCount} 条待确认设定变更`)
  } catch (e) {
    message.warning('定稿后处理部分失败：' + e.message)
  } finally {
    endChapterFinalizationRun(finalizationRun.runKey, finalizedProjectId, finalizedChapterNum)
    finalizeSubmitting.value = false
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
      <div class="flex items-center gap-3">
        <h2 class="text-lg font-bold text-gray-800">{{ projectStore.currentProject.title }}</h2>
        <n-tag size="small">{{ currentChapterDisplayTitle }}</n-tag>
        <n-tag v-if="currentVolume" size="small" type="info" :bordered="false">
          {{ currentVolume.title || `第 ${currentVolume.volumeNum} 卷` }}
        </n-tag>
        <n-tag v-if="beatPlanSavedText" size="small" type="success" :bordered="false">已有小纲</n-tag>
        <n-tag v-if="!aiContextReady" size="small" type="warning" :bordered="false">
          {{ aiContextStatusText }}
        </n-tag>
        <n-spin v-if="finalizationProcessingActive" size="tiny" />
      </div>
      <n-space>
        <n-button size="small" @click="router.push(`/project/${projectId}`)">项目详情</n-button>
        <n-button size="small" @click="handleAudit" :loading="auditRunning">本章审稿</n-button>
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
            <span v-if="hasCustomChapterTitle(ch)" class="truncate block text-[11px] leading-4 text-gray-500">
              {{ chapterListTitle(ch) }}
            </span>
            <div class="flex gap-1 mt-0.5">
              <n-tag v-if="ch.status === 'final'" type="success" size="tiny" :bordered="false">定</n-tag>
              <span v-if="ch.summary" class="text-gray-400 truncate block text-[10px]">{{ ch.summary }}</span>
            </div>
          </div>
        </div>
        <n-button size="tiny" block class="mt-2" @click="goToChapter((writerStore.chapters.length || 0) + 1)">+ 新章节</n-button>
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

      <div class="w-60 border-l bg-gray-50 p-2 overflow-y-auto flex-shrink-0 space-y-2">
        <div class="flex gap-1 mb-2">
          <n-button size="tiny" :type="rightPanel === 'tools' ? 'primary' : 'default'" @click="rightPanel = 'tools'" block>AI 工具</n-button>
          <n-button size="tiny" :type="rightPanel === 'memory' ? 'primary' : 'default'" @click="rightPanel = 'memory'" block>上下文</n-button>
        </div>

        <div v-if="rightPanel === 'tools'" class="space-y-2">
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
      :show="showAuditModal"
      :title="pendingFinalizeVersion ? '定稿前一致性审稿报告' : '本章一致性审稿报告'"
      preset="card"
      class="audit-report-modal"
      style="width: min(860px, 92vw); max-height: 86vh;"
      content-style="padding-bottom: 0;"
      @update:show="handleAuditModalVisibleChange"
    >
      <n-spin :show="auditRunning">
        <div v-if="memoryStore.lastAuditResult" class="audit-report-body space-y-4">
          <div
            v-if="pendingFinalizeVersion && blockingAuditIssues.length"
            class="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800"
          >
            定稿前审稿发现严重/主要问题，系统暂未锁定正文。你可以先生成修订版本，或确认仍然定稿；返回修改则不会定稿。
          </div>
          <n-card size="small" title="总体评价">
            <p class="text-sm">{{ memoryStore.lastAuditResult.overallAssessment }}</p>
          </n-card>

          <div v-if="memoryStore.lastAuditResult.issues?.length > 0">
            <h4 class="text-sm font-semibold mb-2">发现 {{ memoryStore.lastAuditResult.issues.length }} 个问题</h4>
            <div class="space-y-2">
              <div
                v-for="(issue, idx) in memoryStore.lastAuditResult.issues"
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
              <div class="text-gray-700 leading-6">{{ memoryStore.lastAuditResult.styleConsistency }}</div>
            </div>
            <div class="rounded border border-gray-100 bg-gray-50 px-3 py-2">
              <div class="text-gray-400 mb-1">角色一致性</div>
              <div class="text-gray-700 leading-6">{{ memoryStore.lastAuditResult.characterConsistency }}</div>
            </div>
          </div>
          <div v-if="memoryStore.lastAuditResult.recommendations?.length">
            <h4 class="text-sm font-semibold mb-1">建议</h4>
            <ul class="text-sm text-gray-600 list-disc pl-4">
              <li v-for="(rec, idx) in memoryStore.lastAuditResult.recommendations" :key="idx">{{ rec }}</li>
            </ul>
          </div>
        </div>
        <n-empty v-if="!auditRunning && !memoryStore.lastAuditResult" description="点击审稿按钮查看报告" size="small" />
      </n-spin>
      <template #footer>
        <div class="flex justify-end gap-2">
          <n-button
            v-if="memoryStore.lastAuditResult?.issues?.length && !currentChapterFinalized"
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
          <n-button
            v-if="memoryStore.lastAuditResult?.issues?.length && currentChapterFinalized"
            size="small"
            disabled
          >
            已定稿，仅可分卷/全局软纠偏
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

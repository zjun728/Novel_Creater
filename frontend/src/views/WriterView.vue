<script setup>
import { ref, onMounted, watch, computed } from 'vue'
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
  NDropdown
} from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { useProjectStore } from '@/stores/projectStore'
import { useWriterStore } from '@/stores/writerStore'
import { useNovelStore } from '@/stores/novelStore'
import { useSeedStore } from '@/stores/seedStore'
import { useMemoryStore } from '@/stores/memoryStore'
import { useSettingStore } from '@/stores/settingStore'
import { useVolumeStore } from '@/stores/volumeStore'
import { useCorrectionTaskStore } from '@/stores/correctionTaskStore'
import { useCompareStore } from '@/stores/compareStore'
import { buildWritingContext } from '@/utils/contextBuilder'
import { downloadFile, exportTxt, exportMarkdown } from '@/utils/export'
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
const showFusionPanel = ref(false)
const showDiffModal = ref(false)
const showBeatPlanModal = ref(false)
const showAuditModal = ref(false)
const auditRunning = ref(false)
const beatPlanText = ref('')
const beatPlanIntent = ref('single')
const streamingContent = ref(false)
const memoryProcessing = ref(false)
const showMemoryResult = ref(false)
const memoryResult = ref(null)
let autoSaveTimer = null

const beatPlanPrimaryText = computed(() =>
  beatPlanIntent.value === 'multi' ? '生成多候选版本' : '开始生成本章'
)

const currentVolume = computed(() =>
  volumeStore.volumes.find(volume =>
    chapterNum.value >= Number(volume.startChapter || 0) &&
    chapterNum.value <= Number(volume.endChapter || 0)
  )
)

onMounted(async () => {
  try {
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
  beatPlanText.value = ''
  await loadChapter()
  router.replace(`/writer/${projectId.value}/${newNum}`)
})

async function loadContextData() {
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
}

async function loadChapter() {
  try {
    await writerStore.loadChapters(projectId.value)
    const chapter = await writerStore.getOrCreateChapter(projectId.value, chapterNum.value)
    await writerStore.loadVersions(projectId.value, chapter.id)

    const draft = await writerStore.loadTempDraft(projectId.value, chapterNum.value)
    if (draft?.content) {
      editorContent.value = draft.content
    } else if (chapter.finalVersionId) {
      const final = writerStore.versions.find(version => version.id === chapter.finalVersionId)
      editorContent.value = final?.content || ''
      writerStore.currentVersion = final || null
    } else if (writerStore.versions.length > 0) {
      writerStore.currentVersion = writerStore.versions[0]
      editorContent.value = writerStore.versions[0].content
    } else {
      editorContent.value = ''
      writerStore.currentVersion = null
    }
  } catch (e) {
    message.error('加载章节失败：' + e.message)
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
  const { context } = buildWritingContext(
    novelStore,
    chapterNum.value,
    undefined,
    settingStore,
    volumeStore,
    correctionTaskStore
  )
  const seedContext = buildSeedContext(getSelectedSeed())
  if (seedContext) {
    context.seed = seedContext
    if (chapterNum.value === 1 && seedContext.openingHook) {
      context.openingAnchor = seedContext.openingHook
    }
  }
  context.sequenceRules = buildSequenceRules()
  return context
}

function buildPlanningContext() {
  const context = buildBaseContext()
  const draft = editorContent.value?.trim()
  if (draft) context.currentDraft = draft.length > 3000 ? draft.slice(-3000) : draft
  return context
}

async function ensureBeatPlan(force = false) {
  const existingPlan = beatPlanText.value.trim()
  if (existingPlan && !force) return existingPlan
  beatPlanText.value = await writerStore.generateChapterBeatPlan(projectId.value, chapterNum.value, buildBaseContext())
  return beatPlanText.value
}

async function handlePlanBeats() {
  try {
    beatPlanIntent.value = 'single'
    await ensureBeatPlan(false)
    showBeatPlanModal.value = true
    message.success('已打开本章小纲，请审阅后再生成正文')
  } catch (e) {
    message.error('小纲生成失败：' + e.message)
  }
}

async function handleRefreshBeatPlan() {
  try {
    await ensureBeatPlan(true)
    showBeatPlanModal.value = true
    message.success('本章小纲已重新生成')
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
    await ensureBeatPlan(false)
    showBeatPlanModal.value = true
    message.success('请先审阅本章小纲，确认后再生成正文')
  } catch (e) {
    message.error('小纲准备失败：' + e.message)
  }
}

async function generateChapterFromPlan(confirmedPlan) {
  try {
    streamingContent.value = true
    editorContent.value = ''
    const version = await writerStore.generateChapter(
      projectId.value,
      chapterNum.value,
      { ...buildBaseContext(), beatPlan: confirmedPlan },
      null,
      fullContent => {
        editorContent.value = fullContent
      }
    )
    writerStore.currentVersion = version
    message.success('已按确认小纲生成章节')
  } catch (e) {
    message.error('按小纲生成失败：' + e.message)
  } finally {
    streamingContent.value = false
  }
}

async function generateMultiVariantsFromPlan(confirmedPlan) {
  try {
    const versions = await writerStore.generateMultiVariants(projectId.value, chapterNum.value, {
      ...buildBaseContext(),
      beatPlan: confirmedPlan
    })
    message.success(`基于小纲生成了 ${versions.length} 个候选版本`)
    if (versions.length > 0) {
      writerStore.currentVersion = versions[0]
      editorContent.value = versions[0].content
    }
  } catch (e) {
    message.error('多候选版本生成失败：' + e.message)
  }
}

async function handleGenerateFromBeatPlan() {
  const confirmedPlan = beatPlanText.value.trim()
  if (!confirmedPlan) {
    message.warning('请先生成或填写本章小纲')
    return
  }
  showBeatPlanModal.value = false
  if (beatPlanIntent.value === 'multi') {
    await generateMultiVariantsFromPlan(confirmedPlan)
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
    await ensureBeatPlan(false)
    showBeatPlanModal.value = true
    message.success('请先审阅本章小纲，确认后再生成多候选版本')
  } catch (e) {
    message.error('小纲准备失败：' + e.message)
  }
}

async function handleContinue() {
  try {
    const result = await writerStore.continueWriting(editorContent.value, '自然续写，推进情节', null, buildPlanningContext())
    const content = typeof result === 'string'
      ? result
      : result?.content || result?.choices?.[0]?.message?.content || ''
    editorContent.value = editorContent.value + '\n\n' + content
    message.success('续写完成')
  } catch (e) {
    message.error('续写失败：' + e.message)
  }
}

async function handleExpand() {
  if (!selectedText.value) {
    message.warning('请先选中要扩写的文字')
    return
  }
  try {
    const result = await writerStore.expandText(selectedText.value, buildPlanningContext())
    editorContent.value = editorContent.value.replace(selectedText.value, result)
    message.success('扩写完成')
  } catch (e) {
    message.error('扩写失败：' + e.message)
  }
}

async function handleCompress() {
  if (!selectedText.value) {
    message.warning('请先选中要压缩的文字')
    return
  }
  try {
    const result = await writerStore.compressText(selectedText.value)
    editorContent.value = editorContent.value.replace(selectedText.value, result)
    message.success('压缩完成')
  } catch (e) {
    message.error('压缩失败：' + e.message)
  }
}

async function handleRewrite(mode) {
  if (!selectedText.value) {
    message.warning('请先选中要改写的文字')
    return
  }
  try {
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
  }
}

function handleCompare() {
  showCompareModal.value = true
}

function handleOpenFusion() {
  showFusionPanel.value = true
}

function handleOpenDiff() {
  if (compareStore.comparisonVersions.length < 2) {
    message.warning('请先至少加入两个版本到对比池')
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

function loadVersion(version) {
  writerStore.currentVersion = version
  editorContent.value = version.content
}

async function handleFinalize(version) {
  await writerStore.finalizeVersion(version)
  await writerStore.clearTempDraft(projectId.value, chapterNum.value)
  message.success('已定稿，正在提取记忆...')

  memoryProcessing.value = true
  try {
    const results = await memoryStore.processChapterFinalization(projectId.value, version.content, chapterNum.value)
    memoryResult.value = results
    showMemoryResult.value = true
    await loadContextData()

    const factCount = results.facts?.length || 0
    const issueCount = results.audit?.issues?.length || 0
    message.success(`记忆提取完成：提取 ${factCount} 条事实${issueCount ? `，发现 ${issueCount} 个问题` : ''}`)
  } catch (e) {
    message.warning('记忆提取部分失败：' + e.message)
  } finally {
    memoryProcessing.value = false
  }
}

async function handleDeleteVersion(version) {
  await writerStore.deleteVersion(version.id)
  if (writerStore.currentVersion?.id === version.id) {
    writerStore.currentVersion = null
    editorContent.value = ''
  }
  message.success('版本已删除')
}

async function handleManualSave() {
  await writerStore.saveTempDraft(projectId.value, chapterNum.value, editorContent.value)
  message.success('草稿已保存')
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
</script>

<template>
  <div v-if="projectStore.currentProject" class="writer-desk h-full flex flex-col">
    <div class="flex items-center justify-between px-4 py-2 border-b bg-white">
      <div class="flex items-center gap-3">
        <h2 class="text-lg font-bold text-gray-800">{{ projectStore.currentProject.title }}</h2>
        <n-tag size="small">第 {{ chapterNum }} 章</n-tag>
        <n-tag v-if="currentVolume" size="small" type="info" :bordered="false">
          {{ currentVolume.title || `第 ${currentVolume.volumeNum} 卷` }}
        </n-tag>
        <n-tag v-if="beatPlanText" size="small" type="success" :bordered="false">已有小纲</n-tag>
        <n-spin v-if="memoryProcessing" size="tiny" />
      </div>
      <n-space>
        <n-button size="small" @click="handleAudit" :loading="auditRunning">审稿</n-button>
        <n-button size="small" @click="currentView = currentView === 'writer' ? 'bible' : 'writer'">
          {{ currentView === 'writer' ? '圣经' : '写字台' }}
        </n-button>
        <n-button size="small" @click="currentView = currentView === 'memory' ? 'writer' : 'memory'">
          {{ currentView === 'memory' ? '写字台' : '记忆' }}
        </n-button>
        <n-dropdown trigger="click" :options="exportOptions" @select="handleExportSelect">
          <n-button size="small">导出</n-button>
        </n-dropdown>
        <n-button size="small" type="primary" @click="handleManualSave">保存草稿</n-button>
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
            <div class="flex gap-1 mt-0.5">
              <n-tag v-if="ch.status === 'final'" type="success" size="tiny" :bordered="false">定</n-tag>
              <span v-if="ch.summary" class="text-gray-400 truncate block text-[10px]">{{ ch.summary }}</span>
            </div>
          </div>
        </div>
        <n-button size="tiny" block class="mt-2" @click="goToChapter((writerStore.chapters.length || 0) + 1)">+ 新章节</n-button>
      </div>

      <div class="flex-1 flex flex-col overflow-hidden">
        <div class="flex-1 p-4 overflow-y-auto">
          <n-input
            v-model:value="editorContent"
            type="textarea"
            placeholder="在此输入正文，或使用右侧 AI 工具生成..."
            :rows="0"
            class="writer-editor h-full"
            :input-props="{ style: 'min-height: 100%' }"
            @update:value="handleContentChange"
            @select="handleSelectionChange"
            @blur="handleSelectionChange"
          />
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
          <AIActionPanel
            :generating="writerStore.generating"
            :planning="writerStore.beatPlanning"
            :has-beat-plan="!!beatPlanText"
            :has-content="!!editorContent"
            :has-selection="hasSelection"
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
            :comparison-version-ids="compareStore.comparisonVersions.map(version => version.id)"
            @load="loadVersion"
            @delete="handleDeleteVersion"
            @finalize="handleFinalize"
            @compare="handleToggleVersionCompare"
          />

          <CompareInline @load-version="loadVersion" />

          <div v-if="compareStore.comparisonVersions.length >= 2" class="pt-1">
            <div class="grid grid-cols-1 gap-1">
              <n-button size="tiny" type="info" secondary block @click="handleOpenDiff">
                差异对比
              </n-button>
              <n-button size="tiny" type="warning" block @click="handleOpenFusion">
                融合多模型版本
              </n-button>
            </div>
          </div>
        </div>

        <div v-if="rightPanel === 'memory'" class="space-y-2">
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

    <n-modal v-model:show="showBeatPlanModal" title="本章小纲确认" preset="card" style="width: 720px; max-height: 85vh;">
      <div class="space-y-3">
        <div class="rounded border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs leading-6 text-emerald-800">
          先确认这一章的剧情节拍，再生成正文。你可以直接修改小纲，AI 会按确认后的顺序展开，同时保留场景、对白和细节的发挥空间。
        </div>

        <n-input
          v-model:value="beatPlanText"
          type="textarea"
          placeholder="这里会显示 AI 生成的本章小纲，也可以手动补充或重排节拍..."
          :autosize="{ minRows: 16, maxRows: 24 }"
        />

        <div class="flex items-center justify-end">
          <n-space>
            <n-button size="small" :loading="writerStore.beatPlanning" :disabled="streamingContent" @click="handleRefreshBeatPlan">
              重新生成小纲
            </n-button>
            <n-button size="small" type="primary" :loading="streamingContent" :disabled="!beatPlanText.trim() || writerStore.beatPlanning" @click="handleGenerateFromBeatPlan">
              {{ beatPlanPrimaryText }}
            </n-button>
          </n-space>
        </div>
      </div>
    </n-modal>

    <n-modal v-model:show="showAuditModal" title="一致性审稿报告" preset="card" style="width: 700px; max-height: 80vh;">
      <n-spin :show="auditRunning">
        <div v-if="memoryStore.lastAuditResult" class="space-y-4">
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
                    {{ issue.severity }}
                  </n-tag>
                  <n-tag size="tiny" :bordered="false">{{ issue.type }}</n-tag>
                </div>
                <p class="text-gray-800 font-medium">{{ issue.description }}</p>
                <p v-if="issue.location" class="text-gray-400 text-xs mt-1">位置：{{ issue.location }}</p>
                <p v-if="issue.suggestion" class="text-blue-600 text-xs mt-1">建议：{{ issue.suggestion }}</p>
                <p v-if="issue.reason" class="text-gray-500 text-xs mt-1">原因：{{ issue.reason }}</p>
              </div>
            </div>
          </div>
          <n-empty v-else description="未发现明显问题" size="small" />

          <div class="grid grid-cols-2 gap-3 text-sm">
            <div>
              <span class="text-gray-400">风格一致性：</span>
              {{ memoryStore.lastAuditResult.styleConsistency }}
            </div>
            <div>
              <span class="text-gray-400">角色一致性：</span>
              {{ memoryStore.lastAuditResult.characterConsistency }}
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
      :versions="compareStore.comparisonVersions"
      @load-version="loadVersion"
      @close="showDiffModal = false"
    />
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
</style>

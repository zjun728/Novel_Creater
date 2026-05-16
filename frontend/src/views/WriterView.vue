<script setup>
import { ref, onMounted, watch, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NCard, NEmpty, NSpace, NInput, NSelect, NTag, NModal, NPopconfirm, NSpin, NDivider, NDropdown, useMessage } from 'naive-ui'
import { useProjectStore } from '@/stores/projectStore'
import { useWriterStore } from '@/stores/writerStore'
import { useNovelStore } from '@/stores/novelStore'
import { useSeedStore } from '@/stores/seedStore'
import { useMemoryStore } from '@/stores/memoryStore'
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
import { useCompareStore } from '@/stores/compareStore'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const writerStore = useWriterStore()
const novelStore = useNovelStore()
const seedStore = useSeedStore()
const memoryStore = useMemoryStore()
const compareStore = useCompareStore()
const message = useMessage()

const projectId = computed(() => route.params.projectId)
const chapterNum = ref(Number(route.params.chapterNum) || 1)
const editorContent = ref('')
const selectedText = ref('')
const hasSelection = ref(false)
const currentView = ref('writer') // 'writer' | 'bible' | 'memory'
const rightPanel = ref('tools') // 'tools' | 'memory'

const exportOptions = [
  { label: '导出 TXT', key: 'txt' },
  { label: '导出 MD', key: 'md' }
]
const showStyleModal = ref(false)
const showPacingModal = ref(false)
const showCompareModal = ref(false)
const showFusionPanel = ref(false)
const showAuditModal = ref(false)
const auditRunning = ref(false)

// Memory processing
const memoryProcessing = ref(false)
const showMemoryResult = ref(false)
const memoryResult = ref(null)

// 自动保存
let autoSaveTimer = null

onMounted(async () => {
  try {
    if (!projectStore.currentProject || projectStore.currentProject.id !== projectId.value) {
      await projectStore.openProject(projectId.value)
    }
    await loadChapter()
    await loadContextData()
  } catch (e) {
    message.error('初始化写作台失败：' + e.message)
  }
})

watch(chapterNum, async (newNum) => {
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
      const versions = writerStore.versions
      const final = versions.find(v => v.id === chapter.finalVersionId)
      if (final) {
        editorContent.value = final.content
        writerStore.currentVersion = final
      }
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
  if (textarea) {
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    selectedText.value = editorContent.value.substring(start, end)
    hasSelection.value = start !== end
  }
}

function handleContentChange() {
  clearTimeout(autoSaveTimer)
  autoSaveTimer = setTimeout(async () => {
    await writerStore.saveTempDraft(projectId.value, chapterNum.value, editorContent.value)
  }, 2000)
}

// === AI 操作 ===
const streamingContent = ref(false)

async function handleGenerate() {
  try {
    streamingContent.value = true
    editorContent.value = ''
    const { context } = buildWritingContext(novelStore, chapterNum.value)
    const version = await writerStore.generateChapter(
      projectId.value,
      chapterNum.value,
      context,
      null,
      (fullContent, delta) => {
        // 流式回调：实时更新编辑器
        editorContent.value = fullContent
      }
    )
    writerStore.currentVersion = version
    streamingContent.value = false
    message.success('章节生成成功')
  } catch (e) {
    streamingContent.value = false
    message.error('生成失败：' + e.message)
  }
}

async function handleMultiVariant() {
  try {
    const { context } = buildWritingContext(novelStore, chapterNum.value)
    const versions = await writerStore.generateMultiVariants(projectId.value, chapterNum.value, context)
    message.success(`生成了 ${versions.length} 个候选版本`)
    if (versions.length > 0) {
      writerStore.currentVersion = versions[0]
      editorContent.value = versions[0].content
    }
  } catch (e) {
    message.error('生成失败：' + e.message)
  }
}

async function handleContinue() {
  try {
    const result = await writerStore.continueWriting(editorContent.value, '自然续写，推进情节')
    let content = ''
    if (typeof result === 'string') content = result
    else if (result?.content) content = result.content
    else if (result?.choices?.[0]?.message?.content) content = result.choices[0].message.content
    editorContent.value = editorContent.value + '\n\n' + content
    message.success('续写完成')
  } catch (e) {
    message.error('续写失败：' + e.message)
  }
}

async function handleExpand() {
  if (!selectedText.value) { message.warning('请先选中要扩写的文字'); return }
  try {
    const result = await writerStore.expandText(selectedText.value, {})
    editorContent.value = editorContent.value.replace(selectedText.value, result)
    message.success('扩写完成')
  } catch (e) {
    message.error('扩写失败：' + e.message)
  }
}

async function handleCompress() {
  if (!selectedText.value) { message.warning('请先选中要压缩的文字'); return }
  try {
    const result = await writerStore.compressText(selectedText.value)
    editorContent.value = editorContent.value.replace(selectedText.value, result)
    message.success('压缩完成')
  } catch (e) {
    message.error('压缩失败：' + e.message)
  }
}

async function handleRewrite(mode) {
  if (!selectedText.value) { message.warning('请先选中要改写的文字'); return }
  try {
    const context = { styleBible: novelStore.bible?.styleBible, characters: novelStore.characters }
    const result = await writerStore.rewriteSelection(selectedText.value, mode, context)
    editorContent.value = editorContent.value.replace(selectedText.value, result)
    selectedText.value = result
    message.success('改写完成')
  } catch (e) {
    message.error('改写失败：' + e.message)
  }
}

// === 多模型对比 ===
function handleCompare() {
  showCompareModal.value = true
}

function handleOpenFusion() {
  showFusionPanel.value = true
}

// === 风格分析 ===
async function handleStyleAnalysis() {
  if (!editorContent.value) { message.warning('请先生成或输入正文'); return }
  showStyleModal.value = true
  try {
    await memoryStore.analyzeStyle(projectId.value, editorContent.value, chapterNum.value)
  } catch (e) {
    message.error('风格分析失败：' + e.message)
  }
}

// === 节奏分析 ===
async function handlePacingAnalysis() {
  if (!editorContent.value) { message.warning('请先生成或输入正文'); return }
  showPacingModal.value = true
  try {
    await memoryStore.analyzePacing(projectId.value, editorContent.value, chapterNum.value)
  } catch (e) {
    message.error('节奏分析失败：' + e.message)
  }
}

// === 一致性审稿 ===
async function handleAudit() {
  if (!editorContent.value) { message.warning('请先生成或输入正文'); return }
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

// === 版本操作 ===
function loadVersion(version) {
  writerStore.currentVersion = version
  editorContent.value = version.content
}

async function handleFinalize(version) {
  await writerStore.finalizeVersion(version)
  await writerStore.clearTempDraft(projectId.value, chapterNum.value)
  message.success('已定稿，正在提取记忆...')

  // 触发记忆提取管道
  memoryProcessing.value = true
  try {
    const results = await memoryStore.processChapterFinalization(
      projectId.value,
      version.content,
      chapterNum.value
    )
    memoryResult.value = results
    showMemoryResult.value = true
    // 刷新数据
    await loadContextData()

    const factCount = results.facts?.length || 0
    const hasIssues = results.audit?.issues?.length > 0
    message.success(
      `记忆提取完成：提取 ${factCount} 条事实` +
      (hasIssues ? `，发现 ${results.audit.issues.length} 个问题` : '')
    )
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

// === 导出 ===
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
  <div class="writer-desk h-full flex flex-col" v-if="projectStore.currentProject">
    <!-- 顶部工具栏 -->
    <div class="flex items-center justify-between px-4 py-2 border-b bg-white">
      <div class="flex items-center gap-3">
        <h2 class="text-lg font-bold text-gray-800">
          {{ projectStore.currentProject.title }}
        </h2>
        <n-tag size="small">第 {{ chapterNum }} 章</n-tag>
        <n-spin v-if="memoryProcessing" size="tiny" />
      </div>
      <n-space>
        <n-button size="small" @click="handleAudit" :loading="auditRunning">🔍 审稿</n-button>
        <n-button size="small" @click="currentView = currentView === 'writer' ? 'bible' : 'writer'">
          {{ currentView === 'writer' ? '圣经' : '写作台' }}
        </n-button>
        <n-button size="small" @click="currentView = currentView === 'memory' ? 'writer' : 'memory'">
          {{ currentView === 'memory' ? '写作台' : '记忆' }}
        </n-button>
        <NDropdown trigger="click" :options="exportOptions" @select="handleExportSelect">
          <n-button size="small">导出</n-button>
        </NDropdown>
        <n-button size="small" type="primary" @click="handleManualSave">保存草稿</n-button>
      </n-space>
    </div>

    <!-- 主内容区：写作台 -->
    <div class="flex-1 flex overflow-hidden" v-if="currentView === 'writer'">
      <!-- 左侧：章节列表 -->
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
            <span class="truncate block">第{{ ch.chapterNum }}章</span>
            <div class="flex gap-1 mt-0.5">
              <n-tag v-if="ch.status === 'final'" type="success" size="tiny" :bordered="false">定</n-tag>
              <span v-if="ch.summary" class="text-gray-400 truncate block text-[10px]">{{ ch.summary }}</span>
            </div>
          </div>
        </div>
        <n-button size="tiny" block class="mt-2" @click="goToChapter((writerStore.chapters.length || 0) + 1)">+ 新章节</n-button>
      </div>

      <!-- 中间：编辑器 -->
      <div class="flex-1 flex flex-col overflow-hidden">
        <div class="flex-1 p-4 overflow-y-auto">
          <n-input
            v-model:value="editorContent"
            type="textarea"
            placeholder="在此输入正文，或使用右侧 AI 操作生成..."
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
            <span v-if="streamingContent" class="text-green-500 animate-pulse">● 流式生成中...</span>
          </div>
          <span v-if="hasSelection" class="text-blue-500">已选中 {{ selectedText?.length || 0 }} 字符</span>
          <span v-if="writerStore.tempDraft?.savedAt">
            上次自动保存：{{ new Date(writerStore.tempDraft.savedAt).toLocaleTimeString('zh-CN') }}
          </span>
        </div>
      </div>

      <!-- 右侧：工具面板 -->
      <div class="w-60 border-l bg-gray-50 p-2 overflow-y-auto flex-shrink-0 space-y-2">
        <div class="flex gap-1 mb-2">
          <n-button size="tiny" :type="rightPanel === 'tools' ? 'primary' : 'default'" @click="rightPanel = 'tools'" block>AI 工具</n-button>
          <n-button size="tiny" :type="rightPanel === 'memory' ? 'primary' : 'default'" @click="rightPanel = 'memory'" block>上下文</n-button>
        </div>

        <div v-if="rightPanel === 'tools'" class="space-y-2">
          <AIActionPanel
            :generating="writerStore.generating"
            :has-content="!!editorContent"
            :has-selection="hasSelection"
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
            @load="loadVersion"
            @delete="handleDeleteVersion"
            @finalize="handleFinalize"
          />

          <CompareInline @load-version="loadVersion" />

          <div v-if="compareStore.comparisonVersions.length >= 2" class="pt-1">
            <n-button size="tiny" type="warning" block @click="handleOpenFusion">
              融合多模型版本
            </n-button>
          </div>
        </div>

        <div v-if="rightPanel === 'memory'" class="space-y-2">
          <ContextMemoryPanel />
          <n-divider style="margin: 8px 0" />
          <CanonReviewPanel />
        </div>
      </div>
    </div>

    <!-- 创作圣经视图 -->
    <div class="flex-1 overflow-y-auto p-4" v-if="currentView === 'bible'">
      <CreativeBible :project-id="projectId" />
    </div>

    <!-- 记忆管理视图 -->
    <div class="flex-1 overflow-y-auto p-4" v-if="currentView === 'memory'">
      <div class="max-w-3xl mx-auto space-y-4">
        <CanonReviewPanel />
        <n-card title="角色与伏笔" size="small">
          <ContextMemoryPanel />
        </n-card>
      </div>
    </div>

    <!-- 审稿结果弹窗 -->
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

    <!-- 风格分析弹窗 -->
    <StyleAnalysisPanel
      v-if="showStyleModal"
      :project-id="projectId"
      @close="showStyleModal = false"
    />

    <!-- 节奏分析弹窗 -->
    <n-modal v-model:show="showPacingModal" title="章节节奏分析" preset="card" style="width: 640px; max-height: 80vh;">
      <n-spin :show="memoryStore.pacingAnalyzing">
        <PacingChart v-if="memoryStore.lastPacingAnalysis" :pacing="memoryStore.lastPacingAnalysis" />
        <n-empty v-if="!memoryStore.pacingAnalyzing && !memoryStore.lastPacingAnalysis" description="暂无分析结果" size="small" />
      </n-spin>
    </n-modal>

    <!-- 多模型对比弹窗 -->
    <CompareModal
      v-if="showCompareModal"
      :project-id="projectId"
      :chapter-num="chapterNum"
      @close="showCompareModal = false"
    />

    <!-- 多模型融合弹窗 -->
    <FusionPanel
      v-if="showFusionPanel"
      :project-id="projectId"
      :chapter-num="chapterNum"
      @close="showFusionPanel = false"
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

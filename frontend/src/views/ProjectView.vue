<script setup>
import { onMounted, computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NEmpty,
  NSpace,
  NTag,
  NTabs,
  NTabPane,
  NDropdown,
  NModal,
  NInputNumber,
  NRadioGroup,
  NRadioButton,
  NForm,
  NFormItem,
  NInput
} from 'naive-ui'
import { api } from '@/api/db/client'
import { useAppMessage } from '@/composables/useAppMessage'
import { downloadFile, exportTxt, exportMarkdown, exportProjectBundle } from '@/utils/export'
import { useProjectStore } from '@/stores/projectStore'
import { useWriterStore } from '@/stores/writerStore'
import { useSeedStore } from '@/stores/seedStore'
import { useNovelStore } from '@/stores/novelStore'
import { useSettingStore } from '@/stores/settingStore'
import { useVolumeStore } from '@/stores/volumeStore'
import { useCorrectionTaskStore } from '@/stores/correctionTaskStore'
import SeedWorkbench from '@/components/seed/SeedWorkbench.vue'
import CreativeBible from '@/components/bible/CreativeBible.vue'
import MarketRadar from '@/components/market/MarketRadar.vue'
import CharacterArcView from '@/components/bible/CharacterArcView.vue'
import PlotThreadBoard from '@/components/bible/PlotThreadBoard.vue'
import SettingLibrary from '@/components/settings-library/SettingLibrary.vue'
import VolumePlanner from '@/components/chapter/VolumePlanner.vue'
import CorrectionTaskBoard from '@/components/correction/CorrectionTaskBoard.vue'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const writerStore = useWriterStore()
const seedStore = useSeedStore()
const novelStore = useNovelStore()
const settingStore = useSettingStore()
const volumeStore = useVolumeStore()
const correctionTaskStore = useCorrectionTaskStore()
const message = useAppMessage()

const project = computed(() => projectStore.currentProject)
const activeTab = ref('market')

const showProjectEditModal = ref(false)
const editingProject = ref(false)
const loadingProjectEditState = ref(false)
const projectEditContentState = ref(null)
const projectEditForm = ref({
  title: '',
  genre: '',
  description: '',
  targetWords: 100000,
  targetChapters: 100
})

const showGlobalAuditModal = ref(false)
const showGlobalAuditConfigModal = ref(false)
const activeGlobalAudit = ref(null)
const globalAuditScope = ref('all')
const globalAuditStartChapter = ref(1)
const globalAuditEndChapter = ref(null)

const selectedSeed = computed(() => seedStore.seeds.find(seed => seed.status === 'selected'))
const bibleReady = computed(() => Boolean(novelStore.bible?.premise || novelStore.bible?.worldRules || novelStore.bible?.styleBible))
const settingsReady = computed(() => settingStore.entities.length > 0)
const pendingSettingChanges = computed(() =>
  settingStore.changeEvents.filter(event => event.status === 'pending_review').length
)

const projectPlanLocked = computed(() => {
  if (loadingProjectEditState.value) return true
  return Boolean(
    (projectEditContentState.value?.chaptersCount || 0) > 0 ||
    (projectEditContentState.value?.chapterVersions || 0) > 0
  )
})

const projectPlanLockReason = computed(() => {
  if (loadingProjectEditState.value) return '正在检查项目章节状态，目标规划字段暂时锁定。'
  const chapters = projectEditContentState.value?.chaptersCount || 0
  const versions = projectEditContentState.value?.chapterVersions || 0
  if (chapters > 0 || versions > 0) {
    return `当前项目已有 ${chapters} 个章节、${versions} 个正文/候选版本。目标字数和目标章节数会影响后续章节规划与进度判断，已锁定不可编辑。`
  }
  return ''
})

const seedStepState = computed(() => {
  if (selectedSeed.value) return { done: true, statusLabel: '已就绪', statusType: 'success' }
  if (seedStore.seeds.length) return { done: false, statusLabel: '待确认', statusType: 'warning' }
  return { done: false, statusLabel: '待完善', statusType: 'default' }
})

const bibleStepState = computed(() => {
  if (bibleReady.value) return { done: true, statusLabel: '已就绪', statusType: 'success' }
  return { done: false, statusLabel: '待完善', statusType: 'default' }
})

const settingsStepState = computed(() => {
  if (pendingSettingChanges.value) return { done: false, statusLabel: '有待确认', statusType: 'warning' }
  if (settingsReady.value) return { done: true, statusLabel: '已就绪', statusType: 'success' }
  return { done: false, statusLabel: '待完善', statusType: 'default' }
})

const chapterStepState = computed(() => {
  if (writerStore.chapters.some(ch => Number(ch.wordCount || 0) > 0 || ch.finalVersionId || ch.status === 'final')) {
    return { done: true, statusLabel: '已开始', statusType: 'info' }
  }
  if (writerStore.chapters.length > 0) return { done: false, statusLabel: '待写作', statusType: 'warning' }
  return { done: false, statusLabel: '待完善', statusType: 'default' }
})

const correctionStepState = computed(() => {
  if (correctionTaskStore.activeTasks.length) return { done: false, statusLabel: '待处理', statusType: 'warning' }
  if (correctionTaskStore.tasks.length > 0) return { done: true, statusLabel: '已处理', statusType: 'success' }
  return { done: false, statusLabel: '待审稿', statusType: 'default' }
})

const workflowSteps = computed(() => [
  {
    key: 'market',
    title: '1 选题',
    desc: '确定题材赛道、卖点和读者预期',
    done: Boolean(project.value?.genre),
    statusLabel: project.value?.genre ? '已开始' : '待完善',
    statusType: project.value?.genre ? 'info' : 'default'
  },
  {
    key: 'seed',
    title: '2 种子',
    desc: '沉淀主角、冲突、开局钩子',
    ...seedStepState.value
  },
  {
    key: 'bible',
    title: '3 圣经',
    desc: '确认作品蓝图和长期写作原则',
    ...bibleStepState.value
  },
  {
    key: 'settingsLibrary',
    title: '4 设定库',
    desc: '记录人物、势力、地点与规则',
    ...settingsStepState.value
  },
  {
    key: 'chapters',
    title: '5 章节',
    desc: '进入写字台按小纲生成正文',
    ...chapterStepState.value
  },
  {
    key: 'corrections',
    title: '6 纠偏',
    desc: '把审稿问题转成可执行任务',
    ...correctionStepState.value
  }
])

onMounted(async () => {
  const id = route.params.id
  try {
    if (!project.value || project.value.id !== id) {
      await projectStore.openProject(id)
    }
    if (project.value) {
      await Promise.all([
        writerStore.loadChapters(id),
        seedStore.loadSeeds(id),
        novelStore.loadBible(id),
        novelStore.loadCharacters(id),
        novelStore.loadPlotThreads(id),
        novelStore.loadCanonFacts(id),
        novelStore.loadGlobalAudits(id),
        correctionTaskStore.loadTasks(id),
        settingStore.loadEntities(id),
        settingStore.loadRelations(id),
        settingStore.loadChangeEvents(id),
        volumeStore.loadVolumes(id)
      ])
    }
  } catch (e) {
    message.error('加载项目数据失败：' + e.message)
  }
})

const exportOptions = [
  { label: '导出全部 TXT', key: 'txt' },
  { label: '导出全部 Markdown', key: 'md' },
  { label: '导出项目包 JSON', key: 'bundle' }
]

const chapterStatusLabels = {
  planned: '规划中',
  drafting: '草稿中',
  reviewing: '审稿中',
  final: '已定稿'
}

const chapterStatusColors = {
  planned: 'default',
  drafting: 'info',
  reviewing: 'warning',
  final: 'success'
}

async function handleExportSelect(key) {
  const title = project.value?.title || 'novel'
  try {
    if (key === 'txt') {
      const content = await exportTxt(project.value.id)
      downloadFile(content, `${title}.txt`)
      message.success('TXT 导出成功')
    } else if (key === 'md') {
      const content = await exportMarkdown(project.value.id)
      downloadFile(content, `${title}.md`, 'text/markdown')
      message.success('Markdown 导出成功')
    } else if (key === 'bundle') {
      const content = await exportProjectBundle(project.value.id)
      downloadFile(content, `${title}_bundle.json`, 'application/json')
      message.success('项目包导出成功')
    }
  } catch (e) {
    message.error('导出失败：' + e.message)
  }
}

function goToWriter(chapterNum) {
  if (project.value) {
    router.push(`/writer/${project.value.id}/${chapterNum || 1}`)
  }
}

async function openProjectEditModal() {
  if (!project.value) return
  projectEditForm.value = {
    title: project.value.title || '',
    genre: project.value.genre || '',
    description: project.value.description || '',
    targetWords: project.value.targetWords || 100000,
    targetChapters: project.value.targetChapters || 100
  }
  projectEditContentState.value = null
  showProjectEditModal.value = true
  loadingProjectEditState.value = true
  try {
    projectEditContentState.value = await api.projects.contentState(project.value.id)
  } catch (e) {
    projectEditContentState.value = { chaptersCount: 1, chapterVersions: 1 }
    message.warning('无法检查章节状态，已临时锁定目标字数和目标章节数。')
  } finally {
    loadingProjectEditState.value = false
  }
}

async function saveProjectEdit() {
  if (!project.value) return
  if (!projectEditForm.value.title.trim()) {
    message.warning('请输入项目名称')
    return
  }
  const payload = {
    ...project.value,
    title: projectEditForm.value.title.trim(),
    genre: projectEditForm.value.genre || '',
    description: projectEditForm.value.description || '',
    targetWords: projectPlanLocked.value
      ? project.value.targetWords
      : Number(projectEditForm.value.targetWords || project.value.targetWords || 100000),
    targetChapters: projectPlanLocked.value
      ? project.value.targetChapters
      : Number(projectEditForm.value.targetChapters || project.value.targetChapters || 100)
  }

  editingProject.value = true
  try {
    await projectStore.updateProject(payload)
    message.success('项目信息已更新')
    showProjectEditModal.value = false
  } catch (e) {
    message.error('更新项目信息失败：' + e.message)
  } finally {
    editingProject.value = false
  }
}

function onSeedSelected() {
  // 种子选中后，圣经页会读取当前 selected seed。
}

function handleCorrectionNavigate({ targetTab, chapterNum, task }) {
  if (targetTab === 'writer') {
    goToWriter(chapterNum || project.value?.currentChapterNum || 1)
    return
  }

  const tabMap = {
    bible: 'bible',
    chapters: 'chapters',
    corrections: 'corrections',
    plotThreads: 'plotThreads',
    settingsLibrary: 'settingsLibrary'
  }
  activeTab.value = tabMap[targetTab] || 'corrections'
  message.success(`已定位到「${task?.title || '纠偏任务'}」对应模块`)
}

async function handleGlobalAudit() {
  try {
    const scope = buildGlobalAuditScope()
    const report = await novelStore.generateGlobalAudit(project.value, buildGlobalAuditContext(scope))
    activeGlobalAudit.value = report
    showGlobalAuditModal.value = true
    showGlobalAuditConfigModal.value = false
    message.success('审稿报告已生成')
  } catch (e) {
    message.error('审稿失败：' + e.message)
  }
}

function openGlobalAuditConfig() {
  const chapterNums = writerStore.chapters.map(ch => Number(ch.chapterNum)).filter(Boolean)
  if (chapterNums.length) {
    globalAuditStartChapter.value = Math.min(...chapterNums)
    globalAuditEndChapter.value = Math.max(...chapterNums)
  } else {
    globalAuditStartChapter.value = 1
    globalAuditEndChapter.value = project.value?.currentChapterNum || 1
  }
  showGlobalAuditConfigModal.value = true
}

function buildGlobalAuditScope() {
  if (globalAuditScope.value !== 'range') {
    return {
      mode: 'all',
      label: '全书',
      chapters: writerStore.chapters
    }
  }

  const start = Number(globalAuditStartChapter.value || 1)
  const end = Number(globalAuditEndChapter.value || start)
  const normalizedStart = Math.min(start, end)
  const normalizedEnd = Math.max(start, end)
  return {
    mode: 'range',
    startChapter: normalizedStart,
    endChapter: normalizedEnd,
    label: `第 ${normalizedStart}-${normalizedEnd} 章`,
    chapters: writerStore.chapters.filter(ch => {
      const chapterNum = Number(ch.chapterNum || 0)
      return chapterNum >= normalizedStart && chapterNum <= normalizedEnd
    })
  }
}

function viewGlobalAudit(report) {
  activeGlobalAudit.value = report
  showGlobalAuditModal.value = true
}

async function handleCreateCorrectionTasksFromGlobalAudit() {
  const report = activeGlobalAudit.value
  if (!report) return
  const payloads = correctionTaskStore.buildTasksFromGlobalAudit(report)
  if (!payloads.length) {
    message.warning('当前审稿报告没有可转化的问题项')
    return
  }
  try {
    const created = await correctionTaskStore.bulkCreate(project.value.id, payloads)
    message.success(`已生成 ${created.length} 条纠偏任务`)
  } catch (e) {
    message.error('生成纠偏任务失败：' + e.message)
  }
}

function buildGlobalAuditContext(scope = buildGlobalAuditScope()) {
  const rangeFilter = item => {
    if (scope.mode !== 'range') return true
    const chapterNum = Number(item?.chapterNum || 0)
    return chapterNum >= scope.startChapter && chapterNum <= scope.endChapter
  }

  return {
    auditScopeLabel: scope.label,
    auditStartChapter: scope.startChapter,
    auditEndChapter: scope.endChapter,
    projectTitle: project.value?.title,
    genre: project.value?.genre,
    description: project.value?.description,
    targetWords: project.value?.targetWords,
    targetChapters: project.value?.targetChapters,
    currentChapterNum: project.value?.currentChapterNum,
    seedSummary: formatSelectedSeed(selectedSeed.value),
    bibleSummary: formatBible(novelStore.bible),
    volumeSummary: formatVolumes(volumeStore.volumes),
    chapterSummary: formatChapters(scope.chapters),
    settingSummary: formatSettings(settingStore.entities, settingStore.relations),
    factSummary: formatFacts(novelStore.canonFacts.filter(rangeFilter)),
    threadSummary: formatThreads(novelStore.plotThreads),
    settingChangeSummary: formatSettingChanges(settingStore.changeEvents.filter(rangeFilter))
  }
}

function formatSelectedSeed(seed) {
  if (!seed) return ''
  return [
    seed.title ? `标题：${seed.title}` : '',
    seed.genre ? `题材：${seed.genre}` : '',
    seed.logline ? `一句话：${seed.logline}` : '',
    seed.protagonist ? `主角：${seed.protagonist}` : '',
    seed.coreConflict ? `核心冲突：${seed.coreConflict}` : '',
    seed.emotionalPromise ? `情绪价值：${seed.emotionalPromise}` : '',
    seed.endingAnchor ? `结局锚点：${seed.endingAnchor}` : ''
  ].filter(Boolean).join('\n')
}

function formatBible(bible) {
  if (!bible) return ''
  return [
    bible.premise ? `作品定位：${bible.premise}` : '',
    bible.targetReader ? `目标读者：${bible.targetReader}` : '',
    bible.styleBible ? `风格要求：${bible.styleBible}` : '',
    bible.themeBible ? `主题母题：${bible.themeBible}` : '',
    bible.worldRules ? `世界规则：${bible.worldRules}` : '',
    bible.forbiddenDirections?.length ? `禁止方向：${bible.forbiddenDirections.join('；')}` : ''
  ].filter(Boolean).join('\n')
}

function formatVolumes(volumes) {
  if (!volumes?.length) return ''
  return volumes.map(volume => [
    `- ${volume.title || `第 ${volume.volumeNum} 卷`}（第 ${volume.startChapter}-${volume.endChapter} 章 / ${volume.status}）`,
    volume.coreGoal ? `目标：${volume.coreGoal}` : '',
    volume.mainConflict ? `冲突：${volume.mainConflict}` : '',
    volume.summary ? `摘要：${volume.summary}` : '',
    volume.stageSummaryReport?.handoffToNext?.length ? `接力点：${volume.stageSummaryReport.handoffToNext.join('；')}` : '',
    volume.auditReport?.overallAssessment ? `审稿：${volume.auditReport.overallAssessment}` : ''
  ].filter(Boolean).join('；')).join('\n')
}

function formatChapters(chapters) {
  if (!chapters?.length) return ''
  return chapters.slice(-80).map(ch =>
    `- 第 ${ch.chapterNum} 章《${ch.title || '未命名'}》[${ch.status || 'unknown'} / ${ch.wordCount || 0}字]：${ch.summary || '暂无摘要'}`
  ).join('\n')
}

function formatSettings(entities, relations) {
  const entityLines = (entities || [])
    .filter(entity => entity.status !== 'archived')
    .sort((a, b) => Number(b.importance || 0) - Number(a.importance || 0))
    .slice(0, 40)
    .map(entity => `- [${entity.entityType}] ${entity.name}：${entity.summary || '暂无概要'}`)
  const entityMap = new Map((entities || []).map(entity => [entity.id, entity.name]))
  const relationLines = (relations || []).slice(0, 24).map(relation =>
    `- ${entityMap.get(relation.sourceEntityId) || '未知'} -> ${entityMap.get(relation.targetEntityId) || '未知'}：${relation.summary || relation.relationType || '关系'}`
  )
  return [entityLines.join('\n'), relationLines.length ? `关系：\n${relationLines.join('\n')}` : ''].filter(Boolean).join('\n')
}

function formatFacts(facts) {
  return (facts || [])
    .filter(fact => fact.status === 'accepted')
    .slice(0, 80)
    .map(fact => `- 第 ${fact.chapterNum} 章 [${fact.factType}] ${fact.content}`)
    .join('\n')
}

function formatThreads(threads) {
  return (threads || [])
    .slice(0, 60)
    .map(thread => `- [${thread.status}] ${thread.title}：${thread.content || ''}${thread.resolvedChapter ? `；回收于第 ${thread.resolvedChapter} 章` : ''}`)
    .join('\n')
}

function formatSettingChanges(events) {
  return (events || [])
    .filter(event => event.status === 'accepted')
    .slice(0, 40)
    .map(event => `- 第 ${event.chapterNum || '?'} 章 ${event.entityName || event.entityType}：${event.fieldPath || event.changeType} -> ${event.newValue || ''}`)
    .join('\n')
}

function auditReport() {
  return activeGlobalAudit.value?.reportJson || activeGlobalAudit.value?.report || null
}
</script>

<template>
  <div v-if="project" class="p-6">
    <div class="flex items-start justify-between gap-4 mb-6">
      <div>
        <div class="flex items-center gap-2">
          <h2 class="text-2xl font-bold text-gray-800">{{ project.title }}</h2>
          <n-button size="tiny" secondary @click="openProjectEditModal">编辑项目信息</n-button>
        </div>
        <p v-if="project.description" class="text-sm text-gray-500 mt-2 max-w-3xl leading-6">
          {{ project.description }}
        </p>
        <div class="flex items-center gap-2 mt-2">
          <n-tag v-if="project.genre" size="small">{{ project.genre }}</n-tag>
          <n-tag :type="project.status === 'drafting' ? 'info' : 'success'" size="small">
            {{ project.status === 'drafting' ? '创作中' : '已完成' }}
          </n-tag>
          <span class="text-sm text-gray-400">
            目标 {{ project.targetWords ? (project.targetWords / 10000).toFixed(0) : '0' }} 万字 · {{ project.targetChapters || 0 }} 章
          </span>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <n-dropdown trigger="click" :options="exportOptions" @select="handleExportSelect">
          <n-button size="large">导出</n-button>
        </n-dropdown>
        <n-button size="large" :loading="novelStore.globalAuditing" @click="openGlobalAuditConfig">
          全局审稿
        </n-button>
        <n-button type="primary" size="large" @click="goToWriter(project.currentChapterNum || 1)">
          进入写字台
        </n-button>
      </div>
    </div>

    <n-card class="mb-4" size="small">
      <div class="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h3 class="text-base font-semibold text-gray-700">创作准备流程</h3>
          <p class="text-xs text-gray-400 mt-1">按真实长篇小说开发顺序推进：先判断写什么，再确定怎么写，最后进入章节生产。</p>
        </div>
        <n-button size="small" type="primary" secondary @click="goToWriter(project.currentChapterNum || 1)">
          进入写字台
        </n-button>
      </div>
      <div class="grid grid-cols-1 md:grid-cols-6 gap-2 mt-3">
        <button
          v-for="step in workflowSteps"
          :key="step.key"
          class="text-left rounded border px-3 py-2 transition-colors bg-white hover:border-green-300"
          :class="activeTab === step.key ? 'border-green-500 bg-green-50' : 'border-gray-200'"
          @click="activeTab = step.key"
        >
          <div class="flex items-center justify-between gap-2">
            <span class="text-sm font-medium text-gray-700">{{ step.title }}</span>
            <n-tag size="tiny" :type="step.statusType || (step.done ? 'success' : 'default')" :bordered="!step.done">
              {{ step.statusLabel || (step.done ? '已就绪' : '待完善') }}
            </n-tag>
          </div>
          <p class="text-xs text-gray-400 mt-1 leading-5">{{ step.desc }}</p>
        </button>
      </div>
    </n-card>

    <n-alert v-if="novelStore.globalAuditReports.length" type="info" :bordered="false" class="mb-4">
      最近审稿：
      <button class="text-blue-600 hover:underline" @click="viewGlobalAudit(novelStore.globalAuditReports[0])">
        {{ novelStore.globalAuditReports[0].title || '审稿报告' }}
      </button>
      <span class="text-gray-400 ml-2">
        {{ new Date(novelStore.globalAuditReports[0].createdAt).toLocaleString('zh-CN') }}
      </span>
    </n-alert>

    <n-alert v-if="correctionTaskStore.activeTasks.length" type="warning" :bordered="false" class="mb-4">
      当前还有 {{ correctionTaskStore.activeTasks.length }} 条未完成纠偏任务。
      <button class="text-blue-600 hover:underline" @click="activeTab = 'corrections'">
        查看任务板
      </button>
    </n-alert>

    <n-tabs v-model:value="activeTab" type="line" animated>
      <n-tab-pane name="market" tab="1 选题雷达">
        <div class="mt-4">
          <MarketRadar :project-id="project.id" />
        </div>
      </n-tab-pane>

      <n-tab-pane name="seed" tab="2 创作种子">
        <div class="mt-4">
          <SeedWorkbench :project-id="project.id" @seed-selected="onSeedSelected" />
        </div>
      </n-tab-pane>

      <n-tab-pane name="bible" tab="3 创作圣经">
        <div class="mt-4 max-w-3xl">
          <CreativeBible :project-id="project.id" />
          <n-card title="项目信息" class="mt-4" size="small">
            <div class="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span class="text-gray-400">简介：</span>
                <span>{{ project.description || '暂无' }}</span>
              </div>
              <div>
                <span class="text-gray-400">当前章节：</span>
                <span>第 {{ project.currentChapterNum || 0 }} 章</span>
              </div>
              <div>
                <span class="text-gray-400">创建时间：</span>
                <span>{{ new Date(project.createdAt).toLocaleString('zh-CN') }}</span>
              </div>
              <div>
                <span class="text-gray-400">更新时间：</span>
                <span>{{ new Date(project.updatedAt).toLocaleString('zh-CN') }}</span>
              </div>
            </div>
          </n-card>
        </div>
      </n-tab-pane>

      <n-tab-pane name="settingsLibrary" tab="4 设定库">
        <div class="mt-4">
          <SettingLibrary :project-id="project.id" />
        </div>
      </n-tab-pane>

      <n-tab-pane name="chapters" tab="5 章节管理">
        <div class="mt-4">
          <VolumePlanner :project="project" :chapters="writerStore.chapters" />

          <div class="flex items-center justify-between mb-4">
            <h3 class="text-lg font-semibold text-gray-700">章节列表（{{ writerStore.chapters.length }} 章）</h3>
          </div>

          <n-empty v-if="writerStore.chapters.length === 0" description="暂无章节，进入写字台开始创作">
            <template #action>
              <n-button type="primary" @click="goToWriter(1)">开始创作第 1 章</n-button>
            </template>
          </n-empty>

          <div v-if="writerStore.chapters.length > 0" class="grid gap-2">
            <div
              v-for="ch in writerStore.chapters"
              :key="ch.id"
              class="flex items-center justify-between p-3 rounded border border-gray-200 hover:border-blue-300 cursor-pointer transition-colors"
              @click="goToWriter(ch.chapterNum)"
            >
              <div class="flex items-center gap-3">
                <span class="text-sm font-medium text-gray-500 w-16">第 {{ ch.chapterNum }} 章</span>
                <span class="text-sm text-gray-800">{{ ch.title || '未命名' }}</span>
                <n-tag :type="chapterStatusColors[ch.status]" size="tiny" :bordered="false">
                  {{ chapterStatusLabels[ch.status] || ch.status }}
                </n-tag>
              </div>
              <div class="flex items-center gap-3 text-xs text-gray-400">
                <span v-if="ch.wordCount">{{ ch.wordCount }} 字</span>
                <span v-if="ch.summary" class="line-clamp-1 max-w-60">{{ ch.summary }}</span>
                <span>进入</span>
              </div>
            </div>
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="corrections" tab="6 纠偏任务">
        <div class="mt-4">
          <CorrectionTaskBoard :project-id="project.id" @navigate="handleCorrectionNavigate" />
        </div>
      </n-tab-pane>

      <n-tab-pane name="characterArcs" tab="人物弧光">
        <div class="mt-4">
          <CharacterArcView
            :characters="novelStore.characters"
            :chapters="writerStore.chapters"
            :canon-facts="novelStore.canonFacts"
          />
        </div>
      </n-tab-pane>

      <n-tab-pane name="plotThreads" tab="伏笔看板">
        <div class="mt-4">
          <PlotThreadBoard
            :plot-threads="novelStore.plotThreads"
            :chapters="writerStore.chapters"
          />
        </div>
      </n-tab-pane>
    </n-tabs>

    <n-modal v-model:show="showProjectEditModal" preset="card" title="编辑项目信息" style="width: 560px">
      <n-form :model="projectEditForm">
        <n-form-item label="项目名称" required>
          <n-input v-model:value="projectEditForm.title" placeholder="输入项目名称" />
        </n-form-item>
        <n-form-item label="题材">
          <n-input v-model:value="projectEditForm.genre" placeholder="如：玄幻、都市、科幻" />
        </n-form-item>
        <n-form-item label="简介">
          <n-input v-model:value="projectEditForm.description" type="textarea" rows="3" placeholder="项目简介" />
        </n-form-item>
        <n-alert v-if="projectPlanLocked" type="warning" class="mb-4" :bordered="false">
          {{ projectPlanLockReason }}
        </n-alert>
        <n-form-item label="目标字数（万字）">
          <n-input-number
            v-model:value="projectEditForm.targetWords"
            :min="1"
            :step="1"
            :disabled="projectPlanLocked"
            :format="value => `${value / 10000}`"
            :parse="value => Number.parseFloat(value || 0) * 10000"
          />
        </n-form-item>
        <n-form-item label="目标章节数">
          <n-input-number
            v-model:value="projectEditForm.targetChapters"
            :min="1"
            :step="1"
            :disabled="projectPlanLocked"
          />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showProjectEditModal = false">取消</n-button>
          <n-button type="primary" :loading="editingProject" @click="saveProjectEdit">保存修改</n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showGlobalAuditConfigModal" preset="card" title="选择审稿范围" style="width: 520px;">
      <div class="space-y-4">
        <n-alert type="info" :bordered="false">
          全书审稿适合阶段性总检查；章节范围审稿适合只检查某一段剧情、某一卷或最近写完的章节。
        </n-alert>
        <n-radio-group v-model:value="globalAuditScope">
          <n-space>
            <n-radio-button value="all">全书</n-radio-button>
            <n-radio-button value="range">指定章节</n-radio-button>
          </n-space>
        </n-radio-group>
        <div v-if="globalAuditScope === 'range'" class="grid grid-cols-2 gap-3">
          <label class="text-sm text-gray-600">
            <span class="block mb-1">起始章节</span>
            <n-input-number v-model:value="globalAuditStartChapter" :min="1" class="w-full" />
          </label>
          <label class="text-sm text-gray-600">
            <span class="block mb-1">结束章节</span>
            <n-input-number v-model:value="globalAuditEndChapter" :min="1" class="w-full" />
          </label>
        </div>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button @click="showGlobalAuditConfigModal = false">取消</n-button>
          <n-button type="primary" :loading="novelStore.globalAuditing" @click="handleGlobalAudit">
            开始审稿
          </n-button>
        </n-space>
      </template>
    </n-modal>

    <n-modal v-model:show="showGlobalAuditModal" preset="card" title="审稿报告" style="width: 820px; max-height: 86vh;">
      <div v-if="auditReport()" class="space-y-4">
        <div class="flex items-start justify-between gap-3">
          <div>
            <h3 class="text-lg font-bold text-gray-800">项目健康度 {{ auditReport().healthScore ?? '-' }}</h3>
            <p class="text-xs text-gray-400 mt-1">
              {{ activeGlobalAudit?.createdAt ? new Date(activeGlobalAudit.createdAt).toLocaleString('zh-CN') : '' }}
            </p>
          </div>
          <n-tag :type="auditReport().safeToWriteNext ? 'success' : 'warning'" :bordered="false">
            {{ auditReport().safeToWriteNext ? '可继续写' : '建议先调整' }}
          </n-tag>
        </div>

        <n-alert type="info" :bordered="false">
          {{ auditReport().overallVerdict || '暂无总体判断' }}
        </n-alert>

        <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
          <n-card
            v-for="section in [
              ['mainlineReview', '主线'],
              ['characterReview', '人物'],
              ['settingReview', '设定'],
              ['foreshadowingReview', '伏笔'],
              ['pacingReview', '节奏'],
              ['readerPromiseReview', '读者承诺']
            ]"
            :key="section[0]"
            size="small"
            :title="section[1]"
          >
            <n-tag size="tiny" :bordered="false" class="mb-2">
              {{ auditReport()[section[0]]?.status || 'unknown' }}
            </n-tag>
            <p class="text-sm text-gray-600 leading-6 whitespace-pre-wrap">
              {{ auditReport()[section[0]]?.comment || '暂无' }}
            </p>
            <ul v-if="auditReport()[section[0]]?.actions?.length" class="text-xs text-gray-500 mt-2 list-disc pl-4 leading-5">
              <li v-for="(action, idx) in auditReport()[section[0]].actions" :key="idx">{{ action }}</li>
            </ul>
          </n-card>
        </div>

        <n-card v-if="auditReport().criticalIssues?.length" title="关键问题" size="small">
          <div class="space-y-2">
            <div
              v-for="(issue, idx) in auditReport().criticalIssues"
              :key="idx"
              class="rounded border border-gray-200 p-3 text-sm"
            >
              <div class="flex items-center gap-2 mb-1">
                <n-tag size="tiny" :type="issue.severity === 'critical' ? 'error' : issue.severity === 'major' ? 'warning' : 'default'">
                  {{ issue.severity || 'issue' }}
                </n-tag>
                <n-tag size="tiny" :bordered="false">{{ issue.type || 'general' }}</n-tag>
              </div>
              <p class="font-medium text-gray-800">{{ issue.description }}</p>
              <p v-if="issue.impact" class="text-gray-500 mt-1">影响：{{ issue.impact }}</p>
              <p v-if="issue.suggestion" class="text-blue-600 mt-1">建议：{{ issue.suggestion }}</p>
            </div>
          </div>
        </n-card>

        <n-card v-if="auditReport().nextActions?.length" title="下一步行动" size="small">
          <ul class="list-disc pl-5 text-sm text-gray-600 leading-7">
            <li v-for="(item, idx) in auditReport().nextActions" :key="idx">{{ item }}</li>
          </ul>
        </n-card>
      </div>
      <template #footer>
        <n-space justify="end">
          <n-button
            v-if="auditReport()?.criticalIssues?.length || auditReport()?.nextActions?.length"
            type="primary"
            secondary
            @click="handleCreateCorrectionTasksFromGlobalAudit"
          >
            生成纠偏任务
          </n-button>
          <n-button @click="showGlobalAuditModal = false">关闭</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>

  <div v-else class="p-6">
    <n-empty description="项目未找到">
      <template #action>
        <n-button @click="router.push('/')">返回项目库</n-button>
      </template>
    </n-empty>
  </div>
</template>

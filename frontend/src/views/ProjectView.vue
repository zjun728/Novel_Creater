<script setup>
import { onMounted, computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NAlert, NButton, NCard, NEmpty, NSpace, NTag, NTabs, NTabPane, NDropdown, NModal } from 'naive-ui'
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
const showGlobalAuditModal = ref(false)
const activeGlobalAudit = ref(null)
const selectedSeed = computed(() => seedStore.seeds.find(s => s.status === 'selected'))
const bibleReady = computed(() => Boolean(novelStore.bible?.premise || novelStore.bible?.worldRules || novelStore.bible?.styleBible))
const settingsReady = computed(() => settingStore.entities.length > 0)

const workflowSteps = computed(() => [
  {
    key: 'market',
    title: '1 选题',
    desc: '确定题材赛道、卖点和读者预期',
    done: Boolean(project.value?.genre)
  },
  {
    key: 'seed',
    title: '2 种子',
    desc: '沉淀主角、冲突、开局钩子',
    done: Boolean(selectedSeed.value)
  },
  {
    key: 'bible',
    title: '3 圣经',
    desc: '确认作品蓝图和长期写作原则',
    done: bibleReady.value
  },
  {
    key: 'settingsLibrary',
    title: '4 设定库',
    desc: '记录人物、势力、地点与规则',
    done: settingsReady.value
  },
  {
    key: 'chapters',
    title: '5 章节',
    desc: '进入写字台按小纲生成正文',
    done: writerStore.chapters.length > 0
  },
  {
    key: 'corrections',
    title: '6 纠偏',
    desc: '把审稿问题转成可执行任务',
    done: correctionTaskStore.activeTasks.length === 0 && correctionTaskStore.tasks.length > 0
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
  { label: '导出全部 MD', key: 'md' },
  { label: '导出项目包 JSON', key: 'bundle' }
]

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

function onSeedSelected(seed) {
  // 种子被选中后，可以创建创作圣经
}

async function handleGlobalAudit() {
  try {
    const report = await novelStore.generateGlobalAudit(project.value, buildGlobalAuditContext())
    activeGlobalAudit.value = report
    showGlobalAuditModal.value = true
    message.success('全局审稿已生成')
  } catch (e) {
    message.error('全局审稿失败：' + e.message)
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
    message.warning('当前全局审稿报告没有可转化的问题项')
    return
  }
  try {
    const created = await correctionTaskStore.bulkCreate(project.value.id, payloads)
    message.success(`已生成 ${created.length} 条全局纠偏任务`)
  } catch (e) {
    message.error('生成纠偏任务失败：' + e.message)
  }
}

function buildGlobalAuditContext() {
  return {
    projectTitle: project.value?.title,
    genre: project.value?.genre,
    description: project.value?.description,
    targetWords: project.value?.targetWords,
    targetChapters: project.value?.targetChapters,
    currentChapterNum: project.value?.currentChapterNum,
    seedSummary: formatSelectedSeed(selectedSeed.value),
    bibleSummary: formatBible(novelStore.bible),
    volumeSummary: formatVolumes(volumeStore.volumes),
    chapterSummary: formatChapters(writerStore.chapters),
    settingSummary: formatSettings(settingStore.entities, settingStore.relations),
    factSummary: formatFacts(novelStore.canonFacts),
    threadSummary: formatThreads(novelStore.plotThreads),
    settingChangeSummary: formatSettingChanges(settingStore.changeEvents)
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
    seed.emotionalPromise ? `情绪价值：${seed.emotionalPromise}` : ''
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
    `- ${volume.title || `第${volume.volumeNum}卷`}（第${volume.startChapter}-${volume.endChapter}章 / ${volume.status}）`,
    volume.coreGoal ? `目标：${volume.coreGoal}` : '',
    volume.mainConflict ? `冲突：${volume.mainConflict}` : '',
    volume.summary ? `摘要：${volume.summary}` : '',
    volume.stageSummaryReport?.handoffToNext?.length ? `接力：${volume.stageSummaryReport.handoffToNext.join('；')}` : '',
    volume.auditReport?.overallAssessment ? `审稿：${volume.auditReport.overallAssessment}` : ''
  ].filter(Boolean).join('；')).join('\n')
}

function formatChapters(chapters) {
  if (!chapters?.length) return ''
  return chapters.slice(-80).map(ch =>
    `- 第${ch.chapterNum}章《${ch.title || '未命名'}》[${ch.status || 'unknown'} / ${ch.wordCount || 0}字]：${ch.summary || '暂无摘要'}`
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
    .filter(f => f.status === 'accepted')
    .slice(0, 80)
    .map(f => `- 第${f.chapterNum}章[${f.factType}] ${f.content}`)
    .join('\n')
}

function formatThreads(threads) {
  return (threads || [])
    .slice(0, 60)
    .map(thread => `- [${thread.status}] ${thread.title}：${thread.content || ''}${thread.resolvedChapter ? `；回收于第${thread.resolvedChapter}章` : ''}`)
    .join('\n')
}

function formatSettingChanges(events) {
  return (events || [])
    .filter(event => event.status === 'accepted')
    .slice(0, 40)
    .map(event => `- 第${event.chapterNum || '?'}章 ${event.entityName || event.entityType}：${event.fieldPath || event.changeType} -> ${event.newValue || ''}`)
    .join('\n')
}

function auditReport() {
  return activeGlobalAudit.value?.reportJson || activeGlobalAudit.value?.report || null
}

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
</script>

<template>
  <div class="p-6" v-if="project">
    <!-- 项目头部 -->
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-800">{{ project.title }}</h2>
        <div class="flex items-center gap-2 mt-1">
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
        <NDropdown trigger="click" :options="exportOptions" @select="handleExportSelect">
          <n-button size="large">导出</n-button>
        </NDropdown>
        <n-button
          size="large"
          :loading="novelStore.globalAuditing"
          @click="handleGlobalAudit"
        >
          全局审稿
        </n-button>
        <n-button type="primary" size="large" @click="goToWriter(project.currentChapterNum || 1)">
          进入写作台
        </n-button>
      </div>
    </div>

    <!-- 创作准备流程 -->
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
            <n-tag size="tiny" :type="step.done ? 'success' : 'default'" :bordered="!step.done">
              {{ step.done ? '已就绪' : '待完善' }}
            </n-tag>
          </div>
          <p class="text-xs text-gray-400 mt-1 leading-5">{{ step.desc }}</p>
        </button>
      </div>
    </n-card>

    <n-alert
      v-if="novelStore.globalAuditReports.length"
      type="info"
      :bordered="false"
      class="mb-4"
    >
      最近全局审稿：
      <button class="text-blue-600 hover:underline" @click="viewGlobalAudit(novelStore.globalAuditReports[0])">
        {{ novelStore.globalAuditReports[0].title || '全局审稿报告' }}
      </button>
      <span class="text-gray-400 ml-2">
        {{ new Date(novelStore.globalAuditReports[0].createdAt).toLocaleString('zh-CN') }}
      </span>
    </n-alert>

    <n-alert
      v-if="correctionTaskStore.activeTasks.length"
      type="warning"
      :bordered="false"
      class="mb-4"
    >
      当前还有 {{ correctionTaskStore.activeTasks.length }} 条未完成纠偏任务。
      <button class="text-blue-600 hover:underline" @click="activeTab = 'corrections'">
        查看任务板
      </button>
    </n-alert>

    <!-- 标签页 -->
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

          <!-- 项目基本信息 -->
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
            <h3 class="text-lg font-semibold text-gray-700">
              章节列表（{{ writerStore.chapters.length }} 章）
            </h3>
          </div>

          <n-empty v-if="writerStore.chapters.length === 0" description="暂无章节，进入写作台开始创作">
            <template #action>
              <n-button type="primary" @click="goToWriter(1)">开始创作第一章</n-button>
            </template>
          </n-empty>

          <div class="grid gap-2" v-if="writerStore.chapters.length > 0">
            <div
              v-for="ch in writerStore.chapters"
              :key="ch.id"
              class="flex items-center justify-between p-3 rounded border border-gray-200 hover:border-blue-300 cursor-pointer transition-colors"
              @click="goToWriter(ch.chapterNum)"
            >
              <div class="flex items-center gap-3">
                <span class="text-sm font-medium text-gray-500 w-16">第 {{ ch.chapterNum }} 章</span>
                <span class="text-sm text-gray-800">{{ ch.title || '未命名' }}</span>
                <n-tag
                  :type="chapterStatusColors[ch.status]"
                  size="tiny"
                  :bordered="false"
                >
                  {{ chapterStatusLabels[ch.status] || ch.status }}
                </n-tag>
              </div>
              <div class="flex items-center gap-3 text-xs text-gray-400">
                <span v-if="ch.wordCount">{{ ch.wordCount }} 字</span>
                <span v-if="ch.summary" class="line-clamp-1 max-w-60">{{ ch.summary }}</span>
                <span>→</span>
              </div>
            </div>
          </div>
        </div>
      </n-tab-pane>

      <n-tab-pane name="corrections" tab="6 纠偏任务">
        <div class="mt-4">
          <CorrectionTaskBoard :project-id="project.id" />
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

    <n-modal v-model:show="showGlobalAuditModal" preset="card" title="全局审稿报告" style="width: 820px; max-height: 86vh;">
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

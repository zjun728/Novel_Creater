<script setup>
import { onMounted, computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NCard, NEmpty, NSpace, NTag, NTabs, NTabPane, NDropdown } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { downloadFile, exportTxt, exportMarkdown, exportProjectBundle } from '@/utils/export'
import { useProjectStore } from '@/stores/projectStore'
import { useWriterStore } from '@/stores/writerStore'
import { useSeedStore } from '@/stores/seedStore'
import { useNovelStore } from '@/stores/novelStore'
import { useSettingStore } from '@/stores/settingStore'
import SeedWorkbench from '@/components/seed/SeedWorkbench.vue'
import CreativeBible from '@/components/bible/CreativeBible.vue'
import MarketRadar from '@/components/market/MarketRadar.vue'
import CharacterArcView from '@/components/bible/CharacterArcView.vue'
import PlotThreadBoard from '@/components/bible/PlotThreadBoard.vue'
import SettingLibrary from '@/components/settings-library/SettingLibrary.vue'
import VolumePlanner from '@/components/chapter/VolumePlanner.vue'

const route = useRoute()
const router = useRouter()
const projectStore = useProjectStore()
const writerStore = useWriterStore()
const seedStore = useSeedStore()
const novelStore = useNovelStore()
const settingStore = useSettingStore()
const message = useAppMessage()

const project = computed(() => projectStore.currentProject)
const activeTab = ref('market')
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
        settingStore.loadEntities(id),
        settingStore.loadRelations(id),
        settingStore.loadChangeEvents(id)
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
      <div class="grid grid-cols-1 md:grid-cols-5 gap-2 mt-3">
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
  </div>

  <div v-else class="p-6">
    <n-empty description="项目未找到">
      <template #action>
        <n-button @click="router.push('/')">返回项目库</n-button>
      </template>
    </n-empty>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { NButton, NInput, NSelect, NTag, NSpace, NEmpty, NModal, NCard, useMessage } from 'naive-ui'
import { useMarketStore } from '@/stores/marketStore'
import MarketCard from './MarketCard.vue'
import AIChatPanel from './AIChatPanel.vue'

const props = defineProps({
  projectId: { type: String, required: true }
})

const marketStore = useMarketStore()
const message = useMessage()

const keywords = ref('热门小说')
const platformFilter = ref('')
const categoryFilter = ref('')
const lastSources = ref([])

// 弹窗
const showDetail = ref(false)
const detailItem = ref(null)

// 一次性加载种子数提示
const lastSeedCount = ref(0)

// 预设搜索关键词
const presetKeywords = [
  '玄幻 热门',
  '都市 热门',
  '言情 热销',
  '悬疑 灵异',
  '科幻 末世',
  '仙侠 修真',
  '历史 穿越',
  '游戏 竞技'
]

onMounted(async () => {
  await marketStore.loadItems(props.projectId)
})

watch(
  () => marketStore.chatMessages.length,
  (newLen) => {
    // 检查是否有新的种子
    const lastMsg = marketStore.chatMessages[marketStore.chatMessages.length - 1]
    if (lastMsg?.seeds?.length) {
      const newSeeds = lastMsg.seeds.length
      if (newSeeds > lastSeedCount.value) {
        message.success(`已生成 ${newSeeds} 个创作种子，可在"创作种子"标签页查看`)
        lastSeedCount.value = newSeeds
      }
    }
  }
)

async function handleScrape() {
  if (!keywords.value.trim()) {
    message.warning('请输入搜索关键词')
    return
  }
  try {
    const result = await marketStore.scrapeMarket(props.projectId, keywords.value.trim())
    lastSources.value = result?.sources || []
    const count = result?.count || 0
    if (count > 0) {
      if (result?.fallback) {
        message.warning(result.message || `实时抓取失败，已加载 ${count} 条本地参考样本`)
      } else {
        message.success(result.message || `成功抓取 ${count} 条热门小说数据`)
      }
    } else {
      message.warning(result?.message || '未找到可读取的结果，请尝试其他关键词')
    }
  } catch (e) {
    lastSources.value = []
    message.error('抓取失败：' + e.message)
  }
}

function handleAnalyze(item) {
  marketStore.analyzeItem(item.id)
    .then(() => message.success('AI 分析完成'))
    .catch(e => message.error('分析失败：' + e.message))
}

function handleView(item) {
  detailItem.value = item
  showDetail.value = true
}

function handleDelete(item) {
  marketStore.deleteItem(item.id)
    .then(() => message.success('已删除'))
    .catch(e => message.error('删除失败：' + e.message))
}

function handleSeedCreated({ seeds }) {
  message.success(`${seeds.length} 个创作种子已保存，可在"创作种子"标签页查看`)
}

function handleSeedUpdated({ seeds }) {
  message.success(`当前创作种子已更新，可在"创作种子"标签页查看和手动微调`)
}

// 分类统计
const categories = computed(() => {
  const cats = {}
  for (const item of marketStore.items) {
    const c = item.category || '未分类'
    cats[c] = (cats[c] || 0) + 1
  }
  return Object.entries(cats).sort((a, b) => b[1] - a[1])
})

// 平台统计
const platforms = computed(() => {
  const plats = {}
  for (const item of marketStore.items) {
    const p = item.platform || '未知'
    plats[p] = (plats[p] || 0) + 1
  }
  return Object.entries(plats)
})

// 筛选后的 items
const filteredItems = computed(() => {
  let list = marketStore.items
  if (platformFilter.value) {
    list = list.filter(i => i.platform === platformFilter.value)
  }
  if (categoryFilter.value) {
    list = list.filter(i => i.category === categoryFilter.value)
  }
  return list
})

const platformOptions = computed(() =>
  platforms.value.map(([p, c]) => ({ label: `${p} (${c})`, value: p }))
)

const categoryOptions = computed(() =>
  categories.value.map(([c, n]) => ({ label: `${c} (${n})`, value: c }))
)
</script>

<template>
  <div class="market-radar flex gap-4" style="min-height: calc(100vh - 300px)">
    <!-- 左侧：内容区 -->
    <div class="flex-1 min-w-0">
      <!-- 搜索栏 -->
      <div class="flex items-center gap-2 mb-3 flex-wrap">
        <n-input
          v-model:value="keywords"
          placeholder="输入搜索关键词"
          size="small"
          style="width: 200px"
          @keydown.enter="handleScrape"
          clearable
        />
        <n-button
          size="small"
          type="primary"
          :loading="marketStore.scraping"
          @click="handleScrape"
        >
          {{ marketStore.scraping ? '抓取中...' : '开始抓取' }}
        </n-button>

        <div class="flex gap-1">
          <n-button
            v-for="kw in presetKeywords"
            :key="kw"
            size="tiny"
            quaternary
            @click="keywords = kw; handleScrape()"
          >
            {{ kw }}
          </n-button>
        </div>
      </div>

      <div v-if="lastSources.length" class="flex items-center gap-1 mb-3 flex-wrap">
        <span class="text-xs text-gray-400 mr-1">来源状态：</span>
        <n-tag
          v-for="source in lastSources.slice(0, 12)"
          :key="source.platform + source.url"
          size="tiny"
          :type="source.count > 0 ? 'success' : source.ok ? 'warning' : 'error'"
          :bordered="source.count === 0"
        >
          {{ source.platform }} {{ source.count || 0 }}
        </n-tag>
      </div>

      <!-- 筛选 -->
      <div class="flex items-center gap-2 mb-3" v-if="marketStore.items.length > 0">
        <n-select
          v-model:value="platformFilter"
          placeholder="平台筛选"
          size="tiny"
          style="width: 150px"
          :options="[{ label: '全部平台', value: '' }, ...platformOptions]"
          clearable
        />
        <n-select
          v-model:value="categoryFilter"
          placeholder="分类筛选"
          size="tiny"
          style="width: 150px"
          :options="[{ label: '全部分类', value: '' }, ...categoryOptions]"
          clearable
        />
        <span class="text-xs text-gray-400">
          共 {{ marketStore.items.length }} 条结果
          <template v-if="platformFilter || categoryFilter">
            ，当前显示 {{ filteredItems.length }} 条
          </template>
        </span>
      </div>

      <!-- 分类统计 -->
      <div v-if="categories.length > 0 && marketStore.items.length > 0" class="flex items-center gap-1 mb-3 flex-wrap">
        <span class="text-xs text-gray-400 mr-1">热门分类：</span>
        <n-tag
          v-for="([cat, count], idx) in categories.slice(0, 10)"
          :key="cat"
          size="tiny"
          :bordered="idx >= 3"
          :type="idx === 0 ? 'error' : idx < 3 ? 'warning' : 'default'"
          class="cursor-pointer"
          @click="categoryFilter = categoryFilter === cat ? '' : cat"
        >
          {{ cat }} {{ count }}
        </n-tag>
      </div>

      <!-- 卡片网格 -->
      <n-empty
        v-if="!marketStore.loading && filteredItems.length === 0"
        :description="marketStore.items.length === 0 ? '暂无数据，输入关键词开始抓取热门小说趋势' : '无匹配结果'"
        size="small"
      >
        <template v-if="marketStore.items.length === 0" #action>
          <n-button size="small" type="primary" @click="handleScrape">开始抓取</n-button>
        </template>
      </n-empty>

      <div v-else class="grid grid-cols-2 gap-3">
        <MarketCard
          v-for="item in filteredItems"
          :key="item.id"
          :item="item"
          @analyze="handleAnalyze"
          @view="handleView"
          @delete="handleDelete"
        />
      </div>
    </div>

    <!-- 右侧：AI 对话面板 -->
    <div class="w-80 flex-shrink-0 border-l">
      <AIChatPanel
        :project-id="projectId"
        :items="marketStore.items"
        @seed-created="handleSeedCreated"
        @seed-updated="handleSeedUpdated"
      />
    </div>

    <!-- 详情弹窗 -->
    <n-modal v-model:show="showDetail" title="小说详情" preset="card" style="width: 560px; max-height: 80vh;">
      <div v-if="detailItem" class="space-y-3 text-sm">
        <div class="flex items-center gap-2">
          <n-tag type="info" size="small">{{ detailItem.platform }}</n-tag>
          <n-tag v-if="detailItem.category" size="small">{{ detailItem.category }}</n-tag>
          <n-tag v-if="detailItem.status" :type="detailItem.status === 'completed' ? 'success' : 'default'" size="small">
            {{ detailItem.status === 'completed' ? '已完结' : detailItem.status === 'serializing' ? '连载中' : detailItem.status }}
          </n-tag>
        </div>

        <n-card size="small" title="基本信息">
          <div class="grid grid-cols-2 gap-2">
            <div><span class="text-gray-400">书名：</span>{{ detailItem.title }}</div>
            <div><span class="text-gray-400">作者：</span>{{ detailItem.author || '未知' }}</div>
            <div v-if="detailItem.wordCount"><span class="text-gray-400">字数：</span>{{ (detailItem.wordCount / 10000).toFixed(1) }}万字</div>
            <div v-if="detailItem.rankPosition"><span class="text-gray-400">排名：</span>#{{ detailItem.rankPosition }}</div>
          </div>
        </n-card>

        <n-card v-if="detailItem.intro" size="small" title="简介">
          <p class="leading-relaxed text-gray-600">{{ detailItem.intro }}</p>
        </n-card>

        <n-card v-if="detailItem.tags?.length" size="small" title="标签">
          <div class="flex gap-1 flex-wrap">
            <n-tag v-for="(tag, idx) in detailItem.tags" :key="idx" size="tiny" :bordered="true">{{ tag }}</n-tag>
          </div>
        </n-card>

        <n-card v-if="detailItem.aiSummary" size="small" title="AI 市场分析">
          <p class="text-blue-700">{{ detailItem.aiSummary }}</p>
        </n-card>

        <div v-if="detailItem.url" class="text-xs text-gray-400 truncate">
          来源：{{ detailItem.url }}
        </div>
      </div>
    </n-modal>
  </div>
</template>

<style scoped>
.market-radar {
  width: 100%;
}
</style>

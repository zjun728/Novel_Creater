<script setup>
import { NCard, NTag, NButton, NSpace, NPopconfirm } from 'naive-ui'

const props = defineProps({
  item: { type: Object, required: true }
})

const emit = defineEmits(['analyze', 'view', 'delete'])

const platformColors = {
  'fanqienovel.com': '#FF6B35',
  'zongheng.com': '#D4213D',
  'xxsy.net': '#E44C8C',
  'shuqi.com': '#5B8DEF',
  'maigoo.com': '#10B981',
  'chinawriter.com.cn': '#8B5CF6',
  '52shuku.net': '#F59E0B',
  'readnovel.com': '#06B6D4'
}

function getPlatformColor(platform) {
  return platformColors[platform] || '#6B7280'
}

function getPlatformName(platform) {
  const map = {
    'fanqienovel.com': '番茄小说',
    'zongheng.com': '纵横中文网',
    'xxsy.net': '潇湘书院',
    'shuqi.com': '书旗小说',
    'maigoo.com': '买购排行',
    'chinawriter.com.cn': '中国作家网',
    '52shuku.net': '52书库',
    'readnovel.com': '小说阅读网'
  }
  return map[platform] || platform || '未知来源'
}

function getStatusLabel(status) {
  const map = {
    'serializing': '连载中',
    'completed': '已完结',
    'unknown': '状态未知'
  }
  return map[status] || status
}
</script>

<template>
  <n-card size="small" hoverable class="market-card">
    <template #header>
      <div class="flex items-center gap-2">
        <n-tag
          size="tiny"
          :color="{ color: getPlatformColor(item.platform), textColor: '#fff' }"
          :bordered="false"
        >
          {{ getPlatformName(item.platform) }}
        </n-tag>
        <span class="text-sm font-semibold text-gray-800 truncate">
          {{ item.title || '未命名' }}
        </span>
      </div>
    </template>

    <template #header-extra>
      <n-tag v-if="item.rankPosition" size="tiny" type="warning" :bordered="false">
        #{{ item.rankPosition }}
      </n-tag>
    </template>

    <div class="space-y-2 text-xs">
      <div v-if="item.author" class="text-gray-500">
        作者：{{ item.author }}
      </div>

      <div class="flex items-center gap-1 flex-wrap">
        <n-tag v-if="item.category" size="tiny" :bordered="false">{{ item.category }}</n-tag>
        <n-tag
          v-if="item.status"
          size="tiny"
          :type="item.status === 'completed' ? 'success' : item.status === 'serializing' ? 'info' : 'default'"
          :bordered="false"
        >
          {{ getStatusLabel(item.status) }}
        </n-tag>
        <n-tag
          v-if="item.heatText"
          size="tiny"
          type="error"
          :bordered="false"
        >
          {{ item.heatText }}
        </n-tag>
      </div>

      <div v-if="item.intro" class="text-gray-600 line-clamp-3 leading-relaxed">
        {{ item.intro }}
      </div>

      <div v-if="item.tags && item.tags.length" class="flex items-center gap-1 flex-wrap">
        <n-tag
          v-for="(tag, idx) in (Array.isArray(item.tags) ? item.tags.slice(0, 8) : [])"
          :key="idx"
          size="tiny"
          :bordered="true"
          class="text-gray-400"
        >
          {{ tag }}
        </n-tag>
      </div>

      <div v-if="item.aiSummary" class="mt-2 p-2 bg-blue-50 rounded text-blue-700 text-xs">
        <span class="font-medium">AI 分析：</span>{{ item.aiSummary }}
      </div>
    </div>

    <template #footer>
      <n-space justify="end" size="small">
        <n-button
          size="tiny"
          :disabled="!!item.aiSummary"
          @click="emit('analyze', item)"
        >
          {{ item.aiSummary ? '已分析' : 'AI 总结' }}
        </n-button>
        <n-button size="tiny" @click="emit('view', item)">展开</n-button>
        <n-popconfirm @positive-click="emit('delete', item)">
          <template #trigger>
            <n-button size="tiny" quaternary type="error">删除</n-button>
          </template>
          确定删除此条目？
        </n-popconfirm>
      </n-space>
    </template>
  </n-card>
</template>

<style scoped>
.market-card {
  transition: all 0.2s;
}
.market-card:hover {
  border-color: #3b82f6;
}
.line-clamp-3 {
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
</style>


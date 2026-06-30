<script setup>
import { computed, ref } from 'vue'
import { NButton, NCard, NTag, NCollapse, NCollapseItem } from 'naive-ui'
import {
  classifyPlotThreads,
  latestPlotThreadChapter,
  latestPlotThreadSummary,
  plotThreadNodeSummary
} from '@/utils/plotThreadClassifier'

const props = defineProps({
  plotThreads: { type: Array, default: () => [] },
  chapters: { type: Array, default: () => [] },
  canonFacts: { type: Array, default: () => [] },
  currentVolume: { type: Object, default: null },
  syncing: { type: Boolean, default: false }
})
defineEmits(['sync'])

const statusConfig = {
  candidate: { label: '候选', color: 'default' },
  planted: { label: '已埋设', color: 'info' },
  developing: { label: '推进中', color: 'warning' },
  transformed: { label: '已变形', color: 'default' },
  resolved: { label: '已回收', color: 'success' },
  abandoned: { label: '已放弃', color: 'default' }
}

const typeConfig = {
  mainline: { label: '主线', color: 'error' },
  character: { label: '人物', color: 'info' },
  prop: { label: '道具', color: 'warning' },
  faction: { label: '势力', color: 'default' },
  setting: { label: '设定', color: 'success' },
  other: { label: '其他', color: 'default' }
}

const selectedFilter = ref('all')

function normalizeThreadList(value) {
  if (Array.isArray(value)) return value.map(item => String(item || '').trim()).filter(Boolean)
  if (typeof value === 'string') {
    const text = value.trim()
    if (!text) return []
    try {
      const parsed = JSON.parse(text)
      if (Array.isArray(parsed)) return parsed.map(item => String(item || '').trim()).filter(Boolean)
    } catch {}
    return text.split(/[，,；;]/).map(item => item.trim()).filter(Boolean)
  }
  return []
}

const hasUnsyncedCanonThreadTags = computed(() =>
  !props.plotThreads.length &&
  props.canonFacts.some(fact =>
    (fact.status || 'accepted') === 'accepted' &&
    normalizeThreadList(fact.relatedPlotThreads || fact.related_plot_threads || fact.threadTags || fact.tags).length > 0
  )
)

const classifiedThreads = computed(() => classifyPlotThreads(props.plotThreads))

function threadStatus(thread) {
  return statusConfig[thread.status] || { label: thread.status || '未知', color: 'default' }
}

function threadType(thread) {
  return typeConfig[thread.threadType || thread.thread_type || 'other'] || typeConfig.other
}

function plantedChapter(thread) {
  return Number(thread.plantedChapter || thread.planted_chapter || 0)
}

function resolvedChapter(thread) {
  return Number(thread.resolvedChapter || thread.resolved_chapter || 0)
}

function relatedCharacters(thread) {
  return normalizeThreadList(thread.relatedCharacters || thread.related_characters)
}

function inCurrentVolume(thread) {
  if (!props.currentVolume) return true
  const start = Number(props.currentVolume.startChapter || props.currentVolume.start_chapter || 0)
  const end = Number(props.currentVolume.endChapter || props.currentVolume.end_chapter || 0)
  if (!start || !end) return true
  const chapters = [plantedChapter(thread), latestPlotThreadChapter(thread), resolvedChapter(thread)].filter(Boolean)
  return chapters.some(chapterNum => chapterNum >= start && chapterNum <= end)
}

function sortThreads(threads) {
  const statusOrder = { developing: 0, planted: 1, resolved: 2, transformed: 3, abandoned: 4, candidate: 5 }
  return [...threads].sort((a, b) =>
    (statusOrder[a.status] ?? 9) - (statusOrder[b.status] ?? 9) ||
    Number(latestPlotThreadChapter(b) || 0) - Number(latestPlotThreadChapter(a) || 0) ||
    String(a.title || '').localeCompare(String(b.title || ''), 'zh-Hans-CN')
  )
}

const stats = computed(() => {
  const real = classifiedThreads.value.filter(thread => thread.threadClass === 'real_thread')
  const future = classifiedThreads.value.filter(thread => thread.threadClass === 'future_candidate')
  const system = classifiedThreads.value.filter(thread => thread.threadClass === 'system_tag')
  return {
    total: classifiedThreads.value.length,
    real: real.length,
    future: future.length,
    system: system.length,
    planted: real.filter(thread => thread.status === 'planted').length,
    developing: real.filter(thread => thread.status === 'developing').length,
    resolved: real.filter(thread => thread.status === 'resolved').length,
    current: real.filter(inCurrentVolume).length
  }
})

const filterOptions = computed(() => [
  { key: 'all', label: '全部', count: stats.value.real },
  { key: 'current', label: '当前卷', count: stats.value.current },
  { key: 'planted', label: '已埋设', count: stats.value.planted },
  { key: 'developing', label: '推进中', count: stats.value.developing },
  { key: 'resolved', label: '已回收', count: stats.value.resolved },
  { key: 'future', label: '未来候选', count: stats.value.future },
  { key: 'system', label: '系统标签', count: stats.value.system }
])

const visibleThreads = computed(() => {
  const selected = selectedFilter.value
  const threads = classifiedThreads.value.filter(thread => {
    if (selected === 'future') return thread.threadClass === 'future_candidate'
    if (selected === 'system') return thread.threadClass === 'system_tag'
    if (thread.threadClass !== 'real_thread') return false
    if (selected === 'current') return inCurrentVolume(thread)
    if (['planted', 'developing', 'resolved'].includes(selected)) return thread.status === selected
    return true
  })
  return sortThreads(threads)
})

const visibleTitle = computed(() => {
  const option = filterOptions.value.find(item => item.key === selectedFilter.value)
  return option?.label || '全部'
})
</script>

<template>
  <div>
    <div class="flex flex-wrap items-center justify-between gap-3 mb-3">
      <div>
        <h3 class="text-lg font-semibold text-gray-700">伏笔看板</h3>
        <p v-if="plotThreads.length" class="text-xs text-gray-400 mt-0.5">
          默认显示 {{ stats.real }} 条真实伏笔；{{ stats.future }} 条未来候选、{{ stats.system }} 条系统标签已折叠
        </p>
      </div>
      <div class="flex items-center gap-2">
        <span class="text-xs text-gray-400">总计 {{ stats.total }} 条</span>
        <n-button size="tiny" :loading="syncing" @click="$emit('sync')">重新同步</n-button>
      </div>
    </div>

    <div v-if="!plotThreads.length" class="text-center text-gray-400 text-sm py-8">
      <template v-if="hasUnsyncedCanonThreadTags">
        <div>已有线索标签，尚未同步到伏笔看板</div>
        <n-button size="small" class="mt-3" :loading="syncing" @click="$emit('sync')">
          同步伏笔看板
        </n-button>
      </template>
      <template v-else>
        暂无伏笔数据
      </template>
    </div>

    <div v-else>
      <div class="flex flex-wrap gap-2 mb-4">
        <button
          v-for="option in filterOptions"
          :key="option.key"
          type="button"
          :class="[
            'filter-chip',
            selectedFilter === option.key ? 'filter-chip--active' : ''
          ]"
          @click="selectedFilter = option.key"
        >
          <span>{{ option.label }}</span>
          <span class="filter-chip__count">{{ option.count }}</span>
        </button>
      </div>

      <div v-if="!visibleThreads.length" class="text-center text-gray-400 text-sm py-8">
        {{ visibleTitle }}暂无可显示条目
      </div>

      <div v-else class="thread-grid">
        <n-card
          v-for="thread in visibleThreads"
          :key="thread.id || thread.title"
          size="small"
          class="thread-card"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="text-sm font-semibold text-gray-700 truncate">{{ thread.title }}</div>
              <div class="flex items-center gap-1 mt-1 flex-wrap">
                <n-tag :type="threadType(thread).color" size="tiny" :bordered="false">
                  {{ threadType(thread).label }}
                </n-tag>
                <n-tag :type="threadStatus(thread).color" size="tiny" :bordered="false">
                  {{ threadStatus(thread).label }}
                </n-tag>
              </div>
            </div>
            <span v-if="latestPlotThreadChapter(thread)" class="chapter-badge">
              第 {{ latestPlotThreadChapter(thread) }} 章
            </span>
          </div>

          <div class="thread-meta">
            <span v-if="plantedChapter(thread)">首次：第 {{ plantedChapter(thread) }} 章</span>
            <span v-if="latestPlotThreadChapter(thread)">最近：第 {{ latestPlotThreadChapter(thread) }} 章</span>
            <span v-if="resolvedChapter(thread)">回收：第 {{ resolvedChapter(thread) }} 章</span>
          </div>

          <p class="thread-summary">
            {{ latestPlotThreadSummary(thread) || thread.content || '暂无推进摘要' }}
          </p>

          <div v-if="plotThreadNodeSummary(thread)" class="node-summary">
            {{ plotThreadNodeSummary(thread) }}
          </div>

          <div v-if="relatedCharacters(thread).length" class="flex items-center gap-1 mt-2 flex-wrap">
            <n-tag
              v-for="character in relatedCharacters(thread)"
              :key="character"
              size="tiny"
              :bordered="true"
            >
              {{ character }}
            </n-tag>
          </div>

          <n-collapse v-if="thread.content || thread.notes" class="mt-2">
            <n-collapse-item title="详情" name="detail">
              <div class="text-xs text-gray-500 space-y-1 leading-relaxed">
                <div v-if="thread.content">内容：{{ thread.content }}</div>
                <div v-if="thread.notes">备注：{{ thread.notes }}</div>
              </div>
            </n-collapse-item>
          </n-collapse>
        </n-card>
      </div>
    </div>
  </div>
</template>

<style scoped>
.filter-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-height: 30px;
  padding: 4px 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  color: #4b5563;
  background: #fff;
  font-size: 12px;
  line-height: 1;
}

.filter-chip--active {
  border-color: #2563eb;
  color: #1d4ed8;
  background: #eff6ff;
}

.filter-chip__count {
  color: #9ca3af;
}

.thread-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}

.thread-card {
  cursor: default;
  border-radius: 6px;
}

.chapter-badge {
  flex-shrink: 0;
  padding: 3px 7px;
  border-radius: 999px;
  color: #64748b;
  background: #f1f5f9;
  font-size: 11px;
  line-height: 1;
}

.thread-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 10px;
  color: #6b7280;
  font-size: 12px;
}

.thread-summary {
  min-height: 36px;
  margin-top: 8px;
  color: #4b5563;
  font-size: 12px;
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.node-summary {
  margin-top: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  color: #475569;
  background: #f8fafc;
  font-size: 12px;
  line-height: 1.4;
}
</style>

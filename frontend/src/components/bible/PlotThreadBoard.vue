<script setup>
import { computed } from 'vue'
import { NCard, NTag, NCollapse, NCollapseItem } from 'naive-ui'

const props = defineProps({
  plotThreads: { type: Array, default: () => [] },
  chapters: { type: Array, default: () => [] }
})

const statusConfig = {
  candidate: { label: '候选', color: 'default' },
  planted: { label: '已埋设', color: 'info' },
  developing: { label: '推进中', color: 'warning' },
  transformed: { label: '已变形', color: 'default' },
  resolved: { label: '已回收', color: 'success' },
  abandoned: { label: '已放弃', color: 'default' }
}

const columns = ['planted', 'developing', 'resolved', 'abandoned']

const threadsByStatus = computed(() => {
  const map = {}
  for (const col of columns) {
    map[col] = props.plotThreads.filter(t => t.status === col)
  }
  // catch-all for other statuses
  map._other = props.plotThreads.filter(t => !columns.includes(t.status))
  return map
})

function chapterDots(thread) {
  if (!props.chapters.length) return []
  return props.chapters.map(ch => {
    const planted = thread.plantedChapter === ch.chapterNum
    const resolved = thread.resolvedChapter === ch.chapterNum
    return { chapterNum: ch.chapterNum, planted, resolved }
  })
}
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-lg font-semibold text-gray-700">伏笔看板</h3>
      <span class="text-xs text-gray-400">{{ plotThreads.length }} 条伏笔</span>
    </div>

    <div v-if="!plotThreads.length" class="text-center text-gray-400 text-sm py-8">
      暂无伏笔数据，定稿章节后系统会自动提取伏笔
    </div>

    <div v-else class="overflow-x-auto">
      <!-- 章节时间线 -->
      <div v-if="chapters.length" class="flex items-center gap-0.5 mb-4 px-1">
        <span class="text-xs text-gray-400 w-12 flex-shrink-0">章节</span>
        <div
          v-for="ch in chapters"
          :key="ch.id"
          class="w-5 text-center text-[10px] text-gray-400"
        >
          {{ ch.chapterNum }}
        </div>
      </div>

      <!-- Kanban 列 -->
      <div class="flex gap-3" style="min-width: 720px">
        <div
          v-for="col in columns"
          :key="col"
          class="flex-1 min-w-0"
        >
          <div class="flex items-center gap-1 mb-2">
            <n-tag :type="statusConfig[col].color" size="tiny" :bordered="false">
              {{ statusConfig[col].label }}
            </n-tag>
            <span class="text-xs text-gray-400">{{ threadsByStatus[col].length }}</span>
          </div>

          <div class="space-y-2">
            <n-card
              v-for="thread in threadsByStatus[col]"
              :key="thread.id"
              size="small"
              class="thread-card"
            >
              <div class="text-sm font-medium text-gray-700 truncate">{{ thread.title }}</div>
              <p class="text-xs text-gray-500 mt-1 line-clamp-2">{{ thread.content }}</p>

              <div class="flex items-center gap-1 mt-2 flex-wrap">
                <n-tag
                  v-for="(ch, i) in (thread.relatedCharacters || [])"
                  :key="i"
                  size="tiny"
                  :bordered="true"
                >
                  {{ ch }}
                </n-tag>
              </div>

              <!-- 章节标记点 -->
              <div class="flex items-center gap-0.5 mt-2">
                <div
                  v-for="dot in chapterDots(thread)"
                  :key="dot.chapterNum"
                  :class="[
                    'w-3 h-3 rounded-full',
                    dot.planted && dot.resolved ? 'bg-purple-400' :
                    dot.planted ? 'bg-blue-400' :
                    dot.resolved ? 'bg-green-400' : 'bg-gray-100'
                  ]"
                  :title="`第${dot.chapterNum}章${dot.planted ? ' (埋设)' : ''}${dot.resolved ? ' (回收)' : ''}`"
                />
              </div>

              <!-- 展开详情 -->
              <n-collapse v-if="thread.plantedChapter || thread.resolvedChapter || thread.notes" class="mt-1">
                <n-collapse-item title="详情" name="detail">
                  <div class="text-xs text-gray-500 space-y-1">
                    <div v-if="thread.plantedChapter">埋设章节：第 {{ thread.plantedChapter }} 章</div>
                    <div v-if="thread.resolvedChapter">回收章节：第 {{ thread.resolvedChapter }} 章</div>
                    <div v-if="thread.notes">备注：{{ thread.notes }}</div>
                  </div>
                </n-collapse-item>
              </n-collapse>
            </n-card>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.thread-card {
  cursor: default;
}
</style>

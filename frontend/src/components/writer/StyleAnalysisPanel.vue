<script setup>
import { computed } from 'vue'
import { NModal, NCard, NButton } from 'naive-ui'
import { useMemoryStore } from '@/stores/memoryStore'

const props = defineProps({
  projectId: { type: String, required: true }
})

const emit = defineEmits(['close'])

const memoryStore = useMemoryStore()

const result = computed(() => memoryStore.lastStyleAnalysis)

const colors = {
  high: '#22c55e',
  medium: '#eab308',
  low: '#ef4444'
}

function barColor(value) {
  const scores = { '短句': 1, '长句': 3, '混合': 2, '口语化': 1, '书面化': 3, '文学化': 2, '快': 3, '慢': 1, '中等': 2, '多变': 2, '少': 1, '中': 2, '多': 3, '无': 0 }
  return colors.medium
}

function barWidth(value) {
  return value ? '70%' : '30%'
}

</script>

<template>
  <n-modal
    :show="true"
    preset="card"
    title="风格分析"
    style="width: 560px; max-height: 80vh;"
    @close="emit('close')"
  >
    <div v-if="memoryStore.lastStyleAnalysis" class="space-y-4">
      <!-- 一致性评分 -->
      <div class="text-center">
        <div class="text-3xl font-bold" :class="result.styleConsistencyScore >= 7 ? 'text-green-600' : result.styleConsistencyScore >= 5 ? 'text-yellow-600' : 'text-red-600'">
          {{ result.styleConsistencyScore }}/10
        </div>
        <div class="text-xs text-gray-400">风格一致性评分</div>
      </div>

      <!-- 7 维度指标 -->
      <n-card size="small" title="风格维度">
        <div class="space-y-2">
          <div v-for="(value, key) in result.styleFeatures" :key="key" class="flex items-center gap-2">
            <span class="text-xs text-gray-500 w-20 flex-shrink-0">
              {{ { sentenceLength: '句长', rhythm: '节奏', vocabulary: '词汇', tone: '语调', dialogueRatio: '对话占比', descriptionDensity: '描写密度', innerMonologueUsage: '内心独白' }[key] || key }}
            </span>
            <div class="flex-1 h-4 bg-gray-100 rounded overflow-hidden">
              <div
                class="h-full rounded transition-all"
                :style="{ width: barWidth(value), backgroundColor: barColor(value) }"
              />
            </div>
            <span class="text-xs text-gray-600 w-16 flex-shrink-0">{{ value }}</span>
          </div>
        </div>
      </n-card>

      <!-- 优点 -->
      <n-card v-if="result.strengths?.length" size="small" title="优点">
        <ul class="list-disc list-inside text-sm text-gray-600 space-y-0.5">
          <li v-for="(s, i) in result.strengths" :key="i">{{ s }}</li>
        </ul>
      </n-card>

      <!-- 弱项 -->
      <n-card v-if="result.weaknesses?.length" size="small" title="可改进">
        <ul class="list-disc list-inside text-sm text-gray-600 space-y-0.5">
          <li v-for="(w, i) in result.weaknesses" :key="i">{{ w }}</li>
        </ul>
      </n-card>

      <!-- 风格近似 -->
      <n-card v-if="result.comparables?.length" size="small" title="风格近似">
        <div class="flex flex-wrap gap-1">
          <span v-for="(c, i) in result.comparables" :key="i" class="text-xs bg-blue-50 text-blue-700 px-2 py-0.5 rounded">{{ c }}</span>
        </div>
      </n-card>

      <div class="flex justify-end gap-2">
        <n-button size="small" @click="emit('close')">关闭</n-button>
      </div>
    </div>

    <div v-else class="text-center text-gray-400 py-8">
      暂无分析结果
    </div>
  </n-modal>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  pacing: { type: Object, required: true }
})

const segments = computed(() => props.pacing.segments || [])

const maxTension = computed(() => {
  if (!segments.value.length) return 10
  return Math.max(...segments.value.map(s => s.tension || 0), 10)
})

function tensionColor(t) {
  const ratio = maxTension.value > 0 ? t / maxTension.value : 0
  if (ratio >= 0.8) return '#ef4444'
  if (ratio >= 0.6) return '#f97316'
  if (ratio >= 0.4) return '#eab308'
  if (ratio >= 0.2) return '#84cc16'
  return '#22c55e'
}

function climaxPosition(pct) {
  if (!pct && pct !== 0) return null
  return `${(pct * 100).toFixed(0)}%`
}
</script>

<template>
  <div class="space-y-4">
    <!-- 汇总 -->
    <div class="grid grid-cols-3 gap-3">
      <div class="text-center p-3 bg-gray-50 rounded">
        <div class="text-2xl font-bold text-gray-700">{{ pacing.avgTension || '-' }}</div>
        <div class="text-xs text-gray-400">平均张力</div>
      </div>
      <div class="text-center p-3 bg-gray-50 rounded">
        <div class="text-2xl font-bold text-blue-600">{{ climaxPosition(pacing.climaxAt) }}</div>
        <div class="text-xs text-gray-400">高潮位置</div>
      </div>
      <div class="text-center p-3 bg-gray-50 rounded">
        <div class="text-lg font-bold text-gray-700">{{ pacing.overallRhythm || '-' }}</div>
        <div class="text-xs text-gray-400">整体节奏</div>
      </div>
    </div>

    <!-- 张力柱状图 -->
    <div v-if="segments.length" class="p-4 bg-white rounded border">
      <div class="flex items-end gap-1 h-28">
        <div
          v-for="(seg, i) in segments"
          :key="i"
          class="flex-1 rounded-t transition-all cursor-default relative group"
          :style="{
            height: maxTension > 0 ? `${(seg.tension / maxTension) * 100}%` : '0%',
            backgroundColor: tensionColor(seg.tension),
            minHeight: '4px'
          }"
          :title="`${seg.label}: 张力 ${seg.tension}/10`"
        >
          <!-- 高潮标记 -->
          <div
            v-if="pacing.climaxAt !== undefined && Math.abs((i + 0.5) / segments.length - pacing.climaxAt) < (1 / segments.length / 2)"
            class="absolute -top-5 left-1/2 -translate-x-1/2 text-[10px] text-red-500 font-bold whitespace-nowrap"
          >
            高潮
          </div>
        </div>
      </div>
      <div class="flex gap-1 mt-1">
        <div
          v-for="(seg, i) in segments"
          :key="i"
          class="flex-1 text-[10px] text-gray-400 text-center truncate"
        >
          {{ seg.label?.slice(0, 4) }}
        </div>
      </div>
    </div>

    <!-- 段详情 -->
    <div v-if="segments.length" class="space-y-1">
      <div class="text-xs font-semibold text-gray-500 mb-1">段落详情</div>
      <div
        v-for="(seg, i) in segments"
        :key="i"
        class="flex items-center gap-2 text-xs"
      >
        <span
          class="w-6 h-6 rounded flex items-center justify-center text-white text-[10px] font-bold flex-shrink-0"
          :style="{ backgroundColor: tensionColor(seg.tension) }"
        >
          {{ seg.tension }}
        </span>
        <span class="text-gray-700">{{ seg.label }}</span>
        <span v-if="seg.note" class="text-gray-400 ml-auto">{{ seg.note }}</span>
      </div>
    </div>

    <!-- 转折点 -->
    <div v-if="pacing.turningPoints?.length">
      <div class="text-xs font-semibold text-gray-500 mb-1">转折点</div>
      <div
        v-for="(tp, i) in pacing.turningPoints"
        :key="i"
        class="flex items-center gap-2 text-xs text-gray-600"
      >
        <span class="text-blue-500">{{ climaxPosition(tp.at) }}</span>
        <span>{{ tp.label }}</span>
      </div>
    </div>

    <!-- 建议 -->
    <div v-if="pacing.suggestions?.length">
      <div class="text-xs font-semibold text-gray-500 mb-1">节奏建议</div>
      <div
        v-for="(s, i) in pacing.suggestions"
        :key="i"
        class="text-xs text-gray-600 flex gap-1"
      >
        <span class="text-yellow-500">•</span>
        <span>{{ s }}</span>
      </div>
    </div>
  </div>
</template>

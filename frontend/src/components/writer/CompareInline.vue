<script setup>
import { computed } from 'vue'
import { NButton, NTag } from 'naive-ui'
import { useCompareStore } from '@/stores/compareStore'
import { useProviderStore } from '@/stores/providerStore'

const emit = defineEmits(['load-version'])

const compareStore = useCompareStore()
const providerStore = useProviderStore()

const results = computed(() => {
  return Object.entries(compareStore.runningJobs)
    .filter(([, job]) => job.done && job.version)
    .map(([providerId, job]) => {
      const provider = providerStore.providers.find(p => p.id === providerId)
      return {
        providerId,
        providerName: provider?.name || '未知模型',
        version: job.version,
        content: job.content
      }
    })
})

function loadResult(result) {
  emit('load-version', result.version)
}

function getPreview(content) {
  if (!content) return '(空)'
  return content.slice(0, 100) + (content.length > 100 ? '...' : '')
}
</script>

<template>
  <div v-if="results.length > 0" class="compare-inline">
    <h4 class="text-xs font-semibold text-gray-500 mb-2">多模型对比结果</h4>
    <div class="space-y-2">
      <div
        v-for="r in results"
        :key="r.providerId"
        class="p-2 rounded border border-gray-200 hover:border-blue-300 cursor-pointer text-xs transition-colors"
        @click="loadResult(r)"
      >
        <div class="flex items-center justify-between mb-1">
          <n-tag size="tiny" type="info" :bordered="false">{{ r.providerName }}</n-tag>
        </div>
        <div class="text-gray-600 line-clamp-2">{{ getPreview(r.content) }}</div>
      </div>
    </div>
  </div>
</template>

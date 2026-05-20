<script setup>
import { computed } from 'vue'
import { NButton, NTag } from 'naive-ui'
import { useCompareStore } from '@/stores/compareStore'
import { useProviderStore } from '@/stores/providerStore'

const emit = defineEmits(['load-version'])

const compareStore = useCompareStore()
const providerStore = useProviderStore()

const modelResults = computed(() => {
  return Object.entries(compareStore.runningJobs)
    .filter(([, job]) => job.done && job.version)
    .map(([providerId, job]) => {
      const provider = providerStore.providers.find(p => p.id === providerId)
      return {
        id: `job-${providerId}`,
        label: provider?.name || '未知模型',
        version: job.version,
        content: job.content || job.version?.content || ''
      }
    })
})

const selectedVersions = computed(() =>
  compareStore.comparisonVersions.map(version => ({
    id: version.id,
    label: versionLabel(version),
    version,
    content: version.content || ''
  }))
)

const results = computed(() => {
  const map = new Map()
  for (const item of [...modelResults.value, ...selectedVersions.value]) {
    map.set(item.version?.id || item.id, item)
  }
  return [...map.values()]
})

function loadResult(result) {
  emit('load-version', result.version)
}

function getPreview(content) {
  if (!content) return '(空)'
  return content.slice(0, 100) + (content.length > 100 ? '...' : '')
}

function versionLabel(version) {
  if (version.versionType === 'correction_candidate') return '纠偏候选'
  if (version.versionType === 'final') return '定稿版本'
  if (version.versionType === 'ai_candidate') return 'AI 候选'
  return version.versionType || '候选版本'
}
</script>

<template>
  <div v-if="results.length > 0" class="compare-inline">
    <h4 class="text-xs font-semibold text-gray-500 mb-2">对比池</h4>
    <div class="space-y-2">
      <div
        v-for="result in results"
        :key="result.id"
        class="p-2 rounded border border-gray-200 hover:border-blue-300 cursor-pointer text-xs transition-colors"
        @click="loadResult(result)"
      >
        <div class="flex items-center justify-between mb-1">
          <n-tag size="tiny" type="info" :bordered="false">{{ result.label }}</n-tag>
          <n-button size="tiny" quaternary @click.stop="compareStore.toggleVersion(result.version)">移除</n-button>
        </div>
        <div class="text-gray-600 line-clamp-2">{{ getPreview(result.content) }}</div>
      </div>
    </div>
  </div>
</template>

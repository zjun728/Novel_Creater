<script setup>
import { computed } from 'vue'
import { NButton, NTag, NPopconfirm, NEmpty } from 'naive-ui'

const props = defineProps({
  versions: { type: Array, default: () => [] },
  currentVersionId: { type: String, default: null },
  finalVersionId: { type: String, default: '' },
  comparisonVersionIds: { type: Array, default: () => [] },
  finalizeDisabled: { type: Boolean, default: false }
})

const emit = defineEmits(['load', 'delete', 'finalize', 'compare'])

const comparisonIds = computed(() => new Set(props.comparisonVersionIds))
const hasFinalVersion = computed(() => !!props.finalVersionId || props.versions.some(version => version.versionType === 'final'))

const versionTypeLabels = {
  ai_candidate: 'AI 候选',
  correction_candidate: '纠偏候选',
  user_draft: '用户草稿',
  polished: '润色版',
  final: '定稿',
  archived: '存档'
}

const versionTypeColors = {
  ai_candidate: 'info',
  correction_candidate: 'warning',
  user_draft: 'default',
  polished: 'warning',
  final: 'success',
  archived: 'default'
}

function formatDate(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

function previewText(content, maxLen = 80) {
  if (!content) return '(空)'
  return content.length > maxLen ? content.slice(0, maxLen) + '...' : content
}

function sourceBrief(version) {
  const brief = String(version.promptBrief || version.prompt_brief || '')
    .replace(/\n?\[correctionTaskId:[0-9a-fA-F-]{36}\]/g, '')
    .trim()
  if (!brief) return ''
  return brief.length > 80 ? brief.slice(0, 80) + '...' : brief
}
</script>

<template>
  <div class="version-list">
    <h4 class="text-sm font-semibold text-gray-500 mb-2">版本列表</h4>

    <n-empty v-if="versions.length === 0" description="暂无版本" size="small" class="py-4" />

    <div class="space-y-2 max-h-80 overflow-y-auto">
      <div
        v-for="version in versions"
        :key="version.id"
        :class="[
          'p-2 rounded border text-xs cursor-pointer transition-colors',
          version.id === currentVersionId ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
        ]"
        @click="emit('load', version)"
      >
        <div class="flex items-center justify-between mb-1">
          <n-tag :type="versionTypeColors[version.versionType]" size="tiny" :bordered="false">
            {{ versionTypeLabels[version.versionType] || version.versionType }}
          </n-tag>
          <span class="text-gray-400">{{ formatDate(version.createdAt) }}</span>
        </div>

        <div v-if="sourceBrief(version)" class="text-[11px] text-amber-700 bg-amber-50 border border-amber-100 rounded px-2 py-1 mb-1">
          {{ sourceBrief(version) }}
        </div>

        <div class="text-gray-600 line-clamp-2">{{ previewText(version.content) }}</div>

        <div class="flex justify-end gap-1 mt-1">
          <n-button
            size="tiny"
            quaternary
            :type="comparisonIds.has(version.id) ? 'success' : 'default'"
            @click.stop="emit('compare', version)"
          >
            {{ comparisonIds.has(version.id) ? '已加入对比' : '加入对比' }}
          </n-button>
          <n-button
            v-if="version.versionType === 'final' || version.id === finalVersionId"
            size="tiny"
            quaternary
            type="success"
            disabled
            @click.stop
          >
            已定稿
          </n-button>
          <n-popconfirm
            v-else-if="!hasFinalVersion"
            @positive-click="emit('finalize', version)"
          >
            <template #trigger>
              <n-button size="tiny" quaternary type="success" :disabled="finalizeDisabled" @click.stop>定稿</n-button>
            </template>
            确认将此版本设为定稿？
          </n-popconfirm>
          <n-button
            v-else
            size="tiny"
            quaternary
            disabled
            @click.stop
          >
            已锁定
          </n-button>
          <n-popconfirm
            v-if="!hasFinalVersion"
            @positive-click="emit('delete', version)"
          >
            <template #trigger>
              <n-button size="tiny" quaternary type="error" @click.stop>删除</n-button>
            </template>
            确认删除此版本？
          </n-popconfirm>
          <n-button
            v-else
            size="tiny"
            quaternary
            type="error"
            disabled
            @click.stop
          >
            删除
          </n-button>
        </div>
      </div>
    </div>
  </div>
</template>

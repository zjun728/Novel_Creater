<script setup>
import { NButton, NCard, NTag, NSpace, NPopconfirm, NEmpty } from 'naive-ui'

defineProps({
  versions: { type: Array, default: () => [] },
  currentVersionId: { type: String, default: null }
})

const emit = defineEmits(['load', 'delete', 'finalize'])

const versionTypeLabels = {
  ai_candidate: 'AI 候选',
  user_draft: '用户草稿',
  polished: '润色版',
  final: '定稿',
  archived: '存档'
}

const versionTypeColors = {
  ai_candidate: 'info',
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
</script>

<template>
  <div class="version-list">
    <h4 class="text-sm font-semibold text-gray-500 mb-2">版本列表</h4>

    <n-empty v-if="versions.length === 0" description="暂无版本" size="small" class="py-4">
    </n-empty>

    <div class="space-y-2 max-h-80 overflow-y-auto">
      <div
        v-for="v in versions"
        :key="v.id"
        :class="[
          'p-2 rounded border text-xs cursor-pointer transition-colors',
          v.id === currentVersionId ? 'border-blue-400 bg-blue-50' : 'border-gray-200 hover:border-gray-300'
        ]"
        @click="emit('load', v)"
      >
        <div class="flex items-center justify-between mb-1">
          <n-tag :type="versionTypeColors[v.versionType]" size="tiny" :bordered="false">
            {{ versionTypeLabels[v.versionType] || v.versionType }}
          </n-tag>
          <span class="text-gray-400">{{ formatDate(v.createdAt) }}</span>
        </div>
        <div class="text-gray-600 line-clamp-2">{{ previewText(v.content) }}</div>
        <div class="flex justify-end gap-1 mt-1">
          <n-popconfirm
            v-if="v.versionType !== 'final'"
            @positive-click="emit('finalize', v)"
          >
            <template #trigger>
              <n-button size="tiny" quaternary type="success">定稿</n-button>
            </template>
            确认将此版本设为定稿？
          </n-popconfirm>
          <n-popconfirm @positive-click="emit('delete', v)">
            <template #trigger>
              <n-button size="tiny" quaternary type="error">删除</n-button>
            </template>
            确认删除此版本？
          </n-popconfirm>
        </div>
      </div>
    </div>
  </div>
</template>

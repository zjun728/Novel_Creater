<script setup>
import { NButton, NSpace, NDivider, NPopconfirm } from 'naive-ui'

defineProps({
  generating: { type: Boolean, default: false },
  hasContent: { type: Boolean, default: false },
  hasSelection: { type: Boolean, default: false }
})

const emit = defineEmits([
  'generate',
  'multiVariant',
  'compare',
  'continue',
  'expand',
  'compress',
  'rewriteDialog',
  'rewriteConflict',
  'rewritePsychology',
  'rewriteWebStyle',
  'rewriteLiterary',
  'polish'
])
</script>

<template>
  <div class="ai-action-panel">
    <h4 class="text-sm font-semibold text-gray-500 mb-2">AI 操作</h4>

    <!-- 章节生成 -->
    <div class="mb-3">
      <p class="text-xs text-gray-400 mb-1">章节生成</p>
      <n-space vertical size="small">
        <div class="flex gap-1">
          <n-button
            size="small"
            type="primary"
            style="flex: 1"
            :loading="generating"
            @click="emit('generate')"
          >
            生成本章
          </n-button>
          <n-button
            size="small"
            type="info"
            @click="emit('compare')"
          >
            对比
          </n-button>
        </div>
        <n-button
          size="small"
          block
          :disabled="!hasContent"
          @click="emit('multiVariant')"
        >
          生成多候选版本
        </n-button>
      </n-space>
    </div>

    <n-divider style="margin: 8px 0" />

    <!-- 续写与调整 -->
    <div class="mb-3">
      <p class="text-xs text-gray-400 mb-1">续写与调整</p>
      <n-space vertical size="small">
        <n-button
          size="small"
          block
          :disabled="!hasContent"
          @click="emit('continue')"
        >
          ✍️ 继续写
        </n-button>
        <n-button
          size="small"
          block
          :disabled="!hasSelection"
          @click="emit('expand')"
        >
          📝 扩写场景
        </n-button>
        <n-button
          size="small"
          block
          :disabled="!hasSelection"
          @click="emit('compress')"
        >
          📏 压缩场景
        </n-button>
      </n-space>
    </div>

    <n-divider style="margin: 8px 0" />

    <!-- 选区改写 -->
    <div class="mb-3">
      <p class="text-xs text-gray-400 mb-1">选区改写</p>
      <n-space vertical size="small">
        <n-button size="small" block :disabled="!hasSelection" @click="emit('rewriteDialog')">
          💬 改对白
        </n-button>
        <n-button size="small" block :disabled="!hasSelection" @click="emit('rewriteConflict')">
          ⚡ 加强冲突
        </n-button>
        <n-button size="small" block :disabled="!hasSelection" @click="emit('rewritePsychology')">
          🧠 加强心理
        </n-button>
        <n-button size="small" block :disabled="!hasSelection" @click="emit('rewriteWebStyle')">
          📱 改网感
        </n-button>
        <n-button size="small" block :disabled="!hasSelection" @click="emit('rewriteLiterary')">
          📖 改文学化
        </n-button>
        <n-button size="small" block :disabled="!hasSelection" @click="emit('polish')">
          ✨ 润色
        </n-button>
      </n-space>
    </div>
  </div>
</template>

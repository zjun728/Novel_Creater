<script setup>
import { NButton, NSpace, NDivider, NPopconfirm } from 'naive-ui'

defineProps({
  generating: { type: Boolean, default: false },
  planning: { type: Boolean, default: false },
  activeAction: { type: String, default: '' },
  contextReady: { type: Boolean, default: true },
  disabledReason: { type: String, default: '' },
  hasBeatPlan: { type: Boolean, default: false },
  hasContent: { type: Boolean, default: false },
  hasSelection: { type: Boolean, default: false },
  chapterFinalized: { type: Boolean, default: false }
})

const emit = defineEmits([
  'planBeats',
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
    <p v-if="!contextReady" class="text-xs text-amber-600 mb-2">
      {{ disabledReason || '创作上下文加载中，请稍后操作' }}
    </p>
    <p v-else-if="chapterFinalized" class="text-xs text-emerald-700 mb-2">
      本章已定稿，正文和小纲已锁定。
    </p>

    <!-- 章节生成 -->
    <div class="mb-3">
      <p class="text-xs text-gray-400 mb-1">章节生成</p>
      <n-space vertical size="small">
        <n-button
          size="small"
          block
          secondary
          :loading="planning"
          :disabled="generating || !contextReady || (chapterFinalized && !hasBeatPlan)"
          @click="emit('planBeats')"
        >
          {{ planning ? '生成小纲中' : hasBeatPlan ? '查看小纲' : '先做小纲' }}
        </n-button>
        <div class="flex gap-1">
          <n-button
            size="small"
            type="primary"
            style="flex: 1"
            :loading="activeAction === 'chapter' || planning"
            :disabled="generating || planning || !contextReady || chapterFinalized"
            @click="emit('generate')"
          >
            {{ planning ? '准备小纲' : '生成本章' }}
          </n-button>
          <n-button
            size="small"
            type="info"
            :disabled="generating || planning || !contextReady || chapterFinalized"
            @click="emit('compare')"
          >
            对比
          </n-button>
        </div>
        <n-button
          size="small"
          block
          :loading="activeAction === 'multi'"
          :disabled="generating || planning || !contextReady || chapterFinalized"
          @click="emit('multiVariant')"
        >
          基于小纲生成多版本
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
          :disabled="!hasContent || !contextReady || generating || chapterFinalized"
          @click="emit('continue')"
        >
          ✍️ 继续写
        </n-button>
        <n-button
          size="small"
          block
          :disabled="!hasSelection || !contextReady || generating || chapterFinalized"
          @click="emit('expand')"
        >
          📝 扩写场景
        </n-button>
        <n-button
          size="small"
          block
          :disabled="!hasSelection || generating || chapterFinalized"
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
        <n-button size="small" block :disabled="!hasSelection || !contextReady || generating || chapterFinalized" @click="emit('rewriteDialog')">
          💬 改对白
        </n-button>
        <n-button size="small" block :disabled="!hasSelection || !contextReady || generating || chapterFinalized" @click="emit('rewriteConflict')">
          ⚡ 加强冲突
        </n-button>
        <n-button size="small" block :disabled="!hasSelection || !contextReady || generating || chapterFinalized" @click="emit('rewritePsychology')">
          🧠 加强心理
        </n-button>
        <n-button size="small" block :disabled="!hasSelection || !contextReady || generating || chapterFinalized" @click="emit('rewriteWebStyle')">
          📱 改网感
        </n-button>
        <n-button size="small" block :disabled="!hasSelection || !contextReady || generating || chapterFinalized" @click="emit('rewriteLiterary')">
          📖 改文学化
        </n-button>
        <n-button size="small" block :disabled="!hasSelection || !contextReady || generating || chapterFinalized" @click="emit('polish')">
          ✨ 去 AI 腔/润色
        </n-button>
      </n-space>
    </div>
  </div>
</template>

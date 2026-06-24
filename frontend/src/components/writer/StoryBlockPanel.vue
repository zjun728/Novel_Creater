<script setup>
import { computed } from 'vue'
import { NButton, NCard, NEmpty, NSpace, NTag } from 'naive-ui'
import { canEditRemainingStage } from '@/utils/storyBlockSnapshot'

const props = defineProps({
  block: { type: Object, default: null },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits([
  'updateRemainingStages',
  'splitUnfinalizedContent',
  'closeBlock',
  'openNewBlock',
  'confirmBlock'
])

const completedStages = computed(() =>
  (props.block?.stagePlan || []).filter(stage => stage.status === 'completed')
)

const remainingStages = computed(() =>
  (props.block?.stagePlan || []).filter(stage => stage.status !== 'completed')
)

const editableStageCount = computed(() =>
  remainingStages.value.filter(canEditRemainingStage).length
)

const requiresReview = computed(() => Boolean(props.block?.lockState?.requiresReview))
</script>

<template>
  <n-card size="small" class="story-block-panel" :bordered="false">
    <template #header>
      <div class="story-block-header">
        <span>当前故事块快捷操作</span>
        <n-tag v-if="block?.status" size="tiny" :bordered="false">
          {{ block.status }}
        </n-tag>
      </div>
    </template>

    <n-empty v-if="!block" size="small" description="尚未创建当前故事块">
      <template #extra>
        <p v-if="loading" class="story-block-loading-text">正在生成故事块规划，请稍候</p>
        <n-button size="tiny" type="primary" :loading="loading" :disabled="disabled || loading" @click="emit('openNewBlock')">
          开启新故事块
        </n-button>
      </template>
    </n-empty>

    <div v-else class="story-block-body">
      <p v-if="loading" class="story-block-loading-text">正在生成故事块规划，请稍候</p>
      <section class="story-block-section">
        <div class="story-block-section-title">锁定信息</div>
        <div class="story-block-line">
          <span>目标</span>
          <p>{{ block.goal || '未填写' }}</p>
        </div>
        <div class="story-block-line">
          <span>入场</span>
          <p>{{ block.entryState || '未填写' }}</p>
        </div>
        <div class="story-block-line">
          <span>已完成</span>
          <p v-if="completedStages.length">{{ completedStages.map(stage => stage.purpose || stage.id).join('；') }}</p>
          <p v-else>暂无</p>
        </div>
        <div class="story-block-line">
          <span>引用章节</span>
          <p v-if="block.chapterRefs?.length">{{ block.chapterRefs.join('、') }}</p>
          <p v-else>暂无</p>
        </div>
      </section>

      <section class="story-block-section">
        <div class="story-block-section-title">滚动信息</div>
        <div class="story-block-line">
          <span>故事功能</span>
          <p>{{ block.storyFunction || '未填写' }}</p>
        </div>
        <div class="story-block-line">
          <span>下一阶段</span>
          <p>{{ block.nextStageSuggestion || remainingStages[0]?.purpose || '暂无建议' }}</p>
        </div>
        <div class="story-block-line">
          <span>未解决</span>
          <p v-if="block.unresolvedQuestions?.length">{{ block.unresolvedQuestions.join('；') }}</p>
          <p v-else>暂无</p>
        </div>
        <div class="story-block-line">
          <span>可更新阶段</span>
          <p>{{ editableStageCount }} 个</p>
        </div>
      </section>

      <n-space vertical size="small">
        <n-button
          v-if="requiresReview"
          size="tiny"
          block
          type="warning"
          secondary
          :disabled="disabled || loading"
          @click="emit('confirmBlock')"
        >
          确认故事块
        </n-button>
        <n-button
          size="tiny"
          block
          secondary
          :disabled="disabled || loading || editableStageCount === 0"
          @click="emit('updateRemainingStages')"
        >
          更新后续阶段
        </n-button>
        <n-button
          size="tiny"
          block
          secondary
          :disabled="disabled || loading"
          @click="emit('splitUnfinalizedContent')"
        >
          拆分未定稿内容
        </n-button>
        <n-button
          size="tiny"
          block
          secondary
          :disabled="disabled || loading"
          @click="emit('closeBlock')"
        >
          提前结束当前块
        </n-button>
        <n-button
          size="tiny"
          block
          type="primary"
          secondary
          :disabled="disabled || loading"
          @click="emit('openNewBlock')"
        >
          开启新故事块
        </n-button>
      </n-space>
    </div>
  </n-card>
</template>

<style scoped>
.story-block-panel {
  background: #ffffff;
}

.story-block-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 13px;
  font-weight: 700;
  color: #374151;
}

.story-block-body {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.story-block-loading-text {
  margin: 0 0 8px;
  color: #2563eb;
  font-size: 12px;
  line-height: 1.5;
}

.story-block-section {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 8px;
  background: #f9fafb;
}

.story-block-section-title {
  margin-bottom: 6px;
  font-size: 11px;
  font-weight: 700;
  color: #6b7280;
}

.story-block-line {
  display: grid;
  grid-template-columns: 68px minmax(0, 1fr);
  gap: 6px;
  margin-top: 5px;
  font-size: 11px;
  line-height: 1.5;
}

.story-block-line span {
  color: #6b7280;
}

.story-block-line p {
  margin: 0;
  color: #374151;
  word-break: break-word;
}
</style>

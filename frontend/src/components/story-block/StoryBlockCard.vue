<script setup>
import { computed, reactive, ref } from 'vue'
import { NAlert, NButton, NInput, NModal, NTag } from 'naive-ui'
import StoryBlockStageList from './StoryBlockStageList.vue'

const props = defineProps({
  block: { type: Object, required: true },
  active: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits([
  'confirmBlock',
  'updateRemainingStages',
  'closeBlock',
  'openNewBlock',
  'saveStageEdit'
])

const expanded = ref(false)
const editingStage = ref(null)
const stageForm = reactive({
  purpose: '',
  sceneOrAction: '',
  choice: '',
  costOrConsequence: ''
})

const statusLabels = {
  active: '进行中',
  completed: '已完成',
  closed: '已提前结束',
  paused: '暂停'
}

const requiresReview = computed(() => Boolean(props.block?.lockState?.requiresReview))
const isActiveBlock = computed(() => props.block?.status === 'active')

const coverChapters = computed(() => formatChapterRanges(props.block?.chapterRefs || []))

const unresolvedSummary = computed(() => {
  const items = props.block?.unresolvedQuestions || []
  if (!items.length) return '暂无'
  if (items.length <= 2) return items.join('；')
  return `${items.length} 项：${items.slice(0, 2).join('；')}`
})

const editableStageCount = computed(() =>
  (props.block?.stagePlan || []).filter(stage => canEditStage(stage)).length
)

const updateDisabledReason = computed(() =>
  editableStageCount.value === 0 ? '当前块没有可更新的未执行阶段。' : ''
)

function canEditStage(stage = {}) {
  if (!isActiveBlock.value) return false
  if (stage.status && stage.status !== 'planned') return false
  if (stage.completedChapterNum) return false
  if (stage.locked || stage.lockedByBeatPlan || stage.lockedByFinalChapter) return false
  if (Array.isArray(stage.chapterRefs) && stage.chapterRefs.length) return false
  if (stage.inProgress || stage.current || stage.isCurrent) return false
  return true
}

function openStageEditor(stage) {
  if (!canEditStage(stage)) return
  editingStage.value = stage
  stageForm.purpose = stage.purpose || stage.stagePurpose || stage.goal || ''
  stageForm.sceneOrAction = stage.sceneOrAction || stage.action || stage.description || ''
  stageForm.choice = stage.choice || ''
  stageForm.costOrConsequence = stage.costOrConsequence || stage.consequence || stage.cost || ''
}

function saveStageEditor() {
  if (!editingStage.value) return
  emit('saveStageEdit', {
    block: props.block,
    stageId: editingStage.value.id || editingStage.value.stageId,
    patch: { ...stageForm }
  })
  editingStage.value = null
}

function formatChapterRanges(refs = []) {
  const nums = refs
    .map(ref => Number(ref?.chapterNum || ref))
    .filter(num => Number.isFinite(num) && num > 0)
    .sort((a, b) => a - b)
  if (!nums.length) return '暂无'

  const ranges = []
  let start = nums[0]
  let prev = nums[0]
  for (const num of nums.slice(1)) {
    if (num === prev + 1) {
      prev = num
      continue
    }
    ranges.push(start === prev ? `第${start}章` : `第${start}-${prev}章`)
    start = num
    prev = num
  }
  ranges.push(start === prev ? `第${start}章` : `第${start}-${prev}章`)
  return ranges.join('、')
}
</script>

<template>
  <article class="story-block-card" :class="{ active }">
    <div class="story-block-card-main">
      <div class="story-block-card-title-row">
        <div class="story-block-card-title">
          {{ block.title || `故事块 ${block.blockNum || ''}` }}
        </div>
        <div class="story-block-card-tags">
          <n-tag v-if="active" type="success" size="small" :bordered="false">active</n-tag>
          <n-tag size="small" :bordered="false">{{ statusLabels[block.status] || block.status }}</n-tag>
          <n-tag v-if="requiresReview" type="warning" size="small" :bordered="false">需确认故事块</n-tag>
        </div>
      </div>

      <n-alert v-if="requiresReview" type="warning" :show-icon="false" class="story-block-review-alert">
        这是 AI 规划失败后的人工占位故事块，需要确认故事块后再继续生成小纲。
      </n-alert>

      <n-alert v-if="block.lockState?.closeReasonWarning" type="warning" :show-icon="false" class="story-block-review-alert">
        {{ block.lockState.closeReasonWarning }}
      </n-alert>

      <div class="story-block-card-grid">
        <div>
          <span>故事块目标</span>
          <p>{{ block.goal || '暂无' }}</p>
        </div>
        <div>
          <span>故事功能</span>
          <p>{{ block.storyFunction || '暂无' }}</p>
        </div>
        <div>
          <span>入场状态</span>
          <p>{{ block.entryState || '暂无' }}</p>
        </div>
        <div>
          <span>主要压力</span>
          <p>{{ block.mainPressure || '暂无' }}</p>
        </div>
        <div>
          <span>覆盖章节</span>
          <p>{{ coverChapters }}</p>
        </div>
        <div>
          <span>下一阶段</span>
          <p>{{ block.nextStageSuggestion || '暂无' }}</p>
        </div>
        <div class="span-two">
          <span>未解决问题</span>
          <p>{{ unresolvedSummary }}</p>
        </div>
      </div>
    </div>

    <div class="story-block-card-actions">
      <n-button size="small" secondary @click="expanded = !expanded">
        {{ expanded ? '收起详情' : '查看详情' }}
      </n-button>
      <n-button
        v-if="requiresReview"
        size="small"
        type="warning"
        secondary
        :disabled="disabled"
        @click="emit('confirmBlock', block)"
      >
        确认故事块
      </n-button>
      <n-button
        v-if="isActiveBlock"
        size="small"
        secondary
        :disabled="disabled || editableStageCount === 0"
        :title="updateDisabledReason"
        @click="expanded = true"
      >
        编辑未执行阶段
      </n-button>
      <n-button
        v-if="isActiveBlock"
        size="small"
        secondary
        :disabled="disabled || editableStageCount === 0"
        :title="updateDisabledReason"
        @click="emit('updateRemainingStages', block)"
      >
        AI 更新后续阶段
      </n-button>
      <n-button
        v-if="isActiveBlock"
        size="small"
        secondary
        :disabled="disabled"
        @click="emit('closeBlock', block)"
      >
        提前结束当前块
      </n-button>
      <n-button
        v-if="isActiveBlock"
        size="small"
        type="primary"
        secondary
        :disabled="disabled"
        @click="emit('openNewBlock', block)"
      >
        结束并开启新块
      </n-button>
      <n-button
        v-else-if="block.status === 'closed'"
        size="small"
        type="primary"
        secondary
        :disabled="disabled"
        @click="emit('openNewBlock', block)"
      >
        基于未执行内容开启新块
      </n-button>
    </div>

    <StoryBlockStageList
      v-if="expanded"
      class="story-block-stages"
      :stages="block.stagePlan || []"
      :block-status="block.status"
      @edit-stage="openStageEditor"
    />

    <n-modal
      :show="Boolean(editingStage)"
      preset="card"
      title="编辑未执行阶段"
      style="width: 520px; max-width: 92vw;"
      @update:show="value => { if (!value) editingStage = null }"
    >
      <div class="stage-edit-form">
        <label>
          <span>阶段目的</span>
          <n-input v-model:value="stageForm.purpose" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
        </label>
        <label>
          <span>场景/行动</span>
          <n-input v-model:value="stageForm.sceneOrAction" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
        </label>
        <label>
          <span>人物选择</span>
          <n-input v-model:value="stageForm.choice" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
        </label>
        <label>
          <span>代价/后果</span>
          <n-input v-model:value="stageForm.costOrConsequence" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
        </label>
      </div>
      <template #footer>
        <div class="modal-actions">
          <n-button size="small" @click="editingStage = null">取消</n-button>
          <n-button size="small" type="primary" :disabled="disabled" @click="saveStageEditor">保存阶段</n-button>
        </div>
      </template>
    </n-modal>
  </article>
</template>

<style scoped>
.story-block-card {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 12px;
  background: #ffffff;
}

.story-block-card.active {
  border-color: #16a34a;
  box-shadow: inset 3px 0 0 #16a34a;
}

.story-block-card-title-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.story-block-card-title {
  color: #1f2937;
  font-size: 15px;
  font-weight: 700;
}

.story-block-card-tags,
.story-block-card-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.story-block-review-alert {
  margin-top: 10px;
}

.story-block-card-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 14px;
  margin-top: 12px;
}

.story-block-card-grid span {
  display: block;
  margin-bottom: 3px;
  color: #6b7280;
  font-size: 12px;
}

.story-block-card-grid p {
  margin: 0;
  color: #374151;
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
}

.span-two {
  grid-column: span 2;
}

.story-block-card-actions {
  margin-top: 12px;
}

.story-block-stages {
  margin-top: 12px;
}

.stage-edit-form {
  display: grid;
  gap: 12px;
}

.stage-edit-form label {
  display: grid;
  gap: 5px;
  color: #4b5563;
  font-size: 13px;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 768px) {
  .story-block-card-grid {
    grid-template-columns: 1fr;
  }

  .span-two {
    grid-column: auto;
  }
}
</style>

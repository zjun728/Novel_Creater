<script setup>
import { computed } from 'vue'
import { NButton, NEmpty, NTag } from 'naive-ui'

const props = defineProps({
  stages: { type: Array, default: () => [] },
  blockStatus: { type: String, default: 'active' },
  currentStageId: { type: String, default: '' }
})

const emit = defineEmits(['editStage'])

const normalizedStages = computed(() =>
  (props.stages || []).map((stage, index) => {
    const statusInfo = resolveStageStatus(stage)
    return {
      ...stage,
      displayId: stage.id || stage.stageId || `stage-${index + 1}`,
      purpose: stage.purpose || stage.stagePurpose || stage.goal || '未填写阶段目的',
      action: stage.sceneOrAction || stage.action || stage.description || '未填写场景/行动',
      choice: stage.choice || '未填写人物选择',
      cost: stage.costOrConsequence || stage.consequence || stage.cost || '未填写代价/后果',
      displayStatus: statusInfo.status,
      displayLabel: statusInfo.label,
      displayHint: statusInfo.hint,
      editable: statusInfo.editable
    }
  })
)

function resolveStageStatus(stage) {
  const rawStatus = stage.status || 'planned'
  if (rawStatus === 'completed' || stage.completedChapterNum) {
    return { status: 'completed', label: '已完成', editable: false }
  }
  if (hasOutlineOrChapterRefs(stage)) {
    return {
      status: 'locked',
      label: '已用于小纲 / 已锁定',
      hint: '请到对应小纲中调整',
      editable: false
    }
  }
  if (isCurrentStage(stage)) {
    return { status: 'in_progress', label: '进行中', editable: false }
  }
  if (props.blockStatus !== 'active') {
    return { status: 'closed', label: '未执行，随块结束', editable: false }
  }
  if (rawStatus === 'invalidated') {
    return { status: 'invalidated', label: '已失效，随块结束', editable: false }
  }
  if (rawStatus === 'skipped' || rawStatus === 'closed' || rawStatus === 'closed_unexecuted' || rawStatus === 'skipped_by_block_close') {
    return { status: rawStatus, label: '未执行，随块结束', editable: false }
  }
  if (isExplicitlyLocked(stage)) {
    return { status: 'locked', label: '已锁定', editable: false }
  }
  return { status: 'planned', label: '未执行', editable: true }
}

function hasOutlineOrChapterRefs(stage) {
  return Boolean(stage.lockedByBeatPlan) ||
    Boolean(stage.lockedByFinalChapter) ||
    (Array.isArray(stage.chapterRefs) && stage.chapterRefs.length > 0)
}

function isCurrentStage(stage) {
  const stageId = String(stage.id || stage.stageId || '')
  return Boolean(stage.inProgress || stage.current || stage.isCurrent) ||
    (props.currentStageId && stageId === String(props.currentStageId))
}

function isExplicitlyLocked(stage) {
  return Boolean(stage.locked)
}

function isStageReadonly(stage) {
  return !stage.editable
}

function stageStatusType(status) {
  if (status === 'completed') return 'success'
  if (status === 'locked' || status === 'in_progress') return 'warning'
  if (status === 'skipped' || status === 'closed' || status === 'closed_unexecuted' || status === 'skipped_by_block_close' || status === 'invalidated') return 'default'
  return 'info'
}

function formatChapterRefs(stage = {}) {
  const refs = stage.chapterRefs || []
  const completedChapterNum = stage.completedChapterNum
  const merged = completedChapterNum && !refs.includes(completedChapterNum)
    ? [...refs, completedChapterNum]
    : refs
  if (!merged.length) return ''
  return merged.map(ref => `第${ref.chapterNum || ref}章`).join('、')
}
</script>

<template>
  <div class="story-block-stage-list">
    <p class="stage-list-note">
      阶段不是章节。阶段是剧情推进步骤，不等于章节。一章可以完成多个阶段，一个阶段也可以跨章节。已被小纲或定稿章节使用的阶段会自动锁定。
    </p>

    <n-empty v-if="!normalizedStages.length" size="small" description="暂无阶段规划" />

    <div
      v-for="(stage, index) in normalizedStages"
      :key="stage.displayId"
      class="story-block-stage"
      :class="{ 'is-locked': isStageReadonly(stage), 'is-editable': stage.editable }"
    >
      <div class="stage-heading">
        <div class="stage-title">阶段 {{ index + 1 }}</div>
        <div class="stage-tags">
          <n-tag size="tiny" :type="stageStatusType(stage.displayStatus)" :bordered="false">
            {{ stage.displayLabel }}
          </n-tag>
          <n-tag v-if="isStageReadonly(stage)" size="tiny" type="warning" :bordered="false">
            只读
          </n-tag>
          <n-button
            v-if="stage.editable"
            size="tiny"
            secondary
            @click="emit('editStage', stage)"
          >
            编辑
          </n-button>
        </div>
      </div>

      <p v-if="stage.displayHint" class="stage-hint">{{ stage.displayHint }}</p>

      <dl class="stage-fields">
        <div>
          <dt>阶段目的</dt>
          <dd>{{ stage.purpose }}</dd>
        </div>
        <div>
          <dt>场景/行动</dt>
          <dd>{{ stage.action }}</dd>
        </div>
        <div>
          <dt>人物选择</dt>
          <dd>{{ stage.choice }}</dd>
        </div>
        <div>
          <dt>代价/后果</dt>
          <dd>{{ stage.cost }}</dd>
        </div>
        <div v-if="formatChapterRefs(stage)">
          <dt>完成/引用</dt>
          <dd>{{ formatChapterRefs(stage) }}</dd>
        </div>
      </dl>
    </div>
  </div>
</template>

<style scoped>
.story-block-stage-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.stage-list-note {
  margin: 0;
  border: 1px solid #dbeafe;
  border-radius: 6px;
  background: #eff6ff;
  padding: 8px 10px;
  color: #475569;
  font-size: 12px;
  line-height: 1.6;
}

.story-block-stage {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 10px;
  background: #ffffff;
}

.story-block-stage.is-locked {
  background: #fafafa;
}

.story-block-stage.is-editable {
  border-color: #bfdbfe;
}

.stage-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
}

.stage-title {
  font-size: 12px;
  font-weight: 700;
  color: #374151;
}

.stage-tags {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
}

.stage-hint {
  margin: -2px 0 8px;
  color: #64748b;
  font-size: 12px;
}

.stage-fields {
  display: grid;
  gap: 6px;
  margin: 0;
}

.stage-fields div {
  display: grid;
  grid-template-columns: 72px minmax(0, 1fr);
  gap: 8px;
}

.stage-fields dt {
  color: #6b7280;
  font-size: 12px;
}

.stage-fields dd {
  margin: 0;
  color: #374151;
  font-size: 12px;
  line-height: 1.55;
  word-break: break-word;
}
</style>

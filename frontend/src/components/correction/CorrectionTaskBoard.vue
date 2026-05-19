<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NCard, NEmpty, NSelect, NSpace, NTag } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import { CORRECTION_STATUS_OPTIONS, useCorrectionTaskStore } from '@/stores/correctionTaskStore'
import { useNovelStore } from '@/stores/novelStore'
import { useSettingStore } from '@/stores/settingStore'

const props = defineProps({
  projectId: { type: String, required: true },
  compact: { type: Boolean, default: false }
})

const taskStore = useCorrectionTaskStore()
const novelStore = useNovelStore()
const settingStore = useSettingStore()
const message = useAppMessage()
const statusFilter = ref('')

const statusOptions = computed(() => [
  { label: '全部', value: '' },
  ...CORRECTION_STATUS_OPTIONS
])

const visibleTasks = computed(() => {
  if (!statusFilter.value) return taskStore.tasks
  return taskStore.tasks.filter(task => task.status === statusFilter.value)
})

onMounted(loadData)
watch(() => props.projectId, loadData)

async function loadData() {
  if (props.projectId) {
    await taskStore.loadTasks(props.projectId)
  }
}

async function setStatus(task, status) {
  try {
    await taskStore.updateTask(props.projectId, task.id, { status })
    message.success('纠偏任务状态已更新')
  } catch (e) {
    message.error('更新纠偏任务失败：' + e.message)
  }
}

async function createCanonCandidate(task) {
  try {
    await novelStore.saveCanonFact({
      projectId: props.projectId,
      chapterNum: firstChapterRef(task),
      factType: task.issueType || 'plot',
      content: buildCandidateContent(task),
      relatedCharacters: normalizeRelatedItems(task),
      relatedPlotThreads: [],
      evidence: `来自${sourceLabel(task.sourceType)}纠偏任务：${task.title}`,
      confidence: 0.75,
      status: 'pending_review'
    })
    await setStatus(task, 'in_progress')
    message.success('已生成待确认 Canon 事实')
  } catch (e) {
    message.error('生成 Canon 事实失败：' + e.message)
  }
}

async function createSettingChangeCandidate(task) {
  try {
    const related = normalizeRelatedItems(task)
    const entityName = related[0] || guessEntityName(task)
    await settingStore.saveChangeEvent(props.projectId, {
      entityType: inferEntityType(task),
      entityId: null,
      entityName,
      changeType: 'correction_task',
      fieldPath: task.issueType || task.targetModule || '设定纠偏',
      oldValue: '',
      newValue: buildCandidateContent(task),
      chapterNum: firstChapterRef(task) || null,
      evidence: `来自${sourceLabel(task.sourceType)}纠偏任务：${task.title}`,
      confidence: 0.7,
      status: 'pending_review'
    })
    await setStatus(task, 'in_progress')
    message.success('已生成待确认设定变更')
  } catch (e) {
    message.error('生成设定变更失败：' + e.message)
  }
}

function inferEntityType(task) {
  if (task.issueType === 'character') return 'character'
  if (task.issueType === 'setting') return 'location'
  if (task.targetModule === 'setting') return 'character'
  return 'character'
}

function canCreateCanon(task) {
  return ['canon', 'general'].includes(task.targetModule) || task.issueType === 'continuity'
}

function canCreateSetting(task) {
  return task.targetModule === 'setting' || ['character', 'setting'].includes(task.issueType)
}

function firstChapterRef(task) {
  return Number(task.chapterRefs?.[0] || 0)
}

function normalizeRelatedItems(task) {
  return (task.relatedItems || [])
    .map(item => typeof item === 'string' ? item : (item.name || item.title || ''))
    .filter(Boolean)
}

function guessEntityName(task) {
  const match = String(task.title || '').match(/[《「“]?([\u4e00-\u9fa5A-Za-z0-9_·]{2,12})[》」”]?/)
  return match?.[1] || '待确认对象'
}

function buildCandidateContent(task) {
  return [
    task.title || '',
    task.description || '',
    task.suggestedAction ? `建议处理：${task.suggestedAction}` : ''
  ].filter(Boolean).join('\n')
}

function severityType(severity) {
  if (severity === 'critical') return 'error'
  if (severity === 'major') return 'warning'
  if (severity === 'minor') return 'info'
  return 'default'
}

function moduleLabel(module) {
  const labels = {
    bible: '圣经',
    canon: 'Canon',
    chapter: '章节',
    general: '通用',
    outline: '大纲',
    planning: '规划',
    plot_thread: '伏笔',
    setting: '设定库'
  }
  return labels[module] || module || '通用'
}

function sourceLabel(source) {
  const labels = {
    chapter_audit: '章节审稿',
    volume_audit: '分卷审稿',
    global_audit: '全局审稿'
  }
  return labels[source] || source || '审稿'
}

function statusLabel(status) {
  return CORRECTION_STATUS_OPTIONS.find(item => item.value === status)?.label || status
}
</script>

<template>
  <section class="correction-board">
    <div class="board-head">
      <div>
        <h3>纠偏任务板</h3>
        <p v-if="!compact">审稿发现的问题先进入任务板，确认后再处理，不自动覆盖正文或设定。</p>
      </div>
      <n-space align="center">
        <n-select
          v-model:value="statusFilter"
          :options="statusOptions"
          size="small"
          style="width: 120px"
        />
        <n-button size="small" :loading="taskStore.loading" @click="loadData">刷新</n-button>
      </n-space>
    </div>

    <n-empty v-if="!visibleTasks.length && !taskStore.loading" description="暂无纠偏任务" />

    <div v-else class="task-list" :class="{ compact }">
      <n-card v-for="task in visibleTasks" :key="task.id" size="small" class="task-card">
        <div class="task-head">
          <div class="task-title">{{ task.title || '未命名纠偏任务' }}</div>
          <n-tag size="small" :type="severityType(task.severity)" :bordered="false">
            {{ task.severity || 'minor' }}
          </n-tag>
        </div>

        <div class="task-meta">
          <span>{{ sourceLabel(task.sourceType) }}</span>
          <span>{{ moduleLabel(task.targetModule) }}</span>
          <span v-if="task.chapterRefs?.length">章节：{{ task.chapterRefs.join('、') }}</span>
        </div>

        <p v-if="task.description" class="task-desc">{{ task.description }}</p>
        <p v-if="task.suggestedAction" class="task-action">
          <strong>建议：</strong>{{ task.suggestedAction }}
        </p>

        <template #footer>
          <n-space justify="end">
            <n-tag size="small" :bordered="false">{{ statusLabel(task.status) }}</n-tag>
            <n-button
              v-if="canCreateCanon(task) && !['done', 'rejected'].includes(task.status)"
              size="tiny"
              secondary
              @click="createCanonCandidate(task)"
            >
              生成Canon候选
            </n-button>
            <n-button
              v-if="canCreateSetting(task) && !['done', 'rejected'].includes(task.status)"
              size="tiny"
              secondary
              @click="createSettingChangeCandidate(task)"
            >
              生成设定候选
            </n-button>
            <n-button v-if="task.status === 'pending'" size="tiny" @click="setStatus(task, 'accepted')">
              接受
            </n-button>
            <n-button v-if="['pending', 'accepted'].includes(task.status)" size="tiny" @click="setStatus(task, 'in_progress')">
              处理中
            </n-button>
            <n-button v-if="task.status !== 'done'" size="tiny" type="primary" secondary @click="setStatus(task, 'done')">
              完成
            </n-button>
            <n-button v-if="task.status !== 'rejected'" size="tiny" type="error" secondary @click="setStatus(task, 'rejected')">
              忽略本次
            </n-button>
          </n-space>
        </template>
      </n-card>
    </div>
  </section>
</template>

<style scoped>
.correction-board {
  margin-bottom: 16px;
}

.board-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.board-head h3 {
  margin: 0;
  color: #1f2937;
  font-size: 18px;
  font-weight: 700;
}

.board-head p {
  margin: 4px 0 0;
  color: #8a94a6;
  font-size: 13px;
  line-height: 1.6;
}

.task-list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: 10px;
}

.task-list.compact {
  grid-template-columns: 1fr;
}

.task-card {
  border-radius: 6px;
}

.task-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.task-title {
  color: #1f2937;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.5;
}

.task-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  color: #8a94a6;
  font-size: 12px;
}

.task-desc,
.task-action {
  margin: 10px 0 0;
  color: #4b5563;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.task-action strong {
  color: #374151;
}
</style>

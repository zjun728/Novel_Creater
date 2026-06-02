<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { NButton, NCard, NEmpty, NSelect, NSpace, NTag, useDialog } from 'naive-ui'
import { useAppMessage } from '@/composables/useAppMessage'
import {
  CORRECTION_STATUS_OPTIONS,
  correctionTaskMode,
  isCorrectionTaskOpen,
  isCorrectionTaskBlockingForGeneration,
  useCorrectionTaskStore
} from '@/stores/correctionTaskStore'
import { useNovelStore } from '@/stores/novelStore'
import { useSettingStore } from '@/stores/settingStore'
import { useWriterStore } from '@/stores/writerStore'
import { auditSeverityLabel } from '@/utils/auditLabels'
import { settingCandidateStateForTask } from '@/utils/correctionManualClosure'

const props = defineProps({
  projectId: { type: String, required: true },
  compact: { type: Boolean, default: false }
})

const emit = defineEmits(['navigate'])

const taskStore = useCorrectionTaskStore()
const novelStore = useNovelStore()
const settingStore = useSettingStore()
const writerStore = useWriterStore()
const message = useAppMessage()
const dialog = useDialog()
const statusFilter = ref('')
const draftingTaskId = ref('')
const settingCandidateTaskIds = ref(new Set())
const canonCandidateTaskIds = ref(new Set())

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
  if (!props.projectId) return
  await Promise.all([
    taskStore.loadTasks(props.projectId),
    settingStore.loadChangeEvents(props.projectId)
  ])
}

async function setStatus(task, status) {
  try {
    await taskStore.updateTask(props.projectId, task.id, { status })
    message.success('纠偏任务状态已更新')
  } catch (e) {
    message.error('更新纠偏任务失败：' + e.message)
  }
}

function ignoreTask(task) {
  dialog.warning({
    title: '忽略本次纠偏',
    content: '忽略后，该任务会从未完成任务和写作台 AI 上下文中移除；历史任务仍会保留，方便以后回看。',
    positiveText: '确认忽略',
    negativeText: '取消',
    maskClosable: false,
    onPositiveClick: () => setStatus(task, 'ignored')
  })
}

async function createCanonCandidate(task) {
  if (canonCandidateTaskIds.value.has(task.id)) {
    message.info('该纠偏任务已生成过 Canon 候选，请先处理已有待确认内容')
    return
  }

  try {
    canonCandidateTaskIds.value = new Set(canonCandidateTaskIds.value).add(task.id)
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
    const next = new Set(canonCandidateTaskIds.value)
    next.delete(task.id)
    canonCandidateTaskIds.value = next
    message.error('生成 Canon 事实失败：' + e.message)
  }
}

async function createSettingChangeCandidate(task) {
  const candidateState = settingCandidateState(task)
  if (candidateState.locked) {
    message.info(candidateState.hint || '该纠偏任务已生成过设定候选，请先处理已有待确认设定变更')
    return
  }

  try {
    settingCandidateTaskIds.value = new Set(settingCandidateTaskIds.value).add(task.id)
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
    await settingStore.loadChangeEvents(props.projectId)
    message.success('已生成待确认设定变更，请到「4 设定库」确认；确认入库后回到纠偏任务点击「完成」')
  } catch (e) {
    const next = new Set(settingCandidateTaskIds.value)
    next.delete(task.id)
    settingCandidateTaskIds.value = next
    message.error('生成设定变更失败：' + e.message)
  }
}

async function createChapterRevisionDraft(task) {
  const chapterNum = firstChapterRef(task)
  if (!chapterNum) {
    message.warning('该任务没有明确章节号，先定位到对应章节后再生成修订草案')
    return
  }

  draftingTaskId.value = task.id
  try {
    await writerStore.loadChapters(props.projectId)
    const chapter = await writerStore.getOrCreateChapter(props.projectId, chapterNum)
    await writerStore.loadVersions(props.projectId, chapter.id)
    const sourceVersion = findSourceVersion(chapter)
    if (!sourceVersion?.content?.trim()) {
      message.warning('未找到可修订的章节正文或候选版本')
      return
    }
    await writerStore.generateLocalCorrectionPatchCandidate(
      props.projectId,
      chapterNum,
      correctionTasksToPatchIssues([task]),
      sourceVersion.content
    )
    await setStatus(task, 'in_progress')
    message.success('已生成章节局部修订候选版本，可到写字台版本列表查看')
  } catch (e) {
    message.error('生成章节局部修订候选失败：' + e.message)
  } finally {
    draftingTaskId.value = ''
  }
}

async function createChapterRevisionDraftBatch(task) {
  const chapterNum = firstChapterRef(task)
  const tasks = sameChapterDraftTasks(task)
  if (!chapterNum || tasks.length <= 1) {
    await createChapterRevisionDraft(task)
    return
  }

  draftingTaskId.value = `chapter-${chapterNum}`
  try {
    await writerStore.loadChapters(props.projectId)
    const chapter = await writerStore.getOrCreateChapter(props.projectId, chapterNum)
    await writerStore.loadVersions(props.projectId, chapter.id)
    const sourceVersion = findSourceVersion(chapter)
    if (!sourceVersion?.content?.trim()) {
      message.warning('未找到可修订的章节正文或候选版本')
      return
    }
    await writerStore.generateLocalCorrectionPatchCandidate(
      props.projectId,
      chapterNum,
      correctionTasksToPatchIssues(tasks),
      sourceVersion.content
    )
    await Promise.all(tasks.map(item =>
      taskStore.updateTask(props.projectId, item.id, { status: 'in_progress' })
    ))
    message.success(`已基于第 ${chapterNum} 章 ${tasks.length} 条纠偏任务生成综合局部修订候选版本`)
  } catch (e) {
    message.error('生成本章综合局部修订候选失败：' + e.message)
  } finally {
    draftingTaskId.value = ''
  }
}

async function navigateToTask(task) {
  emit('navigate', {
    task,
    targetTab: targetTabForTask(task),
    chapterNum: firstChapterRef(task) || null
  })
  if (['pending', 'accepted'].includes(task.status)) {
    await setStatus(task, 'in_progress')
  }
}

function findSourceVersion(chapter) {
  if (chapter.finalVersionId) {
    const finalVersion = writerStore.versions.find(version => version.id === chapter.finalVersionId)
    if (finalVersion) return finalVersion
  }
  return writerStore.currentVersion || writerStore.versions[0] || null
}

function taskMetadata(task) {
  return task?.metadata && typeof task.metadata === 'object' ? task.metadata : {}
}

function extractTaskLocation(task) {
  const metadata = taskMetadata(task)
  const rawIssue = metadata.rawIssue || {}
  const metadataLocation = metadata.location || metadata.quote || rawIssue.location || rawIssue.quote || rawIssue.evidence || ''
  if (metadataLocation) return metadataLocation

  const fields = [task?.location, task?.evidence, task?.description, task?.suggestedAction, rawIssue.reason]
  for (const value of fields) {
    const text = String(value || '')
    const match = text.match(/位置[：:]\s*([^\n]+)/)
    if (match?.[1]) return match[1].trim()
  }
  return ''
}

function correctionTaskToPatchIssue(task) {
  const metadata = taskMetadata(task)
  const rawIssue = metadata.rawIssue || {}
  const location = extractTaskLocation(task)
  return {
    severity: task?.severity || 'minor',
    type: task?.issueType || task?.targetModule || 'correction_task',
    description: [task?.title, task?.description, rawIssue.description || rawIssue.issue].filter(Boolean).join('\n') || '纠偏任务要求局部修订本章正文',
    location,
    suggestion: metadata.replacement || rawIssue.replacement || task?.suggestedAction || rawIssue.suggestion || '只修订命中的问题片段，保留无关段落。',
    reason: task?.reason || metadata.reason || rawIssue.reason || ''
  }
}

function correctionTasksToPatchIssues(tasks) {
  return (Array.isArray(tasks) ? tasks : [])
    .filter(Boolean)
    .map(correctionTaskToPatchIssue)
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

function hasGeneratedSettingCandidate(task) {
  return settingCandidateState(task).locked
}

function settingCandidateState(task) {
  return settingCandidateStateForTask(
    settingStore.changeEvents,
    task,
    settingCandidateTaskIds.value.has(task.id)
  )
}

function settingCandidateButtonText(task) {
  return settingCandidateState(task).buttonText
}

function settingCandidateHint(task) {
  return settingCandidateState(task).hint
}

function navigateToSettingsCandidate(task) {
  emit('navigate', {
    task,
    targetTab: 'settingsLibrary',
    chapterNum: firstChapterRef(task) || null
  })
}

function canCreateChapterDraft(task) {
  if (correctionTaskMode(task) !== 'hard') return false
  return (
    task.targetModule === 'chapter' ||
    ['plot', 'pacing', 'emotion'].includes(task.issueType) ||
    (task.chapterRefs?.length && !canCreateSetting(task))
  )
}

function sameChapterDraftTasks(task) {
  const chapterNum = firstChapterRef(task)
  if (!chapterNum) return []
  return taskStore.tasks.filter(item =>
    item.id !== task.id &&
    isCorrectionTaskOpen(item) &&
    firstChapterRef(item) === chapterNum &&
    canCreateChapterDraft(item)
  ).concat(task).sort((a, b) => String(a.createdAt || '').localeCompare(String(b.createdAt || '')))
}

function sameChapterDraftTaskCount(task) {
  return sameChapterDraftTasks(task).length
}

function targetTabForTask(task) {
  if (task.targetModule === 'bible' || task.issueType === 'market') return 'bible'
  if (task.targetModule === 'setting' || ['character', 'setting'].includes(task.issueType)) return 'settingsLibrary'
  if (task.targetModule === 'plot_thread' || task.issueType === 'foreshadowing') return 'plotThreads'
  if (['outline', 'planning'].includes(task.targetModule) || ['mainline', 'structure', 'next_action'].includes(task.issueType)) return 'chapters'
  if (task.targetModule === 'chapter' || ['plot', 'pacing', 'emotion'].includes(task.issueType)) return 'writer'
  if (task.chapterRefs?.length) return 'writer'
  return 'corrections'
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
    canon: '记忆',
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

function correctionModeLabel(task) {
  if (isCorrectionTaskBlockingForGeneration(task)) return '阻断'
  const labels = {
    hard: '硬纠偏',
    soft: '软纠偏',
    setting_candidate: '设定候选',
    canon_candidate: '记忆候选',
    advice: '建议'
  }
  return labels[correctionTaskMode(task)] || '软纠偏'
}

function correctionModeType(task) {
  if (isCorrectionTaskBlockingForGeneration(task)) return 'error'
  const mode = correctionTaskMode(task)
  if (mode === 'hard') return 'warning'
  if (mode === 'setting_candidate' || mode === 'canon_candidate') return 'info'
  if (mode === 'advice') return 'default'
  return 'success'
}
</script>

<template>
  <section class="correction-board">
    <div class="board-head">
      <div>
        <h3>纠偏任务板</h3>
        <p v-if="!compact">审稿发现的问题先进入任务板，确认后再处理；正文类问题只生成候选版本，不自动覆盖正式正文。已完成或忽略的任务不会再进入写作台 AI 上下文。</p>
        <div v-if="!compact" class="operation-guide">
          <div><strong>接受：</strong>确认问题有效，状态变为已接受，仍会进入写作台上下文。</div>
          <div><strong>处理中：</strong>标记已开始人工排查或处理，仍属于未完成任务。</div>
          <div><strong>定位处理：</strong>跳到相关章节或模块，并把任务推进为处理中。</div>
          <div><strong>生成设定候选：</strong>只生成待确认设定变更，不直接写入正式设定库；确认入库后再回到这里点完成。</div>
          <div><strong>生成 Canon 候选：</strong>生成待确认记忆事实（Canon），不直接进入正式长期记忆。</div>
          <div><strong>生成章节局部修订候选：</strong>只替换 AI 能安全定位到的原文片段，生成一个候选版本进入写字台版本列表，不覆盖正文。</div>
          <div><strong>综合局部修订本章：</strong>把同章多个正文纠偏合成一个局部补丁候选版本，仍不直接修改正文。</div>
          <div><strong>完成：</strong>只在候选已确认、正文候选已采纳或人工处理完成后点击；完成后不再进入后续 AI 上下文。</div>
          <div><strong>忽略本次：</strong>放弃本次处理，任务关闭但保留历史记录。</div>
        </div>
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
            {{ auditSeverityLabel(task.severity || 'minor') }}
          </n-tag>
        </div>

        <div class="task-meta">
          <span>{{ sourceLabel(task.sourceType) }}</span>
          <span>{{ moduleLabel(task.targetModule) }}</span>
          <n-tag size="tiny" :type="correctionModeType(task)" :bordered="false">
            {{ correctionModeLabel(task) }}
          </n-tag>
          <span v-if="task.chapterRefs?.length">章节：{{ task.chapterRefs.join('、') }}</span>
        </div>

        <p v-if="task.description" class="task-desc">{{ task.description }}</p>
        <p v-if="task.suggestedAction" class="task-action">
          <strong>建议：</strong>{{ task.suggestedAction }}
        </p>
        <div v-if="settingCandidateHint(task)" class="manual-closure-hint">
          <span>{{ settingCandidateHint(task) }}</span>
          <n-button
            v-if="settingCandidateState(task).status === 'pending_review'"
            size="tiny"
            secondary
            @click="navigateToSettingsCandidate(task)"
          >
            去设定库确认
          </n-button>
        </div>

        <template #footer>
          <n-space justify="end">
            <n-tag size="small" :bordered="false">{{ statusLabel(task.status) }}</n-tag>
            <n-button
              v-if="canCreateCanon(task) && isCorrectionTaskOpen(task)"
              size="tiny"
              secondary
              :disabled="canonCandidateTaskIds.has(task.id)"
              @click="createCanonCandidate(task)"
            >
              {{ canonCandidateTaskIds.has(task.id) ? '已生成 Canon 候选' : '生成 Canon 候选' }}
            </n-button>
            <n-button
              v-if="canCreateSetting(task) && isCorrectionTaskOpen(task)"
              size="tiny"
              secondary
              :disabled="hasGeneratedSettingCandidate(task)"
              @click="createSettingChangeCandidate(task)"
            >
              {{ settingCandidateButtonText(task) }}
            </n-button>
            <n-button
              v-if="canCreateChapterDraft(task) && isCorrectionTaskOpen(task)"
              size="tiny"
              secondary
              :loading="draftingTaskId === task.id"
              @click="createChapterRevisionDraft(task)"
            >
              生成章节局部修订候选
            </n-button>
            <n-button
              v-if="canCreateChapterDraft(task) && isCorrectionTaskOpen(task) && sameChapterDraftTaskCount(task) > 1"
              size="tiny"
              type="primary"
              secondary
              :loading="draftingTaskId === `chapter-${firstChapterRef(task)}`"
              @click="createChapterRevisionDraftBatch(task)"
            >
              综合局部修订本章（{{ sameChapterDraftTaskCount(task) }}）
            </n-button>
            <n-button
              v-if="isCorrectionTaskOpen(task)"
              size="tiny"
              secondary
              @click="navigateToTask(task)"
            >
              定位处理
            </n-button>
            <n-button v-if="task.status === 'pending'" size="tiny" @click="setStatus(task, 'accepted')">
              接受
            </n-button>
            <n-button v-if="['pending', 'accepted'].includes(task.status)" size="tiny" @click="setStatus(task, 'in_progress')">
              处理中
            </n-button>
            <n-button v-if="isCorrectionTaskOpen(task)" size="tiny" type="primary" secondary @click="setStatus(task, 'done')">
              完成
            </n-button>
            <n-button v-if="isCorrectionTaskOpen(task)" size="tiny" type="error" secondary @click="ignoreTask(task)">
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

.operation-guide {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 4px 14px;
  margin-top: 8px;
  padding: 10px 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #f8fafc;
  color: #6b7280;
  font-size: 12px;
  line-height: 1.65;
}

.operation-guide strong {
  color: #374151;
  font-weight: 600;
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

.manual-closure-hint {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
  padding: 8px 10px;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  background: #eff6ff;
  color: #1d4ed8;
  font-size: 12px;
  line-height: 1.6;
}

.manual-closure-hint span {
  min-width: 0;
}
</style>

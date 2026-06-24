import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/db/client'
import { filterIssuesForCorrectionTasks } from '@/utils/correctionTaskDenoise'
export {
  CORRECTION_CONTEXT_STATUSES,
  CORRECTION_CLOSED_STATUSES,
  CORRECTION_MODES,
  correctionTaskMode,
  isCorrectionTaskActiveForContext,
  isCorrectionTaskBlockingForGeneration,
  isCorrectionTaskOpen,
  isCorrectionTaskSoftForContext
} from '@/utils/correctionTaskRules'
import {
  CORRECTION_MODES,
  correctionTaskMode,
  isCorrectionTaskActiveForContext,
  isCorrectionTaskOpen
} from '@/utils/correctionTaskRules'

export const CORRECTION_STATUS_OPTIONS = [
  { label: '待确认', value: 'pending' },
  { label: '已接受', value: 'accepted' },
  { label: '处理中', value: 'in_progress' },
  { label: '已完成', value: 'done' },
  { label: '忽略本次', value: 'ignored' },
  { label: '已拒绝', value: 'rejected' }
]

export const useCorrectionTaskStore = defineStore('correctionTask', () => {
  const tasks = ref([])
  const loading = ref(false)

  const activeTasks = computed(() =>
    tasks.value.filter(isCorrectionTaskOpen)
  )

  const contextActiveTasks = computed(() =>
    tasks.value.filter(isCorrectionTaskActiveForContext)
  )

  async function loadTasks(projectId, params = {}) {
    loading.value = true
    try {
      tasks.value = await api.correctionTasks.list(projectId, params)
      return tasks.value
    } finally {
      loading.value = false
    }
  }

  async function bulkCreate(projectId, payloads) {
    if (!payloads?.length) return []
    const created = await api.correctionTasks.bulkCreate(projectId, payloads)
    tasks.value = mergeTasks([...created, ...tasks.value])
    return created
  }

  async function updateTask(projectId, taskId, data) {
    const updated = await api.correctionTasks.update(projectId, taskId, data)
    const idx = tasks.value.findIndex(task => task.id === taskId)
    if (idx === -1) tasks.value.unshift(updated)
    else tasks.value[idx] = updated
    return updated
  }

  async function deleteTask(projectId, taskId) {
    await api.correctionTasks.delete(projectId, taskId)
    tasks.value = tasks.value.filter(task => task.id !== taskId)
  }

  function buildTasksFromVolumeAudit(volume, report) {
    const issues = filterIssuesForCorrectionTasks(report?.issues || [], { maxTasks: 5 })
    return issues.map((issue, index) => ({
      sourceType: 'volume_audit',
      sourceId: volume?.id || null,
      targetModule: inferTargetModule(issue.type),
      title: issue.description || `${volume?.title || '分卷'}纠偏任务 ${index + 1}`,
      description: [
        issue.impact ? `影响：${issue.impact}` : '',
        issue.suggestion ? `建议：${issue.suggestion}` : ''
      ].filter(Boolean).join('\n'),
      severity: issue.severity || 'minor',
      issueType: issue.type || 'general',
      chapterRefs: issue.chapterRefs || [],
      relatedItems: volume?.keyCharacters || [],
      suggestedAction: issue.suggestion || '',
      status: 'pending',
      metadata: {
        correctionMode: CORRECTION_MODES.SOFT,
        blocking: false,
        handlingAdvice: '分卷纠偏不回改已定稿正文；作为后续章节软过渡、设定候选或卷结构调整建议处理。',
        volumeTitle: volume?.title || '',
        volumeRange: [volume?.startChapter, volume?.endChapter],
        rawIssue: issue
      }
    }))
  }

  function buildTasksFromChapterAudit(chapterNum, report, options = {}) {
    if (options.finalized) return []
    const issues = filterIssuesForCorrectionTasks(report?.issues || [], { maxTasks: 3 })
    return issues.map((issue, index) => ({
      sourceType: 'chapter_audit',
      sourceId: options.sourceId || null,
      targetModule: 'chapter',
      title: issue.description || `第 ${chapterNum} 章纠偏任务 ${index + 1}`,
      description: [
        issue.location ? `位置：${issue.location}` : '',
        issue.reason ? `原因：${issue.reason}` : ''
      ].filter(Boolean).join('\n'),
      severity: issue.severity || 'minor',
      issueType: issue.type || 'general',
      chapterRefs: [Number(chapterNum)].filter(Boolean),
      relatedItems: issue.relatedItems || [],
      suggestedAction: issue.suggestion || '',
      status: 'pending',
      metadata: {
        correctionMode: CORRECTION_MODES.HARD,
        blocking: true,
        sourceFinalized: false,
        handlingAdvice: '本章未定稿，可生成章节修订候选或直接在当前草稿中修正；处理前不建议定稿。',
        rawIssue: issue
      }
    }))
  }

  function buildTasksFromGlobalAudit(reportRow) {
    const report = reportRow?.reportJson || reportRow?.report || reportRow
    const sourceId = reportRow?.id || null
    const criticalIssues = (report?.criticalIssues || []).map(issue => ({
      ...issue,
      severity: issue?.severity || 'major'
    }))
    const issueTasks = filterIssuesForCorrectionTasks(criticalIssues, { maxTasks: 8 }).map((issue, index) => ({
      sourceType: 'global_audit',
      sourceId,
      targetModule: inferTargetModule(issue.type),
      title: issue.description || `全局纠偏任务 ${index + 1}`,
      description: issue.impact ? `影响：${issue.impact}` : '',
      severity: issue.severity || 'major',
      issueType: issue.type || 'general',
      chapterRefs: issue.chapterRefs || [],
      relatedItems: issue.relatedItems || [],
      suggestedAction: issue.suggestion || '',
      status: 'pending',
      metadata: {
        correctionMode: CORRECTION_MODES.SOFT,
        blocking: false,
        handlingAdvice: '全局纠偏默认不回改已定稿正文；作为未来章节软修复、长期伏笔回收或设定候选处理。',
        rawIssue: issue
      }
    }))

    const actionTasks = (report?.nextActions || []).slice(0, 3).map((action, index) => ({
      sourceType: 'global_audit',
      sourceId,
      targetModule: 'planning',
      title: action,
      description: '来自全局审稿的下一步行动建议。',
      severity: 'suggestion',
      issueType: 'next_action',
      chapterRefs: [],
      relatedItems: [],
      suggestedAction: action,
      status: 'pending',
      metadata: {
        correctionMode: CORRECTION_MODES.ADVICE,
        blocking: false,
        actionIndex: index
      }
    }))

    return [...issueTasks, ...actionTasks]
  }

  function mergeTasks(items) {
    const map = new Map()
    for (const item of items) map.set(item.id, item)
    return [...map.values()]
  }

  return {
    tasks,
    activeTasks,
    contextActiveTasks,
    loading,
    loadTasks,
    bulkCreate,
    updateTask,
    deleteTask,
    buildTasksFromVolumeAudit,
    buildTasksFromChapterAudit,
    buildTasksFromGlobalAudit
  }
})

function inferTargetModule(type = '') {
  const map = {
    mainline: 'outline',
    plot: 'chapter',
    character: 'setting',
    setting: 'setting',
    continuity: 'canon',
    foreshadowing: 'plot_thread',
    pacing: 'chapter',
    emotion: 'chapter',
    structure: 'outline',
    market: 'bible'
  }
  return map[type] || 'general'
}

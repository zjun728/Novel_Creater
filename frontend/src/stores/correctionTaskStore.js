import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/db/client'

export const CORRECTION_STATUS_OPTIONS = [
  { label: '待确认', value: 'pending' },
  { label: '已接受', value: 'accepted' },
  { label: '处理中', value: 'in_progress' },
  { label: '已完成', value: 'done' },
  { label: '忽略本次', value: 'rejected' }
]

export const CORRECTION_CONTEXT_STATUSES = ['pending', 'accepted', 'in_progress']
export const CORRECTION_CLOSED_STATUSES = ['done', 'rejected', 'ignored', 'cancelled', 'archived']

export function isCorrectionTaskOpen(task) {
  return !CORRECTION_CLOSED_STATUSES.includes(task?.status)
}

export function isCorrectionTaskActiveForContext(task) {
  const status = task?.status || 'pending'
  return CORRECTION_CONTEXT_STATUSES.includes(status)
}

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
    const issues = report?.issues || []
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
        volumeTitle: volume?.title || '',
        volumeRange: [volume?.startChapter, volume?.endChapter],
        rawIssue: issue
      }
    }))
  }

  function buildTasksFromGlobalAudit(reportRow) {
    const report = reportRow?.reportJson || reportRow?.report || reportRow
    const sourceId = reportRow?.id || null
    const issueTasks = (report?.criticalIssues || []).map((issue, index) => ({
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
      metadata: { rawIssue: issue }
    }))

    const actionTasks = (report?.nextActions || []).map((action, index) => ({
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
      metadata: { actionIndex: index }
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

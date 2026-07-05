const STORAGE_PREFIX = 'novel_creator.chapter_finalization.'
const DEFAULT_TTL_MS = 30 * 60 * 1000
const DURABLE_PENDING_STATUSES = new Set(['failed_after_chapter_commit', 'half_success'])
const activeFinalizationRuns = new Set()
const STORY_BLOCK_STAGE_CONFLICT_PATTERN = /已被小纲或定稿章节引用的阶段不能回改|已锁定阶段不能被删除或替换|story_block_stage_update_conflict|story block stage update conflict|故事块.*阶段.*冲突/i
let fallbackRunCounter = 0

function getDefaultStorage() {
  return typeof globalThis !== 'undefined' ? globalThis.localStorage : null
}

function storageKey(projectId, chapterNum) {
  return `${STORAGE_PREFIX}${projectId}.${Number(chapterNum) || 0}`
}

function runKey(projectId, chapterNum, versionId = '') {
  return `${projectId || ''}.${Number(chapterNum) || 0}.${versionId || '*'}`
}

function lowerStatus(value) {
  return String(value || '').trim().toLowerCase()
}

function createStableId(prefix, options = {}) {
  if (options.now != null) return `${prefix}-${options.now}`
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return `${prefix}-${crypto.randomUUID()}`
  fallbackRunCounter += 1
  return `${prefix}-${Date.now()}-${fallbackRunCounter}`
}

function inferStatusFromMessage(message = '') {
  const match = String(message || '').match(/(?:API error|HTTP|status)\s*(\d{3})/i)
  return match ? Number(match[1]) : 0
}

function normalizeFailureDetails(error, options = {}) {
  const detail = error?.detail || {}
  const status = error?.status || detail.status || inferStatusFromMessage(error?.message || detail.message || '')
  return {
    message: error?.message || detail.message || String(error || '定稿后处理失败'),
    name: error?.name || '',
    code: options.code || error?.code || detail.code || '',
    failureType: options.failureType || '',
    status: status || 0,
    upstreamStatus: error?.upstreamStatus ?? detail.upstreamStatus ?? detail.httpStatus ?? null,
    retryable: options.retryable ?? error?.retryable ?? detail.retryable ?? true,
    providerId: error?.providerId || detail.providerId || '',
    providerName: error?.providerName || detail.providerName || '',
    modelName: error?.modelName || detail.modelName || '',
    taskName: error?.taskName || detail.taskName || '',
    taskId: error?.taskId || detail.taskId || '',
    taskKey: error?.taskKey || detail.taskKey || '',
    requestId: error?.requestId || detail.requestId || '',
    failedAt: options.now ?? Date.now()
  }
}

export function classifyPostFinalizeFailure(error) {
  const detail = error?.detail || {}
  const message = String(error?.message || detail.message || error || '')
  const status = error?.status || detail.status || inferStatusFromMessage(message)
  const code = String(error?.code || detail.code || '')
  if (
    code === 'story_block_stage_update_conflict' ||
    (status === 409 && STORY_BLOCK_STAGE_CONFLICT_PATTERN.test(message)) ||
    STORY_BLOCK_STAGE_CONFLICT_PATTERN.test(`${code} ${message}`)
  ) {
    return {
      markerStatus: 'storyBlockSettlementFailure',
      detailKey: 'storyBlockSettlementFailure',
      code: 'story_block_stage_update_conflict',
      failureType: 'story_block_settlement',
      retryable: false
    }
  }
  return {
    markerStatus: 'retryablePostprocessFailure',
    detailKey: 'retryablePostprocessFailure',
    code: code || 'post_finalize_ai_proxy_failed',
    failureType: 'post_finalize_ai_proxy',
    retryable: error?.retryable ?? detail.retryable ?? true
  }
}

export function markChapterFinalizationPending(projectId, chapterNum, options = {}) {
  const storage = options.storage || getDefaultStorage()
  if (!storage || !projectId || !Number(chapterNum)) return null
  const now = options.now ?? Date.now()
  const commitStatus = lowerStatus(options.commitStatus || options.status || 'pending')
  const marker = {
    projectId,
    chapterNum: Number(chapterNum),
    startedAt: now,
    updatedAt: now,
    status: options.markerStatus || (commitStatus === 'pending' ? 'processing' : commitStatus),
    postFinalizePending: options.postFinalizePending !== false,
    postFinalizeFailed: Boolean(options.postFinalizeFailed),
    sourceVersionId: options.sourceVersionId || options.source_version_id || options.versionId || '',
    runId: options.runId || options.run_id || '',
    finalizationId: options.finalizationId || options.finalization_id || '',
    commitStatus
  }
  storage.setItem(storageKey(projectId, chapterNum), JSON.stringify(marker))
  return marker
}

export function markChapterFinalizationFailure(projectId, chapterNum, error, options = {}) {
  const storage = options.storage || getDefaultStorage()
  if (!storage || !projectId || !Number(chapterNum)) return null
  const existing = getChapterFinalizationPending(projectId, chapterNum, options)
  const now = options.now ?? Date.now()
  const classification = classifyPostFinalizeFailure(error)
  const details = normalizeFailureDetails(error, {
    now,
    code: classification.code,
    failureType: classification.failureType,
    retryable: classification.retryable
  })
  const marker = {
    projectId,
    chapterNum: Number(chapterNum),
    startedAt: existing?.startedAt || now,
    updatedAt: now,
    status: classification.markerStatus,
    postFinalizePending: true,
    postFinalizeFailed: true,
    retryablePostprocessFailure: null,
    storyBlockSettlementFailure: null,
    sourceVersionId: options.sourceVersionId || options.source_version_id || existing?.sourceVersionId || '',
    runId: options.runId || options.run_id || existing?.runId || '',
    finalizationId: options.finalizationId || options.finalization_id || existing?.finalizationId || '',
    commitStatus: lowerStatus(options.commitStatus || options.status || 'failed_after_chapter_commit'),
    [classification.detailKey]: details
  }
  storage.setItem(storageKey(projectId, chapterNum), JSON.stringify(marker))
  return marker
}

export function getChapterFinalizationPending(projectId, chapterNum, options = {}) {
  const storage = options.storage || getDefaultStorage()
  if (!storage || !projectId || !Number(chapterNum)) return null
  const key = storageKey(projectId, chapterNum)
  const raw = storage.getItem(key)
  if (!raw) return null

  try {
    const marker = JSON.parse(raw)
    const startedAt = Number(marker?.startedAt || 0)
    const now = options.now ?? Date.now()
    const commitStatus = lowerStatus(marker?.commitStatus || marker?.commit_status || 'pending')
    const durable = DURABLE_PENDING_STATUSES.has(commitStatus) || Boolean(marker?.postFinalizeFailed)
    const ttlMs = options.ttlMs ?? (durable ? Infinity : DEFAULT_TTL_MS)
    if (!startedAt || (Number.isFinite(ttlMs) && now - startedAt > ttlMs)) {
      storage.removeItem(key)
      return null
    }
    return {
      projectId: marker.projectId || projectId,
      chapterNum: Number(marker.chapterNum || chapterNum),
      startedAt,
      updatedAt: Number(marker.updatedAt || startedAt),
      status: marker.status || (commitStatus === 'pending' ? 'processing' : commitStatus),
      postFinalizePending: marker.postFinalizePending !== false,
      postFinalizeFailed: Boolean(marker.postFinalizeFailed || marker.retryablePostprocessFailure || marker.storyBlockSettlementFailure),
      retryablePostprocessFailure: marker.retryablePostprocessFailure || null,
      storyBlockSettlementFailure: marker.storyBlockSettlementFailure || null,
      sourceVersionId: marker.sourceVersionId || marker.source_version_id || '',
      runId: marker.runId || marker.run_id || '',
      finalizationId: marker.finalizationId || marker.finalization_id || '',
      commitStatus
    }
  } catch {
    storage.removeItem(key)
    return null
  }
}

export function clearChapterFinalizationPending(projectId, chapterNum, options = {}) {
  const storage = options.storage || getDefaultStorage()
  if (!storage || !projectId || !Number(chapterNum)) return
  storage.removeItem(storageKey(projectId, chapterNum))
}

export function clearChapterFinalizationFailure(projectId, chapterNum, options = {}) {
  clearChapterFinalizationPending(projectId, chapterNum, options)
}

export function beginChapterFinalizationRun(projectId, chapterNum, versionId = '', options = {}) {
  if (!projectId || !Number(chapterNum)) {
    return { started: false, reason: 'invalid_target', runKey: '' }
  }

  const key = runKey(projectId, chapterNum, versionId)
  if (activeFinalizationRuns.has(key)) {
    return { started: false, reason: 'already_running', runKey: key }
  }

  const existingMarker = getChapterFinalizationPending(projectId, chapterNum, options)
  if (existingMarker && !options.allowExistingPending) {
    return {
      started: false,
      reason: 'pending_marker',
      runKey: key
    }
  }

  activeFinalizationRuns.add(key)
  const runId = options.runId || options.run_id || createStableId('run', options)
  const finalizationId = options.finalizationId || options.finalization_id || createStableId('fin', options)
  markChapterFinalizationPending(projectId, chapterNum, {
    ...options,
    sourceVersionId: options.sourceVersionId || options.source_version_id || versionId,
    runId,
    finalizationId,
    commitStatus: options.commitStatus || options.status || 'pending'
  })
  return { started: true, reason: '', runKey: key, runId, finalizationId }
}

export function endChapterFinalizationRun(key, projectId, chapterNum, options = {}) {
  if (key) activeFinalizationRuns.delete(key)
  if (options.keepPending) {
    markChapterFinalizationPending(projectId, chapterNum, {
      ...options,
      postFinalizeFailed: options.postFinalizeFailed,
      commitStatus: options.commitStatus || options.status || 'failed_after_chapter_commit'
    })
    return
  }
  clearChapterFinalizationPending(projectId, chapterNum, options)
}

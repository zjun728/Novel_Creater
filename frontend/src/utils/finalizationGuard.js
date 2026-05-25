const STORAGE_PREFIX = 'novel_creator.chapter_finalization.'
const DEFAULT_TTL_MS = 30 * 60 * 1000
const activeFinalizationRuns = new Set()

function getDefaultStorage() {
  return typeof globalThis !== 'undefined' ? globalThis.localStorage : null
}

function storageKey(projectId, chapterNum) {
  return `${STORAGE_PREFIX}${projectId}.${Number(chapterNum) || 0}`
}

function runKey(projectId, chapterNum, versionId = '') {
  return `${projectId || ''}.${Number(chapterNum) || 0}.${versionId || '*'}`
}

export function markChapterFinalizationPending(projectId, chapterNum, options = {}) {
  const storage = options.storage || getDefaultStorage()
  if (!storage || !projectId || !Number(chapterNum)) return null
  const marker = {
    projectId,
    chapterNum: Number(chapterNum),
    startedAt: options.now ?? Date.now()
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
    const ttlMs = options.ttlMs ?? DEFAULT_TTL_MS
    if (!startedAt || now - startedAt > ttlMs) {
      storage.removeItem(key)
      return null
    }
    return {
      projectId: marker.projectId || projectId,
      chapterNum: Number(marker.chapterNum || chapterNum),
      startedAt
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

export function beginChapterFinalizationRun(projectId, chapterNum, versionId = '', options = {}) {
  if (!projectId || !Number(chapterNum)) {
    return { started: false, reason: 'invalid_target', runKey: '' }
  }

  const key = runKey(projectId, chapterNum, versionId)
  if (activeFinalizationRuns.has(key)) {
    return { started: false, reason: 'already_running', runKey: key }
  }

  const existingMarker = getChapterFinalizationPending(projectId, chapterNum, options)
  if (existingMarker) {
    return {
      started: false,
      reason: 'pending_marker',
      runKey: key
    }
  }

  activeFinalizationRuns.add(key)
  markChapterFinalizationPending(projectId, chapterNum, options)
  return { started: true, reason: '', runKey: key }
}

export function endChapterFinalizationRun(key, projectId, chapterNum, options = {}) {
  if (key) activeFinalizationRuns.delete(key)
  clearChapterFinalizationPending(projectId, chapterNum, options)
}

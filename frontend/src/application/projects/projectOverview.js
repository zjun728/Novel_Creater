const ARTIFACT_STATUSES = new Set([
  'missing',
  'working_draft',
  'pending_confirmation',
  'current',
  'needs_review',
])

const ARTIFACT_STATUS_LABELS = Object.freeze({
  missing: '尚未建立',
  working_draft: '工作草稿',
  pending_confirmation: '等待确认',
  current: '当前正式版',
  needs_review: '需要检查',
})

const ACHIEVEMENT_KINDS = new Set([
  'seed',
  'contract',
  'bible',
  'planning',
  'final_chapter',
])

function invalidOverview() {
  throw new TypeError('Invalid project overview response')
}

function exactObject(value, keys) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) invalidOverview()
  const actual = Object.keys(value)
  if (actual.length !== keys.length || keys.some(key => !Object.hasOwn(value, key))) {
    invalidOverview()
  }
  return value
}

function safeText(value) {
  if (typeof value !== 'string' || value.length === 0 || value !== value.trim() || /\p{C}/u.test(value)) {
    invalidOverview()
  }
  return value
}

function integer(value, { positive = false } = {}) {
  if (!Number.isSafeInteger(value) || value < (positive ? 1 : 0)) invalidOverview()
  return value
}

function oneOf(value, allowed) {
  if (!allowed.has(value)) invalidOverview()
  return value
}

function parseProject(value) {
  exactObject(value, [
    'id', 'title', 'genre', 'logline', 'targetWords', 'targetChapters',
    'updatedAtMs', 'lifecycle',
  ])
  if (!['active', 'archived'].includes(value.lifecycle)) invalidOverview()
  return {
    id: safeText(value.id),
    title: safeText(value.title),
    genre: safeText(value.genre),
    logline: safeText(value.logline),
    targetWords: integer(value.targetWords, { positive: true }),
    targetChapters: integer(value.targetChapters, { positive: true }),
    updatedAtMs: integer(value.updatedAtMs),
    lifecycle: value.lifecycle,
  }
}

function parseVolume(value) {
  exactObject(value, ['id', 'order', 'title'])
  return {
    id: safeText(value.id),
    order: integer(value.order, { positive: true }),
    title: safeText(value.title),
  }
}

function parseFinalChapter(value) {
  exactObject(value, ['number', 'title', 'finalizedAtMs'])
  return {
    number: integer(value.number, { positive: true }),
    title: safeText(value.title),
    finalizedAtMs: integer(value.finalizedAtMs),
  }
}

function parseProgress(value) {
  exactObject(value, [
    'authoritativeChapterNumber', 'currentVolume', 'latestFinalChapter',
    'finalizedChapterCount', 'finalizedScalarCount',
  ])
  const progress = {
    authoritativeChapterNumber: integer(value.authoritativeChapterNumber, { positive: true }),
    currentVolume: value.currentVolume === null ? null : parseVolume(value.currentVolume),
    latestFinalChapter: value.latestFinalChapter === null
      ? null
      : parseFinalChapter(value.latestFinalChapter),
    finalizedChapterCount: integer(value.finalizedChapterCount),
    finalizedScalarCount: integer(value.finalizedScalarCount),
  }
  const hasLatest = progress.latestFinalChapter !== null
  if ((progress.finalizedChapterCount > 0) !== hasLatest) invalidOverview()
  if (progress.finalizedChapterCount === 0 && progress.finalizedScalarCount !== 0) invalidOverview()
  if (hasLatest) {
    if (progress.latestFinalChapter.number >= progress.authoritativeChapterNumber) invalidOverview()
    if (progress.finalizedChapterCount > progress.latestFinalChapter.number) invalidOverview()
  }
  return progress
}

function parseModules(value) {
  exactObject(value, ['seed', 'contract', 'bible', 'planning', 'outline', 'writing'])
  return Object.fromEntries(Object.entries(value).map(([key, status]) => [
    key,
    oneOf(status, ARTIFACT_STATUSES),
  ]))
}

function parseWriterCore(value) {
  exactObject(value, ['canonRevision', 'projectionRevision', 'synchronized'])
  const writerCore = {
    canonRevision: integer(value.canonRevision),
    projectionRevision: integer(value.projectionRevision),
    synchronized: value.synchronized,
  }
  if (typeof writerCore.synchronized !== 'boolean') invalidOverview()
  if (writerCore.synchronized !== (writerCore.canonRevision === writerCore.projectionRevision)) {
    invalidOverview()
  }
  return writerCore
}

function parseContinuity(value) {
  exactObject(value, ['availability', 'pendingCount'])
  if (!['pending_module', 'available'].includes(value.availability)) invalidOverview()
  if (value.availability === 'pending_module' && value.pendingCount !== null) invalidOverview()
  if (value.availability === 'available' && value.pendingCount === null) invalidOverview()
  return {
    availability: value.availability,
    pendingCount: value.pendingCount === null ? null : integer(value.pendingCount),
  }
}

function parseAchievements(value) {
  if (!Array.isArray(value) || value.length > 5) invalidOverview()
  const identities = new Set()
  return value.map(item => {
    exactObject(item, ['kind', 'label', 'occurredAtMs'])
    const achievement = {
      kind: oneOf(item.kind, ACHIEVEMENT_KINDS),
      label: safeText(item.label),
      occurredAtMs: integer(item.occurredAtMs),
    }
    const identity = JSON.stringify([
      achievement.kind,
      achievement.occurredAtMs,
      achievement.label,
    ])
    if (identities.has(identity)) invalidOverview()
    identities.add(identity)
    return achievement
  })
}

function deepFreeze(value) {
  if (Array.isArray(value)) value.forEach(deepFreeze)
  else if (value && typeof value === 'object') Object.values(value).forEach(deepFreeze)
  return Object.freeze(value)
}

export function parseProjectOverview(value) {
  exactObject(value, [
    'project', 'progress', 'modules', 'writerCore', 'continuity', 'recentAchievements',
  ])
  return deepFreeze({
    project: parseProject(value.project),
    progress: parseProgress(value.progress),
    modules: parseModules(value.modules),
    writerCore: parseWriterCore(value.writerCore),
    continuity: parseContinuity(value.continuity),
    recentAchievements: parseAchievements(value.recentAchievements),
  })
}

export function artifactStatusLabel(status) {
  if (!Object.hasOwn(ARTIFACT_STATUS_LABELS, status)) {
    throw new TypeError('Unknown project overview status')
  }
  return ARTIFACT_STATUS_LABELS[status]
}

export function continuitySummary(continuity) {
  let parsed
  try {
    parsed = parseContinuity(continuity)
  } catch {
    throw new TypeError('Invalid project overview continuity')
  }
  if (parsed.availability === 'pending_module') {
    return '连续性问题将在连续性模块启用后显示'
  }
  return parsed.pendingCount === 0
    ? '暂无待处理的连续性问题'
    : `${parsed.pendingCount} 个连续性问题待处理`
}

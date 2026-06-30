function ok(details = {}) {
  return { ok: true, details }
}

function blocker(code, messageKey, details = {}, severity = 'warning') {
  return {
    ok: false,
    code,
    messageKey,
    severity,
    details
  }
}

function countItems(value, fallback = 0) {
  if (Array.isArray(value)) return value.length
  const count = Number(value)
  return Number.isFinite(count) && count > 0 ? count : fallback
}

function finalVersionIdOf(chapter = null) {
  return chapter?.finalVersionId || chapter?.final_version_id || ''
}

function isFinalChapter(chapter = null) {
  return Boolean(
    chapter &&
    (
      chapter.status === 'final' ||
      finalVersionIdOf(chapter)
    )
  )
}

export function checkCurrentChapterWritable({ currentChapterFinalized = false } = {}) {
  if (currentChapterFinalized) {
    return blocker('currentChapterFinalized', 'currentChapterFinalized')
  }
  return ok()
}

export function checkPreviousChapterFinalized({
  chapterNum = 1,
  previousChapter = null,
  previousFinalizationPending = null
} = {}) {
  const currentNum = Number(chapterNum) || 1
  if (currentNum <= 1) return ok({ previousChapterRequired: false })
  if (!previousChapter) {
    return blocker('previousChapterMissing', 'previousChapterNotFinalized', {
      chapterNum: currentNum,
      previousChapterNum: currentNum - 1
    })
  }
  if (!isFinalChapter(previousChapter)) {
    return blocker('previousChapterNotFinalized', 'previousChapterNotFinalized', {
      chapterNum: currentNum,
      previousChapterNum: currentNum - 1
    })
  }
  if (previousFinalizationPending) {
    return blocker('previousFinalizationPending', 'previousFinalizationPending', {
      chapterNum: currentNum,
      previousChapterNum: currentNum - 1,
      marker: previousFinalizationPending
    })
  }
  return ok({ previousChapterRequired: true })
}

export function checkPendingSettingChanges({
  pendingSettingChanges,
  pendingSettingCount
} = {}) {
  const count = Array.isArray(pendingSettingChanges)
    ? pendingSettingChanges.length
    : countItems(pendingSettingCount)
  if (count > 0) {
    return blocker('pendingSettingChanges', 'pendingSettingChanges', { count })
  }
  return ok({ count: 0 })
}

export function checkPendingStoryMemory({
  pendingCanonFacts,
  pendingMemoryCount
} = {}) {
  const count = Array.isArray(pendingCanonFacts)
    ? pendingCanonFacts.length
    : countItems(pendingMemoryCount)
  if (count > 0) {
    return blocker('pendingStoryMemory', 'pendingStoryMemory', { count })
  }
  return ok({ count: 0 })
}

export function checkCorrectionTaskBlocker({
  blockers = [],
  softTasks = []
} = {}) {
  const blockerCount = countItems(blockers)
  const softTaskCount = countItems(softTasks)
  if (blockerCount > 0) {
    return blocker('correctionTaskBlocker', 'correctionTaskBlocker', {
      blockerCount,
      softTaskCount
    })
  }
  return ok({ blockerCount: 0, softTaskCount })
}

export function checkChapterHardWordMinimum({
  assessment = null,
  wordTarget = null
} = {}) {
  if (assessment?.level !== 'hard_under') {
    return ok({
      level: assessment?.level || '',
      count: Number(assessment?.count || 0)
    })
  }
  return blocker('chapterBelowHardMin', 'chapterBelowHardMin', {
    level: assessment.level,
    count: Number(assessment.count || 0),
    hardMin: Number(wordTarget?.hardMin || 0)
  }, 'error')
}

export function firstBlockingPrecondition(results = []) {
  return (Array.isArray(results) ? results : []).find(result => result && result.ok === false) || null
}

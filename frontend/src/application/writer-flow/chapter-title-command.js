function ok(details = {}) {
  return { ok: true, ...details }
}

function blocker(code, messageKey, details = {}, extra = {}) {
  return {
    ok: false,
    code,
    messageKey,
    details,
    ...extra
  }
}

export function normalizeManualChapterTitle(input = '') {
  return String(input || '').trim().replace(/\s+/g, ' ')
}

export function validateManualChapterTitle({
  chapter = null,
  chapterNum = 0,
  title = '',
  assessTitle
} = {}) {
  if (!chapter?.id) {
    return blocker('chapterNotReady', 'chapterNotReady')
  }

  const normalizedTitle = normalizeManualChapterTitle(title)
  if (!normalizedTitle) {
    return blocker('emptyTitle', 'emptyTitle', { title: normalizedTitle })
  }

  if (Array.from(normalizedTitle).length > 30 || /[\r\n]/.test(String(title || ''))) {
    return blocker('invalidManualTitleShape', 'invalidManualTitleShape', { title: normalizedTitle })
  }

  const titleQuality = typeof assessTitle === 'function'
    ? assessTitle(normalizedTitle, { chapterNum })
    : { titleValid: true }
  if (!titleQuality?.titleValid) {
    return blocker('invalidTitlePolicy', 'invalidTitlePolicy', {
      title: normalizedTitle,
      reason: titleQuality?.titleInvalidReason || '非法标题',
      titleQuality
    })
  }

  return ok({ title: normalizedTitle })
}

export function validateGenerateChapterTitleInput({
  chapter = null,
  content = ''
} = {}) {
  if (!chapter?.id) {
    return blocker('chapterNotReady', 'chapterNotReady')
  }

  const normalizedContent = String(content || '').trim()
  if (!normalizedContent) {
    return blocker('emptyContent', 'emptyContent')
  }

  return ok({ content: normalizedContent })
}

export async function runGenerateChapterTitleCommand({
  projectId = '',
  chapter = null,
  chapterNum = 0,
  content = '',
  chapterGoal = undefined,
  beatPlan = '',
  generateDefaultChapterTitle
} = {}) {
  const validation = validateGenerateChapterTitleInput({ chapter, content })
  if (!validation.ok) return validation

  const title = await generateDefaultChapterTitle(
    projectId,
    chapter,
    chapterNum,
    validation.content,
    {
      chapterGoal,
      beatPlan
    },
    null,
    { force: true }
  )

  if (!title) {
    return blocker('noQualifiedTitle', 'noQualifiedTitle', {}, { openEditor: true })
  }

  return ok({ title })
}

export async function runSaveManualChapterTitleCommand({
  projectId = '',
  chapter = null,
  chapterNum = 0,
  draftTitle = '',
  assessTitle,
  updateChapterTitle
} = {}) {
  const validation = validateManualChapterTitle({
    chapter,
    chapterNum,
    title: draftTitle,
    assessTitle
  })
  if (!validation.ok) return validation

  await updateChapterTitle(projectId, chapter.id, validation.title)
  return ok({ title: validation.title })
}

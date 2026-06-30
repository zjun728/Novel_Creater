export async function runCreateVersionCommand({
  projectId = '',
  chapter = null,
  chapterNum = 0,
  title = '',
  content = '',
  versionType = 'ai_candidate',
  sourceModelId = null,
  promptBrief = '',
  createVersion
} = {}) {
  const chapterId = chapter?.id || chapter?.chapterId || chapter?.chapter_id || ''
  const normalizedChapterNum = Number(chapterNum)
  const normalizedContent = String(content || '')
  if (!projectId) throw new Error('projectId is required')
  if (!chapterId) throw new Error('chapter id is required')
  if (!Number.isFinite(normalizedChapterNum) || normalizedChapterNum <= 0) {
    throw new Error('chapterNum is required')
  }
  if (!normalizedContent.trim()) throw new Error('version content is empty')
  if (typeof createVersion !== 'function') throw new Error('createVersion function is required')

  const version = await createVersion(projectId, chapterId, normalizedChapterNum, {
    title: String(title || ''),
    content: normalizedContent,
    versionType: versionType || 'ai_candidate',
    sourceModelId: sourceModelId || null,
    promptBrief: String(promptBrief || '')
  })
  return { ok: true, version }
}

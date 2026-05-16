import { api } from '@/api/db/client'

async function fetchChapterContent(projectId, chapter) {
  const versions = await api.versions.list(projectId, chapter.id)
  let content = ''
  if (chapter.finalVersionId) {
    const finalVersion = versions.find(v => v.id === chapter.finalVersionId)
    if (finalVersion) content = finalVersion.content
  }
  if (!content && versions.length > 0) {
    content = versions[0].content
  }
  return { chapter, content }
}

export async function exportTxt(projectId) {
  const project = await api.projects.get(projectId)
  if (!project) throw new Error('项目不存在')

  const chapters = await api.chapters.list(projectId)

  const versionResults = await Promise.all(
    chapters.map(ch => fetchChapterContent(projectId, ch))
  )

  const lines = []
  lines.push(`${project.title}`)
  lines.push('')
  if (project.description) {
    lines.push(project.description)
    lines.push('')
  }
  lines.push('='.repeat(50))
  lines.push('')

  for (const { chapter, content } of versionResults) {
    lines.push(chapter.title || `第 ${chapter.chapterNum} 章`)
    lines.push('-'.repeat(30))
    lines.push('')
    if (content) lines.push(content)
    else lines.push('[暂无内容]')
    lines.push('')
    lines.push('')
  }

  return lines.join('\n')
}

export async function exportMarkdown(projectId) {
  const project = await api.projects.get(projectId)
  if (!project) throw new Error('项目不存在')

  const chapters = await api.chapters.list(projectId)

  const versionResults = await Promise.all(
    chapters.map(ch => fetchChapterContent(projectId, ch))
  )

  const lines = []
  lines.push(`# ${project.title}`)
  lines.push('')
  if (project.description) {
    lines.push(`> ${project.description}`)
    lines.push('')
  }
  lines.push('---')
  lines.push('')

  for (const { chapter, content } of versionResults) {
    lines.push(`## ${chapter.title || `第 ${chapter.chapterNum} 章`}`)
    lines.push('')
    if (chapter.summary) {
      lines.push(`*${chapter.summary}*`)
      lines.push('')
    }
    if (content) {
      const paragraphs = content.split(/\n\n+/)
      for (const p of paragraphs) {
        if (p.trim()) {
          lines.push(p.trim())
          lines.push('')
        }
      }
    } else {
      lines.push('*[暂无内容]*')
      lines.push('')
    }
    lines.push('')
  }

  return lines.join('\n')
}

export async function exportSelectedChapters(projectId, chapterIds, format = 'txt') {
  const project = await api.projects.get(projectId)
  if (!project) throw new Error('项目不存在')

  const allChapters = await api.chapters.list(projectId)
  const selected = allChapters.filter(ch => chapterIds.includes(ch.id))

  const versionResults = await Promise.all(
    selected.map(ch => fetchChapterContent(projectId, ch))
  )

  if (format === 'md') {
    const lines = []
    lines.push(`# ${project.title}（节选）`)
    lines.push('')
    for (const { chapter, content } of versionResults) {
      lines.push(`## ${chapter.title || `第 ${chapter.chapterNum} 章`}`)
      lines.push('')
      lines.push(content || '[暂无内容]')
      lines.push('')
    }
    return lines.join('\n')
  }

  const lines = []
  lines.push(`${project.title}（节选）`)
  lines.push('')
  for (const { chapter, content } of versionResults) {
    lines.push(chapter.title || `第 ${chapter.chapterNum} 章`)
    lines.push('-'.repeat(30))
    lines.push('')
    lines.push(content || '[暂无内容]')
    lines.push('')
    lines.push('')
  }
  return lines.join('\n')
}

export async function exportProjectBundle(projectId) {
  const project = await api.projects.get(projectId)
  if (!project) throw new Error('项目不存在')

  const chapters = await api.chapters.list(projectId)

  const versionResults = await Promise.all(
    chapters.map(ch => fetchChapterContent(projectId, ch))
  )

  const chaptersData = versionResults.map(({ chapter, content }) => ({
    chapterNum: chapter.chapterNum,
    title: chapter.title,
    status: chapter.status,
    summary: chapter.summary,
    wordCount: chapter.wordCount,
    content
  }))

  return JSON.stringify({
    exportedAt: new Date().toISOString(),
    project: {
      title: project.title,
      genre: project.genre,
      description: project.description,
      targetWords: project.targetWords,
      targetChapters: project.targetChapters,
      status: project.status
    },
    chapters: chaptersData
  }, null, 2)
}

export function downloadFile(content, filename, mimeType = 'text/plain') {
  const blob = new Blob([content], { type: `${mimeType};charset=utf-8` })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

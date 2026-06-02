const projectId = process.argv[2] || 'a7952220-e9d2-45a2-9eba-9b36c31184c0'
const apiBase = process.env.API_BASE || 'http://127.0.0.1:8000/api'

async function getJson(path) {
  const res = await fetch(`${apiBase}${path}`)
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${path}: ${text.slice(0, 300)}`)
  }
  return res.json()
}

function cnLen(text) {
  return String(text || '').replace(/\s+/g, '').length
}

function normalize(text) {
  return String(text || '').replace(/\s+/g, '')
}

function countMatches(text, regex) {
  return [...String(text || '').matchAll(regex)].length
}

function sampleMatches(text, regex, limit = 8) {
  return [...String(text || '').matchAll(regex)].slice(0, limit).map((m) => m[0])
}

function lastText(text, n = 160) {
  const s = normalize(text)
  return s.slice(Math.max(0, s.length - n))
}

function firstText(text, n = 160) {
  return normalize(text).slice(0, n)
}

function shingles(text, n = 2) {
  const s = normalize(text)
  const out = new Set()
  for (let i = 0; i <= s.length - n; i += 1) out.add(s.slice(i, i + n))
  return out
}

function jaccard(a, b) {
  const A = shingles(a)
  const B = shingles(b)
  if (!A.size && !B.size) return 1
  let inter = 0
  for (const item of A) if (B.has(item)) inter += 1
  return inter / (A.size + B.size - inter)
}

function statusCounts(rows) {
  const map = {}
  for (const row of rows || []) {
    const key = row.status || 'unknown'
    map[key] = (map[key] || 0) + 1
  }
  return map
}

async function main() {
  const project = await getJson(`/projects/${projectId}`)
  const chapters = await getJson(`/projects/${projectId}/chapters`)
  const finalChapters = []
  for (const chapter of chapters.sort((a, b) => (a.chapterNum || 0) - (b.chapterNum || 0))) {
    if (!chapter.finalVersionId) continue
    const versions = await getJson(`/projects/${projectId}/chapters/${chapter.id}/versions`)
    const final = versions.find((v) => v.id === chapter.finalVersionId)
      || versions.find((v) => v.versionType === 'final')
      || versions[0]
    finalChapters.push({ chapter, version: final, versions })
  }

  const canonFacts = await getJson(`/projects/${projectId}/canon-facts`)
  const settingEvents = await getJson(`/projects/${projectId}/settings/change-events`)
  const entities = await getJson(`/projects/${projectId}/settings/entities`)
  const corrections = await getJson(`/projects/${projectId}/correction-tasks`)
  const audits = await getJson(`/projects/${projectId}/global-audits`).catch(() => [])

  const chapterRows = finalChapters.map(({ chapter, version }) => {
    const content = version?.content || ''
    const aiPattern = /不是[^。！？\n]{0,20}[。？！—\-，,；;：:\s]*是/g
    const summaryPattern = /(握紧|抬头看|转身朝|迈步|闭上眼|走进黑暗|往前走|每一步|黑暗|未知)/g
    return {
      chapterNum: chapter.chapterNum,
      title: chapter.title || version?.title || '',
      words: cnLen(content),
      aiContrastCount: countMatches(content, aiPattern),
      aiContrastSamples: sampleMatches(content, aiPattern, 6),
      endingTemplateSignals: countMatches(lastText(content, 260), summaryPattern),
      finalFacts: canonFacts.filter((f) => Number(f.chapterNum) === Number(chapter.chapterNum)).length,
      settingEvents: settingEvents.filter((e) => Number(e.chapterNum) === Number(chapter.chapterNum)).length,
      ending: lastText(content, 180),
      opening: firstText(content, 180),
    }
  })

  const endingSimilarities = []
  for (let i = 0; i < chapterRows.length; i += 1) {
    for (let j = i + 1; j < chapterRows.length; j += 1) {
      endingSimilarities.push({
        chapters: `${chapterRows[i].chapterNum}-${chapterRows[j].chapterNum}`,
        similarity: Number(jaccard(chapterRows[i].ending, chapterRows[j].ending).toFixed(3)),
      })
    }
  }
  endingSimilarities.sort((a, b) => b.similarity - a.similarity)

  const boundaries = []
  for (let i = 0; i < chapterRows.length - 1; i += 1) {
    boundaries.push({
      boundary: `${chapterRows[i].chapterNum}->${chapterRows[i + 1].chapterNum}`,
      prevEnding: chapterRows[i].ending.slice(-120),
      nextOpening: chapterRows[i + 1].opening.slice(0, 120),
    })
  }

  const data = {
    project: {
      id: projectId,
      title: project.title,
      targetWords: project.targetWords,
      targetChapters: project.targetChapters,
    },
    totals: {
      finalizedChapters: finalChapters.length,
      chapterVersions: finalChapters.reduce((sum, item) => sum + item.versions.length, 0),
      canonFacts: canonFacts.length,
      settingEvents: settingEvents.length,
      settingEventStatus: statusCounts(settingEvents),
      entities: entities.length,
      correctionTasks: corrections.length,
      correctionTaskStatus: statusCounts(corrections),
      globalAudits: audits.length,
    },
    chapterRows,
    endingSimilarities: endingSimilarities.slice(0, 8),
    boundaries,
  }

  const md = [
    `# 写作标准验收二次分析`,
    ``,
    `- 项目：${data.project.title}`,
    `- 项目ID：${data.project.id}`,
    `- 已定稿章节：${data.totals.finalizedChapters}`,
    `- 章节版本数：${data.totals.chapterVersions}`,
    `- 记忆事实：${data.totals.canonFacts}`,
    `- 设定变更：${data.totals.settingEvents}，状态 ${JSON.stringify(data.totals.settingEventStatus)}`,
    `- 设定实体：${data.totals.entities}`,
    `- 纠偏任务：${data.totals.correctionTasks}，状态 ${JSON.stringify(data.totals.correctionTaskStatus)}`,
    ``,
    `## 章节指标`,
    `| 章 | 章名 | 字数 | 不是X是Y | 章尾模板信号 | 记忆事实 | 设定变更 |`,
    `|---:|---|---:|---:|---:|---:|---:|`,
    ...chapterRows.map((r) => `| ${r.chapterNum} | ${r.title || ''} | ${r.words} | ${r.aiContrastCount} | ${r.endingTemplateSignals} | ${r.finalFacts} | ${r.settingEvents} |`),
    ``,
    `## “不是X，是Y”样例`,
    ...chapterRows.map((r) => `- 第 ${r.chapterNum} 章：${r.aiContrastSamples.length ? r.aiContrastSamples.join('；') : '未检出'}`),
    ``,
    `## 章尾相似度 Top`,
    ...endingSimilarities.slice(0, 8).map((r) => `- 第 ${r.chapters} 章：${r.similarity}`),
    ``,
    `## 上下章衔接片段`,
    ...boundaries.flatMap((b) => [
      `### 第 ${b.boundary} 章`,
      `- 上章结尾：${b.prevEnding}`,
      `- 下章开头：${b.nextOpening}`,
    ]),
    ``,
  ].join('\n')

  await import('node:fs/promises').then((fs) => Promise.all([
    fs.writeFile('tmp/realistic-flow-qa/standards-secondary-analysis.json', JSON.stringify(data, null, 2), 'utf8'),
    fs.writeFile('tmp/realistic-flow-qa/standards-secondary-analysis.md', md, 'utf8'),
  ]))

  console.log(JSON.stringify({
    project: data.project,
    totals: data.totals,
    chapterRows: data.chapterRows.map((r) => ({
      chapterNum: r.chapterNum,
      title: r.title,
      words: r.words,
      aiContrastCount: r.aiContrastCount,
      endingTemplateSignals: r.endingTemplateSignals,
      finalFacts: r.finalFacts,
      settingEvents: r.settingEvents,
    })),
    maxEndingSimilarity: data.endingSimilarities[0] || null,
    output: [
      'tmp/realistic-flow-qa/standards-secondary-analysis.json',
      'tmp/realistic-flow-qa/standards-secondary-analysis.md',
    ],
  }, null, 2))
}

main().catch((error) => {
  console.error(error)
  process.exit(1)
})

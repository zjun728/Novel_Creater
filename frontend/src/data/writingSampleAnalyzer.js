import { createWritingFingerprintCard, formatWritingFingerprintCardForPrompt } from './writingFingerprints.js'

const CHAPTER_RE = /(?:^|\n)\s*(第[一二三四五六七八九十百千万零〇两\d]+[章节回集卷][^\n]{0,40}|Chapter\s+\d+[^\n]{0,40})\s*(?=\n)/gi
const CHAPTER_LINE_RE = /^\s*(第[一二三四五六七八九十百千万零〇两\d]+[章节回集卷][^\n]{0,40}|Chapter\s+\d+[^\n]{0,40})\s*$/i

function cleanText(value) {
  return typeof value === 'string'
    ? value.replace(/\r/g, '\n').replace(/\u3000/g, ' ').replace(/[ \t]+/g, ' ').trim()
    : ''
}

function uniq(items) {
  return [...new Set(items.filter(Boolean))]
}

function truncateText(text, maxLength = 260) {
  const value = cleanText(text)
  return value.length > maxLength ? `${value.slice(0, maxLength)}...` : value
}

export function sampleTextWindows(text, options = {}) {
  const normalized = cleanText(text)
  const windowSize = Math.max(80, Number(options.windowSize) || 2400)
  const maxWindows = Math.max(1, Math.min(5, Number(options.maxWindows) || 3))
  if (!normalized) return []
  if (normalized.length <= windowSize || maxWindows === 1) {
    return [{ position: 'opening', start: 0, text: normalized.slice(0, windowSize) }]
  }

  const positions = maxWindows === 2
    ? [
        ['opening', 0],
        ['ending', Math.max(0, normalized.length - windowSize)]
      ]
    : [
        ['opening', 0],
        ['middle', Math.max(0, Math.floor(normalized.length / 2 - windowSize / 2))],
        ['ending', Math.max(0, normalized.length - windowSize)]
      ]

  return positions.slice(0, maxWindows).map(([position, start]) => ({
    position,
    start,
    text: normalized.slice(start, start + windowSize)
  }))
}

function splitParagraphs(text) {
  return cleanText(text)
    .split(/\n+/)
    .map(item => item.trim())
    .filter(Boolean)
}

function countMatches(text, regex) {
  return (cleanText(text).match(regex) || []).length
}

function detectChapterCount(text) {
  const matches = cleanText(text).match(CHAPTER_RE)
  return matches?.length || 1
}

function detectMetrics(text) {
  const normalized = cleanText(text)
  const paragraphs = splitParagraphs(normalized)
  const paragraphLengths = paragraphs.map(item => item.length)
  const paragraphCount = paragraphs.length || 1
  const dialogueParagraphCount = paragraphs.filter(item => /^[“"「『].*[”"」』]?$/.test(item) || /^.+[：:]\s*[“"]/.test(item)).length
  const shortParagraphCount = paragraphs.filter(item => item.length > 0 && item.length <= 28).length
  const longParagraphCount = paragraphs.filter(item => item.length >= 160).length
  const aiContrastCount = countMatches(normalized, /不是[^。！？\n]{1,24}[，,、\s]*(?:而是|是)[^。！？\n]{1,40}/g)
  const directEmotionCount = countMatches(normalized, /(感到|感觉到|心中|心里|眼中闪过|涌起).{0,12}(愤怒|恐惧|绝望|震惊|不甘|悲伤|酸涩|灼热|杀意)/g)
  const numericCount = countMatches(normalized, /\d+(?:\.\d+)?(?:%|厘米|米|丈|里|秒|分钟|小时|天|年|MPa|度|次|层|级|斤|两)/g)

  return {
    charCount: normalized.length,
    chapterCount: detectChapterCount(normalized),
    paragraphCount,
    averageParagraphLength: Math.round(paragraphLengths.reduce((sum, len) => sum + len, 0) / paragraphCount),
    dialogueParagraphRatio: Number((dialogueParagraphCount / paragraphCount).toFixed(3)),
    shortParagraphRatio: Number((shortParagraphCount / paragraphCount).toFixed(3)),
    longParagraphRatio: Number((longParagraphCount / paragraphCount).toFixed(3)),
    aiContrastCount,
    directEmotionCount,
    numericCount
  }
}

function firstUsefulParagraph(paragraphs) {
  return paragraphs.find(item => !CHAPTER_LINE_RE.test(item) && item.length >= 12) || paragraphs[0] || ''
}

function lastUsefulParagraph(paragraphs) {
  return [...paragraphs].reverse().find(item => item.length >= 12) || paragraphs[paragraphs.length - 1] || ''
}

function inferChapterEntry(openingParagraph, metrics) {
  if (/^[“"「『]/.test(openingParagraph)) {
    return '可用对白先打开人物关系，再让场景压力和未说出口的信息慢慢浮出；开章不急着解释世界观。'
  }
  if (/[雨雪风雾夜灯门街楼水火土木石]/.test(openingParagraph)) {
    return '先把人物放进具体场景和可触摸的物件里，再让异常、冲突或信息缺口从动作中露出。'
  }
  if (metrics.averageParagraphLength > 120) {
    return '开章偏向用中长段铺出环境、处境和观察顺序，再转入人物选择。'
  }
  return '开章先给出人物正在做的事和身处的压力点，再用细节带出本章问题。'
}

function inferChapterExit(endingParagraph, metrics) {
  if (/[问|门|灯|影|痕|信|票|字|声|路|夜]/.test(endingParagraph)) {
    return '结尾适合落在一个具体物件、声音、痕迹或未解问题上，让读者带着证据感进入下一章。'
  }
  if (metrics.shortParagraphRatio > 0.35) {
    return '结尾可短促收束，但要避免每章都变成动作加状态总结。'
  }
  return '结尾落在关系变化、判断被推翻或新证据出现上，不用模板化内心总结。'
}

function inferDialogueMethod(metrics) {
  if (metrics.dialogueParagraphRatio >= 0.22) {
    return '对话承担关系张力和遮掩，允许停顿、转移话题和言外之意，不让角色主动替作者交代设定。'
  }
  return '对话不必密集，但每次出现都要带身份、态度和未说出口的顾虑，避免纯信息问答。'
}

function inferProseRhythm(metrics) {
  if (metrics.shortParagraphRatio >= 0.45) {
    return '短段落使用频繁，适合制造断裂和压迫；生成时需混入中长段承载观察、因果和情绪余波，让段落节奏有起伏，避免整章一短到底。'
  }
  if (metrics.longParagraphRatio >= 0.18) {
    return '中长段承载观察、行动因果和心理余波，短句只用于转折、沉默和冲击点。'
  }
  return '段落长短相对均衡，适合用中段推进场景，用短句留出停顿和余味。'
}

function buildAvoidPatterns(metrics) {
  const items = [
    '不得复刻样本人物名、地名、势力名、专有名词和标志性意象',
    '不得复制原句、连续表达和独有段落结构'
  ]
  if (metrics.aiContrastCount > 2) items.push('减少套路化“不是X，是/而是Y”反差解释')
  if (metrics.directEmotionCount > 4) items.push('避免动作后立刻替读者命名情绪')
  if (metrics.shortParagraphRatio > 0.45) items.push('避免整章连续短句独段')
  if (metrics.numericCount > 6) items.push('数字和术语必须影响风险、选择或后果')
  return uniq(items)
}

export function analyzeWritingSampleText(text, options = {}) {
  const normalized = cleanText(text)
  const windows = sampleTextWindows(normalized, {
    windowSize: options.windowSize || 3200,
    maxWindows: options.maxWindows || 3
  })
  const sampled = windows.map(item => item.text).join('\n')
  const paragraphs = splitParagraphs(sampled || normalized)
  const metrics = detectMetrics(normalized)
  const openingParagraph = firstUsefulParagraph(paragraphs)
  const endingParagraph = lastUsefulParagraph(paragraphs)

  return createWritingFingerprintCard({
    id: options.id || `local-${String(options.sourceTitle || 'sample').replace(/[^\w\u4e00-\u9fa5]+/g, '-').slice(0, 40)}`,
    sourceTitle: options.sourceTitle || '本地小说样本',
    sourceMode: 'local_sample',
    sourceNote: `离线抽样分析生成；抽样窗口 ${windows.length} 个，只保留抽象写法方法。`,
    genreTags: options.genreTags || [],
    chapterEntry: inferChapterEntry(openingParagraph, metrics),
    chapterExit: inferChapterExit(endingParagraph, metrics),
    dialogueMethod: inferDialogueMethod(metrics),
    characterMethod: '人物应先按自身利益、恐惧、习惯和误判行动，再被主线牵动；关键反应尽量落在动作、停顿和物件互动里。',
    ensembleMethod: '群像要给配角短期目的、顾虑或私心，让他们不只是递线索、送道具或解释规则。',
    challengeMethod: '任务/关卡应由选择代价、资源限制、误判后果和规则边界构成；胜负手要能从前文证据或行动中追溯。',
    emotionMethod: '情绪先通过迟疑、身体反应、习惯落空、无用细节和事后余波呈现，不急着写“他很痛苦/愤怒/绝望”。',
    informationMethod: '信息从物件、证据、旁人反应、失败验证和关系变化中释放；避免老人、反派、系统或旁白一次性交底。',
    proseRhythm: inferProseRhythm(metrics),
    avoidPatterns: buildAvoidPatterns(metrics),
    metrics,
    analysisNotes: [
      `章节数估算：${metrics.chapterCount}`,
      `对白段落占比：${metrics.dialogueParagraphRatio}`,
      `短段占比：${metrics.shortParagraphRatio}`
    ]
  })
}

function joinMethod(cards, key, prefix) {
  const labels = ['章节进入', '章节结尾', '对话方式', '人物方法', '群像方法', '任务/挑战', '情绪呈现', '信息释放', '语言节奏']
  const values = uniq(cards.map(card => {
    const text = card?.[key]
    if (!text) return ''
    return labels.reduce((result, label) => result.replace(new RegExp(`^${label}[:：]\\s*`), ''), text)
  }).filter(Boolean))
  if (!values.length) return ''
  return `${prefix}${values.slice(0, 3).map(item => truncateText(item, 120)).join('；')}`
}

export function createWritingStandardCandidate(cards = [], options = {}) {
  const safeCards = Array.isArray(cards) ? cards.filter(Boolean) : []
  const name = options.name || '本地样本写作标准'
  const category = options.category || '本地样本 / 待审核'
  const id = options.id || `local-standard-${Date.now()}`
  const genreTags = uniq(safeCards.flatMap(card => Array.isArray(card.genreTags) ? card.genreTags : []))
  const avoidPatterns = uniq(safeCards.flatMap(card => Array.isArray(card.avoidPatterns) ? card.avoidPatterns : []))

  const guidance = {
    chapterEngine: joinMethod(safeCards, 'chapterEntry', '章节进入：') || '章节先进入具体处境，再让冲突从人物行动和细节里露出。',
    dialogueMethod: joinMethod(safeCards, 'dialogueMethod', '对话方式：') || '对话带身份、遮掩和停顿，不替作者说明设定。',
    characterMethod: joinMethod(safeCards, 'characterMethod', '人物方法：') || '人物带着自身目标、误判和代价进入场景。',
    ensembleMethod: joinMethod(safeCards, 'ensembleMethod', '群像方法：') || '配角拥有自己的小目标和顾虑。',
    challengeMethod: joinMethod(safeCards, 'challengeMethod', '任务/挑战：') || '关卡靠选择代价、资源限制和规则边界成立。',
    emotionMethod: joinMethod(safeCards, 'emotionMethod', '情绪呈现：') || '情绪通过动作、身体反应和迟来的余波呈现。',
    informationMethod: joinMethod(safeCards, 'informationMethod', '信息释放：') || '信息从证据、行动和失败验证中释放。',
    proseRhythm: joinMethod(safeCards, 'proseRhythm', '语言节奏：') || '段落长短服务场景节奏，不机械一短到底。',
    endingPreference: joinMethod(safeCards, 'chapterExit', '结尾倾向：') || '结尾落在新证据、关系变化或旧判断被推翻上。',
    avoid: uniq([
      ...avoidPatterns,
      '必须禁止复刻原文、专有名词、人物名、地名、连续表达和标志性比喻'
    ]).join('；')
  }

  return {
    id,
    name,
    category,
    status: 'draft',
    sourceCardIds: safeCards.map(card => card.id).filter(Boolean),
    genreTags,
    guidance,
    auditRequired: true,
    noDirectImitation: true
  }
}

export function formatWritingSampleAnalysisMarkdown(result = {}) {
  const cards = Array.isArray(result.cards) ? result.cards : []
  const standard = result.standardCandidate || {}
  const lines = [
    '# 写作样本分析报告',
    '',
    '本报告只保留抽象写法方法，不包含小说原文长段。所有样本只可用于学习叙事方法，不可复刻人物、设定、原句和标志性表达。',
    '',
    `## 合并标准候选：${standard.name || '未命名标准'}`,
    '',
    `- ID：${standard.id || ''}`,
    `- 分类：${standard.category || ''}`,
    `- 来源样本数：${cards.length}`,
    `- 禁止复刻：人物名、地名、势力名、专有名词、原句、连续表达、标志性比喻和独有段落结构`,
    ''
  ]

  if (standard.guidance) {
    lines.push('### 方法摘要', '')
    for (const [key, label] of [
      ['chapterEngine', '章节组织'],
      ['dialogueMethod', '对话方式'],
      ['characterMethod', '人物方法'],
      ['ensembleMethod', '群像方法'],
      ['challengeMethod', '任务/挑战'],
      ['emotionMethod', '情绪呈现'],
      ['informationMethod', '信息释放'],
      ['proseRhythm', '语言节奏'],
      ['endingPreference', '结尾倾向'],
      ['avoid', '避免项']
    ]) {
      if (standard.guidance[key]) lines.push(`- ${label}：${standard.guidance[key]}`)
    }
    lines.push('')
  }

  lines.push('## 单书写作指纹卡', '')
  for (const card of cards) {
    lines.push(formatWritingFingerprintCardForPrompt(card), '')
    if (card.metrics) {
      lines.push(`- 统计：章节约 ${card.metrics.chapterCount}，平均段长 ${card.metrics.averageParagraphLength}，对白占比 ${card.metrics.dialogueParagraphRatio}，短段占比 ${card.metrics.shortParagraphRatio}`, '')
    }
  }
  return lines.join('\n')
}

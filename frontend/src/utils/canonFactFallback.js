const HARD_STATE_PATTERNS = [
  /\d+\s*(?:个)?(?:小时|分钟|天|日|年|次|枚|块|件|滴|寸|丈|里|层|级|阶|境|钱|两|贯|灵石|点)/,
  /[一二三四五六七八九十百千万半两几]\s*(?:个)?(?:小时|分钟|天|日|年|次|枚|块|件|滴|寸|丈|里|层|级|阶|境|钱|两|贯|灵石|点)/,
  /(剩余|还剩|冷却|倒计时|第[一二三四五六七八九十\d]+次|首次|第二次|第三次)/,
  /(受伤|伤口|裂伤|流血|失血|中毒|昏迷|断裂|骨折)/,
  /(当前位置|抵达|离开|进入|回到|留在|转移到|带走|获得|失去|交给|藏在|放入|收回)/
]

function compactText(value, max = 120) {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
}

function splitSentences(text) {
  return String(text || '')
    .replace(/\r/g, '')
    .split(/(?<=[。！？!?；;])|\n+/)
    .map(item => item.replace(/\s+/g, ' ').trim())
    .filter(Boolean)
}

function scoreHardStateSentence(sentence) {
  return HARD_STATE_PATTERNS.reduce((score, pattern) => score + (pattern.test(sentence) ? 1 : 0), 0)
}

function pickEvidence(chapterContent) {
  const sentences = splitSentences(chapterContent)
  return compactText(sentences[0] || chapterContent, 100)
}

function buildChapterAnchorFact(chapterNum, chapterContent, summary) {
  const fallbackSummary = summary || [
    splitSentences(chapterContent)[0],
    splitSentences(chapterContent).slice(-1)[0]
  ].filter(Boolean).join(' ')

  return {
    factType: 'plot',
    content: compactText(`第 ${chapterNum} 章已定稿：${fallbackSummary || '本章内容已进入连续剧情。'}`, 120),
    relatedCharacters: [],
    relatedPlotThreads: ['#章节锚点'],
    evidence: pickEvidence(chapterContent),
    confidence: 0.6,
    status: 'accepted'
  }
}

function buildHardStateFacts(chapterNum, chapterContent) {
  const seen = new Set()
  return splitSentences(chapterContent)
    .map(sentence => ({ sentence, score: scoreHardStateSentence(sentence) }))
    .filter(item => item.score > 0)
    .sort((a, b) => b.score - a.score)
    .map(item => item.sentence)
    .filter(sentence => {
      const key = compactText(sentence, 80)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
    .slice(0, 3)
    .map(sentence => ({
      factType: 'timeline',
      content: compactText(`第 ${chapterNum} 章硬状态：${sentence}`, 120),
      relatedCharacters: [],
      relatedPlotThreads: ['#硬状态账本'],
      evidence: compactText(sentence, 100),
      confidence: 0.55,
      status: 'accepted'
    }))
}

export function buildFallbackCanonFacts({ chapterNum, chapterContent, summary = '' } = {}) {
  const content = String(chapterContent || '').trim()
  if (!content) return []

  const facts = [
    buildChapterAnchorFact(chapterNum || '?', content, summary),
    ...buildHardStateFacts(chapterNum || '?', content)
  ]

  const seen = new Set()
  return facts.filter(fact => {
    const key = `${fact.factType}:${fact.content}`
    if (seen.has(key)) return false
    seen.add(key)
    return true
  }).slice(0, 4)
}

const DEFAULT_SHORT_PARAGRAPH_CJK = 14
const LEADING_ACTION_CHARS = new Set(Array.from(
  '摇抬盯握把低走站伸收摸看听想笑问说回转停坐起闭睁咬皱拍拿推扶躲避跪钻绕沿捡吐呼吸喘点按摁翻塞放抽拔掏抓拽扯拎举挥退进'
))
const LEADING_ACTION_WORDS = [
  '沉默', '开口', '起身', '回头', '低头', '抬头', '皱眉', '咬牙', '后退', '上前',
  '走近', '走出', '站定', '停下', '伸手', '收回', '握住', '看向', '听见', '想起'
]

export function countCjkChars(value) {
  const text = String(value || '')
  return (text.match(/[\u4e00-\u9fff]/g) || []).length
}

export function splitProseParagraphs(text) {
  return String(text || '')
    .replace(/\r\n/g, '\n')
    .split(/\n{2,}/)
    .map(paragraph => paragraph.trim())
    .filter(Boolean)
}

function countAiContrastPattern(text) {
  const matches = String(text || '').match(/不是[^。！？!?；;\n]{1,28}(?:而是|是)[^。！？!?；;\n]{1,36}/g)
  return matches ? matches.length : 0
}

function detectLeadingSubject(paragraph) {
  const text = String(paragraph || '')
    .replace(/^[\s"'“‘《（(【[]+/, '')
    .trim()
  const chars = Array.from(text)
  if (chars.length < 3) return ''

  const startsWithAction = index => {
    const char = chars[index]
    const rest = chars.slice(index, index + 4).join('')
    return LEADING_ACTION_CHARS.has(char) || LEADING_ACTION_WORDS.some(word => rest.startsWith(word))
  }

  const first3 = chars.slice(0, 3).join('')
  if (/^[\u4e00-\u9fff]{3}$/.test(first3) && startsWithAction(3)) return first3

  const first2 = chars.slice(0, 2).join('')
  if (/^[\u4e00-\u9fff]{2}$/.test(first2) && startsWithAction(2)) return first2

  return ''
}

export function analyzeProseRhythm(text, options = {}) {
  const shortThreshold = Number(options.shortThreshold || DEFAULT_SHORT_PARAGRAPH_CJK)
  const paragraphs = splitProseParagraphs(text)
  let shortParagraphCount = 0
  let currentShortStreak = 0
  let maxShortStreak = 0
  let totalCjkLength = 0
  const leadingSubjectCounts = new Map()
  let leadingSubjectParagraphCount = 0

  const paragraphStats = paragraphs.map((paragraph, index) => {
    const cjkLength = countCjkChars(paragraph)
    const lineCount = paragraph.split('\n').filter(line => line.trim()).length
    const isShort = cjkLength > 0 && cjkLength <= shortThreshold && lineCount <= 1
    const leadingSubject = detectLeadingSubject(paragraph)
    totalCjkLength += cjkLength
    if (isShort) {
      shortParagraphCount += 1
      currentShortStreak += 1
      maxShortStreak = Math.max(maxShortStreak, currentShortStreak)
    } else {
      currentShortStreak = 0
    }
    if (leadingSubject) {
      leadingSubjectParagraphCount += 1
      leadingSubjectCounts.set(leadingSubject, (leadingSubjectCounts.get(leadingSubject) || 0) + 1)
    }
    return { index, cjkLength, lineCount, isShort, leadingSubject }
  })

  const paragraphCount = paragraphs.length
  const shortParagraphRate = paragraphCount ? shortParagraphCount / paragraphCount : 0
  const avgParagraphCjkLength = paragraphCount ? totalCjkLength / paragraphCount : 0
  const aiContrastCount = countAiContrastPattern(text)
  const repeatedLeadingSubjects = Array.from(leadingSubjectCounts.entries())
    .filter(([, count]) => count >= 2)
    .sort((a, b) => b[1] - a[1])
    .map(([subject, count]) => ({ subject, count }))
  const maxSameLeadingSubjectCount = repeatedLeadingSubjects[0]?.count || 0
  const leadingSubjectRate = paragraphCount ? maxSameLeadingSubjectCount / paragraphCount : 0
  const reasons = []

  if (paragraphCount >= 50 && shortParagraphRate >= 0.32 && maxShortStreak >= 3) {
    reasons.push('短句独立段落比例偏高')
  }
  if (paragraphCount >= 20 && maxShortStreak >= 6) {
    reasons.push('连续短句独立段落过长')
  }
  if (paragraphCount >= 30 && avgParagraphCjkLength > 0 && avgParagraphCjkLength < 24) {
    reasons.push('平均段落过短')
  }
  if (aiContrastCount > 6) {
    reasons.push('套路化反差句偏多')
  }
  if (paragraphCount >= 6 && maxSameLeadingSubjectCount >= 5 && leadingSubjectRate >= 0.28) {
    reasons.push('段首重复点名偏多')
  }

  return {
    paragraphCount,
    shortParagraphCount,
    shortParagraphRate,
    maxShortStreak,
    avgParagraphCjkLength,
    aiContrastCount,
    leadingSubjectParagraphCount,
    maxSameLeadingSubjectCount,
    leadingSubjectRate,
    repeatedLeadingSubjects,
    paragraphStats,
    reasons,
    shouldRepair: reasons.length > 0
  }
}

export function shouldRepairProseRhythm(analysisOrText) {
  const analysis = typeof analysisOrText === 'string'
    ? analyzeProseRhythm(analysisOrText)
    : analysisOrText
  return Boolean(analysis?.shouldRepair)
}

export function shouldAcceptProseRhythmRepair(before, after, drift = 1) {
  if (!before || !after) return false
  if (drift < 0.78 || drift > 1.22) return false

  const metrics = [
    'shortParagraphRate',
    'maxShortStreak',
    'aiContrastCount',
    'maxSameLeadingSubjectCount'
  ]

  const worsened = metrics.some(key => Number(after[key] || 0) > Number(before[key] || 0))
  if (worsened) return false

  return metrics.some(key => Number(after[key] || 0) < Number(before[key] || 0))
}

export function formatProseRhythmAnalysis(analysis) {
  if (!analysis) return ''
  const rate = `${Math.round((analysis.shortParagraphRate || 0) * 100)}%`
  return [
    `段落数：${analysis.paragraphCount || 0}`,
    `短句独立段落：${analysis.shortParagraphCount || 0}（${rate}）`,
    `最长连续短句独立段落：${analysis.maxShortStreak || 0}`,
    `平均段落汉字数：${Math.round(analysis.avgParagraphCjkLength || 0)}`,
    `套路化反差句：${analysis.aiContrastCount || 0} 次`,
    analysis.maxSameLeadingSubjectCount
      ? `最重复段首主语：${analysis.repeatedLeadingSubjects?.[0]?.subject || '-'}（${analysis.maxSameLeadingSubjectCount} 段）`
      : '',
    analysis.reasons?.length ? `触发原因：${analysis.reasons.join('；')}` : ''
  ].filter(Boolean).join('\n')
}

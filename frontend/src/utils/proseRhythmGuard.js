import { mapRhythmAnalysisToQualitySignals } from '../quality/writingQualityScoring.js'

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
  if (maxSameLeadingSubjectCount > 20) {
    reasons.push('段首重复点名超过 20 次')
  } else if (paragraphCount >= 6 && maxSameLeadingSubjectCount >= 5 && leadingSubjectRate >= 0.28) {
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
    qualitySignals: mapRhythmAnalysisToQualitySignals({
      shortParagraphRate,
      maxShortStreak,
      aiContrastCount,
      maxSameLeadingSubjectCount
    }),
    shouldRepair: reasons.length > 0
  }
}

export function shouldRepairProseRhythm(analysisOrText) {
  const analysis = typeof analysisOrText === 'string'
    ? analyzeProseRhythm(analysisOrText)
    : analysisOrText
  return Boolean(analysis?.shouldRepair)
}

function metricValue(source, key) {
  return Number(source?.[key] || 0)
}

function improvedByRatio(beforeValue, afterValue, minDelta, minRatio = 0.2) {
  if (beforeValue <= 0) return false
  const delta = beforeValue - afterValue
  return delta >= minDelta && delta / beforeValue >= minRatio
}

export function countSignificantProseRhythmImprovements(before, after) {
  if (!before || !after) return 0
  const improvements = [
    improvedByRatio(metricValue(before, 'shortParagraphRate'), metricValue(after, 'shortParagraphRate'), 0.08, 0.18),
    improvedByRatio(metricValue(before, 'maxShortStreak'), metricValue(after, 'maxShortStreak'), 2, 0.25),
    improvedByRatio(metricValue(before, 'maxSameLeadingSubjectCount'), metricValue(after, 'maxSameLeadingSubjectCount'), 3, 0.25)
  ]
  return improvements.filter(Boolean).length
}

function hasPrimaryRhythmRegression(before, after) {
  if (!before || !after) return true
  if (metricValue(after, 'shortParagraphRate') > metricValue(before, 'shortParagraphRate') + 0.03) return true
  if (metricValue(after, 'maxShortStreak') > metricValue(before, 'maxShortStreak') + 1) return true
  if (metricValue(after, 'maxSameLeadingSubjectCount') > metricValue(before, 'maxSameLeadingSubjectCount') + 2) return true
  return false
}

export function buildLocalProseRhythmRepairCandidate(text, options = {}) {
  const paragraphs = splitProseParagraphs(text)
  const shortThreshold = Number(options.shortThreshold || DEFAULT_SHORT_PARAGRAPH_CJK)
  const targetMinCjk = Number(options.targetMinCjk || 34)
  const maxMergeCount = Number(options.maxMergeCount || 4)
  const result = []
  let buffer = []
  let bufferCjk = 0

  const flush = () => {
    if (!buffer.length) return
    result.push(buffer.join(''))
    buffer = []
    bufferCjk = 0
  }

  for (const paragraph of paragraphs) {
    const cjkLength = countCjkChars(paragraph)
    const lineCount = paragraph.split('\n').filter(line => line.trim()).length
    const isShort = cjkLength > 0 && cjkLength <= shortThreshold && lineCount <= 1
    if (!isShort) {
      flush()
      result.push(paragraph)
      continue
    }
    buffer.push(paragraph)
    bufferCjk += cjkLength
    if (buffer.length >= maxMergeCount || bufferCjk >= targetMinCjk) flush()
  }
  flush()
  const candidate = result.join('\n\n').trim()
  return candidate && candidate !== String(text || '').trim() ? candidate : String(text || '').trim()
}

export function shouldAcceptProseRhythmRepair(before, after, drift = 1, options = {}) {
  if (!before || !after) return false
  if (options.narrativeRegression || options.aiRiskWorsened) return false
  const strictDrift = drift >= 0.78 && drift <= 1.22
  const controlledDrift = Boolean(options.allowControlledDrift) && drift >= 0.62 && drift <= 1.55
  if (!strictDrift && !controlledDrift) return false
  if (hasPrimaryRhythmRegression(before, after)) return false

  const aiContrastIncrease = metricValue(after, 'aiContrastCount') - metricValue(before, 'aiContrastCount')
  if (aiContrastIncrease > 2) return false

  const significantImprovements = countSignificantProseRhythmImprovements(before, after)
  if (controlledDrift && !strictDrift) return significantImprovements >= 2
  if (significantImprovements >= 2) return true
  return metricValue(after, 'aiContrastCount') < metricValue(before, 'aiContrastCount')
}

export function shouldAcceptNotXButYRepair(before, after, drift = 1, options = {}) {
  if (!before || !after) return false
  if (options.narrativeRegression || options.aiRiskWorsened) return false
  const beforeCount = metricValue(before, 'aiContrastCount')
  const afterCount = metricValue(after, 'aiContrastCount')
  const maxAllowed = Number(options.maxAllowed ?? 2)
  const minDrop = Number(options.minDrop ?? 1)
  const strictDrift = drift >= Number(options.minDrift ?? 0.82) && drift <= Number(options.maxDrift ?? 1.18)
  if (!strictDrift) return false
  if (hasPrimaryRhythmRegression(before, after)) return false
  return beforeCount > maxAllowed && afterCount <= maxAllowed && beforeCount - afterCount >= minDrop
}

function isSentenceBoundaryChar(char) {
  return /[。！？；!?;]/.test(char) || char === '銆'
}

function splitSentenceUnits(text = '') {
  const source = String(text || '')
  const units = []
  let start = 0
  for (let index = 0; index < source.length; index += 1) {
    if (!isSentenceBoundaryChar(source[index])) continue
    let end = index + 1
    while (end < source.length && /[?.!？！」』”’)\]）】]/.test(source[end])) end += 1
    const unit = source.slice(start, end)
    if (unit.trim()) units.push(unit)
    start = end
  }
  const tail = source.slice(start)
  if (tail.trim()) units.push(tail)
  return units.length ? units : (source.trim() ? [source] : [])
}

function hasNotXButYPattern(text = '') {
  const source = String(text || '')
  if (/不是[^。！？；;!?銆锛\n]{1,36}(?:而是|是)[^。！？；;!?銆锛\n]{1,48}/.test(source)) return true
  return /涓嶆槸/.test(source) && /(鑰屾槸|鏄)/.test(source)
}

function exactOccurrenceCount(source = '', needle = '') {
  if (!needle) return 0
  let count = 0
  let index = 0
  const text = String(source || '')
  while (index <= text.length) {
    const found = text.indexOf(needle, index)
    if (found < 0) break
    count += 1
    index = found + Math.max(needle.length, 1)
  }
  return count
}

export function extractNotXButYRepairSegments(text, options = {}) {
  const source = String(text || '')
  const units = splitSentenceUnits(source)
  const windowSize = Number(options.windowSize ?? 1)
  const maxSegments = Number(options.maxSegments ?? 12)
  const maxChars = Number(options.maxChars ?? 520)
  const seen = new Set()
  const segments = []
  for (let index = 0; index < units.length; index += 1) {
    if (!hasNotXButYPattern(units[index])) continue
    const start = Math.max(0, index - windowSize)
    const end = Math.min(units.length, index + windowSize + 1)
    let originalText = units.slice(start, end).join('')
    if (originalText.length > maxChars) originalText = units[index]
    const key = originalText.trim()
    if (!key || seen.has(key)) continue
    seen.add(key)
    segments.push({
      index: segments.length,
      sentenceIndex: index,
      startSentenceIndex: start,
      endSentenceIndex: end - 1,
      originalText
    })
    if (segments.length >= maxSegments) break
  }
  return segments
}

export function applyNotXButYSegmentReplacements(text, replacements = [], options = {}) {
  let output = String(text || '')
  const maxReplacementGrowth = Number(options.maxReplacementGrowth ?? 1.8)
  const maxExtraChars = Number(options.maxExtraChars ?? 120)
  for (const item of Array.isArray(replacements) ? replacements : []) {
    const originalText = String(item?.originalText || '')
    const replacementText = String(item?.replacementText || '').trim()
    if (!originalText || !replacementText || originalText === replacementText) continue
    if (exactOccurrenceCount(output, originalText) !== 1) continue
    if (replacementText.length > originalText.length * maxReplacementGrowth + maxExtraChars) continue
    output = output.replace(originalText, replacementText)
  }
  return output
}

export function shouldAcceptNotXButYSegmentRepair(before, after, repairedText = '', originalText = '', options = {}) {
  if (!before || !after) return false
  if (options.narrativeRegression || options.aiRiskWorsened) return false
  const beforeCount = metricValue(before, 'aiContrastCount')
  const afterCount = metricValue(after, 'aiContrastCount')
  const maxAllowed = Number(options.maxAllowed ?? 2)
  const minDrop = Number(options.minDrop ?? 1)
  if (beforeCount <= maxAllowed || afterCount > maxAllowed || beforeCount - afterCount < minDrop) return false
  if (hasPrimaryRhythmRegression(before, after)) return false
  const drift = countCjkChars(repairedText) / Math.max(countCjkChars(originalText), 1)
  if (drift < Number(options.minDrift ?? 0.72) || drift > Number(options.maxDrift ?? 1.28)) return false
  return true
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

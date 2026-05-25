function normalizeWhitespace(value) {
  return String(value || '').replace(/\r\n/g, '\n').trim()
}

function normalizeForLooseMatch(value) {
  return String(value || '').replace(/[\s"'“”‘’`]+/gu, '')
}

function normalizeForPunctuationMatch(value) {
  return String(value || '').replace(/[\s"'“”‘’`，。！？、；：,.!?;:—\-]+/gu, '')
}

function buildSearchText(value, skipPattern) {
  const chars = []
  const map = []
  const source = String(value || '')
  for (let index = 0; index < source.length; index += 1) {
    const char = source[index]
    if (skipPattern.test(char)) continue
    chars.push(char)
    map.push(index)
  }
  return { text: chars.join(''), map }
}

function expandSkippedRange(source, start, end, skipPattern) {
  let expandedStart = start
  let expandedEnd = end
  while (expandedStart > 0 && skipPattern.test(source[expandedStart - 1])) {
    expandedStart -= 1
  }
  while (expandedEnd < source.length && skipPattern.test(source[expandedEnd])) {
    expandedEnd += 1
  }
  return { start: expandedStart, end: expandedEnd }
}

function findUniqueMappedRange(source, normalizedQuote, skipPattern, matchMode) {
  const normalizedSource = buildSearchText(source, skipPattern)
  if (!normalizedQuote || !normalizedSource.text) return null
  const firstIndex = normalizedSource.text.indexOf(normalizedQuote)
  if (firstIndex < 0) return null
  const nextIndex = normalizedSource.text.indexOf(normalizedQuote, firstIndex + 1)
  if (nextIndex >= 0) {
    return { found: false, reason: 'ambiguous', index: -1, quote: normalizedQuote }
  }
  const start = normalizedSource.map[firstIndex]
  const end = normalizedSource.map[firstIndex + normalizedQuote.length - 1] + 1
  const expanded = expandSkippedRange(source, start, end, skipPattern)
  return {
    found: true,
    index: expanded.start,
    quote: source.slice(expanded.start, expanded.end),
    matchMode
  }
}

function isSentenceLike(value) {
  const text = normalizeWhitespace(value)
  return text.length >= 8 && /[。！？!?]$/.test(text)
}

function findPreviousSentenceBoundary(source, index) {
  for (let cursor = index - 1; cursor >= 0; cursor -= 1) {
    const char = source[cursor]
    if (char === '\n') {
      if (source[cursor - 1] === '\n' || source[cursor + 1] === '\n') return cursor + 1
      continue
    }
    if (/[。！？!?]/u.test(char)) return cursor + 1
  }
  return 0
}

function findNextSentenceBoundary(source, index) {
  for (let cursor = index; cursor < source.length; cursor += 1) {
    const char = source[cursor]
    if (char === '\n' && source[cursor + 1] === '\n') return cursor
    if (/[。！？!?]/u.test(char)) return cursor + 1
  }
  return index
}

function trimRangeWhitespace(source, start, end) {
  let trimmedStart = start
  let trimmedEnd = end
  while (trimmedStart < trimmedEnd && /\s/u.test(source[trimmedStart])) trimmedStart += 1
  while (trimmedEnd > trimmedStart && /\s/u.test(source[trimmedEnd - 1])) trimmedEnd -= 1
  return { start: trimmedStart, end: trimmedEnd }
}

function shouldExpandToSentence(source, located, replacement) {
  if (!isSentenceLike(replacement)) return false
  const start = located.index
  const end = located.index + located.quote.length
  const startsAtBoundary = start === 0 || /[。！？!?\n]/u.test(source[start - 1])
  const endsAtBoundary = end >= source.length || /[。！？!?\n]/u.test(source[end - 1])
  return !startsAtBoundary || !endsAtBoundary
}

function expandToSentenceRange(source, located) {
  const start = findPreviousSentenceBoundary(source, located.index)
  const end = findNextSentenceBoundary(source, located.index + located.quote.length)
  const trimmed = trimRangeWhitespace(source, start, end)
  return {
    ...located,
    index: trimmed.start,
    quote: source.slice(trimmed.start, trimmed.end),
    expanded: true
  }
}

export function cleanAuditQuote(value) {
  let text = normalizeWhitespace(value)
  text = text.replace(/^(原文|位置|引用|问题片段|片段)\s*[:：]\s*/u, '').trim()
  text = text.replace(/^["“”'‘’`]+|["“”'‘’`]+$/gu, '').trim()
  return text
}

export function getAuditReplacement(issue, fallback = '') {
  const replacement = issue?.replacement ?? issue?.rewrite ?? issue?.fixedText ?? issue?.newText ?? fallback
  return normalizeWhitespace(replacement)
}

export function locateAuditQuote(content, issue) {
  const source = String(content || '')
  const quote = cleanAuditQuote(issue?.location || issue?.quote || issue?.evidence || '')
  if (!quote) {
    return { found: false, reason: 'missing_location', index: -1, quote }
  }
  const index = source.indexOf(quote)
  if (index >= 0) {
    return { found: true, index, quote, matchMode: 'exact' }
  }

  const looseQuote = normalizeForLooseMatch(quote)
  if (looseQuote) {
    const looseRange = findUniqueMappedRange(source, looseQuote, /[\s"'“”‘’`]/u, 'loose')
    if (looseRange) return looseRange
  }

  const punctuationQuote = normalizeForPunctuationMatch(quote)
  if (punctuationQuote) {
    const punctuationRange = findUniqueMappedRange(source, punctuationQuote, /[\s"'“”‘’`，。！？、；：,.!?;:—\-]/u, 'punctuation')
    if (punctuationRange) return punctuationRange
  }

  return { found: false, reason: 'not_found', index: -1, quote }
}

export function applyAuditReplacement(content, issue, replacementOverride = null) {
  const source = String(content || '')
  const replacement = replacementOverride == null
    ? getAuditReplacement(issue)
    : normalizeWhitespace(replacementOverride)
  if (!replacement) {
    return { ok: false, reason: 'missing_replacement', content: source, index: -1, quote: '' }
  }

  const located = locateAuditQuote(source, issue)
  if (!located.found) {
    return { ok: false, reason: located.reason, content: source, index: located.index, quote: located.quote }
  }

  const target = shouldExpandToSentence(source, located, replacement)
    ? expandToSentenceRange(source, located)
    : located

  return {
    ok: true,
    reason: '',
    content: source.slice(0, target.index) + replacement + source.slice(target.index + target.quote.length),
    index: target.index,
    quote: target.quote,
    replacement,
    matchMode: target.matchMode,
    expanded: Boolean(target.expanded)
  }
}

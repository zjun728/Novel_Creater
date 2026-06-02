function normalizePatchText(value) {
  if (value == null) return ''
  return String(value)
    .replace(/^```(?:text|markdown)?/i, '')
    .replace(/```$/i, '')
    .trim()
}

const MAX_PATCH_ORIGINAL_CHARS = 420
const OVERCOMPRESS_MIN_ORIGINAL_CHARS = 120
const MIN_REPLACEMENT_RATIO = 0.55
const MAX_REPLACEMENT_RATIO = 3.5
const MAX_REPLACEMENT_GROWTH_CHARS = 240

function validatePatchScope(originalText, replacementText) {
  if (originalText.length > MAX_PATCH_ORIGINAL_CHARS) return 'overbroad_patch'

  if (
    originalText.length >= OVERCOMPRESS_MIN_ORIGINAL_CHARS &&
    replacementText.length < Math.round(originalText.length * MIN_REPLACEMENT_RATIO)
  ) {
    return 'overcompressed_patch'
  }

  const maxReplacementLength = Math.max(
    Math.round(originalText.length * MAX_REPLACEMENT_RATIO),
    originalText.length + MAX_REPLACEMENT_GROWTH_CHARS
  )
  if (replacementText.length > maxReplacementLength) return 'overexpanded_patch'

  return ''
}

function findAllIndexes(content, needle) {
  const indexes = []
  if (!content || !needle) return indexes
  let start = 0
  while (start < content.length) {
    const index = content.indexOf(needle, start)
    if (index === -1) break
    indexes.push(index)
    start = index + Math.max(needle.length, 1)
  }
  return indexes
}

function compactWithMap(value) {
  const compact = []
  const map = []
  const text = String(value || '')

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    if (/\s/.test(char)) continue
    compact.push(char)
    map.push(i)
  }

  return { text: compact.join(''), map }
}

function isLooseIgnoredChar(char) {
  return /[\s，。！？；：、“”‘’（）《》【】…—\-—–—,.!?;:"'()[\]{}<>]/.test(char)
}

function looseCompactWithMap(value) {
  const compact = []
  const map = []
  const text = String(value || '')

  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    if (isLooseIgnoredChar(char)) continue
    compact.push(char)
    map.push(i)
  }

  return { text: compact.join(''), map }
}

function findWhitespaceTolerantMatches(content, needle) {
  const compactNeedle = compactWithMap(needle).text
  if (compactNeedle.length < 12) return []

  const compactContent = compactWithMap(content)
  const matches = []
  let start = 0

  while (start < compactContent.text.length) {
    const index = compactContent.text.indexOf(compactNeedle, start)
    if (index === -1) break
    const originalStart = compactContent.map[index]
    let originalEnd = compactContent.map[index + compactNeedle.length - 1] + 1
    while (
      originalEnd < String(content || '').length &&
      isLooseIgnoredChar(String(content || '')[originalEnd]) &&
      isLooseIgnoredChar(String(needle || '').trim().slice(-1))
    ) {
      originalEnd += 1
    }
    matches.push({
      startIndex: originalStart,
      endIndex: originalEnd,
      matchedText: String(content || '').slice(originalStart, originalEnd)
    })
    start = index + Math.max(compactNeedle.length, 1)
  }

  return matches
}

function findPunctuationTolerantMatches(content, needle) {
  const compactNeedle = looseCompactWithMap(needle).text
  if (compactNeedle.length < 12) return []

  const compactContent = looseCompactWithMap(content)
  const matches = []
  let start = 0

  while (start < compactContent.text.length) {
    const index = compactContent.text.indexOf(compactNeedle, start)
    if (index === -1) break
    const originalStart = compactContent.map[index]
    let originalEnd = compactContent.map[index + compactNeedle.length - 1] + 1
    while (
      originalEnd < String(content || '').length &&
      isLooseIgnoredChar(String(content || '')[originalEnd]) &&
      isLooseIgnoredChar(String(needle || '').trim().slice(-1))
    ) {
      originalEnd += 1
    }
    matches.push({
      startIndex: originalStart,
      endIndex: originalEnd,
      matchedText: String(content || '').slice(originalStart, originalEnd)
    })
    start = index + Math.max(compactNeedle.length, 1)
  }

  return matches
}

function findUniquePatchMatch(content, originalText) {
  const exactMatches = findAllIndexes(content, originalText)
  if (exactMatches.length === 1) {
    return {
      type: 'exact',
      startIndex: exactMatches[0],
      endIndex: exactMatches[0] + originalText.length,
      matchedText: originalText
    }
  }
  if (exactMatches.length > 1) return { type: 'ambiguous', count: exactMatches.length }

  const whitespaceMatches = findWhitespaceTolerantMatches(content, originalText)
  if (whitespaceMatches.length === 1) {
    return { type: 'whitespace_tolerant', ...whitespaceMatches[0] }
  }
  if (whitespaceMatches.length > 1) return { type: 'ambiguous', count: whitespaceMatches.length }

  const punctuationMatches = findPunctuationTolerantMatches(content, originalText)
  if (punctuationMatches.length === 1) {
    return { type: 'punctuation_tolerant', ...punctuationMatches[0] }
  }
  if (punctuationMatches.length > 1) return { type: 'ambiguous', count: punctuationMatches.length }

  return null
}

export function applyLocalRevisionPatches(originalContent, patches = []) {
  let content = String(originalContent || '')
  const applied = []
  const skipped = []

  for (const [index, patch] of (Array.isArray(patches) ? patches : []).entries()) {
    const originalText = normalizePatchText(patch?.originalText)
    const replacementText = normalizePatchText(patch?.replacementText)
    const issueIndex = Number(patch?.issueIndex || index + 1)

    if (!originalText || !replacementText) {
      skipped.push({ ...patch, issueIndex, reason: 'empty_patch' })
      continue
    }

    if (originalText === replacementText) {
      skipped.push({ ...patch, issueIndex, reason: 'unchanged_patch' })
      continue
    }

    const scopeError = validatePatchScope(originalText, replacementText)
    if (scopeError) {
      skipped.push({ ...patch, issueIndex, reason: scopeError })
      continue
    }

    const match = findUniquePatchMatch(content, originalText)
    if (!match) {
      skipped.push({ ...patch, issueIndex, reason: 'no_match' })
      continue
    }

    if (match.type === 'ambiguous') {
      skipped.push({ ...patch, issueIndex, reason: 'ambiguous_match' })
      continue
    }

    content = content.slice(0, match.startIndex) + replacementText + content.slice(match.endIndex)
    applied.push({
      ...patch,
      issueIndex,
      originalText,
      replacementText,
      matchedText: match.matchedText,
      matchType: match.type,
      startIndex: match.startIndex
    })
  }

  return { content, applied, skipped }
}

export function normalizeLocalRevisionPatches(payload) {
  const source = Array.isArray(payload)
    ? payload
    : Array.isArray(payload?.patches)
      ? payload.patches
      : Array.isArray(payload?.localPatches)
        ? payload.localPatches
        : Array.isArray(payload?.revisions)
          ? payload.revisions
          : Array.isArray(payload?.changes)
            ? payload.changes
            : Array.isArray(payload?.edits)
              ? payload.edits
              : Array.isArray(payload?.items)
                ? payload.items
                : []

  return source
    .map((patch, index) => ({
      issueIndex: Number(patch?.issueIndex || patch?.issue_index || index + 1),
      originalText: normalizePatchText(
        patch?.originalText ||
        patch?.original_text ||
        patch?.sourceText ||
        patch?.source_text ||
        patch?.oldText ||
        patch?.old_text ||
        patch?.before ||
        patch?.find
      ),
      replacementText: normalizePatchText(
        patch?.replacementText ||
        patch?.replacement_text ||
        patch?.revisedText ||
        patch?.revised_text ||
        patch?.newText ||
        patch?.new_text ||
        patch?.after ||
        patch?.replace
      ),
      contextBefore: normalizePatchText(
        patch?.contextBefore ||
        patch?.context_before ||
        patch?.beforeContext ||
        patch?.before_context
      ),
      contextAfter: normalizePatchText(
        patch?.contextAfter ||
        patch?.context_after ||
        patch?.afterContext ||
        patch?.after_context
      ),
      reason: String(patch?.reason || patch?.changeReason || patch?.change_reason || ''),
      confidence: Number(patch?.confidence ?? 0.7)
    }))
    .filter(patch => patch.originalText && patch.replacementText)
}

function cleanJsonCandidate(candidate) {
  return String(candidate || '')
    .trim()
    .replace(/^```(?:json)?/i, '')
    .replace(/```$/i, '')
    .trim()
}

function removeTrailingJsonCommas(text) {
  return String(text || '').replace(/,\s*([}\]])/g, '$1')
}

function parseJsonCandidate(candidate) {
  const cleaned = cleanJsonCandidate(candidate)
  try {
    return JSON.parse(cleaned)
  } catch {
    return JSON.parse(removeTrailingJsonCommas(cleaned))
  }
}

function findMatchingBrace(text, startIndex) {
  let depth = 0
  let inString = false
  let escaped = false

  for (let i = startIndex; i < text.length; i += 1) {
    const char = text[i]
    if (inString) {
      if (escaped) {
        escaped = false
      } else if (char === '\\') {
        escaped = true
      } else if (char === '"') {
        inString = false
      }
      continue
    }

    if (char === '"') {
      inString = true
    } else if (char === '{') {
      depth += 1
    } else if (char === '}') {
      depth -= 1
      if (depth === 0) return i
    }
  }

  return -1
}

function extractBalancedJsonObjects(text) {
  const source = String(text || '')
  const objects = []

  for (let i = 0; i < source.length; i += 1) {
    if (source[i] !== '{') continue
    const end = findMatchingBrace(source, i)
    if (end === -1) continue
    objects.push(source.slice(i, end + 1))
  }

  return objects
}

export function extractLocalRevisionPatches(rawText) {
  const text = typeof rawText === 'string' ? rawText : JSON.stringify(rawText || '')
  const candidates = []
  const cleaned = cleanJsonCandidate(text)
  candidates.push(cleaned)

  const objectMatch = cleaned.match(/\{[\s\S]*\}/)
  if (objectMatch) candidates.push(objectMatch[0])

  const arrayMatch = cleaned.match(/\[[\s\S]*\]/)
  if (arrayMatch) candidates.push(arrayMatch[0])

  for (const candidate of candidates) {
    try {
      const parsed = parseJsonCandidate(candidate)
      const patches = normalizeLocalRevisionPatches(parsed)
      if (patches.length) return patches
    } catch {
      // Try next candidate.
    }
  }

  const objectCandidates = extractBalancedJsonObjects(cleaned)
  for (const candidate of objectCandidates) {
    try {
      const parsed = parseJsonCandidate(candidate)
      const patches = normalizeLocalRevisionPatches(parsed)
      if (patches.length) return patches
      const singlePatch = normalizeLocalRevisionPatches([parsed])
      if (singlePatch.length) return singlePatch
    } catch {
      // Try next balanced object.
    }
  }

  return []
}

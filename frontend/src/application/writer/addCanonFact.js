import { generateId } from '../../utils/id.js'
import { sha256Text } from '../../utils/sha256Text.js'
import { unicodeScalarLength } from '../../utils/unicodeScalarText.js'
import { evidenceExcerpt } from './finalizationEvidence.js'

// Match Python source_paragraphs whitespace and absolute end semantics.
const whitespace = '\\t-\\r\\x1c-\\x20\\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000'
const invalid = () => new TypeError('Invalid author fact')

export function candidateSourceParagraphs(prose) {
  unicodeScalarLength(prose)
  const pattern = new RegExp(`[^${whitespace}][\\s\\S]*?(?=\\r?\\n[${whitespace}]*\\r?\\n|(?![\\s\\S]))`, 'gu')
  const paragraphs = []
  let previousEnd = 0
  let scalarEnd = 0
  for (const match of prose.matchAll(pattern)) {
    const start = scalarEnd + unicodeScalarLength(prose.slice(previousEnd, match.index))
    scalarEnd = start + unicodeScalarLength(match[0])
    previousEnd = match.index + match[0].length
    paragraphs.push({ id: `p${paragraphs.length + 1}`, text: match[0], startScalar: start, endScalar: scalarEnd })
  }
  return paragraphs
}

export function authorFactEvidenceRange(prose, startId, endId) {
  const paragraphs = candidateSourceParagraphs(prose)
  const first = paragraphs.findIndex(item => item.id === startId)
  const last = paragraphs.findIndex(item => item.id === endId)
  if (first < 0 || last < first) throw invalid()
  const range = { startScalar: paragraphs[first].startScalar, endScalar: paragraphs[last].endScalar }
  return { ...range, excerpt: evidenceExcerpt(prose, range) }
}

export async function buildAuthorCanonFact({
  candidateContent, chapterNumber, entities = [], entityId = null,
  factKind = 'dynamic_event', fieldPath = 'author.observation', value, startId, endId,
}, { idFactory = generateId, hashText = sha256Text } = {}) {
  if (!Number.isSafeInteger(chapterNumber) || chapterNumber < 1
    || !['dynamic_event', 'claim', 'stable_definition'].includes(factKind)
    || typeof fieldPath !== 'string' || !fieldPath.trim() || unicodeScalarLength(fieldPath.trim()) > 200
    || fieldPath.trim().startsWith('plot.progress.')
    || typeof value !== 'string' || !value.trim() || unicodeScalarLength(value.trim()) > 4000
    || !Array.isArray(entities)
    || (entityId !== null && (typeof entityId !== 'string' || !entities.some(item => item?.id === entityId)))) throw invalid()
  const evidence = authorFactEvidenceRange(candidateContent, startId, endId)
  const excerptHash = await hashText(evidence.excerpt)
  const id = idFactory()
  if (typeof id !== 'string' || !id || id.length > 100 || !/^[a-f0-9]{64}$/u.test(excerptHash)) throw invalid()
  return {
    id, entityId, factKind, fieldPath: fieldPath.trim(), value: value.trim(),
    evidence: { startScalar: evidence.startScalar, endScalar: evidence.endScalar, excerptHash,
      confidence: 1, rationale: '作者对照原文补录' },
    effectiveStartChapter: chapterNumber, effectiveEndChapter: null,
    assertionOperator: 'equals', valueCardinality: 'multi',
  }
}

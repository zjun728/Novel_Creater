import { sha256Text } from '../../utils/sha256Text.js'

export async function resolveReviewRange({ prose, candidate, review, evidence }) {
  if (!candidate || !review || candidate.id !== review.candidateId
    || candidate.contentHash !== review.candidateHash || candidate.basisStatus !== 'current'
    || candidate.content !== prose) return null
  const excerpt = evidenceExcerpt(prose, evidence)
  if (!excerpt || await sha256Text(excerpt) !== evidence.excerptHash) return null
  if (await sha256Text(prose) !== review.candidateHash) return null
  return { startOffset: evidence.startScalar, endOffset: evidence.endScalar, selectedText: excerpt }
}

export function evidenceExcerpt(prose, evidence) {
  if (typeof prose !== 'string' || !evidence) return ''
  const scalars = Array.from(prose)
  const { startScalar: start, endScalar: end } = evidence
  if (!Number.isInteger(start) || !Number.isInteger(end)
    || start < 0 || end <= start || end > scalars.length) return ''
  return scalars.slice(start, end).join('')
}

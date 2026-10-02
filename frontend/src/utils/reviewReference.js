const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const HASH = /^[0-9a-f]{64}$/
const fields = ['attemptId', 'candidateId', 'candidateHash', 'changeSetRevision', 'changeSetHash', 'qualityReportHash']
export const latestDispute = (decisions, id) => (decisions?.disputeEvents || []).filter(event => event.findingId === id).at(-1)
export const effectiveReviewFindings = review => (review?.qualityReport?.findings || []).filter(item => !(review?.findingDecisions?.ignoredFindingIds || []).includes(item.id) && !(item.severity === 'required' && latestDispute(review?.findingDecisions, item.id)?.action === 'retain'))

export function normalizeReviewReference(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || Object.keys(value).some(key => ![...fields, 'decisionsRevision'].includes(key)) || fields.some(key => !Object.hasOwn(value, key))
    || (Object.hasOwn(value, 'decisionsRevision') && (!Number.isSafeInteger(value.decisionsRevision) || value.decisionsRevision < 0))
    || ['attemptId', 'candidateId'].some(key => typeof value[key] !== 'string' || !UUID.test(value[key]))
    || ['candidateHash', 'changeSetHash', 'qualityReportHash'].some(key => typeof value[key] !== 'string' || !HASH.test(value[key]))
    || !Number.isSafeInteger(value.changeSetRevision) || value.changeSetRevision < 1) {
    throw new TypeError('Invalid review reference')
  }
  return Object.freeze({ ...Object.fromEntries(fields.map(key => [key, value[key]])), ...(Object.hasOwn(value, 'decisionsRevision') ? { decisionsRevision: value.decisionsRevision } : {}) })
}

export function referenceFromReview(review) {
  if (review?.status !== 'awaiting_author' || review.qualityReport?.status !== 'completed'
    || !(effectiveReviewFindings(review).length || review.qualityReport.deterministicBlocks?.length)) return null
  try {
    return normalizeReviewReference({ attemptId: review.attemptId, candidateId: review.candidateId,
      candidateHash: review.candidateHash, changeSetRevision: review.changeSet?.revision,
      changeSetHash: review.changeSet?.contentHash, qualityReportHash: review.qualityReport.contentHash,
      ...(review.findingDecisions ? { decisionsRevision: review.findingDecisions.revision } : {}) })
  } catch { return null }
}

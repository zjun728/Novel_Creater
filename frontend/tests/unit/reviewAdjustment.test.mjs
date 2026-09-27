import assert from 'node:assert/strict'
import test from 'node:test'
import { normalizeReviewReference, referenceFromReview } from '../../src/utils/reviewReference.js'
import { saveThenAdjustReview } from '../../src/application/writer/reviewAdjustment.js'

const reference = normalizeReviewReference({ attemptId: '40000000-0000-4000-8000-000000000001',
  candidateId: '50000000-0000-4000-8000-000000000001', candidateHash: 'a'.repeat(64),
  changeSetRevision: 2, changeSetHash: 'b'.repeat(64), qualityReportHash: 'c'.repeat(64) })
test('review adjustment saves old draft before generating and sends references only', async () => {
  const calls = []
  await saveThenAdjustReview({ reference, isCurrent: () => true,
    saveCandidate: async () => { calls.push('save'); return true },
    generate: async value => { calls.push(value) } })
  assert.deepEqual(calls, ['save', { reviewReference: reference }])
})
test('failed save prevents generation', async () => {
  let starts = 0
  await assert.rejects(saveThenAdjustReview({ reference, isCurrent: () => true,
    saveCandidate: async () => false, generate: () => { starts++ } }), /旧稿未能保存/)
  assert.equal(starts, 0)
})
test('review or context changed during save prevents generation', async () => {
  let current = true, starts = 0
  await assert.rejects(saveThenAdjustReview({ reference, isCurrent: () => current,
    saveCandidate: async () => { current = false; return true }, generate: () => { starts++ } }), /保存期间/)
  assert.equal(starts, 0)
})
test('only current completed reports with opinions can be referenced', () => {
  const review = { status: 'awaiting_author', ...reference,
    changeSet: { revision: 2, contentHash: reference.changeSetHash },
    qualityReport: { status: 'completed', contentHash: reference.qualityReportHash, findings: [{ reason: '问题' }], deterministicBlocks: [] } }
  assert.deepEqual(referenceFromReview(review), reference)
  assert.equal(referenceFromReview({ ...review, status: 'cancelled' }), null)
  assert.equal(referenceFromReview({ ...review, qualityReport: { ...review.qualityReport, findings: [] } }), null)
  assert.throws(() => normalizeReviewReference({ ...reference, opinions: '不得拼接意见' }))
})

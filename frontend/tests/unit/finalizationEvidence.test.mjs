import assert from 'node:assert/strict'
import test from 'node:test'
import { evidenceExcerpt, resolveReviewRange } from '../../src/application/writer/finalizationEvidence.js'
import { sha256Text } from '../../src/utils/sha256Text.js'

test('evidence preview uses Unicode scalars of the frozen candidate and rejects invalid ranges', () => {
  assert.equal(evidenceExcerpt('前😀。耳鸣。', { startScalar: 3, endScalar: 6 }), '耳鸣。')
  for (const evidence of [null, { startScalar: -1, endScalar: 2 }, { startScalar: 0, endScalar: 99 }, { startScalar: 2, endScalar: 1 }]) {
    assert.equal(evidenceExcerpt('正文', evidence), '')
  }
})

test('review location validates the frozen candidate, current prose and evidence hashes', async () => {
  const prose = '前😀。耳鸣。'
  const candidate = { id: 'c1', content: prose, contentHash: await sha256Text(prose), basisStatus: 'current' }
  const review = { candidateId: candidate.id, candidateHash: candidate.contentHash }
  const evidence = { startScalar: 3, endScalar: 6, excerptHash: await sha256Text('耳鸣。') }
  const input = { prose, candidate, review, evidence }
  assert.deepEqual(await resolveReviewRange(input), { startOffset: 3, endOffset: 6, selectedText: '耳鸣。' })
  for (const changed of [
    { prose: '正文已经修改' },
    { candidate: { ...candidate, basisStatus: 'stale' } },
    { review: { ...review, candidateHash: '0'.repeat(64) } },
    { evidence: { ...evidence, excerptHash: '0'.repeat(64) } },
    { evidence: { ...evidence, endScalar: 100 } },
    { evidence: null },
  ]) assert.equal(await resolveReviewRange({ ...input, ...changed }), null)
})

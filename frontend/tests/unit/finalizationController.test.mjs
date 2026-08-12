import assert from 'node:assert/strict'
import test from 'node:test'
import { reactive } from 'vue'

import { createFinalizationController } from '../../src/application/writer/finalizationController.js'


const HASH_A = 'a'.repeat(64)
const HASH_B = 'b'.repeat(64)
const candidate = {
  id: 'candidate-1', contentHash: HASH_A, basisStatus: 'current',
  canonRevision: 0, planningHash: HASH_A, outlineHash: HASH_B,
}
const payload = {
  schemaVersion: 'finalization-changeset-v1',
  title: '第一章', summary: '旧摘要', existingEntityIds: [],
  entities: [], aliases: [], canonEvents: [], storyProgressEvents: [],
  planningPatches: [], planningSuggestions: [],
}
const review = {
  attemptId: 'attempt-1', status: 'awaiting_author',
  candidateId: candidate.id, candidateHash: candidate.contentHash,
  qualityReport: {
    status: 'completed', deterministicBlocks: [], findings: [], contentHash: HASH_A,
  },
  changeSet: {
    revision: 1, contentHash: HASH_A, source: 'extraction', payload,
  },
  confirmation: null,
}


test('prepare, correct, confirm and commit expose one fenced primary action', async () => {
  const calls = []
  let current = structuredClone(review)
  const controller = createFinalizationController({
    getReview: async () => structuredClone(current),
    prepare: async (candidateId, command) => {
      calls.push(['prepare', candidateId, command])
      return { attemptId: 'attempt-1', status: 'awaiting_author' }
    },
    correct: async command => {
      calls.push(['correct', command])
      current = {
        ...current,
        changeSet: {
          revision: 2, contentHash: HASH_B,
          source: 'author_correction', payload: command.changeSet,
        },
      }
      return { currentRevision: 2, currentRevisionHash: HASH_B }
    },
    confirm: async command => {
      calls.push(['confirm', command])
      current = {
        ...current,
        confirmation: { revision: 2, contentHash: HASH_B },
      }
      return { confirmedRevision: 2, confirmedRevisionHash: HASH_B }
    },
    commit: async command => {
      calls.push(['commit', command])
      current = { ...current, status: 'committed' }
      return {
        recordId: 'record-1', finalChapterId: 'chapter-1', canonRevision: 1,
        projectionHash: HASH_A, planningRevisionId: 'planning-2',
        planningRevision: 2, planningHash: HASH_B, replayed: false,
      }
    },
    onCommitted: async () => calls.push(['reload']),
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })

  await controller.prepareCandidate(candidate)
  assert.equal(controller.primaryAction.value, 'confirm')
  assert.equal(calls[0][2].candidateHash, HASH_A)
  assert.equal(calls[0][2].expectedCanonRevision, 0)
  assert.match(calls[0][2].idempotencyKey, /^[a-f0-9]{64}$/u)

  await controller.correctChangeSet(reactive({ ...payload, summary: '作者修正摘要' }))
  assert.equal(controller.review.value.changeSet.revision, 2)
  await controller.confirmChangeSet()
  assert.equal(controller.primaryAction.value, 'commit')
  const result = await controller.commitChapter()

  assert.equal(result.finalChapterId, 'chapter-1')
  assert.equal(controller.primaryAction.value, 'done')
  assert.equal(controller.finalized.value, true)
  assert.deepEqual(calls.at(-1), ['reload'])
  assert.deepEqual(calls[1][1], {
    expectedRevision: 1,
    expectedRevisionHash: HASH_A,
    changeSet: { ...payload, summary: '作者修正摘要' },
  })
  assert.equal(calls[3][1].expectedRevision, 2)
  assert.match(calls[3][1].idempotencyKey, /^[a-f0-9]{64}$/u)
})


test('hard blocks and stale candidates cannot cross the author confirmation boundary', async () => {
  let calls = 0
  const controller = createFinalizationController({
    getReview: async () => ({
      ...review,
      status: 'failed',
      qualityReport: {
        ...review.qualityReport,
        deterministicBlocks: [{ code: 'planning_drift', message: '已变化', evidence: null }],
      },
      changeSet: null,
    }),
    prepare: async () => { calls += 1 },
    correct: async () => { calls += 1 },
    confirm: async () => { calls += 1 },
    commit: async () => { calls += 1 },
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })

  await assert.rejects(
    () => controller.prepareCandidate({ ...candidate, basisStatus: 'stale' }),
    TypeError,
  )
  await controller.load()
  assert.equal(controller.primaryAction.value, 'blocked')
  await assert.rejects(() => controller.confirmChangeSet(), TypeError)
  await assert.rejects(() => controller.commitChapter(), TypeError)
  assert.equal(calls, 0)
})


test('unknown commit result recovers with GET and never issues a second commit', async () => {
  let commitCalls = 0
  let getCalls = 0
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => {
      getCalls += 1
      return getCalls === 1 ? confirmed : { ...confirmed, status: 'committed' }
    },
    commit: async () => {
      commitCalls += 1
      throw Object.assign(new Error('transport detail'), { status: 0 })
    },
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })

  await controller.load()
  const recovered = await controller.commitChapter()

  assert.equal(recovered, null)
  assert.equal(commitCalls, 1)
  assert.equal(getCalls, 2)
  assert.equal(controller.finalized.value, true)
  assert.equal(controller.error.value, '')
})


test('load treats the explicit empty review as prepare state', async () => {
  const controller = createFinalizationController({
    getReview: async () => null,
  })

  const loaded = await controller.load()

  assert.equal(loaded, null)
  assert.equal(controller.review.value, null)
  assert.equal(controller.primaryAction.value, 'prepare')
  assert.equal(controller.error.value, '')
})


test('load does not reclassify a real 404 as an empty review', async () => {
  const failure = Object.assign(new Error('not found'), { status: 404 })
  const controller = createFinalizationController({
    getReview: async () => { throw failure },
  })

  await assert.rejects(controller.load(), error => error === failure)

  assert.equal(controller.review.value, null)
  assert.equal(controller.primaryAction.value, 'prepare')
  assert.equal(controller.error.value, '定稿审查状态加载失败，请刷新后重试。')
})


test('a reset fences a late review from the previous chapter context', async () => {
  let release
  const controller = createFinalizationController({
    getReview: () => new Promise(resolve => { release = resolve }),
  })

  const pending = controller.load()
  controller.reset()
  release(structuredClone(review))
  const loaded = await pending

  assert.equal(loaded, null)
  assert.equal(controller.review.value, null)
  assert.equal(controller.busy.value, false)
})


test('a failed local refresh cannot turn a confirmed server commit into an error', async () => {
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async () => ({
      recordId: 'record-1', finalChapterId: 'chapter-1', canonRevision: 1,
      projectionHash: HASH_A, planningRevisionId: 'planning-2',
      planningRevision: 2, planningHash: HASH_B, replayed: false,
    }),
    onCommitted: async () => { throw new Error('local refresh failed') },
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })
  await controller.load()

  const committed = await controller.commitChapter()

  assert.equal(committed.finalChapterId, 'chapter-1')
  assert.equal(controller.finalized.value, true)
  assert.equal(controller.error.value, '')
})

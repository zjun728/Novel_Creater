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

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

test('accepted correction with lost reread fences writes until R2 is authoritatively recovered', async () => {
  let server = structuredClone(review)
  let readFailure = false
  const commands = []
  const controller = createFinalizationController({
    getReview: async () => {
      if (readFailure) throw Object.assign(new Error('read unavailable'), { status: 503 })
      return structuredClone(server)
    },
    correct: async command => {
      commands.push(command)
      assert.equal(command.expectedRevision, server.changeSet.revision)
      assert.equal(command.expectedRevisionHash, server.changeSet.contentHash)
      server.changeSet = { revision: 2, contentHash: HASH_B, payload: structuredClone(command.changeSet) }
      readFailure = true
      return { currentRevision: 2, currentRevisionHash: HASH_B }
    },
  })
  const draft = { ...payload, summary: '作者修正摘要' }
  await controller.load()
  await assert.rejects(controller.correctChangeSet(draft), /read unavailable/)
  assert.equal(server.changeSet.revision, 2)
  assert.equal(controller.review.value.changeSet.revision, 1)
  assert.match(controller.error.value, /已被服务端接受.*读取失败/)
  assert.doesNotMatch(controller.error.value, /未保存|重试/)
  assert.equal(controller.correctionRecovery.value, 'accepted')
  assert.equal(controller.recoveryPending.value, true)
  for (const action of [
    () => controller.correctChangeSet(draft), () => controller.confirmChangeSet(),
    () => controller.cancelReview(), () => controller.prepareCandidate(candidate),
    () => controller.setFindingIgnored('optional', true),
    () => controller.saveFindingDispute({ findingId: 'required', action: 'retain' }),
    () => controller.commitChapter(), () => controller.revokeReview(),
  ]) assert.equal(await action(), false)
  assert.equal(commands.length, 1)
  await assert.rejects(controller.load(), /read unavailable/)
  assert.equal(controller.recoveryPending.value, true)
  assert.match(controller.error.value, /刷新核对修正/)
  readFailure = false
  await controller.load()
  assert.equal(controller.review.value.changeSet.revision, 2)
  assert.equal(controller.review.value.changeSet.contentHash, HASH_B)
  assert.equal(controller.review.value.changeSet.payload.summary, draft.summary)
  assert.equal(controller.recoveryPending.value, false)
  assert.equal(controller.correctionRecovery.value, '')
  assert.equal(controller.error.value, '')
  await assert.rejects(controller.correctChangeSet({ ...draft, summary: '再次明确修改' }))
  assert.equal(commands[1].expectedRevision, 2)
  assert.equal(commands[1].expectedRevisionHash, HASH_B)
})

test('definitive correction rejection preserves the authoritative version and submitted draft', async () => {
  let reads = 0
  const failure = Object.assign(new Error('invalid correction'), { status: 422 })
  const draft = reactive({ ...payload, summary: '保留作者输入' })
  const controller = createFinalizationController({
    getReview: async () => { reads += 1; return structuredClone(review) },
    correct: async command => {
      assert.equal(command.expectedRevision, 1)
      assert.equal(command.expectedRevisionHash, HASH_A)
      throw failure
    },
  })
  await controller.load()
  await assert.rejects(controller.correctChangeSet(draft), error => error === failure)
  assert.equal(reads, 1)
  assert.deepEqual(controller.review.value, review)
  assert.equal(draft.summary, '保留作者输入')
  assert.equal(controller.recoveryPending.value, false)
  assert.equal(controller.correctionRecovery.value, '')
  assert.match(controller.error.value, /未保存/)
})

test('lost correction response is unknown for both saved and unsaved server outcomes', async t => {
  for (const status of [0, 408, 500, 502, 200]) {
    for (const saved of [false, true]) {
      await t.test(`status=${status}, saved=${saved}`, async () => {
        let server = structuredClone(review)
        let writes = 0
        let reads = 0
        const draft = { ...payload, summary: '未知结果的作者修改' }
        const controller = createFinalizationController({
          getReview: async () => { reads += 1; return structuredClone(server) },
          correct: async () => {
            writes += 1
            if (saved) server.changeSet = { revision: 2, contentHash: HASH_B, payload: draft }
            throw Object.assign(new Error('response unavailable'), { status })
          },
        })
        await controller.load()
        await assert.rejects(controller.correctChangeSet(draft), /response unavailable/)
        assert.equal(reads, 1)
        assert.equal(controller.recoveryPending.value, true)
        assert.equal(controller.correctionRecovery.value, 'unknown')
        assert.match(controller.error.value, /保存结果尚未确认.*刷新核对修正/)
        assert.doesNotMatch(controller.error.value, /未保存|重试/)
        assert.equal(await controller.correctChangeSet(draft), false)
        assert.equal(writes, 1)
        await controller.load()
        assert.equal(controller.review.value.changeSet.revision, saved ? 2 : 1)
        assert.equal(controller.review.value.changeSet.payload.summary, saved ? draft.summary : payload.summary)
        assert.equal(controller.recoveryPending.value, false)
      })
    }
  }
})

test('correction never bypasses missing version pins or a stale revision/hash rejection', async () => {
  let server = structuredClone(review)
  let writes = 0
  const controller = createFinalizationController({
    getReview: async () => structuredClone(server),
    correct: async command => {
      writes += 1
      if (command.expectedRevision !== server.changeSet.revision
        || command.expectedRevisionHash !== server.changeSet.contentHash) {
        throw Object.assign(new Error('CAS conflict'), { status: 409 })
      }
    },
  })
  await controller.load()
  controller.review.value = { ...review, changeSet: { ...review.changeSet, contentHash: 'invalid' } }
  await assert.rejects(controller.correctChangeSet(payload), /revision is required/)
  assert.equal(writes, 0)
  assert.equal(controller.recoveryPending.value, false)
  await controller.load()
  server.changeSet = { ...server.changeSet, revision: 2, contentHash: HASH_B }
  await assert.rejects(controller.correctChangeSet(payload), /CAS conflict/)
  assert.equal(controller.review.value.changeSet.revision, 1)
  assert.equal(controller.recoveryPending.value, false)
  await controller.load()
  controller.review.value = { ...controller.review.value, changeSet: { ...server.changeSet, contentHash: HASH_A } }
  await assert.rejects(controller.correctChangeSet(payload), /CAS conflict/)
  assert.equal(writes, 2)
})

test('reset discards late correction outcomes without locking the new chapter or rereading', async t => {
  for (const accepted of [true, false]) {
    await t.test(`accepted=${accepted}`, async () => {
      const pending = deferred()
      let reads = 0
      const controller = createFinalizationController({
        getReview: async () => { reads += 1; return structuredClone(review) },
        correct: () => pending.promise,
      })
      await controller.load()
      const action = controller.correctChangeSet(payload)
      controller.reset()
      if (accepted) pending.resolve({ currentRevision: 2, currentRevisionHash: HASH_B })
      else pending.reject(Object.assign(new Error('lost response'), { status: 0 }))
      assert.equal(await action, null)
      assert.equal(reads, 1)
      assert.equal(controller.review.value, null)
      assert.equal(controller.recoveryPending.value, false)
      assert.equal(controller.correctionRecovery.value, '')
      assert.equal(controller.error.value, '')
    })
  }
})

test('finding decision saves report identity and revision, failure retains authoritative state', async () => {
  const initial = structuredClone(review)
  initial.qualityReport.findings = [{ id: 'optional', severity: 'optional' }]
  initial.findingDecisions = { revision: 0, ignoredFindingIds: [] }
  let fail = false
  const calls = []
  const controller = createFinalizationController({ getReview: async () => structuredClone(initial), decideFinding: async command => {
    calls.push(command)
    if (fail) throw Error('conflict')
    return { ...initial, findingDecisions: { revision: 1, ignoredFindingIds: ['optional'] } }
  } })
  await controller.load()
  await controller.setFindingIgnored('optional', true)
  assert.equal(calls[0].qualityReportHash, HASH_A)
  assert.equal(calls[0].expectedDecisionsRevision, 0)
  assert.equal(controller.review.value.findingDecisions.revision, 1)
  fail = true
  await assert.rejects(controller.setFindingIgnored('optional', false))
  assert.deepEqual(controller.review.value.findingDecisions.ignoredFindingIds, ['optional'])
  assert.match(controller.error.value, /重新读取/)
})

const preparation = {
  lifecycle: 'active',
  nextAction: 'prepare_chapter_outline',
  targetPath: '/projects/p1/planning/story-blocks',
  authoritativeChapterNumber: 5,
}

test('author dispute is version-bound and failed save preserves previous decisions', async () => {
  const initial = structuredClone(review)
  initial.qualityReport.findings = [{ id: 'required', severity: 'required' }]
  initial.findingDecisions = { revision: 0, ignoredFindingIds: [] }
  let fail = false
  const calls = []
  const controller = createFinalizationController({ getReview: async () => structuredClone(initial),
    disputeFinding: async command => {
      calls.push(command)
      if (fail) throw Error('conflict')
      return { ...initial, findingDecisions: { revision: 1, ignoredFindingIds: [], disputeEvents: [{ findingId: 'required', action: 'note' }] } }
    } })
  await controller.load()
  await controller.saveFindingDispute({ findingId: 'required', action: 'note', reason: '新状态', category: 'state_change', evidence: [] })
  assert.equal(calls[0].attemptId, initial.attemptId)
  assert.equal(calls[0].qualityReportHash, HASH_A)
  assert.equal(calls[0].expectedDecisionsRevision, 0)
  assert.match(calls[0].eventId, /^[a-f0-9]{64}$/)
  await assert.rejects(controller.confirmChangeSet())
  fail = true
  await assert.rejects(controller.saveFindingDispute({ findingId: 'required', action: 'retain' }))
  assert.equal(controller.review.value.findingDecisions.disputeEvents[0].action, 'note')
})

test('retained required opinion confirms with exact author revision; revoke restores block', async () => {
  const initial = structuredClone(review)
  initial.qualityReport.findings = [{ id: 'required', severity: 'required' }]
  initial.findingDecisions = { revision: 2, ignoredFindingIds: [], disputeEvents: [{ findingId: 'required', action: 'note' }, { findingId: 'required', action: 'retain' }] }
  let received
  const controller = createFinalizationController({ getReview: async () => structuredClone(initial), confirm: async value => { received = value } })
  await controller.load()
  await controller.confirmChangeSet()
  assert.equal(received.expectedDecisionsRevisionPin, 2)
  initial.findingDecisions.disputeEvents.push({ findingId: 'required', action: 'revoke' })
  await controller.load()
  await assert.rejects(controller.confirmChangeSet())
})

function committed(chapterNumber = 4) {
  return {
    recordId: 'record-1', finalChapterId: 'chapter-1', chapterNumber,
    canonRevision: 1, projectionHash: HASH_A,
    planningRevisionId: 'planning-2', planningRevision: 2,
    planningHash: HASH_B, replayed: false,
  }
}

test('preflight conflicts explain unconfirmed review recovery without exposing backend details', async () => {
  for (const operation of ['correct', 'confirm']) {
    const failure = Object.assign(new Error('private protected outline detail'), {
      status: 409, code: 'FinalizationPreflightConflict',
    })
    const controller = createFinalizationController({
      getReview: async () => structuredClone(review),
      [operation]: async () => { throw failure },
    })
    await controller.load()
    const action = operation === 'correct'
      ? () => controller.correctChangeSet(payload)
      : () => controller.confirmChangeSet()
    await assert.rejects(action, error => error === failure)
    assert.equal(controller.error.value, '规划调整不符合当前定稿依据，请在未确认时放弃本次审查并重新审查。')
    assert.deepEqual(controller.review.value, review)
    assert.equal(controller.primaryAction.value, 'confirm')
  }
})

test('a confirmed review still cannot be cancelled', async () => {
  let cancelCalls = 0
  const confirmed = { ...review, confirmation: { revision: 1, contentHash: HASH_A } }
  const controller = createFinalizationController({
    getReview: async () => structuredClone(confirmed),
    cancel: async () => { cancelCalls += 1 },
  })
  await controller.load()
  await assert.rejects(controller.cancelReview(), TypeError)
  assert.equal(cancelCalls, 0)
  assert.deepEqual(controller.review.value, confirmed)
})

test('revoking a confirmed review pins the exact attempt and never prepares automatically', async () => {
  let current = { ...review, confirmation: { revision: 1, contentHash: HASH_A } }
  const calls = []
  const controller = createFinalizationController({
    getReview: async () => structuredClone(current),
    revoke: async (attemptId, body) => {
      calls.push({ attemptId, ...body })
      current = { ...current, status: 'cancelled' }
    },
    prepare: async () => { throw new Error('must not prepare') },
  })
  await controller.load()
  await controller.revokeReview()
  assert.deepEqual(calls, [{ attemptId: 'attempt-1', expectedRevision: 1, expectedRevisionHash: HASH_A }])
  assert.equal(controller.review.value.status, 'cancelled')
  assert.equal(controller.primaryAction.value, 'blocked')
})

test('a lost revocation response is reconciled by exact read without repeating writes', async () => {
  let current = { ...review, confirmation: { revision: 1, contentHash: HASH_A } }
  let writes = 0
  const reads = []
  const controller = createFinalizationController({
    getReview: async () => structuredClone(current),
    revoke: async () => { writes += 1; current = { ...current, status: 'cancelled' }; throw Object.assign(new Error('lost'), { status: 0 }) },
    getAttemptState: async id => {
      reads.push(id)
      return { attemptId: id, status: 'cancelled', currentRevision: 1, currentRevisionHash: HASH_A,
        confirmedRevision: 1, confirmedRevisionHash: HASH_A }
    },
  })
  await controller.load()
  await controller.revokeReview()
  assert.equal(writes, 1)
  assert.deepEqual(reads, ['attempt-1'])
  assert.equal(controller.review.value.status, 'cancelled')
  assert.equal(controller.recoveryPending.value, false)
})

test('unresolved revocation blocks every write until a successful exact status read', async () => {
  let available = false
  let reviewUnavailable = false
  let writes = 0
  let current = { ...review, confirmation: { revision: 1, contentHash: HASH_A } }
  const controller = createFinalizationController({
    getReview: async () => {
      if (reviewUnavailable) throw new Error('review unavailable')
      return structuredClone(current)
    },
    revoke: async () => { writes += 1; throw Object.assign(new Error('lost'), { status: 504 }) },
    getAttemptState: async id => {
      if (!available) throw new Error('read unavailable')
      return { attemptId: id, status: 'cancelled', currentRevision: 1, currentRevisionHash: HASH_A,
        confirmedRevision: 1, confirmedRevisionHash: HASH_A }
    },
    prepare: async () => { writes += 1 }, commit: async () => { writes += 1 },
  })
  await controller.load()
  await assert.rejects(controller.revokeReview())
  assert.equal(controller.recoveryPending.value, true)
  await controller.revokeReview()
  await controller.commitChapter()
  await controller.prepareCandidate(candidate)
  assert.equal(writes, 1)
  available = true
  current = { ...current, status: 'cancelled' }
  reviewUnavailable = true
  await assert.rejects(controller.load())
  assert.equal(controller.recoveryPending.value, true)
  await controller.commitChapter()
  assert.equal(writes, 1)
  reviewUnavailable = false
  await controller.load()
  assert.equal(controller.recoveryPending.value, false)
  assert.equal(controller.review.value.status, 'cancelled')
})

test('committing and unknown commit outcomes cannot be revoked', async () => {
  for (const status of ['awaiting_author', 'committing']) {
    let calls = 0
    const controller = createFinalizationController({
      getReview: async () => ({ ...review, status, confirmation: { revision: 1, contentHash: HASH_A } }),
      commit: async () => { throw Object.assign(new Error('unknown'), { status: 504 }) },
      revoke: async () => { calls += 1 },
    })
    await controller.load()
    if (status === 'awaiting_author') await assert.rejects(controller.commitChapter())
    assert.equal(controller.canRevoke.value, false)
    await assert.rejects(controller.revokeReview())
    assert.equal(calls, 0)
  }
})


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


test('an unconfirmed review can be abandoned before returning to drafting', async () => {
  const calls = []
  let current = structuredClone(review)
  const controller = createFinalizationController({
    getReview: async () => structuredClone(current),
    cancel: async command => {
      calls.push(command)
      current = { ...current, status: 'cancelled' }
      return { status: 'cancelled' }
    },
  })
  await controller.load()

  await controller.cancelReview()

  assert.equal(controller.primaryAction.value, 'blocked')
  assert.equal(controller.review.value.status, 'cancelled')
  assert.deepEqual(calls, [{
    expectedRevision: 1,
    expectedRevisionHash: HASH_A,
  }])
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


test('commit preserves its chapter number and publishes two verified author paths after one refresh', async () => {
  const calls = []
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async () => committed(4),
    getProjectId: () => 'p1',
    getChapterNumber: () => 99,
    onCommitted: async () => { calls.push('committed') },
    reloadPreparation: async projectId => {
      calls.push(['preparation', projectId])
      return preparation
    },
    readFinalizedChapter: async (projectId, chapterNumber) => {
      calls.push(['chapter', projectId, chapterNumber])
      return { projectId, chapter: { number: chapterNumber } }
    },
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })
  await controller.load()

  const value = await controller.commitChapter()

  assert.equal(value.chapterNumber, 4)
  assert.equal(controller.result.value.chapterNumber, 4)
  assert.deepEqual(controller.postFinalization.value, {
    currentAction: {
      state: 'available', eyebrow: 'CHAPTER OUTLINE',
      label: '准备第 5 章小纲',
      description: '基于当前规划建立本章的写作边界。',
      targetPath: '/projects/p1/planning/story-blocks', chapterNumber: 5,
    },
    finalizedChapterPath: '/projects/p1/manuscript/chapters/4',
    finalizedChapterReadable: true,
  })
  assert.equal(calls.filter(item => item === 'committed').length, 1)
  assert.deepEqual(calls.slice(1).sort((left, right) => String(left[0]).localeCompare(String(right[0]))), [
    ['chapter', 'p1', 4],
    ['preparation', 'p1'],
  ])
})


test('follow-up reads fail independently without changing committed authority', async () => {
  for (const failure of ['preparation', 'reader']) {
    const confirmed = {
      ...review,
      confirmation: { revision: 1, contentHash: HASH_A },
    }
    const controller = createFinalizationController({
      getReview: async () => confirmed,
      commit: async () => committed(4),
      getProjectId: () => 'p1',
      getChapterNumber: () => 4,
      reloadPreparation: () => {
        if (failure === 'preparation') throw new Error('private preparation failure')
        return preparation
      },
      readFinalizedChapter: async () => {
        if (failure === 'reader') throw new Error('private reader failure')
        return { projectId: 'p1', chapter: { number: 4 } }
      },
      idFactory: () => '44444444-4444-4444-8444-444444444444',
    })
    await controller.load()

    await controller.commitChapter()

    assert.equal(controller.finalized.value, true, failure)
    assert.equal(controller.error.value, '', failure)
    assert.equal(
      controller.postFinalization.value.currentAction.state,
      failure === 'preparation' ? 'unavailable' : 'available',
      failure,
    )
    assert.equal(
      controller.postFinalization.value.finalizedChapterReadable,
      failure !== 'reader',
      failure,
    )
    assert.equal(
      controller.postFinalization.value.finalizedChapterPath,
      failure === 'reader' ? '' : '/projects/p1/manuscript/chapters/4',
      failure,
    )
  }
})


test('unknown commit recovery keeps the original chapter and runs post-commit work once', async () => {
  let getCalls = 0
  let commitCalls = 0
  let committedCalls = 0
  let chapterRead = null
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => (++getCalls === 1 ? confirmed : { ...confirmed, status: 'committed' }),
    commit: async () => {
      commitCalls += 1
      throw Object.assign(new Error('transport detail'), { status: 0 })
    },
    getProjectId: () => 'p1',
    getChapterNumber: () => 4,
    onCommitted: async () => { committedCalls += 1 },
    reloadPreparation: async () => preparation,
    readFinalizedChapter: async (projectId, chapterNumber) => {
      chapterRead = [projectId, chapterNumber]
      return { projectId, chapter: { number: chapterNumber } }
    },
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })
  await controller.load()

  const first = controller.commitChapter()
  const duplicate = await controller.commitChapter()
  const recovered = await first

  assert.equal(duplicate, false)
  assert.equal(recovered, null)
  assert.equal(commitCalls, 1)
  assert.equal(committedCalls, 1)
  assert.deepEqual(chapterRead, ['p1', 4])
  assert.equal(controller.postFinalization.value.finalizedChapterReadable, true)
})


test('reset fences late post-finalization reads from the previous chapter', { timeout: 10000 }, async () => {
  let releasePreparation
  let releaseChapter
  let markPreparationStarted
  let markChapterStarted
  const preparationStarted = new Promise(resolve => { markPreparationStarted = resolve })
  const chapterStarted = new Promise(resolve => { markChapterStarted = resolve })
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async () => committed(4),
    getProjectId: () => 'p1',
    getChapterNumber: () => 4,
    reloadPreparation: () => new Promise(resolve => { releasePreparation = resolve; markPreparationStarted() }),
    readFinalizedChapter: () => new Promise(resolve => { releaseChapter = resolve; markChapterStarted() }),
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })
  await controller.load()

  const pending = controller.commitChapter()
  await Promise.all([preparationStarted, chapterStarted])
  assert.equal(typeof releasePreparation, 'function')
  assert.equal(typeof releaseChapter, 'function')
  controller.reset()
  releasePreparation(preparation)
  releaseChapter({ projectId: 'p1', chapter: { number: 4 } })
  await pending

  assert.equal(controller.result.value, null)
  assert.equal(controller.postFinalization.value, null)
  assert.equal(controller.finalized.value, false)
})


test('commit snapshots its project and fallback chapter before the request starts', async () => {
  let currentProjectId = 'p1'
  let currentChapterNumber = 4
  let releaseCommit
  const reads = []
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: () => new Promise(resolve => { releaseCommit = resolve }),
    getProjectId: () => currentProjectId,
    getChapterNumber: () => currentChapterNumber,
    reloadPreparation: async projectId => {
      reads.push(['preparation', projectId])
      return preparation
    },
    readFinalizedChapter: async (projectId, chapterNumber) => {
      reads.push(['chapter', projectId, chapterNumber])
      return { projectId, chapter: { number: chapterNumber } }
    },
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })
  await controller.load()

  const pending = controller.commitChapter()
  while (!releaseCommit) await new Promise(resolve => setImmediate(resolve))
  currentProjectId = 'p2'
  currentChapterNumber = 9
  releaseCommit({ ...committed(), chapterNumber: undefined })
  await pending

  assert.deepEqual(reads.sort((left, right) => left[0].localeCompare(right[0])), [
    ['chapter', 'p1', 4],
    ['preparation', 'p1'],
  ])
  assert.equal(controller.result.value.chapterNumber, 4)
  assert.equal(controller.postFinalization.value.finalizedChapterPath, '/projects/p1/manuscript/chapters/4')
})


test('a repeated post-finalization refresh discards its older late response', async () => {
  let preparationCalls = 0
  let releaseOlder
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const newer = {
    lifecycle: 'active', nextAction: 'continue_contract',
    targetPath: '/projects/p1/contract', authoritativeChapterNumber: 5,
  }
  const older = {
    lifecycle: 'active', nextAction: 'continue_bible',
    targetPath: '/projects/p1/bible', authoritativeChapterNumber: 5,
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async () => committed(4),
    getProjectId: () => 'p1',
    getChapterNumber: () => 4,
    reloadPreparation: async () => {
      preparationCalls += 1
      if (preparationCalls === 1) return preparation
      if (preparationCalls === 2) return new Promise(resolve => { releaseOlder = resolve })
      return newer
    },
    readFinalizedChapter: async () => ({ projectId: 'p1', chapter: { number: 4 } }),
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })
  await controller.load()
  await controller.commitChapter()

  const first = controller.refreshPostFinalization()
  while (!releaseOlder) await new Promise(resolve => setImmediate(resolve))
  const second = controller.refreshPostFinalization()
  await second
  releaseOlder(older)
  await first

  assert.equal(controller.postFinalization.value.currentAction.label, '继续创作契约')
  assert.equal(controller.postBusy.value, false)
})


test('reader verification never publishes an unsafe finalized chapter path', async () => {
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async () => committed(4),
    getProjectId: () => 'p1',
    getChapterNumber: () => 4,
    reloadPreparation: async () => preparation,
    readFinalizedChapter: async () => ({ projectId: 'p1', chapter: { number: 4 } }),
    finalizedChapterPath: () => '/projects/p1/unsafe\\chapter\n4',
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })
  await controller.load()

  await controller.commitChapter()

  assert.equal(controller.postFinalization.value.finalizedChapterReadable, false)
  assert.equal(controller.postFinalization.value.finalizedChapterPath, '')
})


test('reset while the idempotency key is pending prevents every commit request', async () => {
  const pendingId = deferred()
  let idRequested = false
  let commitCalls = 0
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async () => { commitCalls += 1; return committed(4) },
    getProjectId: () => 'p1',
    getSessionId: () => 's1',
    getChapterNumber: () => 4,
    idFactory: () => { idRequested = true; return pendingId.promise },
  })
  await controller.load()

  const pending = controller.commitChapter()
  while (!idRequested) await new Promise(resolve => setImmediate(resolve))
  controller.reset()
  pendingId.resolve('44444444-4444-4444-8444-444444444444')

  assert.equal(await pending, null)
  assert.equal(commitCalls, 0)
  assert.equal(controller.error.value, '')
})


test('dispose while the idempotency key is pending prevents every commit request', async () => {
  const pendingId = deferred()
  let idRequested = false
  let commitCalls = 0
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async () => { commitCalls += 1; return committed(4) },
    getProjectId: () => 'p1',
    getSessionId: () => 's1',
    getChapterNumber: () => 4,
    idFactory: () => { idRequested = true; return pendingId.promise },
  })
  await controller.load()

  const pending = controller.commitChapter()
  while (!idRequested) await new Promise(resolve => setImmediate(resolve))
  controller.dispose()
  pendingId.resolve('44444444-4444-4444-8444-444444444444')

  assert.equal(await pending, null)
  assert.equal(commitCalls, 0)
})


test('commit passes one frozen project session and chapter identity after a delayed key', async () => {
  const pendingId = deferred()
  let idRequested = false
  let currentProjectId = 'p1'
  let currentSessionId = 's1'
  let currentChapterNumber = 4
  let submittedTarget = null
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async (_command, target) => {
      submittedTarget = target
      return committed(4)
    },
    getProjectId: () => currentProjectId,
    getSessionId: () => currentSessionId,
    getChapterNumber: () => currentChapterNumber,
    reloadPreparation: async () => preparation,
    readFinalizedChapter: async (projectId, chapterNumber) => ({
      projectId,
      chapter: { number: chapterNumber },
    }),
    idFactory: () => { idRequested = true; return pendingId.promise },
  })
  await controller.load()

  const pending = controller.commitChapter()
  while (!idRequested) await new Promise(resolve => setImmediate(resolve))
  currentProjectId = 'p2'
  currentSessionId = 's2'
  currentChapterNumber = 9
  pendingId.resolve('44444444-4444-4444-8444-444444444444')
  await pending

  assert.deepEqual(submittedTarget, {
    projectId: 'p1',
    sessionId: 's1',
    chapterNumber: 4,
  })
  assert.equal(controller.postFinalization.value.finalizedChapterPath, '/projects/p1/manuscript/chapters/4')
})


test('committed state is visible while onCommitted delays post-finalization reads', async () => {
  const refresh = deferred()
  let preparationCalls = 0
  let chapterCalls = 0
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async () => committed(4),
    getProjectId: () => 'p1',
    getSessionId: () => 's1',
    getChapterNumber: () => 4,
    onCommitted: () => refresh.promise,
    reloadPreparation: async () => { preparationCalls += 1; return preparation },
    readFinalizedChapter: async () => {
      chapterCalls += 1
      return { projectId: 'p1', chapter: { number: 4 } }
    },
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })
  await controller.load()

  const pending = controller.commitChapter()
  while (!controller.finalized.value) await new Promise(resolve => setImmediate(resolve))

  assert.equal(controller.postFinalization.value, null)
  assert.equal(controller.busy.value, true)
  assert.equal(preparationCalls, 0)
  assert.equal(chapterCalls, 0)
  refresh.resolve()
  await pending
  assert.equal(controller.postFinalization.value.currentAction.state, 'available')
})

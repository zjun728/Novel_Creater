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

const preparation = {
  lifecycle: 'active',
  nextAction: 'prepare_chapter_outline',
  targetPath: '/projects/p1/planning/story-blocks',
  authoritativeChapterNumber: 5,
}

function committed(chapterNumber = 4) {
  return {
    recordId: 'record-1', finalChapterId: 'chapter-1', chapterNumber,
    canonRevision: 1, projectionHash: HASH_A,
    planningRevisionId: 'planning-2', planningRevision: 2,
    planningHash: HASH_B, replayed: false,
  }
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


test('reset fences late post-finalization reads from the previous chapter', async () => {
  let releasePreparation
  let releaseChapter
  const confirmed = {
    ...review,
    confirmation: { revision: 1, contentHash: HASH_A },
  }
  const controller = createFinalizationController({
    getReview: async () => confirmed,
    commit: async () => committed(4),
    getProjectId: () => 'p1',
    getChapterNumber: () => 4,
    reloadPreparation: () => new Promise(resolve => { releasePreparation = resolve }),
    readFinalizedChapter: () => new Promise(resolve => { releaseChapter = resolve }),
    idFactory: () => '44444444-4444-4444-8444-444444444444',
  })
  await controller.load()

  const pending = controller.commitChapter()
  for (let attempt = 0; attempt < 20 && (!releasePreparation || !releaseChapter); attempt += 1) {
    await new Promise(resolve => setImmediate(resolve))
  }
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

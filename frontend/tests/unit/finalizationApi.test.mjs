import assert from 'node:assert/strict'
import test from 'node:test'


const HASH = 'a'.repeat(64)
const jsonResponse = body => ({
  ok: true,
  status: 200,
  text: async () => JSON.stringify(body),
})
const bodyOf = call => JSON.parse(call.options.body)


test('finalization client uses only the five closed session endpoints', async () => {
  const originalFetch = global.fetch
  const calls = []
  const review = {
    attemptId: 'attempt-1', status: 'awaiting_author',
    candidateId: 'candidate-1', candidateHash: HASH,
    qualityReport: {
      status: 'completed', deterministicBlocks: [], findings: [], contentHash: HASH,
      apiKey: 'MUST-NOT-CROSS',
    },
    changeSet: {
      revision: 1, contentHash: HASH, source: 'extraction',
      payload: {
        schemaVersion: 'finalization-changeset-v1', title: '第一章', summary: '摘要',
        existingEntityIds: [], entities: [], aliases: [], canonEvents: [],
        storyProgressEvents: [], planningPatches: [], planningSuggestions: [],
      },
    },
    confirmation: null,
    prompt: 'MUST-NOT-CROSS',
  }
  const responses = [
    review,
    { attemptId: 'attempt-1', status: 'awaiting_author' },
    { currentRevision: 2, currentRevisionHash: HASH },
    { confirmedRevision: 2, confirmedRevisionHash: HASH },
    {
      recordId: 'record-1', finalChapterId: 'chapter-1', canonRevision: 1,
      projectionHash: HASH, planningRevisionId: 'planning-2',
      planningRevision: 2, planningHash: HASH, replayed: false,
      rawProvider: 'MUST-NOT-CROSS',
    },
  ]
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return jsonResponse(responses.shift())
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    const base = ['project/1', 'session/1']
    const viewed = await api.chapterSessions.getFinalization(...base)
    await api.chapterSessions.prepareFinalization(...base, 'candidate/1', {
      candidateHash: HASH, expectedCanonRevision: 0,
      expectedPlanningHash: HASH, expectedOutlineHash: HASH,
      idempotencyKey: HASH,
    })
    await api.chapterSessions.correctFinalization(...base, {
      expectedRevision: 1, expectedRevisionHash: HASH,
      changeSet: review.changeSet.payload,
    })
    await api.chapterSessions.confirmFinalization(...base, {
      expectedRevision: 2, expectedRevisionHash: HASH,
    })
    const committed = await api.chapterSessions.commitFinalization(...base, {
      expectedRevision: 2, expectedRevisionHash: HASH, idempotencyKey: HASH,
    })

    assert.deepEqual(calls.map(call => [
      call.options.method, new URL(call.url).pathname,
    ]), [
      ['GET', '/api/projects/project%2F1/chapter-sessions/session%2F1/finalization'],
      ['POST', '/api/projects/project%2F1/chapter-sessions/session%2F1/candidates/candidate%2F1/finalization/prepare'],
      ['POST', '/api/projects/project%2F1/chapter-sessions/session%2F1/finalization/revisions'],
      ['POST', '/api/projects/project%2F1/chapter-sessions/session%2F1/finalization/confirm'],
      ['POST', '/api/projects/project%2F1/chapter-sessions/session%2F1/finalization/commit'],
    ])
    assert.deepEqual(bodyOf(calls[2]), {
      expectedRevision: 1, expectedRevisionHash: HASH,
      changeSet: review.changeSet.payload,
    })
    assert.equal(JSON.stringify({ viewed, committed }).includes('MUST-NOT-CROSS'), false)
    assert.equal(viewed.changeSet.payload.title, '第一章')
    assert.equal(committed.finalChapterId, 'chapter-1')
  } finally {
    global.fetch = originalFetch
  }
})


test('getFinalization maps only the closed empty projection to null', async () => {
  const originalFetch = global.fetch
  const responses = [
    { state: 'empty' },
    { state: 'empty', unexpected: true },
    {
      state: 'empty',
      attemptId: 'attempt-1',
      status: 'cancelled',
      candidateId: 'candidate-1',
      candidateHash: HASH,
      qualityReport: null,
      changeSet: null,
      confirmation: null,
    },
  ]
  global.fetch = async () => jsonResponse(responses.shift())
  try {
    const { api } = await import('../../src/api/db/client.js')
    assert.equal(
      await api.chapterSessions.getFinalization('project-1', 'session-1'),
      null,
    )
    await assert.rejects(
      api.chapterSessions.getFinalization('project-1', 'session-1'),
      TypeError,
    )
    await assert.rejects(
      api.chapterSessions.getFinalization('project-1', 'session-1'),
      TypeError,
    )
  } finally {
    global.fetch = originalFetch
  }
})

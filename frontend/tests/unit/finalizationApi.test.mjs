import assert from 'node:assert/strict'
import test from 'node:test'


const HASH = 'a'.repeat(64)
const EVIDENCE = {
  startScalar: 0,
  endScalar: 1,
  excerptHash: HASH,
  confidence: 0.8,
  rationale: '正文依据',
}
const jsonResponse = body => ({
  ok: true,
  status: 200,
  text: async () => JSON.stringify(body),
})
const bodyOf = call => JSON.parse(call.options.body)

test('progress rationale correction round-trips through the existing DTO without changing evidence pins', async () => {
  const originalFetch = global.fetch
  const original = {
    schemaVersion: 'finalization-changeset-v1', title: '隔离章节', summary: '隔离摘要',
    existingEntityIds: [], entities: [], aliases: [], canonEvents: [], planningPatches: [], planningSuggestions: [],
    storyProgressEvents: [{ id: 'progress-1', targetType: 'scene_task', targetId: 'task-1', status: 'advanced', evidence: EVIDENCE }],
  }
  const corrected = structuredClone(original)
  corrected.storyProgressEvents[0].evidence.rationale = '本次正文不足以确认实际执行；安排已明确。'
  let command
  global.fetch = async (_url, options) => {
    if (options.method === 'POST') {
      command = JSON.parse(options.body)
      return jsonResponse({ currentRevision: 2, currentRevisionHash: HASH })
    }
    return jsonResponse({
      attemptId: 'attempt-1', candidateId: 'candidate-1', candidateHash: HASH, status: 'awaiting_author',
      qualityReport: null, confirmation: null,
      changeSet: { revision: 2, contentHash: HASH, source: 'author_correction', payload: corrected },
    })
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    await api.chapterSessions.correctFinalization('fixture-project', 'fixture-session', {
      expectedRevision: 1, expectedRevisionHash: HASH, changeSet: corrected,
    })
    assert.deepEqual(command, { expectedRevision: 1, expectedRevisionHash: HASH, changeSet: corrected })
    const loaded = await api.chapterSessions.getFinalization('fixture-project', 'fixture-session')
    assert.deepEqual(loaded.changeSet.payload, corrected)
    assert.equal(loaded.changeSet.source, 'author_correction')
    assert.deepEqual(original.storyProgressEvents[0].evidence, EVIDENCE)
  } finally { global.fetch = originalFetch }
})


test('finalization client preserves the six original closed session endpoints', async () => {
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
        storyProgressEvents: [], planningPatches: [], planningSuggestions: [{
          id: 'suggestion-1', targetId: null, message: '下一章建议',
          evidence: EVIDENCE,
        }],
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
    { attemptId: 'attempt-1', status: 'cancelled' },
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
    await api.chapterSessions.cancelFinalization(...base, {
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
      ['POST', '/api/projects/project%2F1/chapter-sessions/session%2F1/finalization/cancel'],
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

test('confirmed revocation and status reads encode the exact attempt and strip extra data', async () => {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return jsonResponse({ attemptId: 'a/1', status: 'cancelled', currentRevision: 2,
      currentRevisionHash: HASH, confirmedRevision: 2, confirmedRevisionHash: HASH,
      secret: 'must-not-cross' })
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    const result = await api.chapterSessions.revokeFinalization('p/1', 's/1', 'a/1', {
      expectedRevision: 2, expectedRevisionHash: HASH, force: true,
    })
    await api.chapterSessions.getFinalizationAttemptState('p/1', 's/1', 'a/1')
    assert.deepEqual(bodyOf(calls[0]), { expectedRevision: 2, expectedRevisionHash: HASH })
    assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
      ['POST', '/api/projects/p%2F1/chapter-sessions/s%2F1/finalization/attempts/a%2F1/revoke'],
      ['GET', '/api/projects/p%2F1/chapter-sessions/s%2F1/finalization/attempts/a%2F1'],
    ])
    assert.equal(result.secret, undefined)
  } finally { global.fetch = originalFetch }
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

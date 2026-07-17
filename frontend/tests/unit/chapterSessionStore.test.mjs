import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import { api } from '../../src/api/db/client.js'
import { useChapterSessionStore } from '../../src/stores/chapterSessionStore.js'

function workspace({ content = '', revision = 1, candidates = [] } = {}) {
  return {
    projectId: 'project-1',
    session: {
      id: 'session-1', chapterNum: 1, expectedCanonRevision: 0,
      expectedStoryBlockRevision: 1, status: 'drafting',
      planningSnapshot: { storyBlockId: 'block-1' },
    },
    workingDraft: {
      id: 'draft-1', chapterSessionId: 'session-1',
      revision, content, contentHash: 'a'.repeat(64),
      sourcePayload: { source: 'manual-empty' },
    },
    candidates,
  }
}

async function withApiMethods(replacements, run) {
  const originals = []
  for (const [owner, key, replacement] of replacements) {
    originals.push([owner, key, owner[key]])
    owner[key] = replacement
  }
  try {
    return await run()
  } finally {
    for (const [owner, key, original] of originals.reverse()) owner[key] = original
  }
}

test('chapter session store edits working draft without creating candidate', async () => {
  const calls = []
  await withApiMethods([
    [api.chapterSessions, 'create', async (projectId, command) => {
      calls.push(['create', projectId, structuredClone(command)])
      return workspace()
    }],
    [api.chapterSessions, 'saveWorkingDraft', async (projectId, sessionId, command) => {
      calls.push(['draft', projectId, sessionId, structuredClone(command)])
      return workspace({ content: command.content, revision: command.expectedRevision + 1 })
    }],
    [api.chapterSessions, 'generateWorkingDraft', async (projectId, sessionId, command) => {
      calls.push(['generate', projectId, sessionId, structuredClone(command)])
      return workspace({ content: 'AI 生成正文', revision: command.expectedWorkingDraftRevision + 1 })
    }],
    [api.chapterSessions, 'saveCandidate', async (projectId, sessionId, command) => {
      calls.push(['candidate', projectId, sessionId, structuredClone(command)])
      return workspace({
        content: '正文',
        revision: command.expectedWorkingDraftRevision,
        candidates: [{ id: 'candidate-1', workingDraftRevision: command.expectedWorkingDraftRevision }],
      })
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useChapterSessionStore()
    await store.create('project-1', {
      expectedStoryBlockRevision: 1,
      expectedCanonRevision: 0,
      apiKey: 'must-not-send',
    })
    await store.saveWorkingDraft('project-1', '正文')
    assert.equal(store.candidates.length, 0)
    await store.generateWorkingDraft('project-1', '多一点市井对话')
    assert.equal(store.workingDraft.content, 'AI 生成正文')
    assert.equal(store.candidates.length, 0)
    await store.saveCandidate('project-1')
    assert.equal(store.candidates.length, 1)
    assert.deepEqual(calls, [
      ['create', 'project-1', { expectedStoryBlockRevision: 1, expectedCanonRevision: 0 }],
      ['draft', 'project-1', 'session-1', { expectedRevision: 1, content: '正文' }],
      ['generate', 'project-1', 'session-1', {
        expectedWorkingDraftRevision: 2,
        authorInstruction: '多一点市井对话',
      }],
      ['candidate', 'project-1', 'session-1', { expectedWorkingDraftRevision: 3 }],
    ])
  })
})

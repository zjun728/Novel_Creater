import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import { api } from '../../src/api/db/client.js'
import { useChapterSessionStore } from '../../src/stores/chapterSessionStore.js'

function workspace({
  chapterNumber = 1,
  content = '',
  revision = 1,
  candidates = [],
  sessionId = `session-${chapterNumber}`,
  planningRevision = 1,
  planningHash = 'a'.repeat(64),
  outlineRevision = 3,
  outlineHash = 'c'.repeat(64),
  expectedCanonRevision = 0,
} = {}) {
  return {
    projectId: 'project-1',
    session: {
      id: sessionId, chapterNum: chapterNumber, expectedCanonRevision,
      planningRevisionId: 'planning-revision-1',
      planningRevision,
      planningHash,
      storyBlockId: 'block-1',
      storyBlockRevision: 2,
      storyBlockHash: 'b'.repeat(64),
      chapterOutlineRevisionId: 'outline-revision-1',
      chapterOutlineRevision: outlineRevision,
      chapterOutlineHash: outlineHash,
      status: 'drafting',
    },
    workingDraft: {
      id: `draft-${chapterNumber}`, chapterSessionId: sessionId,
      revision, content, contentHash: 'a'.repeat(64),
      sourcePayload: { source: 'manual-empty' },
    },
    candidates,
  }
}

function currentOutline({
  projectId = 'project-1',
  chapterNumber = 1,
  targetPath = `/projects/${projectId}/write/chapters/${chapterNumber}`,
  confirmed = true,
  activeSession = null,
  startSession = true,
} = {}) {
  return {
    projectId,
    lifecycle: 'active',
    authoritativeChapterNumber: chapterNumber,
    targetPath,
    planningAuthority: {
      planningRevisionId: 'planning-revision-1',
      revision: 7,
      contentHash: 'a'.repeat(64),
      content: null,
    },
    canonProjectionAuthority: {
      canonRevision: 5,
      projectionRevision: 5,
      contentHash: 'd'.repeat(64),
      synchronized: true,
    },
    confirmedOutline: confirmed ? {
      projectId,
      chapterNumber,
      outlineRevisionId: 'outline-revision-1',
      revision: 9,
      parentRevision: 8,
      contentHash: 'c'.repeat(64),
      content: {
        schemaVersion: 'chapter-outline-draft-v1',
        volumeRef: null,
        storyBlockRef: {
          id: 'block-1',
          revision: 2,
          contentHash: 'b'.repeat(64),
        },
        stageRefs: [],
        sceneTaskRefs: [],
        chapterGoal: '守住码头，并确认谁泄露了船期。',
        expectedCharacters: ['林砚'],
        continuation: ['追查旧账'],
        plannedTasks: ['稳住船工'],
        scenes: ['雨夜码头'],
        forbiddenEarlyEvents: ['不可提前揭示内应'],
      },
      basis: {},
      status: 'current',
      reason: 'currentOutlineHead',
    } : null,
    draft: null,
    activeSession,
    capabilities: {
      view: true,
      createDraft: false,
      editDraft: false,
      generate: false,
      confirm: false,
      startSession,
    },
    reasons: [],
  }
}

function deferred() {
  let resolve
  const promise = new Promise(next => {
    resolve = next
  })
  return { promise, resolve }
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
    [api.chapterSessions, 'create', async (projectId, chapterNumber, command) => {
      calls.push(['create', projectId, chapterNumber, structuredClone(command)])
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
    await store.create('project-1', 1, {
      chapterNumber: 1,
      expectedPlanningRevision: 1,
      expectedPlanningHash: 'a'.repeat(64),
      expectedOutlineRevision: 3,
      expectedOutlineHash: 'c'.repeat(64),
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
      ['create', 'project-1', 1, {
        chapterNumber: 1,
        expectedPlanningRevision: 1,
        expectedPlanningHash: 'a'.repeat(64),
        expectedOutlineRevision: 3,
        expectedOutlineHash: 'c'.repeat(64),
        expectedCanonRevision: 0,
      }],
      ['draft', 'project-1', 'session-1', { expectedRevision: 1, content: '正文' }],
      ['generate', 'project-1', 'session-1', {
        expectedWorkingDraftRevision: 2,
        authorInstruction: '多一点市井对话',
      }],
      ['candidate', 'project-1', 'session-1', { expectedWorkingDraftRevision: 3 }],
    ])
  })
})

test('authoritative writer entry reads current then creates from exact returned pins', async () => {
  const calls = []
  const current = currentOutline()
  await withApiMethods([
    [api.chapterOutlines, 'current', async projectId => {
      calls.push(['current', projectId])
      return current
    }],
    [api.chapterSessions, 'create', async (projectId, chapterNumber, command) => {
      calls.push(['create', projectId, chapterNumber, structuredClone(command)])
      return workspace({
        chapterNumber,
        planningRevision: 7,
        outlineRevision: 9,
        expectedCanonRevision: 5,
      })
    }],
    [api.chapterSessions, 'get', async () => {
      assert.fail('new authoritative entry must not GET an absent Session')
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useChapterSessionStore()

    const authority = await store.openAuthoritative('project-1', 1)

    assert.equal(authority, current)
    assert.equal(store.session.id, 'session-1')
    assert.deepEqual(calls, [
      ['current', 'project-1'],
      ['create', 'project-1', 1, {
        chapterNumber: 1,
        expectedPlanningRevision: 7,
        expectedPlanningHash: 'a'.repeat(64),
        expectedOutlineRevision: 9,
        expectedOutlineHash: 'c'.repeat(64),
        expectedCanonRevision: 5,
      }],
    ])
    assert.doesNotMatch(JSON.stringify(calls), /apiKey|secret|provider/i)
  })
})

test('wrong writer route returns current authority without Session request or redirect', async () => {
  const current = currentOutline({
    chapterNumber: 8,
    targetPath: '/projects/project-1/write/chapters/8',
  })
  let sessionRequests = 0
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => current],
    [api.chapterSessions, 'create', async () => {
      sessionRequests += 1
    }],
    [api.chapterSessions, 'get', async () => {
      sessionRequests += 1
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useChapterSessionStore()

    assert.equal(await store.openAuthoritative('project-1', 7), current)
    assert.equal(sessionRequests, 0)
    assert.equal(store.hasSession, false)
  })
})

test('active authoritative Session is replayed with GET and never POSTed', async () => {
  const calls = []
  const current = currentOutline({
    activeSession: {
      chapterSessionId: 'session-1',
      chapterNumber: 1,
      status: 'drafting',
      planningRevisionId: 'planning-revision-1',
      planningRevision: 7,
      planningHash: 'a'.repeat(64),
      outlineRevisionId: 'outline-revision-1',
      outlineRevision: 9,
      outlineHash: 'c'.repeat(64),
    },
    startSession: false,
  })
  await withApiMethods([
    [api.chapterOutlines, 'current', async projectId => {
      calls.push(['current', projectId])
      return current
    }],
    [api.chapterSessions, 'get', async (projectId, chapterNumber) => {
      calls.push(['get', projectId, chapterNumber])
      return workspace({
        chapterNumber,
        planningRevision: 7,
        outlineRevision: 9,
        expectedCanonRevision: 5,
      })
    }],
    [api.chapterSessions, 'create', async () => {
      assert.fail('active Session replay must not POST')
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useChapterSessionStore()

    assert.equal(await store.openAuthoritative('project-1', 1), current)
    assert.equal(store.session.id, 'session-1')
    assert.deepEqual(calls, [
      ['current', 'project-1'],
      ['get', 'project-1', 1],
    ])
  })
})

test('active Session replay fails closed when the loaded workspace pins drift', async () => {
  const current = currentOutline({
    activeSession: {
      chapterSessionId: 'session-1',
      chapterNumber: 1,
      status: 'drafting',
      planningRevisionId: 'planning-revision-1',
      planningRevision: 7,
      planningHash: 'a'.repeat(64),
      outlineRevisionId: 'outline-revision-1',
      outlineRevision: 9,
      outlineHash: 'c'.repeat(64),
    },
    startSession: false,
  })
  await withApiMethods([
    [api.chapterOutlines, 'current', async () => current],
    [api.chapterSessions, 'get', async () => workspace({
      planningRevision: 6,
      outlineRevision: 9,
      expectedCanonRevision: 5,
    })],
    [api.chapterSessions, 'create', async () => {
      assert.fail('active Session drift must not fall back to POST')
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useChapterSessionStore()

    await assert.rejects(
      store.openAuthoritative('project-1', 1),
      /authority.*changed|authority.*mismatch/i,
    )
    assert.equal(store.hasSession, false)
    assert.doesNotMatch(JSON.stringify(store.error), /planning-revision|outline-revision/)
  })
})

test('missing or non-startable current Outline never creates a Session', async () => {
  for (const current of [
    currentOutline({ confirmed: false, startSession: false }),
    currentOutline({ startSession: false }),
    {
      ...currentOutline(),
      confirmedOutline: {
        ...currentOutline().confirmedOutline,
        status: 'superseded',
      },
    },
  ]) {
    let sessionRequests = 0
    await withApiMethods([
      [api.chapterOutlines, 'current', async () => current],
      [api.chapterSessions, 'create', async () => {
        sessionRequests += 1
      }],
      [api.chapterSessions, 'get', async () => {
        sessionRequests += 1
      }],
    ], async () => {
      setActivePinia(createPinia())
      const store = useChapterSessionStore()
      assert.equal(await store.openAuthoritative('project-1', 1), current)
      assert.equal(sessionRequests, 0)
      assert.equal(store.hasSession, false)
    })
  }
})

test('late current response is fenced before it can write state or trigger Session POST', async () => {
  const first = deferred()
  const calls = []
  await withApiMethods([
    [api.chapterOutlines, 'current', async projectId => {
      calls.push(['current', projectId])
      return projectId === 'project-1'
        ? first.promise
        : currentOutline({ projectId: 'project-2', chapterNumber: 2 })
    }],
    [api.chapterSessions, 'create', async (projectId, chapterNumber) => {
      calls.push(['create', projectId, chapterNumber])
      return workspace({
        chapterNumber,
        planningRevision: 7,
        outlineRevision: 9,
        expectedCanonRevision: 5,
      })
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useChapterSessionStore()
    const stale = store.openAuthoritative('project-1', 1)
    const current = store.openAuthoritative('project-2', 2)
    await current
    first.resolve(currentOutline({ projectId: 'project-1', chapterNumber: 1 }))
    assert.equal(await stale, null)

    assert.deepEqual(calls, [
      ['current', 'project-1'],
      ['current', 'project-2'],
      ['create', 'project-2', 2],
    ])
    assert.equal(store.projectId, 'project-2')
    assert.equal(store.chapterNumber, 2)
    assert.equal(store.session.chapterNum, 2)
  })
})

test('chapter session store isolates late reads when switching chapters in one project', async () => {
  const first = deferred()
  const second = deferred()
  const calls = []

  await withApiMethods([
    [api.chapterSessions, 'get', async (projectId, chapterNumber) => {
      calls.push([projectId, chapterNumber])
      return chapterNumber === 1 ? first.promise : second.promise
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = useChapterSessionStore()

    const chapterOneLoad = store.load('project-1', 1)
    const chapterTwoLoad = store.load('project-1', 2)
    second.resolve(workspace({ chapterNumber: 2, content: '第二章' }))
    await chapterTwoLoad
    first.resolve(workspace({ chapterNumber: 1, content: '第一章' }))
    await chapterOneLoad

    assert.deepEqual(calls, [
      ['project-1', 1],
      ['project-1', 2],
    ])
    assert.equal(store.projectId, 'project-1')
    assert.equal(store.chapterNumber, 2)
    assert.equal(store.session.chapterNum, 2)
    assert.equal(store.workingDraft.content, '第二章')
  })
})

test('invalidate clears every pending flag and late completions cannot revive them', async () => {
  const scenarios = [
    {
      name: 'load',
      flag: 'loading',
      start: store => store.load('project-1', 1),
      seed: false,
    },
    {
      name: 'create',
      flag: 'creating',
      start: store => store.create('project-1', 1, {
        chapterNumber: 1,
        expectedPlanningRevision: 1,
        expectedPlanningHash: 'a'.repeat(64),
        expectedOutlineRevision: 3,
        expectedOutlineHash: 'c'.repeat(64),
        expectedCanonRevision: 0,
      }),
      seed: false,
    },
    {
      name: 'saveWorkingDraft',
      flag: 'savingDraft',
      start: store => store.saveWorkingDraft('project-1', '正文'),
      seed: true,
    },
    {
      name: 'generateWorkingDraft',
      flag: 'generatingDraft',
      start: store => store.generateWorkingDraft('project-1', '更有烟火气'),
      seed: true,
    },
    {
      name: 'saveCandidate',
      flag: 'savingCandidate',
      start: store => store.saveCandidate('project-1'),
      seed: true,
    },
  ]

  for (const scenario of scenarios) {
    const gate = deferred()
    await withApiMethods([
      [api.chapterSessions, 'get', async () => (
        scenario.name === 'load' ? gate.promise : workspace()
      )],
      [api.chapterSessions, 'create', async () => (
        scenario.name === 'create' ? gate.promise : workspace()
      )],
      [api.chapterSessions, 'saveWorkingDraft', async () => (
        scenario.name === 'saveWorkingDraft' ? gate.promise : workspace()
      )],
      [api.chapterSessions, 'generateWorkingDraft', async () => (
        scenario.name === 'generateWorkingDraft' ? gate.promise : workspace()
      )],
      [api.chapterSessions, 'saveCandidate', async () => (
        scenario.name === 'saveCandidate' ? gate.promise : workspace()
      )],
    ], async () => {
      setActivePinia(createPinia())
      const store = useChapterSessionStore()
      if (scenario.seed) await store.load('project-1', 1)

      const pending = scenario.start(store)
      assert.equal(store[scenario.flag], true, `${scenario.name} did not enter pending state`)
      store.invalidate()
      for (const flag of [
        'loading',
        'creating',
        'savingDraft',
        'savingCandidate',
        'generatingDraft',
      ]) {
        assert.equal(store[flag], false, `${scenario.name} left ${flag} active`)
      }

      gate.resolve(workspace({ content: `${scenario.name} response`, revision: 2 }))
      await pending
      for (const flag of [
        'loading',
        'creating',
        'savingDraft',
        'savingCandidate',
        'generatingDraft',
      ]) {
        assert.equal(store[flag], false, `${scenario.name} completion revived ${flag}`)
      }
    })
  }
})

test('same chapter write operations are mutually exclusive before any second API call', async () => {
  const scenarios = [
    ['create', 'saveWorkingDraft'],
    ['saveWorkingDraft', 'generateWorkingDraft'],
    ['generateWorkingDraft', 'saveCandidate'],
    ['saveCandidate', 'create'],
  ]

  for (const [activeName, blockedName] of scenarios) {
    const gate = deferred()
    const calls = {
      create: 0,
      saveWorkingDraft: 0,
      generateWorkingDraft: 0,
      saveCandidate: 0,
    }
    await withApiMethods([
      [api.chapterSessions, 'get', async () => workspace()],
      [api.chapterSessions, 'create', async () => {
        calls.create += 1
        return activeName === 'create' ? gate.promise : workspace()
      }],
      [api.chapterSessions, 'saveWorkingDraft', async () => {
        calls.saveWorkingDraft += 1
        return activeName === 'saveWorkingDraft' ? gate.promise : workspace({ revision: 2 })
      }],
      [api.chapterSessions, 'generateWorkingDraft', async () => {
        calls.generateWorkingDraft += 1
        return activeName === 'generateWorkingDraft' ? gate.promise : workspace({
          content: 'AI 生成正文',
          revision: 2,
        })
      }],
      [api.chapterSessions, 'saveCandidate', async () => {
        calls.saveCandidate += 1
        return activeName === 'saveCandidate' ? gate.promise : workspace({
          candidates: [{ id: 'candidate-1', workingDraftRevision: 1 }],
        })
      }],
    ], async () => {
      setActivePinia(createPinia())
      const store = useChapterSessionStore()
      await store.load('project-1', 1)
      const invoke = {
        create: () => store.create('project-1', 1, {
          chapterNumber: 1,
          expectedPlanningRevision: 1,
          expectedPlanningHash: 'a'.repeat(64),
          expectedOutlineRevision: 3,
          expectedOutlineHash: 'c'.repeat(64),
          expectedCanonRevision: 0,
        }),
        saveWorkingDraft: () => store.saveWorkingDraft('project-1', '正文'),
        generateWorkingDraft: () => store.generateWorkingDraft('project-1', ''),
        saveCandidate: () => store.saveCandidate('project-1'),
      }

      const pending = invoke[activeName]()
      assert.equal(store.busy, true)
      await assert.rejects(
        invoke[blockedName](),
        /write is already in progress/,
      )
      assert.equal(calls[blockedName], 0)

      gate.resolve(workspace({
        content: activeName === 'generateWorkingDraft' ? 'AI 生成正文' : '正文',
        revision: 2,
        candidates: activeName === 'saveCandidate'
          ? [{ id: 'candidate-1', workingDraftRevision: 1 }]
          : [],
      }))
      await pending
      assert.equal(store.busy, false)
      assert.equal(store.workingDraft.revision, 2)
    })
  }
})

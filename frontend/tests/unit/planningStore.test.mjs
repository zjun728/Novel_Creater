import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import { api } from '../../src/api/db/client.js'
import { usePlanningStore } from '../../src/stores/planningStore.js'

function state(projectId, ready = false) {
  return {
    projectId,
    hasPlanning: ready,
    planningReady: ready,
    contractRevision: 1,
    activeVolume: ready ? { id: 'volume-1', title: '第一卷 山河初启' } : null,
    activeBlock: ready ? {
      id: 'block-1',
      title: '典籍入山河',
      goal: { chapterCapacity: { targetMin: 3500, targetMax: 4500, softCeiling: 5200 } },
      status: 'active',
    } : null,
    stages: ready ? [{ id: 'stage-1', status: 'in_progress' }] : [],
    sceneTasks: ready ? [{ id: 'task-1', status: 'pending' }] : [],
    manifestHash: ready ? 'a'.repeat(64) : null,
  }
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

test('planning store loads state and creates initial plan explicitly', async () => {
  const calls = []
  await withApiMethods([
    [api.planning, 'get', async projectId => {
      calls.push(['get', projectId])
      return state(projectId, false)
    }],
    [api.planning, 'createInitial', async (projectId, command) => {
      calls.push(['create', projectId, structuredClone(command)])
      return state(projectId, true)
    }],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    await store.load('project-1')
    assert.equal(store.hasPlanning, false)
    assert.equal(store.planningReady, false)

    await store.createInitial('project-1', {
      expectedContractRevision: 1,
      idempotencyKey: 'planning-1',
      apiKey: 'must-not-send',
    })

    assert.equal(store.hasPlanning, true)
    assert.equal(store.planningReady, true)
    assert.equal(store.activeBlock.title, '典籍入山河')
    assert.deepEqual(calls, [
      ['get', 'project-1'],
      ['create', 'project-1', {
        expectedContractRevision: 1,
        idempotencyKey: 'planning-1',
      }],
    ])
  })
})

test('planning store ignores late responses from an older project', async () => {
  const first = deferred()
  await withApiMethods([
    [api.planning, 'get', async projectId => (
      projectId === 'project-1' ? first.promise : state(projectId, true)
    )],
  ], async () => {
    setActivePinia(createPinia())
    const store = usePlanningStore()
    const oldLoad = store.load('project-1')
    await store.load('project-2')
    first.resolve(state('project-1', true))
    await oldLoad

    assert.equal(store.projectId, 'project-2')
    assert.equal(store.state.projectId, 'project-2')
    assert.equal(store.hasPlanning, true)
  })
})

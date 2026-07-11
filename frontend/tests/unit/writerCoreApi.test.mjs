import assert from 'node:assert/strict'
import test from 'node:test'

test('writer core state performs one read through the product API', async () => {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify({
      projectId: 'project-1',
      schemaVersion: 'writer-core-v1.0.0',
      canonHeadRevision: 0,
      projectionHeadRevision: 0,
      projectionInSync: true,
    }), { status: 200, headers: { 'content-type': 'application/json' } })
  }

  try {
    const { api } = await import('../../src/api/db/client.js')
    const state = await api.writerCore.state('project-1')

    assert.equal(state.schemaVersion, 'writer-core-v1.0.0')
    assert.equal(calls.length, 1)
    assert.match(calls[0].url, /\/api\/projects\/project-1\/writer-core\/state$/)
    assert.equal(calls[0].options.method, 'GET')
    assert.equal('body' in calls[0].options, false)
  } finally {
    global.fetch = originalFetch
  }
})

test('project update sends only mutable public fields', async () => {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify({ id: 'project-1' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }

  try {
    const { api } = await import('../../src/api/db/client.js')
    await api.projects.update('project-1', {
      title: 'Changed',
      genre: 'history',
      description: 'Description',
      targetWords: 1000,
      targetChapters: 10,
      currentChapter: 4,
      status: 'drafting',
      unexpected: 'discard me',
    })

    assert.equal(calls.length, 1)
    assert.equal(calls[0].options.method, 'PUT')
    assert.deepEqual(JSON.parse(calls[0].options.body), {
      title: 'Changed',
      genre: 'history',
      description: 'Description',
      targetWords: 1000,
      targetChapters: 10,
    })
  } finally {
    global.fetch = originalFetch
  }
})

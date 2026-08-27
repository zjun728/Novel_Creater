import assert from 'node:assert/strict'
import test from 'node:test'
import { api } from '../../src/api/db/client.js'

const directory = { projectId: 'p 1', title: 'T', lifecycle: 'active', summary: { finalChapterCount: 1, totalScalarCount: 2 }, volumes: [{ id: 'v1', order: 1, title: 'V', chapters: [{ number: 2, title: 'C', scalarCount: 2, finalizedAt: '2025-01-01T00:00:00Z' }] }] }
const chapter = { projectId: 'p 1', projectTitle: 'T', lifecycle: 'active', volume: { id: 'v1', order: 1, title: 'V' }, chapter: { number: 2, title: 'C', content: 'a😀', scalarCount: 2, finalizedAt: '2025-01-01T00:00:00Z' }, outline: { chapterGoal: '', expectedCharacters: [], continuation: [], plannedTasks: [], scenes: [], forbiddenEarlyEvents: [] }, navigation: { previousChapterNumber: null, nextChapterNumber: 8 } }

test('manuscript API uses exact encoded GET URLs and freezes validated results', async () => {
  const prior = global.fetch; const calls = []
  global.fetch = async (url, options) => { calls.push([String(url), options]); return new Response(JSON.stringify(calls.length === 1 ? directory : chapter)) }
  try {
    const index = await api.manuscripts.index('p 1')
    const item = await api.manuscripts.chapter('p 1', 2)
    assert.match(calls[0][0], /\/projects\/p%201\/manuscript$/); assert.equal(calls[0][1].method, 'GET')
    assert.match(calls[1][0], /\/chapters\/2$/); assert.equal(Object.isFrozen(index.volumes[0].chapters), true); assert.equal(Object.isFrozen(item.chapter), true)
  } finally { global.fetch = prior }
})

test('manuscript API rejects unknown contracts without leaking raw values', async () => {
  const prior = global.fetch
  global.fetch = async () => new Response(JSON.stringify({ ...directory, hash: 'secret' }))
  try { await assert.rejects(api.manuscripts.index('p'), error => error.code === 'invalid_response' && !error.message.includes('secret')) } finally { global.fetch = prior }
})

test('manuscript API forwards caller abort as request_aborted', async () => {
  const prior = global.fetch; let seen
  global.fetch = async (_url, options) => { seen = options.signal; return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(Object.assign(new Error(), { name: 'AbortError' })))) }
  const controller = new AbortController(); const request = api.manuscripts.index('p', { signal: controller.signal }); controller.abort()
  try { await assert.rejects(request, error => error.code === 'request_aborted'); assert.ok(seen.aborted) } finally { global.fetch = prior }
})

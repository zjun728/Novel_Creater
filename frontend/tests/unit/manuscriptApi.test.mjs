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

test('directory rejects unsafe IDs and accepts a backend-valid backslash ID', async () => {
  const prior = global.fetch
  for (const id of [' v1', 'v1\u200B']) {
    global.fetch = async () => new Response(JSON.stringify({ ...directory, volumes: [{ ...directory.volumes[0], id }] }))
    await assert.rejects(api.manuscripts.index('p'), error => error.code === 'invalid_response')
  }
  global.fetch = async () => new Response(JSON.stringify({ ...directory, volumes: [{ ...directory.volumes[0], id: 'v\\1' }] }))
  try { assert.equal((await api.manuscripts.index('p')).volumes[0].id, 'v\\1') } finally { global.fetch = prior }
})

test('directory accepts the empty-book shape and returned graph is source-isolated', async () => {
  const prior = global.fetch; const source = { ...directory, summary: { finalChapterCount: 0, totalScalarCount: 0 }, volumes: [] }
  global.fetch = async () => new Response(JSON.stringify(source))
  try { const value = await api.manuscripts.index('p'); source.title = 'changed'; assert.equal(value.title, 'T'); assert.equal(Object.isFrozen(value), true); assert.equal(Object.isFrozen(value.volumes), true) } finally { global.fetch = prior }
})

async function rejectsMutation(name, value, call = () => api.manuscripts.index('p')) {
  const prior = global.fetch
  global.fetch = async () => new Response(JSON.stringify(value))
  try { await assert.rejects(call(), error => error.code === 'invalid_response' && error.message === '服务返回了无效响应' && !error.message.includes('secret'), name) } finally { global.fetch = prior }
}

test('directoryMutations reject exact keys, primitives, ordering, timestamps and arithmetic', async () => {
  const cases = [
    ['summary hash', x => { x.summary.hash = 'secret' }], ['volume revision', x => { x.volumes[0].revision = 1 }],
    ['chapter-meta basis', x => { x.volumes[0].chapters[0].basis = 'secret' }], ['root internalId', x => { x.internalId = 'secret' }],
    ['summary primitive', x => { x.summary = null }], ['volume primitive', x => { x.volumes[0] = null }], ['chapters primitive', x => { x.volumes[0].chapters = {} }],
    ['meta number string', x => { x.volumes[0].chapters[0].number = '2' }], ['meta title null', x => { x.volumes[0].chapters[0].title = null }],
    ['duplicate chapter', x => { x.volumes.push({ id: 'v2', order: 2, title: 'V2', chapters: [structuredClone(x.volumes[0].chapters[0])] }) }],
    ['same-volume unsorted', x => { x.volumes[0].chapters.push({ ...structuredClone(x.volumes[0].chapters[0]), number: 1 }) }],
    ['cross-volume rollback', x => { x.volumes.push({ id: 'v2', order: 2, title: 'V2', chapters: [{ ...structuredClone(x.volumes[0].chapters[0]), number: 1 }] }) }],
    ['duplicate volume ID', x => { x.volumes.push({ id: 'v1', order: 2, title: 'V2', chapters: [{ ...structuredClone(x.volumes[0].chapters[0]), number: 3 }] }) }],
    ['unsorted volume order', x => { x.volumes.push({ id: 'v2', order: 1, title: 'V2', chapters: [{ ...structuredClone(x.volumes[0].chapters[0]), number: 3 }] }) }],
    ['invalid calendar', x => { x.volumes[0].chapters[0].finalizedAt = '2025-02-31T00:00:00Z' }], ['timestamp offset', x => { x.volumes[0].chapters[0].finalizedAt = '2025-01-01T00:00:00+00:00' }], ['timestamp no Z', x => { x.volumes[0].chapters[0].finalizedAt = '2025-01-01T00:00:00' }],
    ['unsafe order', x => { x.volumes[0].order = Number.MAX_SAFE_INTEGER + 1 }], ['unsafe chapter', x => { x.volumes[0].chapters[0].number = Number.MAX_SAFE_INTEGER + 1 }], ['unsafe count', x => { x.summary.totalScalarCount = Number.MAX_SAFE_INTEGER + 1 }], ['summary mismatch', x => { x.summary.finalChapterCount = 9 }], ['total mismatch', x => { x.summary.totalScalarCount = 9 }],
  ]
  for (const [name, mutate] of cases) { const value = structuredClone(directory); mutate(value); await rejectsMutation(name, value) }
})

test('chapterMutations reject every nested boundary and navigation contract', async () => {
  const cases = [
    ['root hash', x => { x.hash = 'secret' }], ['volume contentHash', x => { x.volume.contentHash = 'secret' }], ['chapter revision', x => { x.chapter.revision = 1 }], ['outline basis', x => { x.outline.basis = 'secret' }], ['navigation internalId', x => { x.navigation.internalId = 'secret' }],
    ['root primitive', x => { x.projectTitle = [] }], ['volume primitive', x => { x.volume = [] }], ['chapter primitive', x => { x.chapter = null }], ['outline primitive', x => { x.outline = [] }], ['navigation primitive', x => { x.navigation = null }],
    ['chapterGoal wrong', x => { x.outline.chapterGoal = [] }], ...['expectedCharacters', 'continuation', 'plannedTasks', 'scenes', 'forbiddenEarlyEvents'].map(key => [`${key} wrong`, x => { x.outline[key] = [null] }]),
    ['emoji scalar mismatch', x => { x.chapter.content = '😀'; x.chapter.scalarCount = 2 }], ['chapter count unsafe', x => { x.chapter.scalarCount = Number.MAX_SAFE_INTEGER + 1 }],
    ['previous equals current', x => { x.navigation.previousChapterNumber = x.chapter.number }], ['next equals current', x => { x.navigation.nextChapterNumber = x.chapter.number }], ['navigation primitive', x => { x.navigation.nextChapterNumber = '8' }],
  ]
  for (const [name, mutate] of cases) { const value = structuredClone(chapter); mutate(value); await rejectsMutation(name, value, () => api.manuscripts.chapter('p', 2)) }
})

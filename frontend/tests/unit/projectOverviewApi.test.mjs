import assert from 'node:assert/strict'
import test from 'node:test'

import { api } from '../../src/api/db/client.js'
import { parseProjectOverview } from '../../src/application/projects/projectOverview.js'

export function projectOverview(overrides = {}) {
  const value = {
    project: {
      id: 'project / 一',
      title: '典镇山河',
      genre: '东方玄幻',
      logline: '以山河典册镇压乱世妖祟。',
      targetWords: 2_400_000,
      targetChapters: 800,
      updatedAtMs: 1_777_777_777_000,
      lifecycle: 'active',
    },
    progress: {
      authoritativeChapterNumber: 4,
      currentVolume: { id: 'volume-1', order: 1, title: '山河初醒' },
      latestFinalChapter: { number: 3, title: '城隍夜巡', finalizedAtMs: 1_777_777_770_000 },
      finalizedChapterCount: 3,
      finalizedScalarCount: 18_600,
    },
    modules: {
      seed: 'current',
      contract: 'current',
      bible: 'current',
      planning: 'current',
      outline: 'pending_confirmation',
      writing: 'working_draft',
    },
    writerCore: { canonRevision: 3, projectionRevision: 3, synchronized: true },
    continuity: { availability: 'pending_module', pendingCount: null },
    recentAchievements: [
      { kind: 'final_chapter', label: '第 3 章已定稿', occurredAtMs: 1_777_777_770_000 },
      { kind: 'planning', label: '故事规划已确认', occurredAtMs: 1_777_777_760_000 },
    ],
  }
  return Object.assign(value, overrides)
}

function walkFrozen(value) {
  if (!value || typeof value !== 'object') return
  assert.equal(Object.isFrozen(value), true)
  Object.values(value).forEach(walkFrozen)
}

test('parseProjectOverview accepts the exact response and returns a source-isolated frozen graph', () => {
  const source = projectOverview()
  const result = parseProjectOverview(source)

  assert.equal(result.project.title, '典镇山河')
  assert.equal(result.writerCore.synchronized, true)
  source.project.title = '已篡改'
  source.recentAchievements[0].label = '已篡改'
  assert.equal(result.project.title, '典镇山河')
  assert.equal(result.recentAchievements[0].label, '第 3 章已定稿')
  walkFrozen(result)
})

test('parseProjectOverview rejects unknown keys at every response boundary', () => {
  const cases = [
    value => { value.nextAction = 'continue_writing' },
    value => { value.project.contentHash = 'secret' },
    value => { value.progress.rawJson = '{}' },
    value => { value.progress.currentVolume.revision = 1 },
    value => { value.progress.latestFinalChapter.internalId = 'secret' },
    value => { value.modules.targetPath = '/write' },
    value => { value.writerCore.canonHash = 'secret' },
    value => { value.continuity.items = [] },
    value => { value.recentAchievements[0].entityId = 'secret' },
  ]
  for (const mutate of cases) {
    const payload = projectOverview()
    mutate(payload)
    assert.throws(() => parseProjectOverview(payload), /Invalid project overview response/)
  }
})

test('parseProjectOverview rejects unknown statuses and invalid integer ranges', () => {
  const cases = [
    value => { value.project.lifecycle = 'deleted' },
    value => { value.modules.seed = 'draft' },
    value => { value.continuity.availability = 'guessed' },
    value => { value.recentAchievements[0].kind = 'outline' },
    value => { value.project.targetWords = 0 },
    value => { value.project.targetChapters = Number.MAX_SAFE_INTEGER + 1 },
    value => { value.project.updatedAtMs = -1 },
    value => { value.progress.authoritativeChapterNumber = 0 },
    value => { value.progress.finalizedChapterCount = 1.5 },
    value => { value.progress.finalizedScalarCount = -1 },
    value => { value.progress.currentVolume.order = 0 },
    value => { value.progress.latestFinalChapter.finalizedAtMs = -1 },
    value => { value.writerCore.canonRevision = -1 },
    value => { value.recentAchievements[0].occurredAtMs = 1.5 },
  ]
  for (const mutate of cases) {
    const payload = projectOverview()
    mutate(payload)
    assert.throws(() => parseProjectOverview(payload), /Invalid project overview response/)
  }
})

test('parseProjectOverview rejects contradictory progress, writer-core and continuity shapes', () => {
  const cases = [
    value => { value.progress.finalizedChapterCount = 3; value.progress.latestFinalChapter = null },
    value => { value.progress.finalizedChapterCount = 0; value.progress.finalizedScalarCount = 9; value.progress.latestFinalChapter = null },
    value => { value.progress.authoritativeChapterNumber = 3 },
    value => { value.progress.finalizedChapterCount = 4 },
    value => { value.writerCore.projectionRevision = 2 },
    value => { value.writerCore.synchronized = false },
    value => { value.continuity.pendingCount = 4 },
    value => { value.continuity = { availability: 'available', pendingCount: null } },
    value => { value.recentAchievements.push(...Array.from({ length: 4 }, (_, index) => ({ kind: 'seed', label: `种子 ${index}`, occurredAtMs: index }))) },
  ]
  for (const mutate of cases) {
    const payload = projectOverview()
    mutate(payload)
    assert.throws(() => parseProjectOverview(payload), /Invalid project overview response/)
  }
})

test('projects.overview uses the encoded abortable GET path and parses the response', async () => {
  const prior = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push([String(url), options])
    return new Response(JSON.stringify(projectOverview()))
  }
  try {
    const controller = new AbortController()
    const result = await api.projects.overview('project / 一', { signal: controller.signal })
    assert.equal(result.project.title, '典镇山河')
    assert.equal(calls[0][0], 'http://127.0.0.1:8000/api/projects/project%20%2F%20%E4%B8%80/overview')
    assert.equal(calls[0][1].method, 'GET')
    assert.equal(calls[0][1].signal.aborted, false)
  } finally {
    global.fetch = prior
  }
})

test('projects.overview classifies invalid responses without leaking rejected values', async () => {
  const prior = global.fetch
  global.fetch = async () => new Response(JSON.stringify({ ...projectOverview(), contentHash: 'secret-value' }))
  try {
    await assert.rejects(
      api.projects.overview('project-1'),
      error => error.code === 'invalid_response'
        && error.message === '服务返回了无效响应'
        && !error.message.includes('secret-value'),
    )
  } finally {
    global.fetch = prior
  }
})

test('projects.overview forwards caller abort as request_aborted', async () => {
  const prior = global.fetch
  global.fetch = async (_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(Object.assign(new Error(), { name: 'AbortError' })))
  })
  const controller = new AbortController()
  const pending = api.projects.overview('project-1', { signal: controller.signal })
  controller.abort()
  try {
    await assert.rejects(pending, error => error.code === 'request_aborted')
  } finally {
    global.fetch = prior
  }
})

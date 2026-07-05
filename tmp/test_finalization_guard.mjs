import assert from 'node:assert/strict'
import {
  beginChapterFinalizationRun,
  clearChapterFinalizationPending,
  endChapterFinalizationRun,
  getChapterFinalizationPending,
  markChapterFinalizationPending
} from '../frontend/src/utils/finalizationGuard.js'

function createStorage() {
  const values = new Map()
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null
    },
    setItem(key, value) {
      values.set(key, String(value))
    },
    removeItem(key) {
      values.delete(key)
    },
    has(key) {
      return values.has(key)
    }
  }
}

const projectId = 'project-1'

{
  const storage = createStorage()
  markChapterFinalizationPending(projectId, 3, { storage, now: 1000 })
  const marker = getChapterFinalizationPending(projectId, 3, { storage, now: 1500 })
  assert.equal(marker.projectId, projectId)
  assert.equal(marker.chapterNum, 3)
  assert.equal(marker.startedAt, 1000)
}

{
  const storage = createStorage()
  markChapterFinalizationPending(projectId, 4, { storage, now: 1000 })
  clearChapterFinalizationPending(projectId, 4, { storage })
  assert.equal(getChapterFinalizationPending(projectId, 4, { storage, now: 1500 }), null)
}

{
  const storage = createStorage()
  markChapterFinalizationPending(projectId, 5, { storage, now: 1000, ttlMs: 100 })
  assert.equal(getChapterFinalizationPending(projectId, 5, { storage, now: 1200, ttlMs: 100 }), null)
}

{
  const storage = createStorage()
  markChapterFinalizationPending(projectId, 9, {
    storage,
    now: 1000,
    commitStatus: 'failed_after_chapter_commit',
    sourceVersionId: 'version-postprocess-failed',
    finalizationId: 'fin-9'
  })
  const marker = getChapterFinalizationPending(projectId, 9, {
    storage,
    now: 1000 + 365 * 24 * 60 * 60 * 1000
  })
  assert.equal(marker?.chapterNum, 9)
  assert.equal(marker?.commitStatus, 'failed_after_chapter_commit')
  assert.equal(marker?.sourceVersionId, 'version-postprocess-failed')
}

{
  const storage = createStorage()
  const first = beginChapterFinalizationRun(projectId, 6, 'version-a', { storage, now: 1000 })
  const second = beginChapterFinalizationRun(projectId, 6, 'version-a', { storage, now: 1001 })

  assert.equal(first.started, true)
  assert.equal(second.started, false)
  assert.equal(second.reason, 'already_running')
  assert.equal(getChapterFinalizationPending(projectId, 6, { storage, now: 1002 })?.chapterNum, 6)

  endChapterFinalizationRun(first.runKey, projectId, 6, { storage })
  const third = beginChapterFinalizationRun(projectId, 6, 'version-a', { storage, now: 1003 })
  assert.equal(third.started, true)
  endChapterFinalizationRun(third.runKey, projectId, 6, { storage })
}

{
  const storage = createStorage()
  markChapterFinalizationPending(projectId, 7, { storage, now: 1000 })
  const run = beginChapterFinalizationRun(projectId, 7, 'version-b', { storage, now: 1001 })

  assert.equal(run.started, false)
  assert.equal(run.reason, 'pending_marker')
}

{
  const storage = createStorage()
  markChapterFinalizationPending(projectId, 8, { storage, now: 1000 })
  const retry = beginChapterFinalizationRun(projectId, 8, 'version-c', {
    storage,
    now: 2000,
    allowExistingPending: true
  })

  assert.equal(retry.started, true)
  assert.equal(retry.reason, '')
  assert.equal(getChapterFinalizationPending(projectId, 8, { storage, now: 2001 })?.startedAt, 2000)

  endChapterFinalizationRun(retry.runKey, projectId, 8, { storage })
  assert.equal(getChapterFinalizationPending(projectId, 8, { storage, now: 2002 }), null)
}

{
  const storage = createStorage()
  const run = beginChapterFinalizationRun(projectId, 10, 'version-d', { storage, now: 1000 })
  endChapterFinalizationRun(run.runKey, projectId, 10, {
    storage,
    keepPending: true,
    now: 2000,
    commitStatus: 'failed_after_chapter_commit',
    sourceVersionId: 'version-d'
  })
  const marker = getChapterFinalizationPending(projectId, 10, {
    storage,
    now: 2000 + 365 * 24 * 60 * 60 * 1000
  })
  assert.equal(marker?.commitStatus, 'failed_after_chapter_commit')
  assert.equal(marker?.sourceVersionId, 'version-d')
}

console.log('finalization guard tests passed')

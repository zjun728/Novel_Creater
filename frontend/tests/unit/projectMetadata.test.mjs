import assert from 'node:assert/strict'
import test from 'node:test'

import {
  PROJECT_METADATA_DEFAULTS,
  createProjectMetadataLeaveGuard,
  projectMetadataPayload,
  projectMetadataUpdatePayload,
} from '../../src/application/projects/projectMetadata.js'

test('project metadata payload keeps only the five public fields and applies long-form defaults', () => {
  assert.deepEqual(projectMetadataPayload({ title: '  典镇山河  ', apiKey: 'secret' }), {
    title: '典镇山河',
    genre: '',
    description: '',
    targetWords: 2_400_000,
    targetChapters: 720,
  })
  assert.deepEqual(PROJECT_METADATA_DEFAULTS, {
    genre: '',
    description: '',
    targetWords: 2_400_000,
    targetChapters: 720,
  })
})

test('project metadata leave guard covers route reuse and browser unload', () => {
  let saving = false
  let dirty = true
  let warnings = 0
  let confirmations = 0
  const guard = createProjectMetadataLeaveGuard({
    isSaving: () => saving,
    isDirty: () => dirty,
    confirmDiscard: () => { confirmations += 1; return false },
    warnSaving: () => { warnings += 1 },
  })

  assert.equal(guard.confirmLeave(), false)
  assert.equal(confirmations, 1)
  const event = { prevented: false, preventDefault() { this.prevented = true } }
  assert.equal(guard.beforeUnload(event), true)
  assert.equal(event.prevented, true)
  assert.equal(event.returnValue, '')

  saving = true
  assert.equal(guard.confirmLeave(), false)
  assert.equal(warnings, 1)
  saving = false
  dirty = false
  assert.equal(guard.confirmLeave(), true)
  assert.equal(guard.beforeUnload({ preventDefault() {} }), false)
})

test('project metadata update adds only the required lifecycle revision', () => {
  assert.deepEqual(projectMetadataUpdatePayload({
    title: '新标题',
    genre: '东方奇幻',
    description: '长篇简介',
    targetWords: 3_000_000,
    targetChapters: 900,
    expectedLifecycleRevision: 4,
    ignored: true,
  }), {
    title: '新标题',
    genre: '东方奇幻',
    description: '长篇简介',
    targetWords: 3_000_000,
    targetChapters: 900,
    expectedLifecycleRevision: 4,
  })
})

test('project metadata rejects invalid text and non-positive or coerced integers', () => {
  for (const input of [
    { title: '' },
    { title: '项目', genre: '题'.repeat(121) },
    { title: '项目', description: '介'.repeat(5001) },
    { title: '项目', targetWords: '2400000' },
    { title: '项目', targetChapters: 0 },
    { title: '项目', targetWords: 2_147_483_648 },
  ]) {
    assert.throws(() => projectMetadataPayload(input), /Invalid project metadata/)
  }
  assert.throws(
    () => projectMetadataUpdatePayload({ title: '项目', expectedLifecycleRevision: -1 }),
    /Invalid project metadata/,
  )
})

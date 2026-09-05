import assert from 'node:assert/strict'
import test from 'node:test'

import {
  PROJECT_METADATA_DEFAULTS,
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
  ]) {
    assert.throws(() => projectMetadataPayload(input), /Invalid project metadata/)
  }
  assert.throws(
    () => projectMetadataUpdatePayload({ title: '项目', expectedLifecycleRevision: -1 }),
    /Invalid project metadata/,
  )
})

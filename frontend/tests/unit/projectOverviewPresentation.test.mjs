import assert from 'node:assert/strict'
import test from 'node:test'

import {
  artifactStatusLabel,
  continuitySummary,
} from '../../src/application/projects/projectOverview.js'

test('artifact statuses use stable author-facing Chinese labels', () => {
  assert.equal(artifactStatusLabel('missing'), '尚未建立')
  assert.equal(artifactStatusLabel('working_draft'), '工作草稿')
  assert.equal(artifactStatusLabel('pending_confirmation'), '等待确认')
  assert.equal(artifactStatusLabel('current'), '当前正式版')
  assert.equal(artifactStatusLabel('needs_review'), '需要检查')
  assert.throws(() => artifactStatusLabel('draft'), /Unknown project overview status/)
})

test('continuity copy distinguishes the pending module from real issue counts', () => {
  assert.equal(
    continuitySummary({ availability: 'pending_module', pendingCount: null }),
    '连续性问题将在连续性模块启用后显示',
  )
  assert.equal(
    continuitySummary({ availability: 'available', pendingCount: 0 }),
    '暂无待处理的连续性问题',
  )
  assert.equal(
    continuitySummary({ availability: 'available', pendingCount: 3 }),
    '3 个连续性问题待处理',
  )
  assert.throws(
    () => continuitySummary({ availability: 'pending_module', pendingCount: 2 }),
    /Invalid project overview continuity/,
  )
})

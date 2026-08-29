import assert from 'node:assert/strict'
import test from 'node:test'

import { bibleHistoryStatusLabel, bibleModeLabel, bibleReasonLabel, presentBibleReasons } from '../../src/application/bible/bibleStatusPresentation.js'

const reasonLabels = {
  selection_missing: '请选择种子后继续。', seed_missing: '请选择种子后继续。',
  contract_missing: '请完成或重新签署创作契约。', contract_not_ready: '请完成或重新签署创作契约。', contract_revision_replaced: '请完成或重新签署创作契约。', contract_basis_invalid: '请完成或重新签署创作契约。', contract_unavailable: '请完成或重新签署创作契约。',
  selection_revision_changed: '内容已固定为项目永久基线，请查看历史记录。', seed_identity_changed: '内容已固定为项目永久基线，请查看历史记录。', seed_revision_changed: '内容已固定为项目永久基线，请查看历史记录。', seed_generation_changed: '内容已固定为项目永久基线，请查看历史记录。', contract_revision_changed: '内容已固定为项目永久基线，请查看历史记录。', creation_contract_changed: '内容已固定为项目永久基线，请查看历史记录。', style_contract_changed: '内容已固定为项目永久基线，请查看历史记录。', bible_policy_changed: '内容已固定为项目永久基线，请查看历史记录。', bible_head_changed: '内容已固定为项目永久基线，请查看历史记录。', bible_revision_replaced: '内容已固定为项目永久基线，请查看历史记录。',
  project_archived: '项目已归档，只能查阅。', bible_read_only: '项目已归档，只能查阅。',
}

test('reason presentation preserves every author guidance, omits confirmed, and deduplicates visible guidance', () => {
  for (const [reason, label] of Object.entries(reasonLabels)) assert.equal(bibleReasonLabel(reason), label)
  assert.equal(bibleReasonLabel('bible_confirmed'), null)
  assert.deepEqual(presentBibleReasons(['bible_confirmed', 'contract_unavailable', 'contract_basis_invalid']), ['请完成或重新签署创作契约。'])
})

test('reason presentation is frozen, fail-closed, and never echoes untrusted inputs', () => {
  const unknown = 'unknown <raw-token>'
  const expected = '创作圣经状态需要重新读取。'
  const values = [unknown, '__proto__', 'constructor', 'toString', null, [], Symbol('raw'), new Proxy({}, { get() { throw new Error('raw getter') } })]
  for (const value of values) {
    assert.doesNotThrow(() => bibleReasonLabel(value))
    assert.equal(bibleReasonLabel(value), expected)
    assert.doesNotMatch(bibleReasonLabel(value), /raw-token|__proto__|constructor|toString/)
  }
  const throwingReasons = new Proxy([], { get() { throw new Error('raw list getter') } })
  assert.doesNotThrow(() => presentBibleReasons(throwingReasons))
  for (const value of [undefined, null, {}, throwingReasons, ['contract_unavailable', unknown, 'contract_basis_invalid']]) {
    const labels = presentBibleReasons(value)
    assert.ok(Object.isFrozen(labels))
    assert.doesNotMatch(labels.join(' '), /raw-token|__proto__|constructor|toString/)
  }
  assert.deepEqual(presentBibleReasons(['contract_unavailable', unknown, 'contract_basis_invalid']), ['请完成或重新签署创作契约。', expected])
})

test('mode and history statuses use closed author-facing labels', () => {
  assert.deepEqual(Object.fromEntries(['first', 'draft', 'head', 'superseded', 'archived'].map(mode => [mode, bibleModeLabel(mode)])), {
    first: '待建立', draft: '工作草稿', head: '已确认', superseded: '历史修订', archived: '只读归档',
  })
  assert.deepEqual(Object.fromEntries(['current', 'superseded'].map(status => [status, bibleHistoryStatusLabel(status)])), {
    current: '当前修订', superseded: '历史修订',
  })
  for (const value of ['__proto__', 'constructor', 'toString', null, [], Symbol('raw'), new Proxy({}, { get() { throw new Error('raw getter') } })]) {
    assert.doesNotThrow(() => bibleModeLabel(value)); assert.doesNotThrow(() => bibleHistoryStatusLabel(value))
    assert.equal(bibleModeLabel(value), '状态待核对'); assert.equal(bibleHistoryStatusLabel(value), '状态待核对')
  }
})

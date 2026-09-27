import test from 'node:test'
import assert from 'node:assert/strict'
import { appendRewritePreset, rewritePresets } from '../../src/application/writer/rewritePresets.js'

test('presets preserve author instructions and never duplicate an applied preset', () => {
  for (const { label } of rewritePresets) {
    const value = appendRewritePreset('保留这句对白。', label)
    assert.ok(value.startsWith('保留这句对白。\n'))
    assert.ok(value.includes('保留既定事实、剧情走向和信息量。'))
    assert.equal(appendRewritePreset(value, label), value)
  }
})

test('oversized presets are rejected without truncating existing text, using Unicode scalars', () => {
  const addition = appendRewritePreset('', '改对白')
  const prefix = '😀'.repeat(1000 - Array.from(addition).length - 1)
  assert.equal(Array.from(appendRewritePreset(prefix, '改对白')).length, 1000)
  assert.equal(appendRewritePreset(`${prefix}😀`, '改对白'), null)
  assert.equal(appendRewritePreset('作者要求', '未知预设'), '作者要求')
})

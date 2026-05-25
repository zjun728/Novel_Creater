import assert from 'node:assert/strict'
import {
  applyLocalRevisionPatches,
  extractLocalRevisionPatches
} from '../frontend/src/utils/localRevisionPatch.js'

const original = [
  '林逐走进雨巷。',
  '他的境界是炼气三层。',
  '雨声压低了街上的人声。'
].join('\n')

const result = applyLocalRevisionPatches(original, [
  {
    issueIndex: 1,
    originalText: '他的境界是炼气三层。',
    replacementText: '他的境界仍停在炼气二层。',
    reason: '修正境界前后不一致'
  },
  {
    issueIndex: 2,
    originalText: '正文里不存在的片段',
    replacementText: '不应该被写入正文。',
    reason: '不能匹配则跳过'
  }
])

assert.equal(result.applied.length, 1)
assert.equal(result.skipped.length, 1)
assert.equal(
  result.content,
  [
    '林逐走进雨巷。',
    '他的境界仍停在炼气二层。',
    '雨声压低了街上的人声。'
  ].join('\n')
)

const ambiguous = applyLocalRevisionPatches('重复句。\n重复句。', [
  { originalText: '重复句。', replacementText: '替换句。' }
])

assert.equal(ambiguous.applied.length, 0)
assert.equal(ambiguous.skipped[0].reason, 'ambiguous_match')

const quoted = applyLocalRevisionPatches('“老钱。”他说。', [
  { originalText: '“老钱。”他说。', replacementText: '“老钱，别急。”他说。' }
])

assert.equal(quoted.applied.length, 1)
assert.equal(quoted.content, '“老钱，别急。”他说。')

const quotedUnique = applyLocalRevisionPatches('她说：“老钱。”老钱。', [
  { originalText: '“老钱。”', replacementText: '“别急。”' }
])

assert.equal(quotedUnique.applied.length, 1)
assert.equal(quotedUnique.content, '她说：“别急。”老钱。')

const lineWrapped = applyLocalRevisionPatches('林逐抬头。\n旧神经束开始发亮。', [
  { originalText: '林逐抬头。旧神经束开始发亮。', replacementText: '林逐抬头，旧神经束只亮了一瞬。' }
])

assert.equal(lineWrapped.applied.length, 1)
assert.equal(lineWrapped.content, '林逐抬头，旧神经束只亮了一瞬。')

const parsedAliases = extractLocalRevisionPatches({
  changes: [
    {
      oldText: '需要替换的原句。',
      newText: '替换后的新句。'
    }
  ]
})

assert.equal(parsedAliases.length, 1)
assert.equal(parsedAliases[0].originalText, '需要替换的原句。')
assert.equal(parsedAliases[0].replacementText, '替换后的新句。')

console.log('LOCAL_REVISION_PATCH_TEST_OK')

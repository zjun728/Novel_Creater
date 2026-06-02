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

const overbroadPatch = applyLocalRevisionPatches('甲'.repeat(520), [
  {
    originalText: '甲'.repeat(520),
    replacementText: '过度概括后的摘要。'
  }
])
assert.equal(overbroadPatch.applied.length, 0)
assert.equal(overbroadPatch.skipped[0].reason, 'overbroad_patch')

const overcompressedPatch = applyLocalRevisionPatches('乙'.repeat(180), [
  {
    originalText: '乙'.repeat(180),
    replacementText: '压缩太狠。'
  }
])
assert.equal(overcompressedPatch.applied.length, 0)
assert.equal(overcompressedPatch.skipped[0].reason, 'overcompressed_patch')

const overexpandedPatch = applyLocalRevisionPatches('丙'.repeat(24), [
  {
    originalText: '丙'.repeat(24),
    replacementText: '新增无关剧情。'.repeat(40)
  }
])
assert.equal(overexpandedPatch.applied.length, 0)
assert.equal(overexpandedPatch.skipped[0].reason, 'overexpanded_patch')

const trailingCommaJson = extractLocalRevisionPatches(`{
  "patches": [
    {
      "issueIndex": 1,
      "originalText": "不是刻上去的。是信息态纹理的显形。",
      "replacementText": "砧石表面浮现出一行字，字迹像信息态纹理自行显形。",
      "reason": "去掉机械句式",
    },
  ],
}`)
assert.equal(trailingCommaJson.length, 1)
assert.equal(trailingCommaJson[0].originalText, '不是刻上去的。是信息态纹理的显形。')

const truncatedJson = extractLocalRevisionPatches(`{
  "patches": [
    {
      "issueIndex": 1,
      "originalText": "林逐站在门口。",
      "replacementText": "林逐停在门槛外，先看了一眼门缝里漏出的灯。",
      "reason": "补足人物动作"
    },
    {
      "issueIndex": 2,
      "originalText": "这段还没写完"
`)
assert.equal(truncatedJson.length, 1)
assert.equal(truncatedJson[0].replacementText, '林逐停在门槛外，先看了一眼门缝里漏出的灯。')

const punctuationTolerant = applyLocalRevisionPatches(
  '不是刻上去的。是信息态纹理的显形。字迹像火尖烧出来的一道沟槽。',
  [
    {
      originalText: '不是刻上去的——是信息态纹理的显形。',
      replacementText: '砧石表面浮现出一行字，字迹像信息态纹理自行显形。'
    }
  ]
)
assert.equal(punctuationTolerant.applied.length, 1)
assert.equal(
  punctuationTolerant.content,
  '砧石表面浮现出一行字，字迹像信息态纹理自行显形。字迹像火尖烧出来的一道沟槽。'
)

console.log('LOCAL_REVISION_PATCH_TEST_OK')

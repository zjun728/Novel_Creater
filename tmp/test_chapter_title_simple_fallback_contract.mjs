import assert from 'node:assert/strict'

import {
  deriveFallbackChapterTitle,
  cleanGeneratedChapterTitle
} from '../frontend/src/prompts/chapter.js'

const cases = [
  {
    content: '火灶房里，侯小妹把《炼灵》残卷收进袖中。',
    expected: '炼灵'
  },
  {
    content: '无心和尚没有进门，只把黄金棺材推到院中。',
    expected: '黄金棺材'
  },
  {
    content: '金龙宝行的人亮出第七封信，裴昊退了一步。',
    expected: '第七封信'
  },
  {
    content: '大梵音寺的钟响过三声，林远才知道自己已经服软。',
    expectedOneOf: ['大梵音寺', '服软']
  }
]

for (const item of cases) {
  const title = deriveFallbackChapterTitle({ content: item.content })
  assert.equal(cleanGeneratedChapterTitle(title), title)
  if (item.expected) assert.equal(title, item.expected)
  if (item.expectedOneOf) assert.ok(item.expectedOneOf.includes(title), `${title} should be one of ${item.expectedOneOf.join(', ')}`)
}

const bad = deriveFallbackChapterTitle({
  content: '母亲核心开始发出冷光。档案室里的凭证被放回抽屉。',
  existingTitles: []
})
assert.notEqual(bad, '母亲核心冷光')
assert.notEqual(bad, '档案室凭证')

console.log('CHAPTER_TITLE_SIMPLE_FALLBACK_CONTRACT_OK')

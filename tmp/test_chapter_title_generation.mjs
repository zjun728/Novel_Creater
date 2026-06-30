import assert from 'node:assert/strict'
import {
  buildChapterTitlePrompt,
  buildChapterTitleSystemPrompt,
  collectPositiveChapterTitleCandidates,
  cleanGeneratedChapterTitle,
  deriveFallbackChapterTitle,
  evaluateChapterTitlePolicy,
  isChapterTitleDuplicate,
  isDefaultChapterTitle
} from '../frontend/src/prompts/chapter.js'

assert.equal(isDefaultChapterTitle('', 12), true)
assert.equal(isDefaultChapterTitle('第 12 章', 12), true)
assert.equal(isDefaultChapterTitle('第12章', 12), true)
assert.equal(isDefaultChapterTitle('雨夜归人', 12), false)

assert.equal(cleanGeneratedChapterTitle('《雨夜归人》'), '雨夜归人')
assert.equal(cleanGeneratedChapterTitle('# 第十二章 雨夜归人'), '雨夜归人')
assert.equal(cleanGeneratedChapterTitle('章名：雨夜归人'), '雨夜归人')
assert.equal(cleanGeneratedChapterTitle('火灶房'), '火灶房')
assert.equal(cleanGeneratedChapterTitle('黄金棺材'), '黄金棺材')
assert.equal(cleanGeneratedChapterTitle('十一号门'), '十一号门')
assert.equal(cleanGeneratedChapterTitle('林墨站在档案室门口想起母亲'), '')
assert.equal(cleanGeneratedChapterTitle('这是一个非常非常长的章节标题'), '')

const jsonTitle = cleanGeneratedChapterTitle(JSON.stringify({
  candidates: [
    { title: '林墨站在档案室门口想起母亲', type: 'event', reason: 'too long' },
    { title: '档案室', type: 'place', reason: '本章主要场景' }
  ]
}))
assert.equal(jsonTitle, '档案室')

assert.equal(
  deriveFallbackChapterTitle({
    beatPlan: '林墨进入棋院后山，发现一局没有执棋人的残局。',
    content: '风从棋院后山吹下来。石桌上那局无人棋还在，黑子压着一枚旧铜钱。'
  }),
  '棋院'
)

const positiveMaterials = collectPositiveChapterTitleCandidates({
  chapterNum: 88,
  beatPlan: '陆沉舟进入星债会地窖，在东城染坊找到铁箱账本和三号仓钥。',
  content: '马三说“就是这里”。陆沉舟打开铁箱账本，染坊钥匙压在账页下。'
})
assert.ok(
  positiveMaterials.some(item => item.title === '铁箱账本' && item.type === 'item'),
  'positive material extractor should include concrete evidence/item titles'
)
assert.ok(
  positiveMaterials.some(item => item.title === '星债会地窖' && item.type === 'place'),
  'positive material extractor should include concrete place titles'
)
assert.ok(
  positiveMaterials.every(item => item.title !== '就是这里'),
  'positive material extractor must not promote dialogue/location fragments'
)

const systemPrompt = buildChapterTitleSystemPrompt()
assert.match(systemPrompt, /真实网文目录/)
assert.match(systemPrompt, /朴素/)
assert.match(systemPrompt, /通俗易懂的目录标签/)
assert.match(systemPrompt, /不追求高级，不追求玄，不追求文学化/)
assert.match(systemPrompt, /房间、密室、账册、钥匙、纸条/)
assert.match(systemPrompt, /JSON/)

const prompt = buildChapterTitlePrompt({
  chapterNum: 12,
  chapterGoal: { goal: '主角回到林家旧宅，发现族谱中被抹去的名字。' },
  beatPlan: '1. 雨夜回宅。\n2. 族谱缺名。',
  content: '雨落在林家旧宅的青石板上。林逐看见族谱里那一页被刀尖刮得发白。'
})

assert.match(prompt, /生成 3-5 个章名候选/)
assert.match(prompt, /最近 5 个章名|本章正文/)
assert.match(prompt, /可以直接使用第一次出现的重要人物、功法、武器、组织、地点、房间、密室或道具名/)
assert.match(prompt, /简单直白的具体名词优先于漂亮但虚的词/)
assert.doesNotMatch(prompt, /物象 \+ 状态/)

assert.equal(
  isChapterTitleDuplicate('后山无人棋', { existingTitles: ['第 2 章 · 后山无人棋'] }),
  true
)
assert.equal(
  isChapterTitleDuplicate('后山旧棋', { existingTitles: ['第 2 章 · 后山无人棋'] }),
  false
)
assert.notEqual(evaluateChapterTitlePolicy('新的开始').status, 'pass')
assert.equal(evaluateChapterTitlePolicy('门裂痕').status, 'pass')

console.log('CHAPTER_TITLE_GENERATION_OK')

import assert from 'node:assert/strict'
import {
  buildChapterTitlePrompt,
  buildChapterTitleSystemPrompt,
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

const systemPrompt = buildChapterTitleSystemPrompt()
assert.match(systemPrompt, /真实网文目录/)
assert.match(systemPrompt, /朴素/)
assert.match(systemPrompt, /JSON/)

const prompt = buildChapterTitlePrompt({
  chapterNum: 12,
  chapterGoal: { goal: '主角回到林家旧宅，发现族谱中被抹去的名字。' },
  beatPlan: '1. 雨夜回宅。\n2. 族谱缺名。',
  content: '雨落在林家旧宅的青石板上。林逐看见族谱里那一页被刀尖刮得发白。'
})

assert.match(prompt, /生成 3-5 个章名候选/)
assert.match(prompt, /最近 5 个章名|本章正文/)
assert.match(prompt, /可以直接使用第一次出现的重要人物、功法、武器、组织、地点或道具名/)
assert.doesNotMatch(prompt, /物象 \+ 状态/)

assert.equal(
  isChapterTitleDuplicate('后山无人棋', { existingTitles: ['第 2 章 · 后山无人棋'] }),
  true
)
assert.equal(
  isChapterTitleDuplicate('后山旧棋', { existingTitles: ['第 2 章 · 后山无人棋'] }),
  false
)
assert.equal(evaluateChapterTitlePolicy('新的开始').status, 'pass')
assert.equal(evaluateChapterTitlePolicy('门裂痕').status, 'pass')

console.log('CHAPTER_TITLE_GENERATION_OK')

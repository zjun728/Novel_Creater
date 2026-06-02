import assert from 'node:assert/strict'
import {
  buildChapterTitlePrompt,
  buildChapterTitleSystemPrompt,
  cleanGeneratedChapterTitle,
  isDefaultChapterTitle
} from '../frontend/src/prompts/chapter.js'

assert.equal(isDefaultChapterTitle('', 12), true)
assert.equal(isDefaultChapterTitle('第 12 章', 12), true)
assert.equal(isDefaultChapterTitle('第12章', 12), true)
assert.equal(isDefaultChapterTitle('雨夜归人', 12), false)

assert.equal(cleanGeneratedChapterTitle('《雨夜归人》'), '雨夜归人')
assert.equal(cleanGeneratedChapterTitle('# 第十二章 雨夜归人'), '雨夜归人')
assert.equal(cleanGeneratedChapterTitle('章名：雨夜归人'), '雨夜归人')
assert.equal(cleanGeneratedChapterTitle('林墨在棋院后山无人棋'), '')
assert.equal(cleanGeneratedChapterTitle('林墨被带进密室'), '')
assert.equal(cleanGeneratedChapterTitle('后山无人棋'), '后山无人棋')
assert.equal(cleanGeneratedChapterTitle('这是一个非常非常非常非常长的章节标题'), '')

const systemPrompt = buildChapterTitleSystemPrompt()
assert.match(systemPrompt, /章节命名/)
assert.match(systemPrompt, /只输出章名/)
assert.match(systemPrompt, /不是剧情摘要/)
assert.match(systemPrompt, /不要直接截取正文句子/)

const prompt = buildChapterTitlePrompt({
  chapterNum: 12,
  chapterGoal: { goal: '主角回到林家旧宅，发现族谱中被抹去的名字。' },
  beatPlan: '1. 雨夜回宅。\n2. 族谱缺名。',
  content: '雨落在林家旧宅的青石板上。林逐看见族谱里那一页被刀尖刮得发白。'
})

assert.match(prompt, /第 12 章/)
assert.match(prompt, /本章正文节选/)
assert.match(prompt, /雨落在林家旧宅/)
assert.doesNotMatch(prompt, /只输出小说正文/)

console.log('CHAPTER_TITLE_GENERATION_OK')

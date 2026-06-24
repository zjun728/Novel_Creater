import assert from 'node:assert/strict'

import {
  buildChapterTitlePrompt,
  cleanGeneratedChapterTitle,
  deriveFallbackChapterTitle
} from '../frontend/src/prompts/chapter.js'

const prompt = buildChapterTitlePrompt({
  chapterNum: 21,
  chapterGoal: {
    goal: '主角在冷却期内追查凭证来源，但真正的变化是黑卡裂开第三道缝。'
  },
  beatPlan: '冷却期仍未结束。主角拿着凭证复核来源，黑卡忽然裂开第三道缝，露出新的暗号。',
  content: '冷却期还没结束，凭证已经被翻看过很多次。真正让他停住的是黑卡边缘那道新裂缝。第三道缝出现时，桌上的灯灭了一下。'
})

assert.match(prompt, /真实网文目录/)
assert.match(prompt, /朴素、直接、好记/)
assert.match(prompt, /event\|place\|person\|skill\|weapon\|item\|organization\|conflict\|result/)
assert.doesNotMatch(prompt, /抽象主题/)

assert.equal(cleanGeneratedChapterTitle('黑卡裂痕'), '黑卡裂痕')
assert.equal(cleanGeneratedChapterTitle('凭证'), '凭证')

const fallbackTitle = deriveFallbackChapterTitle({
  existingTitles: ['冷却期凭证'],
  beatPlan: '主角在冷却期内追查凭证来源，但真正的变化是黑卡裂开第三道缝。',
  content: '冷却期还没结束，凭证已经被翻看过很多次。真正让他停住的是黑卡边缘那道新裂缝。'
})

assert.ok(fallbackTitle, 'fallback title should produce a usable plain catalog title')
assert.equal(cleanGeneratedChapterTitle(fallbackTitle), fallbackTitle)

console.log('CHAPTER_TITLE_EVENT_NAMING_CONTRACT_OK')

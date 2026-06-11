import assert from 'node:assert/strict'
import {
  buildChapterBeatPrompt,
  buildChapterPrompt
} from '../frontend/src/prompts/chapter.js'

const context = {
  chapterNum: 12,
  wordTarget: {
    target: 5000,
    min: 4500,
    max: 6500,
    hardMin: 4000,
    hardMax: 7000
  },
  beatPlan: '1. 主角进入旧宅，发现被抹去的名字。\n2. 族老试探主角是否还怨恨父亲。',
  previousChapterEnding: '主角看见族谱上被刮掉的名字。'
}

const chapterPrompt = buildChapterPrompt(context)
assert.match(chapterPrompt, /4500-6500 字/)
assert.match(chapterPrompt, /质量优先级高于机械字数/)
assert.match(chapterPrompt, /不得为了压字数省略关键动作、情绪转折、人物反应、因果交代或章节钩子/)
assert.match(chapterPrompt, /可以略高于建议范围/)
assert.match(chapterPrompt, /不要超过 7000 字/)
assert.match(chapterPrompt, /不是硬性截断线/)
assert.match(chapterPrompt, /如果明显超量，请减少支线、旁白、重复描写或低效对白/)
assert.match(chapterPrompt, /本章容量预算/)
assert.match(chapterPrompt, /主场景建议控制在 3-4 个/)
assert.match(chapterPrompt, /不要把近景规划里的后续章节提前写进本章/)
assert.match(chapterPrompt, /支线展开、复盘解释和下一轮冲突优先留到下一章/)

const beatPrompt = buildChapterBeatPrompt(context)
assert.match(beatPrompt, /按约 5000 字体量设计/)
assert.match(beatPrompt, /优先服务 4500-6500 字正文/)
assert.match(beatPrompt, /小纲总长度控制在 700-1100 字/)
assert.match(beatPrompt, /节拍控制在 4-6 条/)
assert.match(beatPrompt, /不要规划成两章内容/)
assert.match(beatPrompt, /把后续冲突或余波留到下一章/)
assert.match(beatPrompt, /本章结尾应是自然小钩子/)

console.log('CHAPTER_WORD_PROMPT_GUARD_OK')

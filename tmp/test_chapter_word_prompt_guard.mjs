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
    max: 5500,
    hardMin: 4000,
    hardMax: 6000
  },
  beatPlan: '1. 主角进入旧宅，发现被抹去的名字。\n2. 族老试探主角是否还怨恨父亲。',
  previousChapterEnding: '主角看见族谱上被刮掉的名字。'
}

const chapterPrompt = buildChapterPrompt(context)
assert.match(chapterPrompt, /优先控制在 4500-5500 字/)
assert.match(chapterPrompt, /接近 6000 字/)
assert.match(chapterPrompt, /主动收束场景/)
assert.match(chapterPrompt, /不得为了压字数省略关键动作、情绪转折或因果交代/)
assert.match(chapterPrompt, /减少支线、旁白、重复描写或低效对白/)

const beatPrompt = buildChapterBeatPrompt(context)
assert.match(beatPrompt, /按约 5000 字体量设计/)
assert.match(beatPrompt, /不要规划成两章内容/)
assert.match(beatPrompt, /减少支线节拍/)
assert.match(beatPrompt, /把后续冲突或余波留到下一章/)

console.log('CHAPTER_WORD_PROMPT_GUARD_OK')

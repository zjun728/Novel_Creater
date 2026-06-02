import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildChapterBeatPrompt,
  buildChapterSystemPrompt
} from '../src/prompts/chapter.js'
import { formatWritingStyleStandardsForPrompt } from '../src/data/writingStyleStandards.js'

test('chapter beat prompt stays a planning prompt instead of inheriting chapter draft checklists', () => {
  const prompt = buildChapterBeatPrompt({
    chapterNum: 2,
    previousChapterEnding: '他推开门，看见桌上那枚旧铜钱正在发烫。',
    chapterGoal: {
      goal: '主角确认铜钱不是普通古物，并被迫做第一次选择。',
      conflict: '是否把线索交给来历不明的调查员。',
      turn: '铜钱里的旧誓言回应了主角。'
    },
    stateLedger: '主角：左手烫伤；铜钱：仍在身上。',
    worldRules: '古物只会回应真实代价。',
    beatPlan: ''
  })

  assert.match(prompt, /## 规划任务/)
  assert.doesNotMatch(prompt, /## 写作任务/)
  assert.doesNotMatch(prompt, /人物代入感要求/)
  assert.doesNotMatch(prompt, /配角自主性/)
  assert.doesNotMatch(prompt, /信息揭示方式/)
  assert.doesNotMatch(prompt, /句式节奏预设/)
  assert.doesNotMatch(prompt, /输出前静默自检/)
})

test('chapter system prompt keeps creative guidance light and leaves AI-tone policing to audit or repair', () => {
  const prompt = buildChapterSystemPrompt()

  assert.match(prompt, /小说章节正文/)
  assert.match(prompt, /已确认/)
  assert.doesNotMatch(prompt, /整章最多\s*2\s*次/)
  assert.doesNotMatch(prompt, /禁止连续使用套路化反差句/)
  assert.doesNotMatch(prompt, /连续短句独段/)
})

test('writing style standards are formatted as writing guidance, not audit checklists', () => {
  const prompt = formatWritingStyleStandardsForPrompt({
    primaryStandard: 'rational-fantasy',
    secondaryFlavor: 'folk-eerie',
    customStyleNotes: '保留考据解谜感，但不要把术语堆成说明书。'
  })

  assert.match(prompt, /主写作标准/)
  assert.match(prompt, /章节组织/)
  assert.match(prompt, /人物方法/)
  assert.match(prompt, /信息释放/)
  assert.match(prompt, /辅助风味/)
  assert.doesNotMatch(prompt, /审稿重点/)
  assert.doesNotMatch(prompt, /执行规则/)
})

import assert from 'node:assert/strict'

import {
  buildChapterBeatPlanJsonRepairPrompt,
  buildChapterBeatPlanParseRetryPrompt
} from '../frontend/src/prompts/chapter.js'

const truncatedRaw = `{
  "chapterEvent": "雨夜当铺内，陆沉舟清账时发现父亲名字出现在新账上。",
  "characterGoal": "陆沉舟要确认父亲名字异常的原因。",
  "coreConflict": "掌柜老周阻止他深查，巡天司夜巡逼近。",
  "externalPressure": "巡天司在当铺外搜查星账异常。",
  "costOrLoss": "陆沉舟使用星账后失去一段童年记忆。",
  "irreversibleChange": "陆沉舟获得玉佩线索并暴露追查行动。",
  "endingHandoff": "陆沉舟从后巷逃离，`

const parseRetryPrompt = buildChapterBeatPlanParseRetryPrompt({
  chapterNum: 1,
  previousCandidate: truncatedRaw,
  contextBrief: '当前故事块阶段：确认异常。'
})

assert.match(parseRetryPrompt, /只输出合法 JSON/)
assert.match(parseRetryPrompt, /不要 Markdown/)
assert.match(parseRetryPrompt, /每字段\s*60-120\s*个中文字符以内/)
for (const field of [
  'chapterEvent',
  'characterGoal',
  'coreConflict',
  'externalPressure',
  'costOrLoss',
  'irreversibleChange',
  'endingHandoff'
]) {
  assert.match(parseRetryPrompt, new RegExp(`"${field}"`), `parse retry prompt should include ${field}`)
}
assert.doesNotMatch(parseRetryPrompt, /loopExit|volumeGoalHandoff|usedTurnDecision/)

const repairPrompt = buildChapterBeatPlanJsonRepairPrompt({
  chapterNum: 1,
  candidateRaw: truncatedRaw
})

assert.match(repairPrompt, /只补全合法 JSON/)
assert.match(repairPrompt, /不允许新增剧情事实/)
assert.match(repairPrompt, /不允许扩写正文/)
assert.match(repairPrompt, /每字段\s*60-120\s*个中文字符以内/)
assert.doesNotMatch(repairPrompt, /Markdown/)

console.log('beat plan JSON repair prompt contract tests passed')

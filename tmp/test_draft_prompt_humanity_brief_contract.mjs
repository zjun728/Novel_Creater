import assert from 'node:assert/strict'
import {
  buildDraftPrompt,
  buildDraftSystemPrompt
} from '../frontend/src/prompts/chapterDraftPrompt.js'

const system = buildDraftSystemPrompt()
const prompt = buildDraftPrompt({
  chapterNum: 21,
  previousChapterEnding: '陆沉舟站在暗道里，听见上方有人叫小九的名字。',
  beatPlan: {
    chapterEvent: '陆沉舟带小九离开第三密栈，途中因隐瞒失忆产生争执。',
    characterGoal: '他想保住账本，也想继续装作自己没事。',
    coreConflict: '小九不再相信他每句“没事”。',
    externalPressure: '巡天司开始封锁主簿大堂后巷。',
    costOrLoss: '隐瞒让小九受伤。',
    irreversibleChange: '两人合作关系从照应变成带条件交易。',
    endingHandoff: '小九要求他把星账代价说清楚。'
  }
})
const combined = `${system}\n${prompt}`

for (const phrase of [
  '大白话',
  '动作、选择、停顿、隐瞒、误会',
  '不要每问必答',
  '行动和后果',
  '人物关系或主角选择发生小变化'
]) {
  assert.match(combined, new RegExp(phrase), `draft humanity brief should include: ${phrase}`)
}

const humanityBriefMatch = combined.match(/故事性与人物血肉轻量提示[\s\S]{0,520}/)
assert.ok(humanityBriefMatch, 'draft prompt should keep a short humanity brief section')
assert.doesNotMatch(
  humanityBriefMatch[0],
  /notXButY|短句率|同主语|硬性|必须逐条|rubric/i,
  'humanity brief must not become a hard QA rubric'
)

console.log('draft prompt humanity brief contract passed')

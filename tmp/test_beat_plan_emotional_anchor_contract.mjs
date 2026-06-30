import assert from 'node:assert/strict'
import {
  BEAT_PLAN_STRUCTURE_FIELDS,
  buildChapterBeatPrompt,
  collectStructuredBeatPlanIssues,
  formatStructuredBeatPlan,
  parseStructuredBeatPlan
} from '../frontend/src/prompts/chapter.js'

const prompt = buildChapterBeatPrompt({
  chapterNum: 21,
  previousChapterEnding: '陆沉舟站在第三密栈门口，左臂黑纹发烫。',
  storyBlock: {
    title: '密栈余波',
    relationshipFocus: '陆沉舟 / 小九',
    relationshipTask: '隐瞒失忆引发信任摩擦',
    sceneVarietyHint: '先用处理伤口和分歧场，不连续潜入。'
  }
})

for (const field of [
  'protagonistImmediateWant',
  'emotionalAnchor',
  'misbeliefOrFear',
  'relationshipDelta',
  'stageAnswerForReader'
]) {
  assert.match(prompt, new RegExp(field), `chapter beat prompt should request ${field}`)
  assert.ok(
    BEAT_PLAN_STRUCTURE_FIELDS.some(item => item.key === field && item.required === false && item.internal === true),
    `${field} should be optional/internal, not a hard gate`
  )
}

const minimal = parseStructuredBeatPlan({
  chapterEvent: '陆沉舟和小九先处理伤口，再确认第三密栈账本指向天池。',
  characterGoal: '陆沉舟想确认路线图真假，同时不让小九发现自己忘了一段旧事。',
  coreConflict: '小九不愿再陪他硬闯，巡天司也开始封锁密栈外街。',
  externalPressure: '巡天司换防提前，旧街小贩传来有人查问陆家旧识。',
  costOrLoss: '陆沉舟隐瞒失忆，导致小九误以为他不信任自己。',
  irreversibleChange: '小九要求参与下一步交易，两人的合作从被动跟随变成带条件结盟。',
  endingHandoff: '两人带着账本离开密栈，但路线图只剩半张。',
  protagonistImmediateWant: '先活着离开，再确认父亲是否故意瞒他。',
  emotionalAnchor: '他想信父亲，却第一次怕自己被父亲当成后手。',
  misbeliefOrFear: '他嘴硬说没事，其实怕小九发现他忘了母亲教账的细节。',
  relationshipDelta: '小九从单纯帮忙变成要求他交代实话。',
  stageAnswerForReader: '第三密栈账本确实指向天池，不只是徐主簿设局。'
})

assert.equal(minimal.emotionalAnchor.includes('父亲'), true)
assert.equal(minimal.relationshipDelta.includes('小九'), true)
const formatted = formatStructuredBeatPlan(minimal)
assert.match(formatted, /情绪锚点/)
assert.match(formatted, /关系轻微变化/)
assert.match(formatted, /给读者的阶段答案/)
assert.equal(collectStructuredBeatPlanIssues(minimal).issues.some(issue => issue.type.includes('emotional')), false)

const withoutOptional = collectStructuredBeatPlanIssues({
  chapterEvent: '陆沉舟带账本离开密栈。',
  characterGoal: '他要确认下一步去哪里。',
  coreConflict: '巡天司封锁街口。',
  externalPressure: '搜查逼近。',
  costOrLoss: '左臂伤势加重。',
  irreversibleChange: '账本从密栈转到陆沉舟手里。',
  endingHandoff: '他必须找安全处读账。'
})
assert.deepEqual(
  withoutOptional.missingRequiredFields,
  [],
  'emotional anchor fields should not be required hard gates'
)

console.log('beat plan emotional anchor contract passed')

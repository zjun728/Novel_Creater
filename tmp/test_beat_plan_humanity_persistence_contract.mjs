import assert from 'node:assert/strict'
import {
  compactStructuredBeatPlanFields,
  formatStructuredBeatPlan,
  parseStructuredBeatPlan
} from '../frontend/src/prompts/chapter.js'

const humanityFields = {
  protagonistImmediateWant: '陆沉舟眼下只想确认父亲留下的半张账图真假，同时把小九安全带出封锁街。',
  emotionalAnchor: '他嘴上说只看证据，心里却怕父亲真把他当成一枚可以牺牲的后手。',
  misbeliefOrFear: '他误以为小九追问是想退出，便故意把左臂黑纹藏在袖子里。',
  relationshipDelta: '小九看出他隐瞒伤势后不再只跟着走，而是要求下一步由她先谈条件。',
  stageAnswerForReader: '半张账图确实通向城南水渠，第三密栈不是徐主簿临时编出的假线。'
}

const sourcePlan = {
  chapterEvent: '陆沉舟和小九在封锁街边处理伤口，并用半张账图换到城南水渠的入口线索。',
  characterGoal: '陆沉舟要确认账图真假，又不想让小九知道自己记忆缺了一块。',
  coreConflict: '巡天司换防提前，小九也不愿再被他一句没事糊弄过去。',
  externalPressure: '封锁街口的搜查逼近，灰衣人留下的暗记正在被人抹掉。',
  costOrLoss: '陆沉舟为了保住账图承认自己忘了一段父亲旧事，小九对他的信任带上条件。',
  irreversibleChange: '两人的合作从临时同行变成带条件互相兜底，水渠入口也被巡天司注意。',
  endingHandoff: '他们必须在下一章赶到水渠口，但小九先拿走了半张账图。',
  ...humanityFields
}

const compacted = compactStructuredBeatPlanFields(sourcePlan, { maxFieldChars: 120 })
const formatted = formatStructuredBeatPlan(compacted)
const reparsed = parseStructuredBeatPlan(formatted)

for (const [key, expected] of Object.entries(humanityFields)) {
  assert.match(formatted, new RegExp(`###\\s*${{
    protagonistImmediateWant: '主角即时欲望',
    emotionalAnchor: '情绪锚点',
    misbeliefOrFear: '误解或恐惧',
    relationshipDelta: '关系轻微变化',
    stageAnswerForReader: '给读者的阶段答案'
  }[key]}`), `${key} should be written as a persisted markdown section`)
  assert.equal(
    reparsed[key],
    compacted[key],
    `${key} should survive format -> parse round trip instead of becoming inferred-only`
  )
  assert.ok(reparsed[key].includes(expected.slice(0, 8)), `${key} should keep its concrete content`)
}

console.log('beat plan humanity persistence contract passed')

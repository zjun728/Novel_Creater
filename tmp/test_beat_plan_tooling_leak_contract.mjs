import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  buildLocalChapterBeatPlanFallback,
  collectStructuredBeatPlanIssues,
  containsBeatPlanToolingLeak,
  deriveChapterBeatPlanFromStoryBlock
} from '../frontend/src/prompts/chapter.js'

const context = {
  chapterNum: 26,
  blockStageSnapshot: {
    storyBlockId: 'block-waterway',
    stageId: 'stage-4',
    stagePurpose: '让陆沉舟把第三密栈线索带到城南水渠，并与小九发生一次信任谈判。',
    blockGoal: '把第三密栈账图从密栈余波推进到城南水渠入口。',
    entryState: '陆沉舟和小九从封锁街退到卖灯棚后，左臂黑纹还在发烫。',
    stageAction: '陆沉舟用半张账图向灯棚老太太换取城南水渠入口，巡天司搜查同时压近。',
    stageChoice: '陆沉舟选择向小九承认自己漏掉一段父亲旧记忆，换她继续帮忙。',
    stageCostOrConsequence: '小九不再无条件跟随，半张账图交到她手里，巡天司也记住了灯棚暗号。',
    mainPressure: '巡天司临检灯棚，老太太只肯给一次开口机会。',
    unresolvedQuestions: ['父亲为何把账图分成两半', '城南水渠里是谁在等他'],
    nextStageSuggestion: 'stage-4',
    exitTarget: '城南水渠入口外的铁栅前'
  }
}

const fallback = buildLocalChapterBeatPlanFallback(context, 26, '')
assert.equal(
  containsBeatPlanToolingLeak('第 25 章发生一件读者能复述的事：人物目标：围绕“stage-4”。'),
  true,
  'tooling leak detector should catch old fallback phrasing'
)
assert.equal(
  containsBeatPlanToolingLeak('stage-5（安全屋休整与决策）'),
  true,
  'tooling leak detector should catch stage pointers even when they carry a label'
)
assert.equal(
  containsBeatPlanToolingLeak('下一阶段：stage-x'),
  true,
  'tooling leak detector should catch symbolic stage pointers'
)
assert.equal(
  containsBeatPlanToolingLeak('本章关系变化落在“陆沉舟和小九的互信”，不能只把配角当线索出口。'),
  true,
  'tooling leak detector should catch relationship-task scaffolding text'
)
assert.equal(
  containsBeatPlanToolingLeak('主角要完成客栈取信，并把结果接到废弃矿道入口。'),
  true,
  'tooling leak detector should catch mechanical handoff scaffolding text'
)
assert.equal(
  containsBeatPlanToolingLeak(fallback),
  false,
  'local fallback beat plan should not leak tool phrasing into final beat plan text'
)
assert.doesNotMatch(fallback, /读者能复述的事|人物目标：围绕|本章关系变化落在|不能只把配角当线索出口|stage-[\dx]+/i)

const derivation = deriveChapterBeatPlanFromStoryBlock(context, 26)
assert.equal(derivation.allowedToContinue, true)
assert.equal(derivation.source, 'derived_from_story_block')
assert.equal(containsBeatPlanToolingLeak(derivation.content), false)
assert.doesNotMatch(derivation.content, /读者能复述的事|人物目标：围绕|本章关系变化落在|不能只把配角当线索出口|stage-[\dx]+/i)

const structuredIssues = collectStructuredBeatPlanIssues({
  chapterEvent: '陆沉舟到达安全屋，处理伤口并确认下一步路线。',
  characterGoal: '陆沉舟要决定是否立刻出发。',
  coreConflict: '巡天司搜捕和伤势同时压迫他。',
  externalPressure: '搜查逼近，安全屋可能暴露。',
  costOrLoss: '继续休整会失去时间，立刻出发会加重伤势。',
  irreversibleChange: '小九接过路线判断权。',
  endingHandoff: 'stage-5（安全屋休整与决策）',
  relationshipDelta: '本章关系变化落在“陆沉舟和小九的互信”，不能只把配角当线索出口。',
  stageAnswerForReader: '主角要完成客栈取信，并把结果接到废弃矿道入口。'
})
assert.ok(
  structuredIssues.toolingLeakFields.includes('endingHandoff'),
  'structured beat plan quality should flag stage pointer leaks in final fields'
)
assert.ok(
  structuredIssues.toolingLeakFields.includes('relationshipDelta'),
  'relationship helper fields should reject scaffolding text'
)
assert.ok(
  structuredIssues.toolingLeakFields.includes('stageAnswerForReader'),
  'reader answer fields should reject mechanical handoff scaffolding'
)

const writerStoreSource = fs.readFileSync('frontend/src/stores/writerStore.js', 'utf8')
assert.match(
  writerStoreSource,
  /toolingLeakFields[\s\S]{0,240}beat_plan_requires_review|beat_plan_requires_review[\s\S]{0,240}toolingLeakFields/,
  'unrepaired tooling leaks should be classified as beat_plan_requires_review before draft generation'
)

console.log('beat plan tooling leak contract passed')

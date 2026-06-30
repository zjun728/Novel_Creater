import assert from 'node:assert/strict'
import {
  analyzeChapter,
  summarizeRerun
} from './story_humanity_rerun_21_25.mjs'

const sample = [
  {
    chapterNum: 43,
    text: '追兵搜查客栈，陆沉舟带小九撤离地道，拿到账页后躲藏，又解读去下一地点。',
    expect: 'chase_escape'
  },
  {
    chapterNum: 44,
    text: '陆沉舟没有逃，他和小九在废院对峙争执。小九质问他为什么隐瞒星账代价，两人重新谈条件。',
    expect: 'relationship_confrontation'
  },
  {
    chapterNum: 45,
    text: '星账黑纹裂开，陆沉舟失去一段父亲记忆。老陈沉默替他包扎，众人看见代价后改变计划。',
    expect: 'consequence_scene'
  },
  {
    chapterNum: 46,
    text: '陆沉舟主动设局，把假账页交给甲十七，安排老陈去南巷放风，等缺指男人自己露面。',
    expect: 'active_setup'
  },
  {
    chapterNum: 47,
    text: '巡天司搜查水渠，陆沉舟翻过旧墙撤离，带着线索躲进废矿道继续解读下一处入口。',
    expect: 'chase_escape'
  }
]

const chapters = sample.map(item => analyzeChapter({
  chapterNum: item.chapterNum,
  reportEntry: {
    title: `第${item.chapterNum}章`,
    finalized: true,
    storyBlockId: 'block-function',
    blockStageId: `stage-${item.chapterNum}`
  },
  beat: { beatPlanSource: 'ai_generated', content: '' },
  beatPlanFields: {
    protagonistImmediateWant: '先稳住局面',
    emotionalAnchor: '怕再次误判',
    misbeliefOrFear: '嘴硬说自己没事',
    relationshipDelta: '陆沉舟和小九的信任发生变化。',
    stageAnswerForReader: '确认缺指男人在逼星账露面。'
  },
  content: item.text
}))

assert.deepEqual(chapters.map(item => item.dominantStoryFunction), sample.map(item => item.expect))

const comparison = summarizeRerun(chapters, {}, { rangeStart: 43, rangeEnd: 47 })

assert.equal(comparison.storyFunctionMix.nonChaseDominantCount, 3)
assert.equal(comparison.storyFunctionMix.chaseEscapeCount, 2)
assert.equal(comparison.storyFunctionMix.acceptanceNonChaseThresholdMet, true)
assert.ok(['reduced', 'still_dominant'].includes(comparison.chaseLoop.status))
assert.notEqual(comparison.chaseLoop.status, 'resolved')

console.log('story humanity story function report contract passed')

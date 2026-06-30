import assert from 'node:assert/strict'
import {
  analyzeChapter,
  summarizeRerun
} from './story_humanity_rerun_21_25.mjs'

const chapter = analyzeChapter({
  chapterNum: 43,
  reportEntry: {
    title: '半炷香',
    finalized: true,
    storyBlockId: 'block-partial',
    blockStageId: 'stage-1',
    wordCount: 4780
  },
  beat: { beatPlanSource: 'ai_generated', content: '' },
  beatPlanFields: {
    protagonistImmediateWant: '先拿到缺指男人去向',
    emotionalAnchor: '父亲名字再次出现带来不安',
    misbeliefOrFear: '误以为父亲线索能同时救小九',
    relationshipDelta: '与当铺掌柜形成带代价交易。',
    stageAnswerForReader: '确认父亲名字和缺指男人有关。'
  },
  content: '陆沉舟追问当铺掌柜，拿到账页线索，街外有人搜查，他判断缺指男人去了码头。'
})

const comparison = summarizeRerun([chapter], {}, { rangeStart: 43, rangeEnd: 47 })

assert.equal(comparison.chaseLoop.status, 'insufficient_sample')
assert.equal(comparison.chaseLoop.insufficientSampleForResolved, true)
assert.notEqual(comparison.chaseLoop.status, 'resolved')

console.log('story humanity partial blocker report contract passed')

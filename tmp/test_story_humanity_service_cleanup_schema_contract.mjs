import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  analyzeChapter,
  summarizeRerun
} from './story_humanity_rerun_21_25.mjs'

const reportScript = readFileSync('tmp/story_humanity_rerun_21_25.mjs', 'utf8')
assert.match(reportScript, /serviceCleanupDiagnostics/)
assert.match(reportScript, /loadServiceCleanupDiagnostics/)
assert.doesNotMatch(reportScript, /serviceCleanupSafetyDiagnostics/)

const chapter = analyzeChapter({
  chapterNum: 38,
  reportEntry: {
    title: '第三密栈',
    finalized: true,
    storyBlockId: 'block-open',
    blockStageId: 'stage-5',
    storyBlockReviewDecision: 'continue_current_block',
    stageContinuationDepth: 0,
    previousOpenStageId: 'stage-4',
    settlementDecision: 'completed_by_equivalent_story_function',
    settlementEvidence: ['小九被绑', '星账代价加剧'],
    whetherStageClosedBeforeNextBeatPlan: true
  },
  beatPlanFields: {
    emotionalAnchor: '怕再误判',
    relationshipDelta: '小九和陆沉舟的亏欠更深',
    stageAnswerForReader: '第三密栈是缺指男人下一步目标。'
  },
  content: '陆沉舟确认第三密栈是下一步目标。'
})

assert.equal(chapter.stageContinuationDepth, 0)
assert.equal(chapter.previousOpenStageId, 'stage-4')
assert.equal(chapter.settlementDecision, 'completed_by_equivalent_story_function')
assert.deepEqual(chapter.settlementEvidence, ['小九被绑', '星账代价加剧'])
assert.equal(chapter.whetherStageClosedBeforeNextBeatPlan, true)

const comparison = summarizeRerun([chapter], {}, { rangeStart: 38, rangeEnd: 42 })
assert.equal(comparison.stageReuse.stageContinuationDiagnostics[0].settlementDecision, 'completed_by_equivalent_story_function')

console.log('story humanity service cleanup schema contract passed')

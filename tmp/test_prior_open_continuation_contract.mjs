import assert from 'node:assert/strict'
import {
  analyzeChapter,
  summarizePriorOpenContinuation
} from './story_humanity_rerun_21_25.mjs'

const prior = {
  chapterNum: 35,
  storyBlockId: 'block-open',
  blockStageId: 'stage-4',
  storyBlockStageContinues: true,
  storyBlockStageContinueReason: '下一章展开南门渡行动，完成取物人反制或逆转。'
}

const current = [
  analyzeChapter({
    chapterNum: 36,
    reportEntry: {
      title: '南门渡',
      finalized: true,
      storyBlockId: 'block-open',
      blockStageId: 'stage-4',
      storyBlockStageContinues: false,
      storyBlockReviewDecision: 'adjust_remaining_stages',
      wordCount: 5200
    },
    beatPlanFields: {
      emotionalAnchor: '怕判断错',
      relationshipDelta: '小九重新信他',
      stageAnswerForReader: '南门渡伏击完成'
    },
    content: '南门渡伏击完成。'
  })
]

const summary = summarizePriorOpenContinuation(current, prior)
assert.equal(summary.status, 'completed_in_current_range')
assert.equal(summary.carriedByChapter, 36)
assert.match(summary.priorStageContinueReason, /南门渡/)

const missing = summarizePriorOpenContinuation([
  analyzeChapter({
    chapterNum: 36,
    reportEntry: {
      title: '南门渡',
      finalized: true,
      storyBlockId: 'block-open',
      blockStageId: 'stage-4',
      storyBlockStageContinues: true,
      storyBlockStageContinueReason: '',
      wordCount: 5200
    },
    beatPlanFields: { emotionalAnchor: '怕', relationshipDelta: '信任变化' },
    content: '南门渡。'
  })
], prior)

assert.equal(missing.status, 'continued_without_reason')
assert.equal(missing.hasIssue, true)

const stillOpenAfter37 = summarizePriorOpenContinuation([
  analyzeChapter({
    chapterNum: 36,
    reportEntry: {
      title: '更夫',
      finalized: true,
      storyBlockId: 'block-open',
      blockStageId: 'stage-4',
      storyBlockStageContinues: true,
      storyBlockStageContinueReason: '下一章再完成判断失误后果。',
      wordCount: 5200
    },
    beatPlanFields: { emotionalAnchor: '怕', relationshipDelta: '信任变化' },
    content: '更夫。'
  }),
  analyzeChapter({
    chapterNum: 38,
    reportEntry: {
      title: '第 38 章',
      finalized: false,
      storyBlockId: 'block-open',
      blockStageId: 'stage-4',
      wordCount: 0
    },
    beatPlanFields: { emotionalAnchor: '怕', relationshipDelta: '信任变化' },
    content: ''
  }),
  analyzeChapter({
    chapterNum: 37,
    reportEntry: {
      title: '真画',
      finalized: true,
      storyBlockId: 'block-open',
      blockStageId: 'stage-4',
      storyBlockStageContinues: true,
      storyBlockStageContinueReason: '还要下一章继续完成判断失误后果。',
      wordCount: 5200
    },
    beatPlanFields: { emotionalAnchor: '怕', relationshipDelta: '信任变化' },
    content: '真画。'
  })
], prior)

assert.equal(stillOpenAfter37.status, 'still_open_after_37')
assert.equal(stillOpenAfter37.hasIssue, true)

console.log('prior open continuation contract passed')

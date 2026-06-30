import assert from 'node:assert/strict'
import {
  analyzeChapter,
  summarizeRerun
} from './story_humanity_rerun_21_25.mjs'

const chapters = [
  analyzeChapter({
    chapterNum: 26,
    reportEntry: {
      title: '排水道',
      finalized: true,
      storyBlockId: 'block-a',
      blockStageId: 'stage-4',
      storyBlockStageContinues: true,
      storyBlockStageContinueReason: '第 26 章只完成会合与取钥匙，星账代价尚未兑现，需要第 27 章继续同一阶段。',
      wordCount: 5800
    },
    beatPlanFields: {
      protagonistImmediateWant: '离开排水道',
      emotionalAnchor: '怕再丢记忆',
      relationshipDelta: '小九开始信他',
      stageAnswerForReader: '灰衣人是旧部'
    },
    content: '陆沉舟和小九进入排水道，确认灰衣人身份。'
  }),
  analyzeChapter({
    chapterNum: 27,
    reportEntry: {
      title: '旧铜钥匙',
      finalized: true,
      storyBlockId: 'block-a',
      blockStageId: 'stage-4',
      previousStoryBlockStageContinues: true,
      previousStoryBlockReviewDecision: 'continue_current_block',
      storyBlockStageContinues: false,
      storyBlockReviewDecision: 'adjust_remaining_stages',
      wordCount: 5700
    },
    beatPlanFields: {
      protagonistImmediateWant: '带钥匙离开',
      emotionalAnchor: '开始怕星账',
      relationshipDelta: '甲十七从传话人变成看管人',
      stageAnswerForReader: 'stage-4 完成'
    },
    content: '陆沉舟用旧铜钥匙打开暗渠，兑现星账代价。'
  })
]

const comparison = summarizeRerun(chapters, {}, { rangeStart: 26, rangeEnd: 27 })

assert.equal(comparison.stageReuse.duplicateStageCount, 1)
assert.equal(comparison.stageReuse.repeatedStages[0].stageId, 'stage-4')
assert.equal(comparison.stageReuse.repeatedStages[0].status, 'legal_continue')
assert.match(comparison.stageReuse.repeatedStages[0].stageContinueReason, /星账代价尚未兑现/)
assert.equal(comparison.stageReuse.hasHiddenAbnormalReuse, false)
assert.equal(comparison.stageReuse.openContinuations.length, 1)
assert.equal(comparison.stageReuse.openContinuations[0].chapterNum, 26)
assert.equal(comparison.stageReuse.openContinuations[0].status, 'legal_continue')

const abnormal = summarizeRerun([
  analyzeChapter({
    chapterNum: 31,
    reportEntry: { title: '矿道', finalized: true, storyBlockId: 'block-b', blockStageId: 'stage-2', wordCount: 5500 },
    beatPlanFields: { emotionalAnchor: '怕', relationshipDelta: '信任变化' },
    content: '矿道。'
  }),
  analyzeChapter({
    chapterNum: 32,
    reportEntry: { title: '铜盘', finalized: true, storyBlockId: 'block-b', blockStageId: 'stage-2', wordCount: 5500 },
    beatPlanFields: { emotionalAnchor: '怕', relationshipDelta: '信任变化' },
    content: '铜盘。'
  })
], {}, { rangeStart: 31, rangeEnd: 32 })

assert.equal(abnormal.stageReuse.repeatedStages[0].status, 'missing_continue_reason')
assert.equal(abnormal.stageReuse.hasHiddenAbnormalReuse, true)

const missingOpenReason = summarizeRerun([
  analyzeChapter({
    chapterNum: 35,
    reportEntry: {
      title: '南门渡',
      finalized: true,
      storyBlockId: 'block-c',
      blockStageId: 'stage-4',
      storyBlockStageContinues: true,
      storyBlockStageContinueReason: '',
      wordCount: 5500
    },
    beatPlanFields: { emotionalAnchor: '怕', relationshipDelta: '信任变化' },
    content: '南门渡。'
  })
], {}, { rangeStart: 35, rangeEnd: 35 })

assert.equal(missingOpenReason.stageReuse.openContinuations[0].status, 'missing_continue_reason')
assert.equal(missingOpenReason.stageReuse.hasHiddenAbnormalReuse, true)

console.log('stage reuse continue report contract passed')

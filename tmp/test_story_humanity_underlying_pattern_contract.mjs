import assert from 'node:assert/strict'
import {
  analyzeChapter,
  classifyUnderlyingProgressionPattern,
  summarizeRerun
} from './story_humanity_rerun_21_25.mjs'

const samples = [
  {
    chapterNum: 48,
    text: '陆沉舟给掌柜留下一张假账页，又让小九去茶摊放话。他不急着逃，等巡天司的人自己来问价。',
    dominant: 'active_setup',
    pattern: 'active_setup'
  },
  {
    chapterNum: 49,
    text: '掌柜扣住旧铜扣不肯交，陆沉舟和他谈条件。小九打断两次，逼掌柜说出马三欠账的实价。',
    dominant: 'relationship_confrontation',
    pattern: 'relationship_negotiation'
  },
  {
    chapterNum: 50,
    text: '搜查声逼近，陆沉舟带着新线索撤离水渠，钻进地道后立刻解读铜扣，决定去下一处西仓库。',
    dominant: 'consequence_scene',
    pattern: 'pursuit_pressure'
  },
  {
    chapterNum: 51,
    text: '陆沉舟拿到马三留下的钥匙，钥匙背面刻着新地址。他没有停留，带小九立刻转去码头后巷。',
    dominant: 'investigation',
    pattern: 'clue_handoff'
  },
  {
    chapterNum: 52,
    text: '星账残页一碰就碎，陆沉舟试着用旧铜扣压住账纹，结果掌心黑纹反噬。小九看见后逼他改用人情换消息。',
    dominant: 'consequence_scene',
    pattern: 'rule_discovery_by_action'
  }
]

for (const item of samples) {
  assert.equal(
    classifyUnderlyingProgressionPattern(item.text),
    item.pattern,
    `${item.chapterNum} should classify underlying progression as ${item.pattern}`
  )
}

const chapters = samples.map(item => analyzeChapter({
  chapterNum: item.chapterNum,
  reportEntry: {
    title: `第${item.chapterNum}章`,
    finalized: true,
    dominantStoryFunction: item.dominant,
    storyBlockId: 'block-underlying',
    blockStageId: `stage-${item.chapterNum}`
  },
  beat: { beatPlanSource: 'ai_generated', content: '' },
  beatPlanFields: {
    protagonistImmediateWant: '先稳住局面',
    emotionalAnchor: '担心再次失去小九',
    misbeliefOrFear: '嘴硬说自己还撑得住',
    relationshipDelta: '陆沉舟和小九的信任发生变化。',
    stageAnswerForReader: '确认铜扣和父亲线有关。'
  },
  content: item.text
}))

assert.deepEqual(
  chapters.map(item => item.underlyingProgressionPattern),
  samples.map(item => item.pattern)
)

const comparison = summarizeRerun(chapters, {}, { rangeStart: 48, rangeEnd: 52 })

assert.equal(comparison.storyFunctionMix.nonChaseDominantCount, 5)
assert.equal(comparison.underlyingProgressionPattern.nonPursuitUnderlyingPatternCount, 3)
assert.equal(comparison.underlyingProgressionPattern.pursuitOrClueHandoffCount, 2)
assert.equal(comparison.underlyingProgressionPattern.acceptanceNonPursuitThresholdMet, true)
assert.ok(['reduced', 'still_dominant'].includes(comparison.chaseLoop.status))

const mislabeled = chapters.map((chapter, index) => ({
  ...chapter,
  underlyingProgressionPattern: index < 4 ? 'pursuit_pressure' : 'clue_handoff',
  indicators: {
    ...chapter.indicators,
    loopSignal: index < 4 ? 'medium_chase_or_escape_loop' : chapter.indicators.loopSignal
  }
}))
const misleadingComparison = summarizeRerun(mislabeled, {}, { rangeStart: 48, rangeEnd: 52 })

assert.equal(misleadingComparison.storyFunctionMix.nonChaseDominantCount, 5)
assert.equal(misleadingComparison.underlyingProgressionPattern.nonPursuitUnderlyingPatternCount, 0)
assert.equal(misleadingComparison.chaseLoop.status, 'still_dominant')
assert.notEqual(
  misleadingComparison.chaseLoop.status,
  'reduced',
  'chaseLoop must not be reduced merely because dominantStoryFunction is non-chase'
)

const weakTitleChapter = analyzeChapter({
  chapterNum: 50,
  reportEntry: {
    title: '操',
    finalized: true,
    storyBlockId: 'block-title',
    blockStageId: 'stage-title'
  },
  beat: { beatPlanSource: 'ai_generated', content: '' },
  beatPlanFields: {},
  content: '陆沉舟骂了一句，手里的账页碎了。'
})
assert.equal(weakTitleChapter.weakTitle, true, 'single-character oral exclamation title should be weak in story report')

console.log('story humanity underlying progression pattern contract passed')

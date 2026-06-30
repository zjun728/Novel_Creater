import assert from 'node:assert/strict'
import {
  analyzeChapter,
  summarizeRerun
} from './story_humanity_rerun_21_25.mjs'

const chapters = Array.from({ length: 10 }, (_, index) => {
  const chapterNum = 36 + index
  const hasTexture = [36, 40, 44].includes(chapterNum)
  const chaseText = index < 3
    ? '追兵搜查，陆沉舟撤离地道，拿线索后躲藏，再解读去下一地点。'
    : '陆沉舟在客栈和小九处理伤口，做出是否相信甲十七的选择。'
  return analyzeChapter({
    chapterNum,
    reportEntry: {
      title: `北仓${index}`,
      finalized: true,
      storyBlockId: 'block-mid',
      blockStageId: `stage-${index + 1}`,
      wordCount: 5200
    },
    beat: { beatPlanSource: 'ai_generated', content: '' },
    beatPlanFields: {
      protagonistImmediateWant: '先保住小九',
      emotionalAnchor: '怕再次判断错',
      misbeliefOrFear: '嘴硬说没事',
      relationshipDelta: hasTexture ? '小九和陆沉舟因为包扎伤口重新建立信任。' : '甲十七暂时配合。',
      stageAnswerForReader: '确认下一步去南门渡。'
    },
    content: `${chaseText}${hasTexture ? '两人停下来包扎伤口，吃了半碗冷饭，吵了一句后决定继续合作。' : ''}`
  })
})

const comparison = summarizeRerun(chapters, {}, { rangeStart: 36, rangeEnd: 45 })

assert.equal(comparison.mechanismFieldPersistence.chaptersWithPersistedHumanityFields, 10)
assert.equal(comparison.mechanismFieldPersistence.requiredPersistedHumanityChapters, 8)
assert.equal(comparison.mechanismFieldPersistence.persistedHumanityThresholdMet, true)
assert.ok(comparison.sceneTextureEvidence.chaptersWithTexture >= 3)
assert.equal(comparison.sceneTextureEvidence.everyFiveChapterWindowHasTexture, true)
assert.equal(comparison.chaseLoop.consecutiveLoopWarning, true)
assert.equal(comparison.chaseLoop.maxConsecutiveLoopChapters >= 3, true)
assert.equal(comparison.chaseLoop.status !== 'chaseLoopResolved', true)
assert.equal(comparison.finalChapterStageAnswer.finalized, true)
assert.equal(comparison.finalChapterStageAnswer.hasStageAnswer, true)

const partialChapters = chapters.slice(0, 2)
const partialComparison = summarizeRerun(partialChapters, {}, { rangeStart: 36, rangeEnd: 45 })
assert.equal(partialComparison.finalChapterStageAnswer.finalized, false)
assert.equal(partialComparison.finalChapterStageAnswer.hasStageAnswer, false)
assert.match(partialComparison.finalChapterStageAnswer.verdict, /第 45 章未定稿/)

console.log('story humanity midrange report contract passed')

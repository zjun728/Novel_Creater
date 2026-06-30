import assert from 'node:assert/strict'
import {
  analyzeChapter,
  classifyChaseLoop,
  summarizeRerun
} from './story_humanity_rerun_21_25.mjs'

const inferredOnlyChapters = [26, 27, 28, 29, 30].map((chapterNum, index) => analyzeChapter({
  chapterNum,
  reportEntry: { title: ['水渠口', '灯棚后', '旧闸', '封街', '半账'][index], finalized: true, wordCount: 6100 },
  chapter: { title: ['水渠口', '灯棚后', '旧闸', '封街', '半账'][index], status: 'final', wordCount: 6100 },
  beat: {
    content: [
      '### 本章事件',
      '陆沉舟和小九在搜查逼近时从灯棚退到水渠口。',
      '',
      '### 人物目标',
      '陆沉舟要保住账图。',
      '',
      '### 核心冲突',
      '巡天司搜查压近。',
      '',
      '### 外部压力',
      '追兵封街。',
      '',
      '### 代价或损失',
      '他隐瞒伤势，小九误会他不信任自己。',
      '',
      '### 不可逆变化',
      '小九要求拿走半张账图。',
      '',
      '### 结尾交接',
      '两人撤到水渠铁栅前。'
    ].join('\n'),
    beatPlanSource: 'ai_generated'
  },
  beatPlanFields: {},
  content: [
    '巡天司搜查从街口压来，陆沉舟拉着小九撤进灯棚后。',
    '他嘴上说没事，却把黑纹藏进袖子，小九停了一下，没有追问。',
    '两人钻向水渠，追兵的脚步声一直在后面，半张账图被小九抢先收走。'
  ].join('\n')
}))

assert.equal(inferredOnlyChapters[0].persistedHumanityFields.length, 0)
assert.equal(inferredOnlyChapters[0].derivedHumanityFields.length, 0)
assert.ok(inferredOnlyChapters[0].inferredHumanitySignals.length > 0)
assert.ok(inferredOnlyChapters[0].missingHumanityFields.includes('protagonistImmediateWant'))

const comparison = summarizeRerun(inferredOnlyChapters, {}, {
  rangeStart: 26,
  rangeEnd: 30,
  stateWarnings: [{ chapterNum: 27, status: 'rejected', reason: 'hard_conflict' }]
})

assert.equal(
  comparison.emotionalAnchors.verdict,
  '正文信号显示改善，但机制落盘未验证',
  'inferred signals must not be reported as persisted mechanism success'
)
assert.equal(comparison.mechanismFieldPersistence.chaptersWithPersistedOrDerivedEmotionRelation, 0)
assert.ok(comparison.stateWarnings.length >= 1, 'rejected setting candidates should be surfaced')

const chase = classifyChaseLoop(inferredOnlyChapters)
assert.notEqual(chase.status, 'chaseLoopResolved')
assert.notEqual(chase.status, 'resolved')
assert.ok(['reduced', 'still_dominant', 'chaseLoopReduced', 'chaseLoopStillDominant'].includes(chase.status))

console.log('story humanity conservative verdict contract passed')

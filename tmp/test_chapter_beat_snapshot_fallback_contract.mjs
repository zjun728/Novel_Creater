import assert from 'node:assert/strict'

import { buildLocalChapterBeatPlanFallback } from '../frontend/src/prompts/chapter.js'
import { validateBeatPlanProgressionGate } from '../frontend/src/quality/writingQualityScoring.js'

const fallback = buildLocalChapterBeatPlanFallback({
  chapterNum: 1,
  blockStageSnapshot: {
    blockGoal: '陆沉舟发现亡父名现星账，决定私下查证真相。',
    entryState: '陆沉舟在雨夜当铺清账，身份是被除名星吏。',
    stagePurpose: '清账发现亡父名现星账。',
    stageAction: '雨夜当铺清账，星账新页出现死去三年的父亲姓名及一笔异常债务。',
    stageChoice: '陆沉舟决定私下查阅详情，不声张。',
    stageCostOrConsequence: '触发星账反震，当铺账房出现灵脉波动，引起巡天司注意。',
    mainPressure: '巡天司的监视与追击，星账每次使用必须支付即时代价。',
    nextStageSuggestion: '纪九以情报为饵接触陆沉舟，追兵封锁当铺。'
  }
}, 1, '')

assert.match(fallback, /雨夜当铺/)
assert.match(fallback, /亡父名现星账|父亲姓名/)
assert.doesNotMatch(fallback, /下一章必须/)
assert.doesNotMatch(fallback, /最近章节没有明显高频循环/)
assert.ok(fallback.length >= 500 && fallback.length <= 1300)
assert.equal(validateBeatPlanProgressionGate(fallback, { chapterNum: 1 }).passed, true)

const compactSnapshotFallback = buildLocalChapterBeatPlanFallback({
  chapterNum: 1,
  blockStageSnapshot: {
    blockGoal: '觉醒星账，查出父亲旧案第一条线索，获得通行证决定南下',
    entryState: '被逐巡天司，无名籍，流落边城靠打杂为生',
    stagePurpose: '意外触账',
    stageAction: '当铺清账时发现亡父名字出现在新账，强行查账触动星账',
    stageChoice: '支付代价追溯来源',
    stageCostOrConsequence: '失去一段少年记忆',
    mainPressure: '巡天司下层追杀魏长史，每次查账付出记忆代价',
    nextStageSuggestion: '掌握星账初解，取得南疆通行证，启程南下追查矿脉',
    unresolvedQuestions: [
      '父亲名字为何出现在新账',
      '星账选择陆沉舟的原因',
      '南疆矿脉与父亲案关联'
    ]
  }
}, 1, '')

assert.match(compactSnapshotFallback, /当铺清账/)
assert.match(compactSnapshotFallback, /失去一段少年记忆/)
assert.ok(compactSnapshotFallback.length >= 500 && compactSnapshotFallback.length <= 1300)
assert.equal(validateBeatPlanProgressionGate(compactSnapshotFallback, { chapterNum: 1 }).passed, true)

console.log('chapter beat snapshot fallback contract tests passed')

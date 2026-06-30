import assert from 'node:assert/strict'
import { enforceStageContinuationSettlement } from '../frontend/src/utils/storyBlockStageSettlement.js'

const currentStage = {
  id: 'stage-2',
  purpose: '陆沉舟误判取物人的真实意图',
  sceneOrAction: '错误信任线人后被反制',
  choice: '救小九还是保住星账',
  costOrConsequence: '小九处境恶化，星账代价加剧'
}

const futureStage = {
  id: 'stage-3',
  purpose: '第三密栈反向设局',
  sceneOrAction: '用假账页试探缺指男人',
  choice: '主动布局还是继续逃离',
  costOrConsequence: '让商盟误以为星账已经失控'
}

const untouchedFutureStage = {
  id: 'stage-4',
  purpose: '徐正清身份线索转入商盟规则',
  sceneOrAction: '去商盟外档核验徐正清旧账',
  choice: '公开求证还是私下交易',
  costOrConsequence: '巡天司开始怀疑陆沉舟背后有人'
}

const settled = enforceStageContinuationSettlement({
  decision: 'continue_current_block',
  completedStageIds: ['stage-3', 'stage-4'],
  stageContinues: true,
  stageContinueReason: '本章好像已经顺手写到第三密栈和徐正清旧账。',
  reason: '本章好像已经顺手写到第三密栈和徐正清旧账。'
}, {
  chapterNum: 43,
  stageContinuationDepth: 2,
  previousOpenStageId: 'stage-2',
  blockStageSnapshot: {
    storyBlockId: 'block-scope',
    stageId: currentStage.id,
    stagePurpose: currentStage.purpose,
    stageAction: currentStage.sceneOrAction,
    stageChoice: currentStage.choice,
    stageCostOrConsequence: currentStage.costOrConsequence
  },
  storyBlock: {
    id: 'block-scope',
    stagePlan: [currentStage, futureStage, untouchedFutureStage]
  },
  finalizedSummary: [
    '陆沉舟误信线人，低估缺指男人，结果被反制设伏。',
    '小九被绑成交换筹码，星账黑纹裂开，使用次数到极限。',
    '他在纸条上看到第三密栈和假账页，意识到后续可能要反向设局，但本章没有真正执行。'
  ].join(''),
  chapterEnding: '缺指男人要求他用星账换小九。',
  settingChanges: [
    { entityName: '小九', evidence: '小九被绑，关系代价已经发生' },
    { entityName: '星账', evidence: '星账代价到达极限' }
  ]
})

assert.equal(settled.stageContinues, false)
assert.equal(settled.settlementDecision, 'completed_by_equivalent_story_function')
assert.deepEqual(settled.completedStageIds, ['stage-2'])
assert.equal(settled.equivalentCompletionScope, 'current_stage_only')
assert.equal(settled.futureStageTouched, true)
assert.equal(settled.futureStageOverClosed, false)
assert.equal(settled.needsFutureStageReplan, true)
assert.equal(settled.replanRemainingStages, true)
assert.ok(settled.futureStageEvidence.some(item => /stage-3|第三密栈|假账页|反向设局/.test(item)))

console.log('story block equivalent completion scope contract passed')

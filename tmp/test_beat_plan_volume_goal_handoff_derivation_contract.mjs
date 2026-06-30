import assert from 'node:assert/strict'

import { validateBeatPlanProgressionGate } from '../frontend/src/quality/writingQualityScoring.js'

const chapter10BeatPlan = `### 本章事件
陆沉舟从松林逃出后被追兵紧逼，冒险搭上顺风马车前往星荒城；途中遇土匪拦路，他利用星账面页上的债务记录谎称自己为债主，虚张声势吓退土匪，但星账外形被一名曾是商盟探子的土匪记住，暴露了行踪。

### 人物目标
陆沉舟必须在体力耗尽和伤口失血的情况下甩开追兵，以最快速度抵达星荒城并打探西凉矿山位置；他冒险搭乘马车，试图用信息资产而非武力化解危机。

### 核心冲突
追兵紧咬不放，土匪首领怀疑他是巡天司密探意图搜身；车夫担心惹祸催促下车；使用星账查询父亲位置将永久丧失关键记忆，且暴露星账增加追踪风险。

### 外部压力
土匪中有人曾是商盟外围探子，认出星账特征计划将情报卖给巡天司；车夫在镇口发现巡天司设卡盘查，暗示陆沉舟已陷入危险境地。

### 代价或损失
陆沉舟为获取父亲最后出现地点，选择用星账查询，代价是永久失去母亲教他的第一首童谣旋律；星账使用后轻微发热，外形被土匪记住，增加了被追踪隐患。

### 不可逆变化
陆沉舟通过星账确认父亲陆望舒三个月前曾出现在星荒城西凉矿山乙七号巷道入口，但代价是情感锚点断裂，他永远失去了关于母亲童谣的记忆片段。

### 结尾交接
陆沉舟获得父亲关键线索，但星账暴露，追兵和商盟可能已掌握其行踪；他必须在被包围前潜入西凉矿山，而星账的代价警告他不可继续轻易使用。`

const storyContext = {
  chapterNum: 10,
  nearTurnDecisionCard: {
    currentVolumeGoal: '推动旧线索、敌方压力、主线压力、家族真相，离开局部编号结构。',
    requiredChange: '从局部编号结构切回主线压力。',
    numberedSequenceStatus: ''
  },
  volumeStage: {
    coreGoal: '查明父亲陆望舒在星荒城西凉矿山留下的线索，并确认星账代价与追兵来源。',
    mainConflict: '巡天司、商盟、土匪探子和星账代价同时逼迫陆沉舟暴露行踪。'
  },
  blockStageSnapshot: {
    stagePurpose: '抵达星荒城，寻找西凉矿山乙七号巷道。',
    stageAction: '陆沉舟在追兵压力下前往星荒城，并设法确认西凉矿山入口。',
    stageChoice: '是否冒险使用星账确认父亲地点，承担记忆代价和暴露风险。',
    stageCostOrConsequence: '失去母亲童谣记忆，星账形状被敌方记住。',
    exitTarget: '陆沉舟潜入西凉矿山，追查父亲在乙七号巷道留下的线索。'
  }
}

const chapter10Quality = validateBeatPlanProgressionGate(chapter10BeatPlan, storyContext)
assert.equal(
  chapter10Quality.passed,
  true,
  `chapter 10 concrete handoff must pass or warn, got ${chapter10Quality.issues.map(item => `${item.type}:${item.severity}`).join(', ')}`
)
assert.ok(
  !chapter10Quality.issues.some(item => item.type === 'volume_goal_handoff_missing' && ['major', 'critical', 'severe'].includes(String(item.severity))),
  'derived volume handoff must not become a hard blocker'
)
assert.ok(
  chapter10Quality.freshness?.volumeGoalHandoff?.derivedHandoffText,
  'quality diagnostics must record derived volume handoff evidence'
)
assert.ok(
  chapter10Quality.freshness?.volumeGoalHandoff?.matchedTerms?.length > 0,
  'quality diagnostics must include matched handoff terms'
)

const strictVolumeGoalContext = {
  ...storyContext,
  nearTurnDecisionCard: {
    currentVolumeGoal: '推动回收组真实身份、愿望交易所封锁名单、家族真相，离开局部编号结构。',
    requiredChange: '从局部编号结构切回主线压力。',
    numberedSequenceStatus: ''
  },
  volumeStage: {
    coreGoal: '推动回收组真实身份与愿望交易所封锁名单浮出水面。',
    mainConflict: '愿望交易所回收组继续压迫主角。'
  }
}
const strictQuality = validateBeatPlanProgressionGate(chapter10BeatPlan, strictVolumeGoalContext)
assert.equal(
  strictQuality.passed,
  true,
  `derived handoff must downgrade missing volume goal to warning, got ${strictQuality.issues.map(item => `${item.type}:${item.severity}`).join(', ')}`
)
assert.ok(
  strictQuality.issues.some(item => item.type === 'volume_goal_handoff_missing_downgraded' && item.severity === 'warning'),
  'missing explicit volume handoff should be downgraded to a warning when concrete derived evidence exists'
)
assert.equal(strictQuality.freshness?.volumeGoalHandoff?.missing, false)
assert.equal(strictQuality.freshness?.volumeGoalHandoff?.derived, true)

const emptyLoopBeatPlan = `### 本章事件
陆沉舟继续进入十号门，观察里面的旧画面，理解星账规则。

### 人物目标
陆沉舟想继续弄清楚规则。

### 核心冲突
他必须在继续看下一个空间和继续理解规则之间选择。

### 外部压力
空间里继续出现旧画面。

### 代价或损失
他感到疲惫。

### 不可逆变化
他对规则有了更深理解，局势变化，认知变化。

### 结尾交接
他准备继续去看下一个房间。`

const emptyLoopQuality = validateBeatPlanProgressionGate(emptyLoopBeatPlan, storyContext)
assert.equal(emptyLoopQuality.passed, false, 'true empty numbered loop must still fail')
assert.ok(
  emptyLoopQuality.issues.some(item => ['volume_goal_handoff_missing', 'abstract_irreversible_change', 'loop_exit_missing'].includes(item.type)),
  'true empty loop should fail through the quality gate'
)

console.log('beat plan volume goal handoff derivation contract tests passed')

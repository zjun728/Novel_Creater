import { formatProseRhythmAnalysis } from '../utils/proseRhythmGuard.js'
import {
  buildAntiLoopPlanningBrief,
  buildBeatPlanProgressionGateBrief,
  buildGenerationQualityBrief,
  buildProseRhythmRepairBrief
} from '../quality/writingQualityPrompt.js'
import {
  analyzeMultiChapterNarrativeProgression,
  extractNarrativeTermStats,
  filterNarrativeEvidenceLabels
} from '../quality/writingQualityScoring.js'
import {
  cleanGeneratedChapterTitle as selectDomainGeneratedChapterTitle,
  collectChapterTitleMaterials,
  deriveFallbackChapterTitle as deriveDomainFallbackChapterTitle,
  evaluateChapterTitlePolicy as evaluateDomainChapterTitlePolicy,
  getChapterTitleQuality as getDomainChapterTitleQuality,
  isChapterTitleDuplicate as isDomainChapterTitleDuplicate,
  isDefaultChapterTitle as isDomainDefaultChapterTitle,
  normalizeChapterTitleKey as normalizeDomainChapterTitleKey
} from '../domain/chapter-title/index.js'
import {
  buildNarrativeVoiceContractV2,
  formatNarrativeVoiceContractForPrompt
} from '../utils/narrativeVoiceContract.js'
import {
  buildSceneExecutionCard,
  formatSceneExecutionCardForPrompt
} from '../utils/sceneExecutionContract.js'

/**
 * 章节生成 Prompt
 */

function hasText(value) {
  return value !== undefined && value !== null && String(value).trim() !== ''
}

const BEAT_PLAN_PLACEHOLDER_PATTERN = /^(?:未填写|空|待补充|TODO|TBD|略|暂无|无|不详|待定|N\/A|NA|null|none)[。.!！?？\s]*$/i
const DERIVED_BEAT_PLAN_PLACEHOLDER_PATTERN = /(待补充|未填写|TODO|TBD|略|推进剧情|当前故事块目标|一次明确选择|外部压力逼近|追兵、规则或地点秩序进入场景|身份暴露、线索受损|身体或记忆付出代价|下一阶段行动|可继续写的追击压力|已付出可见代价)/i
const DERIVED_BEAT_PLAN_REQUIRED_SNAPSHOT_FIELDS = [
  'storyBlockId',
  'stageId',
  'blockGoal',
  'stagePurpose',
  'stageAction',
  'stageChoice',
  'stageCostOrConsequence'
]

export const BEAT_PLAN_SOURCES = Object.freeze({
  aiGenerated: 'ai_generated',
  aiRepaired: 'ai_repaired',
  derivedFromStoryBlock: 'derived_from_story_block',
  localSafetyRequiresReview: 'local_safety_requires_review'
})

export function isBeatPlanPlaceholder(value) {
  const text = String(value ?? '').trim()
  if (!text) return false
  return BEAT_PLAN_PLACEHOLDER_PATTERN.test(text)
}

function isDerivedBeatPlanPlaceholder(value) {
  const text = String(value ?? '').trim()
  if (!text) return true
  return isBeatPlanPlaceholder(text) || DERIVED_BEAT_PLAN_PLACEHOLDER_PATTERN.test(text)
}

function hasConcreteBeatPlanText(value) {
  return hasText(value) && !isBeatPlanPlaceholder(value)
}

function unique(values = []) {
  return [...new Set(values.filter(Boolean))]
}

function formatList(items) {
  if (!Array.isArray(items)) return hasText(items) ? String(items) : ''
  return items.filter(hasText).map(item => `- ${item}`).join('\n')
}

function formatChapterGoal(goal) {
  if (!goal) return ''
  if (typeof goal === 'string') return goal

  const lines = []
  if (goal.title) lines.push(`- 标题/阶段：${goal.title}`)
  if (goal.goal) lines.push(`- 本章要完成：${goal.goal}`)
  if (goal.conflict) lines.push(`- 核心冲突：${goal.conflict}`)
  if (goal.turn) lines.push(`- 转折：${goal.turn}`)
  if (goal.emotionalBeat) lines.push(`- 情绪节拍：${goal.emotionalBeat}`)
  return lines.join('\n')
}

function formatNearOutline(outline) {
  if (!Array.isArray(outline)) return hasText(outline) ? String(outline) : ''
  return outline.map(o => {
    const parts = [
      o.title,
      o.goal,
      o.conflict ? `冲突：${o.conflict}` : '',
      o.turn ? `转折：${o.turn}` : '',
      o.emotionalBeat ? `情绪：${o.emotionalBeat}` : ''
    ].filter(hasText)
    return `- 第${o.chapterNum || '?'}章：${parts.join('；')}`
  }).join('\n')
}

function formatCharacters(characters) {
  if (!Array.isArray(characters)) return hasText(characters) ? String(characters) : ''

  return characters.map(c => {
    const hardState = c.hardState || {}
    const softState = c.softState || {}
    const trustLabel = c.trustLabel || (c.trustLevel && c.trustLevel !== 'trusted' ? ` [trustLevel=${c.trustLevel}]` : '')
    const lines = [`### ${c.name || '未命名角色'}（${c.role || '配角'}）${trustLabel}`]
    if (c.personality) lines.push(`- 性格：${c.personality}`)
    if (c.desire) lines.push(`- 欲望：${c.desire}`)
    if (c.fear) lines.push(`- 恐惧：${c.fear}`)
    if (c.location || hardState.location) lines.push(`- 当前位置：${c.location || hardState.location}`)
    if (c.physicalStatus || hardState.physicalStatus) lines.push(`- 身体状态：${c.physicalStatus || hardState.physicalStatus}`)
    if (c.emotion || softState.emotion) lines.push(`- 当前情绪：${c.emotion || softState.emotion}`)
    if (c.currentDesire || softState.currentDesire) lines.push(`- 当前欲望：${c.currentDesire || softState.currentDesire}`)
    return lines.join('\n')
  }).join('\n\n')
}

function formatPlotThreads(threads) {
  if (!Array.isArray(threads)) return hasText(threads) ? String(threads) : ''
  return threads
    .filter(t => t.status === 'planted' || t.status === 'developing')
    .map(t => `- ${t.title}：${t.content}（状态：${t.status}）`)
    .join('\n')
}

function formatChapterBeatPlan(plan) {
  if (!plan) return ''
  if (typeof plan === 'string') return plan.trim()
  if (Array.isArray(plan)) {
    return plan
      .filter(hasText)
      .map((beat, index) => {
        if (typeof beat === 'string') return `${index + 1}. ${beat}`
        const label = beat.type || beat.label || `节拍 ${index + 1}`
        const content = beat.content || beat.description || beat.goal || ''
        const turn = beat.turn ? ` 转折：${beat.turn}` : ''
        return `${index + 1}. [${label}] ${content}${turn}`
      })
      .join('\n')
  }
  return JSON.stringify(plan, null, 2)
}

function formatSeedContext(seed) {
  if (!seed) return ''
  if (typeof seed === 'string') return seed.trim()

  const lines = []
  if (seed.genre) lines.push(`- 题材：${seed.genre}`)
  if (seed.logline) lines.push(`- 一句话：${seed.logline}`)
  if (seed.protagonist) lines.push(`- 主角：${seed.protagonist}`)
  if (seed.desire) lines.push(`- 主角欲望：${seed.desire}`)
  if (seed.coreConflict) lines.push(`- 核心冲突：${seed.coreConflict}`)
  if (seed.worldPressure) lines.push(`- 世界压力：${seed.worldPressure}`)
  if (seed.openingHook) lines.push(`- 开局钩子：${seed.openingHook}`)
  if (seed.styleTarget) lines.push(`- 风格目标：${seed.styleTarget}`)
  if (seed.differentiation) lines.push(`- 差异化：${seed.differentiation}`)
  return lines.join('\n')
}

function formatSequenceRules(rules) {
  if (!rules) return ''
  if (typeof rules === 'string') return rules.trim()
  if (!Array.isArray(rules)) return JSON.stringify(rules, null, 2)
  return rules.filter(hasText).map(rule => `- ${rule}`).join('\n')
}

function formatRecentChapterEndings(endings) {
  if (!endings) return ''
  if (typeof endings === 'string') return endings.trim()
  if (!Array.isArray(endings)) return JSON.stringify(endings, null, 2)

  return endings
    .map((item, index) => {
      if (typeof item === 'string') return `- 最近第 ${index + 1} 段结尾：${item.trim()}`
      const chapterNum = item.chapterNum || item.chapter_num || item.num || '?'
      const ending = item.ending || item.content || item.text || item.summary || ''
      return hasText(ending) ? `- 第 ${chapterNum} 章结尾事实：${formatDraftContinuityText(ending, 360)}` : ''
    })
    .filter(hasText)
    .join('\n')
}

function normalizeRecentChaptersForTurnCard(context = {}) {
  const byChapter = new Map()
  const add = (item = {}) => {
    const chapterNum = Number(item.chapterNum || item.chapter_num || item.num || 0)
    const key = chapterNum || byChapter.size + 1
    const existing = byChapter.get(key) || { chapterNum: chapterNum || key }
    byChapter.set(key, {
      ...existing,
      ...item,
      chapterNum: chapterNum || existing.chapterNum || key
    })
  }

  if (Array.isArray(context.recentChapters)) {
    context.recentChapters.forEach(add)
  }
  if (Array.isArray(context.recentSummaries)) {
    context.recentSummaries.forEach(item => add({
      chapterNum: item.chapterNum || item.chapter_num,
      summary: item.summary || item.content || item.text || ''
    }))
  }
  if (Array.isArray(context.recentChapterEndings)) {
    context.recentChapterEndings.forEach(item => add({
      chapterNum: item.chapterNum || item.chapter_num,
      ending: item.ending || item.content || item.text || ''
    }))
  }

  return [...byChapter.values()]
    .sort((a, b) => Number(a.chapterNum || 0) - Number(b.chapterNum || 0))
    .slice(-5)
    .map(item => ({
      chapterNum: item.chapterNum,
      title: item.title || '',
      summary: item.summary || '',
      opening: item.opening || '',
      ending: item.ending || '',
      content: item.content || '',
      beatPlan: item.beatPlan || item.outline || ''
    }))
}

function labelsFromTermItems(items = [], limit = 5) {
  return (Array.isArray(items) ? items : [])
    .map(item => typeof item === 'string' ? item : item?.label || item?.key || '')
    .filter(hasText)
    .slice(0, limit)
}

function inferCurrentGoalForTurnCard(context = {}) {
  const chapterGoal = formatChapterGoal(context.chapterGoal)
  if (chapterGoal) return compactFallbackText(chapterGoal, 180)
  if (Array.isArray(context.nearOutline)) {
    const chapterNum = Number(context.chapterNum || 0)
    const current = context.nearOutline.find(item => Number(item?.chapterNum || item?.chapter_num || 0) === chapterNum)
      || context.nearOutline[0]
    const text = [current?.title, current?.goal, current?.conflict, current?.turn].filter(hasText).join('；')
    if (text) return compactFallbackText(text, 180)
  }
  return compactFallbackText(context.volumeStage?.coreGoal || context.volumeStage?.stageSummary || context.volumeStage?.mainConflict, 180)
    || '承接当前卷目标，完成一个读者能复述的真实事件。'
}

function inferCurrentVolumeGoalForTurnCard(context = {}) {
  return compactFallbackText([
    context.volumeStage?.coreGoal,
    context.volumeStage?.mainConflict,
    context.currentVolume?.goal,
    context.currentVolume?.mainConflict
  ].filter(hasText).join('；'), 220)
}

function inferVolumeGoalGapForTurnCard(context = {}, recentChapters = []) {
  const volumeGoal = inferCurrentVolumeGoalForTurnCard(context)
  if (!volumeGoal) return ''
  const recentText = recentChapters
    .map(item => [item.summary, item.ending, item.beatPlan].filter(hasText).join(' '))
    .join(' ')
  const numberedFlowCount = (recentText.match(/(?:进入|打开|走进|推门).{0,12}(?:[0-9一二三四五六七八九十百千万两零〇]+)号(?:门|房间|空间|档案|画布|凭证)?/g) || []).length
  const unresolved = Array.isArray(context.volumeStage?.unresolvedItems)
    ? context.volumeStage.unresolvedItems.map(formatStageItem).join('；')
    : context.volumeStage?.unresolvedItems
  if (numberedFlowCount >= 2) {
    return compactFallbackText(`最近章节停在局部编号结构，当前卷目标还差“${volumeGoal}”的可见推进；下一章需要从局部编号结构切回主线缺口：${unresolved || volumeGoal}`, 220)
  }
  return compactFallbackText(`当前卷目标缺口：${unresolved || volumeGoal}。下一章至少推进其中一个可验证结果。`, 220)
}

const NUMBERED_SEQUENCE_BREAK_OPTIONS = [
  '合并编号序列',
  '跳过编号流程',
  '规则失效',
  '敌方打断',
  '切到现实地点',
  '关系背叛',
  '目标改变',
  '阶段性结论'
]

function countRecentNumberedScenePatterns(recentChapters = []) {
  const numberedPattern = /(?:进入|打开|走进|推门|触发).{0,18}(?:[0-9一二三四五六七八九十百千万两零〇]+)号(?:门|房间|空间|档案|画布|凭证|卡|柜|箱)?/g
  const observePattern = /看见|看到|旁观|记忆|愿望|画面|记录|读出|解释|展示/
  const choicePattern = /选择|决定|拒绝|触碰|交出|换取|承认/
  const exitPattern = /离开|出来|走出|回到|准备进入|去看/
  return (Array.isArray(recentChapters) ? recentChapters : [])
    .map(item => [item.title, item.summary, item.opening, item.ending, item.content, item.beatPlan].filter(hasText).join('\n'))
    .filter(text => {
      const hasNumbered = numberedPattern.test(text)
      numberedPattern.lastIndex = 0
      return hasNumbered &&
        observePattern.test(text) &&
        choicePattern.test(text) &&
        exitPattern.test(text)
    })
    .length
}

function inferHandoffTargetForTurnCard(context = {}) {
  if (context.volumeStage?.handoffPoint) return compactFallbackText(context.volumeStage.handoffPoint, 180)
  if (Array.isArray(context.nearOutline)) {
    const chapterNum = Number(context.chapterNum || 0)
    const next = context.nearOutline.find(item => Number(item?.chapterNum || item?.chapter_num || 0) === chapterNum + 1)
    const text = [next?.title, next?.goal, next?.conflict, next?.turn].filter(hasText).join('；')
    if (text) return compactFallbackText(text, 180)
  }
  return '交接到具体动作未完成、关系变化、物件状态改变或下一章问题。'
}

export function buildNearTurnDecisionCard(context = {}) {
  if (context.nearTurnDecisionCard && typeof context.nearTurnDecisionCard === 'object') {
    return context.nearTurnDecisionCard
  }
  const recentChapters = normalizeRecentChaptersForTurnCard(context)
  const combinedRecentText = recentChapters
    .map(item => [item.title, item.summary, item.opening, item.ending, item.content, item.beatPlan].filter(hasText).join('\n'))
    .join('\n\n')
  const multi = recentChapters.length >= 2 ? analyzeMultiChapterNarrativeProgression(recentChapters) : null
  const fallbackStats = combinedRecentText ? extractNarrativeTermStats(combinedRecentText, { minCount: 2, actionMinCount: 1, limit: 8 }) : null
  const termFilterOptions = {
    source: combinedRecentText,
    characterNames: context.characterNames || context.coreCharacterNames || context.protagonistNames || []
  }
  const repeatedObjects = filterNarrativeEvidenceLabels(
    labelsFromTermItems(multi?.recent5RepeatedObjects?.length ? multi.recent5RepeatedObjects : fallbackStats?.objects),
    { ...termFilterOptions, category: 'object' }
  ).slice(0, 5)
  const repeatedActions = filterNarrativeEvidenceLabels(
    labelsFromTermItems(multi?.recent5RepeatedActions?.length ? multi.recent5RepeatedActions : fallbackStats?.actions),
    { ...termFilterOptions, category: 'action' }
  ).slice(0, 5)
  const repeatedConcepts = filterNarrativeEvidenceLabels(
    labelsFromTermItems(multi?.recent5RepeatedConcepts?.length ? multi.recent5RepeatedConcepts : fallbackStats?.concepts),
    { ...termFilterOptions, category: 'concept' }
  ).slice(0, 5)
  const repeatedObjectText = repeatedObjects.length ? repeatedObjects.join('、') : '最近章节的同类物象或状态'
  const repeatedActionText = repeatedActions.length ? repeatedActions.join('、') : '观察、确认、理解等低行动动作'
  const currentGoal = inferCurrentGoalForTurnCard(context)
  const currentVolumeGoal = inferCurrentVolumeGoalForTurnCard(context)
  const volumeGoalGap = inferVolumeGoalGapForTurnCard(context, recentChapters)
  const stagnationPoint = repeatedObjects.length || repeatedActions.length || repeatedConcepts.length
    ? `最近章节容易停在“${[repeatedObjectText, repeatedActionText, repeatedConcepts.join('、')].filter(hasText).join(' / ')}”的循环里。`
    : '最近章节没有明显高频循环，但下一章仍需给出可见事件增量。'
  const requiredChange = `下一章必须至少引入一个明确转向：新地点、具体人物行动、新敌我态势、外部压力、关系摩擦、旧线索阶段性结论、道具失效或规则证伪。`
  const forbiddenWriting = `禁止继续围绕${repeatedObjectText}反复${repeatedActionText}；不要把“更理解、更清楚、又变化”当作剧情推进。`
  const requiredPlotIncrement = `让“${currentGoal}”通过一次具体行动出现可见阻力、代价和不可逆结果；同时推进卷目标缺口“${volumeGoalGap || currentVolumeGoal || '当前卷目标'}”。`
  const handoffTarget = inferHandoffTargetForTurnCard(context)
  const numberedSequenceCount = countRecentNumberedScenePatterns(recentChapters)
  const numberedSequenceStatus = numberedSequenceCount >= 3 ? 'must_break' : (numberedSequenceCount >= 2 ? 'watch' : 'none')
  const requiredNumberedSequenceBreaks = numberedSequenceStatus === 'must_break' ? NUMBERED_SEQUENCE_BREAK_OPTIONS : []
  const numberedBreakRequirement = numberedSequenceStatus === 'must_break'
    ? `最近 ${numberedSequenceCount} 章已经连续使用编号场景流程；下一章必须选择一种处理：${requiredNumberedSequenceBreaks.join('、')}。禁止继续“进入编号对象 -> 观看/感知 -> 选择 -> 离开”。`
    : ''

  return {
    recentChapterNums: recentChapters.map(item => item.chapterNum).filter(Boolean),
    repeatedObjects,
    repeatedActions,
    repeatedConcepts,
    currentVolumeGoal,
    volumeGoalGap,
    currentGoal,
    stagnationPoint,
    requiredChange: numberedBreakRequirement ? `${requiredChange} ${numberedBreakRequirement}` : requiredChange,
    forbiddenWriting: numberedBreakRequirement ? `${forbiddenWriting}；${numberedBreakRequirement}` : forbiddenWriting,
    requiredPlotIncrement,
    numberedSequenceStatus,
    numberedSequenceCount,
    requiredNumberedSequenceBreaks,
    handoffTarget
  }
}

export function formatNearTurnDecisionCard(card = null) {
  if (!card) return ''
  const repeatedObjects = labelsFromTermItems(card.repeatedObjects).join('、') || '无明显高频物象'
  const repeatedActions = labelsFromTermItems(card.repeatedActions).join('、') || '无明显高频动作'
  const repeatedConcepts = labelsFromTermItems(card.repeatedConcepts).join('、') || '无明显高频抽象概念'
  const numberedSequenceLine = card.numberedSequenceStatus === 'must_break'
    ? `12. 编号序列终止/反转：最近 ${card.numberedSequenceCount || 3} 章已形成编号场景循环；本章必须选择：${labelsFromTermItems(card.requiredNumberedSequenceBreaks).join('、') || NUMBERED_SEQUENCE_BREAK_OPTIONS.join('、')}；禁止继续“进入编号对象 -> 观看/感知 -> 选择 -> 离开”。`
    : ''
  return [
    `1. 最近重复物象：${repeatedObjects}`,
    `2. 最近重复动作：${repeatedActions}`,
    `3. 最近重复抽象概念：${repeatedConcepts}`,
    `4. 当前主线目标：${card.currentGoal || '未识别'}`,
    `5. 当前卷目标：${card.currentVolumeGoal || '未识别'}`,
    `6. 当前卷目标缺口：${card.volumeGoalGap || '未识别'}`,
    `7. 当前停滞点：${card.stagnationPoint || '未识别'}`,
    `8. 下一章必须引入的变化：${card.requiredChange || '至少一个具体转向'}`,
    `9. 下一章禁止继续的写法：${card.forbiddenWriting || '禁止重复最近章节的物象/动作/概念循环'}`,
    `10. 下一章必须完成的剧情增量：${card.requiredPlotIncrement || '完成可复述真实事件'}`,
    `11. 下一章结尾应交接到哪里：${card.handoffTarget || '交接到具体动作、关系、物件状态或下一章问题'}`,
    numberedSequenceLine
  ].filter(Boolean).join('\n')
}

export const BEAT_PLAN_STRUCTURE_FIELDS = [
  { key: 'chapterEvent', label: '本章事件', required: true, markdownHeading: '本章事件' },
  { key: 'characterGoal', label: '人物目标', required: true, markdownHeading: '人物目标' },
  { key: 'coreConflict', label: '核心冲突', required: true, markdownHeading: '核心冲突' },
  { key: 'externalPressure', label: '外部压力', required: true, markdownHeading: '外部压力' },
  { key: 'costOrLoss', label: '代价或损失', required: true, markdownHeading: '代价或损失' },
  { key: 'irreversibleChange', label: '不可逆变化', required: true, markdownHeading: '不可逆变化' },
  { key: 'endingHandoff', label: '结尾交接', required: true, markdownHeading: '结尾交接' },
  { key: 'protagonistImmediateWant', label: '主角即时欲望', required: false, internal: true, markdownHeading: '主角即时欲望' },
  { key: 'emotionalAnchor', label: '情绪锚点', required: false, internal: true, markdownHeading: '情绪锚点' },
  { key: 'misbeliefOrFear', label: '误解或恐惧', required: false, internal: true, markdownHeading: '误解或恐惧' },
  { key: 'relationshipDelta', label: '关系轻微变化', required: false, internal: true, markdownHeading: '关系轻微变化' },
  { key: 'stageAnswerForReader', label: '给读者的阶段答案', required: false, internal: true, markdownHeading: '给读者的阶段答案' },
  { key: 'entryScene', label: '场景入口', required: false, internal: true, markdownHeading: '场景入口' },
  { key: 'relationshipFriction', label: '关系摩擦', required: false, internal: true, markdownHeading: '关系摩擦' },
  { key: 'keyAction', label: '关键行动', required: false, internal: true, markdownHeading: '关键行动' },
  { key: 'loopExit', label: '如何离开上一循环', required: false, internal: true, markdownHeading: '本章离开上一循环的方式' },
  { key: 'volumeGoalHandoff', label: '如何接力当前卷目标', required: false, internal: true, markdownHeading: '本章推进卷目标缺口' },
  { key: 'unresolved', label: '暂不解决内容', required: false, internal: true, markdownHeading: '本章暂不解决内容' },
  { key: 'forbiddenContinuation', label: '本章禁止继续的重复模式', required: false, internal: true, markdownHeading: '本章禁止继续的重复模式' },
  { key: 'usedTurnDecision', label: '是否使用近景转向卡', required: false, internal: true },
  { key: 'breaksPattern', label: '本章打断了哪个重复模式', required: false, internal: true },
  { key: 'volumeGoalGap', label: '本章推进了哪个卷目标缺口', required: false, internal: true },
  { key: 'nextProgress', label: '本章下一步推进', required: false, internal: true }
]

export const BEAT_PLAN_HUMANITY_FIELD_KEYS = [
  'protagonistImmediateWant',
  'emotionalAnchor',
  'misbeliefOrFear',
  'relationshipDelta',
  'stageAnswerForReader'
]

const BEAT_PLAN_FIELD_ALIASES = {
  chapterEvent: ['chapterEvent', 'realEvent', 'event', '本章具体事件', '本章一句话事件', '本章真实事件', '本章真实发生的事件'],
  entryScene: ['entryScene', 'sceneEntry', '场景入口'],
  characterGoal: ['characterGoal', 'goal', '人物当前目标', '本章目标'],
  coreConflict: ['coreConflict', 'conflict', '本章核心冲突'],
  externalPressure: ['externalPressure', 'obstacle', '外部阻力'],
  relationshipFriction: ['relationshipFriction', '关系摩擦'],
  keyAction: ['keyAction', '关键行动'],
  costOrLoss: ['costOrLoss', 'cost', 'loss', '代价或损失'],
  irreversibleChange: ['irreversibleChange', 'irreversibleResult', '不可逆结果', '本章不可逆变化'],
  protagonistImmediateWant: ['protagonistImmediateWant', '主角即时欲望', '主角本章最想要什么'],
  emotionalAnchor: ['emotionalAnchor', '情绪锚点', '本章情绪锚点'],
  misbeliefOrFear: ['misbeliefOrFear', '误解或恐惧', '主角误解', '主角害怕', '嘴硬或不愿承认'],
  relationshipDelta: ['relationshipDelta', '关系轻微变化', '人物关系轻微变化'],
  stageAnswerForReader: ['stageAnswerForReader', '给读者的阶段答案', '阶段性答案'],
  loopExit: ['loopExit', 'breakLoop', '如何离开上一循环', '本章离开上一循环的方式'],
  volumeGoalHandoff: ['volumeGoalHandoff', 'volumeHandoff', '本章推进卷目标缺口', '如何接力当前卷目标'],
  endingHandoff: ['endingHandoff', 'handoff', '本章结尾交接点', '结尾交接点'],
  unresolved: ['unresolved', '本章暂不解决内容', '暂不解决内容'],
  forbiddenContinuation: ['forbiddenContinuation', '本章禁止继续的重复模式', '禁止继续的写法'],
  usedTurnDecision: ['usedTurnDecision', '是否使用近景转向卡'],
  breaksPattern: ['breaksPattern', '本章打断了哪个重复模式'],
  volumeGoalGap: ['volumeGoalGap', '本章推进了哪个卷目标缺口'],
  nextProgress: ['nextProgress', '本章下一步推进']
}

Object.assign(BEAT_PLAN_FIELD_ALIASES, {
  chapterEvent: [...BEAT_PLAN_FIELD_ALIASES.chapterEvent, '本章事件', '本章具体事件', '本章一句话事件', '本章真实事件', '本章真实发生的事件'],
  characterGoal: [...BEAT_PLAN_FIELD_ALIASES.characterGoal, '人物目标', '人物当前目标', '本章目标'],
  coreConflict: [...BEAT_PLAN_FIELD_ALIASES.coreConflict, '核心冲突', '本章核心冲突'],
  externalPressure: [...BEAT_PLAN_FIELD_ALIASES.externalPressure, '外部压力', '外部阻力'],
  costOrLoss: [...BEAT_PLAN_FIELD_ALIASES.costOrLoss, '代价或损失', '代价', '损失'],
  irreversibleChange: [...BEAT_PLAN_FIELD_ALIASES.irreversibleChange, '不可逆变化', '不可逆结果', '本章不可逆变化'],
  endingHandoff: [...BEAT_PLAN_FIELD_ALIASES.endingHandoff, '结尾交接', '本章结尾交接点', '结尾交接点']
})

function normalizeBeatPlanFieldValue(value) {
  if (Array.isArray(value)) return value.filter(hasText).join('；').trim()
  if (value && typeof value === 'object') return JSON.stringify(value)
  if (typeof value === 'boolean') return value
  return String(value || '').replace(/\s+/g, ' ').trim()
}

function extractJsonObjectText(text = '') {
  const source = String(text || '').trim()
    .replace(/^```(?:json)?/i, '')
    .replace(/```$/i, '')
    .trim()
  const start = source.indexOf('{')
  const end = source.lastIndexOf('}')
  if (start < 0 || end <= start) return ''
  return source.slice(start, end + 1)
}

function parseJsonBeatPlan(text = '') {
  const jsonText = extractJsonObjectText(text)
  if (!jsonText) return null
  try {
    const parsed = JSON.parse(jsonText)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : null
  } catch {
    return null
  }
}

function parseMarkdownBeatPlanSections(text = '') {
  const sections = splitBeatPlanSections(text)
  const parsed = {}
  for (const section of sections) {
    const heading = String(section.heading || '').trim()
    if (!heading) continue
    const body = section.lines.slice(1).join('\n').replace(/^[-*]\s*/gm, '').trim()
    for (const field of BEAT_PLAN_STRUCTURE_FIELDS) {
      const aliases = BEAT_PLAN_FIELD_ALIASES[field.key] || []
      if (aliases.some(alias => heading.includes(alias))) {
        parsed[field.key] = body
        break
      }
    }
  }
  return parsed
}

export function parseStructuredBeatPlan(input = '') {
  if (input && typeof input === 'object' && !Array.isArray(input)) {
    const out = {}
    for (const field of BEAT_PLAN_STRUCTURE_FIELDS) {
      for (const alias of BEAT_PLAN_FIELD_ALIASES[field.key] || [field.key]) {
        if (Object.prototype.hasOwnProperty.call(input, alias)) {
          out[field.key] = normalizeBeatPlanFieldValue(input[alias])
          break
        }
      }
    }
    return out
  }
  const source = String(input || '').trim()
  const parsedJson = parseJsonBeatPlan(source)
  if (parsedJson) return parseStructuredBeatPlan(parsedJson)
  return parseStructuredBeatPlan(parseMarkdownBeatPlanSections(source))
}

export function collectStructuredBeatPlanIssues(plan = {}, options = {}) {
  const normalized = parseStructuredBeatPlan(plan)
  const missingRequiredFields = BEAT_PLAN_STRUCTURE_FIELDS
    .filter(field => field.required && !hasText(normalized[field.key]))
    .map(field => field.key)
  const placeholderFields = BEAT_PLAN_STRUCTURE_FIELDS
    .filter(field => field.required && isBeatPlanPlaceholder(normalized[field.key]))
    .map(field => field.key)
  const toolingLeakFields = BEAT_PLAN_STRUCTURE_FIELDS
    .filter(field => hasText(normalized[field.key]) && containsBeatPlanToolingLeak(normalized[field.key]))
    .map(field => field.key)
  const issues = []
  if (missingRequiredFields.length) {
    issues.push({
      type: 'structured_beat_plan_missing_fields',
      severity: 'major',
      missingRequiredFields
    })
  }
  if (placeholderFields.length) {
    issues.push({
      type: 'structured_beat_plan_placeholder_fields',
      severity: 'major',
      placeholderFields
    })
  }
  if (toolingLeakFields.length) {
    issues.push({
      type: 'structured_beat_plan_tooling_leak',
      severity: 'major',
      toolingLeakFields,
      detail: '小纲字段含有 stage-x、读者复述、围绕、关系任务或机械交接等工具话术，需要改成自然剧情小纲。'
    })
  }
  const loopExitText = String(normalized.loopExit || '')
  const hasConcreteLoopExit = /离开|进入|转入|新地点|敌方|追击|主动出手|公开否认|证伪|不再作为|烧毁|失效|关系破裂|关系重组|打破|关闭|中断|跳切|合并|反转|封锁|切回|结束|停止|改道|现实|走廊|回收组|外部压力|打断/.test(loopExitText) &&
    !/继续(?:观察|触摸|确认|感受|理解)|又(?:观察|确认|理解)|仍然(?:观察|确认|理解)|更理解|更清楚/.test(loopExitText)
  if (hasText(normalized.loopExit) && !hasConcreteLoopExit) {
    issues.push({
      type: 'loop_exit_missing',
      severity: 'major',
      detail: 'loopExit 必须写出具体离场、打断、切回现实或关闭旧结构的动作。'
    })
  }
  const volumeEvidenceText = [
    normalized.volumeGoalHandoff,
    normalized.chapterEvent,
    normalized.coreConflict,
    normalized.externalPressure,
    normalized.costOrLoss,
    normalized.irreversibleChange,
    normalized.endingHandoff
  ].filter(hasConcreteBeatPlanText).join(' ')
  const hasConcreteVolumeHandoff = hasConcreteBeatPlanText(volumeEvidenceText) &&
    !/更理解|更清楚|继续探索|继续观察|继续确认|规则更完整|线索更清楚/.test(volumeEvidenceText)
  const volumeGoalHandoffStatus = hasConcreteVolumeHandoff ? 'pass' : 'fail'
  if (volumeGoalHandoffStatus === 'fail') {
    issues.push({
      type: 'volume_goal_handoff_missing',
      severity: 'major',
      detail: '结构化小纲缺少 volumeGoalHandoff。'
    })
  }
  const storyChanges = [
    normalized.chapterEvent,
    normalized.coreConflict,
    normalized.externalPressure,
    normalized.costOrLoss,
    normalized.irreversibleChange,
    normalized.endingHandoff,
    normalized.breaksPattern,
    normalized.nextProgress
  ].filter(hasConcreteBeatPlanText).join(' ')
  const turnDecisionStatus = !options.nearTurnDecisionCard || hasText(storyChanges)
    ? 'pass'
    : 'fail'
  if (turnDecisionStatus === 'fail' && options.nearTurnDecisionCard) {
    issues.push({
      type: 'turn_decision_card_not_applied',
      severity: 'major',
      detail: '结构化小纲没有显式填写近景转向卡使用、打断模式、卷目标缺口和下一步推进。'
    })
  }
  return {
    missingRequiredFields,
    placeholderFields,
    toolingLeakFields,
    volumeGoalHandoffStatus,
    turnDecisionStatus,
    issues
  }
}

export function compactStructuredBeatPlanFields(plan = {}, options = {}) {
  const maxFieldChars = Number(options.maxFieldChars || 140)
  const normalized = parseStructuredBeatPlan(plan)
  const out = {}
  for (const field of BEAT_PLAN_STRUCTURE_FIELDS) {
    const value = normalized[field.key]
    if (typeof value === 'boolean') {
      out[field.key] = value
      continue
    }
    const text = String(value || '').replace(/\s+/g, ' ').trim()
    out[field.key] = text.length > maxFieldChars ? text.slice(0, maxFieldChars) : text
  }
  return out
}

export function formatStructuredBeatPlan(plan = {}) {
  const normalized = parseStructuredBeatPlan(plan)
  const line = key => normalizeBeatPlanFieldValue(normalized[key]) || '未填写'
  const optionalSection = (key, heading) => {
    const value = normalizeBeatPlanFieldValue(normalized[key])
    return value ? `\n\n### ${heading}\n${value}` : ''
  }
  return cleanChapterBeatPlanText(`
### 本章事件
${line('chapterEvent')}

### 人物目标
${line('characterGoal')}

### 核心冲突
${line('coreConflict')}

### 外部压力
${line('externalPressure')}

### 代价或损失
${line('costOrLoss')}

### 不可逆变化
${line('irreversibleChange')}

### 结尾交接
${line('endingHandoff')}
${optionalSection('protagonistImmediateWant', '主角即时欲望')}
${optionalSection('emotionalAnchor', '情绪锚点')}
${optionalSection('misbeliefOrFear', '误解或恐惧')}
${optionalSection('relationshipDelta', '关系轻微变化')}
${optionalSection('stageAnswerForReader', '给读者的阶段答案')}
  `)
}

function structuredBeatPlanJsonSchemaText() {
  const example = {}
  for (const field of BEAT_PLAN_STRUCTURE_FIELDS.filter(field => field.required && !field.internal)) {
    example[field.key] = field.key === 'usedTurnDecision' ? true : field.label
  }
  for (const field of BEAT_PLAN_STRUCTURE_FIELDS.filter(field =>
    ['protagonistImmediateWant', 'emotionalAnchor', 'misbeliefOrFear', 'relationshipDelta', 'stageAnswerForReader'].includes(field.key)
  )) {
    example[field.key] = field.label
  }
  return JSON.stringify(example, null, 2)
}

export function buildChapterBeatPlanRepairPrompt({
  chapterNum,
  originalBeatPlan = '',
  missingRequiredFields = [],
  previousIssues = [],
  nearTurnDecisionCard = null,
  volumeGoal = ''
} = {}) {
  const cardText = formatNearTurnDecisionCard(nearTurnDecisionCard)
  const issueLines = (previousIssues || []).map(item => {
    if (typeof item === 'string') return item
    const expectedTerms = Array.isArray(item.expectedTerms) ? `；expectedTerms=${item.expectedTerms.join('、')}` : ''
    const hitTerms = Array.isArray(item.hitTerms) ? `；hitTerms=${item.hitTerms.join('、')}` : ''
    return `${item.type || 'issue'}：${item.detail || ''}${expectedTerms}${hitTerms}`
  })
  const expectedVolumeTerms = unique((previousIssues || [])
    .flatMap(item => Array.isArray(item?.expectedTerms) ? item.expectedTerms : [])
    .map(item => String(item || '').trim())
    .filter(hasText))
  const missingStoryFields = (missingRequiredFields || [])
    .filter(key => BEAT_PLAN_STRUCTURE_FIELDS.some(field => field.key === key && field.required && !field.internal))
  return [
    `# 小纲故事修复：第 ${chapterNum || '?'} 章`,
    '目标不是补表格，而是让故事发生变化：让本章出现外部事件、人物行动、关系变化、代价或阶段性答案。',
    '尽量保留原小纲里已经具体的事件、人物目标和结尾交接；如果原小纲只是在旧结构里继续观察或确认，请把它改成可复述的事件。',
    '如果原小纲继续编号门/编号画布/编号凭证逐个观看，请用合并、跳切、反转、关闭序列、敌方打断、切到现实地点或规则失效打破。',
    '卷目标接力要落在本章发生的行动、证据、阻挠、误导、关系摩擦或代价上，不能只写“继续理解”“线索更清楚”。',
    expectedVolumeTerms.length ? `卷目标必须显式接上的关键词：${expectedVolumeTerms.join('、')}。` : '',
    '只输出合法 JSON，不要 Markdown，不要解释。',
    `需要补强的故事要素：${missingStoryFields.join(', ') || '无字段缺失，但需要让故事产生可见变化'}`,
    issueLines.length ? `上一轮问题：${issueLines.join('；')}` : '',
    volumeGoal ? `当前卷目标：${volumeGoal}` : '',
    cardText ? `近景转向卡：\n${cardText}` : '',
    `输出 JSON schema：\n${structuredBeatPlanJsonSchemaText()}`,
    `原小纲：\n${typeof originalBeatPlan === 'string' ? originalBeatPlan : JSON.stringify(originalBeatPlan, null, 2)}`
  ].filter(Boolean).join('\n\n')
}

export function buildChapterBeatPlanParseRetryPrompt({
  chapterNum,
  previousCandidate = '',
  contextBrief = ''
} = {}) {
  return [
    `# 第 ${chapterNum || '?'} 章小纲 JSON parse-retry`,
    '上一次小纲 JSON 被截断或解析失败。请重新输出同一章的小纲，不要写正文。',
    '只输出合法 JSON。不要 Markdown，不要解释，不要前后缀。',
    '只保留 7 个字段：chapterEvent、characterGoal、coreConflict、externalPressure、costOrLoss、irreversibleChange、endingHandoff。',
    '每字段 60-120 个中文字符以内；保留已出现的剧情事实，不扩写成正文段落。',
    `JSON schema：\n${structuredBeatPlanJsonSchemaText()}`,
    contextBrief ? `可用上下文：\n${contextBrief}` : '',
    `上一次候选内容（可能被截断，仅用于保持同一剧情）：\n${previousCandidate || ''}`
  ].filter(Boolean).join('\n\n')
}

export function buildChapterBeatPlanJsonRepairPrompt({
  chapterNum,
  candidateRaw = ''
} = {}) {
  return [
    `# 第 ${chapterNum || '?'} 章小纲 JSON 修复`,
    '下面的小纲候选是被截断或格式损坏的 JSON。',
    '只补全合法 JSON，不输出代码块、说明或前后缀。',
    '不允许新增剧情事实，不允许扩写正文；只能整理、截短、闭合和补齐已经出现或显然缺失的字段。',
    '只保留 7 个字段：chapterEvent、characterGoal、coreConflict、externalPressure、costOrLoss、irreversibleChange、endingHandoff。',
    '每字段 60-120 个中文字符以内。',
    `JSON schema：\n${structuredBeatPlanJsonSchemaText()}`,
    `待修复候选：\n${candidateRaw || ''}`
  ].filter(Boolean).join('\n\n')
}

export function buildChapterBeatPlanCompactionPrompt({
  chapterNum,
  beatPlan,
  contextBrief = '',
  attempt = 1,
  previousLength = 0
} = {}) {
  return [
    `请把第 ${chapterNum || '?'} 章小纲压缩为 700-1100 字，绝不能超过 1300 字。`,
    '这是字段保真压缩，不是重写剧情摘要；不要新增剧情，不要改变因果顺序，不要把两章容量塞进一章。',
    '先写“本章事件”：这一章到底发生了什么；然后保留人物目标、核心冲突、外部压力、代价或损失、不可逆变化和结尾交接。',
    '如果原小纲缺少故事要素，请在不新增剧情的前提下补成可执行事件；内容要具体，不能只写“更理解规则”“线索更清楚”。',
    '如果原小纲仍是编号门、编号凭证、编号档案、编号画布逐个观看，第三次编号结构必须合并、跳切、反转、升级或被外部压力打断。',
    '节拍控制在 4-6 条，保留本章核心目的、人物动机、关键选择、代价、结尾钩子、连续性自检和写作约束。',
    '必须保留时间线连续性、状态延续、道具来源、人物铺垫和伏笔铺垫的关键提醒，但用短句合并表达。',
    attempt > 1 ? `上一次压缩仍过长（${previousLength || '?'} 字符），请继续压缩，同时仍保留字段。` : '',
    contextBrief ? `上下文：\n${contextBrief}` : '',
    `原小纲：\n${beatPlan || ''}`
  ].filter(Boolean).join('\n\n')
}

const REQUIRED_BEAT_PLAN_SECTION_HEADINGS = [
  '本章具体事件',
  '本章真实事件',
  '本章推进卷目标缺口',
  '本章核心冲突',
  '本章不可逆变化',
  '本章离开上一循环的方式',
  '本章结尾交接点',
  '本章暂不解决内容'
]

const OPTIONAL_BEAT_PLAN_SECTION_HEADINGS = [
  '可发散空间',
  '写作提醒',
  '人味与节奏呼吸',
  '信息释放方式',
  '有效选择',
  '必须承接',
  '人物动机层',
  '本章节拍',
  '结尾钩子'
]

function splitBeatPlanSections(text = '') {
  const sections = []
  const lines = String(text || '').split(/\r?\n/)
  let current = { heading: '', lines: [] }
  for (const line of lines) {
    const match = line.match(/^\s{0,3}#{1,6}\s*(.+?)\s*$/)
    if (match) {
      if (current.heading || current.lines.length) sections.push(current)
      current = { heading: match[1].trim(), lines: [line.trim()] }
    } else {
      current.lines.push(line)
    }
  }
  if (current.heading || current.lines.length) sections.push(current)
  return sections
}

function normalizeSqueezedBeatPlan(text = '') {
  return String(text || '')
    .replace(/[ \t]+/g, ' ')
    .replace(/\n{3,}/g, '\n\n')
    .trim()
}

export function squeezeChapterBeatPlanText(text = '', options = {}) {
  const maxChars = Number(options.maxChars || 1300)
  const minChars = Number(options.minChars || 500)
  let source = normalizeSqueezedBeatPlan(text)
  if (source.length <= maxChars) return source

  const sections = splitBeatPlanSections(source)
  const isRequired = heading => REQUIRED_BEAT_PLAN_SECTION_HEADINGS.some(item => heading.includes(item))
  const isOptional = heading => OPTIONAL_BEAT_PLAN_SECTION_HEADINGS.some(item => heading.includes(item))

  const withoutOptional = sections
    .filter(section => isRequired(section.heading) || !isOptional(section.heading))
    .map(section => section.lines.join('\n').trim())
    .filter(Boolean)
    .join('\n\n')
  source = normalizeSqueezedBeatPlan(withoutOptional)
  if (source.length <= maxChars && source.length >= minChars) return source
  if (source.length < minChars) {
    let rebuilt = source
    for (const section of sections.filter(item => isOptional(item.heading))) {
      const body = section.lines.slice(1).join(' ').replace(/\s+/g, ' ').trim()
      const budget = Math.max(40, Math.min(140, maxChars - rebuilt.length - section.heading.length - 10))
      if (budget <= 40) break
      const candidate = normalizeSqueezedBeatPlan([
        rebuilt,
        `### ${section.heading}\n${body.slice(0, budget)}`
      ].filter(Boolean).join('\n\n'))
      if (candidate.length > maxChars) break
      rebuilt = candidate
      if (rebuilt.length >= minChars) return rebuilt
    }
    if (rebuilt.length >= minChars) return rebuilt
  }

  const shortened = splitBeatPlanSections(source)
    .map(section => {
      if (!section.heading) return section.lines.join('\n').trim()
      if (isRequired(section.heading)) return section.lines.join('\n').trim()
      const body = section.lines.slice(1).join(' ').replace(/\s+/g, ' ').trim()
      return [section.lines[0], body ? body.slice(0, 80) : ''].filter(Boolean).join('\n')
    })
    .filter(Boolean)
    .join('\n\n')
  source = normalizeSqueezedBeatPlan(shortened)
  if (source.length <= maxChars && source.length >= minChars) return source
  return source
}

function sanitizePromptInstructionText(value) {
  return String(value || '')
    .replace(/“?不是X[，,]是Y(?:\/而是Y)?”?/g, '模板化反差判断句')
    .replace(/“?感觉到”?/g, '内感知句')
}

export function formatDraftContinuityText(value, max = 520) {
  const text = String(value || '')
    .replace(/\s+/g, ' ')
    .replace(/不是[^。！？；\n]{0,24}(?:而是|是)[^。！？；\n]{0,24}/g, '上一章的判断句')
    .replace(/[他她它][^。！？；\n]{0,8}感(?:到|觉到)[^。！？；\n]{0,30}/g, '角色察觉到异常')
    .replace(/([^。！？；\s]{1,10})(?:在|从)[^。！？；\n]{0,18}(?:延伸|展开|断裂|形成)[^。！？；\n]{0,24}/g, '上一章的状态变化')
    .trim()
  return compactFallbackText(text, max)
}

function formatWordTarget(target) {
  if (!target?.target) return ''
  const sceneBudget = (() => {
    const words = Number(target.target || 0)
    if (words <= 2800) return '1-2 个'
    if (words <= 4200) return '2-3 个'
    if (words <= 6200) return '2-3 个'
    return '3-4 个'
  })()
  return [
    `- 源头控量：先把本章正文拆成 2-4 个核心场景；每个场景围绕一个明确目标、一次压力升级、一次信息揭示或一次选择代价。`,
    `- 输出优先落在 ${Math.max(target.min, target.target - 400)}-${Math.min(target.max, target.target + 1200)} 字；接近 ${target.max} 字时直接收束到小纲结尾，不补复盘、解释或下一轮感知。`,
    `- 本章只能完成本章小纲任务，不允许提前写后续章节内容；如果内容超量，减少场景数量，不要扩写解释、复盘、余波或下一章开场。`,
    `- 不可逆变化要落到关系变化、线索推进、地点变化、目标变化、代价兑现、敌我态势变化之一，并写成发生过程。`,
    `- 如果场景只是重复观察、重复确认、重复形成图案或围绕同一物象/同一状态打转，改成行动选择、代价兑现或新地点/新关系推进。`,
    `- 如果场景进入连续问答，第二轮之后必须用新动作、环境变化、关系摩擦或代价推进；不要让沉默、凝视、语气标签循环替代剧情。`,
    `- 建议围绕约 ${target.target} 字设计场景密度，优先落在 ${target.min}-${target.max} 字；这是写作节奏参考，不是硬性截断线。`,
    `- 本章容量预算：主场景建议控制在 ${sceneBudget}，每个主场景围绕一个明确压力、一次选择或一次信息揭示展开。`,
    `- 故事块和本章小纲优先；卷级方向参考里的后续内容不能提前写进本章。`,
    `- 本章写到小纲结尾钩子即停止；不得继续写钩子后的追查、复盘、余波、下一轮冲突或下一章开场。`,
    `- 质量优先级高于机械字数：不得为了压字数省略关键动作、情绪转折、人物反应、因果交代或章节钩子。`,
    `- 如果内容自然超量，先判断是否把两章容量塞进了一章；能拆则在自然断点把支线、解释、余波或下一轮冲突留到下一章。`,
    `- 如果明显超量，请减少支线、旁白、重复描写或低效对白；不要压掉关键动作、人物反应和因果交代。`,
    `- 如果当前章核心动作无法安全拆分，可以略高于建议范围；但应减少重复描写、低效对白、纯旁白解释和无效支线。`,
    `- 接近硬边界时，优先停在自然钩子或人物选择后的短暂停顿；不要为了补完余波继续扩写，也不要强行草草收尾或灌水。`,
    `- 硬边界参考：尽量不要低于 ${target.hardMin} 字，也不要超过 ${target.hardMax} 字；越界时优先调整场景容量，而不是扩成下一章。`
  ].join('\n')
}

function compactFallbackText(value, max = 180) {
  return String(value || '')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, max)
}

export function containsBeatPlanToolingLeak(text = '') {
  const source = String(text || '')
  return /第\s*\d+\s*章发生一件读者能复述的事/.test(source) ||
    /读者能复述的事/.test(source) ||
    /人物目标：围绕/.test(source) ||
    /围绕“[^”]+”/.test(source) ||
    /本章关系变化落在/.test(source) ||
    /不能只把配角当线索出口/.test(source) ||
    /下一阶段\s*[：:]\s*stage-[\dx]+/i.test(source) ||
    /主角要完成[\s\S]{0,80}并把结果接到/.test(source) ||
    /\bstage-(?:\d+|x)\b/i.test(source)
}

function cleanFallbackGoalText(value) {
  return sanitizePromptInstructionText(formatDraftContinuityText(value, 160))
    .replace(/^[-：:；;\s]+/, '')
    .replace(/^(本章一句话事件|本章一句话目标|本章要让读者看到什么变化|本章真实事件|读者能看见的)[：:\s-]*/, '')
    .replace(/^[-\s]*本章要完成[：:\s]*/, '')
    .replace(/###.*$/, '')
    .trim()
}

function extractFallbackGoalFromBeatText(text = '') {
  const source = String(text || '')
  const patterns = [
    /本章一句话事件\s*[-：:]*\s*([\s\S]*?)(?:###|\n#{1,6}|\n\s*[-*]\s*本章真实事件|本章真实事件|$)/,
    /本章要让读者看到什么变化[：:]\s*([\s\S]*?)(?:###|\n#{1,6}|\n\s*[-*]\s*本章真实事件|本章真实事件|$)/,
    /本章一句话目标\s*[-：:]*\s*([\s\S]*?)(?:###|\n#{1,6}|\n\s*[-*]\s*本章真实事件|本章真实事件|$)/,
    /本章真实事件\s*[-：:]*\s*([\s\S]*?)(?:###|\n#{1,6}|\n\s*[-*]\s*本章核心冲突|本章核心冲突|$)/
  ]
  for (const pattern of patterns) {
    const match = source.match(pattern)
    const cleaned = cleanFallbackGoalText(match?.[1] || '')
    if (cleaned) return cleaned
  }
  return cleanFallbackGoalText(source)
}

function inferFallbackGoal(context = {}, originalText = '') {
  const goal = formatChapterGoal(context.chapterGoal)
  if (goal) return cleanFallbackGoalText(goal)
  if (Array.isArray(context.nearOutline)) {
    const chapterNum = Number(context.chapterNum || 0)
    const matched = context.nearOutline.find(item => Number(item?.chapterNum || item?.chapter_num || 0) === chapterNum)
    const item = matched || context.nearOutline[0]
    const text = [item?.title, item?.goal, item?.conflict, item?.turn].filter(hasText).join('；')
    if (text) return cleanFallbackGoalText(text)
  }
  return extractFallbackGoalFromBeatText(originalText) || '承接上一章悬念，让主角在外部压力下做出改变后续走向的选择。'
}

function enrichLocalFallbackBeatPlan(plan = {}, context = {}) {
  const previousEnding = context.previousEnding || '上一章留下的即时悬念'
  const stagnationPoint = context.stagnationPoint || '最近章节的停滞点'
  const requiredChange = context.requiredChange || '新的外部压力、地点变化、关系摩擦或阶段性答案'
  const forbiddenWriting = context.forbiddenWriting || '继续原地观察、确认或理解'
  const handoffTarget = context.handoffTarget || '下一章可以承接的动作、关系或物件状态'
  const volumeGoal = context.volumeGoal || '当前卷目标'
  return {
    ...plan,
    chapterEvent: `${plan.chapterEvent || ''} 场景从“${previousEnding}”接上，人物不能停在“${stagnationPoint}”，本章要用一次可见行动把故事推向“${requiredChange}”。`,
    characterGoal: `${plan.characterGoal || ''} 目标要落到当场可做的选择：先争取证据、通行资格、证人配合或脱身机会，再把它接回“${volumeGoal}”。`,
    coreConflict: `${plan.coreConflict || ''} 阻力不是解释规则，而是有人、地点秩序、道具状态或敌方行动当场拦住他，逼他放弃一部分安全选择。`,
    externalPressure: `${plan.externalPressure || ''} 外部压力要进入场景：封锁、追击、误导、证人不配合、物件失效或旧线索被证伪，打断“${forbiddenWriting}”。`,
    costOrLoss: `${plan.costOrLoss || ''} 代价要有过程和残留：身份暴露、关系裂痕、线索损毁、记忆失效、地点被迫转移或敌我态势公开化。`,
    irreversibleChange: `${plan.irreversibleChange || ''} 变化必须让下一章无法回到原状态：关系、线索、地点、目标、代价或敌我态势至少一项被改写。`,
    endingHandoff: `${plan.endingHandoff || ''} 结尾停在“${handoffTarget}”，留下一个可继续写的动作、物件状态、关系裂口或追击压力。`
  }
}

function relationshipHintFromFallbackContext(context = {}, fallback = '') {
  const storyBlock = context.storyBlock || context.currentStoryBlock || context.block || {}
  const task = compactFallbackText(
    storyBlock.relationshipTask ||
    storyBlock.relationshipEndHint ||
    context.relationshipTask ||
    context.relationshipDelta ||
    fallback,
    120
  )
  const focus = compactFallbackText(storyBlock.relationshipFocus || context.relationshipFocus || '', 80)
  if (task && focus) return `${focus}因为“${task}”出现一次小变化。`
  if (task) return `陆沉舟和相关角色因为“${task}”出现一次能看见的态度变化。`
  return '陆沉舟和同行者因隐瞒、交易、救助或条件合作出现轻微变化。'
}

function humanityFallbackFields({
  stageChoice = '',
  stageCost = '',
  blockGoal = '',
  stageAction = '',
  mainPressure = '',
  nextStage = '',
  context = {},
  goal = '',
  requiredChange = '',
  handoffTarget = '',
  unresolved = ''
} = {}) {
  return {
    protagonistImmediateWant: compactFallbackText(
      stageChoice || goal || blockGoal || requiredChange || '先处理眼前危险，再保住能继续追查的证据或同伴。',
      120
    ),
    emotionalAnchor: compactFallbackText(
      stageCost
        ? `他在“${stageCost}”之后仍要强撑，情绪落在代价、父亲线索和不愿示弱之间。`
        : '他嘴上先处理正事，心里仍被父亲线索、失忆代价或同伴安危牵住。',
      140
    ),
    misbeliefOrFear: compactFallbackText(
      mainPressure
        ? `他怕“${mainPressure}”证明自己判断错了，于是会嘴硬、隐瞒或先做选择再解释。`
        : '他怕自己拖累别人或被父亲旧局牵着走，容易把真实担心藏成一句没事。',
      140
    ),
    relationshipDelta: compactFallbackText(
      relationshipHintFromFallbackContext(context, stageCost || requiredChange),
      140
    ),
    stageAnswerForReader: compactFallbackText(
      nextStage || handoffTarget || stageAction || unresolved || '本章至少确认一个具体去向、物件状态或关系条件，让读者知道这一段推进到哪里。',
      140
    )
  }
}

function normalizeStageReferenceText(value) {
  return String(value ?? '').replace(/\s+/g, '').trim().toLowerCase()
}

function isBareStageReference(value) {
  return /^stage-\d+(?:\b|[（(:：\s_-])/i.test(String(value ?? '').trim())
}

function stageReferenceLabel(value = '') {
  const text = String(value ?? '').trim()
  const parenMatch = text.match(/^stage-\d+\s*[（(]\s*([^）)]+)\s*[）)]\s*$/i)
  if (parenMatch?.[1]) return parenMatch[1].trim()
  const suffixMatch = text.match(/^stage-\d+\s*[-_:：]\s*(.+)$/i)
  if (suffixMatch?.[1]) return suffixMatch[1].trim()
  return ''
}

export function resolveMeaningfulHandoffSource(snapshot = {}) {
  const nextStageSuggestion = String(snapshot?.nextStageSuggestion ?? '').trim()
  const exitTarget = String(snapshot?.exitTarget ?? '').trim()
  const stageId = String(snapshot?.stageId ?? '').trim()
  const normalizedNext = normalizeStageReferenceText(nextStageSuggestion)
  const normalizedStageId = normalizeStageReferenceText(stageId)
  const nextStageLabel = stageReferenceLabel(nextStageSuggestion)
  const nextIsStagePointer = isBareStageReference(nextStageSuggestion) ||
    (normalizedNext && normalizedStageId && normalizedNext === normalizedStageId)

  if (nextStageLabel && !isDerivedBeatPlanPlaceholder(nextStageLabel)) {
    return {
      sourceField: 'nextStageSuggestion.label',
      value: nextStageLabel,
      rejectedNextStageSuggestion: nextStageSuggestion
    }
  }

  if (hasText(nextStageSuggestion) && !nextIsStagePointer && !isDerivedBeatPlanPlaceholder(nextStageSuggestion)) {
    return {
      sourceField: 'nextStageSuggestion',
      value: nextStageSuggestion,
      rejectedNextStageSuggestion: ''
    }
  }

  if (hasText(exitTarget) && !isDerivedBeatPlanPlaceholder(exitTarget)) {
    return {
      sourceField: 'exitTarget',
      value: exitTarget,
      rejectedNextStageSuggestion: nextIsStagePointer ? nextStageSuggestion : ''
    }
  }

  return {
    sourceField: '',
    value: '',
    rejectedNextStageSuggestion: nextIsStagePointer ? nextStageSuggestion : ''
  }
}

export function buildLocalChapterBeatPlanFallback(context = {}, chapterNum = context?.chapterNum, originalText = '') {
  const snapshot = context.blockStageSnapshot || context.stageSnapshot || null
  if (snapshot) {
    const stageAction = compactFallbackText(snapshot.stageAction || snapshot.sceneOrAction || '', 160)
    const stageChoice = compactFallbackText(snapshot.stageChoice || snapshot.choice || '', 100)
    const stageCost = compactFallbackText(snapshot.stageCostOrConsequence || snapshot.costOrConsequence || snapshot.consequence || '', 140)
    const blockGoal = compactFallbackText(snapshot.blockGoal || '', 150)
    const mainPressure = compactFallbackText(snapshot.mainPressure || '', 120)
    const handoffSource = resolveMeaningfulHandoffSource(snapshot)
    const nextStage = compactFallbackText(handoffSource.value || '', 120)
    const unresolved = compactFallbackText(
      Array.isArray(snapshot.unresolvedQuestions) ? snapshot.unresolvedQuestions.join('；') : snapshot.unresolvedQuestions,
      120
    )
    const humanityFields = humanityFallbackFields({
      stageChoice,
      stageCost,
      blockGoal,
      stageAction,
      mainPressure,
      nextStage,
      context,
      unresolved
    })
    const concretePlan = {
      chapterEvent: `${stageAction || blockGoal || '陆沉舟承接上一章压力，完成一次能改变局面的当场行动。'}。`,
      entryScene: `从当前故事块入场状态进入：${compactFallbackText(snapshot.entryState || '主角处在上一段剧情压力中', 120)}。`,
      characterGoal: `陆沉舟先做出“${stageChoice || '一次明确选择'}”，让这一步直接推动“${blockGoal || snapshot.stagePurpose || '当前故事块目标'}”。`,
      coreConflict: `核心冲突：${mainPressure || '外部压力逼近'}当场阻断主角，让他不能只观察或等待，必须行动。`,
      externalPressure: `外部压力：${mainPressure || '追兵、规则或地点秩序进入场景'}，打断安全选择并压缩行动时间。`,
      relationshipFriction: '相关人物带着利益、怀疑或追捕压力进入，不替作者解释设定。',
      keyAction: `关键行动：主角打开、查阅、验证或带走关键物件/线索，并做出“${stageChoice || '继续追查'}”的选择。`,
      costOrLoss: `代价或损失：${stageCost || '身份暴露、线索受损、身体或记忆付出代价'}。`,
      irreversibleChange: `不可逆变化：${stageCost || '代价已经兑现'}，并且主角获得无法装作没看见的线索，不能回到原来的安全状态。`,
      loopExit: `离开上一循环：从被动处境进入具体查证、逃离或对抗，故事转入“${nextStage || '下一阶段行动'}”。`,
      volumeGoalHandoff: `本章用“${blockGoal || stageAction || '当前阶段任务'}”接力当前卷目标。`,
      endingHandoff: nextStage || '以可继续写的追击压力、物件状态或新线索作为自然停顿点。',
      unresolved: unresolved || '保留故事块未解决问题，不提前揭开后续大谜底。',
      forbiddenContinuation: '不要把本章写成设定说明或规则表，不让人物只观察、理解、确认。',
      usedTurnDecision: true,
      breaksPattern: '用具体行动、外部压力和代价离开原地观察。',
      volumeGoalGap: blockGoal || snapshot.stagePurpose || '当前卷阶段目标',
      nextProgress: nextStage || stageAction || '进入下一阶段剧情',
      ...humanityFields
    }
    for (const maxFieldChars of [150, 130, 110, 92, 76]) {
      const formatted = formatStructuredBeatPlan(compactStructuredBeatPlanFields(concretePlan, { maxFieldChars }))
        .replace('### 本章具体事件', '### 本章一句话事件')
      if (formatted.length >= 500 && formatted.length <= 1300) return formatted
    }
    const formatted = formatStructuredBeatPlan(concretePlan)
      .replace('### 本章具体事件', '### 本章一句话事件')
    if (formatted.length <= 1300) {
      let padded = `${formatted}\n\n### 执行边界\n本章只写当前阶段：场景落在“${stageAction || blockGoal}”，人物选择落在“${stageChoice || '继续追查'}”，代价落在“${stageCost || '已付出可见代价'}”。结尾自然停在“${nextStage || '下一阶段行动'}”之前，不提前写完整个故事块。`
      if (padded.length < 500) {
        padded += `\n\n### 节拍安排\n1. 入场先让人物在“${compactFallbackText(snapshot.entryState || '当前压力', 80)}”中处理眼前事务，不跳到解释世界观。\n2. 中段让“${stageAction || blockGoal}”被外部压力打断，主角必须做出“${stageChoice || '继续追查'}”。\n3. 结果必须兑现“${stageCost || '可见代价'}”，并把未解问题留给后续章节。`
      }
      if (padded.length < 500) {
        padded += `\n\n### 信息边界\n只释放本章行动能证明的信息：${unresolved || '保留故事块未解决问题'}。读者要看到人物做事、受阻、选择和付出代价，而不是阅读规则表。`
      }
      return padded.length <= 1300 ? padded : formatted
    }
  }

  const goal = inferFallbackGoal({ ...context, chapterNum }, originalText)
  const turnCard = buildNearTurnDecisionCard({ ...context, chapterNum })
  const previousEnding = formatDraftContinuityText(context.previousChapterEnding, 42) || '上一章留下的即时悬念或人物状态'
  const volumeGoal = compactFallbackText(
    context.volumeStage?.coreGoal || context.volumeStage?.stageSummary || context.volumeStage?.mainConflict,
    56
  ) || '当前卷的阶段目标'
  const eventLine = compactFallbackText(turnCard?.requiredPlotIncrement || goal, 72)
  const requiredChange = compactFallbackText(turnCard?.requiredChange, 96) || '引入新地点、具体行动、外部压力、关系摩擦或旧线索阶段性结论之一。'
  const forbiddenWriting = compactFallbackText(turnCard?.forbiddenWriting, 86) || '不再围绕最近高频物象、低行动动作或抽象概念原地确认。'
  const stagnationPoint = compactFallbackText(turnCard?.stagnationPoint, 70) || '最近章节可能停在相似观察和确认中。'
  const handoffTarget = compactFallbackText(turnCard?.handoffTarget, 82) || '交接到具体动作、关系变化、物件状态或下一章问题。'
  const unresolved = compactFallbackText(
    Array.isArray(context.volumeStage?.unresolvedItems)
      ? context.volumeStage.unresolvedItems.map(formatStageItem).join('；')
      : context.volumeStage?.unresolvedItems,
    80
  ) || '后续章节要继续保留的悬念'
  const breakPattern = compactFallbackText([
    turnCard?.repeatedObjects?.join('、'),
    turnCard?.repeatedActions?.join('、'),
    turnCard?.repeatedConcepts?.join('、')
  ].filter(hasText).join(' / ') || stagnationPoint, 72)
  const volumeGoalGap = compactFallbackText(turnCard?.volumeGoalGap || volumeGoal, 96)
  const nextProgress = compactFallbackText(turnCard?.requiredPlotIncrement || eventLine, 110)
  const loopExit = compactFallbackText(`离开旧观察或编号结构，转入“${requiredChange}”，用可见行动、外部阻力和交接点“${handoffTarget}”打破停滞。`, 150)
  const humanityFields = humanityFallbackFields({
    context,
    goal,
    requiredChange,
    handoffTarget,
    stageAction: eventLine,
    stageCost: requiredChange,
    mainPressure: stagnationPoint,
    nextStage: handoffTarget,
    unresolved
  })
  const plan = {
    chapterEvent: eventLine || '陆沉舟承接上一章压力，做出一次会改变后续走向的当场选择。',
    entryScene: `从“${previousEnding}”进入，不跳时空，不重置人物状态。`,
    characterGoal: `只服务“${goal}”，并推进当前卷目标“${volumeGoal}”的一个可验证小结果。`,
    coreConflict: `${requiredChange} 这股阻力迫使主角行动，不能只靠观察、触摸、确认或理解。`,
    externalPressure: requiredChange,
    relationshipFriction: '配角、敌方或规则执行者必须带着顾虑、利益或拒绝参与，不只解释设定。',
    keyAction: '用进入、离开、打开、拒绝、交出、抢先、验证或公开表态推进事件。',
    costOrLoss: '选择造成资源损耗、关系裂痕、身份暴露、线索失效、地点改变或敌我态势变化之一。',
    irreversibleChange: '落到关系变化、线索推进、地点变化、目标变化、代价兑现或敌我态势变化之一，并无法原样退回。',
    loopExit,
    volumeGoalHandoff: `${volumeGoalGap}；本章用“${nextProgress}”接力当前卷目标。`,
    endingHandoff: handoffTarget,
    unresolved,
    forbiddenContinuation: forbiddenWriting,
    usedTurnDecision: true,
    breaksPattern: breakPattern,
    volumeGoalGap,
    nextProgress,
    ...humanityFields
  }
  const enrichedPlan = enrichLocalFallbackBeatPlan(plan, {
    previousEnding,
    stagnationPoint,
    requiredChange,
    forbiddenWriting,
    handoffTarget,
    volumeGoal
  })
  for (const maxFieldChars of [150, 130, 110, 92, 76, 64]) {
    const formatted = formatStructuredBeatPlan(compactStructuredBeatPlanFields(enrichedPlan, { maxFieldChars }))
      .replace('### 鏈珷鍏蜂綋浜嬩欢', '### 鏈珷涓€鍙ヨ瘽浜嬩欢')
      if (formatted.length >= 450 && formatted.length <= 1300) return formatted
  }
  for (const maxFieldChars of [110, 92, 76, 64]) {
    const formatted = formatStructuredBeatPlan(compactStructuredBeatPlanFields(plan, { maxFieldChars }))
      .replace('### 本章具体事件', '### 本章一句话事件')
    if (formatted.length <= 1300) return formatted
  }
  return formatStructuredBeatPlan(compactStructuredBeatPlanFields(plan, { maxFieldChars: 52 }))
    .replace('### 本章具体事件', '### 本章一句话事件')
}

function previewDerivedFieldValue(value, max = 90) {
  return String(value ?? '').replace(/\s+/g, ' ').trim().slice(0, max)
}

function buildStageSnapshotFieldDiagnostics(snapshot = {}) {
  const fields = [
    ...DERIVED_BEAT_PLAN_REQUIRED_SNAPSHOT_FIELDS,
    'mainPressure',
    'unresolvedQuestions',
    'nextStageSuggestion',
    'exitTarget'
  ]
  const diagnostics = {}
  for (const field of fields) {
    const value = field === 'unresolvedQuestions' && Array.isArray(snapshot[field])
      ? snapshot[field].join('；')
      : snapshot[field]
    diagnostics[field] = {
      present: hasText(value),
      placeholder: isDerivedBeatPlanPlaceholder(value),
      valuePreview: previewDerivedFieldValue(value)
    }
  }
  return diagnostics
}

function stageSnapshotDerivationIssues(snapshot = {}) {
  if (!snapshot || typeof snapshot !== 'object') return ['missing blockStageSnapshot']
  const fieldDiagnostics = buildStageSnapshotFieldDiagnostics(snapshot)
  const issues = []
  for (const field of DERIVED_BEAT_PLAN_REQUIRED_SNAPSHOT_FIELDS) {
    if (!fieldDiagnostics[field]?.present) issues.push(`missing ${field}`)
    else if (fieldDiagnostics[field]?.placeholder) issues.push(`placeholder ${field}`)
  }
  const meaningfulHandoff = resolveMeaningfulHandoffSource(snapshot)
  const pressureFields = ['mainPressure', 'unresolvedQuestions']
  const hasPressureText = pressureFields.some(field => fieldDiagnostics[field]?.present && !fieldDiagnostics[field]?.placeholder)
  if (!hasPressureText && !meaningfulHandoff.value) {
    issues.push('missing external pressure or ending handoff support')
  }
  return issues
}

function containsMeaningfulFragment(text = '', source = '') {
  const target = String(text || '')
  const fragments = String(source || '')
    .split(/[，,。；;、：:\s"“”()（）]+/)
    .map(item => item.trim())
    .filter(item => item.length >= 4)
  if (!fragments.length) return false
  return fragments.some(fragment => target.includes(fragment.slice(0, Math.min(fragment.length, 12))))
}

function derivedBeatPlanContentIssues(content = '', snapshot = {}, context = {}) {
  const parsed = parseStructuredBeatPlan(content)
  const structuredIssues = collectStructuredBeatPlanIssues(parsed, {
    nearTurnDecisionCard: context.nearTurnDecisionCard || null
  })
  const issues = []
  if (containsBeatPlanToolingLeak(content)) {
    issues.push('tooling phrasing leaked into derived beat plan')
  }
  for (const field of BEAT_PLAN_STRUCTURE_FIELDS.filter(field => field.required && !field.internal)) {
    const value = parsed[field.key]
    if (!hasText(value)) issues.push(`missing beatPlan.${field.key}`)
    else if (isDerivedBeatPlanPlaceholder(value)) issues.push(`placeholder beatPlan.${field.key}`)
  }
  if (structuredIssues.missingRequiredFields.length) {
    issues.push(`missing required fields: ${structuredIssues.missingRequiredFields.join(',')}`)
  }
  if (structuredIssues.placeholderFields?.length) {
    issues.push(`placeholder fields: ${structuredIssues.placeholderFields.join(',')}`)
  }
  if (structuredIssues.volumeGoalHandoffStatus === 'fail') {
    issues.push('missing concrete story change or volume handoff')
  }
  if (content.length < 500 || content.length > 1300) {
    issues.push(`invalid derived beat plan length: ${content.length}`)
  }
  const choiceText = `${parsed.characterGoal || ''} ${parsed.coreConflict || ''} ${parsed.keyAction || ''}`
  const costText = `${parsed.costOrLoss || ''} ${parsed.irreversibleChange || ''}`
  const handoffText = `${parsed.endingHandoff || ''} ${parsed.externalPressure || ''}`
  if (!containsMeaningfulFragment(choiceText, snapshot.stageChoice)) {
    issues.push('missing character choice from stageChoice')
  }
  if (!containsMeaningfulFragment(costText, snapshot.stageCostOrConsequence)) {
    issues.push('missing cost or irreversible consequence from stageCostOrConsequence')
  }
  const handoffSource = resolveMeaningfulHandoffSource(snapshot)
  if (!handoffSource.value) {
    issues.push('missing ending handoff from nextStageSuggestion or exitTarget')
  } else if (!containsMeaningfulFragment(handoffText, handoffSource.value)) {
    issues.push(`missing ending handoff from ${handoffSource.sourceField}`)
  }
  return issues
}

export function deriveChapterBeatPlanFromStoryBlock(context = {}, chapterNum = context?.chapterNum) {
  const snapshot = context.blockStageSnapshot || context.stageSnapshot || null
  const stageSnapshotFields = buildStageSnapshotFieldDiagnostics(snapshot || {})
  const snapshotIssues = stageSnapshotDerivationIssues(snapshot || {})
  if (snapshotIssues.length) {
    return {
      source: BEAT_PLAN_SOURCES.localSafetyRequiresReview,
      content: '',
      allowedToContinue: false,
      derivedFromStoryBlock: false,
      reason: '故事块阶段快照不完整，不能自动派生小纲。',
      issues: snapshotIssues,
      stageSnapshotFields
    }
  }

  const content = buildLocalChapterBeatPlanFallback({ ...context, chapterNum }, chapterNum, '')
  const contentIssues = derivedBeatPlanContentIssues(content, snapshot, context)
  if (contentIssues.length) {
    return {
      source: BEAT_PLAN_SOURCES.localSafetyRequiresReview,
      content,
      allowedToContinue: false,
      derivedFromStoryBlock: false,
      reason: '故事块阶段快照可用，但派生小纲未通过质量闸。',
      issues: contentIssues,
      stageSnapshotFields
    }
  }

  return {
    source: BEAT_PLAN_SOURCES.derivedFromStoryBlock,
    content,
    allowedToContinue: true,
    derivedFromStoryBlock: true,
    reason: 'AI 小纲连续空响应，已由 story block 阶段快照派生结构化小纲。',
    issues: [],
    stageSnapshotFields
  }
}

function formatVolumeStage(stage) {
  if (!stage) return ''
  if (typeof stage === 'string') return stage.trim()

  const lines = [
    `- 当前分卷：${stage.title || '未命名'}（${stage.chapterRange || '章节范围未定'}）`,
    stage.targetWords ? `- 目标字数：${stage.targetWords}` : '',
    stage.status ? `- 状态：${stage.status}` : '',
    stage.coreGoal ? `- 分卷目标：${stage.coreGoal}` : '',
    stage.mainConflict ? `- 分卷核心冲突：${stage.mainConflict}` : '',
    stage.keyCharacters?.length ? `- 分卷关键人物：${stage.keyCharacters.join('、')}` : '',
    stage.currentSummary ? `- 当前阶段短摘要：${stage.currentSummary}` : '',
    stage.foreshadowingPlan?.length ? `- 本卷伏笔计划：${stage.foreshadowingPlan.map(formatStageItem).join('；')}` : '',
    stage.unresolvedItems?.length ? `- 本卷暂不解决：${stage.unresolvedItems.map(formatStageItem).join('；')}` : '',
    stage.handoffPoint ? `- 本卷卷尾交接点：${stage.handoffPoint}` : '',
    stage.stageSummary ? `- 阶段总结：${stage.stageSummary}` : '',
    stage.completedBeats?.length ? `- 已完成节点：${stage.completedBeats.map(formatStageItem).join('；')}` : '',
    stage.openQuestions?.length ? `- 未解问题：${stage.openQuestions.map(formatStageItem).join('；')}` : '',
    stage.characterChanges?.length ? `- 人物变化：${stage.characterChanges.map(formatStageItem).join('；')}` : '',
    stage.settingChanges?.length ? `- 设定变化：${stage.settingChanges.map(formatStageItem).join('；')}` : '',
    stage.foreshadowingState?.length ? `- 伏笔状态：${stage.foreshadowingState.map(formatStageItem).join('；')}` : '',
    stage.handoffToNext?.length ? `- 接力点：${stage.handoffToNext.map(formatStageItem).join('；')}` : '',
    stage.continuityNotes?.length ? `- 连续性约束：${stage.continuityNotes.map(formatStageItem).join('；')}` : '',
    stage.auditAssessment ? `- 最近分卷审稿：${stage.auditAssessment}` : '',
    stage.auditIssues?.length ? `- 审稿待处理：${stage.auditIssues.map(formatStageItem).join('；')}` : '',
    stage.previousVolumeSummaries?.length
      ? `- 前卷摘要：${stage.previousVolumeSummaries.map(item => `${item.title || item.range}：${item.summary}`).join('；')}`
      : '',
    stage.nextVolumePreview
      ? `- 下一卷粗方向：${stage.nextVolumePreview.title || stage.nextVolumePreview.range || '后续卷'}；目标：${stage.nextVolumePreview.coreGoal || '未填写'}；冲突：${stage.nextVolumePreview.mainConflict || '未填写'}`
      : ''
  ].filter(hasText)

  return lines.join('\n')
}

function formatStageItem(item) {
  if (typeof item === 'string') return item
  if (!item || typeof item !== 'object') return ''
  return [
    item.name || item.title || item.label || '',
    item.state ? `状态=${item.state}` : '',
    item.change ? `变化=${item.change}` : '',
    item.description || '',
    item.suggestion ? `建议=${item.suggestion}` : '',
    item.note ? `说明=${item.note}` : '',
    item.nextUse ? `接力=${item.nextUse}` : ''
  ].filter(hasText).join('，')
}

export function cleanGeneratedChapterText(text) {
  if (!text) return ''

  const isOpeningMetaLine = (line) => {
    const trimmed = line.trim()
    if (!trimmed) return true
    const withoutMarkdown = trimmed.replace(/^#{1,6}\s*/, '').trim()
    if (/^(以下是|下面是|正文如下|候选稿|章节正文)[：:]/.test(withoutMarkdown)) return true
    if (/^(?:正文|章节正文|候选正文)\s*[：:]\s*$/.test(withoutMarkdown)) return true
    return /^第\s*[\d一二三四五六七八九十百千万零〇两]+\s*章(?:\s*[：:、.\-—·]\s*.*|\s+\S{1,16})?$/.test(withoutMarkdown)
  }

  const lines = String(text)
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .split('\n')

  let hasProseStarted = false
  return lines
    .filter(line => {
      const trimmed = line.trim()
      if (!hasProseStarted && isOpeningMetaLine(line)) return false
      if (trimmed) hasProseStarted = true
      return true
    })
    .join('\n')
    .replace(/\n{4,}/g, '\n\n\n')
    .trim()
}

const MULTI_VARIANT_LABELS = ['稳妥推进版', '强冲突版', '意外转向版']

function normalizeVariantLabel(label, index = 0) {
  const text = String(label || '').replace(/[《》【】[\]（）()#*：:\-—\s]/g, '')
  if (/稳妥|稳健|保守|自然推进/.test(text)) return '稳妥推进版'
  if (/强冲突|冲突|张力|加速|压迫/.test(text)) return '强冲突版'
  if (/意外|转向|惊喜|反转/.test(text)) return '意外转向版'
  return MULTI_VARIANT_LABELS[index] || `候选 ${index + 1}`
}

function cleanVariantContent(content) {
  return cleanGeneratedChapterText(
    String(content || '')
      .replace(/^\s*<<<END_VARIANT>>>\s*/i, '')
      .replace(/\s*<<<END_VARIANT>>>\s*$/i, '')
      .replace(/^\s*(?:正文|章节正文|候选正文)\s*[：:]\s*/i, '')
      .trim()
  )
}

function extractMarkerVariants(text) {
  const variants = []
  const markerRegex = /<<<VARIANT\s*[:：]\s*([^>\n]+?)\s*>>>\s*([\s\S]*?)(?=<<<VARIANT\s*[:：]|$)/gi
  let match = markerRegex.exec(text)
  while (match) {
    const content = cleanVariantContent(match[2])
    if (content) {
      variants.push({
        label: normalizeVariantLabel(match[1], variants.length),
        content
      })
    }
    match = markerRegex.exec(text)
  }
  return variants
}

function extractHeadingVariants(text) {
  const lines = String(text || '').split(/\r?\n/)
  const boundaries = []

  lines.forEach((line, index) => {
    const trimmed = line.trim()
    if (!trimmed || trimmed.length > 80) return

    const named = trimmed.match(/^(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?(?:[【\[(（《]?\s*)?(?:候选\s*)?(?:版本|方案|稿件)?\s*(?:一|二|三|1|2|3|A|B|C)?\s*[】\])）》、.．:：\-\s]*(稳妥推进版?|稳健推进版?|保守推进版?|自然推进版?|强冲突版?|冲突加强版?|张力加强版?|意外转向版?|惊喜转向版?|反转版?)(?:\*\*)?\s*(?:[：:\-—]\s*)?$/i)
    if (named) {
      boundaries.push({ lineIndex: index, label: named[1] })
      return
    }

    const numbered = trimmed.match(/^(?:#{1,6}\s*)?(?:[-*]\s*)?(?:\*\*)?(?:候选\s*)?(?:版本|方案|稿件)\s*(一|二|三|1|2|3|A|B|C)\s*(?:\*\*)?\s*[：:、.．\-\s]*(.*)$/i)
    if (numbered) {
      boundaries.push({ lineIndex: index, label: numbered[2] || numbered[1] })
    }
  })

  if (boundaries.length < 2) return []

  return boundaries.map((boundary, index) => {
    const next = boundaries[index + 1]
    const content = cleanVariantContent(lines.slice(boundary.lineIndex + 1, next?.lineIndex ?? lines.length).join('\n'))
    return {
      label: normalizeVariantLabel(boundary.label, index),
      content
    }
  }).filter(variant => variant.content)
}

function extractRuleSeparatedVariants(text) {
  const parts = String(text || '')
    .split(/\n\s*(?:-{3,}|={3,}|_{3,}|※{3,})\s*\n/g)
    .map(cleanVariantContent)
    .filter(content => content.length > 80)

  if (parts.length < 3) return []
  return parts.slice(0, 3).map((content, index) => ({
    label: MULTI_VARIANT_LABELS[index],
    content
  }))
}

export function parseMultiVariantText(text) {
  if (!text) return []

  const raw = String(text)
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .trim()

  const parsed = [
    extractMarkerVariants(raw),
    extractHeadingVariants(raw),
    extractRuleSeparatedVariants(raw)
  ].find(list => list.length >= 2)

  if (parsed?.length) {
    const seen = new Set()
    return parsed.filter(variant => {
      const key = `${variant.label}::${variant.content.slice(0, 120)}`
      if (seen.has(key)) return false
      seen.add(key)
      return true
    }).slice(0, 3)
  }

  const fallback = cleanVariantContent(raw)
  return fallback ? [{ label: '候选', content: fallback }] : []
}

export function cleanChapterBeatPlanText(text) {
  if (!text) return ''
  return String(text)
    .replace(/^\s*```(?:markdown|md|text|txt)?\s*/i, '')
    .replace(/\s*```\s*$/i, '')
    .trim()
}

export function isDefaultChapterTitle(title, chapterNum) {
  return isDomainDefaultChapterTitle(title, chapterNum)
}

export function formatChapterDisplayTitle(chapter = {}, options = {}) {
  const chapterNum = chapter.chapterNum || chapter.chapter_num || options.chapterNum || ''
  const numberTitle = chapterNum ? `第 ${chapterNum} 章` : '未命名章节'
  const title = String(chapter.title || '').trim()
  if (!title || isDefaultChapterTitle(title, chapterNum)) return numberTitle
  if (options.includeNumber === false) return title
  return `${numberTitle} · ${title}`
}

export function isChapterTitleDuplicate(title, context = {}) {
  return isDomainChapterTitleDuplicate(title, context)
}

export function evaluateChapterTitlePolicy(title, context = {}) {
  return evaluateDomainChapterTitlePolicy(title, context)
}

export function getChapterTitleQuality(title, context = {}) {
  return getDomainChapterTitleQuality(title, context)
}

export function cleanGeneratedChapterTitle(text, context = {}) {
  return selectDomainGeneratedChapterTitle(text, context)
}

export function collectPositiveChapterTitleCandidates(context = {}) {
  return collectChapterTitleMaterials(context)
}

export function deriveFallbackChapterTitle(context = {}) {
  return deriveDomainFallbackChapterTitle(context)
}

export function buildChapterTitleSystemPrompt() {
  return `你是一位长篇小说目录编辑，只负责给本章起一个真实网文目录里会出现的朴素章名。

章名原则：
- 章名是通俗易懂的目录标签，目标是让读者能回忆这一章。
- 不追求高级，不追求玄，不追求文学化；简单、直白、土一点的具体名词也可以。
- 优先 1-6 个汉字；少数自然标题可以 7-8 个汉字。
- 可以直接使用第一次出现的重要人物、功法、武器、组织、地点或道具名。
- 可以直接使用关键场景、房间、密室、账册、钥匙、纸条、证据等具体名词。
- 可以用当前章节的关键事件、突破境界、功法级别、法力等级、地点、人物、功法、武器、道具、组织、冲突或结果命名。
- 修仙/玄幻目录可以很朴素：交易、中毒、返回、出手、破禁、恶斗、试毒、谈判这类关键事件词可以直接用。
- 可以使用短并列或对抗结构，例如“甲与乙”“甲对乙”“符宝之秘”“剑诀之威”；连续斗法可用“恶斗（上）/（中）/（下）”。
- 候选优先级：核心地点/关键事件 > 关键物证/道具 > 突破境界/功法级别/法力等级 > 不可逆代价/行动后果 > 阶段答案/转折事件 > 人物/组织。
- 不要输出完整句子，不要输出剧情摘要，不要为了避重造奇怪词。
- 不要输出单字虚标题、代词短语、对白碎片、口语判断残片、方向/位置残片或为避重造出的怪词，例如“巡”“追”“别动”“谁派你来的”“不一定”“里面”“这边”。

输出 JSON，生成 3-5 个候选：
{
  "candidates": [
    {
      "title": "",
      "type": "event|place|person|skill|weapon|item|organization|conflict|result",
      "reason": ""
    }
  ]
}`
}

export function buildChapterTitlePrompt(context = {}) {
  const parts = [
    `请为第 ${context.chapterNum || '?'} 章生成 3-5 个章名候选。`
  ]

  const beatPlan = formatChapterBeatPlan(context.beatPlan)
  if (beatPlan) parts.push(`## 简短小纲\n${beatPlan}`)

  const existingTitles = [
    ...(Array.isArray(context.existingTitles) ? context.existingTitles : []),
    ...(Array.isArray(context.existingChapterTitles) ? context.existingChapterTitles : [])
  ]
    .map(normalizeDomainChapterTitleKey)
    .filter(Boolean)
    .slice(-5)
  if (existingTitles.length) {
    parts.push(`## 最近 5 个章名\n${existingTitles.join('、')}`)
  }

  const chapterGoal = formatChapterGoal(context.chapterGoal)
  if (chapterGoal) parts.push(`## 本章目标\n${chapterGoal}`)

  const content = String(context.content || '').trim()
  if (content) {
    const excerpt = content.length > 2800
      ? `${content.slice(0, 1800)}\n\n……\n\n${content.slice(-900)}`
      : content.slice(0, 2800)
    parts.push(`## 本章正文\n${excerpt}`)
  }

  parts.push(`请输出 JSON，格式必须是：
{
  "candidates": [
    { "title": "审问", "type": "event", "reason": "本章核心事件" }
  ]
}

候选要像真实网文目录：朴素、直接、好记。优先 1-6 字。
type 只能是 event|place|person|skill|weapon|item|organization|conflict|result。
可以直接使用第一次出现的重要人物、功法、武器、组织、地点、房间、密室或道具名。
可以直接用账册、钥匙、纸条、证据等具体物件；简单直白的具体名词优先于漂亮但虚的词。
可以直接用本章关键事件、突破境界、功法级别、法力等级取题，例如“审问”“筑基中期”“炼灵二重”“法力三重”。
修仙/玄幻目录可以用短事件词或短结构，例如“交易”“中毒”“破禁”“出手”“恶斗（上）”“符宝之秘”“剑诀之威”。
优先从本章核心地点、关键事件、关键物证、突破境界、不可逆代价、阶段答案里取题。
不要输出完整句子、单字虚标题、代词短语、对白碎片、方向/位置残片或剧情摘要，不要为了避重而造奇怪词。`)
  return parts.join('\n\n')
}

export function buildChapterSystemPrompt() {
  return `你是一位专业小说作者，擅长小说章节正文和长篇连载。

核心职责：
- 把已确认的世界规则、设定库、角色状态、上一章结尾和本章小纲当作创作边界。
- 在边界内写出具体场景：人物要行动、观察、误判、选择，并承担后果。
- 对话要符合角色身份和关系，不要让所有人说成同一种声音。
- 可以补充细节、对白、过渡和合理意外，但不能无解释推翻已有事实。
- 两难选择必须有效：不同选择必须带来不同损失、关系代价或未来后果，不能只是形式上的选择题。
- 写作标准是气质和方法，不是逐条打卡；明显模板句式和节奏问题会在生成后单独审稿或润色。
- 上下文里的历史正文只承接事实和状态，不作为句式、段落结构或意象链的模仿样本。

${buildGenerationQualityBrief()}

输出要求：
- 只输出小说正文，不输出标题、Markdown 标题、提纲、解释、创作说明或“以下是正文”等提示语。
- 不要输出“# 第N章”“第N章”“第十二章 章名”这类章节标题；章节标题由系统另行生成。
- 第一行直接进入正文叙事。
- 正文从本章小纲第一个节拍，或本章时间线最早的可写场景开始。
- 如果是第一章，从主角初始处境或创作种子的开局钩子开始。
- 按自然时间和因果顺序写场景，不要把结尾、设定说明、系统提示或任务奖励插入到开头。
- 系统提示、任务面板、弹窗等内容只能作为小说世界内角色实际看到或听到的内容出现。`
}

export function buildChapterPrompt(context) {
  const parts = []

  const bible = context.bible || {}
  const premise = bible.premise || context.premise
  const styleBible = bible.styleBible || context.styleBible
  const styleMethodBrief = context.styleMethodBrief || ''
  const styleStandardBrief = context.styleStandardBrief || bible.styleStandardBrief
  const worldRules = bible.worldRules || context.worldRules

  if (context.creativeBoundary) {
    parts.push(`## 本章创作边界摘要\n${context.creativeBoundary}`)
  } else {
    const boundaryLines = [
      premise ? `作品方向：${premise}` : '',
      worldRules ? `世界硬边界：${worldRules}` : ''
    ].filter(hasText)
    if (boundaryLines.length) parts.push(`## 本章创作边界摘要\n${boundaryLines.join('\n')}`)
  }

  const sceneExecutionCard = context.sceneExecutionCard || buildSceneExecutionCard(context)
  const sceneExecutionCardPrompt = formatSceneExecutionCardForPrompt(sceneExecutionCard)
  if (sceneExecutionCardPrompt) parts.push(sceneExecutionCardPrompt)

  const styleHints = [styleMethodBrief, !styleMethodBrief ? styleBible : '', !styleMethodBrief ? styleStandardBrief : '']
    .filter(hasText)
    .map(sanitizePromptInstructionText)
    .join('\n\n')
  const narrativeVoiceContract = context.narrativeVoiceContract || (styleHints
    ? buildNarrativeVoiceContractV2({
      styleBible,
      styleMethodBrief,
      styleStandardBrief
    })
    : null)
  const narrativeVoicePrompt = narrativeVoiceContract
    ? formatNarrativeVoiceContractForPrompt(narrativeVoiceContract)
    : ''
  if (narrativeVoicePrompt) {
    parts.push(narrativeVoicePrompt)
  } else if (styleHints) {
    parts.push(`## 写作气质\n${styleHints}`)
  }

  if (context.settingLibrary) parts.push(`## 关键设定边界\n${context.settingLibrary}`)
  if (context.recentSettingChanges) parts.push(`## 最近设定变化\n${context.recentSettingChanges}`)
  if (context.softCorrectionAims) parts.push(`## 软过渡提醒\n${context.softCorrectionAims}`)

  if (context.stateLedger) parts.push(`## 章节状态账本（硬状态优先）\n${context.stateLedger}`)

  const seedInfo = formatSeedContext(context.seed)
  if (seedInfo) parts.push(`## 创作种子\n${seedInfo}`)

  if (context.openingAnchor) {
    parts.push(`## 开局锚点（第一章优先执行）\n${context.openingAnchor}`)
  }

  const sequenceRules = formatSequenceRules(context.sequenceRules)
  if (sequenceRules) parts.push(`## 顺序控制\n${sequenceRules}`)

  const wordTarget = formatWordTarget(context.wordTarget)
  if (wordTarget) parts.push(`## 本章字数节奏（质量优先）\n${wordTarget}`)

  if (context.previousChapterEnding) {
    const previousEndingForDraft = formatDraftContinuityText(context.previousChapterEnding)
    parts.push(`## 上一章结尾事实（只承接，不仿写）
${previousEndingForDraft}

承接要求：
- 只承接事实、状态和未完成动作，不复用上一章的句式、意象链或段落结构。
- 如果上一章结尾停在内在感知或抽象判断，本章开场优先用外部动作、人物行动、声音、来客、环境变化打断旧状态，再进入本章小纲。
- 不要无提示地跳到全新地点、全新时间或无关日常；如必须转场，第一段要先完成上一章钩子的即时回应。
- 上一章结尾如果明显是未完成句、动作中断或危机未落地，本章开头必须先补足这个动作或危机，再进入本章小纲后续节拍。`)
  }

  const recentChapterEndings = formatRecentChapterEndings(context.recentChapterEndings)
  if (recentChapterEndings) {
    parts.push(`## 最近章节结尾（避免重复模板）
${recentChapterEndings}

结尾反复规避：
- 本章结尾不得复用最近章节的动作、意象或句式，不要连续用“抬头、转身、闭眼、握拳、走进黑暗、沉入黑暗、看天色、状态总结、内心独白收束”等模板。
- 结尾优先落在具体动作未完成、关系变化、物件状态、误判代价、选择余波或下一章问题上，不要只做抽象总结。
- 如果本章必须安静收束，也要换成具体的人物行为、物件细节或未被说出口的关系变化。`)
  }

  const volumeStage = formatVolumeStage(context.volumeStage)
  if (volumeStage) parts.push(`## 分卷阶段参考\n${volumeStage}`)

  const chapterGoal = formatChapterGoal(context.chapterGoal)
  if (chapterGoal) parts.push(`## 本章目标\n${chapterGoal}`)

  const nearOutline = formatNearOutline(context.nearOutline)
  if (nearOutline) parts.push(`## 近景大纲\n${nearOutline}`)

  if (context.currentVolume) {
    const volume = context.currentVolume
    parts.push(`## 当前卷\n- 标题：${volume.title || '无'}\n- 目标：${volume.goal || '无'}\n- 主要冲突：${volume.mainConflict || '无'}`)
  }

  if (context.recentSummaries?.length) {
    parts.push(`## 前情摘要
${context.recentSummaries.map(s => `- 第${s.chapterNum}章：${sanitizePromptInstructionText(s.summary)}`).join('\n')}

使用方式：
- 前情摘要只用于承接事实和状态，不作为句式或意象模仿样本。
- 如果最近几章反复围绕同类物象、动作或抽象判断推进，本章按已确认小纲换成新的行动、关系摩擦或场景压力。`)
  }

  if (context.recentFacts) {
    parts.push(`## 已确认事实\n${context.recentFacts}`)
  }

  const characters = formatCharacters(context.characters)
  if (characters) parts.push(`## 角色状态\n${characters}`)

  const plotThreads = formatPlotThreads(context.plotThreads)
  if (plotThreads) parts.push(`## 进行中的伏笔\n${plotThreads}`)

  if (context.relationships) {
    parts.push(`## 角色关系\n${context.relationships}`)
  }

  if (context.companionVoiceCards) {
    parts.push(`## 配角声音卡（短量参考，不是人物档案）\n${context.companionVoiceCards}`)
  }

  if (context.currentDraft) {
    parts.push(`## 当前草稿（请在此基础上续写或改写）\n${context.currentDraft}`)
  }

  parts.push(`## 硬连续性边界（不可违背）
- 时间线连续性：承接上一章留下的动作、危险、承诺、伤势、物品状态和情绪余波。
- 状态延续：身体状态不能突然跳变，断臂、伤口位置、毒素扩散、残肢长度、昏迷/清醒、濒死/恢复等必须沿用状态账本；如果本章改变，要写出直接原因、过程和代价。
- 规则数值延续：冷却时间、使用次数、距离、时长、等级、资源消耗、阵法规则等不能突然改口；如果需要例外，要先给出可见条件或代价。
- 势力连续性：宗门、家族、势力、城市、组织的存灭和立场不能无铺垫改变；不得突然宣告灭亡、叛变、掌控或结盟，除非前文已有证据或本章先写出发现过程。
- 道具来源：新出现的关键线索、道具、钱款、身份、法器、能力或情报，要有来源、交接、发现过程或代价。
- 人物铺垫：角色重大选择要来自当前欲望、压力、误判、利益牵引或关系变化。
- 伏笔铺垫：使用伏笔或回收线索时，要来自此前信息、误导解除或本章先行证据。
- 如果剧情需要改变既有状态，在正文中写清因果，后续会进入设定或记忆提取。`)

  parts.push(`## 本章容量与场景组织
- 生成前在心中把本章拆成 2-4 个核心场景，不输出场景清单。
- 每个场景围绕压力升级、信息露出、人物选择或代价发生推进。
- 本章只执行已确认小纲；内容偏多时收住支线、解释和余波，把后续冲突留到下一章。
- 正文负责把小纲里的变化写成可见经过、人物反应和后续影响。
- 如果上一章停在原地研究、触摸、观察或抽象判断，本章开场用外部打断或人物行动把角色带离旧状态。`)

  const beatPlan = formatChapterBeatPlan(context.beatPlan)
  if (beatPlan) {
    parts.push(`## 已确认本章小纲（优先执行）
${beatPlan}

执行要求：
- 按小纲的自然时间和因果顺序展开成正文。
- 第一幕对应小纲第一个可写场景，不先写后续结论、余波或复盘。
- 小纲是方向，不是模板；可以补充过渡、细节、对白和合理意外。
- 核心因果、人物目标和本章必须完成的剧情推进不能丢。
- 不要把小纲条目、编号或分析文字写进正文。`)
  }

  if (context.includeGenerationQualityBrief !== false) {
    parts.push(`${buildGenerationQualityBrief()}

这些是写作方向，不是检查清单；自然叙事优先，生成后会另行审稿和验收。`)
  }

  parts.push(`## 戏剧执行底线
- 每个主场景围绕一个可见压力展开：人物想要什么、怕失去什么、此刻为什么不能退。
- 对白必须推进冲突或遮掩真相；简短不等于平直，要有逼问、回避、潜台词或权力变化。
- 情绪转折要发生在场景里：由证据、错话、动作失败、关系代价或环境压力触发。
- 动作必须改变局势、暴露意图或留下代价；不要只写位移、握拳、沉默和机械反应。
- 描写只选最贴近压力的一两处表情、语气、身体反应或环境细节；少解释，不少临场感。
- 信息释放优先靠证据、误判解除、物件反应、失败尝试和人物选择，不用旁白替读者总结。
- 收束停在 Scene Execution Card 的停靠点，不提前写后续章真相、复盘或路线图。`)

  parts.push(`## 写作任务
请撰写第 ${context.chapterNum || '?'} 章正文。
${context.instruction ? `特别要求：${context.instruction}\n` : ''}如果没有可见小纲，请先在心中按自然时间顺序排好本章场景，但不要输出小纲。
请直接输出正文，不要输出标题、Markdown 标题、“# 第N章”“第N章”和解释。`)

  return parts.join('\n\n')
}

export function buildProseRhythmRepairSystemPrompt() {
  return `你是长篇小说正文节奏修订编辑。任务是修正文稿中过密的短句独立段落、机械化“不是X，是Y”句式、段首重复点名和碎片化分镜感。
硬性原则：
- 只做句式节奏和段落组织修订，不要新增剧情、人物、道具、设定、结论或伏笔。
- 保留原文事件顺序、人物选择、因果关系、对白含义、结尾钩子和已确认设定。
- 常规叙事段落应自然合并为 2-5 句，包含动作因果、感官连续、人物观察和情绪余波。
- 短句可以保留，但只能用于局部爆点、恐惧、断裂、反转或停顿；不要连续一行一句。
- 去掉高频 AI 腔：减少“不是X，是Y/而是Y”“某种”“像是又像是”等模板句。
- 避免感官打勾和说明书式数字；感官写一两处最关键的，数字和术语只保留会改变风险、选择、代价或误判的。
- 情绪不要只贴标签；用身体反应、动作迟疑、错话、沉默、回避和残留习惯承接。
- 可以补极少量生活痕迹或角色化细节来增加呼吸感，但不得新增剧情节点、设定结论或支线。
- 降低段首重复点名：不要连续多段都以同一个主角姓名开头；能承接时改用动作、物件、环境、感官、对白、心理余波或代词起段，必要时才点名。
- 输出完整正文，不要输出修改说明、标题、Markdown 小纲或 JSON。`
}

export function buildProseRhythmRepairPrompt({ chapterNum, content, analysis, beatPlan, context } = {}) {
  const report = formatProseRhythmAnalysis(analysis)
  const contextHints = [
    context?.styleBible ? `风格要求：${context.styleBible}` : '',
    context?.styleStandardBrief ? `题材/风格标准：\n${context.styleStandardBrief}` : '',
    context?.stateLedger ? `章节状态账本：\n${context.stateLedger}` : '',
    beatPlan ? `本章小纲：\n${formatChapterBeatPlan(beatPlan)}` : ''
  ].filter(hasText).join('\n\n')

  return `请对第 ${chapterNum || '?'} 章正文做一次“句式节奏修订”。

## 当前节奏问题
${report || '检测到连续短句或 AI 腔句式偏多。'}

## 修订目标
- ${buildProseRhythmRepairBrief().replace(/\n/g, '\n- ')}
- 保留全部剧情事实，不要删掉关键动作、选择、代价和结尾钩子。
- 把连续短句独立段落合并为自然叙事段落；常规推进段落尽量 2-5 句。
- 允许保留少量短句作为局部节奏点，但不要形成连续短句堆叠。
- 调整段首重复点名：避免多段连续或高频使用同一个角色姓名起段，改用动作承接、物件状态、环境变化、感官细节、对白或代词起段；不要因此改变视角归属。
- 修订后长度应接近原文，允许轻微浮动，不要大幅扩写或压缩。
- 只输出修订后的完整正文，不要输出解释。

${contextHints ? `## 参考约束\n${contextHints}\n\n` : ''}## 待修订正文
${content || ''}`
}

export function buildChapterBeatSystemPrompt() {
  return `你是一位长篇小说章节策划，负责在正式写正文前设计可执行的小纲。

你的任务是规划本章路线，不是写正文，也不是审稿。

规划原则：
- 小纲只锁定关键场景、冲突、信息释放和结尾钩子。
- 已确认事实、角色状态、上一章结尾和世界规则是边界。
- 第一条节拍必须是读者真正看到的开场场景。
- 给正文保留对白、细节、动作和临场发挥空间。

输出要求：
- 只输出章前小纲，不输出小说正文。
- 只输出合法 JSON，不要 Markdown，不要解释前缀。
- 必须保留 chapterEvent、characterGoal、coreConflict、externalPressure、costOrLoss、irreversibleChange、endingHandoff 这 7 个核心字段；可补充少量情绪锚点辅助字段。
- 小纲总长度控制在 500-900 字，节拍控制在 4-6 条。
- JSON 字段必须完整、具体、可校验；不要用“更理解规则”“线索更清楚”这类抽象话代替事件。`
}

function formatStoryBlockHumanityTaskForBeatPlan(block = null) {
  if (!block) return ''
  const nested = block.lockState?.storyHumanity || block.storyHumanity || {}
  const pick = (...keys) => {
    for (const key of keys) {
      const value = block[key] ?? nested[key]
      const text = String(value || '').replace(/\s+/g, ' ').trim()
      if (text) return text
    }
    return ''
  }
  const lines = [
    pick('relationshipFocus', 'relationship_focus') ? `relationshipFocus：${pick('relationshipFocus', 'relationship_focus')}` : '',
    pick('relationshipStart', 'relationship_start') ? `relationshipStart：${pick('relationshipStart', 'relationship_start')}` : '',
    pick('relationshipTask', 'relationship_task') ? `relationshipTask：${pick('relationshipTask', 'relationship_task')}` : '',
    pick('relationshipEndHint', 'relationship_end_hint', 'relationshipEnd') ? `relationshipEndHint：${pick('relationshipEndHint', 'relationship_end_hint', 'relationshipEnd')}` : '',
    pick('sceneVarietyHint', 'scene_variety_hint') ? `sceneVarietyHint：${pick('sceneVarietyHint', 'scene_variety_hint')}` : ''
  ].filter(Boolean)
  return lines.join('\n')
}

export function buildChapterBeatPrompt(context) {
  const parts = []
  const bible = context.bible || {}
  const premise = bible.premise || context.premise
  const styleBible = bible.styleBible || context.styleBible
  const styleStandardBrief = context.styleStandardBrief || bible.styleStandardBrief
  const worldRules = bible.worldRules || context.worldRules
  const forbiddenDirections = bible.forbiddenDirections || context.forbiddenDirections

  if (premise) parts.push(`## 作品定位\n${premise}`)
  if (styleBible || styleStandardBrief) {
    parts.push(`## 写作气质参考\n${[styleBible, styleStandardBrief].filter(hasText).join('\n\n')}`)
  }
  if (worldRules) parts.push(`## 世界规则（硬边界）\n${worldRules}`)
  if (context.settingLibrary) parts.push(`## 设定库摘要（硬边界）\n${context.settingLibrary}`)
  if (context.stateLedger) parts.push(`## 章节状态账本（硬边界）\n${context.stateLedger}`)

  if (context.previousChapterEnding) {
    parts.push(`## 上一章结尾（本章开场要承接）\n${context.previousChapterEnding}`)
  }

  const chapterGoal = formatChapterGoal(context.chapterGoal)
  if (chapterGoal) parts.push(`## 本章目标\n${chapterGoal}`)

  const storyBlockHumanityTask = formatStoryBlockHumanityTaskForBeatPlan(context.storyBlock)
  if (storyBlockHumanityTask) {
    parts.push(`## 故事块人物关系任务（轻量参考）\n${storyBlockHumanityTask}`)
  }

  const nearOutline = formatNearOutline(context.nearOutline)
  if (nearOutline) parts.push(`## 卷级方向参考（低优先级，nearOutline 仅供参考）\n${nearOutline}`)

  const nearTurnDecisionCard = buildNearTurnDecisionCard(context)
  const nearTurnDecisionCardText = formatNearTurnDecisionCard(nearTurnDecisionCard)
  if (nearTurnDecisionCardText) {
    parts.push(`## 近景转向决策卡（必须进入本章小纲，不是 QA 报告）\n${nearTurnDecisionCardText}`)
  }

  const volumeStage = formatVolumeStage(context.volumeStage)
  if (volumeStage) parts.push(`## 分卷阶段上下文\n${volumeStage}`)

  if (context.recentSummaries?.length) {
    parts.push(`## 前情摘要\n${context.recentSummaries.map(s => `- 第${s.chapterNum}章：${s.summary}`).join('\n')}`)
  }

  if (context.recentFacts) parts.push(`## 已确认事实\n${context.recentFacts}`)
  if (context.activeCorrectionTasks) parts.push(`## 未完成纠偏提醒（只处理会影响本章的硬问题）\n${context.activeCorrectionTasks}`)
  if (forbiddenDirections?.length) parts.push(`## 禁止方向\n${formatList(forbiddenDirections)}`)

  parts.push(buildAntiLoopPlanningBrief())
  parts.push(buildBeatPlanProgressionGateBrief())

  return `${parts.join('\n\n')}

## 规划任务
请为第 ${context.chapterNum || '?'} 章生成“正式写作前确认的小纲”。

${context.wordTarget?.target ? `本章按约 ${context.wordTarget.target} 字体量设计，优先服务 ${context.wordTarget.min}-${context.wordTarget.max} 字正文；不要规划成两章内容，把后续冲突或余波留到下一章。` : ''}

先回答：这一章到底发生了什么？小纲首先服务剧情，让正文能自然写出场景、选择、代价和交接。

规划提醒：
- 如果最近章节已经反复使用编号门、编号凭证、编号画布或编号档案，编号序列必须合并、跳过、反转、关闭，或让敌方/现实地点/关系变化打断它。
- 不要把一章写成“进入编号对象 -> 观看/感知 -> 选择 -> 离开”的重复流程；让外部压力、人物行动、关系摩擦或阶段性答案推动故事。
- 卷目标接力落在本章发生的证据、阻挠、追击、封锁、关系破裂、道具失效或代价兑现上。
- 可补充轻量人物锚点：protagonistImmediateWant、emotionalAnchor、misbeliefOrFear、relationshipDelta、stageAnswerForReader。它们帮助规划人物欲望、嘴硬/害怕、关系变化和读者阶段答案，不是煽情任务。
- 设定呈现优先按行动后果走：人物尝试 -> 出事 -> 付代价 -> 别人反应 -> 主角只总结一点点。

输出格式必须是严格合法 JSON，不要 Markdown；只输出 JSON，不要解释：

${structuredBeatPlanJsonSchemaText()}

字段填写要求：
- chapterEvent：本章真实发生的事件，先回答“这一章到底发生了什么”。
- characterGoal：人物此刻想要什么，为什么非做不可。
- coreConflict：谁或什么力量阻止他。
- externalPressure：外部压力如何进入场景。
- costOrLoss：选择造成什么损失、牺牲或后遗症。
- irreversibleChange：关系、线索、地点、目标、代价或敌我态势至少有一项发生可验证变化。
- endingHandoff：结尾把动作、关系、物件状态或问题交给下一章。
- protagonistImmediateWant：主角本章最想要什么，写眼下欲望，不写抽象使命。
- emotionalAnchor：本章情绪锚点，可以是父亲、亏欠、害怕失去、嘴硬或不愿承认的事。
- misbeliefOrFear：主角误解、害怕、嘴硬或想隐瞒的点。
- relationshipDelta：本章人物关系发生的轻微变化。
- stageAnswerForReader：本章给读者的阶段性答案，避免只抛新问题。
- 每个字段 60-120 个中文字符以内；不要把字段写成长段正文，辅助字段可短写或省略。

要求：
- 时间线连续性：节拍按自然时间和因果顺序排列。
- 状态延续：身体状态、伤势、断臂位置、昏迷/清醒和情绪余波不得突然跳变。
- 规则数值延续：冷却时间、使用次数、距离、时长、等级、资源消耗、阵法规则等不得突然改口。
- 道具来源：新线索、道具、钱款、身份、法器、能力或情报必须安排来源、交接、发现过程或代价。
- 人物铺垫：重大选择必须来自当前欲望、压力、误判、利益牵引或关系变化。
- 伏笔铺垫：伏笔回收必须来自此前信息、误导解除或本章先行证据。
- 宗门势力存灭不得突然跳变；如本章必须改变，节拍里先安排发现、验证、代价或误判解除过程。
- 第一条是正文第一幕，不要从后续会议、事后追查、伤亡结果或已经发生后的复盘开始。
- 如果这是第 1 章，第一条必须来自开局锚点、创作种子或主角初始处境。
- 每个节拍都要能转化为正文场景，不要写抽象口号。
- 每个关键节拍写清“发生什么”和“为什么推动故事”。
- 关键真相尽量安排成“被发现”，不要安排成“被解释”。
- 选择要有真实代价；如果两个选项结局一样，这不是有效两难，要改成压力、误判或关系代价。
- 允许一两处闲笔、沉默、跑题对白或生活痕迹，为正文留下呼吸感。
- 句式节奏：小纲要规划正常叙事节奏，给正文留下长中短句混合的空间，不要把整章规划成短句密集的动作清单。
- 小纲只锁定关键路线，不规定具体句子和全部动作。
- 小纲总长度控制在 500-900 字；如果超过 1100 字，必须删掉解释、复盘、重复约束和过细动作，只保留可执行节拍。
- 节拍控制在 4-6 条。
- 本章结尾应是自然小钩子，可以留下动作、关系、物件或问题，不要写成抽象总结。
- 不要把结尾反转放到开头。
- 除非用户明确要求，不要把倒叙、插叙或闪回作为第一幕。
- 不要写小说正文。`
}

export function buildNotXButYRepairSystemPrompt() {
  return [
    '你是长篇小说轻量语言修订编辑。',
    '只处理非对白叙述中过密的“不是X，是Y/而是Y”反差判断句。',
    '优先把抽象判断改成动作、物件反应、对话停顿、人物反应或现实后果。',
    '不得新增剧情、删减关键信息、改变事件顺序、改变人物选择或结尾交接。',
    '只输出修订后的完整正文，不要解释。'
  ].join('\n')
}

export function buildNotXButYRepairPrompt({ chapterNum, content, analysis, beatPlan = '', context = {} } = {}) {
  const count = Number(analysis?.aiContrastCount || 0)
  const parts = [
    `请轻量修订第 ${chapterNum || '?'} 章，目标是把非对白叙述中的“不是X，是Y/而是Y”降到 0-2 次。`,
    `当前检测到 ${count} 次。`,
    '修订方式：能用动作、物件状态、对话错位、沉默、阻挠或代价呈现的地方，不要再用反差判断句解释。',
    '保留剧情事实、场景顺序、人物选择、信息量和章末钩子；不要整章重写。',
    beatPlan ? `本章小纲：\n${compactFallbackText(beatPlan, 1200)}` : '',
    context?.chapterGoal ? `本章目标：\n${formatChapterGoal(context.chapterGoal)}` : '',
    `正文：\n${String(content || '').trim()}`
  ].filter(hasText)
  return parts.join('\n\n')
}

export function buildNotXButYSegmentRepairPrompt({ chapterNum, segments = [], analysis, beatPlan = '', context = {} } = {}) {
  const segmentText = (Array.isArray(segments) ? segments : [])
    .map((segment, index) => [
      `SEGMENT_${index + 1}:`,
      segment.originalText || ''
    ].join('\n'))
    .join('\n\n---\n\n')
  return [
    `Repair only the listed sentence groups from chapter ${chapterNum || '?'}.`,
    `Current notXButY count: ${Number(analysis?.aiContrastCount || 0)}. Target: 0-2.`,
    'Return strict JSON only: {"replacements":[{"originalText":"","replacementText":""}]}',
    'Rules:',
    '- originalText must exactly copy one listed segment.',
    '- replacementText may only rewrite that same sentence group and its immediate local wording.',
    '- Preserve plot facts, character choices, event order, information amount, and ending handoff.',
    '- Do not rewrite the whole chapter, do not add new plot, do not remove evidence.',
    '- Replace contrast-judgment phrasing with visible action, object reaction, interrupted dialogue, cost, or consequence.',
    beatPlan ? `Beat plan reference:\n${compactFallbackText(beatPlan, 900)}` : '',
    context?.chapterGoal ? `Chapter goal:\n${formatChapterGoal(context.chapterGoal)}` : '',
    `Segments:\n${segmentText}`
  ].filter(hasText).join('\n\n')
}

export function buildParagraphRepetitionRepairPrompt({ chapterNum, content, analysis, beatPlan = '', context = {} } = {}) {
  const issueTypes = (analysis?.issues || []).map(item => item.type).filter(Boolean).join(', ') || 'paragraph_level_repetition'
  return [
    `Repair paragraph-level repetition in chapter ${chapterNum || '?'}.`,
    `Detected issues: ${issueTypes}.`,
    'Goal: keep the chapter readable and novel-like by merging, trimming, or varying repeated paragraph structures.',
    'Preserve plot facts, character choices, event order, information amount, external events, irreversible change, and ending handoff.',
    'Do not add a new subplot, new character, new clue, new rule, or new ending.',
    'Do not rewrite the chapter into a summary. Keep concrete scene action and dialogue.',
    'When several paragraphs repeat the same thought/action pattern, keep the strongest one and fold only necessary facts from the others into adjacent natural prose.',
    'Output the full repaired chapter text only, no title, no explanation.',
    beatPlan ? `Beat plan reference:\n${compactFallbackText(beatPlan, 1200)}` : '',
    context?.chapterGoal ? `Chapter goal:\n${formatChapterGoal(context.chapterGoal)}` : '',
    `Chapter text:\n${String(content || '').trim()}`
  ].filter(hasText).join('\n\n')
}

/**
 * 章节续写 prompt
 */
export function buildContinuePrompt(currentContent, instruction, context = {}) {
  const volumeStage = formatVolumeStage(context.volumeStage)
  const constraints = [
    context.styleBible ? `风格要求：${context.styleBible}` : '',
    context.styleStandardBrief ? `题材/风格标准：\n${context.styleStandardBrief}` : '',
    context.settingLibrary ? `设定库：\n${context.settingLibrary}` : '',
    context.recentSettingChanges ? `最近设定变化：\n${context.recentSettingChanges}` : '',
    context.activeCorrectionTasks ? `未完成纠偏任务：\n${context.activeCorrectionTasks}` : '',
    volumeStage ? `分卷阶段上下文：\n${volumeStage}` : '',
    context.recentFacts ? `已确认事实：\n${context.recentFacts}` : ''
  ].filter(hasText).join('\n\n')

  return `${constraints ? `## 写作上下文\n${constraints}\n\n` : ''}以下是小说的当前内容：

---
${currentContent}
---

请从最后一句自然续写。${instruction ? `\n续写方向：${instruction}` : ''}

要求：
- 只输出续写正文，不要输出标题、说明或提纲。
- 保持一致的风格和人物声音。
- 承接当前分卷目标、阶段总结、人物状态和已确认事实。
- 向前推进情节或深化人物。
- 不要重复已有内容。
- 续写长度：800-2000 字。`
}

/**
 * 多候选版本 prompt
 */
export function buildMultiVariantPrompt(context) {
  const basePrompt = buildChapterPrompt(context)
  const labels = Array.isArray(context?.variantLabels) && context.variantLabels.length
    ? context.variantLabels
    : MULTI_VARIANT_LABELS
  const descriptions = {
    稳妥推进版: '按照小纲自然推进，风格稳健，适合作为正文基准稿。',
    强冲突版: '加强矛盾和冲突，节奏更快，张力更强。',
    意外转向版: '在合理范围内引入意外发展，制造惊喜。'
  }
  const variantList = labels
    .map((label, index) => `${index + 1}. **${label}**：${descriptions[label] || '在不违背小纲的前提下提供不同写法。'}`)
    .join('\n')
  const variantBlocks = labels
    .map(label => `<<<VARIANT:${label}>>>\n只写这一版的章节正文，不要写标题、解释或小纲。\n<<<END_VARIANT>>>`)
    .join('\n\n')
  const baselineDraft = hasText(context?.baselineDraft)
    ? `\n\n## 已有基准正文\n下面是用户当前已有的基准正文。新候选应与它形成可比较的差异，不要简单同义改写，也不要无视小纲乱改。\n---\n${context.baselineDraft}\n---`
    : ''

  return `${basePrompt}
${baselineDraft}

请生成 ${labels.length} 个不同方向的候选版本：

${variantList}

输出格式必须严格使用下面的分隔协议：

${variantBlocks}

注意：
- 分隔符必须原样保留，便于系统拆分版本。
- 每个分隔符之间只能放对应版本的小说正文。
- 不要把多个版本混写到同一个正文里。`
}

/**
 * 扩写 prompt
 */
export function buildExpandPrompt(selectedText, context = {}) {
  const volumeStage = formatVolumeStage(context.volumeStage)
  return `请扩写以下段落，丰富细节、心理描写和场景氛围：

${volumeStage ? `## 分卷阶段上下文\n${volumeStage}\n` : ''}
${context.styleBible ? `## 风格要求\n${context.styleBible}\n` : ''}
${context.styleStandardBrief ? `## 题材/风格标准\n${context.styleStandardBrief}\n` : ''}

---
${selectedText}
---

扩写要求：
- 只输出扩写后的正文。
- 保持原有人物性格和对话风格。
- 可以增加内心独白、环境描写、动作细节。
- 扩写后长度约为原来的 2-3 倍。
- 不要让扩写后的文字变得冗长拖沓。`
}

/**
 * 压缩 prompt
 */
export function buildCompressPrompt(selectedText) {
  return `请压缩以下段落，保留核心情节和关键对话，删除冗余描写：
---
${selectedText}
---

压缩要求：
- 只输出压缩后的正文。
- 保留情节推进的关键节点。
- 保留重要对话和人物反应。
- 压缩后长度约为原来的一半。`
}

/**
 * 多模型融合 prompt
 */
export function buildFusionPrompt(fragments, context) {
  const fragmentText = fragments.map((f, i) =>
    `### 候选 ${i + 1}（来源：${f.label || `模型 ${i + 1}`}）\n\n${f.content}`
  ).join('\n\n---\n\n')

  return `请将以下多个 AI 生成的章节候选版本融合成一个最佳版本。
${fragmentText}

融合要求：
- 只输出融合后的正文，不要输出标题或解释。
- 提取每个候选中最精彩的情节走向和描写。
- 保持统一的叙事风格和人物声音。
- 解决候选之间的冲突和矛盾。
- 确保情节连贯，过渡自然。
- 融合后的长度应接近原候选的平均长度。
- 不要添加与候选中完全无关的新情节。
${context.chapterNum ? `这是第 ${context.chapterNum} 章。` : ''}

请直接输出融合后的完整章节正文。`
}

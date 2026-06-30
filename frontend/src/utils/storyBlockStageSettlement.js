const MAX_STAGE_CONTINUATION_DEPTH = 2

function cleanText(value = '') {
  return String(value ?? '').replace(/\s+/g, ' ').trim()
}

function asList(value) {
  return Array.isArray(value) ? value : []
}

function uniqueStrings(values = []) {
  const seen = new Set()
  const result = []
  for (const value of values) {
    const text = cleanText(value)
    if (!text || seen.has(text)) continue
    seen.add(text)
    result.push(text)
  }
  return result
}

function snapshotStageId(snapshot = {}) {
  return cleanText(snapshot?.stageId || snapshot?.id || snapshot?.stage_id)
}

export function reviewStageId(review = {}) {
  return cleanText(
    review.blockStageSnapshot?.stageId ||
    review.blockStageSnapshot?.id ||
    review.blockStageId ||
    review.block_stage_id ||
    review.stageId ||
    review.stage_id
  )
}

function historyStageId(item = {}) {
  return cleanText(
    item.blockStageId ||
    item.block_stage_id ||
    item.storyBlockStageId ||
    item.stageId ||
    item.stage_id ||
    item.blockStageSnapshot?.stageId ||
    item.blockStageSnapshot?.id
  )
}

function reviewContinueReason(review = {}) {
  return cleanText(review.stageContinueReason || review.stage_continue_reason || review.reason)
}

function stagePlanLength(block = {}) {
  return asList(block.stagePlan || block.stage_plan).length
}

function storyBlockStages(block = {}) {
  return asList(block.stagePlan || block.stage_plan)
}

function nextChapterNum(context = {}) {
  return Number(context.chapterNum || context.nextChapterNum || 0) || 'next'
}

function buildSettlementStage(context = {}, review = {}) {
  const chapter = nextChapterNum(context)
  const index = stagePlanLength(context.storyBlock || {}) + 1
  const reason = reviewContinueReason(review) || '未完成的后续动作转入新阶段，不再复用旧阶段。'
  return {
    id: `stage-split-${chapter}-${index}`,
    purpose: '承接残余动作，转入新的可执行阶段',
    sceneOrAction: cleanText(reason).slice(0, 160) || '把旧阶段剩余动作写成新的场景行动。',
    choice: '陆沉舟必须在救人、保住星账和反向设局之间做出一个有代价的选择。',
    costOrConsequence: '让小九后果、第三密栈或星账代价进入后续阶段，不再悬挂旧阶段。',
    status: 'planned',
    generatedBy: 'stage_continuation_settlement'
  }
}

export function buildStageContinuationDiagnostics({
  currentStageId = '',
  previousOpenStageId = '',
  reviewHistory = []
} = {}) {
  const stageId = cleanText(currentStageId || previousOpenStageId)
  const ordered = [...asList(reviewHistory)]
    .sort((left, right) => Number(left.chapterNum || left.chapter_num || 0) - Number(right.chapterNum || right.chapter_num || 0))
  let depth = 0
  let lastOpenChapterNum = null
  for (let index = ordered.length - 1; index >= 0; index -= 1) {
    const item = ordered[index]
    const itemStageId = historyStageId(item)
    if (item.stageContinues === true && (!stageId || !itemStageId || itemStageId === stageId)) {
      depth += 1
      if (lastOpenChapterNum === null) {
        lastOpenChapterNum = Number(item.chapterNum || item.chapter_num || 0) || lastOpenChapterNum
      }
      continue
    }
    break
  }
  return {
    stageContinuationDepth: depth,
    previousOpenStageId: stageId,
    lastOpenChapterNum,
    stageContinuationLimit: MAX_STAGE_CONTINUATION_DEPTH,
    requiresSettlementBeforeNextBeatPlan: Boolean(stageId && depth >= MAX_STAGE_CONTINUATION_DEPTH)
  }
}

function collectEvidenceText(context = {}) {
  const parts = [
    context.finalizedSummary,
    context.chapterEnding,
    context.previousChapterEnding,
    asList(context.facts).map(item => cleanText(item?.content || item?.summary || item?.text || item?.evidence || item)).join(' '),
    asList(context.settingChanges).map(item => cleanText(item?.evidence || item?.newValue || item?.entityName || item)).join(' '),
    asList(context.storyBlock?.reviewHistory || context.storyBlock?.review_history)
      .slice(-4)
      .map(item => cleanText(item.stageContinueReason || item.reason || item.completionEvidence))
      .join(' ')
  ]
  return parts.map(cleanText).filter(Boolean).join(' ')
}

function matchEvidence(text, label, pattern) {
  const match = text.match(pattern)
  if (!match) return null
  return `${label}：${cleanText(match[0]).slice(0, 60)}`
}

const FUTURE_STAGE_COMMON_TERMS = new Set([
  '陆沉舟',
  '本章',
  '当前',
  '阶段',
  '后续',
  '选择',
  '代价',
  '结果',
  '目标',
  '确认',
  '继续',
  '故事',
  '功能',
  '人物',
  '线索',
  '进入',
  '承接',
  '推进',
  '任务',
  '行动',
  '关系',
  '已经',
  '可能',
  '真正',
  '需要',
  '没有',
  '可以',
  '当前章',
  '下一章'
])

function storyBlockStageId(stage = {}) {
  return cleanText(stage.id || stage.stageId || stage.stage_id)
}

function stageSearchText(stage = {}) {
  return cleanText([
    stage.id,
    stage.stageId,
    stage.purpose,
    stage.stagePurpose,
    stage.goal,
    stage.sceneOrAction,
    stage.action,
    stage.description,
    stage.choice,
    stage.costOrConsequence,
    stage.consequence,
    stage.cost
  ].filter(Boolean).join(' '))
}

function collectFutureStageKeywords(stage = {}) {
  const text = stageSearchText(stage)
  const tokens = text
    .split(/[，。；：、,.;:!?！？（）()\s\-—_]+/)
    .map(cleanText)
    .filter(Boolean)
  const keywords = new Set()
  for (const token of tokens) {
    if (token.length < 2) continue
    if (token.length <= 8 && !FUTURE_STAGE_COMMON_TERMS.has(token)) keywords.add(token)
    if (token.length > 4) {
      for (let size = 3; size <= Math.min(6, token.length); size += 1) {
        for (let index = 0; index <= token.length - size; index += 1) {
          const part = token.slice(index, index + size)
          if (!FUTURE_STAGE_COMMON_TERMS.has(part)) keywords.add(part)
        }
      }
    }
  }
  return [...keywords]
}

function futureStagesAfterCurrent(block = {}, currentStageId = '') {
  const stages = storyBlockStages(block)
  const currentIndex = stages.findIndex(stage => storyBlockStageId(stage) === currentStageId)
  if (currentIndex < 0) return stages.filter(stage => storyBlockStageId(stage) && storyBlockStageId(stage) !== currentStageId)
  return stages.slice(currentIndex + 1)
}

function detectFutureStageTouch(context = {}, currentStageId = '') {
  const text = collectEvidenceText(context)
  const futureStages = futureStagesAfterCurrent(context.storyBlock || {}, currentStageId)
  const evidence = []
  for (const stage of futureStages) {
    const id = storyBlockStageId(stage)
    if (!id) continue
    const hits = collectFutureStageKeywords(stage)
      .filter(keyword => keyword.length >= 2 && text.includes(keyword))
      .slice(0, 4)
    if (hits.length) evidence.push(`${id}：${hits.join('、')}`)
  }
  return {
    futureStageTouched: evidence.length > 0,
    futureStageEvidence: evidence
  }
}

function currentStageOnlyCompleted(stageIdValue = '') {
  return stageIdValue ? [stageIdValue] : []
}

export function hasEquivalentStoryFunction(context = {}) {
  const text = collectEvidenceText(context)
  const evidence = [
    matchEvidence(text, '错误信任或误判', /误信|错误信任|判断错|判断失误|低估|独自|不等|贸然|冒险|自以为/),
    matchEvidence(text, '敌方反制', /反制|设伏|伏击|陷阱|后手|威胁|警告|假画像|假线索|被误导|入局/),
    matchEvidence(text, '关系代价', /小九.{0,16}(绑|带走|失踪|人质|高烧|伤势|恶化)|绑走.{0,12}小九|用.{0,12}换.{0,12}小九/),
    matchEvidence(text, '星账代价', /星账.{0,24}(极限|代价|失效|碎裂|裂|最后|报废|加重|次数|能力)|黑纹|失读/),
    matchEvidence(text, '局势不可逆变化', /内鬼|背叛|坐实|身份确认|目标确认|真实目标|第三密栈|选择受限|无法回头|交换筹码/),
    matchEvidence(text, '阶段答案', /确认|证实|坐实|原来|真身|真实目标|答案|指向/)
  ].filter(Boolean)
  const equivalent = evidence.length >= 3 && (
    evidence.some(item => item.startsWith('关系代价') || item.startsWith('星账代价')) ||
    evidence.some(item => item.startsWith('敌方反制')) && evidence.some(item => item.startsWith('局势不可逆变化'))
  )
  return {
    equivalent,
    evidence,
    text
  }
}

export function enforceStageContinuationSettlement(review = {}, context = {}) {
  const snapshot = context.blockStageSnapshot || review.blockStageSnapshot || {}
  const stageId = snapshotStageId(snapshot) || reviewStageId(review)
  const diagnostics = buildStageContinuationDiagnostics({
    currentStageId: stageId,
    previousOpenStageId: context.previousOpenStageId || stageId,
    reviewHistory: context.storyBlock?.reviewHistory || context.storyBlock?.review_history || []
  })
  const depth = Math.max(
    Number(context.stageContinuationDepth || 0) || 0,
    Number(review.stageContinuationDepth || 0) || 0,
    Number(diagnostics.stageContinuationDepth || 0) || 0
  )
  const out = {
    ...review,
    completedStageIds: uniqueStrings(review.completedStageIds || []),
    remainingStages: asList(review.remainingStages).map(stage => ({ ...stage })),
    carryOverToNextChapter: uniqueStrings(review.carryOverToNextChapter || []),
    settlementEvidence: asList(review.settlementEvidence).map(cleanText).filter(Boolean),
    equivalentCompletionScope: cleanText(review.equivalentCompletionScope || review.equivalent_completion_scope || ''),
    futureStageTouched: review.futureStageTouched === true || review.future_stage_touched === true,
    futureStageEvidence: uniqueStrings(review.futureStageEvidence || review.future_stage_evidence || []),
    futureStageOverClosed: review.futureStageOverClosed === true || review.future_stage_over_closed === true,
    needsFutureStageReplan: review.needsFutureStageReplan === true || review.needs_future_stage_replan === true,
    replanRemainingStages: review.replanRemainingStages === true || review.replan_remaining_stages === true,
    stageContinuationDepth: depth,
    previousOpenStageId: cleanText(context.previousOpenStageId || review.previousOpenStageId || stageId)
  }

  if (review.stageContinues !== true) {
    return out
  }

  const equivalence = hasEquivalentStoryFunction(context)
  if (equivalence.equivalent && stageId) {
    const futureTouch = detectFutureStageTouch(context, stageId)
    const futureIds = new Set(futureStagesAfterCurrent(context.storyBlock || {}, stageId).map(storyBlockStageId).filter(Boolean))
    const attemptedFutureClose = out.completedStageIds.some(id => futureIds.has(id))
    out.stageContinues = false
    out.stageContinueReason = ''
    out.completedStageIds = currentStageOnlyCompleted(stageId)
    out.settlementDecision = 'completed_by_equivalent_story_function'
    out.settlementEvidence = equivalence.evidence
    out.equivalentCompletionScope = 'current_stage_only'
    out.futureStageTouched = futureTouch.futureStageTouched || attemptedFutureClose
    out.futureStageEvidence = futureTouch.futureStageEvidence
    out.futureStageOverClosed = false
    out.preventedFutureStageOverClose = attemptedFutureClose
    out.needsFutureStageReplan = out.futureStageTouched
    out.replanRemainingStages = out.futureStageTouched
    if (out.futureStageTouched && out.decision === 'continue_current_block') {
      out.decision = 'adjust_remaining_stages'
    }
    out.whetherStageClosedBeforeNextBeatPlan = true
    out.reason = `当前阶段故事功能已等价完成：${equivalence.evidence.slice(0, 3).join('；')}。下一章进入后续阶段，不再逐字验收旧阶段措辞。`
    return out
  }

  if (depth >= MAX_STAGE_CONTINUATION_DEPTH) {
    out.stageContinues = false
    out.stageContinueReason = ''
    out.decision = 'adjust_remaining_stages'
    out.completedStageIds = currentStageOnlyCompleted(stageId)
    out.settlementDecision = stageId ? 'split_remaining_stage' : 'blocked_for_manual_review'
    out.settlementEvidence = [
      `同一阶段连续继续深度=${depth}`,
      reviewContinueReason(review)
    ].filter(Boolean)
    out.whetherStageClosedBeforeNextBeatPlan = Boolean(stageId)
    out.remainingStages = out.remainingStages.length ? out.remainingStages : [buildSettlementStage(context, review)]
    out.carryOverToNextChapter = uniqueStrings([
      ...out.carryOverToNextChapter,
      reviewContinueReason(review),
      '旧阶段已结算，剩余动作转入后续未锁定阶段。'
    ])
    out.reason = stageId
      ? `同一阶段已连续跨章继续 ${depth} 次，不得继续复用同一阶段；当前阶段关闭，残余动作拆入后续未锁定阶段。`
      : `同一阶段已连续跨章继续 ${depth} 次，但缺少 stageId，需人工复核后再生成小纲。`
    if (!stageId) out.requiresReview = true
  }

  return out
}

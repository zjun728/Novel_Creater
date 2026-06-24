import {
  buildChapterBeatPrompt,
  buildChapterBeatSystemPrompt
} from './chapter.js'
import {
  buildAntiLoopPlanningBrief,
  buildBeatPlanProgressionGateBrief
} from '../quality/writingQualityPrompt.js'
import { storyBlockSnapshotBrief } from '../utils/storyBlockSnapshot.js'

export const BEAT_PLAN_PROMPT_SOFT_LIMIT = 12000
export const BEAT_PLAN_PROMPT_HARD_LIMIT = 18000

export function buildScenePlanSystemPrompt() {
  return `${buildChapterBeatSystemPrompt()}

补充定位：
- 这是“场景型小纲”，不是写正文，也不是审稿报告。
- 小纲要规划场景摩擦、人物遮掩、信息释放、有效选择和结尾余波。
- 不要把正文句子写死，只锁定可执行路线。`
}

export function buildScenePlanPrompt(context = {}) {
  return buildScenePlanPromptWithDiagnostics(context).prompt
}

export function buildScenePlanPromptWithDiagnostics(context = {}, options = {}) {
  const promptCharsBeforeCompression = buildUncompressedScenePlanPromptForDiagnostics(context).length
  let forceMinimalApplied = Boolean(options.forceMinimal)
  let lightweightContext = buildLightweightScenePlanContext(context, options)
  let prompt = buildLightweightScenePlanPrompt(lightweightContext, options)
  if (!forceMinimalApplied && prompt.length > BEAT_PLAN_PROMPT_HARD_LIMIT) {
    forceMinimalApplied = true
    lightweightContext = buildLightweightScenePlanContext(context, { ...options, forceMinimal: true })
    prompt = buildLightweightScenePlanPrompt(lightweightContext, { ...options, forceMinimal: true })
  }
  const promptCharsAfterCompression = prompt.length
  const diagnostics = buildScenePlanContextDiagnostics(context, lightweightContext, {
    promptCharsBeforeCompression,
    promptCharsAfterCompression,
    forceMinimal: forceMinimalApplied
  })
  return {
    prompt,
    diagnostics,
    lightweightContext
  }
}

export function buildLightweightScenePlanContext(context = {}, options = {}) {
  const forceMinimal = Boolean(options.forceMinimal || context.forceMinimal)
  const blockStageSnapshot = context.blockStageSnapshot || context.stageSnapshot || null
  const storyBlock = compactStoryBlockForBeatPlan(context.storyBlock, { forceMinimal, blockStageSnapshot })
  return {
    chapterNum: context.chapterNum,
    wordTarget: context.wordTarget || null,
    seed: context.chapterNum === 1 ? compactSeed(context.seed) : null,
    storyBlock,
    blockStageSnapshot,
    chapterGoal: compactChapterGoalForBeatPlan(context.chapterGoal, blockStageSnapshot),
    volumeStage: compactVolumeForBeatPlan(context.volumeStage || context.currentVolume, { forceMinimal }),
    previousChapterEnding: compactText(context.previousChapterEnding || context.previousEnding, forceMinimal ? 260 : 420),
    recentSummaries: compactRecentSummaries(context.recentSummaries, forceMinimal ? 1 : 2),
    recentFacts: compactRecentFacts(context.recentFacts, forceMinimal ? 3 : 5),
    settingLibrary: compactSettingBrief(context.settingLibrary, context.settings, forceMinimal ? 600 : 1000),
    stateLedger: compactStateLedger(context.stateLedger, forceMinimal ? 500 : 900),
    forbiddenDirections: compactList(context.forbiddenDirections, 3, 80)
  }
}

function buildLightweightScenePlanPrompt(context = {}, options = {}) {
  const storyBlockBrief = context.blockStageSnapshot
    ? storyBlockSnapshotBrief(context.blockStageSnapshot)
    : formatStoryBlockForPlanning(context.storyBlock)
  const activeBlockBrief = context.storyBlock
    ? formatStoryBlockForPlanning(context.storyBlock)
    : ''
  const prefix = [
    activeBlockBrief ? `## 当前 active 故事块精简摘要\n${activeBlockBrief}` : '',
    storyBlockBrief ? `## block_stage_snapshot / 当前故事块阶段（小纲必须从当前故事块阶段生成）\n${storyBlockBrief}` : '',
    context.storyBlock
      ? '- 故事块不是固定章节数量；本章只负责当前章可写内容，不要提前写掉后续阶段。'
      : '',
    '## 容量与推进补充',
    '- 本章只规划 2-4 个核心场景；每个场景必须服务明确目标，不能把后续章节内容提前塞入本章。',
    '- 本章必须至少规划一个不可逆变化：关系变化、线索推进、地点变化、目标变化、代价兑现或敌我态势变化。',
    '- 如果内容超量，减少场景数量，不要增加解释、复盘、余波或下一章开场。',
    '## 场景型小纲补充目标',
    '- 场景摩擦：本章不能只顺滑推进，至少要有误判、阻滞、遮掩、迟疑、关系压力或现实打断之一。',
    '- 信息释放：关键内容优先通过证据、行动失败、物件反应、关系变化或旁人遮掩被发现。',
    '- 有效选择：关键选择必须有不同损失；如果不是两难，要写清真正压力来自哪里。',
    '- 人味呼吸：预留一处沉默、跑题对白、生活痕迹或无用但真实的细节。',
    options.forceMinimal
      ? '## 空响应重试约束\n- 上一次模型返回空内容；这次只使用极简上下文，必须输出完整 JSON 小纲。'
      : '',
    buildAntiLoopPlanningBrief(),
    buildBeatPlanProgressionGateBrief(),
    context.writingFingerprint ? `## 写作指纹\n${context.writingFingerprint}` : ''
  ].filter(Boolean).join('\n')

  return `${prefix}\n\n${buildChapterBeatPrompt(context)}`
}

function buildUncompressedScenePlanPromptForDiagnostics(context = {}) {
  const storyBlockBrief = context.blockStageSnapshot
    ? storyBlockSnapshotBrief(context.blockStageSnapshot)
    : formatStoryBlockForPlanning(context.storyBlock)
  const prefix = [
    storyBlockBrief ? `## block_stage_snapshot / 当前故事块阶段（小纲必须从当前故事块阶段生成）\n${storyBlockBrief}` : '',
    context.storyBlock
      ? '- 故事块不是固定章节数量；本章只负责当前章可写内容，不要提前写掉后续阶段。'
      : ''
  ].filter(Boolean).join('\n')
  return `${prefix}\n\n${buildChapterBeatPrompt(context)}`
}

function buildScenePlanContextDiagnostics(originalContext = {}, lightweightContext = {}, options = {}) {
  const storyBlock = originalContext.storyBlock || null
  const stages = Array.isArray(storyBlock?.stagePlan) ? storyBlock.stagePlan : []
  const snapshot = originalContext.blockStageSnapshot || originalContext.stageSnapshot || null
  const promptCharsBeforeCompression = Number(options.promptCharsBeforeCompression || 0)
  const promptCharsAfterCompression = Number(options.promptCharsAfterCompression || 0)
  return {
    promptCharsBeforeCompression,
    promptCharsAfterCompression,
    promptChars: promptCharsAfterCompression,
    promptTokensApprox: estimatePromptTokens(promptCharsAfterCompression),
    contextCompressionApplied: Boolean(
      options.forceMinimal ||
      promptCharsBeforeCompression > BEAT_PLAN_PROMPT_SOFT_LIMIT ||
      promptCharsBeforeCompression > promptCharsAfterCompression
    ),
    promptSoftLimit: BEAT_PLAN_PROMPT_SOFT_LIMIT,
    promptHardLimit: BEAT_PLAN_PROMPT_HARD_LIMIT,
    forceMinimal: Boolean(options.forceMinimal),
    storyBlockId: snapshot?.storyBlockId || storyBlock?.id || '',
    blockStageId: snapshot?.stageId || '',
    activeStoryBlockExists: Boolean(storyBlock && storyBlock.status === 'active'),
    activeStoryBlockStageCount: stages.length,
    activeStoryBlockNextStage: describeNextStoryBlockStage(storyBlock, snapshot),
    oversizedInputs: detectOversizedInputs(originalContext),
    injectedContext: {
      hasBible: Boolean(lightweightContext.bible),
      hasFullVolumes: Boolean(lightweightContext.volumePlanning),
      hasFullSettings: false,
      recentFactCount: Array.isArray(lightweightContext.recentFacts) ? lightweightContext.recentFacts.length : 0,
      recentSummaryCount: Array.isArray(lightweightContext.recentSummaries) ? lightweightContext.recentSummaries.length : 0,
      hasStoryBlockDiagnostics: Boolean(lightweightContext.storyBlock?.planningDiagnostics || lightweightContext.storyBlock?.reviewHistory)
    }
  }
}

function estimatePromptTokens(charsOrText = '') {
  const chars = typeof charsOrText === 'number' ? charsOrText : String(charsOrText || '').length
  return Math.ceil(chars / 2)
}

function detectOversizedInputs(context = {}) {
  const bibleChars = safeJsonLength(context.bible || context.premise || context.worldRules)
  const volumeChars = safeJsonLength(context.volumePlanning || context.volumes || context.volumeStage || context.currentVolume)
  const settingChars = safeJsonLength(context.settingLibrary || context.settings || context.stateLedger)
  const diagnosticsChars = safeJsonLength({
    planningDiagnostics: context.storyBlock?.planningDiagnostics,
    reviewHistory: context.storyBlock?.reviewHistory || context.reviewHistory,
    rawHead: context.storyBlock?.rawHead,
    rawTail: context.storyBlock?.rawTail
  })
  return {
    bible: bibleChars > 1800,
    volumes: volumeChars > 1800,
    settings: settingChars > 2400,
    diagnostics: diagnosticsChars > 200,
    bibleChars,
    volumeChars,
    settingChars,
    diagnosticsChars
  }
}

function compactStoryBlockForBeatPlan(block = null, options = {}) {
  if (!block) return null
  const stages = Array.isArray(block.stagePlan) ? block.stagePlan : []
  const snapshotStageId = options.blockStageSnapshot?.stageId || ''
  const currentStage = snapshotStageId
    ? stages.find(stage => String(stage?.id || stage?.stageId || '') === String(snapshotStageId))
    : null
  const nextStage = currentStage || stages.find(stage => !['completed', 'closed', 'skipped'].includes(String(stage?.status || '').toLowerCase())) || stages[0] || null
  const selectedStages = options.forceMinimal
    ? [nextStage].filter(Boolean)
    : compactStageWindow(stages, nextStage)
  return {
    id: block.id || '',
    title: compactText(block.title, 80),
    status: block.status || '',
    goal: compactText(block.goal, options.forceMinimal ? 140 : 220),
    storyFunction: compactText(block.storyFunction || block.story_function, 120),
    entryState: compactText(block.entryState || block.entry_state, options.forceMinimal ? 120 : 180),
    mainPressure: compactText(block.mainPressure || block.main_pressure, options.forceMinimal ? 120 : 180),
    nextStageSuggestion: compactText(block.nextStageSuggestion || block.next_stage_suggestion, options.forceMinimal ? 120 : 180),
    unresolvedQuestions: compactList(block.unresolvedQuestions || block.unresolved_questions, options.forceMinimal ? 2 : 4, 90),
    stagePlan: selectedStages.map(stage => ({
      id: stage?.id || stage?.stageId || '',
      status: stage?.status || 'planned',
      purpose: compactText(stage?.purpose || stage?.stagePurpose || stage?.goal, 120),
      sceneOrAction: compactText(stage?.sceneOrAction || stage?.action || stage?.description, 150),
      choice: compactText(stage?.choice, 110),
      costOrConsequence: compactText(stage?.costOrConsequence || stage?.consequence || stage?.cost, 120)
    }))
  }
}

function compactStageWindow(stages = [], nextStage = null) {
  if (!Array.isArray(stages) || !stages.length) return []
  if (!nextStage) return stages.slice(0, 3)
  const index = stages.indexOf(nextStage)
  if (index < 0) return [nextStage]
  return stages.slice(Math.max(0, index - 1), Math.min(stages.length, index + 3))
}

function compactSeed(seed = null) {
  if (!seed) return null
  return {
    premise: compactText(seed.premise, 180),
    openingHook: compactText(seed.openingHook || seed.opening_hook, 180),
    openingAnchor: compactText(seed.openingAnchor || seed.opening_anchor, 180),
    protagonist: compactText(seed.protagonist, 120)
  }
}

function compactChapterGoalForBeatPlan(chapterGoal = null, snapshot = null) {
  if (chapterGoal) return chapterGoal
  if (!snapshot) return null
  return [
    snapshot.stagePurpose ? `阶段目的：${compactText(snapshot.stagePurpose, 120)}` : '',
    snapshot.stageAction ? `本章行动：${compactText(snapshot.stageAction, 160)}` : '',
    snapshot.stageChoice ? `人物选择：${compactText(snapshot.stageChoice, 100)}` : '',
    snapshot.stageCostOrConsequence ? `代价/后果：${compactText(snapshot.stageCostOrConsequence, 120)}` : ''
  ].filter(Boolean).join('\n')
}

function compactVolumeForBeatPlan(volume = null, options = {}) {
  if (!volume) return null
  const rawSummary = volume.stageSummary || volume.summary
  return {
    title: compactText(volume.title || volume.name, 80),
    coreGoal: compactText(volume.coreGoal || volume.goal, options.forceMinimal ? 140 : 220),
    mainConflict: compactText(volume.mainConflict || volume.conflict, options.forceMinimal ? 120 : 180),
    handoffPoint: compactText(volume.handoffPoint || volume.handoff_point, options.forceMinimal ? 100 : 160),
    stageSummary: safeJsonLength(rawSummary) > 1200 ? '' : compactText(rawSummary, options.forceMinimal ? 120 : 180),
    unresolvedItems: compactList(volume.unresolvedItems || volume.unresolved_items, 3, 80)
  }
}

function compactRecentSummaries(summaries = [], limit = 2) {
  if (!Array.isArray(summaries)) return []
  return summaries.slice(-limit).map(item => ({
    chapterNum: item?.chapterNum || item?.chapter_num || '',
    summary: compactText(item?.summary || item?.content || item?.text, 180)
  })).filter(item => item.summary)
}

function compactRecentFacts(facts = [], limit = 5) {
  const list = Array.isArray(facts)
    ? facts
    : String(facts || '').split(/\n+/).filter(Boolean)
  return list.slice(0, limit).map(item => {
    if (typeof item === 'string') return compactText(item, 140)
    return compactText(item?.text || item?.summary || item?.content || item?.fact || JSON.stringify(item), 140)
  }).filter(Boolean)
}

function compactSettingBrief(settingLibrary, settings, maxChars = 1000) {
  const source = settingLibrary || settings
  if (!source) return ''
  if (typeof source === 'string') return compactLongSourceBrief(source, maxChars, '设定库')
  if (Array.isArray(source)) {
    return source.slice(0, 8).map(item => {
      const name = item?.name || item?.entityName || item?.title || ''
      const summary = item?.summary || item?.description || item?.content || ''
      return compactText([name, summary].filter(Boolean).join('：'), 130)
    }).filter(Boolean).join('\n')
  }
  if (typeof source === 'object') {
    if (safeJsonLength(source) > maxChars * 4) return `（设定库过长，已在小纲阶段压缩；不注入全量设定库。）`
    const entries = Object.entries(source).slice(0, 8)
    return entries.map(([key, value]) => `${key}：${compactText(value, 120)}`).join('\n').slice(0, maxChars)
  }
  return compactText(source, maxChars)
}

function compactStateLedger(ledger, maxChars = 900) {
  if (!ledger) return ''
  if (typeof ledger === 'string') return compactLongSourceBrief(ledger, maxChars, '状态账本')
  if (typeof ledger === 'object') {
    if (safeJsonLength(ledger) > maxChars * 4) return `（状态账本过长，已在小纲阶段压缩；不注入全量状态账本。）`
    const picked = ['characters', 'locations', 'items', 'relationships', 'characterStates', 'locationStates', 'itemStates']
      .map(key => ledger?.[key] ? `${key}：${compactText(ledger[key], 180)}` : '')
      .filter(Boolean)
    return compactText(picked.join('\n') || JSON.stringify(ledger), maxChars)
  }
  return compactText(ledger, maxChars)
}

function compactLongSourceBrief(value, maxChars = 1000, label = '上下文') {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (text.length <= maxChars) return text
  const candidate = text
    .split(/[。！？!?；;\n]/)
    .map(item => item.trim())
    .filter(item => item && item.length <= 180)
    .slice(0, 5)
    .join('；')
  if (candidate && candidate.length <= maxChars && !isLikelyBulkRepeatedText(candidate)) return candidate
  return `（${label}过长，已在小纲阶段压缩；不注入全量${label}。）`
}

function isLikelyBulkRepeatedText(text = '') {
  const normalized = String(text || '').trim()
  if (!normalized) return false
  const tokens = normalized.split(/\s+/).filter(Boolean)
  if (tokens.length < 12) return false
  const unique = new Set(tokens)
  return unique.size <= Math.max(3, Math.ceil(tokens.length * 0.2))
}

function compactList(value, limit = 4, itemMaxChars = 90) {
  const list = Array.isArray(value)
    ? value
    : String(value || '').split(/[；;\n]/).filter(Boolean)
  return list.slice(0, limit).map(item => compactText(item, itemMaxChars)).filter(Boolean)
}

function compactText(value, maxChars = 160) {
  if (value === undefined || value === null) return ''
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  const normalized = text.replace(/\s+/g, ' ').trim()
  if (normalized.length <= maxChars) return normalized
  return `${normalized.slice(0, Math.max(0, maxChars - 1))}…`
}

function safeJsonLength(value) {
  if (!value) return 0
  try {
    return JSON.stringify(value).length
  } catch {
    return String(value).length
  }
}

function describeNextStoryBlockStage(block = null, snapshot = null) {
  if (snapshot?.stageId) {
    return [snapshot.stageId, snapshot.stagePurpose || snapshot.stageAction].filter(Boolean).join('：')
  }
  const stages = Array.isArray(block?.stagePlan) ? block.stagePlan : []
  const next = stages.find(stage => !['completed', 'closed', 'skipped'].includes(String(stage?.status || '').toLowerCase())) || stages[0]
  if (!next) return ''
  return [next.id || next.stageId, next.purpose || next.stagePurpose || next.sceneOrAction].filter(Boolean).join('：')
}

function formatStoryBlockForPlanning(block = null) {
  if (!block) return ''
  const stages = Array.isArray(block.stagePlan) ? block.stagePlan : []
  const nextStage = stages.find(stage => stage?.status !== 'completed') || stages[0] || null
  return [
    block.title ? `故事块：${block.title}` : '',
    block.goal ? `目标：${block.goal}` : '',
    block.storyFunction ? `故事功能：${block.storyFunction}` : '',
    block.entryState ? `入场状态：${block.entryState}` : '',
    block.nextStageSuggestion ? `下一阶段建议：${block.nextStageSuggestion}` : '',
    nextStage?.purpose ? `当前阶段目的：${nextStage.purpose}` : '',
    nextStage?.sceneOrAction ? `当前阶段行动：${nextStage.sceneOrAction}` : '',
    nextStage?.choice ? `人物选择：${nextStage.choice}` : '',
    nextStage?.costOrConsequence ? `代价/后果：${nextStage.costOrConsequence}` : '',
    block.unresolvedQuestions?.length ? `未解决问题：${block.unresolvedQuestions.join('；')}` : ''
  ].filter(Boolean).join('\n')
}

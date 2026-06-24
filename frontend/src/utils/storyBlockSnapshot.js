export const STORY_BLOCK_STATUSES = ['active', 'completed', 'paused', 'closed']

export const ALLOWED_STORY_BLOCK_REVIEW_DECISIONS = [
  'continue_current_block',
  'adjust_remaining_stages',
  'split_unfinalized_content',
  'complete_current_block',
  'open_new_block'
]

function cloneJson(value) {
  if (value === undefined || value === null) return value
  return JSON.parse(JSON.stringify(value))
}

function pickStageValue(stage = {}, ...keys) {
  for (const key of keys) {
    const value = stage?.[key]
    if (value !== undefined && value !== null && String(value).trim() !== '') return value
  }
  return ''
}

export function normalizeStoryBlockStatus(status = 'active') {
  const value = String(status || '').trim()
  return STORY_BLOCK_STATUSES.includes(value) ? value : 'paused'
}

export function normalizeStoryBlockReviewDecision(decision = 'continue_current_block') {
  const value = String(decision || '').trim()
  return ALLOWED_STORY_BLOCK_REVIEW_DECISIONS.includes(value) ? value : 'continue_current_block'
}

export function canEditRemainingStage(stage = {}) {
  const status = String(stage.status || 'planned')
  if (['completed', 'closed', 'skipped', 'locked'].includes(status)) return false
  if (stage.lockedByBeatPlan || stage.lockedByFinalChapter || stage.locked) return false
  if (Array.isArray(stage.chapterRefs) && stage.chapterRefs.length) return false
  return true
}

function completedStageIdSet(block = {}) {
  const ids = new Set()
  for (const stage of Array.isArray(block.completedStages) ? block.completedStages : []) {
    if (stage && typeof stage === 'object' && stage.id) ids.add(String(stage.id))
    else if (stage) ids.add(String(stage))
  }
  return ids
}

function isStageCompletedByReview(block = {}, stage = {}) {
  const id = stage?.id || stage?.stageId
  return Boolean(id && completedStageIdSet(block).has(String(id)))
}

export function buildBlockStageSnapshot(block = {}, stage = {}, options = {}) {
  const capturedAt = options.capturedAt ?? Date.now()
  const blockId = block.id || block.storyBlockId || ''
  const stageId = stage.id || stage.stageId || options.stageId || ''
  return {
    storyBlockId: blockId,
    blockTitle: block.title || '',
    blockGoal: block.goal || '',
    storyFunction: block.storyFunction || block.story_function || '',
    entryState: block.entryState || block.entry_state || '',
    exitTarget: block.exitTarget || block.exit_target || '',
    mainPressure: block.mainPressure || block.main_pressure || '',
    stageId,
    stagePurpose: pickStageValue(stage, 'purpose', 'stagePurpose', 'goal'),
    stageAction: pickStageValue(stage, 'sceneOrAction', 'stageAction', 'action', 'description'),
    stageChoice: pickStageValue(stage, 'choice', 'stageChoice'),
    stageCostOrConsequence: pickStageValue(stage, 'costOrConsequence', 'stageCostOrConsequence', 'consequence', 'cost'),
    nextStageSuggestion: block.nextStageSuggestion || block.next_stage_suggestion || '',
    unresolvedQuestions: cloneJson(block.unresolvedQuestions || block.unresolved_questions || []),
    dontAdvanceYet: cloneJson(block.dontAdvanceYet || block.dont_advance_yet || []),
    capacityAssessment: block.capacityAssessment || block.capacity_assessment || 'normal',
    locked: Boolean(stage.lockedByBeatPlan || stage.lockedByFinalChapter || stage.locked || stage.status === 'completed'),
    capturedAt
  }
}

export function findNextEditableStage(block = {}) {
  if (normalizeStoryBlockStatus(block.status || 'active') !== 'active') return null
  const stages = Array.isArray(block.stagePlan) ? block.stagePlan : []
  return stages.find(stage => !isStageCompletedByReview(block, stage) && canEditRemainingStage(stage)) || null
}

export function storyBlockSnapshotBrief(snapshot = {}) {
  return [
    snapshot.blockGoal ? `故事块目标：${snapshot.blockGoal}` : '',
    snapshot.storyFunction ? `故事功能：${snapshot.storyFunction}` : '',
    snapshot.entryState ? `入场状态：${snapshot.entryState}` : '',
    snapshot.stagePurpose ? `当前阶段目的：${snapshot.stagePurpose}` : '',
    snapshot.stageAction ? `当前阶段行动：${snapshot.stageAction}` : '',
    snapshot.stageChoice ? `人物选择：${snapshot.stageChoice}` : '',
    snapshot.stageCostOrConsequence ? `代价/后果：${snapshot.stageCostOrConsequence}` : '',
    snapshot.nextStageSuggestion ? `下一阶段建议：${snapshot.nextStageSuggestion}` : ''
  ].filter(Boolean).join('\n')
}

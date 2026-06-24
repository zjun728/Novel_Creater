export const CLOSED_UNEXECUTED_STAGE_STATUS = 'closed_unexecuted'
export const SKIPPED_BY_BLOCK_CLOSE_STATUS = 'skipped_by_block_close'

const CLOSE_DECISIONS = new Set(['complete_current_block', 'open_new_block'])
const GENERIC_CLOSE_REASON_PATTERN = /本章高效完成|高效完成|一气呵成|无需多章展开|短冲突块|本章写完|单章完成/
const EXIT_TARGET_PATTERN = /(exitTarget|出口目标|退出目标|块目标|故事块目标|主任务|任务)[\s\S]{0,28}(达成|完成|已满足|已达成|自然结束|失败|终止)|(达成|完成|满足)[\s\S]{0,16}(exitTarget|出口目标|退出目标|块目标|主任务)/
const MAJOR_TURN_PATTERN = /(重大|明确)[\s\S]{0,12}(转向|转折|变化)|新任务|新地点|新敌我态势|目标[\s\S]{0,12}转向|转入[\s\S]{0,12}(新任务|新地点|新线)/
const EXTERNAL_INVALIDATION_PATTERN = /(外力|外部事件|警报|封锁|追捕|被迫|逼迫|失效|打断|不再适用)[\s\S]{0,30}(失效|不再适用|转向|结束|撤离|离开|关闭|中断)?/
const SHORT_BLOCK_PATTERN = /开局|过渡|短过渡|短冲突|短块/

export function storyBlockStageId(stage = {}) {
  return String(stage?.id || stage?.stageId || stage?.stage_id || '').trim()
}

function uniqueStrings(values = []) {
  const seen = new Set()
  const result = []
  for (const value of values) {
    const text = String(value || '').trim()
    if (!text || seen.has(text)) continue
    seen.add(text)
    result.push(text)
  }
  return result
}

function stageHasExecutionEvidence(stage = {}) {
  return stage.status === 'completed' ||
    Boolean(stage.completedChapterNum || stage.completed_chapter_num) ||
    Boolean(stage.lockedByBeatPlan || stage.locked_by_beat_plan) ||
    Boolean(stage.lockedByFinalChapter || stage.locked_by_final_chapter) ||
    (Array.isArray(stage.chapterRefs || stage.chapter_refs) && (stage.chapterRefs || stage.chapter_refs).length > 0)
}

function completedStageIdSet(block = {}) {
  return new Set((Array.isArray(block.completedStages) ? block.completedStages : [])
    .map(stage => typeof stage === 'string' ? stage : storyBlockStageId(stage))
    .filter(Boolean))
}

export function filterExecutedCompletedStageIds(review = {}, block = {}, snapshot = {}) {
  const stagePlan = Array.isArray(block.stagePlan) ? block.stagePlan : []
  const currentStageId = String(snapshot?.stageId || review.blockStageId || '').trim()
  const ids = Array.isArray(review.completedStageIds) ? [...review.completedStageIds] : []
  if (
    currentStageId &&
    review.stageContinues !== true &&
    ['continue_current_block', 'adjust_remaining_stages', 'complete_current_block', 'open_new_block'].includes(review.decision)
  ) {
    ids.push(currentStageId)
  }

  const alreadyCompleted = completedStageIdSet(block)
  return uniqueStrings(ids).filter(stageId => {
    if (stageId === currentStageId) return true
    if (alreadyCompleted.has(stageId)) return true
    const stage = stagePlan.find(item => storyBlockStageId(item) === stageId)
    return Boolean(stage && stageHasExecutionEvidence(stage))
  })
}

function closeText(review = {}) {
  return [
    review.completionEvidence,
    review.reason,
    review.singleChapterBlockReason
  ].filter(Boolean).join('\n')
}

function isDesignedShortBlock(block = {}, review = {}) {
  const stageCount = Array.isArray(block.stagePlan) ? block.stagePlan.length : 0
  const shortReason = String(
    block.shortBlockReason ||
    block.short_block_reason ||
    block.lockState?.shortBlockReason ||
    block.lock_state?.shortBlockReason ||
    review.singleChapterBlockReason ||
    ''
  )
  return stageCount > 0 && stageCount < 3 && SHORT_BLOCK_PATTERN.test(shortReason)
}

export function assessStoryBlockCloseDecision(review = {}, block = {}, snapshot = {}) {
  if (!CLOSE_DECISIONS.has(review.decision)) {
    return {
      earlyCloseAllowed: true,
      blockCloseReasonType: 'not_closing',
      earlyCloseEvidence: ''
    }
  }

  const text = closeText(review)
  const executedIds = filterExecutedCompletedStageIds(review, block, snapshot)
  const stageCount = Array.isArray(block.stagePlan) ? block.stagePlan.length : 0
  const onlyFirstStageExecuted = stageCount >= 4 && executedIds.length <= 1
  const genericOnly = GENERIC_CLOSE_REASON_PATTERN.test(text) &&
    !EXIT_TARGET_PATTERN.test(text) &&
    !MAJOR_TURN_PATTERN.test(text) &&
    !EXTERNAL_INVALIDATION_PATTERN.test(text)

  let blockCloseReasonType = 'weak_or_generic'
  if (EXIT_TARGET_PATTERN.test(text)) blockCloseReasonType = 'exit_target_achieved'
  else if (MAJOR_TURN_PATTERN.test(text)) blockCloseReasonType = 'major_turn'
  else if (EXTERNAL_INVALIDATION_PATTERN.test(text)) blockCloseReasonType = 'external_invalidation'
  else if (isDesignedShortBlock(block, review)) blockCloseReasonType = 'designed_short_transition'

  const hasStrongEvidence = blockCloseReasonType !== 'weak_or_generic'
  const earlyCloseAllowed = hasStrongEvidence && !genericOnly && !(onlyFirstStageExecuted && blockCloseReasonType === 'designed_short_transition')

  return {
    earlyCloseAllowed,
    blockCloseReasonType,
    earlyCloseEvidence: text,
    executedStageCount: executedIds.length,
    onlyFirstStageExecuted,
    genericOnly
  }
}

export function splitStoryBlockStagesByExecution(block = {}, review = {}, snapshot = {}) {
  const completedIds = new Set(filterExecutedCompletedStageIds(review, block, snapshot))
  const invalidatedIds = new Set(uniqueStrings(review.invalidatedStageIds || review.invalidatedStages || []))
  const completedStages = []
  const remainingStages = []
  const invalidatedStages = []
  const closedUnexecutedStages = []

  for (const stage of Array.isArray(block.stagePlan) ? block.stagePlan : []) {
    const stageId = storyBlockStageId(stage)
    const status = String(stage.status || '')
    if (!stageId) continue
    if (completedIds.has(stageId) || status === 'completed') {
      completedStages.push(stage)
    } else if (invalidatedIds.has(stageId) || status === 'invalidated') {
      invalidatedStages.push(stage)
    } else if (status === CLOSED_UNEXECUTED_STAGE_STATUS || status === SKIPPED_BY_BLOCK_CLOSE_STATUS || status === 'closed' || status === 'skipped') {
      closedUnexecutedStages.push(stage)
    } else if (CLOSE_DECISIONS.has(review.decision)) {
      closedUnexecutedStages.push(stage)
    } else {
      remainingStages.push(stage)
    }
  }

  return {
    completedStages,
    remainingStages,
    invalidatedStages,
    closedUnexecutedStages
  }
}

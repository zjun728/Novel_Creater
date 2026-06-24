import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const storyBlocksRouter = readFileSync('backend/routers/story_blocks.py', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const stageList = readFileSync('frontend/src/components/story-block/StoryBlockStageList.vue', 'utf8')
const storyBlockCard = readFileSync('frontend/src/components/story-block/StoryBlockCard.vue', 'utf8')

assert.match(storyBlocksRouter, /def _apply_completed_stage_ids_to_plan/)
assert.match(storyBlocksRouter, /def _archive_unfinished_stages_for_closed_block/)
assert.match(storyBlocksRouter, /class StatusPayload[\s\S]*closeReason/)
assert.match(storyBlocksRouter, /def _stage_has_outline_or_chapter_refs/)
assert.match(storyBlocksRouter, /locked_stage_ids = await _locked_stage_ids\(pid, bid\)/)
assert.match(storyBlocksRouter, /completedStageIds[\s\S]*_apply_completed_stage_ids_to_plan/)
assert.match(
  storyBlocksRouter,
  /def _review_stage_continues/,
  'story block review must explicitly detect same-stage continuation'
)
assert.match(
  storyBlocksRouter,
  /def _default_completed_stage_ids_for_review/,
  'continue_current_block must default to completing the reviewed snapshot stage'
)
assert.match(
  storyBlocksRouter,
  /blockStageSnapshot[\s\S]*stageId/,
  'backend must read review.blockStageSnapshot.stageId when completedStageIds is omitted'
)
assert.match(
  storyBlocksRouter,
  /continue_current_block[\s\S]*_default_completed_stage_ids_for_review/,
  'continue_current_block should advance to the next stage unless stageContinues is true'
)
assert.match(storyBlocksRouter, /UPDATE story_blocks[\s\S]*stage_plan=%s[\s\S]*completed_stages=%s/)
assert.match(storyBlocksRouter, /status in \{"completed", "closed"\}[\s\S]*_archive_unfinished_stages_for_closed_block/)
assert.match(storyBlocksRouter, /stage\.get\("status"\) == "completed"[\s\S]*closed_unexecuted/)
assert.match(storyBlocksRouter, /stage_id in locked_stage_ids[\s\S]*status"\] = "locked"/)
assert.match(storyBlocksRouter, /closeReason[\s\S]*unknown/)
assert.match(storyBlocksRouter, /closeReasonWarning/)
assert.match(storyBlocksRouter, /block\.get\("status"\) != "active"[\s\S]*HTTPException\(409/)

const reviewFn = writerView.slice(
  writerView.indexOf('async function performStoryBlockReviewAfterFinalize'),
  writerView.indexOf('async function loadFinalizedVersionForPostprocess')
)
assert.match(reviewFn, /normalizeReviewForStageProgress/)
assert.match(reviewFn, /stageContinues/)
assert.match(reviewFn, /deriveNextStageSuggestion/)
assert.match(reviewFn, /const reviewedBlock = await loadStoryBlockAfterReview/)
assert.match(reviewFn, /review\.decision === 'continue_current_block'[\s\S]*stagePlan: reviewedBlock\.stagePlan/)
assert.match(reviewFn, /review\.decision === 'adjust_remaining_stages'[\s\S]*mergeForwardStagePlan\(reviewedBlock/)
assert.match(reviewFn, /review\.decision === 'open_new_block'[\s\S]*closeBlock/)

assert.match(stageList, /阶段不是章节/)
assert.match(stageList, /一章可以完成多个阶段/)
assert.match(stageList, /一个阶段也可以跨章节/)
assert.match(stageList, /planned[\s\S]*未执行/)
assert.match(stageList, /completed[\s\S]*已完成/)
assert.match(stageList, /closed[\s\S]*未执行，随块结束/)
assert.match(stageList, /skipped[\s\S]*未执行，随块结束/)
assert.match(stageList, /closed_unexecuted[\s\S]*未执行，随块结束/)
assert.match(stageList, /invalidated[\s\S]*已失效，随块结束/)
assert.match(stageList, /locked[\s\S]*已锁定/)
assert.match(stageList, /blockStatus/)
assert.match(stageList, /blockStatus[\s\S]*completed[\s\S]*closed/)
assert.match(stageList, /editable/)
assert.match(stageList, /已用于小纲/)
assert.match(stageList, /进行中/)
assert.match(stageList, /请到对应小纲中调整/)
assert.match(stageList, /emit\('editStage'/)
assert.match(stageList, /编辑/)
assert.match(storyBlockCard, /:block-status="block\.status"/)
assert.match(storyBlockCard, /editableStageCount/)
assert.match(storyBlockCard, /编辑未执行阶段/)
assert.match(storyBlockCard, /AI 更新后续阶段/)
assert.match(storyBlockCard, /结束并开启新块/)
assert.match(storyBlockCard, /当前块没有可更新的未执行阶段/)
assert.match(storyBlockCard, /props\.block\?\.status === 'active'|block\.status === 'active'/)
assert.doesNotMatch(storyBlockCard, /开启新故事块[\s\S]*isActiveBlock/)

console.log('story block stage status contract tests passed')

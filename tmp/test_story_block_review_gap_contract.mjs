import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const chaptersRouter = readFileSync('backend/routers/chapters.py', 'utf8')
const storyBlocksRouter = readFileSync('backend/routers/story_blocks.py', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const storyBlockStore = readFileSync('frontend/src/stores/storyBlockStore.js', 'utf8')
const storyBlockPanel = readFileSync('frontend/src/components/writer/StoryBlockPanel.vue', 'utf8')
const auditPrompt = readFileSync('frontend/src/prompts/audit.js', 'utf8')
const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')
const storyBlockPrompt = readFileSync('frontend/src/prompts/storyBlockPrompt.js', 'utf8')

const legacyAdjust = ['adjust', 'current', 'block'].join('_')
const obsoleteStatus = ['super', 'seded'].join('')
const obsoleteAuditHint = ['block', 'Review', 'Hint'].join('')
const forbiddenRuntimePattern = new RegExp(`${legacyAdjust}|${obsoleteStatus}`)

for (const source of [chaptersRouter, storyBlocksRouter, writerView, storyBlockStore, storyBlockPanel, auditPrompt, memoryStore, storyBlockPrompt]) {
  assert.doesNotMatch(source, forbiddenRuntimePattern)
}

assert.match(chaptersRouter, /async def _validate_story_block_snapshot_fields/)
assert.match(chaptersRouter, /_find_stage_by_id\(block\.get\("stage_plan"\), data\.blockStageId\)/)
assert.match(chaptersRouter, /"blockGoal"[\s\S]*block\.get\("goal"\)/)
assert.match(chaptersRouter, /"entryState"[\s\S]*block\.get\("entry_state"\)/)
assert.match(chaptersRouter, /"storyFunction"[\s\S]*block\.get\("story_function"\)/)
assert.match(chaptersRouter, /"mainPressure"[\s\S]*block\.get\("main_pressure"\)/)
assert.match(chaptersRouter, /"stagePurpose"[\s\S]*_pick_stage_value\(stage,\s*"purpose",\s*"stagePurpose",\s*"goal"\)/)
assert.match(chaptersRouter, /"stageAction"[\s\S]*_pick_stage_value\(stage,\s*"sceneOrAction",\s*"action",\s*"description"\)/)
assert.match(chaptersRouter, /"stageChoice"[\s\S]*_pick_stage_value\(stage,\s*"choice"\)/)
assert.match(chaptersRouter, /"stageCostOrConsequence"[\s\S]*_pick_stage_value\(stage,\s*"costOrConsequence",\s*"consequence",\s*"cost"\)/)
assert.match(chaptersRouter, /raise HTTPException\(400,\s*"blockStageSnapshot/)

assert.match(storyBlocksRouter, /@router\.post\("\/projects\/\{pid\}\/story-blocks\/\{bid\}\/confirm-review"\)/)
assert.match(storyBlocksRouter, /lock_state\["requiresReview"\]\s*=\s*False/)

assert.match(writerView, /function isStoryBlockReviewRequired/)
assert.match(writerView, /if \(block && isStoryBlockReviewRequired\(block\)\)[\s\S]*return null/)
assert.match(writerView, /async function handleConfirmStoryBlockReview/)
assert.match(writerView, /@confirm-block="handleConfirmStoryBlockReview"/)
assert.match(storyBlockStore, /async function confirmStoryBlockReview/)
assert.match(storyBlockStore, /api\.storyBlocks\.confirmReview/)
assert.match(storyBlockPanel, /confirmBlock/)
assert.match(storyBlockPanel, /requiresReview/)

assert.doesNotMatch(auditPrompt, new RegExp(obsoleteAuditHint))
assert.doesNotMatch(memoryStore, new RegExp(obsoleteAuditHint))
const reviewFn = writerView.slice(
  writerView.indexOf('async function performStoryBlockReviewAfterFinalize'),
  writerView.indexOf('async function loadFinalizedVersionForPostprocess')
)
assert.doesNotMatch(reviewFn, new RegExp(obsoleteAuditHint))

assert.match(storyBlockPrompt, /已定稿章节不得返回 split_unfinalized_content/)
assert.match(storyBlockPrompt, /carryOverToNextChapter/)
assert.match(reviewFn, /review\.decision === 'split_unfinalized_content'/)
assert.match(reviewFn, /carryOverToNextChapter/)
assert.match(reviewFn, /拆分建议已转为后续章节承接事项/)
assert.doesNotMatch(reviewFn, /editorContent\.value\s*=/)

console.log('story block review gap contract tests passed')

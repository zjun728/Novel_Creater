import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const storyBlocksRouter = readFileSync('backend/routers/story_blocks.py', 'utf8')
const chaptersRouter = readFileSync('backend/routers/chapters.py', 'utf8')

const legacyAdjust = ['adjust', 'current', 'block'].join('_')
const obsoleteStatus = ['super', 'seded'].join('')
const forbiddenRuntimePattern = new RegExp(`${legacyAdjust}|${obsoleteStatus}`)

assert.doesNotMatch(storyBlocksRouter, forbiddenRuntimePattern)
assert.doesNotMatch(chaptersRouter, forbiddenRuntimePattern)

assert.match(storyBlocksRouter, /async def _reject_existing_active_block/)
assert.match(storyBlocksRouter, /await _reject_existing_active_block\(pid\)/)
assert.match(storyBlocksRouter, /HTTPException\(409,\s*["'][^"']*active/)
assert.match(storyBlocksRouter, /async def _get_single_active_block/)
assert.match(storyBlocksRouter, /fetchall\([\s\S]*status='active'/)
assert.match(storyBlocksRouter, /len\(rows\)\s*>\s*1[\s\S]*HTTPException\(409/)

assert.match(chaptersRouter, /async def _validate_story_block_reference/)
assert.match(chaptersRouter, /await _validate_story_block_reference\(pid,\s*data,\s*cnum\)/)
assert.match(chaptersRouter, /SELECT \* FROM story_blocks[\s\S]*project_id=%s AND id=%s/)
assert.match(chaptersRouter, /block\.get\("status"\)\s*!=\s*"active"[\s\S]*HTTPException\(409/)
assert.match(chaptersRouter, /stage_plan/)
assert.match(chaptersRouter, /blockStageId[\s\S]*stage_ids[\s\S]*HTTPException\(400/)
assert.match(chaptersRouter, /blockStageSnapshot[\s\S]*storyBlockId[\s\S]*stageId/)
assert.match(chaptersRouter, /snapshot\.get\("storyBlockId"\)[\s\S]*data\.storyBlockId/)
assert.match(chaptersRouter, /snapshot\.get\("stageId"\)[\s\S]*data\.blockStageId/)

console.log('story block backend blocker contract tests passed')

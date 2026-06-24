import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'

assert.ok(existsSync('tmp/run_story_block_realistic_flow.mjs'), 'story block realistic flow script should exist')

const script = readFileSync('tmp/run_story_block_realistic_flow.mjs', 'utf8')
const legacyAdjust = ['adjust', 'current', 'block'].join('_')
const obsoleteStatus = ['super', 'seded'].join('')
const forbiddenRuntimePattern = new RegExp(`${legacyAdjust}|${obsoleteStatus}`)

assert.match(script, /tmp\/realistic-flow-qa/)
assert.match(script, /block_stage_snapshot/)
assert.match(script, /storyBlockId/)
assert.match(script, /createdCleanProject/)
assert.match(script, /usesArchivedReports:\s*false/)
assert.match(script, /adjust_remaining_stages/)
assert.match(script, /split_unfinalized_content/)
assert.doesNotMatch(script, forbiddenRuntimePattern)
assert.doesNotMatch(script, /tmp\/archive\/2026-06-17\/realistic-flow-qa/)

console.log('story block realistic flow contract tests passed')

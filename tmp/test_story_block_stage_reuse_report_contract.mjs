import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(
  liveScript,
  /story_block_stage_reuse_detected/,
  'live report must classify repeated story block stage as story_block_stage_reuse_detected'
)
assert.match(
  liveScript,
  /new Error\([\s\S]*story_block_stage_reuse_detected/,
  'stage reuse throw site must attach the specific blocker code'
)
assert.doesNotMatch(
  liveScript,
  /第 \$\{chapterNum\} 章无理由复用已完成阶段 \$\{entry\.blockStageId\}`\)/,
  'stage reuse must not throw a plain generic Error without a blocker code'
)

console.log('story block stage reuse report contract tests passed')

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(liveScript, /evidence_contradiction/)
assert.match(liveScript, /normalizeCompletionEvidenceForStageSplit/)
assert.match(
  liveScript,
  /completedStageCount[\s\S]*stageCount[\s\S]*closedUnexecutedStageCount[\s\S]*所有阶段|所有阶段[\s\S]*completedStageCount[\s\S]*closedUnexecutedStageCount/,
  'live report should scan completionEvidence for all-stage-complete contradictions'
)
assert.match(
  liveScript,
  /块目标达成，剩余阶段随块关闭/,
  'contradictory completion evidence should be corrected to a stage-split-safe phrase'
)

console.log('story block completion evidence contradiction contract tests passed')

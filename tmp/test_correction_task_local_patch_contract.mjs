import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const board = readFileSync('frontend/src/components/correction/CorrectionTaskBoard.vue', 'utf8')

const singleBlock = board.match(/async function createChapterRevisionDraft\(task\) \{[\s\S]*?\n\}/)?.[0] || ''
const batchBlock = board.match(/async function createChapterRevisionDraftBatch\(task\) \{[\s\S]*?\n\}/)?.[0] || ''

assert.match(singleBlock, /generateLocalCorrectionPatchCandidate/)
assert.doesNotMatch(singleBlock, /generateCorrectionDraft/)
assert.match(batchBlock, /generateLocalCorrectionPatchCandidate/)
assert.doesNotMatch(batchBlock, /generateCorrectionDraft/)

assert.match(board, /function correctionTaskToPatchIssue/)
assert.match(board, /function correctionTasksToPatchIssues/)
assert.match(board, /局部修订候选/)

console.log('correction task local patch contract tests passed')

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

const runStart = source.indexOf('async function runChapter(')
const compressLoopIndex = source.indexOf('for (let compressAttempt = 1; draftCount > range.hardMax && compressAttempt <= 2; compressAttempt += 1)', runStart)
const secondRetryNoteIndex = source.indexOf('第 ${chapterNum} 章第 ${compressAttempt} 次压缩后仍过长', runStart)
const selectionIndex = source.indexOf('const selectedCandidate = chooseBestChapterCandidate(project, compressionCandidates)', runStart)
const compressedGateIndex = source.indexOf("throw buildChapterWordGateError(project, chapterNum, lastCandidate.count, 'compressed_retry')", runStart)

assert.ok(runStart > -1, 'runChapter should exist')
assert.ok(compressLoopIndex > runStart, 'runChapter should allow two compression attempts')
assert.ok(secondRetryNoteIndex > compressLoopIndex, 'first failed compression should feed a second compression attempt')
assert.ok(selectionIndex > secondRetryNoteIndex, 'compressed retry should select the best saved candidate before gating')
assert.ok(compressedGateIndex > selectionIndex, 'compressed retry should gate only after retry and candidate selection fail')

console.log('realistic QA compression retry contract tests passed')

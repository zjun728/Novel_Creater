import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(source, /function isChapterWordCountTooFarForQaStop\(project, count\)/)
assert.match(source, /const qaStopMin = Math\.round\(range\.target \* 0\.65\)/)
assert.match(source, /const qaStopMax = Math\.round\(range\.target \* 1\.4\)/)

const runChapterStart = source.indexOf('async function runChapter(')
const assessIndex = source.indexOf('if (!assessChapterWordCount(project, chapterNum, draftCount', runChapterStart)
const auditIndex = source.indexOf('const audit = await auditChapter', runChapterStart)

assert.ok(assessIndex > runChapterStart, 'QA should assess final candidate word count before audit')
assert.ok(auditIndex > assessIndex, 'near word-count misses should continue to audit/finalize flow')

const assessStart = source.indexOf('function assessChapterWordCount(')
const assessEnd = source.indexOf('function isChapterWordCountInHardRange', assessStart)
const assessBlock = source.slice(assessStart, assessEnd)
assert.match(assessBlock, /isChapterWordCountTooFarForQaStop\(project, count\)/)
assert.match(assessBlock, /isChapterWordCountInHardRange\(project, count\)/)

console.log('realistic QA near word range continue contract tests passed')

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const script = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(
  script,
  /async function compressLongChapterContent/,
  'realistic QA should compress over-expanded chapter drafts before stopping the 20-chapter run'
)

assert.match(
  script,
  /compressed_retry/,
  'compressed retry word count should be recorded separately from first/expanded drafts'
)

assert.match(
  script,
  /第 \$\{chapterNum\} 章压缩稿/,
  'compressed retry should be saved as its own candidate version for traceability'
)

assert.match(
  script,
  /draftContent = compressedContent/,
  'runChapter should continue audit/finalize with the compressed draft when it passes the hard gate'
)

const runChapterStart = script.indexOf('async function runChapter(')
const compressGateIndex = script.indexOf('for (let compressAttempt = 1; draftCount > range.hardMax && compressAttempt <= 2; compressAttempt += 1)', runChapterStart)
const auditIndex = script.indexOf('const audit = await auditChapter', runChapterStart)
assert.ok(compressGateIndex > runChapterStart, 'runChapter should check for too-long chosen drafts')
assert.ok(auditIndex > compressGateIndex, 'too-long compression should run before audit/finalize work')

console.log('realistic QA long draft compression contract tests passed')

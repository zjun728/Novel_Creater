import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const script = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(
  script,
  /async function expandShortChapterContent/,
  'realistic QA should retry clearly too-short drafts before stopping the 20-chapter run'
)

assert.match(
  script,
  /expanded_retry/,
  'expanded retry word count should be recorded separately from the first draft'
)

assert.match(
  script,
  /for \(let expandAttempt = 1; expandAttempt <= 2; expandAttempt \+= 1\)/,
  'realistic QA should allow a second expansion pass when the first补足稿 is still too short'
)

assert.match(
  script,
  /第 \$\{chapterNum\} 章补足稿 \$\{expandAttempt\}/,
  'expanded retry should be saved as its own candidate version for traceability'
)

assert.match(
  script,
  /draftContent = expandedContent/,
  'runChapter should continue audit/finalize with the expanded draft when it passes the hard gate'
)

assert.doesNotMatch(
  script,
  /assessChapterWordCount\(project, chapterNum, count, '初稿'\)[\s\S]*return content\.trim\(\)/,
  'initial generation should not permanently fail the report before the short-draft retry has a chance to recover'
)

console.log('realistic QA short draft retry contract tests passed')

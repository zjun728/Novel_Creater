import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const script = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

assert.match(
  script,
  /buildChapterTitleSystemPrompt/,
  'realistic QA should reuse the same chapter title prompt as the frontend'
)

assert.match(
  script,
  /cleanGeneratedChapterTitle/,
  'realistic QA should apply the same chapter title cleaner as the frontend'
)

const titleHelperStart = script.indexOf('async function generateRealisticQaChapterTitle(')
assert.ok(titleHelperStart > -1, 'realistic QA should have a title generation helper')

const finalizeStart = script.indexOf('async function finalizeChapter(')
assert.ok(finalizeStart > -1, 'finalizeChapter should exist')

const finalizeBlockEnd = script.indexOf('\n}\n\nasync function runChapter', finalizeStart)
const finalizeBlock = script.slice(finalizeStart, finalizeBlockEnd)

assert.match(
  finalizeBlock,
  /await generateRealisticQaChapterTitle\(project,\s*provider,\s*chapter,\s*version,\s*summary/,
  'realistic QA should generate a chapter title before finalizing'
)

const titleBeforeFinalize = finalizeBlock.indexOf('await generateRealisticQaChapterTitle')
const requestFinalize = finalizeBlock.indexOf("await request('POST', `/projects/${project.id}/chapters/${chapter.id}/versions/${version.id}/finalize`")
assert.ok(
  titleBeforeFinalize > -1 && requestFinalize > titleBeforeFinalize,
  'chapter title should be written before the backend finalizes and locks the chapter'
)

console.log('REALISTIC_QA_CHAPTER_TITLE_CONTRACT_OK')

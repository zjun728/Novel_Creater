import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const chapterPrompt = readFileSync('frontend/src/prompts/chapter.js', 'utf8')

assert.match(
  writerView,
  /const recentChapterEndings = ref\(\[\]\)/,
  'writer view should keep recent chapter endings for anti-template generation context'
)

assert.match(
  writerView,
  /async function loadRecentChapterEndings\(/,
  'writer view should load multiple recent finalized chapter endings, not only the immediately previous chapter'
)

assert.match(
  writerView,
  /result\.context\.recentChapterEndings = recentChapterEndings\.value/,
  'writer view should pass recent chapter endings into the generation context'
)

assert.match(
  chapterPrompt,
  /context\.recentChapterEndings/,
  'chapter prompt should consume recentChapterEndings from generation context'
)

console.log('recent chapter endings context contract tests passed')

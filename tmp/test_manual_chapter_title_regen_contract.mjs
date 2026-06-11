import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

assert.match(
  writerStore,
  /async function generateDefaultChapterTitle\(projectId, chapter, chapterNum, content, context, provider, options = \{\}\)/,
  'chapter title generator should accept options for manual forced regeneration'
)
assert.match(
  writerStore,
  /options\.force/,
  'chapter title generator should allow forcing a new title even when a custom title already exists'
)
assert.match(
  writerView,
  /const chapterTitleGenerating = ref\(false\)/,
  'writer desk should track manual chapter title generation loading state'
)
assert.match(
  writerView,
  /async function handleGenerateChapterTitle\(\)/,
  'writer desk should expose a manual chapter title generation handler'
)
assert.match(
  writerView,
  /generateDefaultChapterTitle\([\s\S]*force:\s*true/,
  'manual title handler should force metadata-only regeneration'
)
assert.match(
  writerView,
  /重生成章名|生成章名/,
  'writer desk should render a visible title generation button'
)

console.log('manual chapter title regeneration contract passed')

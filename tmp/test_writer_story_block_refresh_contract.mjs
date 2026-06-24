import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

const ensureReadyMatch = writerView.match(/async function ensureStoryBlockReady[\s\S]*?\n}\n\nfunction isStoryBlockReviewRequired/)
assert.ok(ensureReadyMatch, 'WriterView must define ensureStoryBlockReady')
const ensureReady = ensureReadyMatch[0]
assert.match(
  ensureReady,
  /await storyBlockStore\.loadBlocks\(projectId\.value\)/,
  '小纲/正文生成前必须刷新 storyBlockStore.loadBlocks(projectId)'
)
assert.ok(
  ensureReady.indexOf('await storyBlockStore.loadBlocks(projectId.value)') < ensureReady.indexOf('activeStoryBlock.value'),
  'ensureStoryBlockReady must refresh before reading cached activeStoryBlock'
)
assert.doesNotMatch(
  ensureReady,
  /activeStoryBlock\.value\s*\|\|\s*await storyBlockStore\.loadActiveBlock/,
  'ensureStoryBlockReady must not prefer stale cached activeBlock'
)

const loadChapterMatch = writerView.match(/async function loadChapter[\s\S]*?\n}\n\nasync function loadPreviousChapterEnding/)
assert.ok(loadChapterMatch, 'WriterView must define loadChapter')
assert.match(
  loadChapterMatch[0],
  /await storyBlockStore\.loadBlocks\(projectId\.value\)/,
  '切换章节/加载章节时必须刷新 story blocks，避免下一章沿用旧 active block'
)

const captureMatch = writerView.match(/function captureCurrentBlockStageSnapshot[\s\S]*?\n}\n\nasync function ensureBeatPlan/)
assert.ok(captureMatch, 'WriterView must define captureCurrentBlockStageSnapshot')
assert.match(
  captureMatch[0],
  /throw new Error\([^)]*故事块[^)]*阶段/,
  'captureCurrentBlockStageSnapshot must fail loudly when there is no editable stage'
)

console.log('writer story block refresh contract tests passed')

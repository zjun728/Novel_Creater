import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = file => readFileSync(file, 'utf8')
const getFunctionBlock = (source, name) => {
  const start = source.indexOf(`function ${name}`)
  if (start === -1) return ''
  const next = source.indexOf('\nfunction ', start + 1)
  return source.slice(start, next === -1 ? source.length : next)
}
const getExportFunctionBlock = (source, name) => {
  const start = source.indexOf(`export function ${name}`)
  if (start === -1) return ''
  const next = source.indexOf('\nexport function ', start + 1)
  return source.slice(start, next === -1 ? source.length : next)
}

const settingsPrompt = read('frontend/src/prompts/settingsFromBible.js')
const fallbackBlock = getFunctionBlock(settingsPrompt, 'buildFallbackRawEvents')
const oldStoryTerms = [
  '沈苍',
  '吕岳',
  '昴日星官',
  '三界同僚工作群',
  '神仙工作群',
  '打破派',
  '封渊君'
]
for (const term of oldStoryTerms) {
  assert.ok(!fallbackBlock.includes(term), `settings fallback must not hard-code old test story term: ${term}`)
}
assert.match(
  settingsPrompt,
  /extractCandidateEntityNames|extractGenericCandidateNames/,
  'settings fallback should use generic candidate-name extraction instead of old-project name lists'
)

const writerView = read('frontend/src/views/WriterView.vue')
assert.match(
  writerView,
  /pendingCanonFacts/,
  'writer view should compute pending canon facts so memory confirmation can gate generation'
)
assert.match(
  writerView,
  /ensureNoPendingStoryMemory|ensureNoPendingMemoryChanges/,
  'writer view should expose a pending-memory guard before AI generation'
)
assert.match(
  writerView,
  /pendingCanonFacts[\s\S]{0,800}正文生成|ensureNoPendingStoryMemory\('正文生成'\)/,
  'chapter generation should be blocked when pending story memory exists'
)

const chapterPrompt = read('frontend/src/prompts/chapter.js')
const buildChapterPromptBlock = getExportFunctionBlock(chapterPrompt, 'buildChapterPrompt')
assert.ok(
  !buildChapterPromptBlock.includes('## 禁止方向'),
  'chapter drafting prompt should not inject full forbidden-direction checklist; audit can enforce it later'
)
assert.ok(
  !buildChapterPromptBlock.includes('## 未完成纠偏任务'),
  'chapter drafting prompt should not inject full correction-task text; only short soft-transition aims are allowed'
)
assert.ok(
  !buildChapterPromptBlock.includes('## 题材/风格标准'),
  'chapter drafting prompt should not inject full writing-standard checklist'
)
assert.match(
  buildChapterPromptBlock,
  /创作边界摘要|本章创作边界/,
  'chapter drafting prompt should replace heavy rule dumps with a compact creative-boundary section'
)

const contextBuilder = read('frontend/src/utils/contextBuilder.js')
assert.ok(
  !/builder\.add\('volumeStage'[\s\S]{0,120}required:\s*true/.test(contextBuilder),
  'volume-stage context should not be required in drafting context'
)
assert.ok(
  !/builder\.add\('worldRules'[\s\S]{0,120}required:\s*true/.test(contextBuilder),
  'world rules should be summarized into drafting context instead of required as a full hard block'
)
assert.match(
  contextBuilder,
  /creativeBoundary|draftingBoundary|styleMethodBrief/,
  'context builder should expose a compact drafting boundary/style method for chapter generation'
)

console.log('quality-first generation contract ok')

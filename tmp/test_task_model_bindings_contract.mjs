import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')

assert.match(writerStore, /async function resolveTaskProvider\(/)

const expectations = [
  ['generateChapterBeatPlan', /\['outlineModelId', 'writingModelId'\]/],
  ['generateChapter', /\['writingModelId'\]/],
  ['generateCorrectionDraft', /\['polishModelId', 'auditModelId', 'writingModelId'\]/],
  ['generateLocalCorrectionPatchCandidate', /\['polishModelId', 'auditModelId', 'writingModelId'\]/],
  ['continueWriting', /\['writingModelId'\]/],
  ['generateMultiVariants', /\['writingModelId'\]/],
  ['rewriteSelection', /\['polishModelId', 'writingModelId'\]/],
  ['expandText', /\['polishModelId', 'writingModelId'\]/],
  ['compressText', /\['polishModelId', 'summaryModelId', 'writingModelId'\]/],
  ['generateDefaultChapterTitle', /\['summaryModelId', 'writingModelId'\]/]
]

for (const [fnName, keyPattern] of expectations) {
  const match = writerStore.match(new RegExp(`async function ${fnName}\\([\\s\\S]*?\\n  \\}`))
  assert.ok(match, `missing ${fnName}`)
  assert.match(match[0], /resolveTaskProvider\(/, `${fnName} should resolve provider through task bindings`)
  assert.match(match[0], keyPattern, `${fnName} should use the expected binding fallback order`)
}

console.log('task model binding contract tests passed')

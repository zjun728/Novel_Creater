import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')

const localRevisionBlock = writerStore.match(
  /async function generateLocalCorrectionPatchCandidate\([\s\S]*?\n  \}/
)?.[0] || ''

assert.match(localRevisionBlock, /applyLocalRevisionPatches/)
assert.doesNotMatch(localRevisionBlock, /generateAuditRevisionFallbackDraft/)
assert.match(localRevisionBlock, /AI 没有返回可安全应用的局部修订补丁/)

console.log('audit revision fallback contract tests passed')

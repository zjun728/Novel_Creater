import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const script = readFileSync('tmp/run_realistic_longform_flow.mjs', 'utf8')

const reviseBlock = script.match(/async function reviseChapter\([\s\S]*?\n\}/)?.[0] || ''
assert.match(reviseBlock, /extractLocalRevisionPatches|applyLocalRevisionPatches/)
assert.match(reviseBlock, /局部补丁|局部修订/)
assert.doesNotMatch(reviseBlock, /修订后的完整正文/)

console.log('realistic QA local patch revision contract tests passed')

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

assert.match(writerView, /beginChapterFinalizationRun/)
assert.match(writerView, /endChapterFinalizationRun/)

const performFinalizeBlock = writerView.match(/async function performFinalize\(version\) \{[\s\S]*?\n\}/)?.[0] || ''
assert.match(performFinalizeBlock, /beginChapterFinalizationRun/)
assert.match(performFinalizeBlock, /endChapterFinalizationRun/)
assert.match(performFinalizeBlock, /memoryProcessing\.value\s*=\s*true[\s\S]*writerStore\.finalizeVersion/)

assert.match(writerView, /:disabled="auditRunning \|\| auditRevisionGenerating \|\| finalizationActionBusy"/)

console.log('writer finalization lock contract tests passed')

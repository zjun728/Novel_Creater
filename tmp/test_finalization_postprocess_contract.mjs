import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const finalizationGuard = readFileSync('frontend/src/utils/finalizationGuard.js', 'utf8')

const processBlock = memoryStore.match(/async function processChapterFinalization\([\s\S]*?\n  \}/)?.[0] || ''
assert.match(processBlock, /errors:\s*\[\]/)
assert.match(processBlock, /recordFinalizationStepError/)
assert.match(processBlock, /requiredFailures/)

const performBlock = writerView.match(/async function performFinalize\(version\) \{[\s\S]*?\n\}/)?.[0] || ''
assert.match(performBlock, /let finalizationCompleted\s*=\s*false/)
assert.match(performBlock, /let chapterFinalized\s*=\s*false/)
assert.match(performBlock, /results\.errors\?\.length/)
assert.match(performBlock, /finalizationCompleted\s*=\s*true/)
assert.match(performBlock, /keepPending:\s*chapterFinalized && !finalizationCompleted/)

assert.match(finalizationGuard, /keepPending/)
assert.match(finalizationGuard, /if \(!options\.keepPending\)/)

console.log('finalization postprocess contract tests passed')

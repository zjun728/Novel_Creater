import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const finalizationGuard = readFileSync('frontend/src/utils/finalizationGuard.js', 'utf8')
const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')

assert.match(finalizationGuard, /allowExistingPending/)
assert.match(finalizationGuard, /existingMarker && !options\.allowExistingPending/)

assert.match(writerView, /const finalizationRetrying = ref\(false\)/)
assert.match(writerView, /const blockingFinalizationPending = computed\(\(\) => findBlockingFinalizationPending\(\)\)/)
assert.match(writerView, /async function loadFinalizedVersionForPostprocess\(targetChapterNum\)/)
assert.match(writerView, /async function retryFinalizationPostprocess\(targetChapterNum\)/)
assert.match(writerView, /allowExistingPending:\s*true/)
assert.match(writerView, /processChapterFinalization\(projectId\.value, version\.content, num\)/)
assert.match(writerView, /keepPending:\s*!completed/)
assert.match(writerView, /v-if="blockingFinalizationPending"/)
assert.match(writerView, /retryFinalizationPostprocess\(blockingFinalizationPending\.chapterNum\)/)

assert.match(memoryStore, /function canonFactDedupKey\(fact\)/)
assert.match(memoryStore, /await novelStore\.loadCanonFacts\(projectId\)/)
assert.match(memoryStore, /existingFactKeys\.has\(factKey\)/)
assert.match(memoryStore, /existingFactKeys\.add\(factKey\)/)
assert.match(
  memoryStore,
  /event\.status !== 'rejected'/,
  'finalization retry should not recreate setting changes that already exist in pending or accepted states'
)

console.log('finalization retry contract passed')

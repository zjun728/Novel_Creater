import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const finalizationGuard = readFileSync('frontend/src/utils/finalizationGuard.js', 'utf8')
const memoryStore = readFileSync('frontend/src/stores/memoryStore.js', 'utf8')

assert.match(finalizationGuard, /allowExistingPending/)
assert.match(finalizationGuard, /existingMarker && !options\.allowExistingPending/)

assert.match(writerView, /const finalizationRetrying = ref\(false\)/)
assert.match(writerView, /const finalizationMarkerVersion = ref\(0\)/)
assert.match(
  writerView,
  /const blockingFinalizationPending = computed\(\(\) => \{[\s\S]*finalizationMarkerVersion\.value[\s\S]*return findBlockingFinalizationPending\(\)[\s\S]*\}\)/
)
assert.match(writerView, /function upsertDurableFinalizationMarker\(marker\)/)
assert.match(writerView, /function removeDurableFinalizationMarker\(targetChapterNum,\s*marker\)/)
assert.match(writerView, /async function loadFinalizedVersionForPostprocess\(targetChapterNum\)/)
assert.match(writerView, /async function retryFinalizationPostprocess\(targetChapterNum\)/)
assert.match(writerView, /const localMarker = getChapterFinalizationPending\(projectId\.value,\s*num\)/)
assert.match(writerView, /const durableMarker = findDurableFinalizationPending\(num\)/)
assert.match(writerView, /const marker = localMarker \|\| durableMarker/)
assert.match(writerView, /const durableCloseoutRunId = marker\.runId \|\| marker\.run_id \|\| finalizationRun\?\.runId \|\| ''/)
assert.match(writerView, /const durableCloseoutFinalizationId = marker\.finalizationId \|\| marker\.finalization_id \|\| finalizationRun\?\.finalizationId \|\| ''/)
assert.match(writerView, /if \(!marker\) \{[\s\S]*没有待重试的定稿后处理[\s\S]*return[\s\S]*\}/)
assert.match(writerView, /allowExistingPending:\s*true/)
assert.match(writerView, /processChapterFinalization\(projectId\.value,\s*version\.content,\s*num,\s*\{[\s\S]*sourceVersionId:\s*version\.id[\s\S]*runId:\s*finalizationRun\.runId[\s\S]*finalizationId:\s*finalizationRun\.finalizationId[\s\S]*\}\)/)
assert.match(writerView, /runId:\s*durableCloseoutRunId/)
assert.match(writerView, /finalizationId:\s*durableCloseoutFinalizationId/)
assert.match(writerView, /\} catch \(durableSaveError\) \{[\s\S]*console\.warn\('Durable finalization marker save failed'[\s\S]*\}\s*if \(completed\) removeDurableFinalizationMarker\(num,\s*marker\)/)
assert.match(writerView, /saveDurableFinalizationMarker\(num,\s*\{[\s\S]*commitStatus:\s*completed \? 'committed' : 'failed_after_chapter_commit'[\s\S]*\}\)/)
assert.match(writerView, /keepPending:\s*!completed/)
assert.match(writerView, /sourceVersionId:\s*retryVersionId,[\s\S]*runId:\s*finalizationRun\.runId,[\s\S]*finalizationId:\s*finalizationRun\.finalizationId/)
assert.match(writerView, /getFinalizationMarkerAction/)
assert.match(writerView, /finalizationMarkerAction\.canRetryPostprocess/)
assert.match(writerView, /v-if="blockingFinalizationPending && finalizationMarkerAction\.canRetryPostprocess"/)
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

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const store = readFileSync('frontend/src/stores/volumeStore.js', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

for (const field of [
  'parsedVolumeCount',
  'normalizedVolumeCount',
  'droppedVolumes',
  'dropReason',
  'saveAttempted',
  'savedVolumeCount',
  'saveErrors',
  'failureStage',
  'parsedCandidateSource',
  'parsedCandidateType',
  'parsedFirstItemType',
  'parsedFirstItemKeys',
  'rejectedParsedCandidates'
]) {
  assert.match(store, new RegExp(field), `volume planning diagnostics should include ${field}`)
}

assert.match(
  store,
  /normalizeGeneratedVolumesWithDiagnostics/,
  'normalization should return both normalized volumes and droppedVolumes diagnostics'
)
assert.match(
  store,
  /truncateVolumeField/,
  'normalization should truncate overlong model fields instead of dropping valid volumes'
)
assert.match(
  store,
  /volume_plan_normalize_empty/,
  'normalize-empty failures should use volume_plan_normalize_empty'
)
assert.match(
  store,
  /volume_plan_save_failed/,
  'save failures should use volume_plan_save_failed'
)
assert.match(
  store,
  /volume_plan_parse_failed/,
  'parse failures should use volume_plan_parse_failed'
)
assert.match(
  store,
  /repairTriggered[\s\S]*compactRetryTriggered/,
  'parse failures should trigger repair and compact retry diagnostics'
)

assert.match(
  liveScript,
  /classifyVolumePlanningFailureCode/,
  'live script should classify volume planning failures from diagnostics'
)
assert.doesNotMatch(
  liveScript,
  /code:\s*['"]volume_planning['"][\s\S]*volume plan failure dialog/,
  'volume plan failure dialog should not always become generic volume_planning'
)
for (const code of [
  'volume_plan_parse_failed',
  'volume_plan_normalize_empty',
  'volume_plan_save_failed',
  'volume_plan_ui_wait_failed'
]) {
  assert.match(liveScript, new RegExp(code), `live blocker should support ${code}`)
}

assert.match(
  store,
  /diagnostics\.parsedVolumeCount\s*=\s*parsed\?\.volumes\?\.length/,
  'parse diagnostics should record the actual number of parsed volumes, including legal 8-volume JSON'
)
for (const reason of [
  'nested_array_not_volume_plan',
  'array_items_not_volume_objects',
  'object_missing_volumes',
  'volume_like_validation_failed'
]) {
  assert.match(store, new RegExp(reason), `parser diagnostics should record ${reason}`)
}
assert.match(
  store,
  /validateVolumePlanRoot/,
  'parser should validate candidate root shape before accepting it as a volume plan'
)
assert.match(
  store,
  /isVolumeLikeObject/,
  'parser should reject arrays whose items do not look like volume objects'
)

console.log('volume plan diagnostics contract tests passed')

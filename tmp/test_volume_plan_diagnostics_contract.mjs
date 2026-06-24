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
  'failureStage'
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

console.log('volume plan diagnostics contract tests passed')

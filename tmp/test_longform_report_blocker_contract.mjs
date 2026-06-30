import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(liveScript, /function pendingHardConflictDiagnostics/)
for (const field of [
  'entityName',
  'fieldPath',
  'oldValue',
  'newValue',
  'classification',
  'fieldTier',
  'suggestedRehomeTarget',
  'whyBlocked',
  'classificationConflictDiagnostic'
]) {
  assert.match(liveScript, new RegExp(field), `hard conflict report must include ${field}`)
}
assert.match(
  liveScript,
  /function settingClassificationConflictDiagnostic/,
  'live report must diagnose hard_conflict entries whose whyBlocked already describes reveal/refinement'
)

assert.match(liveScript, /function syncHardConflictBlockerFromFlow/)
assert.match(
  liveScript,
  /settings_confirmation_failed[\s\S]*syncHardConflictBlockerFromFlow\(/,
  'settings confirmation failures must sync top-level blocker from flow event'
)
assert.match(
  liveScript,
  /report\.acceptance\.reason\s*=\s*report\.blocker\.message/,
  'top-level blocker message must drive acceptance.reason'
)
assert.match(
  liveScript,
  /hard_conflict_setting_review_required[\s\S]*pendingHardConflicts/,
  'hard setting blocker must preserve pending hard conflict diagnostics'
)

console.log('longform report blocker contract tests passed')

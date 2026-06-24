import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(
  liveScript,
  /function syncReportBlockerFromFlowEvents\(/,
  'live report writer should have a top-level blocker sync pass'
)
assert.match(
  liveScript,
  /function writeReport\(\)\s*\{\s*syncReportBlockerFromFlowEvents\(\)/,
  'writeReport must sync blocker before writing latest report artifacts'
)
assert.match(
  liveScript,
  /settings_confirmation_failed[\s\S]*hard_conflict_setting_review_required[\s\S]*report\.blocker/,
  'settings hard conflict flow events must be promoted to report.blocker'
)
assert.match(
  liveScript,
  /report\.acceptance\.reason\s*=\s*report\.blocker\.message/,
  'promoted blocker must populate acceptance.reason'
)

console.log('live report blocker integrity contract tests passed')

import assert from 'node:assert/strict'
import fs from 'node:fs'

const source = fs.readFileSync('tmp/story_humanity_rerun_21_25.mjs', 'utf8')

assert.match(
  source,
  /function\s+extractShortDraftDiagnostics/,
  'story humanity report should extract short draft diagnostics from live chapter flow events'
)

assert.match(
  source,
  /below_hard_min_auto_regenerate_succeeded/,
  'short draft diagnostics should read the successful full-regenerate event'
)

assert.match(
  source,
  /shortDraftStrategy[\s\S]*expansionAccepted[\s\S]*factDriftCheck[\s\S]*endingPreserved/,
  'story report should expose shortDraftStrategy, expansionAccepted, factDriftCheck, and endingPreserved'
)

console.log('story humanity short draft report contract passed')

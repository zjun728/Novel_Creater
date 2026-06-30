import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const runtimeConfig = readFileSync('tmp/live-qa/runners/live-runner-runtime-config.mjs', 'utf8')

assert.match(
  liveScript,
  /async function collectDirtyDataWritten/,
  'dirtyDataWritten must be collected from live API state, not inferred from chapterReports'
)
assert.match(
  liveScript,
  /\/projects\/\$\{report\.project\.id\}\/chapters/,
  'dirtyDataWritten.chapters must query actual chapters'
)
assert.match(
  liveScript,
  /\/projects\/\$\{report\.project\.id\}\/story-blocks/,
  'dirtyDataWritten.storyBlocks must query actual story blocks'
)
assert.match(
  liveScript,
  /await fail\(/,
  'failure reporting must await live dirty-data collection before writing the report'
)
assert.match(
  liveScript,
  /const PHASE_TARGET = runtimeConfig\.phaseTarget/,
  'live script must use centralized runtime config for temporary smaller phase targets'
)
assert.match(
  runtimeConfig,
  /env\.PHASE_TARGET/,
  'runtime config must allow a temporary smaller phase target for 1-3 chapter post-fix validation while keeping default target centralized'
)
assert.doesNotMatch(
  liveScript,
  /chapters:\s*report\.chapterReports\.length\s*>\s*0/,
  'dirtyDataWritten.chapters must not be inferred from collected chapterReports'
)

console.log('longform live dirty-data report contract tests passed')

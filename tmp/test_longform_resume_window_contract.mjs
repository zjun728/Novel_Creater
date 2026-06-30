import assert from 'node:assert/strict'
import fs from 'node:fs'
import { buildLiveRunnerRuntimeConfig } from './live-qa/runners/live-runner-runtime-config.mjs'

const source = fs.readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const configSource = fs.readFileSync('tmp/live-qa/runners/live-runner-runtime-config.mjs', 'utf8')

assert.match(
  source,
  /const RESUME_CHAPTER_WINDOW = runtimeConfig\.resumeChapterWindow/,
  'resumed live runs should use a window size instead of a fixed end chapter'
)
assert.match(
  configSource,
  /startChapter\s*\+\s*resumeChapterWindow\s*-\s*1/,
  'resumed live run cap should resolve to START_CHAPTER + window - 1'
)
assert.doesNotMatch(
  source,
  /START_CHAPTER\s*>\s*1\s*\?\s*30\s*:/,
  'resumed live run cap must not be hard-coded to chapter 30'
)

const resumed = buildLiveRunnerRuntimeConfig({
  env: {
    EXISTING_PROJECT_ID: 'p1',
    START_CHAPTER: '88',
    PHASE_TARGET: '95',
    RESUME_CHAPTER_WINDOW: '5'
  }
})
assert.equal(resumed.maxPhaseTarget, 92)
assert.equal(resumed.phaseTarget, 92)
assert.equal(resumed.runChapterCount, 5)

console.log('longform resume window contract passed')

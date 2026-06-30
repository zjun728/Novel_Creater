import fs from 'node:fs'
import assert from 'node:assert/strict'

const writerStore = fs.readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const liveRunner = fs.readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

const ensureQualityMatch = writerStore.match(
  /async function ensureChapterBeatPlanQuality[\s\S]*?\n  }\n\n  function applyDerivedBeatPlanFallback/
)
assert.ok(ensureQualityMatch, 'writerStore should expose ensureChapterBeatPlanQuality before derived fallback')
const ensureQualityBody = ensureQualityMatch[0]

assert.match(
  ensureQualityBody,
  /beat_plan_empty_after_quality_cleaning/,
  'empty beat plans after cleaning should get a specific failure code, not a generic Error'
)
assert.match(
  ensureQualityBody,
  /buildBeatPlanQualityDiagnostics[\s\S]*failureCode:\s*'beat_plan_empty_after_quality_cleaning'/,
  'empty beat plans after cleaning should preserve quality diagnostics'
)

const generateMatch = writerStore.match(
  /async function generateChapterBeatPlan[\s\S]*?\n    } finally \{\n      beatPlanning\.value = false\n    }\n  \}/
)
assert.ok(generateMatch, 'writerStore should expose generateChapterBeatPlan')
const generateBody = generateMatch[0]

assert.match(
  generateBody,
  /beat_plan_empty_after_quality_cleaning[\s\S]*applyDerivedBeatPlanFallback/,
  'generateChapterBeatPlan should recover empty quality output through story-block-derived fallback'
)
assert.match(
  generateBody,
  /derivedFallbackTriggered[\s\S]*saveBeatPlanDiagnostics/,
  'the empty-quality fallback path should persist diagnostics for the runner'
)

const waitMatch = liveRunner.match(/async function waitForSavedBeatPlan[\s\S]*?\n}\n\nasync function waitForGeneratedChapterVersion/)
assert.ok(waitMatch, 'live runner should expose waitForSavedBeatPlan')
const waitBody = waitMatch[0]

assert.match(
  waitBody,
  /readBeatPlanDiagnostics\(page,\s*chapterNum\)[\s\S]*summarizeBeatPlanPromptDiagnostics/,
  'beat-plan wait timeout/failure diagnostics should read local beat-plan diagnostics'
)
assert.match(
  waitBody,
  /小纲生成失败[\s\S]*小纲为空/,
  'runner should detect the actual visible empty-beat-plan failure instead of waiting for the full timeout'
)
assert.match(
  waitBody,
  /promptChars[\s\S]*promptTokensApprox[\s\S]*finalFailureAfterRecovery/,
  'beat-plan saved blocker should include prompt, recovery, and final failure diagnostics'
)

console.log('beat plan empty quality fallback contract passed')

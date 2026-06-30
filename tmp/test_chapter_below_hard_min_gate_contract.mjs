import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const finalizationCommand = readFileSync('frontend/src/application/writer-flow/finalization-command.js', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

function blockBetween(source, startNeedle, endNeedle) {
  const start = source.indexOf(startNeedle)
  assert.notEqual(start, -1, `missing block start: ${startNeedle}`)
  const end = source.indexOf(endNeedle, start + startNeedle.length)
  assert.notEqual(end, -1, `missing block end: ${endNeedle}`)
  return source.slice(start, end)
}

assert.match(
  writerView,
  /chapter_below_hard_min/,
  'WriterView should use a clear chapter_below_hard_min blocker before finalization'
)
assert.match(
  writerView,
  /ensureChapterAboveHardWordMinBeforeFinalize/,
  'WriterView should validate hard word floor before starting finalization'
)
assert.match(
  writerView,
  /正文低于硬下限，请扩写或重新生成/,
  'WriterView should show a clear hard-min failure message'
)
assert.match(
  blockBetween(writerView, 'async function handleFinalize(version)', 'async function performFinalize(version)'),
  /await ensureChapterAboveHardWordMinBeforeFinalize\(version\)[\s\S]*await performFinalize\(version\)/,
  'hard word floor check must run before performFinalize starts the finalization command'
)
assert.match(
  blockBetween(writerView, 'async function performFinalize(version)', 'async function performStoryBlockReviewAfterFinalize'),
  /runFinalizeChapterCommand[\s\S]*finalizeVersion:\s*writerStore\.finalizeVersion/,
  'performFinalize must pass writerStore.finalizeVersion into the application command'
)
assert.match(
  finalizationCommand,
  /const finalizeVersion = requiredFunction\(input,\s*'finalizeVersion'\)[\s\S]*await finalizeVersion\(version\)/,
  'finalization command must call the injected finalizeVersion only after UI preflight has passed'
)

assert.match(
  liveScript,
  /hardFailWordCountChapters/,
  'live report should list chapters that violate hard word floor'
)
assert.match(
  liveScript,
  /chapter_below_hard_min/,
  'live report should use chapter_below_hard_min blocker'
)
assert.match(
  liveScript,
  /syncHardWordCountBlocker/,
  'live report should sync hard word-count failures into the top-level blocker'
)
assert.match(
  liveScript,
  /wordCountPolicy[\s\S]*hardPass\s*===\s*false/,
  'live report should inspect wordCountPolicy.hardPass'
)
assert.match(
  liveScript,
  /ensureDraftAboveHardMinOrRegenerate/,
  'live flow should try automatic draft regeneration before blocking on below_hard_min'
)
assert.match(
  liveScript,
  /below_hard_min_auto_regenerate_started/,
  'live report should record when below_hard_min auto regeneration starts'
)
assert.match(
  liveScript,
  /below_hard_min_auto_regenerate_succeeded/,
  'live report should record when below_hard_min auto regeneration succeeds'
)
assert.match(
  liveScript,
  /await ensureDraftAboveHardMinOrRegenerate\(page, chapterNum\)/,
  'runChapter should call the automatic hard-min recovery before finalization'
)

console.log('chapter below hard min gate contract tests passed')

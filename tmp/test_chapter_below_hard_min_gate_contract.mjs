import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

assert.match(
  writerView,
  /chapter_below_hard_min/,
  'WriterView should use a clear chapter_below_hard_min blocker before finalization'
)
assert.match(
  writerView,
  /ensureChapterAboveHardWordMinBeforeFinalize/,
  'WriterView should validate hard word floor before calling finalizeVersion'
)
assert.match(
  writerView,
  /正文低于硬下限，请扩写或重新生成/,
  'WriterView should show a clear hard-min failure message'
)
assert.match(
  writerView,
  /await ensureChapterAboveHardWordMinBeforeFinalize\(version\)[\s\S]*await writerStore\.finalizeVersion\(version\)/,
  'hard word floor check must run before finalizeVersion'
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

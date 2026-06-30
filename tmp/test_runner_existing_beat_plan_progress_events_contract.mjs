import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

for (const eventName of [
  'writer_context_ready',
  'existing_beat_plan_detected',
  'draft_entry_clicked_after_existing_beat_plan',
  'draft_entry_clicked_after_new_beat_plan',
  'draft_generation_wait_started'
]) {
  assert.match(
    source,
    new RegExp(`markChapterFlowEvent\\(chapterNum, ['"]${eventName}['"]`),
    `runner should persist ${eventName} so a mid-draft timeout is not reported as writer_page_visible`
  )
}

assert.match(
  source,
  /existing_beat_plan_detected[\s\S]{0,500}hasSavedBeatPlan/,
  'existing beat-plan diagnostics should record that a saved beat plan was present'
)

assert.match(
  source,
  /draft_entry_clicked_after_existing_beat_plan[\s\S]{0,700}draftGenerationEntryLabel/,
  'draft entry click diagnostics should record which existing-plan draft entry was clicked'
)

console.log('runner existing beat plan progress events contract passed')

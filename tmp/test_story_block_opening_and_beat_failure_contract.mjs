import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const storyBlockPrompt = readFileSync('frontend/src/prompts/storyBlockPrompt.js', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')
const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const chaptersRouter = readFileSync('backend/routers/chapters.py', 'utf8')

assert.match(
  storyBlockPrompt,
  /chapterNum/,
  'story block planning prompt must include chapterNum'
)
assert.match(
  storyBlockPrompt,
  /openingHook/,
  'story block planning prompt must include openingHook'
)
assert.match(
  storyBlockPrompt,
  /openingAnchor/,
  'story block planning prompt must include openingAnchor'
)
assert.match(
  storyBlockPrompt,
  /handoffPoint/,
  'story block planning prompt must expose volume handoff as distant direction'
)
assert.match(
  storyBlockPrompt,
  /chapterNum\s*=\s*1|chapterNum.*?1|第 1 章|第一章/s,
  'story block prompt must explicitly constrain first chapter behavior'
)
assert.match(
  storyBlockPrompt,
  /首个故事块.*?(openingHook|openingAnchor)|openingHook.*?首个故事块|openingAnchor.*?首个故事块/s,
  'first story block must start from openingHook/openingAnchor'
)
assert.match(
  storyBlockPrompt,
  /handoff.*?(不能|不得).*?(entryState|stage-1)|entryState.*?(不能|不得).*?handoff|stage-1.*?(不能|不得).*?handoff/s,
  'volume handoff point must not become first block entryState or stage-1'
)

assert.match(
  writerView,
  /chapterNum:\s*chapterNum\.value/,
  'story block planning context must pass current chapterNum'
)
assert.match(
  writerView,
  /openingHook|openingAnchor/,
  'story block planning context must pass seed opening hook/anchor'
)

assert.match(
  writerStore,
  /beatPlanDiagnostics/,
  'writer store must record beat plan raw diagnostics'
)
assert.match(
  writerStore,
  /上一次模型返回了空小纲/,
  'empty beat plan responses must trigger a targeted retry'
)
assert.match(
  writerStore,
  /BEAT_PLAN_REQUIRES_REVIEW|beat_plan_requires_review/,
  'empty beat plan after retry must use a distinct review-required error code when story block derivation cannot continue'
)
assert.match(
  writerStore,
  /deriveChapterBeatPlanFromStoryBlock/,
  'empty beat plan after retry must attempt story block stage derivation before blocking'
)

assert.match(
  liveScript,
  /beat_plan_generation_failed/,
  'live script must classify empty/failed beat plan generation separately'
)
assert.match(
  liveScript,
  /beat_plan_saved_failed/,
  'live script must classify beat plan save failure separately'
)
assert.doesNotMatch(
  liveScript,
  /chapter \${chapterNum} generated timed out[\s\S]{0,500}chapter_.*_draft_generation/s,
  'live script must not report beat plan failures as draft generation timeout'
)
assert.match(
  liveScript,
  /chapter_beat_plan|chapterBeatPlan|beatPlanRecord|beatPlanGeneration/s,
  'live diagnostics must record beat plan chain state'
)

assert.match(
  chaptersRouter,
  /block_stage_snapshot/,
  'backend chapter beat plan save must persist block_stage_snapshot'
)
assert.match(
  chaptersRouter,
  /story_block_id/,
  'backend chapter beat plan save must persist story_block_id'
)
assert.match(
  chaptersRouter,
  /block_stage_id/,
  'backend chapter beat plan save must persist block_stage_id'
)

console.log('story block opening and beat failure contract tests passed')

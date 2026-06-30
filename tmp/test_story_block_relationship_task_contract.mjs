import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  buildStoryBlockPlanningPrompt,
  buildStoryBlockPlanningRepairPrompt
} from '../frontend/src/prompts/storyBlockPrompt.js'

const prompt = buildStoryBlockPlanningPrompt({
  chapterNum: 21,
  currentVolume: { title: '第一卷', coreGoal: '追查父亲旧案' },
  recentSummaries: [{ chapterNum: 20, summary: '陆沉舟进入第三密栈，取得账本和信。' }],
  previousChapterEnding: '陆沉舟发现底层密室还藏着去天池的路线图。',
  newBlockSeed: { title: '密栈余波', goal: '处理第三密栈后果' }
})
const repairPrompt = buildStoryBlockPlanningRepairPrompt('{"title":"密栈余波"}')
const storeSource = readFileSync('frontend/src/stores/storyBlockStore.js', 'utf8')
const planPromptSource = readFileSync('frontend/src/prompts/chapterPlanPrompt.js', 'utf8')

for (const field of [
  'relationshipFocus',
  'relationshipStart',
  'relationshipTask',
  'relationshipEndHint',
  'sceneVarietyHint'
]) {
  assert.match(prompt, new RegExp(field), `story block planning prompt should request ${field}`)
  assert.match(repairPrompt, new RegExp(field), `story block repair prompt should preserve ${field}`)
}

assert.match(
  prompt,
  /误会|信任|亏欠|交易|救助|隐瞒|背叛/,
  'relationshipTask should be framed as a story mechanism, not a QA gate'
)
assert.match(
  prompt,
  /不能只连续潜入\/追逃|连续潜入|追逃/,
  'sceneVarietyHint should discourage repeating only infiltration/chase gameplay'
)
assert.match(
  storeSource,
  /relationshipFocus|relationshipTask|sceneVarietyHint/,
  'story block normalization should preserve relationship task fields, even if only in lockState'
)
assert.match(
  planPromptSource,
  /relationshipFocus|relationshipTask|sceneVarietyHint/,
  'beat-plan context should carry story block humanity fields forward'
)

console.log('story block relationship task contract passed')

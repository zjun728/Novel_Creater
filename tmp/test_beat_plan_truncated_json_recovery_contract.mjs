import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const writerStore = readFileSync('frontend/src/stores/writerStore.js', 'utf8')
const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const chapterPrompt = readFileSync('frontend/src/prompts/chapter.js', 'utf8')

const truncatedCandidateRaw = `{
  "chapterEvent": "雨夜当铺内，陆沉舟清账时发现死去三年的父亲名字出现在当天新账上。他反复核对笔迹，确认与三年前一致。",
  "characterGoal": "陆沉舟要确认父亲名字出现在新账上的原因——是笔误还是父亲未死或存在更大秘密。",
  "coreConflict": "掌柜老周代表当铺势力阻止他深查，用‘笔误’和‘巡天司’施压；星账使用本身也带来代价和风险。",
  "externalPressure": "巡天司夜巡小队在当铺外经过，对话中提到最近在查‘星账异常’和‘旧账目’。",
  "costOrLoss": "陆沉舟为使用星账付出了一段童年记忆，导致他短暂眩晕，且失去的记忆无法恢复。",
  "irreversibleChange": "陆沉舟确认父亲名字异常且与未来时间关联，获得玉佩线索；但他失去了部分记忆。",
  "endingHandoff": "陆沉舟在雨夜后巷攥着账页纸条，听到身后巡天司脚步声逼近。他必须决定是立即去典当行查玉佩来源，还是`

assert.ok(truncatedCandidateRaw.includes('"endingHandoff"'), 'fixture should include most fields')
assert.ok(!truncatedCandidateRaw.trim().endsWith('}'), 'fixture should be an unclosed JSON object')

assert.match(
  writerStore,
  /shouldTriggerBeatPlanParseRecovery\(/,
  'truncated or length-finished JSON parse failures must be routed into recovery'
)
assert.match(
  writerStore,
  /buildChapterBeatPlanParseRetryPrompt/,
  'parse recovery must use the dedicated minimal parse-retry prompt'
)
assert.match(
  writerStore,
  /buildChapterBeatPlanJsonRepairPrompt/,
  'parse recovery must use JSON repair before final failure'
)
assert.match(
  writerStore,
  /reason:\s*['"]parse_retry['"]/,
  'finishReason=length parse failure should create an attempt2 parse-retry record'
)
assert.match(
  writerStore,
  /maxTokens:\s*BEAT_PLAN_EMPTY_LENGTH_RETRY_MAX_TOKENS/,
  'parse-retry should reuse the high token retry budget'
)

for (const field of [
  'parseRetryTriggered',
  'parseRetrySucceeded',
  'repairTriggered',
  'repairSucceeded',
  'derivedFallbackTriggered',
  'derivedFallbackSucceeded',
  'finalFailureAfterRecovery',
  'failureStage'
]) {
  assert.match(writerStore, new RegExp(field), `writer diagnostics must record ${field}`)
  assert.match(liveScript, new RegExp(field), `live report diagnostics must surface ${field}`)
}

assert.match(
  chapterPrompt,
  /每个字段.{0,24}60-120/,
  'initial beat plan prompt should constrain each JSON field to short content'
)

console.log('beat plan truncated JSON recovery contract tests passed')

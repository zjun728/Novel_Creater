import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')

const clickBeatPlanMatch = source.match(/async function clickBeatPlanEntry[\s\S]*?\n}\n\nasync function clickDraftEntry/)
const clickDraftMatch = source.match(/async function clickDraftEntry[\s\S]*?\n}\n\nasync function clickDraftGenerationEntry/)
const waitBeatPlanMatch = source.match(/async function waitForSavedBeatPlan[\s\S]*?\n}\n\nasync function waitForGeneratedChapterVersion/)
const waitGeneratedMatch = source.match(/async function waitForGeneratedChapterVersion[\s\S]*?\n}\n\nasync function waitForStoryBlockReviewSaved/)
const runChapterMatch = source.match(/async function runChapter[\s\S]*?\n}\n\nasync function findChapter/)

assert.ok(clickBeatPlanMatch, '必须拆出 clickBeatPlanEntry 处理“先做小纲”')
assert.ok(clickDraftMatch, '必须拆出 clickDraftEntry 处理“生成本章”')
assert.ok(waitBeatPlanMatch, '必须在点击“先做小纲”后等待小纲落库')
assert.ok(waitGeneratedMatch, '必须存在 waitForGeneratedChapterVersion')
assert.ok(runChapterMatch, '必须存在 runChapter')

const clickBeatPlanBody = clickBeatPlanMatch[0]
const clickDraftBody = clickDraftMatch[0]
const waitGeneratedBody = waitGeneratedMatch[0]
const runChapterBody = runChapterMatch[0]

for (const label of ['先做小纲', '生成正文', '生成本章', '开始生成本章', '保存小纲并生成正文', '确认小纲并生成正文']) {
  assert.match(source, new RegExp(label), `live 脚本必须支持按钮文案：${label}`)
}

assert.match(clickBeatPlanBody, /BEAT_PLAN_ENTRY_LABELS/, '小纲入口应只走 BEAT_PLAN_ENTRY_LABELS')
assert.match(clickBeatPlanBody, /beatPlanEntryLabel/, '小纲入口报告必须记录 beatPlanEntryLabel')
assert.match(clickBeatPlanBody, /beatPlanStartedAt/, '小纲入口报告必须记录 beatPlanStartedAt')
assert.doesNotMatch(clickBeatPlanBody, /draftGenerationStartedAt/, '点击“先做小纲”不能设置 draftGenerationStartedAt')

assert.match(clickDraftBody, /DRAFT_ENTRY_LABELS|DRAFT_MODAL_ENTRY_LABELS/, '正文入口应使用正文按钮文案集合')
assert.match(clickDraftBody, /draftGenerationEntryLabel/, '正文入口报告必须记录 draftGenerationEntryLabel')
assert.match(clickDraftBody, /draftGenerationStartedAt/, '只有正文入口点击后才能记录 draftGenerationStartedAt')
assert.doesNotMatch(clickDraftBody, /先做小纲/, 'clickDraftEntry 不能把“先做小纲”当作正文入口')

assert.match(
  runChapterBody,
  /if\s*\(\s*!initialBeatPlan\?\.content\s*\)[\s\S]*clickBeatPlanEntry\(page,\s*chapterNum[\s\S]*waitForSavedBeatPlan\(page,\s*chapterNum[\s\S]*clickDraftEntry\(page,\s*chapterNum/,
  '无小纲时必须先点“先做小纲”，等小纲落库后再点“生成本章”'
)
assert.match(
  runChapterBody,
  /else\s*\{[\s\S]*clickDraftEntry\(page,\s*chapterNum/,
  '已有小纲时必须直接点击“生成本章”'
)

assert.match(waitGeneratedBody, /clickDraftEntry\(page,\s*chapterNum/, '候选等待期间小纲已保存但正文未启动时必须点击正文入口')
assert.doesNotMatch(waitGeneratedBody, /clickDraftGenerationEntry\(page,\s*chapterNum/, '等待候选落库时不能再用旧的混合入口函数')
assert.match(waitGeneratedBody, /draftEntryClickedAfterBeatPlan/, '报告必须记录小纲后是否补点正文入口')
assert.match(source, /draft_generation_not_started/, '点到正文入口但无流请求时必须报 draft_generation_not_started')
assert.match(waitGeneratedBody, /draft_generation_entry_not_found/, '小纲已保存但找不到正文入口时必须报 draft_generation_entry_not_found')

for (const field of [
  'beatPlanEntryLabel',
  'beatPlanStartedAt',
  'beatPlanSavedAt',
  'draftGenerationEntryLabel',
  'draftGenerationStartedAt',
  'draftEntryClickedAfterBeatPlan',
  'draftStreamRequestCount',
  'draftStreamResponseCount'
]) {
  assert.match(source, new RegExp(field), `报告诊断必须包含 ${field}`)
}

assert.match(source, /visibleButtons/, '入口诊断必须包含 visibleButtons')
assert.match(source, /enabledButtons/, '入口诊断必须包含 enabledButtons')
assert.match(source, /entryVisibleButDisabled/, '入口存在但 disabled 时必须记录 entryVisibleButDisabled')
assert.match(source, /entryWaitTimedOut/, '入口等待超时时必须记录 entryWaitTimedOut')

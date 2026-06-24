import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const waitMatch = source.match(/async function waitForGeneratedChapterVersion[\s\S]*?\n}\n\nasync function waitForStoryBlockReviewSaved/)
assert.ok(waitMatch, '必须存在 waitForGeneratedChapterVersion')
const waitBody = waitMatch[0]

assert.doesNotMatch(
  waitBody,
  /clickButton\(page,\s*['"]生成本章['"]/,
  '正文候选等待不能依赖“生成本章”按钮重新可见或再次点击'
)
assert.doesNotMatch(
  waitBody,
  /startButton\.click\(/,
  '正文候选等待不能裸点“开始生成本章”并暴露 locator timeout'
)
assert.match(
  waitBody,
  /clickDraftEntry\(page,\s*chapterNum/,
  '需要通过统一正文生成入口定位函数确认生成正文'
)

assert.match(waitBody, /versionCountBefore/, '等待诊断必须记录 versionCountBefore')
assert.match(waitBody, /versionCountAfter/, '等待诊断必须记录 versionCountAfter')
assert.match(waitBody, /chapterStatus/, '等待诊断必须记录 chapterStatus')
assert.match(waitBody, /visibleErrorMessages/, '等待诊断必须记录 visibleErrorMessages')
assert.match(waitBody, /lastAiProxyRequestAt/, '等待诊断必须记录 lastAiProxyRequestAt')
assert.match(waitBody, /lastAiProxyResponseAt/, '等待诊断必须记录 lastAiProxyResponseAt')
assert.match(waitBody, /streamStarted/, '等待诊断必须记录 streamStarted')
assert.match(waitBody, /streamEnded/, '等待诊断必须记录 streamEnded')

assert.match(source, /draft_generation_timeout/, '正文生成超时 blocker code 必须是 draft_generation_timeout')
assert.match(source, /draft_generation_not_started/, '正文入口点击后未出现流请求时 blocker code 必须是 draft_generation_not_started')
assert.match(source, /draft_stream_stalled/, '流式生成停滞 blocker code 必须是 draft_stream_stalled')
assert.match(source, /draft_save_failed/, '候选保存失败 blocker code 必须是 draft_save_failed')
assert.doesNotMatch(
  source,
  /draft_generation_timed_out/,
  '报告 code 不应继续使用 draft_generation_timed_out'
)

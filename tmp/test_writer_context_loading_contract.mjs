import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const writerView = readFileSync('frontend/src/views/WriterView.vue', 'utf8')

assert.match(liveScript, /async function waitForWriterContextReady/, 'live 脚本必须先等待写字台上下文 ready')
assert.match(liveScript, /writer_context_loading_timeout/, '上下文加载超时必须使用 writer_context_loading_timeout')
assert.match(liveScript, /contextLoadingVisible/, '上下文诊断必须包含 contextLoadingVisible')
assert.match(liveScript, /contextLoadingDurationMs/, '上下文诊断必须包含 contextLoadingDurationMs')
assert.match(liveScript, /contextApiRequests/, '上下文诊断必须包含 contextApiRequests')
assert.match(liveScript, /contextApiFailures/, '上下文诊断必须包含 contextApiFailures')
assert.match(liveScript, /disabledDraftEntryLabels/, '上下文诊断必须包含 disabledDraftEntryLabels')
assert.match(liveScript, /lastConsoleErrors/, '上下文诊断必须包含 lastConsoleErrors')
assert.match(liveScript, /liveConsoleErrorEvents/, 'console 错误必须带时间戳，避免前置旧错误污染上下文等待')
assert.match(liveScript, /consoleErrorsSince\(eventWindowStartedAtMs\)/, '上下文失败判定只能使用进入写字台后的新 console 错误')
assert.match(liveScript, /recentConsoleContextFailures/, '上下文诊断必须区分本次等待期间的新 console 错误')
assert.match(liveScript, /writerEnteredAt/, '报告必须记录进入写字台时间')
assert.match(liveScript, /contextWaitStartedAt/, '报告必须记录上下文等待开始时间')
assert.match(liveScript, /staleConsoleErrorsIgnored/, '旧 console 错误必须作为 stale warning 记录')
assert.match(liveScript, /currentContextFailures/, '当前窗口上下文失败必须单独记录')

const runChapterMatch = liveScript.match(/async function runChapter[\s\S]*?\n}\n\nfunction storyBlockStageReuseError/)
assert.ok(runChapterMatch, '必须存在 runChapter')
const runChapterBody = runChapterMatch[0]
assert.match(
  runChapterBody,
  /writerEnteredAtMs[\s\S]*waitForWriterContextReady\(page,\s*chapterNum[\s\S]*(clickBeatPlanEntry|clickDraftEntry)\(page,\s*chapterNum/,
  'runChapter 必须在点击“先做小纲/生成本章”前等待上下文 ready'
)
assert.match(
  runChapterBody,
  /generationEntryDiagnostics:\s*\{[\s\S]*writerContext:\s*writerContextDiagnostics/,
  '正文等待报告必须保留 writer context 诊断字段'
)

const waitContextMatch = liveScript.match(/async function waitForWriterContextReady[\s\S]*?\n}\n\nasync function clickGenerationEntryByLabels/)
assert.ok(waitContextMatch, '必须存在 waitForWriterContextReady')
const waitContextBody = waitContextMatch[0]
const readyCheckIndex = waitContextBody.indexOf('contextReadyByEnabledEntry')
const failureCheckIndex = waitContextBody.indexOf('currentContextFailures.length')
assert.ok(readyCheckIndex >= 0, '必须显式优先判断 enabled 入口 ready')
assert.ok(failureCheckIndex >= 0, '必须显式判断当前窗口上下文失败')
assert.ok(
  readyCheckIndex < failureCheckIndex,
  'contextLoading 消失且入口 enabled 时，应先判定 ready，再处理旧错误 warning'
)
assert.doesNotMatch(
  runChapterBody,
  /waitFor\(\{ state: 'visible', timeout: 60000 \}\)\s*const initialGenerationEntry = await clickDraftGenerationEntry\(page,\s*chapterNum,\s*\{ clickTimeoutMs: 60000 \}\)/,
  'runChapter 不能进入写字台后立即找正文入口'
)

assert.match(writerView, /const contextLoadError\s*=\s*ref/, 'WriterView 必须记录上下文加载失败原因')
assert.match(writerView, /contextLoadError\.value\s*=\s*''[\s\S]*contextLoading\.value\s*=\s*true/, '开始加载上下文时必须清空旧错误并设置 loading')
assert.match(writerView, /catch\s*\(e\)[\s\S]*contextLoadError\.value\s*=[\s\S]*message\.error/, 'loadContextData 失败必须记录错误并显示提示')
assert.match(writerView, /finally\s*\{[\s\S]*contextLoading\.value\s*=\s*false[\s\S]*\}/, 'loadContextData 必须在 finally 清理 contextLoading')
assert.match(writerView, /aiContextStatusText[\s\S]*contextLoadError\.value/, '上下文状态文本必须暴露加载错误')

console.log('writer context loading contract tests passed')

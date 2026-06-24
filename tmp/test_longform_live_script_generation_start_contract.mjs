import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const liveScript = readFileSync('tmp/run_longform_browser_240w_phase1.mjs', 'utf8')
const debugScript = readFileSync('tmp/debug_chapter_generation_click.mjs', 'utf8')

for (const source of [liveScript, debugScript]) {
  assert.match(source, /async function clickStartGenerationIfPrompted/)
  assert.match(source, /confirmed_prompt/)
  assert.match(source, /already_generating/)
  assert.match(source, /正在生成本章\|AI 正在处理正文/)
}

assert.doesNotMatch(
  liveScript,
  /await clickButton\(page,\s*'开始生成本章',\s*300000\)/,
  'live 脚本不能在生成本章后无条件等待确认按钮'
)

assert.match(
  liveScript,
  /await dismissAppDialogs\(page\)[\s\S]{0,300}生成章名/,
  '正文候选生成后、点击生成章名前必须先清理可能残留的确认弹窗'
)
assert.match(
  liveScript,
  /确认\|确定\|知道了\|关闭\|OK/,
  '弹窗清理必须覆盖 Naive UI 常见的“关闭”按钮'
)
assert.match(
  liveScript,
  /async function clickButton[\s\S]{0,900}dismissAppDialogs\(page\)[\s\S]{0,500}locator\.click/,
  '通用按钮点击遇到遮罩拦截时必须清理弹窗并重试'
)

assert.match(
  liveScript,
  /生成章前小纲失败|小纲过短/,
  'live 脚本必须识别章前小纲失败提示，避免伪装成正文生成超时'
)

assert.match(
  liveScript,
  /请先审阅本章小纲[\s\S]*confirmed_start_generation/,
  'live 脚本必须支持小纲生成后再次点击“生成本章”的真实确认路径'
)

assert.match(
  liveScript,
  /chapter-beat-plan\/\$\{chapterNum\}[\s\S]*hasSavedBeatPlan[\s\S]*clickDraftEntry\(page,\s*chapterNum[\s\S]*generationEntryClicked/,
  'live script must retry the real generate action when a beat plan already exists but no draft was created'
)

assert.match(
  liveScript,
  /n-modal-container[\s\S]{0,500}n-modal/,
  'dialog cleanup must handle Naive UI modal containers, not only n-dialog'
)

assert.match(
  liveScript,
  /missingStoryBlockReviewDecision/,
  'live script must record missing story block review as a hard blocker'
)
assert.match(
  liveScript,
  /storyBlockReviewDecision[\s\S]*missingStoryBlockReviewDecision[\s\S]*throw new Error/,
  'live script must stop before creating the next chapter when block review decision is missing'
)
assert.match(
  liveScript,
  /story block review saved[\s\S]{0,900}reviewHistory\s*\|\|\s*block\.review_history/,
  'live script must wait for post-finalize story block review before reporting the chapter'
)
assert.match(
  liveScript,
  /async function collectFinalizationDiagnostics/,
  'live script must collect finalization diagnostics when a chapter has candidate versions but does not finalize'
)
assert.match(
  liveScript,
  /async function clickFinalizeContinuationIfPrompted/,
  'live script must poll for finalize continuation buttons produced by the pre-finalize audit'
)
assert.match(
  liveScript,
  /clickFinalizeContinuationIfPrompted\(page[\s\S]{0,600}chapter \${chapterNum} finalized/,
  'live script must keep checking finalize continuation while waiting for finalization, not only once before the wait'
)
assert.match(
  liveScript,
  /finalizeButton[\s\S]*isEnabled/,
  'finalization diagnostics must include finalize button visibility/enabled state'
)
assert.match(
  liveScript,
  /candidateVersionCount/,
  'finalization diagnostics must include candidate version count'
)
assert.match(
  liveScript,
  /dialogTexts[\s\S]*consoleErrors/,
  'finalization diagnostics must include dialogs and console errors'
)

console.log('longform live script generation start contract tests passed')

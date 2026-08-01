import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const source = path => readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')

function functionBody(moduleSource, signature) {
  const start = moduleSource.indexOf(signature)
  assert.notEqual(start, -1)
  const open = moduleSource.indexOf('{', start + signature.length)
  let depth = 0
  for (let index = open; index < moduleSource.length; index += 1) {
    if (moduleSource[index] === '{') depth += 1
    if (moduleSource[index] === '}') depth -= 1
    if (depth === 0) return moduleSource.slice(open + 1, index)
  }
  assert.fail(`unterminated function: ${signature}`)
}

test('writer view has one controller-owned plain-text working draft loop', async () => {
  const [view, editor] = await Promise.all([
    source('views/ChapterWriterView.vue'),
    source('components/writer/PlainTextDraftEditor.vue'),
  ])

  assert.match(view, /components\/writer\/PlainTextDraftEditor\.vue/)
  assert.match(view, /createWorkingDraftAutosave/)
  assert.match(view, /createChapterWriterController/)
  assert.match(view, /writeBusy:\s*\(\)\s*=>\s*chapterSessionStore\.commandBusy/)
  assert.doesNotMatch(view, /writeBusy:\s*\(\)\s*=>\s*chapterSessionStore\.writeBusy/)
  assert.match(view, /controller\.resetContext\(\)/)
  assert.match(view, /controller\.setAuthorInstruction/)
  assert.match(view, /controller\.setSelection/)
  assert.match(view, /<div v-if="session" class="editor-surface"[\s\S]*?<plain-text-draft-editor/)
  assert.match(view, /onBeforeRouteLeave\(async/)
  assert.match(view, /onBeforeRouteUpdate\(async/)
  assert.match(view, /beforeunload/)
  assert.match(view, /flush:\s*'sync'/)
  assert.doesNotMatch(view, /chapterSessionStore\.error/)
  assert.doesNotMatch(view, /const authorInstruction = ref/)
  assert.doesNotMatch(view, /const selection = ref/)
  assert.doesNotMatch(view, /chapterEditorState|保存工作稿|contenteditable/)
  assert.doesNotMatch(view, /draft-meta|persistenceState|characterCount/)
  assert.match(editor, /<textarea[\s\S]*aria-label="章节正文工作稿"/)
  assert.match(editor, /Array\.from\(text\.value\)\.length/)
  assert.doesNotMatch(editor, /contenteditable/)
  assert.match(editor, /dirty: \{ type: Boolean/)
  assert.match(editor, /status: \{ type: String/)
  assert.match(editor, /lastSavedAt: \{ type: String/)
  for (const label of ['正在暂存', '已暂存', '暂存失败', '与服务端版本冲突']) {
    assert.match(editor, new RegExp(label))
  }
  assert.match(editor, /请先复制当前正文，再刷新页面重新加载服务端版本。/)
  assert.match(editor, /class="draft-status" aria-live="polite"/)
  assert.doesNotMatch(editor, /class="draft-persistence" aria-live=/)
  const conflictBranch = editor.match(/<template v-if="status === 'conflict'">[\s\S]*?<\/template>/)?.[0]
  assert.ok(conflictBranch)
  assert.doesNotMatch(conflictBranch, /retry|reload|reset|disabled/)
  assert.match(editor, /@click="emit\('retry'\)"/)
})

test('operation status is a shallow readable overlay with one auditable busy lock', async () => {
  const [view, controller] = await Promise.all([
    source('views/ChapterWriterView.vue'),
    source('application/writer/chapterWriterController.js'),
  ])

  assert.match(view, /createDraftOperation:\s*command\s*=>\s*chapterSessionStore\.createDraftOperation/)
  assert.match(view, /readDraftOperation:\s*operationId\s*=>\s*chapterSessionStore\.readDraftOperation/)
  assert.match(view, /reloadWorkspace:\s*\(\)\s*=>\s*chapterSessionStore\.reloadCurrentWorkspace/)
  assert.match(view, /controller\.retryUnknown/)
  assert.match(view, /class="draft-operation-layer"[\s\S]*?aria-live="polite"/)
  assert.match(view, /\{\{ controller\.operationStatusText\.value \}\}/)
  assert.match(view, /draft-operation-layer\s*\{[^}]*pointer-events:\s*none/)
  assert.match(view, /draft-operation-layer[\s\S]*?max-height:/)
  assert.match(view, /plain-text-draft-editor[\s\S]*?:disabled="editorDisabled"/)
  assert.match(view, /writer-outline-link[\s\S]*?:aria-disabled="controller\.actionBusy\.value"/)
  assert.match(view, /@click="guardBusyNavigation"/)
  assert.match(view, /返回项目[\s\S]*?:disabled="controller\.actionBusy\.value"|:disabled="controller\.actionBusy\.value"[\s\S]*?返回项目/)
  assert.match(view, /controller\.dispose\(\)/)
  assert.doesNotMatch(view, /operation\.output|providerId|modelName|failureCode|idempotencyKey/)

  for (const label of [
    '正在生成',
    '生成完成',
    '生成失败',
    '生成结果已失效',
    '结果未知，可重试',
  ]) assert.match(controller, new RegExp(label))
  assert.doesNotMatch(controller, /operationStatusText[\s\S]{0,300}(?:error\.message|failureCode\.value)/)
})

test('route loading resets coordinator context synchronously before any awaited work', async () => {
  const view = await source('views/ChapterWriterView.vue')
  const body = view.match(/async function loadWorkspace\([\s\S]*?\n\}/)?.[0]
  assert.ok(body)
  assert.ok(body.indexOf('controller.resetContext()') >= 0)
  assert.ok(body.indexOf('controller.resetContext()') < body.indexOf('await '))
})

test('local generation rejection shows one fixed safe fallback only without an operation status', async () => {
  const view = await source('views/ChapterWriterView.vue')
  const body = functionBody(view, 'async function generateWorkingDraft()')
  const invoke = new Function(
    'controller',
    'actionError',
    `return (async () => {${body}})()`,
  )
  const rawFailure = new Error('raw provider and authority detail')
  const actionError = { value: 'stale' }
  const controller = {
    operationStatusText: { value: '' },
    async generateWorkingDraft() { throw rawFailure },
  }

  await invoke(controller, actionError)

  assert.equal(actionError.value, '当前工作稿未能完成生成，请检查作者要求后重试。')
  assert.doesNotMatch(actionError.value, /raw|provider|authority|detail/i)

  actionError.value = 'stale'
  controller.operationStatusText.value = '生成失败'
  await invoke(controller, actionError)
  assert.equal(actionError.value, '')
})

test('author instruction input enforces a Unicode-scalar limit with an accessible count', async () => {
  const view = await source('views/ChapterWriterView.vue')
  const input = view.match(/<n-input id="author-instruction"[^>]*\/>/)?.[0]
  assert.ok(input)
  assert.doesNotMatch(input, /maxlength|show-count/)
  assert.match(input, /aria-describedby="author-instruction-count"/)
  assert.match(input, /@update:value="updateAuthorInstruction"/)
  assert.match(view, /unicodeScalarLength|limitUnicodeScalarText/)
  assert.match(view, /id="author-instruction-count"[^>]*aria-live="polite"/)
})

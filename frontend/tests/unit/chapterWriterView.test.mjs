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
  assert.match(editor, /readonly: \{ type: Boolean/)
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
  assert.match(editor, /:readonly="readonly \|\| streaming"/)
  assert.match(editor, /:disabled="disabled"/)
  assert.match(editor, /:disabled="disabled \|\| readonly \|\| streaming"/)
  assert.match(editor, /if \(props\.readonly \|\| props\.disabled \|\| props\.streaming\) return/)
  const selectionBody = functionBody(editor, 'function emitSelection(')
  assert.doesNotMatch(selectionBody, /readonly|disabled/)
  assert.match(editor, /:read-only:not\(:disabled\)/)
})

test('operation status is a shallow readable overlay with one auditable busy lock', async () => {
  const [view, controller] = await Promise.all([
    source('views/ChapterWriterView.vue'),
    source('application/writer/chapterWriterController.js'),
  ])

  assert.match(view, /createDraftOperation:\s*command\s*=>\s*chapterSessionStore\.createDraftOperation/)
  assert.match(view, /readDraftOperation:\s*operationId\s*=>\s*chapterSessionStore\.readDraftOperation/)
  assert.match(view, /listDraftOperationEvents:\s*\(operationId, afterSequence\)\s*=>\s*chapterSessionStore\.listDraftOperationEvents/)
  assert.match(view, /cancelDraftOperation:\s*operationId\s*=>\s*chapterSessionStore\.cancelDraftOperation/)
  assert.match(view, /reloadWorkspace:\s*\(\)\s*=>\s*chapterSessionStore\.reloadCurrentWorkspace/)
  assert.match(view, /controller\.retryUnknown/)
  assert.match(view, /class="draft-operation-layer"[\s\S]*?aria-live="polite"/)
  assert.match(view, /\{\{ controller\.operationStatusText\.value \}\}/)
  assert.match(view, /draft-operation-layer\s*\{[^}]*pointer-events:\s*none/)
  assert.match(view, /draft-operation-layer[\s\S]*?max-height:/)
  assert.match(view, /const editorDisabled = computed\(\(\) => !session\.value\)/)
  assert.match(view, /const editorReadonly = computed\([\s\S]*?controller\.actionBusy\.value[\s\S]*?finalization\.finalized\.value/)
  assert.match(view, /plain-text-draft-editor[\s\S]*?:disabled="editorDisabled"/)
  assert.match(view, /plain-text-draft-editor[\s\S]*?:readonly="editorReadonly"/)
  assert.match(view, /plain-text-draft-editor[\s\S]*?:model-value="controller\.editorText\.value"/)
  assert.match(view, /plain-text-draft-editor[\s\S]*?:streaming="controller\.streamingPreview\.value !== null"/)
  assert.match(view, /writer-outline-link[\s\S]*?:aria-disabled="controller\.actionBusy\.value"/)
  assert.match(view, /@click="guardBusyNavigation"/)
  assert.match(view, /返回项目[\s\S]*?:disabled="controller\.actionBusy\.value"|:disabled="controller\.actionBusy\.value"[\s\S]*?返回项目/)
  assert.match(view, /controller\.dispose\(\)/)
  assert.doesNotMatch(view, /operation\.output|providerId|modelName|failureCode|idempotencyKey/)

  for (const label of [
    '正在生成',
    '正在恢复连接',
    '正在取消',
    '已停止，已保留生成内容',
    '已停止，正文未改变',
    '生成完成',
    '生成失败',
    '生成已失效',
  ]) assert.match(controller, new RegExp(label))
  assert.doesNotMatch(controller, /结果未知，可重试/)
  assert.doesNotMatch(controller, /operationStatusText[\s\S]{0,300}(?:error\.message|failureCode\.value)/)
})

test('route loading resets coordinator context synchronously before any awaited work', async () => {
  const view = await source('views/ChapterWriterView.vue')
  const body = view.match(/async function loadWorkspace\([\s\S]*?\n\}/)?.[0]
  assert.ok(body)
  assert.ok(body.indexOf('controller.resetContext()') >= 0)
  assert.ok(body.indexOf('controller.resetContext()') < body.indexOf('await '))
})

test('route loading starts a nonblocking safe resume after autosave reset when the workspace has an active operation', async () => {
  const view = await source('views/ChapterWriterView.vue')
  const body = functionBody(view, 'async function loadWorkspace(')
  const reset = body.indexOf('autosave.reset(chapterSessionStore.workspace)')
  const resume = body.indexOf('controller.resumeDraftOperation(activeDraftOperationId)')
  assert.ok(reset >= 0)
  assert.ok(resume > reset)
  assert.match(body, /const activeDraftOperationId = chapterSessionStore\.workspace\?\.activeDraftOperationId/)
  assert.match(body, /void controller\.resumeDraftOperation\(activeDraftOperationId\)\.catch\(\(\) => \{[\s\S]*?if \(!loadGuard\.isCurrent\(generation\)\) return[\s\S]*?actionError\.value = '生成失败'/)
  assert.doesNotMatch(body.slice(resume, resume + 220), /await controller\.resumeDraftOperation/)
})

test('stop generation is available only while the controller marks the current operation cancellable', async () => {
  const view = await source('views/ChapterWriterView.vue')
  const stop = functionBody(view, 'async function stopGeneration(')
  assert.match(stop, /controller\.cancelGeneration\(\)/)
  assert.match(view, /<n-button v-if="controller\.operationCancellable\.value"[\s\S]*?@click="stopGeneration"[\s\S]*?>停止生成<\/n-button>/)
  assert.doesNotMatch(view, /<n-button v-if="controller\.actionBusy\.value"[\s\S]*?@click="stopGeneration"/)
  assert.match(view, /plain-text-draft-editor[\s\S]*?:streaming="controller\.streamingPreview\.value !== null"/)
  assert.doesNotMatch(view, /:streaming="controller\.operationCancellable\.value"/)
  assert.match(view, /<template v-else>[\s\S]*?AI 生成工作稿[\s\S]*?保存为候选[\s\S]*?<\/template>/)
  assert.match(view, /:disabled="commandDisabled"/)
  assert.match(view, /:loading="controller\.actionBusy\.value"/)
  assert.match(view, /:aria-disabled="controller\.actionBusy\.value"/)
  assert.match(view, /onBeforeRouteLeave\(async \(\) => await controller\.canNavigate\(\)\)/)
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

test('failed full generation offers one explicit partial-draft recovery action', async () => {
  const view = await source('views/ChapterWriterView.vue')

  assert.match(view, /controller\.recoverablePartialDraft\.value/)
  assert.match(view, /已保留[^<]*部分正文/)
  assert.match(view, /@click="recoverPartialDraft"[^>]*>载入部分稿<\/n-button>/)
  assert.match(view, /controller\.recoverPartialDraft\(\)/)
  assert.match(view, /将替换当前工作稿/)
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

test('non-empty exact selection reveals four compact local tools with one shared busy and cancel path', async () => {
  const view = await source('views/ChapterWriterView.vue')

  assert.match(view, /const validSelection = computed/)
  assert.match(view, /selectedText\.length > 0/)
  assert.match(view, /scalars\.slice\(startOffset, endOffset\)\.join\(''\) === selectedText/)
  assert.match(view, /v-if="validSelection" class="selection-tools"/)
  for (const [label, operationType] of [
    ['AI 改写', 'rewrite_selection'],
    ['AI 润色', 'polish_selection'],
    ['AI 扩写', 'expand_selection'],
    ['AI 缩写', 'compress_selection'],
  ]) {
    assert.match(view, new RegExp(`>${label}<\\/n-button>`))
    assert.match(view, new RegExp(`runSelectionOperation\\('${operationType}'\\)`))
  }
  assert.match(view, /:disabled="commandDisabled"/)
  assert.match(view, /:loading="controller\.actionBusy\.value"/)
  assert.match(view, /controller\.operationCancellable\.value/)
  assert.doesNotMatch(view, /selection-modal|history-drawer|page\.evaluate|\bfetch\(|\baxios\b/)
})

test('local replacement preview stays outside the editor and exposes only one ephemeral undo action', async () => {
  const view = await source('views/ChapterWriterView.vue')

  assert.match(view, /undoLocalDraft:\s*command\s*=>\s*chapterSessionStore\.undoLocalDraft/)
  assert.match(view, /:selection-range="controller\.restoredSelection\.value"/)
  assert.match(view, /class="replacement-preview"[\s\S]*?替换内容预览/)
  assert.match(view, /\{\{ controller\.replacementPreview\.value \}\}/)
  assert.match(view, /v-if="controller\.undoAvailable\.value"[\s\S]*?@click="undoLastLocal"[\s\S]*?>撤销本次 AI 修改<\/n-button>/)
  assert.equal((view.match(/撤销本次 AI 修改/g) || []).length, 1)
  assert.match(view, /controller\.undoLastLocal\(\)/)
  assert.doesNotMatch(view, /replacementPreview\.value[^\n]*model-value/)
})

test('selection tools use the existing instruction field with a 1000-scalar local limit', async () => {
  const view = await source('views/ChapterWriterView.vue')
  const update = functionBody(view, 'function updateAuthorInstruction(')

  assert.match(view, /const authorInstructionLimit = computed\(\(\) => validSelection\.value \? 1_000 : 2_000\)/)
  assert.match(update, /authorInstructionLimit\.value/)
  assert.match(view, /\{\{ authorInstructionCount \}\} \/ \{\{ authorInstructionLimit \}\}/)
  assert.equal((view.match(/id="author-instruction"/g) || []).length, 1)
})


test('candidate workbench compares exactly two read-only drafts and loads explicitly', async () => {
  const view = await source('views/ChapterWriterView.vue')

  assert.match(view, /loadCandidate:\s*\(candidateId, command\)\s*=>\s*chapterSessionStore\.loadCandidate/)
  assert.match(view, /const selectedCandidateIds = ref\(\[\]\)/)
  assert.match(view, /const selectedCandidates = computed/)
  assert.match(view, /selectedCandidateIds\.value\.length >= 2/)
  assert.match(view, /watch\(candidates,[\s\S]*selectedCandidateIds\.value = selectedCandidateIds\.value\.filter/)
  assert.match(view, /unicodeScalarLength\(String\(candidate\.content \?\? ''\)\)/)
  assert.match(view, /candidate\.contentHash\.slice\(0, 8\)/)
  assert.match(view, /formatCandidateTime\(candidate\.createdAt\)/)
  assert.match(view, /@click="loadCandidate\(candidate\)"[^>]*>载入为工作稿<\/n-button>/)
  assert.match(view, /:disabled="candidateSelectionDisabled\(candidate\.id\)"/)
  assert.match(view, /v-if="selectedCandidates\.length === 2"[\s\S]{0,100}class="candidate-comparison"/)
  assert.equal((view.match(/class="candidate-comparison-pane"/g) || []).length, 1)
  assert.match(view, /<pre>\{\{ candidate\.content \}\}<\/pre>/)
  assert.match(view, /controller\.resetContext\(\)[\s\S]{0,80}selectedCandidateIds\.value = \[\]/)
  assert.doesNotMatch(view, /v-model[^>]*candidate\.content|contenteditable|融合候选|fusion|diff-match-patch|candidate-modal|history-drawer/)
  assert.match(view, /workspace-grid\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) 320px/)
})


test('writer finalization reloads server actions and verifies the committed chapter without navigating', async () => {
  const view = await source('views/ChapterWriterView.vue')
  const commit = functionBody(view, 'commit: async command =>')

  assert.match(view, /mapProjectNextAction/)
  assert.match(view, /finalChapterPath/)
  assert.match(view, /getProjectId:\s*\(\)\s*=>\s*projectId\.value/)
  assert.match(view, /getChapterNumber:\s*\(\)\s*=>\s*chapterNumber\.value/)
  assert.match(view, /reloadPreparation:\s*projectId\s*=>\s*api\.projects\.preparation\(projectId/)
  assert.match(view, /readFinalizedChapter:\s*\(projectId, chapterNumber\)\s*=>\s*api\.manuscripts\.chapter\(\s*projectId,\s*chapterNumber/)
  assert.match(view, /mapNextAction:\s*mapProjectNextAction/)
  assert.match(view, /finalizedChapterPath:\s*\(projectId, chapterNumber\)\s*=>\s*finalChapterPath\(\s*projectId,\s*chapterNumber/)
  assert.ok(commit.indexOf('const committedChapterNumber') >= 0)
  assert.ok(commit.indexOf('const committedChapterNumber') < commit.indexOf('await api.chapterSessions.commitFinalization'))
  assert.match(commit, /chapterNumber:\s*committedChapterNumber/)
  assert.doesNotMatch(view, /reloadPreparation:\s*.*chapterNumber|targetPath:\s*chapterWriterPath\([^,]+,\s*chapterNumber/)
  assert.doesNotMatch(view, /onCommitted[\s\S]{0,500}router\.(?:push|replace)/)
})

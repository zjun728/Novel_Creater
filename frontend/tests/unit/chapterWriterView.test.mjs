import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const source = path => readFile(new URL(`../../src/${path}`, import.meta.url), 'utf8')

test('writer view has one controller-owned plain-text working draft loop', async () => {
  const [view, editor] = await Promise.all([
    source('views/ChapterWriterView.vue'),
    source('components/writer/PlainTextDraftEditor.vue'),
  ])

  assert.match(view, /components\/writer\/PlainTextDraftEditor\.vue/)
  assert.match(view, /createWorkingDraftAutosave/)
  assert.match(view, /createChapterWriterController/)
  assert.match(view, /chapterSessionStore\.commandBusy/)
  assert.match(view, /controller\.resetContext\(\)/)
  assert.match(view, /controller\.setAuthorInstruction/)
  assert.match(view, /controller\.setSelection/)
  assert.match(view, /<plain-text-draft-editor\s+v-if="session"/)
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
  assert.match(editor, /@click="emit\('retry'\)"/)
})

import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createChapterEditorState,
  decideChapterNavigation,
} from '../../src/utils/chapterEditorState.js'

function workspace(content, revision) {
  return {
    workingDraft: {
      content,
      revision,
    },
  }
}

test('save response preserves input typed after save began and advances persisted baseline', () => {
  const state = createChapterEditorState()
  state.syncFromWorkspace(workspace('服务端旧稿', 1))
  state.editorContent.value = '点击保存时的正文'
  const token = state.beginSave()

  state.editorContent.value = '保存请求期间继续输入的正文'
  state.finishSave(workspace('点击保存时的正文', 2), token)

  assert.equal(state.editorContent.value, '保存请求期间继续输入的正文')
  assert.equal(state.baselineContent.value, '点击保存时的正文')
  assert.equal(state.baselineRevision.value, 2)
  assert.equal(state.dirty.value, true)
})

test('save response synchronizes editor when no newer input exists', () => {
  const state = createChapterEditorState()
  state.syncFromWorkspace(workspace('服务端旧稿', 1))
  state.editorContent.value = '保存后的正文'
  const token = state.beginSave()

  state.finishSave(workspace('保存后的正文', 2), token)

  assert.equal(state.editorContent.value, '保存后的正文')
  assert.equal(state.baselineRevision.value, 2)
  assert.equal(state.dirty.value, false)
})

test('generation response always becomes the new editor baseline', () => {
  const state = createChapterEditorState()
  state.syncFromWorkspace(workspace('手写正文', 1))

  state.finishGeneration(workspace('AI 生成正文', 2))

  assert.equal(state.editorContent.value, 'AI 生成正文')
  assert.equal(state.baselineContent.value, 'AI 生成正文')
  assert.equal(state.baselineRevision.value, 2)
  assert.equal(state.dirty.value, false)
})

test('navigation blocks busy work and asks once before abandoning dirty text', () => {
  let confirms = 0
  const confirmDiscard = () => {
    confirms += 1
    return false
  }

  assert.equal(decideChapterNavigation({
    busy: true,
    dirty: true,
    confirmDiscard,
  }), false)
  assert.equal(confirms, 0)
  assert.equal(decideChapterNavigation({
    busy: false,
    dirty: true,
    confirmDiscard,
  }), false)
  assert.equal(confirms, 1)
  assert.equal(decideChapterNavigation({
    busy: false,
    dirty: false,
    confirmDiscard,
  }), true)
  assert.equal(confirms, 1)
})

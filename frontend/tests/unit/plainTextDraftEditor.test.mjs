import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const source = readFile(
  new URL('../../src/components/writer/PlainTextDraftEditor.vue', import.meta.url),
  'utf8',
)

function functionBody(moduleSource, signature) {
  const start = moduleSource.indexOf(signature)
  assert.notEqual(start, -1, `missing ${signature}`)
  const open = moduleSource.indexOf('{', start + signature.length)
  let depth = 0
  for (let index = open; index < moduleSource.length; index += 1) {
    if (moduleSource[index] === '{') depth += 1
    if (moduleSource[index] === '}') depth -= 1
    if (depth === 0) return moduleSource.slice(open + 1, index)
  }
  assert.fail(`unterminated function: ${signature}`)
}

test('streaming preview is a native readonly textarea that stays focusable, selectable, copyable, and scrollable', async () => {
  const editor = await source

  assert.match(editor, /streaming: \{ type: Boolean, default: false \}/)
  assert.match(editor, /<textarea[\s\S]*?:readonly="readonly \|\| streaming"/)
  assert.match(editor, /<textarea[\s\S]*?:disabled="disabled"/)
  assert.doesNotMatch(editor, /contenteditable/)
  assert.doesNotMatch(editor, /:disabled="disabled \|\| streaming"/)
  assert.match(editor, /@select="emitSelection\(\$event\.target\)"/)
  assert.match(editor, /@scroll="updateFollow"/)
  assert.match(editor, /:read-only:not\(:disabled\)/)
  assert.match(editor, /cursor:\s*text/)
  assert.doesNotMatch(editor, /selectionStart\s*=/)
  assert.doesNotMatch(editor, /selectionEnd\s*=/)
})

test('streaming blocks text mutation, paste, and autosave retry but leaves selection events available', async () => {
  const editor = await source

  const updateText = functionBody(editor, 'function updateText(')
  const blockPaste = functionBody(editor, 'function blockPaste(')
  const selection = functionBody(editor, 'function emitSelection(')
  assert.match(updateText, /props\.streaming/)
  assert.match(blockPaste, /event\.preventDefault\(\)/)
  assert.match(editor, /@paste="blockPaste"/)
  assert.match(editor, /:disabled="disabled \|\| readonly \|\| streaming"/)
  assert.doesNotMatch(selection, /readonly|disabled|streaming/)
})

test('streaming follows output until the reader scrolls more than 24px from the bottom and can resume accessibly', async () => {
  const editor = await source

  assert.match(editor, /const autoFollow = ref\(true\)/)
  assert.match(editor, /scrollHeight - target\.scrollTop - target\.clientHeight/)
  assert.match(editor, /distance > 24/)
  assert.match(editor, /watch\(\(\) => props\.modelValue/)
  assert.match(editor, /if \(props\.streaming && autoFollow\.value\)/)
  assert.match(editor, /nextTick\(scrollToLatest\)/)
  assert.match(editor, /watch\(\(\) => props\.streaming/)
  assert.match(editor, /autoFollow\.value = true/)
  assert.match(editor, /v-if="streaming && !autoFollow"/)
  assert.match(editor, /type="button"[\s\S]*?aria-label="回到最新输出"[\s\S]*?@click="returnToLatest"/)
  assert.match(editor, />回到最新<\/button>/)
  const returnToLatest = functionBody(editor, 'function returnToLatest(')
  assert.match(returnToLatest, /autoFollow\.value = true/)
  assert.match(returnToLatest, /scrollToLatest\(\)/)
})

test('terminal replacement range is restored through the same native textarea without mutating text', async () => {
  const editor = await source

  assert.match(editor, /selectionRange: \{ type: Object, default: null \}/)
  assert.match(editor, /watch\(\(\) => props\.selectionRange/)
  assert.match(editor, /nextTick\(restoreSelection\)/)
  const restore = functionBody(editor, 'function restoreSelection(')
  assert.match(restore, /locateRange\(range\.startOffset, range\.endOffset\)/)
  assert.doesNotMatch(restore, /emit\('update:modelValue'|\.value\s*=/)
  assert.equal((editor.match(/<textarea/g) || []).length, 1)
  assert.doesNotMatch(editor, /contenteditable/)
})

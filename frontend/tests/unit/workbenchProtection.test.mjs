import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

const view = await readFile(new URL('../../src/views/ChapterWriterView.vue', import.meta.url), 'utf8')
function body(name) {
  const start = view.indexOf(`function ${name}(`)
  assert.ok(start >= 0)
  const open = view.indexOf('{', start)
  let depth = 1
  let end = open + 1
  for (; depth; end++) { if (view[end] === '{') depth++; if (view[end] === '}') depth-- }
  return view.slice(open + 1, end - 1)
}
function invoke(name, state, parameters = {}) {
  const values = { ...state, ...parameters }
  return new Function(...Object.keys(values), `return (async () => {${body(name)}})()`)(...Object.values(values))
}
const ref = value => ({ value })

test('unresolved generation blocks new commands and outline editing until recovery', async () => {
  const state = {
    session: ref({ id: 'active' }), protectionBusy: ref(false),
    controller: { actionBusy: ref(false), operationRetryAvailable: ref(true) },
    chapterSessionStore: { commandBusy: false }, finalization: { busy: ref(false), finalized: ref(false) },
    reviewDirty: ref(false), autosave: { async flush() { throw new Error('must not flush during unknown recovery') } },
    outlineDialogOpen: ref(false), actionError: ref(''),
  }
  const expression = view.match(/const commandDisabled = computed\(\(\) => \(([\s\S]*?)\n\)\)/)[1]
  const disabled = new Function(...Object.keys(state), `return (${expression})`)
  assert.equal(disabled(...Object.values(state)), true)
  await invoke('openOutlineEditor', state)
  assert.equal(state.outlineDialogOpen.value, false)
  assert.equal(state.actionError.value, '')
  state.controller.operationRetryAvailable.value = false
  assert.equal(disabled(...Object.values(state)), false)
})

test('comparison remains open while preserving a draft and clears both modes on close', async () => {
  const state = { protectionBusy: ref(true), previewCandidate: ref({ id: 'saved' }), savedComparisonOpen: ref(true) }
  await invoke('closeComparison', state)
  assert.equal(state.previewCandidate.value.id, 'saved')
  assert.equal(state.savedComparisonOpen.value, true)
  state.protectionBusy.value = false
  await invoke('closeComparison', state)
  assert.equal(state.previewCandidate.value, null)
  assert.equal(state.savedComparisonOpen.value, false)
})

test('candidate switching retains current text and does not load after failed preservation', async () => {
  let text = '作者尚未保存的最新正文'
  const selected = { id: 'older', content: '较早版本' }
  const state = {
    commandDisabled: ref(false), protectionBusy: ref(false), previewCandidate: ref(selected), actionError: ref(''),
    controller: { async saveCandidate() { return false }, async loadCandidate(candidate) { text = candidate.content } },
  }
  await invoke('confirmCandidateSwitch', state)
  assert.equal(text, '作者尚未保存的最新正文')
  assert.equal(state.previewCandidate.value, selected)
  assert.equal(state.protectionBusy.value, false)
  assert.ok(state.actionError.value)
  state.controller.saveCandidate = async () => true
  state.controller.loadCandidate = async candidate => { text = candidate.content; return true }
  await invoke('confirmCandidateSwitch', state)
  assert.equal(text, '较早版本')
  assert.equal(state.actionError.value, '')
  assert.equal(state.previewCandidate.value, null)
})

test('candidate switching saves latest text before loading and suppresses duplicate clicks', async () => {
  let text = '最新正文'
  const saved = []
  let release
  const waiting = new Promise(resolve => { release = resolve })
  const state = {
    commandDisabled: ref(false), protectionBusy: ref(false), previewCandidate: ref({ id: 'old', content: '旧正文' }), actionError: ref(''),
    controller: {
      async saveCandidate() { saved.push(text); await waiting; return true },
      async loadCandidate(candidate) { text = candidate.content; return true },
    },
  }
  const first = invoke('confirmCandidateSwitch', state)
  await invoke('confirmCandidateSwitch', state)
  assert.deepEqual(saved, ['最新正文'])
  assert.equal(text, '最新正文')
  release()
  await first
  assert.equal(text, '旧正文')
  assert.equal(state.previewCandidate.value, null)
})

test('regeneration does not start when preserving the latest draft fails', async () => {
  let generations = 0
  const state = {
    commandDisabled: ref(false), protectionBusy: ref(false), regenerationOpen: ref(true), actionError: ref(''),
    controller: { async saveCandidate() { throw new Error('save failed') } },
    async performGeneration() { generations++ },
  }
  await invoke('confirmRegeneration', state, { keep: true })
  assert.equal(generations, 0)
  assert.equal(state.regenerationOpen.value, true)
  await invoke('confirmRegeneration', state, { keep: false })
  assert.equal(generations, 1)
  assert.equal(state.actionError.value, '')
})

test('outline editing stays closed if the working draft cannot be flushed', async () => {
  const state = {
    controller: { actionBusy: ref(false), operationRetryAvailable: ref(false) }, finalization: { busy: ref(false), finalized: ref(false) }, protectionBusy: ref(false),
    reviewDirty: ref(false), session: ref({ id: 'current' }), autosave: { async flush() { throw new Error('save failed') } },
    outlineDialogOpen: ref(false), actionError: ref(''),
  }
  await invoke('openOutlineEditor', state)
  assert.equal(state.outlineDialogOpen.value, false)
  assert.ok(state.actionError.value)
})

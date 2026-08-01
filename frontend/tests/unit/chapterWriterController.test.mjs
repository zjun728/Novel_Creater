import assert from 'node:assert/strict'
import test from 'node:test'

import { createChapterWriterController } from '../../src/application/writer/chapterWriterController.js'

const HASH = 'a'.repeat(64)
const FLUSHED_HASH = 'b'.repeat(64)

function deferred() {
  let resolve
  const promise = new Promise(next => {
    resolve = next
  })
  return { promise, resolve }
}

function autosave({ text = '正文', revision = 1, hash = HASH } = {}) {
  const state = {
    text: { value: text },
    dirty: { value: false },
    status: { value: 'saved' },
    persistedRevision: { value: revision },
    persistedHash: { value: hash },
    persistedContent: text,
    flushCalls: 0,
    resetCalls: [],
    async flush() {
      this.flushCalls += 1
      this.persistedContent = this.text.value
      this.dirty.value = false
      this.status.value = 'saved'
      return true
    },
    edit(nextText) {
      const normalized = String(nextText ?? '')
      if (this.text.value === normalized) return false
      this.text.value = normalized
      this.dirty.value = normalized !== this.persistedContent
      this.status.value = this.dirty.value ? 'pending' : 'saved'
      return true
    },
    reset(workspace) { this.resetCalls.push(workspace) },
  }
  return state
}

test('candidate freeze flushes first and uses post-flush authority with one UUID', async () => {
  const state = autosave()
  const calls = []
  state.flush = async () => {
    state.flushCalls += 1
    state.persistedRevision.value = 7
    state.persistedHash.value = FLUSHED_HASH
    state.text.value = '已暂存正文'
    state.persistedContent = '已暂存正文'
    state.dirty.value = false
    state.status.value = 'saved'
    return true
  }
  const controller = createChapterWriterController({
    autosave: state,
    idFactory: () => {
      calls.push('newId')
      return '11111111-1111-1111-1111-111111111111'
    },
    freezeCandidate: async command => {
      calls.push(command)
      return { workingDraft: { content: '已暂存正文' } }
    },
  })

  await controller.saveCandidate()

  assert.deepEqual(calls, [
    'newId',
    {
      expectedWorkingDraftRevision: 7,
      expectedContentHash: FLUSHED_HASH,
      idempotencyKey: '11111111-1111-1111-1111-111111111111',
    },
  ])
  assert.equal(state.flushCalls, 1)
  assert.equal(state.resetCalls.length, 1)
})

test('generation does not reset when edits return to the flushed text during the request', async () => {
  const state = autosave({ text: '保存前正文', revision: 4, hash: FLUSHED_HASH })
  const calls = []
  let controller
  controller = createChapterWriterController({
    autosave: state,
    generateWorkingDraft: async command => {
      calls.push(command)
      controller.edit('临时改动')
      controller.edit('保存前正文')
      return { workingDraft: { content: 'AI 正文' } }
    },
  })

  controller.setAuthorInstruction('多一点市井对话')
  await controller.generateWorkingDraft()

  assert.deepEqual(calls, [{
    expectedWorkingDraftRevision: 4,
    authorInstruction: '多一点市井对话',
  }])
  assert.equal(state.flushCalls, 1)
  assert.equal(state.text.value, '保存前正文')
  assert.equal(state.dirty.value, false)
  assert.deepEqual(state.resetCalls, [])
})

test('candidate fails closed without consuming a UUID when flush is not confirmed', async () => {
  const state = autosave()
  const calls = []
  state.flush = async () => {
    state.flushCalls += 1
    return false
  }
  const controller = createChapterWriterController({
    autosave: state,
    idFactory: () => {
      calls.push('newId')
      return '11111111-1111-1111-1111-111111111111'
    },
    freezeCandidate: async command => {
      calls.push(command)
      return { workingDraft: { content: '候选正文' } }
    },
  })

  assert.equal(await controller.saveCandidate(), false)
  assert.equal(state.flushCalls, 1)
  assert.deepEqual(calls, [])
})

test('generation fails closed when flush leaves the draft dirty', async () => {
  const state = autosave()
  const calls = []
  state.dirty.value = true
  state.flush = async () => {
    state.flushCalls += 1
    return true
  }
  const controller = createChapterWriterController({
    autosave: state,
    generateWorkingDraft: async command => {
      calls.push(command)
      return { workingDraft: { content: 'AI 正文' } }
    },
  })

  assert.equal(await controller.generateWorkingDraft(), false)
  assert.equal(state.flushCalls, 1)
  assert.deepEqual(calls, [])
})

test('navigation flushes normal dirty text but rejects busy and failed-unsaved states', async () => {
  const state = autosave()
  state.dirty.value = true
  state.status.value = 'pending'
  state.flush = async () => {
    state.flushCalls += 1
    state.dirty.value = false
    state.status.value = 'saved'
    return true
  }
  const controller = createChapterWriterController({ autosave: state })

  assert.equal(await controller.canNavigate(), true)
  assert.equal(state.flushCalls, 1)
  state.dirty.value = true
  state.status.value = 'failed'
  assert.equal(await controller.canNavigate(), false)
  assert.equal(controller.beforeUnloadRisk.value, true)
  state.status.value = 'conflict'
  assert.equal(await controller.canNavigate(), false)
  const busy = createChapterWriterController({ autosave: state, writeBusy: () => true })
  assert.equal(await busy.canNavigate(), false)
})

test('navigation waits for an in-flight save after edits return to persisted text', async () => {
  const state = autosave({ text: 'A' })
  const gate = deferred()
  state.status.value = 'saving'
  state.flush = async () => {
    state.flushCalls += 1
    await gate.promise
    state.status.value = 'saved'
    state.dirty.value = false
    return true
  }
  const controller = createChapterWriterController({ autosave: state })
  controller.edit('B')
  controller.edit('A')
  state.status.value = 'saving'

  const navigation = controller.canNavigate()
  let settled = false
  void navigation.then(() => { settled = true })
  await Promise.resolve()

  assert.equal(state.dirty.value, false)
  assert.equal(state.status.value, 'saving')
  assert.equal(state.flushCalls, 1)
  assert.equal(settled, false)
  gate.resolve()
  assert.equal(await navigation, true)
})

test('controller rejects malformed persisted hashes and candidate UUIDs before callbacks', async () => {
  const malformedHash = 'not-a-content-hash'
  const candidateState = autosave({ hash: malformedHash })
  const generationState = autosave({ hash: malformedHash })
  let freezeCalls = 0
  let generateCalls = 0
  const candidate = createChapterWriterController({
    autosave: candidateState,
    idFactory: () => 'INVALID-UUID',
    freezeCandidate: async () => { freezeCalls += 1 },
  })
  const generation = createChapterWriterController({
    autosave: generationState,
    generateWorkingDraft: async () => { generateCalls += 1 },
  })

  await assert.rejects(candidate.saveCandidate(), error => (
    error instanceof TypeError && !String(error.message).includes(malformedHash)
  ))
  await assert.rejects(generation.generateWorkingDraft(), error => (
    error instanceof TypeError && !String(error.message).includes(malformedHash)
  ))
  assert.equal(freezeCalls, 0)
  assert.equal(generateCalls, 0)

  const validState = autosave()
  const invalidKey = createChapterWriterController({
    autosave: validState,
    idFactory: () => 'INVALID-UUID',
    freezeCandidate: async () => { freezeCalls += 1 },
  })
  await assert.rejects(invalidKey.saveCandidate(), error => (
    error instanceof TypeError && !String(error.message).includes('INVALID-UUID')
  ))
  assert.equal(freezeCalls, 0)
})

test('local action lock rejects external busy, double candidate, and crossed generation', async () => {
  const externallyBusy = createChapterWriterController({
    autosave: autosave(),
    writeBusy: true,
    idFactory: () => assert.fail('external busy must not consume UUID'),
    freezeCandidate: async () => assert.fail('external busy must not freeze'),
  })
  assert.equal(await externallyBusy.saveCandidate(), false)

  const state = autosave()
  const gate = deferred()
  const calls = []
  state.flush = async () => {
    state.flushCalls += 1
    await gate.promise
    return true
  }
  const controller = createChapterWriterController({
    autosave: state,
    idFactory: () => {
      calls.push('uuid')
      return '11111111-1111-1111-1111-111111111111'
    },
    freezeCandidate: async () => {
      calls.push('freeze')
      return { workingDraft: { content: '候选' } }
    },
    generateWorkingDraft: async () => {
      calls.push('generate')
      return { workingDraft: { content: '生成' } }
    },
  })

  const first = controller.saveCandidate()
  assert.equal(controller.actionBusy.value, true)
  assert.equal(controller.beforeUnloadRisk.value, true)
  assert.equal(await controller.saveCandidate(), false)
  assert.equal(await controller.generateWorkingDraft(), false)
  assert.equal(await controller.canNavigate(), false)
  assert.equal(state.flushCalls, 1)
  assert.deepEqual(calls, [])

  gate.resolve()
  await first
  assert.equal(controller.actionBusy.value, false)
  assert.deepEqual(calls, ['uuid', 'freeze'])
})

test('public actionBusy cannot release a pending action lock', async () => {
  const state = autosave()
  const gate = deferred()
  const calls = []
  state.flush = async () => {
    state.flushCalls += 1
    await gate.promise
    return true
  }
  const controller = createChapterWriterController({
    autosave: state,
    idFactory: () => {
      calls.push('uuid')
      return '11111111-1111-1111-1111-111111111111'
    },
    freezeCandidate: async () => {
      calls.push('freeze')
      return { workingDraft: { content: '候选' } }
    },
  })

  const first = controller.saveCandidate()
  const originalWarn = console.warn
  console.warn = () => {}
  try {
    controller.actionBusy.value = false
  } finally {
    console.warn = originalWarn
  }

  assert.equal(controller.actionBusy.value, true)
  assert.equal(await controller.saveCandidate(), false)
  assert.equal(state.flushCalls, 1)
  assert.deepEqual(calls, [])
  gate.resolve()
  await first
  assert.deepEqual(calls, ['uuid', 'freeze'])
})

test('route context resets instruction and selection before a later generation', async () => {
  const state = autosave()
  const calls = []
  const controller = createChapterWriterController({
    autosave: state,
    generateWorkingDraft: async command => {
      calls.push(command)
      return { workingDraft: { content: '生成' } }
    },
  })

  controller.setAuthorInstruction('A 项目的临时要求')
  controller.setSelection({ startOffset: 1, endOffset: 2, selectedText: '甲' })
  assert.equal(controller.authorInstruction.value, 'A 项目的临时要求')
  assert.deepEqual(controller.selection.value, {
    startOffset: 1,
    endOffset: 2,
    selectedText: '甲',
  })

  controller.resetContext()

  assert.equal(controller.authorInstruction.value, '')
  assert.equal(controller.selection.value, null)
  await controller.generateWorkingDraft()
  assert.deepEqual(calls, [{
    expectedWorkingDraftRevision: 1,
    authorInstruction: '',
  }])
})

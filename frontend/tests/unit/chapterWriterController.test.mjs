import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'
import { watch } from 'vue'

import { createChapterWriterController } from '../../src/application/writer/chapterWriterController.js'
import { ApiError } from '../../src/api/db/api-error.js'

const HASH = 'a'.repeat(64)
const FLUSHED_HASH = 'b'.repeat(64)
const PROJECT_ID = '11111111-1111-4111-8111-111111111111'
const SESSION_ID = '22222222-2222-4222-8222-222222222222'
const OPERATION_ID = '33333333-3333-4333-8333-333333333333'
const KEY = '44444444-4444-4444-8444-444444444444'

function textHash(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((next, fail) => {
    resolve = next
    reject = fail
  })
  return { promise, resolve, reject }
}

async function waitForSignalBeforeSettlement(signal, pending, name) {
  const settledFirst = Promise.resolve(pending).then(
    () => { throw new Error(`${name} settled before its expected signal`) },
    () => { throw new Error(`${name} settled before its expected signal`) },
  )
  await Promise.race([signal, settledFirst])
}

function operation(overrides = {}) {
  const status = overrides.status ?? 'completed'
  const partialOutput = overrides.partialOutput
    ?? (status === 'completed' ? '权威生成正文' : '')
  const partialOutputHash = overrides.partialOutputHash ?? textHash(partialOutput)
  return {
    id: OPERATION_ID,
    projectId: PROJECT_ID,
    chapterSessionId: SESSION_ID,
    operationType: 'generate_new',
    status,
    lastEventSequence: status === 'completed' || status === 'failed' || status === 'cancelled' ? 2 : 1,
    partialOutput,
    partialOutputHash,
    partialOutputScalars: Array.from(partialOutput).length,
    resultWorkingDraftRevision: status === 'completed' ? 5 : null,
    resultContentHash: status === 'completed' ? partialOutputHash : null,
    resultSelectionStart: null,
    resultSelectionEnd: null,
    failureCode: status === 'failed' ? 'DraftProviderFailed' : null,
    model: Object.freeze({ providerId: 'provider-1', modelName: 'writer-model' }),
    ...overrides,
  }
}

test('local selection operation flushes exact text, previews separately, then exposes one undo', async () => {
  const state = autosave({ text: '左侧目标右侧', revision: 4, hash: HASH })
  const calls = []
  const replacement = '新片段'
  const resultHash = 'b'.repeat(64)
  const pending = deferred()
  const controller = operationController({
    autosave: state,
    createDraftOperation: async command => {
      calls.push(['start', command])
      return pending.promise
    },
    reloadWorkspace: async () => ({
      workingDraft: {
        revision: 5,
        contentHash: resultHash,
        content: `左侧${replacement}右侧`,
      },
    }),
    undoLocalDraft: async command => {
      calls.push(['undo', command])
      return { workingDraft: { revision: 6, contentHash: HASH, content: '左侧目标右侧' } }
    },
  })
  controller.setSelection({ startOffset: 2, endOffset: 4, selectedText: '目标' })

  const request = controller.runSelectionOperation('rewrite_selection')
  await Promise.resolve()
  assert.equal(controller.editorText.value, '左侧目标右侧')
  pending.resolve(operation({
    operationType: 'rewrite_selection',
    partialOutput: replacement,
    partialOutputHash: textHash(replacement),
    resultContentHash: resultHash,
    resultSelectionStart: 2,
    resultSelectionEnd: 5,
  }))
  await request

  assert.equal(state.flushCalls, 1)
  assert.equal(calls[0][1].startOffset, 2)
  assert.equal(calls[0][1].endOffset, 4)
  assert.equal(calls[0][1].selectedTextHash, textHash('目标'))
  assert.equal(controller.undoAvailable.value, true)
  assert.deepEqual(controller.restoredSelection.value, { startOffset: 2, endOffset: 5 })
  await controller.undoLastLocal()
  assert.deepEqual(calls[1], ['undo', {
    expectedWorkingDraftRevision: 5,
    expectedContentHash: resultHash,
    sourceOperationId: OPERATION_ID,
  }])
  assert.equal(controller.undoAvailable.value, false)
})

test('local cancellation with preview preserves editor and unknown undo reconciles once without retry', async () => {
  const state = autosave({ text: '左侧目标右侧', revision: 4, hash: HASH })
  const resultHash = 'b'.repeat(64)
  let reloads = 0
  let undoCalls = 0
  const controller = operationController({
    autosave: state,
    createDraftOperation: async () => operation({
      operationType: 'rewrite_selection',
      status: 'cancelled',
      partialOutput: ' 取消前预览 ',
      partialOutputHash: textHash(' 取消前预览 '),
      partialOutputScalars: 7,
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
    reloadWorkspace: async () => {
      reloads += 1
      return { workingDraft: { revision: 6, contentHash: HASH, content: '已撤销' } }
    },
  })
  controller.setSelection({ startOffset: 2, endOffset: 4, selectedText: '目标' })

  await controller.runSelectionOperation('rewrite_selection')

  assert.equal(controller.editorText.value, '左侧目标右侧')
  assert.equal(state.resetCalls.length, 0)
  assert.equal(controller.undoAvailable.value, false)
  assert.equal(reloads, 0)

  const completed = operationController({
    autosave: state,
    createDraftOperation: async () => operation({
      operationType: 'rewrite_selection',
      partialOutput: '新片段',
      partialOutputHash: textHash('新片段'),
      resultContentHash: resultHash,
      resultSelectionStart: 2,
      resultSelectionEnd: 5,
    }),
    reloadWorkspace: async () => {
      reloads += 1
      return reloads === 1
        ? { workingDraft: { revision: 5, contentHash: resultHash, content: '新正文' } }
        : { workingDraft: { revision: 6, contentHash: HASH, content: '已撤销' } }
    },
    undoLocalDraft: async () => {
      undoCalls += 1
      throw new ApiError({
        status: 502,
        code: 'DraftOperationUnavailable',
        message: 'unknown',
      })
    },
  })
  completed.setSelection({ startOffset: 2, endOffset: 4, selectedText: '目标' })
  await completed.runSelectionOperation('rewrite_selection')
  assert.equal(completed.undoAvailable.value, true)
  await completed.undoLastLocal()
  assert.equal(undoCalls, 1)
  assert.equal(reloads, 2)
  assert.equal(completed.undoAvailable.value, false)
  assert.equal(state.resetCalls.at(-1).workingDraft.content, '已撤销')
})

function operationController(overrides = {}) {
  return createChapterWriterController({
    autosave: autosave({ revision: 4, hash: HASH }),
    createDraftOperation: async () => operation(),
    readDraftOperation: async () => operation(),
    listDraftOperationEvents: async (operationId, after) => ({
      operationId,
      events: [],
      lastEventSequence: after,
      nextAfter: after,
      hasMore: false,
    }),
    cancelDraftOperation: async () => operation({
      status: 'cancelled',
      partialOutput: '',
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
    reloadWorkspace: async () => ({ workingDraft: { content: '权威生成正文' } }),
    idFactory: () => KEY,
    pollScheduler: () => ({ promise: Promise.resolve(), cancel() {} }),
    ...overrides,
  })
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

test('streaming preview owns editorText during generation without editing autosave', async () => {
  const state = autosave({ text: '作者原正文', revision: 4, hash: HASH })
  const statusRead = deferred()
  const statusStarted = deferred()
  const controller = operationController({
    autosave: state,
    createDraftOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listDraftOperationEvents: async (operationId, after) => (after === 1
      ? {
          operationId,
          events: [{
            sequence: 2,
            type: 'delta',
            createdAt: 2,
            text: '流式新正文',
            partialOutputHash: textHash('流式新正文'),
            partialOutputScalars: 5,
          }],
          lastEventSequence: 2,
          nextAfter: 2,
          hasMore: false,
        }
      : {
          operationId,
          events: [{
            sequence: 3,
            type: 'completed',
            createdAt: 3,
            resultWorkingDraftRevision: 5,
            resultContentHash: textHash('流式新正文'),
          }],
          lastEventSequence: 3,
          nextAfter: 3,
          hasMore: false,
        }),
    readDraftOperation: () => {
      statusStarted.resolve()
      return statusRead.promise
    },
  })
  const generation = controller.generateWorkingDraft()
  await statusStarted.promise
  assert.equal(controller.streamingPreview.value, '流式新正文')
  assert.equal(controller.editorText.value, '流式新正文')
  assert.equal(state.text.value, '作者原正文')
  assert.equal(state.dirty.value, false)

  statusRead.resolve(operation({
    status: 'completed',
    lastEventSequence: 3,
    partialOutput: '流式新正文',
    resultWorkingDraftRevision: 5,
    resultContentHash: textHash('流式新正文'),
  }))
  await generation
  assert.equal(state.resetCalls.length, 1)
  assert.equal(controller.streamingPreview.value, null)
  assert.equal(controller.editorText.value, '作者原正文')
})

test('resumeDraftOperation is GET-only and cancelGeneration settles inside the active generation lock', async () => {
  const state = autosave({ text: '原正文', revision: 4, hash: HASH })
  const resumeRead = deferred()
  let flushes = 0
  state.flush = async () => {
    flushes += 1
    return true
  }
  const resumed = operationController({
    autosave: state,
    idFactory: () => assert.fail('resume must not create a key'),
    createDraftOperation: async () => assert.fail('resume must not POST'),
    readDraftOperation: () => resumeRead.promise,
  })
  const resume = resumed.resumeDraftOperation(OPERATION_ID)
  assert.equal(resumed.actionBusy.value, true)
  assert.equal(resumed.operationCancellable.value, false)
  assert.equal(resumed.operationStatusText.value, '正在恢复连接')
  resumeRead.resolve(operation())
  await resume
  assert.equal(resumed.operationCancellable.value, false)
  assert.equal(flushes, 0)
  assert.equal(state.resetCalls.length, 1)

  const eventGate = deferred()
  const eventStarted = deferred()
  let cancelCalls = 0
  const cancelled = operationController({
    autosave: state,
    createDraftOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listDraftOperationEvents: async (operationId, after) => {
      eventStarted.resolve()
      await eventGate.promise
      return { operationId, events: [], lastEventSequence: after, nextAfter: after, hasMore: false }
    },
    cancelDraftOperation: async () => {
      cancelCalls += 1
      return operation({
        status: 'cancelled',
        lastEventSequence: 2,
        partialOutput: '已保留',
        resultWorkingDraftRevision: 5,
        resultContentHash: textHash('已保留'),
      })
    },
    reloadWorkspace: async () => ({ workingDraft: { content: '已保留' } }),
  })
  const generation = cancelled.generateWorkingDraft()
  await eventStarted.promise
  assert.equal(cancelled.operationCancellable.value, true)
  const cancellation = cancelled.cancelGeneration()
  assert.equal(cancelled.operationCancellable.value, false)
  assert.equal(cancelled.operationStatusText.value, '正在取消')
  await cancellation
  assert.equal(cancelled.operationStatusText.value, '已停止，已保留生成内容')
  eventGate.resolve()
  await generation
  assert.equal(cancelled.operationCancellable.value, false)
  assert.equal(cancelCalls, 1)
  assert.equal(state.resetCalls.length, 2)
})

test('operationStatusText notifies reactive views after cancellation reload releases cancelling state', async () => {
  const eventGate = deferred()
  const eventStarted = deferred()
  const reloadStarted = deferred()
  const reload = deferred()
  const controller = operationController({
    createDraftOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listDraftOperationEvents: async (operationId, after) => {
      eventStarted.resolve()
      await eventGate.promise
      return { operationId, events: [], lastEventSequence: after, nextAfter: after, hasMore: false }
    },
    cancelDraftOperation: async () => operation({
      status: 'cancelled',
      lastEventSequence: 2,
      partialOutput: '已保留',
      resultWorkingDraftRevision: 5,
      resultContentHash: textHash('已保留'),
    }),
    reloadWorkspace: async () => {
      reloadStarted.resolve()
      return reload.promise
    },
  })
  const observedStatusTexts = []
  const stopWatching = watch(
    controller.operationStatusText,
    (statusText) => observedStatusTexts.push(statusText),
    { immediate: true, flush: 'sync' },
  )
  let generation
  let cancellation

  try {
    generation = controller.generateWorkingDraft()
    await waitForSignalBeforeSettlement(eventStarted.promise, generation, 'generation')
    cancellation = controller.cancelGeneration()
    await waitForSignalBeforeSettlement(reloadStarted.promise, cancellation, 'cancellation')
    assert.equal(observedStatusTexts.at(-1), '正在取消')

    reload.resolve({ workingDraft: { content: '已保留' } })
    await cancellation
    assert.deepEqual(observedStatusTexts.slice(-2), ['正在取消', '已停止，已保留生成内容'])
    eventGate.resolve()
    await generation
  } finally {
    stopWatching()
    reload.resolve({ workingDraft: { content: '已保留' } })
    eventGate.resolve()
    await Promise.allSettled([generation, cancellation].filter(Boolean))
    controller.dispose()
  }

})

test('generation is not cancellable until the start response identifies an active operation', async () => {
  const startGate = deferred()
  const startCalled = deferred()
  const controller = operationController({
    createDraftOperation: () => {
      startCalled.resolve()
      return startGate.promise
    },
  })

  const generation = controller.generateWorkingDraft()
  await startCalled.promise
  assert.equal(controller.actionBusy.value, true)
  assert.equal(controller.operationCancellable.value, false)
  assert.equal(await controller.cancelGeneration(), false)

  startGate.resolve(operation())
  await generation
  assert.equal(controller.operationCancellable.value, false)
})

test('cancelled generation without retained output reports that the working draft did not change', async () => {
  const eventsStarted = deferred()
  const eventGate = deferred()
  let reloads = 0
  const controller = operationController({
    createDraftOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listDraftOperationEvents: async (operationId, after) => {
      eventsStarted.resolve()
      await eventGate.promise
      return { operationId, events: [], lastEventSequence: after, nextAfter: after, hasMore: false }
    },
    cancelDraftOperation: async () => operation({
      status: 'cancelled',
      lastEventSequence: 2,
      partialOutput: '',
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
    reloadWorkspace: async () => {
      reloads += 1
      return { workingDraft: { content: '不应加载' } }
    },
  })

  const generation = controller.generateWorkingDraft()
  await eventsStarted.promise
  await controller.cancelGeneration()
  assert.equal(controller.operationStatusText.value, '已停止，正文未改变')
  eventGate.resolve()
  assert.equal(await generation, null)
  assert.equal(reloads, 0)
})

test('generation does not reset when edits return to the flushed text during the request', async () => {
  const state = autosave({ text: '保存前正文', revision: 4, hash: FLUSHED_HASH })
  const calls = []
  let controller
  controller = createChapterWriterController({
    autosave: state,
    idFactory: () => KEY,
    createDraftOperation: async command => {
      calls.push(command)
      controller.edit('临时改动')
      controller.edit('保存前正文')
      return operation()
    },
    readDraftOperation: async () => operation(),
    reloadWorkspace: async () => ({ workingDraft: { content: 'AI 正文' } }),
  })

  controller.setAuthorInstruction('多一点市井对话')
  await controller.generateWorkingDraft()

  assert.deepEqual(calls, [{
    operationType: 'generate_new',
    expectedWorkingDraftRevision: 4,
    expectedContentHash: FLUSHED_HASH,
    idempotencyKey: KEY,
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
    createDraftOperation: async () => { generateCalls += 1 },
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
    idFactory: () => KEY,
    createDraftOperation: async command => {
      calls.push(command)
      return operation()
    },
    readDraftOperation: async () => operation(),
    reloadWorkspace: async () => ({ workingDraft: { content: '生成' } }),
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
    operationType: 'generate_new',
    expectedWorkingDraftRevision: 1,
    expectedContentHash: HASH,
    idempotencyKey: KEY,
    authorInstruction: '',
  }])
})

test('formal generation flushes first and submits post-flush revision hash and controller instruction', async () => {
  const state = autosave({ text: '可见正文', revision: 2, hash: HASH })
  const calls = []
  state.flush = async () => {
    calls.push('flush')
    state.persistedRevision.value = 7
    state.persistedHash.value = FLUSHED_HASH
    state.persistedContent = state.text.value
    state.dirty.value = false
    state.status.value = 'saved'
    return true
  }
  const controller = operationController({
    autosave: state,
    createDraftOperation: async command => {
      calls.push(structuredClone(command))
      return operation({ resultWorkingDraftRevision: 8 })
    },
  })
  controller.setAuthorInstruction('多一点市井对话')

  await controller.generateWorkingDraft()

  assert.deepEqual(calls, [
    'flush',
    {
      operationType: 'generate_new',
      expectedWorkingDraftRevision: 7,
      expectedContentHash: FLUSHED_HASH,
      idempotencyKey: KEY,
      authorInstruction: '多一点市井对话',
    },
  ])
  assert.equal(state.resetCalls.length, 1)
})

test('completed reload is fenced by both edit generation and route context', async () => {
  for (const invalidate of [
    controller => controller.edit('等待期间的新正文'),
    controller => controller.resetContext(),
  ]) {
    const state = autosave({ text: '发起时正文', revision: 4, hash: HASH })
    const pending = deferred()
    const started = deferred()
    const controller = operationController({
      autosave: state,
      createDraftOperation: () => {
        started.resolve()
        return pending.promise
      },
    })
    const request = controller.generateWorkingDraft()
    await started.promise
    invalidate(controller)
    pending.resolve(operation())

    await request

    assert.deepEqual(state.resetCalls, [])
    assert.notEqual(state.text.value, '权威生成正文')
  }
})

test('failed expired unknown and known rejection never replace local text', async () => {
  const failed = operation({
    status: 'failed',
    resultWorkingDraftRevision: null,
    resultContentHash: null,
    failureCode: 'DraftProviderFailed',
  })
  const expired = operation({
    status: 'expired',
    lastEventSequence: 1,
    resultWorkingDraftRevision: null,
    resultContentHash: null,
  })
  for (const createDraftOperation of [
    async () => failed,
    async () => expired,
    async () => { throw new ApiError() },
    async () => { throw new ApiError({ status: 409, message: 'raw provider detail' }) },
  ]) {
    const state = autosave({ text: '作者本地正文', revision: 4, hash: HASH })
    const controller = operationController({ autosave: state, createDraftOperation })
    try { await controller.generateWorkingDraft() } catch { /* expected transport/rejection */ }
    assert.equal(state.text.value, '作者本地正文')
    assert.deepEqual(state.resetCalls, [])
  }
})

test('one busy action blocks edit candidate navigation and exposes fixed safe operation statuses', async () => {
  const state = autosave({ text: '发起时正文', revision: 4, hash: HASH })
  const pending = deferred()
  const controller = operationController({
    autosave: state,
    createDraftOperation: () => pending.promise,
    freezeCandidate: async () => assert.fail('candidate must remain separate while generation is busy'),
  })
  const request = controller.generateWorkingDraft()
  await Promise.resolve()

  assert.equal(controller.actionBusy.value, true)
  assert.equal(controller.operationStatusText.value, '正在生成')
  assert.equal(controller.edit('不应写入'), false)
  assert.equal(state.text.value, '发起时正文')
  assert.equal(await controller.saveCandidate(), false)
  assert.equal(await controller.canNavigate(), false)

  pending.resolve(operation())
  await request
  assert.equal(controller.operationStatusText.value, '生成完成')

  const cases = [
    [async () => operation({ status: 'failed', resultWorkingDraftRevision: null, resultContentHash: null, failureCode: 'DraftProviderFailed' }), '生成失败'],
      [async () => operation({ status: 'expired', lastEventSequence: 1, resultWorkingDraftRevision: null, resultContentHash: null }), '生成已失效'],
    [async () => { throw new ApiError() }, '生成失败'],
    [async () => { throw new ApiError({ status: 409, message: 'raw provider detail' }) }, '生成失败'],
  ]
  for (const [createDraftOperation, expected] of cases) {
    const subject = operationController({ createDraftOperation })
    try { await subject.generateWorkingDraft() } catch { /* expected */ }
    assert.equal(subject.operationStatusText.value, expected)
    assert.doesNotMatch(subject.operationStatusText.value, /raw|provider|detail/i)
  }
})

test('unknown retry reuses the coordinator key and context reset clears it synchronously', async () => {
  const calls = []
  let attempt = 0
  const controller = operationController({
    createDraftOperation: async command => {
      calls.push(command)
      attempt += 1
      if (attempt === 1) throw new ApiError()
      return operation()
    },
  })
  await assert.rejects(controller.generateWorkingDraft(), ApiError)
  assert.equal(controller.operationRetryAvailable.value, true)
  await controller.retryUnknown()
  assert.strictEqual(calls[1], calls[0])

  const resetSubject = operationController({
    createDraftOperation: async () => { throw new ApiError() },
  })
  await assert.rejects(resetSubject.generateWorkingDraft(), ApiError)
  assert.equal(resetSubject.operationRetryAvailable.value, true)
  resetSubject.resetContext()
  assert.equal(resetSubject.operationRetryAvailable.value, false)
  await assert.rejects(resetSubject.retryUnknown(), /no unknown/i)
})

test('pending navigation owns the action lock against generate retry and candidate requests', async () => {
  for (const contender of ['generate', 'retry', 'candidate']) {
    const state = autosave({ revision: 4, hash: HASH })
    const flushGate = deferred()
    const flushStarted = deferred()
    let operationStarts = 0
    let candidateStarts = 0
    const controller = operationController({
      autosave: state,
      createDraftOperation: async () => {
        operationStarts += 1
        if (contender === 'retry' && operationStarts === 1) throw new ApiError()
        return operation()
      },
      freezeCandidate: async () => {
        candidateStarts += 1
        return { workingDraft: { content: '候选正文' } }
      },
    })
    if (contender === 'retry') {
      await assert.rejects(controller.generateWorkingDraft(), ApiError)
      assert.equal(controller.operationRetryAvailable.value, true)
    }
    state.flush = async () => {
      flushStarted.resolve()
      const succeeded = await flushGate.promise
      if (succeeded) {
        state.dirty.value = false
        state.status.value = 'saved'
      }
      return succeeded
    }

    const navigation = controller.canNavigate()
    await flushStarted.promise
    let competing
    try {
      assert.equal(controller.actionBusy.value, true, `${contender} saw navigation unlocked`)
      competing = contender === 'generate'
        ? controller.generateWorkingDraft()
        : contender === 'retry'
          ? controller.retryUnknown()
          : controller.saveCandidate()
      assert.equal(await competing, false)
      assert.equal(operationStarts, contender === 'retry' ? 1 : 0)
      assert.equal(candidateStarts, 0)
    } finally {
      flushGate.resolve(true)
      await Promise.allSettled([navigation, competing].filter(Boolean))
    }
    assert.equal(await navigation, true)
    assert.equal(controller.actionBusy.value, false)
  }
})

test('failed navigation flush returns false and releases the action lock', async () => {
  const state = autosave({ revision: 4, hash: HASH })
  const flushGate = deferred()
  const flushStarted = deferred()
  state.flush = async () => {
    flushStarted.resolve()
    return flushGate.promise
  }
  let candidateStarts = 0
  const controller = operationController({
    autosave: state,
    freezeCandidate: async () => {
      candidateStarts += 1
      return { workingDraft: { content: '候选正文' } }
    },
  })

  const navigation = controller.canNavigate()
  await flushStarted.promise
  assert.equal(controller.actionBusy.value, true)
  flushGate.resolve(false)

  assert.equal(await navigation, false)
  assert.equal(controller.actionBusy.value, false)
  state.flush = async () => true
  assert.deepEqual(await controller.saveCandidate(), { workingDraft: { content: '候选正文' } })
  assert.equal(candidateStarts, 1)
})

test('reset fences a pending navigation and its late flush cannot unlock the new context action', async () => {
  const state = autosave({ revision: 4, hash: HASH })
  const navigationFlush = deferred()
  const navigationStarted = deferred()
  const operationGate = deferred()
  const operationStarted = deferred()
  let flushCalls = 0
  state.flush = async () => {
    flushCalls += 1
    if (flushCalls === 1) {
      navigationStarted.resolve()
      return navigationFlush.promise
    }
    return true
  }
  const controller = operationController({
    autosave: state,
    createDraftOperation: () => {
      operationStarted.resolve()
      return operationGate.promise
    },
  })

  const navigation = controller.canNavigate()
  await navigationStarted.promise
  controller.resetContext()
  const generation = controller.generateWorkingDraft()
  await operationStarted.promise
  assert.equal(controller.actionBusy.value, true)

  navigationFlush.resolve(true)
  assert.equal(await navigation, false)
  assert.equal(controller.actionBusy.value, true)

  operationGate.resolve(operation())
  await generation
  assert.equal(controller.actionBusy.value, false)
})

test('dispose fences a pending navigation without allowing its late flush to revive the controller', async () => {
  const state = autosave({ revision: 4, hash: HASH })
  const flushGate = deferred()
  const flushStarted = deferred()
  state.flush = async () => {
    flushStarted.resolve()
    return flushGate.promise
  }
  let candidateStarts = 0
  const controller = operationController({
    autosave: state,
    freezeCandidate: async () => { candidateStarts += 1 },
  })

  const navigation = controller.canNavigate()
  await flushStarted.promise
  controller.dispose()
  flushGate.resolve(true)

  assert.equal(await navigation, false)
  assert.equal(controller.actionBusy.value, false)
  assert.equal(await controller.saveCandidate(), false)
  assert.equal(candidateStarts, 0)
})

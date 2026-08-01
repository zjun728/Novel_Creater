import assert from 'node:assert/strict'
import test from 'node:test'

import { createDraftOperationCoordinator } from '../../src/application/writer/draftOperationCoordinator.js'

const PROJECT_ID = '11111111-1111-4111-8111-111111111111'
const SESSION_ID = '22222222-2222-4222-8222-222222222222'
const OPERATION_ID = '33333333-3333-4333-8333-333333333333'
const KEY = '44444444-4444-4444-8444-444444444444'
const HASH = 'a'.repeat(64)

function operation(overrides = {}) {
  return {
    operationId: OPERATION_ID,
    projectId: PROJECT_ID,
    chapterSessionId: SESSION_ID,
    operationType: 'generate_new',
    status: 'completed',
    lastEventSequence: 2,
    resultWorkingDraftRevision: 5,
    resultContentHash: HASH,
    failureCode: null,
    providerId: 'provider-1',
    modelName: 'writer-model',
    ...overrides,
  }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((nextResolve, nextReject) => {
    resolve = nextResolve
    reject = nextReject
  })
  return { promise, resolve, reject }
}

function coordinator(overrides = {}) {
  return createDraftOperationCoordinator({
    startOperation: async () => operation(),
    readOperation: async () => operation(),
    reloadWorkspace: async () => ({ workingDraft: { content: 'authoritative' } }),
    idFactory: () => KEY,
    ...overrides,
  })
}

function command() {
  return {
    expectedWorkingDraftRevision: 4,
    expectedContentHash: HASH,
    authorInstruction: '多一点人物试探',
  }
}

test('coordinator creates one frozen canonical command and prohibits duplicate starts for one action', async () => {
  const pending = deferred()
  const calls = []
  const subject = coordinator({
    startOperation: next => {
      calls.push(next)
      return pending.promise
    },
  })
  const request = subject.generateNew(command())
  assert.equal(subject.busy, true)
  await assert.rejects(() => subject.generateNew(command()), /already in progress/i)
  assert.equal(calls.length, 1)
  assert.deepEqual(calls[0], {
    operationType: 'generate_new',
    expectedWorkingDraftRevision: 4,
    expectedContentHash: HASH,
    idempotencyKey: KEY,
    authorInstruction: '多一点人物试探',
  })
  assert.equal(Object.isFrozen(calls[0]), true)
  pending.resolve(operation())
  await request
})

test('coordinator replays exactly the frozen command after an unknown transport outcome', async () => {
  const calls = []
  let attempt = 0
  const subject = coordinator({
    startOperation: async next => {
      calls.push(next)
      attempt += 1
      if (attempt === 1) throw new Error('network unavailable')
      return operation({ status: 'failed', resultWorkingDraftRevision: null, resultContentHash: null, failureCode: 'DraftProviderFailed' })
    },
  })
  await assert.rejects(() => subject.generateNew(command()), /network unavailable/)
  assert.equal(subject.status, 'unknown')
  assert.equal(subject.failureCode, 'request_unknown')
  await subject.retryUnknown()
  assert.equal(calls.length, 2)
  assert.strictEqual(calls[1], calls[0])
  assert.equal(subject.status, 'failed')
  assert.equal(subject.failureCode, 'DraftProviderFailed')
})

test('completed operation reloads authoritative workspace exactly once and never exposes output text', async () => {
  let reloads = 0
  const subject = coordinator({
    startOperation: async () => operation({ output: 'must-not-cross' }),
    reloadWorkspace: async () => {
      reloads += 1
      return { workingDraft: { content: 'authoritative only' } }
    },
  })
  const workspace = await subject.generateNew(command())
  assert.deepEqual(workspace, { workingDraft: { content: 'authoritative only' } })
  assert.equal(reloads, 1)
  assert.equal(JSON.stringify(subject.operation).includes('must-not-cross'), false)
})

test('failed and expired operations neither reload nor alter editor-owned workspace', async () => {
  let reloads = 0
  for (const result of [
    operation({ status: 'failed', resultWorkingDraftRevision: null, resultContentHash: null, failureCode: 'DraftProviderFailed' }),
    operation({ status: 'expired', lastEventSequence: 1, resultWorkingDraftRevision: null, resultContentHash: null, failureCode: null }),
  ]) {
    const subject = coordinator({
      startOperation: async () => result,
      reloadWorkspace: async () => { reloads += 1 },
    })
    assert.equal(await subject.generateNew(command()), null)
    assert.equal(subject.status, result.status)
  }
  assert.equal(reloads, 0)
})

test('resetContext fences late operation responses before they can reload or publish state', async () => {
  const pending = deferred()
  let reloads = 0
  const subject = coordinator({
    startOperation: () => pending.promise,
    reloadWorkspace: async () => { reloads += 1 },
  })
  const request = subject.generateNew(command())
  subject.resetContext()
  pending.resolve(operation())
  assert.equal(await request, null)
  assert.equal(reloads, 0)
  assert.equal(subject.operation, null)
  assert.equal(subject.status, 'idle')
})

test('dispose fences a late authoritative reload response', async () => {
  const pendingReload = deferred()
  const subject = coordinator({ reloadWorkspace: () => pendingReload.promise })
  const request = subject.generateNew(command())
  await Promise.resolve()
  subject.dispose()
  pendingReload.resolve({ workingDraft: { content: 'late' } })
  assert.equal(await request, null)
  assert.equal(subject.operation, null)
  assert.equal(subject.status, 'disposed')
})

test('coordinator exposes only read-only public state without request or provider secrets', async () => {
  const subject = coordinator({
    startOperation: async () => operation({
      prompt: 'secret prose',
      provider: { apiKey: 'secret-key' },
      model: { baseUrl: 'https://secret.invalid' },
    }),
  })
  await subject.generateNew(command())
  assert.equal(Object.isFrozen(subject), true)
  assert.throws(() => { subject.status = 'tampered' }, TypeError)
  const publicState = {
    status: subject.status,
    operation: subject.operation,
    busy: subject.busy,
    failureCode: subject.failureCode,
  }
  assert.equal(JSON.stringify(publicState).match(/secret|prompt|authorInstruction|idempotencyKey|baseUrl|responseBody/i), null)
})

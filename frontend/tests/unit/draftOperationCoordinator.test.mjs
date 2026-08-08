import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'

import { createDraftOperationCoordinator } from '../../src/application/writer/draftOperationCoordinator.js'
import { ApiError } from '../../src/api/db/api-error.js'

const PROJECT_ID = '11111111-1111-4111-8111-111111111111'
const SESSION_ID = '22222222-2222-4222-8222-222222222222'
const OPERATION_ID = '33333333-3333-4333-8333-333333333333'
const KEY = '44444444-4444-4444-8444-444444444444'
const HASH = 'a'.repeat(64)

function textHash(value) {
  return createHash('sha256').update(value, 'utf8').digest('hex')
}

function operation(overrides = {}) {
  const status = overrides.status ?? 'completed'
  const partialOutput = overrides.partialOutput
    ?? (status === 'completed' ? 'authoritative' : '')
  const partialOutputHash = overrides.partialOutputHash ?? textHash(partialOutput)
  const partialOutputScalars = overrides.partialOutputScalars
    ?? Array.from(partialOutput).length
  return {
    id: OPERATION_ID,
    projectId: PROJECT_ID,
    chapterSessionId: SESSION_ID,
    operationType: 'generate_new',
    status,
    lastEventSequence: status === 'completed' || status === 'failed' || status === 'cancelled' ? 2 : 1,
    partialOutput,
    partialOutputHash,
    partialOutputScalars,
    resultWorkingDraftRevision: status === 'completed' ? 5 : null,
    resultContentHash: status === 'completed' ? partialOutputHash : null,
    failureCode: status === 'failed' ? 'DraftProviderFailed' : null,
    model: Object.freeze({ providerId: 'provider-1', modelName: 'writer-model' }),
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

function immediatePollScheduler() {
  return { promise: Promise.resolve(), cancel() {} }
}

function coordinator(overrides = {}) {
  return createDraftOperationCoordinator({
    startOperation: async () => operation(),
    readOperation: async () => operation(),
    listEvents: async (operationId, after) => ({
      operationId,
      events: [],
      lastEventSequence: after,
      nextAfter: after,
      hasMore: false,
    }),
    cancelOperation: async () => operation({
      status: 'cancelled',
      partialOutput: '',
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
    reloadWorkspace: async () => ({ workingDraft: { content: 'authoritative' } }),
    idFactory: () => KEY,
    pollScheduler: immediatePollScheduler,
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

test('resume calibrates the fresh snapshot, drains only retained suffixes, and never POSTs or creates a key', async () => {
  const calls = []
  let reads = 0
  const subject = coordinator({
    startOperation: async () => assert.fail('resume must not POST'),
    idFactory: () => assert.fail('resume must not create a key'),
    readOperation: async operationId => {
      calls.push(['read', operationId])
      reads += 1
      return reads === 1
        ? operation({ status: 'running', lastEventSequence: 8, partialOutput: ' 甲' })
        : operation({
          status: 'completed',
          lastEventSequence: 10,
          partialOutput: '甲乙',
          resultWorkingDraftRevision: 5,
          resultContentHash: textHash('甲乙'),
        })
    },
    listEvents: async (operationId, after) => {
      calls.push(['events', operationId, after])
      assert.equal(after, 8)
      return {
        operationId,
        events: [{
          sequence: 9,
          type: 'delta',
          createdAt: 9,
          text: '乙 ',
          partialOutputHash: textHash(' 甲乙 '),
          partialOutputScalars: 4,
        }, {
          sequence: 10,
          type: 'completed',
          createdAt: 10,
          resultWorkingDraftRevision: 5,
          resultContentHash: textHash('甲乙'),
        }],
        lastEventSequence: 10,
        nextAfter: 10,
        hasMore: false,
      }
    },
  })

  const result = await subject.resume(OPERATION_ID)
  assert.deepEqual(result, { workingDraft: { content: 'authoritative' } })
  assert.equal(subject.preview, '甲乙')
  assert.equal(subject.reconnecting, false)
  assert.deepEqual(calls, [
    ['read', OPERATION_ID],
    ['events', OPERATION_ID, 8],
    ['read', OPERATION_ID],
  ])
})

test('coordinator calibrates normalized completed and cancelled snapshots after a terminal-only event page', async () => {
  for (const status of ['completed', 'cancelled']) {
    let eventReads = 0
    let reloads = 0
    const snapshots = []
    let subject
    subject = coordinator({
      startOperation: async () => operation({
        status: 'running',
        lastEventSequence: 1,
        partialOutput: '',
        resultWorkingDraftRevision: null,
        resultContentHash: null,
      }),
      listEvents: async (operationId, after) => {
        eventReads += 1
        if (eventReads === 1) {
          assert.equal(after, 1)
          return {
            operationId,
            events: [{
              sequence: 2,
              type: 'delta',
              createdAt: 2,
              text: ' 甲 ',
              partialOutputHash: textHash(' 甲 '),
              partialOutputScalars: 3,
            }],
            lastEventSequence: 3,
            nextAfter: 2,
            hasMore: true,
          }
        }
        assert.equal(after, 2)
        return {
          operationId,
          events: [{
            sequence: 3,
            type: status,
            createdAt: 3,
            resultWorkingDraftRevision: 5,
            resultContentHash: textHash('甲'),
          }],
          lastEventSequence: 3,
          nextAfter: 3,
          hasMore: false,
        }
      },
      readOperation: async () => operation({
        status,
        lastEventSequence: 3,
        partialOutput: '甲',
        resultWorkingDraftRevision: 5,
        resultContentHash: textHash('甲'),
      }),
      reloadWorkspace: async () => {
        reloads += 1
        return { workingDraft: { content: 'authoritative' } }
      },
      onChange: () => snapshots.push({
        status: subject.status,
        operation: subject.operation?.status ?? null,
        preview: subject.preview,
      }),
    })
    await subject.generateNew(command())
    assert.equal(subject.preview, '甲')
    assert.equal(subject.status, status)
    assert.equal(reloads, 1)
    const terminalSnapshots = snapshots.filter(snapshot => snapshot.operation === status)
    assert.ok(terminalSnapshots.length > 0)
    assert.equal(
      terminalSnapshots.every(snapshot => snapshot.preview === '甲'),
      true,
    )
  }
})

test('coordinator calibrates whitespace-only cancellation to empty without reloading', async () => {
  let reloads = 0
  const subject = coordinator({
    startOperation: async () => operation({
      status: 'running',
      lastEventSequence: 1,
      partialOutput: '',
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
    listEvents: async (operationId, after) => {
      assert.equal(after, 1)
      return {
        operationId,
        events: [{
          sequence: 2,
          type: 'delta',
          createdAt: 2,
          text: ' ',
          partialOutputHash: textHash(' '),
          partialOutputScalars: 1,
        }, {
          sequence: 3,
          type: 'cancelled',
          createdAt: 3,
          resultWorkingDraftRevision: null,
          resultContentHash: null,
        }],
        lastEventSequence: 3,
        nextAfter: 3,
        hasMore: false,
      }
    },
    readOperation: async () => operation({
      status: 'cancelled',
      lastEventSequence: 3,
      partialOutput: '',
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
    reloadWorkspace: async () => { reloads += 1 },
  })
  assert.equal(await subject.generateNew(command()), null)
  assert.equal(subject.preview, '')
  assert.equal(subject.status, 'cancelled')
  assert.equal(reloads, 0)
})

test('resume rejects a non-canonical operation id before any transport call', () => {
  let reads = 0
  const subject = coordinator({
    readOperation: async () => {
      reads += 1
      return operation()
    },
  })

  assert.throws(() => subject.resume('NOT-A-CANONICAL-ID'), TypeError)
  assert.equal(reads, 0)
  assert.equal(subject.status, 'idle')
  assert.equal(subject.busy, false)
})

test('status ahead of retained events drains immediately before any one-second wait', async () => {
  const calls = []
  let reads = 0
  let eventReads = 0
  let delays = 0
  const subject = coordinator({
    startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listEvents: async (operationId, after) => {
      calls.push(['events', after])
      eventReads += 1
      if (eventReads === 1) {
        return { operationId, events: [], lastEventSequence: 1, nextAfter: 1, hasMore: false }
      }
      if (eventReads === 3) {
        assert.equal(after, 2)
        return { operationId, events: [], lastEventSequence: 2, nextAfter: 2, hasMore: false }
      }
      if (eventReads === 4) {
        assert.equal(after, 2)
        return {
          operationId,
          events: [{
            sequence: 3,
            type: 'completed',
            createdAt: 3,
            resultWorkingDraftRevision: 5,
            resultContentHash: textHash('甲'),
          }],
          lastEventSequence: 3,
          nextAfter: 3,
          hasMore: false,
        }
      }
      return {
        operationId,
        events: [{
          sequence: 2,
          type: 'delta',
          createdAt: 2,
          text: '甲',
          partialOutputHash: textHash('甲'),
          partialOutputScalars: 1,
        }],
        lastEventSequence: 2,
        nextAfter: 2,
        hasMore: false,
      }
    },
    readOperation: async () => {
      reads += 1
      calls.push(['read', reads])
      return reads === 1
        ? operation({ status: 'running', lastEventSequence: 2, partialOutput: '甲' })
        : operation({
          status: 'completed',
          lastEventSequence: 3,
          partialOutput: '甲',
          resultWorkingDraftRevision: 5,
          resultContentHash: textHash('甲'),
        })
    },
    pollScheduler: () => {
      delays += 1
      calls.push(['delay'])
      return { promise: Promise.resolve(), cancel() {} }
    },
  })
  await subject.generateNew(command())
  assert.equal(subject.preview, '甲')
  assert.equal(delays, 1)
  assert.deepEqual(calls, [
    ['events', 1], ['read', 1], ['events', 1], ['delay'],
    ['events', 2], ['read', 2], ['events', 2],
  ])
})

test('a retained-cycle status behind the drained event cursor fails closed', async () => {
  let eventReads = 0
  let statusReads = 0
  const subject = coordinator({
    startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listEvents: async (operationId, after) => {
      eventReads += 1
      assert.equal(after, 1)
      return {
        operationId,
        events: [{
          sequence: 2,
          type: 'delta',
          createdAt: 2,
          text: '甲',
          partialOutputHash: textHash('甲'),
          partialOutputScalars: 1,
        }],
        lastEventSequence: 2,
        nextAfter: 2,
        hasMore: false,
      }
    },
    readOperation: async () => {
      statusReads += 1
      return operation({ status: 'running', lastEventSequence: 1 })
    },
  })

  await assert.rejects(subject.generateNew(command()), TypeError)
  assert.equal(subject.status, 'operation_invalid')
  assert.equal(subject.preview, '甲')
  assert.equal(eventReads, 1)
  assert.equal(statusReads, 1)
})

test('expired status drains its retained delta suffix without requiring a terminal event', async () => {
  let eventReads = 0
  let reloads = 0
  const subject = coordinator({
    startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listEvents: async (operationId, after) => {
      eventReads += 1
      if (eventReads === 1) {
        assert.equal(after, 1)
        return { operationId, events: [], lastEventSequence: 1, nextAfter: 1, hasMore: false }
      }
      assert.equal(after, 1)
      return {
        operationId,
        events: [{
          sequence: 2,
          type: 'delta',
          createdAt: 2,
          text: '甲',
          partialOutputHash: textHash('甲'),
          partialOutputScalars: 1,
        }],
        lastEventSequence: 2,
        nextAfter: 2,
        hasMore: false,
      }
    },
    readOperation: async () => operation({
      status: 'expired',
      lastEventSequence: 2,
      partialOutput: '甲',
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
    reloadWorkspace: async () => { reloads += 1 },
  })
  assert.equal(await subject.generateNew(command()), null)
  assert.equal(subject.status, 'expired')
  assert.equal(subject.preview, '甲')
  assert.equal(eventReads, 2)
  assert.equal(reloads, 0)
})

test('generic retained terminal evidence must match the same-cursor status before publish or reload', async () => {
  const cases = [
    ['failed', 'completed'],
    ['completed', 'cancelled'],
    ['completed', 'failed'],
    ['completed', 'expired'],
    ['failed', 'running'],
  ]
  for (const [eventType, status] of cases) {
    const snapshots = []
    let reloads = 0
    let statusRead = false
    let subject
    const event = eventType === 'completed'
      ? {
          sequence: 2,
          type: 'completed',
          createdAt: 2,
          resultWorkingDraftRevision: 5,
          resultContentHash: textHash('甲'),
        }
      : {
          sequence: 2,
          type: 'failed',
          createdAt: 2,
          failureCode: 'DraftProviderFailed',
        }
    const terminal = status === 'completed' || status === 'cancelled'
      ? operation({
          status,
          lastEventSequence: 2,
          partialOutput: '甲',
          resultWorkingDraftRevision: 5,
          resultContentHash: textHash('甲'),
        })
      : operation({
          status,
          lastEventSequence: 2,
          partialOutput: '',
          resultWorkingDraftRevision: null,
          resultContentHash: null,
          failureCode: status === 'failed' ? 'DraftProviderFailed' : null,
        })
    subject = coordinator({
      startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
      listEvents: async operationId => ({
        operationId,
        events: [event],
        lastEventSequence: 2,
        nextAfter: 2,
        hasMore: false,
      }),
      readOperation: async () => {
        statusRead = true
        return terminal
      },
      reloadWorkspace: async () => { reloads += 1 },
      onChange: () => snapshots.push({
        status: subject.status,
        operation: subject.operation?.status ?? null,
        afterStatusRead: statusRead,
      }),
    })
    await assert.rejects(subject.generateNew(command()), TypeError, `${eventType}->${status}`)
    assert.equal(subject.status, 'operation_invalid', `${eventType}->${status}`)
    assert.equal(subject.operation, null, `${eventType}->${status}`)
    assert.equal(reloads, 0, `${eventType}->${status}`)
    assert.equal(
      snapshots.some(snapshot => (
        snapshot.afterStatusRead && snapshot.operation === status
      )),
      false,
      `${eventType}->${status}`,
    )
  }
})

test('generic retained terminal evidence binds result revisions hashes and failure codes', async () => {
  const cases = [
    ['completed', {
      sequence: 2,
      type: 'completed',
      createdAt: 2,
      resultWorkingDraftRevision: 5,
      resultContentHash: textHash('甲'),
    }, operation({
      status: 'completed',
      lastEventSequence: 2,
      partialOutput: '甲',
      resultWorkingDraftRevision: 6,
      resultContentHash: textHash('甲'),
    })],
    ['cancelled', {
      sequence: 2,
      type: 'cancelled',
      createdAt: 2,
      resultWorkingDraftRevision: 5,
      resultContentHash: textHash('甲'),
    }, operation({
      status: 'cancelled',
      lastEventSequence: 2,
      partialOutput: '乙',
      resultWorkingDraftRevision: 5,
      resultContentHash: textHash('乙'),
    })],
    ['failed', {
      sequence: 2,
      type: 'failed',
      createdAt: 2,
      failureCode: 'DraftProviderFailed',
    }, operation({
      status: 'failed',
      lastEventSequence: 2,
      resultWorkingDraftRevision: null,
      resultContentHash: null,
      failureCode: 'DraftProviderResultInvalid',
    })],
  ]
  for (const [status, event, terminal] of cases) {
    let reloads = 0
    const subject = coordinator({
      startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
      listEvents: async operationId => ({
        operationId,
        events: [event],
        lastEventSequence: 2,
        nextAfter: 2,
        hasMore: false,
      }),
      readOperation: async () => terminal,
      reloadWorkspace: async () => { reloads += 1 },
    })
    await assert.rejects(subject.generateNew(command()), TypeError, status)
    assert.equal(subject.status, 'operation_invalid', status)
    assert.equal(subject.operation, null, status)
    assert.equal(reloads, 0, status)
  }
})

test('an unknown transport failure during the status-ahead drain keeps same-key recovery', async () => {
  const starts = []
  let eventReads = 0
  const subject = coordinator({
    startOperation: async next => {
      starts.push(next)
      return starts.length === 1
        ? operation({ status: 'running', lastEventSequence: 1 })
        : operation()
    },
    listEvents: async (operationId, after) => {
      eventReads += 1
      if (eventReads === 1) {
        return { operationId, events: [], lastEventSequence: after, nextAfter: after, hasMore: false }
      }
      if (eventReads === 3) {
        return {
          operationId,
          events: [{
            sequence: 2,
            type: 'completed',
            createdAt: 2,
            resultWorkingDraftRevision: 5,
            resultContentHash: textHash('authoritative'),
          }],
          lastEventSequence: 2,
          nextAfter: 2,
          hasMore: false,
        }
      }
      throw new ApiError()
    },
    readOperation: async () => operation({
      status: 'running',
      lastEventSequence: 2,
      partialOutput: '甲',
    }),
  })

  await assert.rejects(subject.generateNew(command()), ApiError)
  assert.equal(subject.status, 'unknown')
  assert.equal(subject.retryAvailable, true)
  await subject.retryUnknown()
  assert.strictEqual(starts[1], starts[0])
})

test('cancellation wins over a rejected status-ahead event drain', async () => {
  const secondDrain = deferred()
  const secondDrainStarted = deferred()
  let eventReads = 0
  const subject = coordinator({
    startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listEvents: async (operationId, after) => {
      eventReads += 1
      if (eventReads === 1) {
        return { operationId, events: [], lastEventSequence: after, nextAfter: after, hasMore: false }
      }
      secondDrainStarted.resolve()
      return secondDrain.promise
    },
    readOperation: async () => operation({
      status: 'running',
      lastEventSequence: 2,
      partialOutput: '甲',
    }),
    cancelOperation: async () => operation({
      status: 'cancelled',
      lastEventSequence: 2,
      partialOutput: '',
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
  })

  const generation = subject.generateNew(command())
  await secondDrainStarted.promise
  const cancelled = await subject.cancelActive()
  secondDrain.reject(new Error('stale second drain failed'))

  assert.deepEqual(await generation, cancelled)
  assert.equal(subject.status, 'cancelled')
})

test('cancellation during asynchronous page hashing prevents another event request', async () => {
  const hashStarted = deferred()
  const hashGate = deferred()
  const unexpectedList = deferred()
  const unexpectedListStarted = deferred()
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  const originalCrypto = globalThis.crypto
  const originalDigest = originalCrypto.subtle.digest.bind(originalCrypto.subtle)
  let gated = false
  let listCalls = 0
  let generation
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true,
    value: {
      subtle: {
        async digest(algorithm, data) {
          if (!gated && data.byteLength > 0) {
            gated = true
            hashStarted.resolve()
            await hashGate.promise
          }
          return originalDigest(algorithm, data)
        },
      },
    },
  })
  try {
    const subject = coordinator({
      startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
      listEvents: async operationId => {
        listCalls += 1
        if (listCalls > 1) {
          unexpectedListStarted.resolve()
          return unexpectedList.promise
        }
        return {
          operationId,
          events: [{
            sequence: 2,
            type: 'delta',
            createdAt: 2,
            text: '甲',
            partialOutputHash: textHash('甲'),
            partialOutputScalars: 1,
          }],
          lastEventSequence: 3,
          nextAfter: 2,
          hasMore: true,
        }
      },
      cancelOperation: async () => operation({
        status: 'cancelled',
        lastEventSequence: 3,
        partialOutput: '甲',
        resultWorkingDraftRevision: 5,
        resultContentHash: textHash('甲'),
      }),
    })

    generation = subject.generateNew(command())
    await hashStarted.promise
    const cancelled = await subject.cancelActive()
    hashGate.resolve()
    const winner = await Promise.race([
      generation.then(value => ({ kind: 'settled', value })),
      unexpectedListStarted.promise.then(() => ({ kind: 'extra-list' })),
    ])
    if (winner.kind === 'extra-list') {
      unexpectedList.resolve({
        operationId: OPERATION_ID,
        events: [],
        lastEventSequence: 3,
        nextAfter: 3,
        hasMore: false,
      })
    }
    const generationResult = await generation
    assert.equal(winner.kind, 'settled')
    assert.equal(listCalls, 1)
    assert.deepEqual(generationResult, cancelled)
  } finally {
    hashGate.resolve()
    unexpectedList.resolve({
      operationId: OPERATION_ID,
      events: [],
      lastEventSequence: 3,
      nextAfter: 3,
      hasMore: false,
    })
    if (generation) await generation.catch(() => {})
    if (descriptor) Object.defineProperty(globalThis, 'crypto', descriptor)
    else delete globalThis.crypto
  }
})

test('cancellation during status snapshot hashing cannot publish stale running state', async () => {
  const hashStarted = deferred()
  const hashGate = deferred()
  const hashReleased = deferred()
  const cancelStarted = deferred()
  const pendingCancel = deferred()
  const descriptor = Object.getOwnPropertyDescriptor(globalThis, 'crypto')
  const originalCrypto = globalThis.crypto
  const originalDigest = originalCrypto.subtle.digest.bind(originalCrypto.subtle)
  let nonEmptyDigests = 0
  const nonEmptyInputs = []
  let generation
  const snapshots = []
  let subject
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true,
    value: {
      subtle: {
        async digest(algorithm, data) {
          if (data.byteLength > 0) {
            nonEmptyDigests += 1
            nonEmptyInputs.push(new TextDecoder().decode(data))
            if (nonEmptyDigests === 3) {
              hashStarted.resolve()
              await hashGate.promise
            }
          }
          const result = await originalDigest(algorithm, data)
          if (nonEmptyDigests === 3) hashReleased.resolve()
          return result
        },
      },
    },
  })
  try {
    subject = coordinator({
      startOperation: async () => operation({
        status: 'running',
        lastEventSequence: 2,
        partialOutput: '起',
      }),
      listEvents: async operationId => ({
        operationId,
        events: [{
          sequence: 3,
          type: 'delta',
          createdAt: 2,
          text: '甲',
          partialOutputHash: textHash('起甲'),
          partialOutputScalars: 2,
        }],
        lastEventSequence: 3,
        nextAfter: 3,
        hasMore: false,
      }),
      readOperation: async () => operation({
        status: 'running',
        lastEventSequence: 3,
        partialOutput: '起甲',
      }),
      cancelOperation: async () => {
        cancelStarted.resolve()
        return pendingCancel.promise
      },
      onChange: () => snapshots.push({
        status: subject.status,
        operation: subject.operation?.status ?? null,
        operationRef: subject.operation,
        cancelling: subject.cancelling,
      }),
    })

    generation = subject.generateNew(command())
    await hashStarted.promise
    assert.deepEqual(nonEmptyInputs, ['起', '起甲', '起甲'])
    const cancellation = subject.cancelActive()
    await cancelStarted.promise
    assert.equal(
      snapshots.filter(snapshot => snapshot.cancelling && snapshot.operation === 'running').length,
      1,
    )
    hashGate.resolve()
    await hashReleased.promise
    await new Promise(resolve => setImmediate(resolve))
    assert.equal(
      snapshots.filter(snapshot => snapshot.cancelling && snapshot.operation === 'running').length,
      1,
    )
    pendingCancel.resolve(operation({
      status: 'cancelled',
      lastEventSequence: 4,
      partialOutput: '起甲',
      resultWorkingDraftRevision: 5,
      resultContentHash: textHash('起甲'),
    }))
    const cancelled = await cancellation

    assert.deepEqual(await generation, cancelled)
    assert.equal(subject.status, 'cancelled')
    assert.equal(subject.operation.status, 'cancelled')
    assert.equal(subject.busy, false)
    const terminalReferences = snapshots
      .filter(snapshot => snapshot.operation === 'cancelled')
      .map(snapshot => snapshot.operationRef)
    assert.equal(new Set(terminalReferences).size, 1)
  } finally {
    hashGate.resolve()
    pendingCancel.resolve(operation({
      status: 'cancelled',
      lastEventSequence: 4,
      partialOutput: '起甲',
      resultWorkingDraftRevision: 5,
      resultContentHash: textHash('起甲'),
    }))
    if (generation) await generation.catch(() => {})
    if (descriptor) Object.defineProperty(globalThis, 'crypto', descriptor)
    else delete globalThis.crypto
  }
})

test('cancelActive shares one terminal settlement with the running action and reloads only for output', async () => {
  for (const partialOutput of ['甲', '']) {
    const eventGate = deferred()
    const eventStarted = deferred()
    let reloads = 0
    let cancels = 0
    const subject = coordinator({
      startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
      listEvents: async (operationId, after) => {
        eventStarted.resolve()
        await eventGate.promise
        if (!partialOutput) throw new Error('stale event request failed')
        return { operationId, events: [], lastEventSequence: after, nextAfter: after, hasMore: false }
      },
      cancelOperation: async operationId => {
        cancels += 1
        return operation({
          id: operationId,
          status: 'cancelled',
          lastEventSequence: 2,
          partialOutput,
          resultWorkingDraftRevision: partialOutput ? 5 : null,
          resultContentHash: partialOutput ? textHash(partialOutput) : null,
        })
      },
      reloadWorkspace: async () => {
        reloads += 1
        return { workingDraft: { content: partialOutput } }
      },
    })
    const generation = subject.generateNew(command())
    await eventStarted.promise
    const cancellation = subject.cancelActive()
    const repeatedCancellation = subject.cancelActive()
    assert.strictEqual(repeatedCancellation, cancellation)
    assert.equal(subject.cancelling, true)
    const cancelResult = await cancellation
    eventGate.resolve()
    const generationResult = await generation
    assert.equal(cancels, 1)
    assert.equal(reloads, partialOutput ? 1 : 0)
    assert.deepEqual(generationResult, cancelResult)
    assert.equal(subject.status, 'cancelled')
    assert.equal(subject.cancelling, false)
  }
})

test('a stale status response cannot roll back a completed cancellation', async () => {
  const pendingStatus = deferred()
  const statusStarted = deferred()
  const subject = coordinator({
    startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    readOperation: () => {
      statusStarted.resolve()
      return pendingStatus.promise
    },
    cancelOperation: async () => operation({
      status: 'cancelled',
      lastEventSequence: 2,
      partialOutput: '甲',
      resultWorkingDraftRevision: 5,
      resultContentHash: textHash('甲'),
    }),
  })
  const generation = subject.generateNew(command())
  await statusStarted.promise
  const cancelled = await subject.cancelActive()
  pendingStatus.resolve(operation({ status: 'running', lastEventSequence: 1 }))
  assert.deepEqual(await generation, cancelled)
  assert.equal(subject.status, 'cancelled')
  assert.equal(subject.preview, '甲')
})

test('a stale rejected status request settles through the completed cancellation', async () => {
  const pendingStatus = deferred()
  const statusStarted = deferred()
  const subject = coordinator({
    startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    readOperation: () => {
      statusStarted.resolve()
      return pendingStatus.promise
    },
    cancelOperation: async () => operation({
      status: 'cancelled',
      lastEventSequence: 2,
      partialOutput: '',
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
  })

  const generation = subject.generateNew(command())
  await statusStarted.promise
  const cancelled = await subject.cancelActive()
  pendingStatus.reject(new Error('stale status request failed'))

  assert.deepEqual(await generation, cancelled)
  assert.equal(subject.status, 'cancelled')
  assert.equal(subject.preview, '')
})

test('resetContext fences a pending event page before it can mutate preview state', async () => {
  const pendingEvents = deferred()
  const eventsStarted = deferred()
  const subject = coordinator({
    startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listEvents: () => {
      eventsStarted.resolve()
      return pendingEvents.promise
    },
  })

  const generation = subject.generateNew(command())
  await eventsStarted.promise
  subject.resetContext()
  pendingEvents.resolve({
    operationId: OPERATION_ID,
    events: [{
      sequence: 2,
      type: 'delta',
      text: '迟到正文',
      partialOutputHash: textHash('迟到正文'),
      partialOutputScalars: 4,
      createdAt: 1,
    }],
    lastEventSequence: 2,
    nextAfter: 2,
    hasMore: false,
  })

  assert.equal(await generation, null)
  assert.equal(subject.status, 'idle')
  assert.equal(subject.preview, '')
  assert.equal(subject.busy, false)
})

test('author instruction limit counts Unicode scalars and rejects malformed Unicode', async () => {
  const instructions = []
  const subjectFor = () => coordinator({
    startOperation: async next => {
      instructions.push(next.authorInstruction)
      return operation()
    },
  })

  await subjectFor().generateNew({ ...command(), authorInstruction: '😀'.repeat(1_001) })
  await subjectFor().generateNew({ ...command(), authorInstruction: '😀'.repeat(2_000) })
  assert.deepEqual(instructions.map(value => Array.from(value).length), [1_001, 2_000])
  assert.throws(
    () => subjectFor().generateNew({ ...command(), authorInstruction: '😀'.repeat(2_001) }),
    TypeError,
  )
  assert.throws(
    () => subjectFor().generateNew({ ...command(), authorInstruction: '\ud800' }),
    TypeError,
  )
})

test('coordinator replays exactly the frozen command after an unknown transport outcome', async () => {
  const calls = []
  let attempt = 0
  const subject = coordinator({
    startOperation: async next => {
      calls.push(next)
      attempt += 1
      if (attempt === 1) throw new ApiError()
      return operation({ status: 'failed', resultWorkingDraftRevision: null, resultContentHash: null, failureCode: 'DraftProviderFailed' })
    },
  })
  await assert.rejects(() => subject.generateNew(command()), ApiError)
  assert.equal(subject.status, 'unknown')
  assert.equal(subject.failureCode, 'request_unknown')
  await subject.retryUnknown()
  assert.equal(calls.length, 2)
  assert.strictEqual(calls[1], calls[0])
  assert.equal(subject.status, 'failed')
  assert.equal(subject.failureCode, 'DraftProviderFailed')
})

test('hash-invalid start and resume snapshots never become public operations', async () => {
  for (const mode of ['start', 'resume']) {
    const snapshots = []
    let reloads = 0
    let subject
    const invalid = operation({
      status: mode === 'start' ? 'running' : 'completed',
      lastEventSequence: 2,
      partialOutput: '甲',
      partialOutputHash: textHash('乙'),
      resultWorkingDraftRevision: mode === 'start' ? null : 5,
      resultContentHash: mode === 'start' ? null : textHash('乙'),
    })
    subject = coordinator({
      startOperation: async () => invalid,
      readOperation: async () => invalid,
      reloadWorkspace: async () => { reloads += 1 },
      onChange: () => snapshots.push({
        status: subject.status,
        operation: subject.operation?.status ?? null,
        failureCode: subject.failureCode,
      }),
    })
    const request = mode === 'start'
      ? subject.generateNew(command())
      : subject.resume(OPERATION_ID)
    await assert.rejects(request, TypeError)
    assert.equal(subject.status, 'operation_invalid')
    assert.equal(subject.operation, null)
    assert.equal(reloads, 0)
    assert.equal(snapshots.some(snapshot => snapshot.operation === invalid.status), false)
  }
})

test('hash-invalid direct cancellation never publishes its terminal snapshot', async () => {
  const eventGate = deferred()
  const eventStarted = deferred()
  const snapshots = []
  let reloads = 0
  let subject
  subject = coordinator({
    startOperation: async () => operation({ status: 'running', lastEventSequence: 1 }),
    listEvents: async () => {
      eventStarted.resolve()
      return eventGate.promise
    },
    cancelOperation: async () => operation({
      status: 'cancelled',
      lastEventSequence: 2,
      partialOutput: '甲',
      partialOutputHash: textHash('乙'),
      resultWorkingDraftRevision: 5,
      resultContentHash: textHash('乙'),
    }),
    reloadWorkspace: async () => { reloads += 1 },
    onChange: () => snapshots.push({
      status: subject.status,
      operation: subject.operation?.status ?? null,
      failureCode: subject.failureCode,
    }),
  })
  const generation = subject.generateNew(command())
  await eventStarted.promise
  await assert.rejects(subject.cancelActive(), TypeError)
  eventGate.resolve({
    operationId: OPERATION_ID,
    events: [],
    lastEventSequence: 1,
    nextAfter: 1,
    hasMore: false,
  })
  await assert.rejects(generation, TypeError)
  assert.equal(subject.status, 'operation_invalid')
  assert.equal(subject.operation, null)
  assert.equal(reloads, 0)
  assert.equal(snapshots.some(snapshot => snapshot.operation === 'cancelled'), false)
})

test('same-key completed and cancelled replays drain retained terminal suffixes before reloading', async () => {
  for (const status of ['completed', 'cancelled']) {
    const starts = []
    const eventCursors = []
    let reads = 0
    let reloads = 0
    const subject = coordinator({
      startOperation: async next => {
        starts.push(next)
        return starts.length === 1
          ? operation({ status: 'running', lastEventSequence: 1 })
          : operation({
            status,
            lastEventSequence: 3,
            partialOutput: '甲',
            resultWorkingDraftRevision: 5,
            resultContentHash: textHash('甲'),
          })
      },
      listEvents: async (operationId, after) => {
        eventCursors.push(after)
        return eventCursors.length === 1
          ? { operationId, events: [], lastEventSequence: 1, nextAfter: 1, hasMore: false }
          : {
              operationId,
              events: [{
                sequence: 2,
                type: 'delta',
                createdAt: 2,
                text: '甲',
                partialOutputHash: textHash('甲'),
                partialOutputScalars: 1,
              }, {
                sequence: 3,
                type: status,
                createdAt: 3,
                resultWorkingDraftRevision: 5,
                resultContentHash: textHash('甲'),
              }],
              lastEventSequence: 3,
              nextAfter: 3,
              hasMore: false,
            }
      },
      readOperation: async () => {
        reads += 1
        throw new ApiError()
      },
      reloadWorkspace: async () => {
        reloads += 1
        return { workingDraft: { content: 'authoritative' } }
      },
    })
    await assert.rejects(subject.generateNew(command()), ApiError)
    assert.deepEqual(await subject.retryUnknown(), {
      workingDraft: { content: 'authoritative' },
    })
    assert.strictEqual(starts[1], starts[0])
    assert.deepEqual(eventCursors, [1, 1])
    assert.equal(reads, 1)
    assert.equal(subject.status, status)
    assert.equal(subject.preview, '甲')
    assert.equal(reloads, 1)
  }
})

test('hash-invalid same-key replay never publishes its cancelled terminal snapshot', async () => {
  const snapshots = []
  let eventReads = 0
  let subject
  subject = coordinator({
    startOperation: async () => (
      eventReads === 0
        ? operation({ status: 'running', lastEventSequence: 1 })
        : operation({
          status: 'cancelled',
          lastEventSequence: 2,
          partialOutput: '甲',
          partialOutputHash: textHash('乙'),
          resultWorkingDraftRevision: 5,
          resultContentHash: textHash('乙'),
        })
    ),
    listEvents: async operationId => {
      eventReads += 1
      if (eventReads === 1) {
        return { operationId, events: [], lastEventSequence: 1, nextAfter: 1, hasMore: false }
      }
      return {
        operationId,
        events: [{
          sequence: 2,
          type: 'cancelled',
          createdAt: 2,
          resultWorkingDraftRevision: 5,
          resultContentHash: textHash('乙'),
        }],
        lastEventSequence: 2,
        nextAfter: 2,
        hasMore: false,
      }
    },
    readOperation: async () => { throw new ApiError() },
    onChange: () => snapshots.push({
      status: subject.status,
      operation: subject.operation?.status ?? null,
      failureCode: subject.failureCode,
    }),
  })
  await assert.rejects(subject.generateNew(command()), ApiError)
  await assert.rejects(subject.retryUnknown(), TypeError)
  assert.equal(subject.status, 'operation_invalid')
  assert.equal(snapshots.some(snapshot => snapshot.operation === 'cancelled'), false)
})

test('same-key replay rejects a lower status cursor and a mismatched terminal page without reloading', async () => {
  for (const caseName of ['lower_cursor', 'wrong_terminal']) {
    const eventCursors = []
    let starts = 0
    let reads = 0
    let reloads = 0
    const subject = coordinator({
      startOperation: async () => {
        starts += 1
        if (starts === 1) return operation({ status: 'running', lastEventSequence: 1 })
        if (caseName === 'lower_cursor') {
          return operation({
            status: 'expired',
            lastEventSequence: 1,
            resultWorkingDraftRevision: null,
            resultContentHash: null,
          })
        }
        return operation({
          status: 'completed',
          lastEventSequence: 3,
          partialOutput: '甲',
          resultWorkingDraftRevision: 5,
          resultContentHash: textHash('甲'),
        })
      },
      listEvents: async (operationId, after) => {
        eventCursors.push(after)
        if (caseName === 'lower_cursor' || eventCursors.length === 1) {
          return {
            operationId,
            events: [{
              sequence: 2,
              type: 'delta',
              createdAt: 2,
              text: '甲',
              partialOutputHash: textHash('甲'),
              partialOutputScalars: 1,
            }],
            lastEventSequence: 2,
            nextAfter: 2,
            hasMore: false,
          }
        }
        return {
          operationId,
          events: [{
            sequence: 2,
            type: 'delta',
            createdAt: 2,
            text: '甲',
            partialOutputHash: textHash('甲'),
            partialOutputScalars: 1,
          }, {
            sequence: 3,
            type: 'failed',
            createdAt: 3,
            failureCode: 'DraftProviderFailed',
          }],
          lastEventSequence: 3,
          nextAfter: 3,
          hasMore: false,
        }
      },
      readOperation: async () => {
        reads += 1
        throw new ApiError()
      },
      reloadWorkspace: async () => { reloads += 1 },
    })
    await assert.rejects(subject.generateNew(command()), ApiError)
    await assert.rejects(subject.retryUnknown(), TypeError, caseName)
    assert.equal(subject.status, 'operation_invalid', caseName)
    assert.equal(reloads, 0, caseName)
    assert.equal(reads, 1, caseName)
    assert.deepEqual(
      eventCursors,
      caseName === 'lower_cursor' ? [1] : [1, 2],
      caseName,
    )
  }
})

test('exact durable-operation 502 keeps the frozen command for same-key replay', async () => {
  const calls = []
  let attempt = 0
  const subject = coordinator({
    startOperation: async next => {
      calls.push(next)
      attempt += 1
      if (attempt === 1) {
        throw new ApiError({ status: 502, code: 'DraftOperationUnavailable' })
      }
      return operation({
        status: 'failed',
        resultWorkingDraftRevision: null,
        resultContentHash: null,
        failureCode: 'DraftProviderFailed',
      })
    },
  })

  await assert.rejects(() => subject.generateNew(command()), ApiError)
  assert.equal(subject.status, 'unknown')
  await subject.retryUnknown()
  assert.strictEqual(calls[1], calls[0])
})

test('explicit unknown retry covers the lease window then reconciles once with the same key', async () => {
  const starts = []
  let reads = 0
  let delays = 0
  const subject = coordinator({
    startOperation: async next => {
      starts.push(next)
      if (starts.length === 1) {
        throw new ApiError({ status: 502, code: 'DraftOperationUnavailable' })
      }
      if (starts.length === 2) {
        return operation({
          status: 'running', lastEventSequence: 1,
          resultWorkingDraftRevision: null, resultContentHash: null,
        })
      }
      return operation({
        status: 'expired', lastEventSequence: 1,
        resultWorkingDraftRevision: null, resultContentHash: null,
      })
    },
    readOperation: async () => {
      reads += 1
      return operation({
        status: 'running', lastEventSequence: 1,
        resultWorkingDraftRevision: null, resultContentHash: null,
      })
    },
    pollScheduler: () => {
      delays += 1
      return { promise: Promise.resolve(), cancel() {} }
    },
  })

  await assert.rejects(() => subject.generateNew(command()), ApiError)
  assert.equal(await subject.retryUnknown(), null)
  assert.equal(starts.length, 3)
  assert.strictEqual(starts[1], starts[0])
  assert.strictEqual(starts[2], starts[0])
  assert.equal(reads, 1_261)
  assert.equal(delays, 1_260)
  assert.equal(subject.status, 'expired')
})

test('lease-end reconciliation is bounded when the same operation is still running', async () => {
  let starts = 0
  const subject = coordinator({
    startOperation: async () => {
      starts += 1
      if (starts === 1) {
        throw new ApiError({ status: 502, code: 'DraftOperationUnavailable' })
      }
      return operation({
        status: 'running', lastEventSequence: 1,
        resultWorkingDraftRevision: null, resultContentHash: null,
      })
    },
    readOperation: async () => operation({
      status: 'running', lastEventSequence: 1,
      resultWorkingDraftRevision: null, resultContentHash: null,
    }),
    pollScheduler: () => ({ promise: Promise.resolve(), cancel() {} }),
  })

  await assert.rejects(() => subject.generateNew(command()), ApiError)
  assert.equal(await subject.retryUnknown(), null)
  assert.equal(starts, 3)
  assert.equal(subject.status, 'unknown')
  assert.equal(subject.failureCode, 'request_unknown')
})

test('reset and dispose cancel explicit lease recovery before automatic replay', async () => {
  for (const invalidate of [
    subject => subject.resetContext(),
    subject => subject.dispose(),
  ]) {
    const delay = deferred()
    const delayStarted = deferred()
    let starts = 0
    let cancelled = 0
    const subject = coordinator({
      startOperation: async () => {
        starts += 1
        if (starts === 1) {
          throw new ApiError({ status: 502, code: 'DraftOperationUnavailable' })
        }
        return operation({
          status: 'running', lastEventSequence: 1,
          resultWorkingDraftRevision: null, resultContentHash: null,
        })
      },
      readOperation: async () => operation({
        status: 'running', lastEventSequence: 1,
        resultWorkingDraftRevision: null, resultContentHash: null,
      }),
      pollScheduler: () => ({
        promise: (delayStarted.resolve(), delay.promise),
        cancel() {
          cancelled += 1
          delay.resolve()
        },
      }),
    })
    await assert.rejects(() => subject.generateNew(command()), ApiError)
    const recovery = subject.retryUnknown()
    await delayStarted.promise
    invalidate(subject)
    assert.equal(await recovery, null)
    assert.equal(starts, 2)
    assert.equal(cancelled, 1)
  }
})

test('an unrelated 502 remains a known rejection without recovery state', async () => {
  const subject = coordinator({
    startOperation: async () => {
      throw new ApiError({ status: 502, code: 'GatewayUnavailable' })
    },
  })

  await assert.rejects(() => subject.generateNew(command()), ApiError)
  assert.equal(subject.status, 'request_rejected')
  await assert.rejects(() => subject.retryUnknown(), /no unknown/i)
})

test('coordinator polls a running operation with its fenced id until completed once', async () => {
  const reads = []
  let reloads = 0
  const subject = coordinator({
    startOperation: async () => operation({
      status: 'running',
      lastEventSequence: 1,
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
    readOperation: async operationId => {
      reads.push(operationId)
      return reads.length === 1
        ? operation({
          status: 'running',
          lastEventSequence: 1,
          resultWorkingDraftRevision: null,
          resultContentHash: null,
        })
        : operation({ lastEventSequence: 3 })
    },
    listEvents: async (operationId, after) => (reads.length < 2
      ? { operationId, events: [], lastEventSequence: after, nextAfter: after, hasMore: false }
      : {
          operationId,
          events: [
            {
              sequence: 2,
              type: 'delta',
              createdAt: 2,
              text: 'authoritative',
              partialOutputHash: textHash('authoritative'),
              partialOutputScalars: 13,
            },
            {
              sequence: 3,
              type: 'completed',
              createdAt: 3,
              resultWorkingDraftRevision: 5,
              resultContentHash: textHash('authoritative'),
            },
          ],
          lastEventSequence: 3,
          nextAfter: 3,
          hasMore: false,
        }),
    reloadWorkspace: async () => {
      reloads += 1
      return { workingDraft: { content: 'reloaded' } }
    },
  })
  assert.deepEqual(await subject.generateNew(command()), {
    workingDraft: { content: 'reloaded' },
  })
  assert.deepEqual(reads, [OPERATION_ID, OPERATION_ID])
  assert.equal(reloads, 1)
  assert.equal(subject.status, 'completed')
})

test('coordinator polls a running operation through failed and expired terminal states without reload', async () => {
  for (const terminal of [
    operation({
      status: 'failed',
      resultWorkingDraftRevision: null,
      resultContentHash: null,
      failureCode: 'DraftProviderFailed',
    }),
    operation({
      status: 'expired',
      lastEventSequence: 1,
      resultWorkingDraftRevision: null,
      resultContentHash: null,
    }),
  ]) {
    let reloads = 0
    const subject = coordinator({
      startOperation: async () => operation({
        status: 'running',
        lastEventSequence: 1,
        resultWorkingDraftRevision: null,
        resultContentHash: null,
      }),
      readOperation: async () => terminal,
      listEvents: async (operationId, after) => (
        terminal.lastEventSequence === after
          ? { operationId, events: [], lastEventSequence: after, nextAfter: after, hasMore: false }
          : {
              operationId,
              events: [{
                sequence: 2,
                type: terminal.status,
                createdAt: 2,
                failureCode: terminal.failureCode,
              }],
              lastEventSequence: 2,
              nextAfter: 2,
              hasMore: false,
            }
      ),
      reloadWorkspace: async () => { reloads += 1 },
    })
    assert.equal(await subject.generateNew(command()), null)
    assert.equal(subject.status, terminal.status)
    assert.equal(reloads, 0)
  }
})

test('coordinator fences reset and dispose while a status read is pending', async () => {
  for (const reset of [
    subject => subject.resetContext(),
    subject => subject.dispose(),
  ]) {
    const pendingRead = deferred()
    let reloads = 0
    const subject = coordinator({
      startOperation: async () => operation({
        status: 'running',
        lastEventSequence: 1,
        resultWorkingDraftRevision: null,
        resultContentHash: null,
      }),
      readOperation: () => pendingRead.promise,
      reloadWorkspace: async () => { reloads += 1 },
    })
    const request = subject.generateNew(command())
    await Promise.resolve()
    reset(subject)
    pendingRead.resolve(operation())
    assert.equal(await request, null)
    assert.equal(reloads, 0)
    assert.equal(subject.operation, null)
  }
})

test('reset and dispose cancel a pending bounded poll delay without another status read', async () => {
  for (const invalidate of [
    subject => subject.resetContext(),
    subject => subject.dispose(),
  ]) {
    const delay = deferred()
    const delayStarted = deferred()
    let cancelled = 0
    let reads = 0
    const subject = coordinator({
      startOperation: async () => operation({
        status: 'running',
        lastEventSequence: 1,
        resultWorkingDraftRevision: null,
        resultContentHash: null,
      }),
      readOperation: async () => {
        reads += 1
        return operation({
          status: 'running',
          lastEventSequence: 1,
          resultWorkingDraftRevision: null,
          resultContentHash: null,
        })
      },
      pollScheduler: delayMs => {
        assert.equal(delayMs, 1_000)
        delayStarted.resolve()
        return {
          promise: delay.promise,
          cancel() {
            cancelled += 1
            delay.resolve()
          },
        }
      },
    })
    const request = subject.generateNew(command())
    await delayStarted.promise
    invalidate(subject)
    assert.equal(await request, null)
    assert.equal(cancelled, 1)
    assert.equal(reads, 1)
  }
})

test('known HTTP rejection is public-safe, never retryable, and permits a distinct new action', async () => {
  const knownFailure = new ApiError({ status: 409, code: 'DraftOperationConflict', message: 'raw server detail' })
  let starts = 0
  const subject = coordinator({
    startOperation: async () => {
      starts += 1
      if (starts === 1) throw knownFailure
      return operation()
    },
  })
  await assert.rejects(() => subject.generateNew(command()), ApiError)
  assert.equal(subject.status, 'request_rejected')
  assert.equal(subject.failureCode, 'request_rejected')
  assert.equal(JSON.stringify({ status: subject.status, failureCode: subject.failureCode }).includes('raw server detail'), false)
  await assert.rejects(() => subject.retryUnknown(), /no unknown/i)
  assert.deepEqual(await subject.generateNew(command()), {
    workingDraft: { content: 'authoritative' },
  })
})

test('local and response-invalid failures are fixed public states, never unknown recovery', async () => {
  for (const startOperation of [
    async () => { throw new TypeError('local implementation detail') },
    async () => ({ ...operation(), prompt: 'private response' }),
  ]) {
    const subject = coordinator({ startOperation })
    await assert.rejects(() => subject.generateNew(command()), TypeError)
    assert.equal(subject.status, 'operation_invalid')
    assert.equal(subject.failureCode, 'operation_invalid')
    assert.equal(JSON.stringify({ status: subject.status, failureCode: subject.failureCode }).match(/detail|private/i), null)
    await assert.rejects(() => subject.retryUnknown(), /no unknown/i)
  }
})

test('unknown status recovery keeps its frozen command and rejects new generate actions', async () => {
  const pendingRead = deferred()
  const readStarted = deferred()
  const calls = []
  let starts = 0
  const subject = coordinator({
    startOperation: async next => {
      calls.push(next)
      starts += 1
      if (starts === 2) return operation()
      return operation({
        status: 'running',
        lastEventSequence: 1,
        resultWorkingDraftRevision: null,
        resultContentHash: null,
      })
    },
    readOperation: () => {
      readStarted.resolve()
      return pendingRead.promise
    },
    listEvents: async operationId => ({
      operationId,
      events: [{
        sequence: 2,
        type: 'completed',
        createdAt: 2,
        resultWorkingDraftRevision: 5,
        resultContentHash: textHash('authoritative'),
      }],
      lastEventSequence: 2,
      nextAfter: 2,
      hasMore: false,
    }),
  })
  const first = subject.generateNew(command())
  await readStarted.promise
  pendingRead.reject(new ApiError({
    status: 502,
    code: 'DraftOperationUnavailable',
  }))
  await assert.rejects(first, ApiError)
  await assert.rejects(() => subject.generateNew(command()), /recovery/i)
  assert.deepEqual(await subject.retryUnknown(), {
    workingDraft: { content: 'authoritative' },
  })
  assert.equal(calls.length, 2)
  assert.strictEqual(calls[1], calls[0])
})

test('completed operation reloads authoritative workspace exactly once and never exposes output text', async () => {
  let reloads = 0
  const subject = coordinator({
    startOperation: async () => operation(),
    reloadWorkspace: async () => {
      reloads += 1
      return { workingDraft: { content: 'authoritative only' } }
    },
  })
  const workspace = await subject.generateNew(command())
  assert.deepEqual(workspace, { workingDraft: { content: 'authoritative only' } })
  assert.equal(reloads, 1)
  assert.equal(Object.hasOwn(subject.operation, 'output'), false)
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
  const subject = coordinator()
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
  assert.equal(Object.isFrozen(subject.operation), true)
  assert.equal(Object.isFrozen(subject.operation.model), true)
})

test('coordinator bounds command and completed revisions without issuing unsafe starts', async () => {
  const base = 2_147_483_646
  const result = 2_147_483_647
  const calls = []
  const subject = coordinator({
    startOperation: async next => {
      calls.push(next)
      return operation({
        resultWorkingDraftRevision: result,
      })
    },
  })
  assert.equal((await subject.generateNew({
    ...command(),
    expectedWorkingDraftRevision: base,
  })).workingDraft.content, 'authoritative')
  for (const revision of [base + 1, Number.MAX_SAFE_INTEGER + 1]) {
    assert.throws(() => subject.generateNew({
      ...command(),
      expectedWorkingDraftRevision: revision,
    }), TypeError)
  }
  assert.equal(calls.length, 1)
  const invalidResult = coordinator({
    startOperation: async () => operation({
      resultWorkingDraftRevision: Number.MAX_SAFE_INTEGER + 1,
    }),
  })
  await assert.rejects(() => invalidResult.generateNew(command()), TypeError)
  assert.equal(invalidResult.status, 'operation_invalid')
})

test('late reload rejection after reset or dispose resolves null without public contamination', async () => {
  for (const invalidate of [
    subject => subject.resetContext(),
    subject => subject.dispose(),
  ]) {
    const lateReload = deferred()
    const reloadStarted = deferred()
    const subject = coordinator({
      reloadWorkspace: () => {
        reloadStarted.resolve()
        return lateReload.promise
      },
    })
    const request = subject.generateNew(command())
    await reloadStarted.promise
    invalidate(subject)
    lateReload.reject(new Error('late reload detail'))
    assert.equal(await request, null)
    assert.equal(subject.operation, null)
    assert.equal(subject.failureCode, null)
  }
})

test('scheduler synchronous and async failures become operation_invalid, while invalidated rejection is ignored', async () => {
  for (const pollScheduler of [
    () => { throw new Error('scheduler detail') },
    () => ({ promise: Promise.reject(new Error('scheduler detail')), cancel() {} }),
  ]) {
    const subject = coordinator({
      startOperation: async () => operation({
        status: 'running', lastEventSequence: 1,
        resultWorkingDraftRevision: null, resultContentHash: null,
      }),
      readOperation: async () => operation({
        status: 'running', lastEventSequence: 1,
        resultWorkingDraftRevision: null, resultContentHash: null,
      }),
      pollScheduler,
    })
    await assert.rejects(() => subject.generateNew(command()), Error)
    assert.equal(subject.status, 'operation_invalid')
    assert.equal(subject.failureCode, 'operation_invalid')
    await assert.rejects(() => subject.retryUnknown(), /no unknown/i)
  }

  const delayed = deferred()
  const subject = coordinator({
    startOperation: async () => operation({
      status: 'running', lastEventSequence: 1,
      resultWorkingDraftRevision: null, resultContentHash: null,
    }),
    readOperation: async () => operation({
      status: 'running', lastEventSequence: 1,
      resultWorkingDraftRevision: null, resultContentHash: null,
    }),
    pollScheduler: () => ({
      promise: delayed.promise,
      cancel() { delayed.reject(new Error('cancelled scheduler detail')) },
    }),
  })
  const request = subject.generateNew(command())
  await Promise.resolve()
  await Promise.resolve()
  subject.resetContext()
  assert.equal(await request, null)
  assert.equal(subject.status, 'idle')
})

test('dispose is idempotent and resetContext cannot revive a disposed coordinator', () => {
  const subject = coordinator()
  subject.dispose()
  subject.resetContext()
  assert.equal(subject.status, 'disposed')
  subject.dispose()
  assert.equal(subject.status, 'disposed')
  assert.throws(() => subject.generateNew(command()), /disposed/i)
})

test('default polling uses one-second timers, cancellation clears them, and bounded recovery retains retry state', async () => {
  const originalSetTimeout = global.setTimeout
  const originalClearTimeout = global.clearTimeout
  const timers = []
  const cleared = []
  global.setTimeout = (callback, delayMs) => {
    const timer = { callback, delayMs }
    timers.push(timer)
    return timer
  }
  global.clearTimeout = timer => { cleared.push(timer) }
  try {
    for (const invalidate of [
      subject => subject.resetContext(),
      subject => subject.dispose(),
    ]) {
      let reads = 0
      const subject = createDraftOperationCoordinator({
        startOperation: async () => operation({
          status: 'running', lastEventSequence: 1,
          resultWorkingDraftRevision: null, resultContentHash: null,
        }),
        readOperation: async () => {
          reads += 1
          return operation({
            status: 'running', lastEventSequence: 1,
            resultWorkingDraftRevision: null, resultContentHash: null,
          })
        },
        listEvents: async (operationId, after) => ({
          operationId,
          events: [],
          lastEventSequence: after,
          nextAfter: after,
          hasMore: false,
        }),
        cancelOperation: async () => operation({
          status: 'cancelled',
          partialOutput: '',
          resultWorkingDraftRevision: null,
          resultContentHash: null,
        }),
        reloadWorkspace: async () => ({}),
        idFactory: () => KEY,
      })
      const timerCount = timers.length
      const request = subject.generateNew(command())
      while (timers.length === timerCount) {
        await new Promise(resolve => setImmediate(resolve))
      }
      const timer = timers.at(-1)
      assert.equal(reads, 1)
      assert.equal(timer.delayMs, 1_000)
      invalidate(subject)
      assert.equal(await request, null)
      assert.equal(cleared.at(-1), timer)
      assert.equal(reads, 1)
    }
  } finally {
    global.setTimeout = originalSetTimeout
    global.clearTimeout = originalClearTimeout
  }

  let reads = 0
  let delays = 0
  const exhausted = coordinator({
    startOperation: async () => operation({
      status: 'running', lastEventSequence: 1,
      resultWorkingDraftRevision: null, resultContentHash: null,
    }),
    readOperation: async () => {
      reads += 1
      return operation({
        status: 'running', lastEventSequence: 1,
        resultWorkingDraftRevision: null, resultContentHash: null,
      })
    },
    pollScheduler: () => {
      delays += 1
      return { promise: Promise.resolve(), cancel() {} }
    },
  })
  assert.equal(await exhausted.generateNew(command()), null)
  assert.equal(reads, 1_200)
  assert.equal(delays, 1_199)
  assert.equal(exhausted.status, 'unknown')
  assert.equal(exhausted.failureCode, 'request_unknown')
  await assert.rejects(() => exhausted.generateNew(command()), /recovery/i)
})

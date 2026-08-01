import assert from 'node:assert/strict'
import test from 'node:test'

import { createDraftOperationCoordinator } from '../../src/application/writer/draftOperationCoordinator.js'
import { ApiError } from '../../src/api/db/api-error.js'

const PROJECT_ID = '11111111-1111-4111-8111-111111111111'
const SESSION_ID = '22222222-2222-4222-8222-222222222222'
const OPERATION_ID = '33333333-3333-4333-8333-333333333333'
const KEY = '44444444-4444-4444-8444-444444444444'
const HASH = 'a'.repeat(64)

function operation(overrides = {}) {
  return {
    id: OPERATION_ID,
    projectId: PROJECT_ID,
    chapterSessionId: SESSION_ID,
    operationType: 'generate_new',
    status: 'completed',
    lastEventSequence: 2,
    resultWorkingDraftRevision: 5,
    resultContentHash: HASH,
    failureCode: null,
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
        promise: delay.promise,
        cancel() {
          cancelled += 1
          delay.resolve()
        },
      }),
    })
    await assert.rejects(() => subject.generateNew(command()), ApiError)
    const recovery = subject.retryUnknown()
    await Promise.resolve()
    await Promise.resolve()
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
        : operation()
    },
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
    await Promise.resolve()
    await Promise.resolve()
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
    readOperation: () => pendingRead.promise,
  })
  const first = subject.generateNew(command())
  await Promise.resolve()
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
    const subject = coordinator({ reloadWorkspace: () => lateReload.promise })
    const request = subject.generateNew(command())
    await Promise.resolve()
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
        reloadWorkspace: async () => ({}),
        idFactory: () => KEY,
      })
      const request = subject.generateNew(command())
      await Promise.resolve()
      await Promise.resolve()
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

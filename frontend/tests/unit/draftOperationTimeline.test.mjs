import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'

import { createDraftOperationTimeline } from '../../src/application/writer/draftOperationTimeline.js'

const OPERATION_ID = '33333333-3333-4333-8333-333333333333'

function hashText(value) {
  return Promise.resolve(createHash('sha256').update(value, 'utf8').digest('hex'))
}

function operation({
  text = '',
  sequence = 1,
  status = 'running',
  operationType = 'generate_new',
  resultSelectionStart = null,
  resultSelectionEnd = null,
  resultWorkingDraftRevision,
  resultContentHash,
  failureCode,
} = {}) {
  const result = status === 'completed' || (status === 'cancelled' && text)
  return {
    id: OPERATION_ID,
    operationType,
    status,
    partialOutput: text,
    partialOutputHash: createHash('sha256').update(text, 'utf8').digest('hex'),
    partialOutputScalars: Array.from(text).length,
    lastEventSequence: sequence,
    resultWorkingDraftRevision: resultWorkingDraftRevision ?? (result ? 2 : null),
    resultContentHash: resultContentHash ?? (result
      ? createHash('sha256').update(text, 'utf8').digest('hex')
      : null),
    resultSelectionStart,
    resultSelectionEnd,
    failureCode: failureCode ?? (status === 'failed' ? 'DraftProviderFailed' : null),
  }
}

test('timeline exposes a separate local replacement preview and terminal range', async () => {
  const timeline = createDraftOperationTimeline({ hashText })
  await timeline.calibrate(operation({
    text: ' 新😀 ',
    sequence: 2,
    status: 'completed',
    operationType: 'rewrite_selection',
    resultContentHash: 'a'.repeat(64),
    resultSelectionStart: 3,
    resultSelectionEnd: 7,
  }))

  assert.equal(timeline.preview, ' 新😀 ')
  assert.equal(timeline.previewKind, 'replacement')
  assert.equal(timeline.operationType, 'rewrite_selection')
  assert.deepEqual(timeline.resultSelection, { startOffset: 3, endOffset: 7 })
})

function page(events, { lastEventSequence, hasMore = false } = {}) {
  const nextAfter = events.length ? events.at(-1).sequence : 0
  return {
    operationId: OPERATION_ID,
    events,
    lastEventSequence: lastEventSequence ?? nextAfter,
    nextAfter,
    hasMore,
  }
}

function delta(sequence, text, cumulative) {
  return {
    sequence,
    type: 'delta',
    createdAt: sequence,
    text,
    partialOutputHash: createHash('sha256').update(cumulative, 'utf8').digest('hex'),
    partialOutputScalars: Array.from(cumulative).length,
  }
}

test('timeline calibrates a fresh authoritative snapshot without replay then applies retained suffixes', async () => {
  const timeline = createDraftOperationTimeline({ hashText })
  await timeline.calibrate(operation({ text: '甲', sequence: 8 }))
  assert.equal(timeline.preview, '甲')
  assert.equal(timeline.cursor, 8)

  await timeline.applyPage(page([
    delta(9, '乙', '甲乙'),
  ], { lastEventSequence: 9 }))
  assert.equal(timeline.preview, '甲乙')
  assert.equal(timeline.cursor, 9)
})

test('timeline drains consecutive pages and keeps heartbeat and terminal events text-neutral', async () => {
  const timeline = createDraftOperationTimeline({ hashText })
  await timeline.calibrate(operation({ text: '', sequence: 1 }))
  await timeline.applyPage(page([
    delta(2, '甲', '甲'),
    { sequence: 3, type: 'heartbeat', createdAt: 3 },
  ], { lastEventSequence: 5, hasMore: true }))
  await timeline.applyPage(page([
    delta(4, '😀', '甲😀'),
    {
      sequence: 5,
      type: 'completed',
      createdAt: 5,
      resultWorkingDraftRevision: 2,
      resultContentHash: createHash('sha256').update('甲😀', 'utf8').digest('hex'),
    },
  ], { lastEventSequence: 5 }))
  assert.equal(timeline.preview, '甲😀')
  assert.equal(timeline.cursor, 5)
})

test('timeline atomically calibrates a completed same-cursor snapshot after raw streamed whitespace', async () => {
  const timeline = createDraftOperationTimeline({ hashText })
  await timeline.calibrate(operation({ text: '', sequence: 1 }))
  await timeline.applyPage(page([
    delta(2, ' 甲 ', ' 甲 '),
    {
      sequence: 3,
      type: 'completed',
      createdAt: 3,
      resultWorkingDraftRevision: 2,
      resultContentHash: createHash('sha256').update('甲', 'utf8').digest('hex'),
    },
  ], { lastEventSequence: 3 }))
  await timeline.calibrate(operation({ text: '甲', sequence: 3, status: 'completed' }))
  assert.equal(timeline.preview, '甲')
  assert.equal(timeline.cursor, 3)
})

test('timeline binds same-cursor statuses to terminal event evidence and fences later events', async () => {
  const timeline = createDraftOperationTimeline({ hashText })
  await timeline.calibrate(operation({ text: '', sequence: 1 }))
  await timeline.applyPage(page([{
    sequence: 2,
    type: 'completed',
    createdAt: 2,
    resultWorkingDraftRevision: 2,
    resultContentHash: createHash('sha256').update('', 'utf8').digest('hex'),
  }], { lastEventSequence: 2 }))
  await timeline.calibrate(operation({ text: '', sequence: 2, status: 'completed' }))
  for (const status of ['cancelled', 'failed', 'starting', 'running', 'expired']) {
    await assert.rejects(
      timeline.calibrate(operation({ text: '', sequence: 2, status })),
      TypeError,
    )
  }
  await assert.rejects(
    timeline.applyPage(page([{
      sequence: 3,
      type: 'heartbeat',
      createdAt: 3,
    }], { lastEventSequence: 3 })),
    TypeError,
  )

  const bootstrap = createDraftOperationTimeline({ hashText })
  await bootstrap.calibrate(operation({ text: '甲', sequence: 2, status: 'cancelled' }))
  assert.equal(bootstrap.preview, '甲')
})

test('timeline binds terminal scalars and seals terminal bootstrap snapshots', async () => {
  for (const [status, event, mismatch] of [
    ['completed', {
      sequence: 2,
      type: 'completed',
      createdAt: 2,
      resultWorkingDraftRevision: 2,
      resultContentHash: createHash('sha256').update('甲', 'utf8').digest('hex'),
    }, operation({ text: '甲', sequence: 2, status: 'completed', resultWorkingDraftRevision: 3 })],
    ['cancelled', {
      sequence: 2,
      type: 'cancelled',
      createdAt: 2,
      resultWorkingDraftRevision: 2,
      resultContentHash: createHash('sha256').update('甲', 'utf8').digest('hex'),
    }, operation({
      text: '甲',
      sequence: 2,
      status: 'cancelled',
      resultContentHash: createHash('sha256').update('乙', 'utf8').digest('hex'),
    })],
    ['failed', {
      sequence: 2,
      type: 'failed',
      createdAt: 2,
      failureCode: 'DraftProviderFailed',
    }, operation({ sequence: 2, status: 'failed', failureCode: 'DraftProviderResultInvalid' })],
  ]) {
    const timeline = createDraftOperationTimeline({ hashText })
    await timeline.calibrate(operation({ text: '甲', sequence: 1 }))
    await timeline.applyPage(page([event], { lastEventSequence: 2 }))
    await assert.rejects(timeline.calibrate(mismatch), TypeError, status)
  }

  for (const event of [
    { sequence: 3, type: 'heartbeat', createdAt: 3 },
    delta(3, '乙', '甲乙'),
    {
      sequence: 3,
      type: 'completed',
      createdAt: 3,
      resultWorkingDraftRevision: 3,
      resultContentHash: createHash('sha256').update('甲', 'utf8').digest('hex'),
    },
  ]) {
    const timeline = createDraftOperationTimeline({ hashText })
    await timeline.calibrate(operation({ text: '甲', sequence: 2, status: 'completed' }))
    await assert.rejects(timeline.applyPage(page([event], { lastEventSequence: 3 })), TypeError)
    assert.equal(timeline.preview, '甲')
    assert.equal(timeline.cursor, 2)
  }

  const emptyAhead = createDraftOperationTimeline({ hashText })
  await emptyAhead.calibrate(operation({ text: '甲', sequence: 2, status: 'completed' }))
  await assert.rejects(emptyAhead.applyPage({
    operationId: OPERATION_ID,
    events: [],
    lastEventSequence: 3,
    nextAfter: 2,
    hasMore: true,
  }), TypeError)
  assert.equal(emptyAhead.preview, '甲')
  assert.equal(emptyAhead.cursor, 2)
})

test('timeline seals a same-cursor expired snapshot after retained events', async () => {
  const timeline = createDraftOperationTimeline({ hashText })
  await timeline.calibrate(operation({ text: '', sequence: 1, status: 'running' }))
  await timeline.applyPage(page([
    delta(2, '甲', '甲'),
    { sequence: 3, type: 'heartbeat', createdAt: 3 },
  ], { lastEventSequence: 3 }))
  await timeline.calibrate(operation({ text: '甲', sequence: 3, status: 'expired' }))

  await assert.rejects(timeline.applyPage(page([
    { sequence: 4, type: 'heartbeat', createdAt: 4 },
  ], { lastEventSequence: 4 })), TypeError)
  await assert.rejects(timeline.applyPage({
    operationId: OPERATION_ID,
    events: [],
    lastEventSequence: 4,
    nextAfter: 3,
    hasMore: true,
  }), TypeError)
  assert.equal(timeline.preview, '甲')
  assert.equal(timeline.cursor, 3)
})

test('timeline requires a recognized status and keeps same-cursor non-normalizing snapshots closed', async () => {
  const invalidStatus = createDraftOperationTimeline({ hashText })
  await assert.rejects(
    invalidStatus.calibrate(operation({ status: 'unknown' })),
    TypeError,
  )

  for (const status of ['starting', 'running', 'failed', 'expired']) {
    const timeline = createDraftOperationTimeline({ hashText })
    await timeline.calibrate(operation({ text: '原始', sequence: 3 }))
    await assert.rejects(
      timeline.calibrate(operation({ text: '不一致', sequence: 3, status })),
      TypeError,
    )
    assert.equal(timeline.preview, '原始')
    assert.equal(timeline.cursor, 3)
  }
})

test('timeline rejects gaps, scalar drift, and hash drift atomically', async () => {
  for (const invalidEvent of [
    delta(3, '乙', '甲乙'),
    { ...delta(2, '乙', '甲乙'), partialOutputScalars: 3 },
    { ...delta(2, '乙', '甲乙'), partialOutputHash: 'a'.repeat(64) },
  ]) {
    const timeline = createDraftOperationTimeline({ hashText })
    await timeline.calibrate(operation({ text: '甲', sequence: 1 }))
    await assert.rejects(
      timeline.applyPage(page([invalidEvent], { lastEventSequence: invalidEvent.sequence })),
      TypeError,
    )
    assert.equal(timeline.preview, '甲')
    assert.equal(timeline.cursor, 1)
  }
})

test('timeline permits bootstrap only and rejects every non-current snapshot atomically', async () => {
  for (const status of [
    'starting', 'running', 'completed', 'failed', 'cancelled', 'expired',
  ]) {
    const timeline = createDraftOperationTimeline({ hashText })
    await timeline.calibrate(operation({ text: '甲乙', sequence: 8 }))
    await assert.rejects(
      timeline.calibrate(operation({ text: '甲', sequence: 7, status })),
      TypeError,
    )
    await assert.rejects(
      timeline.calibrate(operation({ text: '甲乙丙', sequence: 9, status })),
      TypeError,
    )
    assert.equal(timeline.preview, '甲乙')
    assert.equal(timeline.cursor, 8)
  }
})

test('timeline reset fences a pending asynchronous calibration and rejects events beyond the page snapshot', async () => {
  let releaseHash
  const hashGate = new Promise(resolve => { releaseHash = resolve })
  const timeline = createDraftOperationTimeline({
    hashText: async () => hashGate,
  })
  const pending = timeline.calibrate(operation({ text: '甲', sequence: 1 }))
  timeline.reset()
  releaseHash(createHash('sha256').update('甲', 'utf8').digest('hex'))
  assert.equal(await pending, false)
  assert.equal(timeline.preview, '')
  assert.equal(timeline.cursor, 0)

  const bounded = createDraftOperationTimeline({ hashText })
  await bounded.calibrate(operation({ text: '', sequence: 1 }))
  await assert.rejects(
    bounded.applyPage(page([
      delta(2, '甲', '甲'),
    ], { lastEventSequence: 1 })),
    TypeError,
  )
  assert.equal(bounded.preview, '')
  assert.equal(bounded.cursor, 1)
})

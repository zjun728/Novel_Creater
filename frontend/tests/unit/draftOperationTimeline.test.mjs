import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import test from 'node:test'

import { createDraftOperationTimeline } from '../../src/application/writer/draftOperationTimeline.js'

const OPERATION_ID = '33333333-3333-4333-8333-333333333333'

function hashText(value) {
  return Promise.resolve(createHash('sha256').update(value, 'utf8').digest('hex'))
}

function operation({ text = '', sequence = 1 } = {}) {
  return {
    id: OPERATION_ID,
    partialOutput: text,
    partialOutputHash: createHash('sha256').update(text, 'utf8').digest('hex'),
    partialOutputScalars: Array.from(text).length,
    lastEventSequence: sequence,
  }
}

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

test('timeline recalibrates when its retained cursor is ahead of the authoritative status snapshot', async () => {
  const timeline = createDraftOperationTimeline({ hashText })
  await timeline.calibrate(operation({ text: '甲乙', sequence: 8 }))
  await timeline.calibrate(operation({ text: '甲', sequence: 7 }))
  assert.equal(timeline.preview, '甲')
  assert.equal(timeline.cursor, 7)
  timeline.reset()
  assert.equal(timeline.preview, '')
  assert.equal(timeline.cursor, 0)
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
  await pending
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

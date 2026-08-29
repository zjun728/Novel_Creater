import assert from 'node:assert/strict'
import test from 'node:test'

import { presentActualProgress } from '../../src/application/planning/actualProgressPresentation.js'

const safeStatus = (overrides = {}) => ({
  synchronized: true,
  canonRevision: 4,
  projectionRevision: 4,
  ...overrides,
})

const content = (overrides = {}) => ({
  storyBlocks: [{
    id: 'block-1',
    title: '  初入江湖  ',
    stages: [{
      id: 'stage-1',
      title: '  初试锋芒  ',
      sceneTasks: [{ id: 'task-1', task: '  救下故人  ' }],
    }],
  }],
  ...overrides,
})

const entry = ({
  chapterNumber = 3,
  targetType = 'story_block',
  targetId = 'block-1',
  progressStatus = 'started',
  entityId = null,
  subjectKey = '__global__',
  fieldPath = `plot.progress.${targetType}.${targetId}`,
  value,
} = {}) => ({
  entityId,
  subjectKey,
  fieldPath,
  value: value === undefined ? { chapterNumber, status: progressStatus, targetId, targetType } : value,
})

function present({ items = [], status = safeStatus(), planningContent = content() } = {}) {
  return presentActualProgress({ items, status, planningContent })
}

function expectMessage(options, state, message) {
  const model = present(options)
  assert.equal(model.state, state)
  assert.equal(model.heading, '正文进度')
  assert.equal(model.message, message)
  assert.deepEqual(model.rows, [])
  return model
}

function assertDeepFrozen(value, seen = new Set()) {
  if (value === null || typeof value !== 'object' || seen.has(value)) return
  seen.add(value)
  assert.equal(Object.isFrozen(value), true)
  for (const child of Object.values(value)) assertDeepFrozen(child, seen)
}

test('maps every recognized kind and progress status to author-facing labels', () => {
  const items = [
    entry({ chapterNumber: 6, targetType: 'story_block', progressStatus: 'started' }),
    entry({ chapterNumber: 5, targetType: 'stage', targetId: 'stage-1', progressStatus: 'advanced' }),
    entry({ chapterNumber: 4, targetType: 'scene_task', targetId: 'task-1', progressStatus: 'completed' }),
  ]

  const model = present({ items })

  assert.equal(model.state, 'recognized')
  assert.equal(model.message, '已同步 3 章定稿带来的规划进度。')
  assert.deepEqual(model.rows, [
    { key: 'progress-row-1', chapterLabel: '第6章', kindLabel: '故事块', hierarchyLabel: '初入江湖', statusLabel: '已开始' },
    { key: 'progress-row-2', chapterLabel: '第5章', kindLabel: '阶段', hierarchyLabel: '初入江湖 / 初试锋芒', statusLabel: '已推进' },
    { key: 'progress-row-3', chapterLabel: '第4章', kindLabel: '场景任务', hierarchyLabel: '初入江湖 / 初试锋芒 / 救下故人', statusLabel: '已完成' },
  ])
})

test('covers every kind by status label combination', () => {
  const combinations = [
    ['story_block', 'started', '故事块', '已开始', 'block-1'],
    ['story_block', 'advanced', '故事块', '已推进', 'block-1'],
    ['story_block', 'completed', '故事块', '已完成', 'block-1'],
    ['stage', 'started', '阶段', '已开始', 'stage-1'],
    ['stage', 'advanced', '阶段', '已推进', 'stage-1'],
    ['stage', 'completed', '阶段', '已完成', 'stage-1'],
    ['scene_task', 'started', '场景任务', '已开始', 'task-1'],
    ['scene_task', 'advanced', '场景任务', '已推进', 'task-1'],
    ['scene_task', 'completed', '场景任务', '已完成', 'task-1'],
  ]
  const model = present({ items: combinations.map(([targetType, progressStatus, , , targetId], index) => entry({
    chapterNumber: index + 1,
    targetType,
    progressStatus,
    targetId,
  })) })
  assert.deepEqual(
    model.rows.map(row => [row.kindLabel, row.statusLabel]),
    combinations.slice().reverse().map(([, , kindLabel, statusLabel]) => [kindLabel, statusLabel]),
  )
})

test('returns each status envelope presentation state with the fixed Chinese message', () => {
  expectMessage({ status: safeStatus({ synchronized: false, canonRevision: 5, projectionRevision: 4 }) }, 'syncing', '正文进度正在同步，稍后重新读取。')
  expectMessage({ status: safeStatus({ canonRevision: 0, projectionRevision: 0 }), items: [entry()] }, 'no-canon', '尚无已定稿正文带来的规划进度。')
  expectMessage({ items: [] }, 'empty', '定稿事实已同步，当前没有规划项发生变化。')
  const unrecognized = expectMessage({ items: [entry({ targetId: 'unknown' })] }, 'unrecognized', '定稿进度已同步，暂时无法生成作者摘要。共有 1 项暂不能展示。')
  assert.equal(unrecognized.unrecognizedCount, 1)
})

test('rejects invalid envelopes including synchronized equality in both directions', () => {
  for (const status of [
    null,
    {},
    safeStatus({ synchronized: true, canonRevision: 5, projectionRevision: 4 }),
    safeStatus({ synchronized: false, canonRevision: 4, projectionRevision: 4 }),
    safeStatus({ canonRevision: -1 }),
    safeStatus({ projectionRevision: 1.5 }),
    safeStatus({ canonRevision: Number.MAX_SAFE_INTEGER + 1 }),
    safeStatus({ synchronized: 'true' }),
  ]) {
    expectMessage({ status, items: [entry()] }, 'invalid', '正文进度状态需要重新读取。')
  }
})

test('treats malformed item containers and throwing status access as safe empty or invalid models', () => {
  for (const items of [null, {}, 'not-an-array']) {
    expectMessage({ items }, 'empty', '定稿事实已同步，当前没有规划项发生变化。')
  }
  const hostileStatus = {}
  Object.defineProperty(hostileStatus, 'canonRevision', { enumerable: true, get() { throw new Error('secret status') } })
  expectMessage({ status: hostileStatus, items: [entry()] }, 'invalid', '正文进度状态需要重新读取。')
})

test('fail-closes malformed entries and value shapes without throwing', () => {
  const inheritedValue = Object.create({ chapterNumber: 3 })
  Object.assign(inheritedValue, { status: 'started', targetId: 'block-1', targetType: 'story_block' })
  const hiddenRequired = { status: 'started', targetId: 'block-1', targetType: 'story_block' }
  Object.defineProperty(hiddenRequired, 'chapterNumber', { value: 3, enumerable: false })
  const throwingEntry = {}
  Object.defineProperty(throwingEntry, 'value', { get() { throw new Error('hidden entry secret') } })
  const throwingProxy = new Proxy({}, { getOwnPropertyDescriptor() { throw new Error('proxy secret') } })
  const badValues = [
    null, [], 'value', 3,
    { chapterNumber: 3, status: 'started', targetId: 'block-1', targetType: 'story_block', extra: true },
    inheritedValue, hiddenRequired,
    { chapterNumber: 0, status: 'started', targetId: 'block-1', targetType: 'story_block' },
    { chapterNumber: Number.MAX_SAFE_INTEGER + 1, status: 'started', targetId: 'block-1', targetType: 'story_block' },
    { chapterNumber: 3, status: 'wrong', targetId: 'block-1', targetType: 'story_block' },
    { chapterNumber: 3, status: 'started', targetId: '', targetType: 'story_block' },
    { chapterNumber: 3, status: 'started', targetId: 'block-1', targetType: 'volume' },
  ]
  const model = present({ items: [null, [], 2, throwingEntry, throwingProxy, ...badValues.map(value => entry({ value }))] })

  assert.equal(model.state, 'unrecognized')
  assert.equal(model.unrecognizedCount, 17)
  assert.deepEqual(model.rows, [])
})

test('requires exact canonical target path and global entity scope', () => {
  const invalid = [
    entry({ fieldPath: 'plot.progress.stage.stage-1', targetType: 'story_block' }),
    entry({ fieldPath: 'volume.progress.story_block.block-1' }),
    entry({ fieldPath: 'plot.progress.story_block.block-1.trailing' }),
    entry({ entityId: 'entity-1' }),
    entry({ subjectKey: 'chapter-3' }),
    entry({ targetId: 'missing' }),
  ]
  const model = present({ items: invalid })
  assert.equal(model.state, 'unrecognized')
  assert.equal(model.unrecognizedCount, invalid.length)
})

test('uses only server ids for hierarchy and rejects malformed planning content safely', () => {
  const localOnly = content({ storyBlocks: [{ clientNodeKey: 'block-1', title: '不能匹配', stages: [] }] })
  assert.equal(present({ planningContent: localOnly, items: [entry()] }).state, 'unrecognized')
  for (const planningContent of [null, [], {}, { storyBlocks: {} }, new Proxy({}, { get() { throw new Error('hierarchy secret') } })]) {
    const model = present({ planningContent, items: [entry()] })
    assert.equal(model.state, 'unrecognized')
    assert.equal(model.unrecognizedCount, 1)
  }
  const malformedNestedCollection = content({
    storyBlocks: [{ id: 'block-1', title: '有效块', stages: {} }],
  })
  assert.equal(present({ planningContent: malformedNestedCollection, items: [entry()] }).state, 'unrecognized')
  const throwingTitle = { id: 'block-1', stages: [] }
  Object.defineProperty(throwingTitle, 'title', { get() { throw new Error('hierarchy title secret') } })
  assert.equal(present({ planningContent: content({ storyBlocks: [throwingTitle] }), items: [entry()] }).state, 'unrecognized')
})

test('falls back to the fixed author label when hierarchy titles are blank or non-strings', () => {
  const planningContent = content({
    storyBlocks: [{ id: 'block-1', title: '   ', stages: [{
      id: 'stage-1', title: 2, sceneTasks: [{ id: 'task-1', task: '' }],
    }] }],
  })
  const model = present({ planningContent, items: [entry({ targetType: 'scene_task', targetId: 'task-1' })] })
  assert.equal(model.rows[0].hierarchyLabel, '当前规划项 / 当前规划项 / 当前规划项')
})

test('keeps duplicate author labels separate but deduplicates only exact internal identity', () => {
  const planningContent = content({
    storyBlocks: [
      { id: 'block-1', title: '同名', stages: [] },
      { id: 'block-2', title: '同名', stages: [] },
    ],
  })
  const a = entry({ chapterNumber: 3, targetId: 'block-1' })
  const duplicate = entry({ chapterNumber: 3, targetId: 'block-1' })
  const b = entry({ chapterNumber: 3, targetId: 'block-2' })
  const model = present({ items: [a, duplicate, b], planningContent })
  assert.equal(model.rows.length, 2)
  assert.deepEqual(model.rows.map(row => row.hierarchyLabel), ['同名', '同名'])
})

test('avoids delimiter collisions when deduplicating internal identities', () => {
  const planningContent = content({ storyBlocks: [
    { id: 'a|b', title: '一', stages: [] },
    { id: 'b', title: '二', stages: [] },
  ] })
  const one = entry({ chapterNumber: 1, targetId: 'a|b', progressStatus: 'started' })
  const two = entry({ chapterNumber: 1, targetId: 'b', progressStatus: 'started', targetType: 'story_block' })
  const model = present({ items: [one, two], planningContent })
  assert.equal(model.rows.length, 2)
})

test('sorts chapters descending, preserves same-chapter input order, and has deterministic explicit reordering', () => {
  const items = [
    entry({ chapterNumber: 2, targetType: 'scene_task', targetId: 'task-1' }),
    entry({ chapterNumber: 3, targetType: 'stage', targetId: 'stage-1' }),
    entry({ chapterNumber: 3, targetType: 'story_block', targetId: 'block-1', progressStatus: 'advanced' }),
  ]
  const model = present({ items })
  assert.deepEqual(model.rows.map(row => row.kindLabel), ['阶段', '故事块', '场景任务'])
  const reordered = present({ items: [items[2], items[1], items[0]] })
  assert.deepEqual(reordered.rows.map(row => row.kindLabel), ['故事块', '阶段', '场景任务'])
})

test('limits rows to ten and counts all distinct recognized chapters before truncation', () => {
  const items = Array.from({ length: 12 }, (_, index) => entry({
    chapterNumber: index + 1,
    progressStatus: ['started', 'advanced', 'completed'][index % 3],
  }))
  const model = present({ items })
  assert.equal(model.rows.length, 10)
  assert.deepEqual(model.rows.map(row => row.chapterLabel), ['第12章', '第11章', '第10章', '第9章', '第8章', '第7章', '第6章', '第5章', '第4章', '第3章'])
  assert.equal(model.omittedRecognizedCount, 2)
  assert.equal(model.message, '已同步 12 章定稿带来的规划进度。')
})

test('reports mixed rows and unrecognized entries independently', () => {
  const model = present({ items: [entry(), entry({ targetId: 'missing' })] })
  assert.equal(model.state, 'recognized')
  assert.equal(model.rows.length, 1)
  assert.equal(model.unrecognizedCount, 1)
  assert.equal(model.omittedRecognizedCount, 0)
})

test('never leaks canonical transport fields or hostile nested values and recursively freezes the display model', () => {
  const hostile = 'uuid-7c9c1d10-ea3d-4bd3-a68f-transport-hash-path-subject'
  const model = present({ items: [entry({
    value: { chapterNumber: 7, status: 'completed', targetId: 'block-1', targetType: 'story_block' },
    fieldPath: `plot.progress.story_block.block-1.${hostile}`,
  }), entry({
    entityId: `${hostile}-entity`,
    subjectKey: `${hostile}-subject`,
    fieldPath: `plot.progress.story_block.block-1/${hostile}.json`,
    value: { chapterNumber: 99, status: 'started', targetId: 'block-1', targetType: 'story_block', nested: { hash: hostile } },
  }), entry()] })
  const output = JSON.stringify(model)
  assert.equal(output.includes(hostile), false)
  assert.equal(output.includes('targetId'), false)
  assert.equal(output.includes('fieldPath'), false)
  assertDeepFrozen(model)
  assert.throws(() => { model.rows.push({}) }, TypeError)
})

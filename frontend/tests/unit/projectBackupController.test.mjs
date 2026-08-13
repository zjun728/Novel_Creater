import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { createProjectBackupController } from '../../src/application/project/projectBackupController.js'
import { createOperationStore } from '../../src/stores/operationStore.js'

const PHASES = [
  '正在核对项目状态',
  '正在建立一致快照',
  '正在写入备份包',
  '正在准备下载',
]

function deferred() {
  let resolve
  let reject
  const promise = new Promise((nextResolve, nextReject) => { resolve = nextResolve; reject = nextReject })
  return { promise, resolve, reject }
}

function harness(overrides = {}) {
  const events = []
  const operations = []
  const saved = []
  const revoked = []
  const requests = []
  const api = overrides.api || {
    projectBackups: {
      create: async (projectId, revision, options) => {
        events.push('request')
        requests.push({ projectId, revision, options })
        return {
          blob: new Blob(['backup']),
          contentDisposition: 'attachment; filename="project.zip"',
          packageSha256: 'a'.repeat(64),
        }
      },
    },
  }
  const controller = createProjectBackupController({
    api,
    operationStore: {
      start: value => { operations.push(['start', value]); return 'op-1' },
      update: (id, value) => operations.push(['update', id, value]),
      finish: id => operations.push(['finish', id]),
    },
    flushCurrentDraft: async () => { events.push('flush'); return true },
    createObjectURL: blob => {
      assert.ok(blob instanceof Blob)
      events.push('create-url')
      return 'blob:backup'
    },
    revokeObjectURL: url => { events.push('revoke'); revoked.push(url) },
    saveBlob: (url, filename) => { events.push('save'); saved.push([url, filename]) },
    ...overrides,
  })
  return { controller, api, events, operations, saved, revoked, requests }
}

test('active backup flushes first, uses the exact revision, and publishes only four fixed phases', async () => {
  const item = harness()
  assert.equal(await item.controller.backup('project/1', 7), true)
  assert.deepEqual(item.events, ['flush', 'request', 'create-url', 'save', 'revoke'])
  assert.equal(item.requests.length, 1)
  assert.deepEqual(
    { projectId: item.requests[0].projectId, revision: item.requests[0].revision },
    { projectId: 'project/1', revision: 7 },
  )
  assert.equal(typeof item.requests[0].options.signal, 'object')
  assert.deepEqual(item.operations, [
    ['start', { label: PHASES[0], detail: '', blocking: true }],
    ['update', 'op-1', { label: PHASES[1], detail: '' }],
    ['update', 'op-1', { label: PHASES[2], detail: '' }],
    ['update', 'op-1', { label: PHASES[3], detail: '' }],
    ['finish', 'op-1'],
  ])
  assert.deepEqual(item.saved, [['blob:backup', 'project.zip']])
  assert.deepEqual(item.revoked, ['blob:backup'])
  assert.equal(item.controller.busy.value, false)
  assert.equal(item.controller.error.value, '')
})

test('false and rejected active flushes expose one fixed error and send zero requests', async () => {
  const falseFlush = harness({ flushCurrentDraft: async () => false })
  assert.equal(await falseFlush.controller.backup('p', 1), false)
  assert.equal(falseFlush.controller.error.value, '保存当前正文失败，未创建备份。')
  assert.equal(falseFlush.requests.length, 0)
  assert.deepEqual(falseFlush.operations, [])

  const failure = new Error('private draft path')
  const rejectedFlush = harness({ flushCurrentDraft: async () => { throw failure } })
  await assert.rejects(() => rejectedFlush.controller.backup('p', 1), value => value === failure)
  assert.equal(rejectedFlush.controller.error.value, '保存当前正文失败，未创建备份。')
  assert.equal(rejectedFlush.requests.length, 0)
  assert.deepEqual(rejectedFlush.operations, [])
})

test('archived backup skips the draft flush and uses the zip fallback filename', async () => {
  let flushes = 0
  const item = harness({
    flushCurrentDraft: async () => { flushes += 1; return false },
    api: { projectBackups: { create: async (projectId, revision, options) => {
      item.requests.push({ projectId, revision, options })
      return { blob: new Blob(['backup']), contentDisposition: null, packageSha256: 'b'.repeat(64) }
    } } },
  })
  assert.equal(await item.controller.backup('archived/1', 11, { archived: true }), true)
  assert.equal(flushes, 0)
  assert.deepEqual(item.saved, [['blob:backup', 'project-backup.zip']])
  assert.equal(item.requests[0].revision, 11)
})

test('backup is single-flight even while the active draft flush is pending', async () => {
  const pending = deferred()
  let requests = 0
  const item = harness({
    flushCurrentDraft: () => pending.promise,
    api: { projectBackups: { create: async () => {
      requests += 1
      return { blob: new Blob(['backup']), contentDisposition: null }
    } } },
  })
  const first = item.controller.backup('p', 4)
  assert.equal(item.controller.busy.value, true)
  assert.equal(await item.controller.backup('p', 4), false)
  pending.resolve(true)
  assert.equal(await first, true)
  assert.equal(requests, 1)
})

test('create and save failures use a fixed public error while cleanup remains complete', async () => {
  const createFailure = harness({
    createObjectURL: () => { throw new Error('private create detail') },
  })
  await assert.rejects(() => createFailure.controller.backup('p', 1))
  assert.equal(createFailure.controller.error.value, '创建项目备份失败，请重试。')
  assert.deepEqual(createFailure.revoked, [])
  assert.deepEqual(createFailure.operations.at(-1), ['finish', 'op-1'])
  assert.equal(createFailure.controller.busy.value, false)

  const saveFailure = harness({
    saveBlob: () => { throw new Error('private save detail') },
  })
  await assert.rejects(() => saveFailure.controller.backup('p', 1))
  assert.equal(saveFailure.controller.error.value, '创建项目备份失败，请重试。')
  assert.deepEqual(saveFailure.revoked, ['blob:backup'])
  assert.deepEqual(saveFailure.operations.at(-1), ['finish', 'op-1'])
  assert.equal(saveFailure.controller.busy.value, false)
})

test('a revoke failure cannot leave the operation or busy state behind', async () => {
  const item = harness({
    revokeObjectURL: () => { throw new Error('private revoke detail') },
  })
  await assert.rejects(() => item.controller.backup('p', 1), /private revoke detail/)
  assert.equal(item.controller.error.value, '创建项目备份失败，请重试。')
  assert.deepEqual(item.operations.at(-1), ['finish', 'op-1'])
  assert.equal(item.controller.busy.value, false)
})

test('a save failure remains primary when revoke also fails and cleanup permits retry', async () => {
  const saveFailure = new Error('primary save failure')
  const revokeFailure = new Error('secondary revoke failure')
  let saves = 0
  let revokes = 0
  const item = harness({
    saveBlob: () => {
      saves += 1
      if (saves === 1) throw saveFailure
    },
    revokeObjectURL: () => {
      revokes += 1
      if (revokes === 1) throw revokeFailure
    },
  })

  await assert.rejects(
    () => item.controller.backup('p', 1),
    failure => failure === saveFailure,
  )
  assert.equal(revokes, 1)
  assert.deepEqual(item.operations.at(-1), ['finish', 'op-1'])
  assert.equal(item.controller.busy.value, false)

  assert.equal(await item.controller.backup('p', 1), true)
  assert.equal(item.requests.length, 2)
  assert.equal(revokes, 2)
})

test('a save failure remains primary while transient real-store finish cleanup clears blocking for retry', async () => {
  const saveFailure = new Error('primary save failure')
  const finishFailure = new Error('secondary finish failure')
  let saves = 0
  let finishes = 0
  setActivePinia(createPinia())
  const operationStore = createOperationStore(`backup-cross-cleanup-${Date.now()}`)()
  const realFinish = operationStore.finish.bind(operationStore)
  operationStore.finish = operationId => {
    finishes += 1
    if (finishes === 1) throw finishFailure
    return realFinish(operationId)
  }
  const item = harness({
    operationStore,
    saveBlob: () => {
      saves += 1
      if (saves === 1) throw saveFailure
    },
  })

  await assert.rejects(
    () => item.controller.backup('p', 1),
    failure => failure === saveFailure,
  )
  assert.deepEqual(item.revoked, ['blob:backup'])
  assert.equal(item.controller.busy.value, false)
  assert.equal(operationStore.blocking, false)
  assert.equal(operationStore.active, false)
  assert.equal(finishes, 2)

  assert.equal(await item.controller.backup('p', 1), true)
  assert.equal(item.requests.length, 2)
  assert.equal(finishes, 3)
  assert.equal(operationStore.blocking, false)
  assert.equal(operationStore.active, false)
})

test('dispose aborts the request and fences a late binary result', async () => {
  const pending = deferred()
  let receivedSignal
  let aborts = 0
  const item = harness({
    abortControllerFactory: () => ({
      signal: { get aborted() { return aborts > 0 } },
      abort: () => { aborts += 1 },
    }),
    api: { projectBackups: { create: async (_projectId, _revision, { signal }) => {
      receivedSignal = signal
      return pending.promise
    } } },
  })
  const running = item.controller.backup('p', 5)
  await Promise.resolve()
  item.controller.dispose()
  pending.resolve({
    blob: new Blob(['late']),
    contentDisposition: 'attachment; filename="late.zip"',
    packageSha256: 'c'.repeat(64),
  })
  assert.equal(await running, false)
  assert.equal(receivedSignal.aborted, true)
  assert.equal(aborts, 1)
  assert.deepEqual(item.saved, [])
  assert.deepEqual(item.revoked, [])
  assert.equal(item.operations.filter(value => value[0] === 'finish').length, 1)
  assert.equal(item.controller.busy.value, false)
})

test('only safe zip content-disposition names are used and the blob body is never read', async () => {
  const values = [
    ['attachment; filename="safe.zip"', 'safe.zip'],
    ["attachment; filename*=UTF-8''%E5%A4%87%E4%BB%BD.zip", '备份.zip'],
    ["attachment; filename*=UTF-8''bad%ZZ.zip", 'project-backup.zip'],
    ["attachment; filename*=UTF-8''a%2Fb.zip", 'project-backup.zip'],
    ['attachment; filename="../../evil.zip"', 'project-backup.zip'],
    ['attachment; filename="not-a-zip.txt"', 'project-backup.zip'],
    ['attachment; filename="bad\u0001.zip"', 'project-backup.zip'],
  ]
  for (const [contentDisposition, filename] of values) {
    const blob = new Blob(['body-name.zip'])
    Object.defineProperty(blob, 'text', {
      value: async () => { throw new Error('blob body must not be read as a filename') },
    })
    const item = harness({ api: { projectBackups: { create: async () => ({
      blob, contentDisposition, packageSha256: 'd'.repeat(64),
    }) } } })
    assert.equal(await item.controller.backup('p', 1, { archived: true }), true)
    assert.equal(item.saved[0][1], filename)
  }
})

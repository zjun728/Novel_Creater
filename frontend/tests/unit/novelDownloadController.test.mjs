import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { createNovelDownloadController } from '../../src/application/downloads/novelDownloadController.js'
import { createOperationStore } from '../../src/stores/operationStore.js'

const OPTIONS = Object.freeze({
  available: true, reason: null, formats: ['txt', 'markdown'], volumes: [], chapters: [],
})
const selector = { scope: 'book', format: 'txt' }

function deferred() {
  let resolve
  let reject
  const promise = new Promise((nextResolve, nextReject) => { resolve = nextResolve; reject = nextReject })
  return { promise, resolve, reject }
}

function harness(overrides = {}) {
  const operations = []
  const revoked = []
  const saved = []
  const api = overrides.api || {
    novelDownloads: {
      options: async () => OPTIONS,
      download: async () => ({ blob: new Blob(['book']), contentDisposition: 'attachment; filename="book.txt"' }),
    },
  }
  const controller = createNovelDownloadController({
    api,
    operationStore: {
      start: value => { operations.push(value); return 'op-1' },
      finish: id => operations.push(['finish', id]),
    },
    createObjectURL: blob => { assert.ok(blob instanceof Blob); return 'blob:1' },
    revokeObjectURL: url => revoked.push(url),
    saveBlob: (url, filename) => saved.push([url, filename]),
    ...overrides,
  })
  return { controller, api, operations, revoked, saved }
}

test('loads safe options, surfaces a fixed retryable error, and does not expose transport detail', async () => {
  let calls = 0
  const { controller } = harness({ api: { novelDownloads: {
    options: async () => {
      calls += 1
      if (calls === 1) throw new Error('token=secret')
      return OPTIONS
    },
    download: async () => { throw new Error('not used') },
  } } })
  await assert.rejects(() => controller.loadOptions('p'))
  assert.equal(controller.error.value, '下载选项加载失败，请重试。')
  controller.clearError()
  assert.equal(controller.error.value, '')
  assert.equal(controller.options.value, null)
  assert.equal(controller.loading.value, false)
  assert.deepEqual(await controller.loadOptions('p'), OPTIONS)
  assert.equal(controller.error.value, '')
})

test('invalid option payloads become the same safe retryable loading failure', async () => {
  const { controller } = harness({ api: { novelDownloads: {
    options: async () => ({ available: true, formats: ['exe'], volumes: [], chapters: [] }),
    download: async () => { throw new Error('not used') },
  } } })
  await assert.rejects(() => controller.loadOptions('p'), TypeError)
  assert.equal(controller.options.value, null)
  assert.equal(controller.error.value, '下载选项加载失败，请重试。')
})

test('a new project aborts and replaces an older options request', async () => {
  const first = deferred(); const signals = []
  const { controller } = harness({ api: { novelDownloads: {
    options: (projectId, { signal } = {}) => { signals.push(signal); return projectId === 'A' ? first.promise : Promise.resolve({ ...OPTIONS, chapters: [{ number: 2, title: 'B', volumeId: 'v' }] }) },
    download: async () => { throw new Error('not used') },
  } } })
  const old = controller.loadOptions('A'); const next = controller.loadOptions('B')
  await next; first.resolve(OPTIONS); await old
  assert.equal(signals[0].aborted, true)
  assert.equal(controller.optionsProjectId.value, 'B')
  assert.equal(controller.options.value.chapters[0].number, 2)
})

test('switching projects fences an old download even when its transport ignores abort', async () => {
  const pending = deferred(); let signal
  const { controller, operations, saved, revoked } = harness({ api: { novelDownloads: {
    options: async () => OPTIONS,
    download: (_projectId, _selector, request) => { signal = request.signal; return pending.promise },
  } } })
  await controller.loadOptions('A')
  const old = controller.download('A', selector)
  controller.selectProject('B')
  pending.resolve({ blob: new Blob(['old']), contentDisposition: 'attachment; filename="old.txt"' })
  assert.equal(await old, false)
  assert.equal(signal.aborted, true)
  assert.deepEqual(saved, [])
  assert.deepEqual(revoked, [])
  assert.equal(controller.busy.value, false)
  assert.deepEqual(operations.filter(item => Array.isArray(item) && item[0] === 'finish'), [['finish', 'op-1']])
  await controller.loadOptions('B')
  assert.equal(await controller.download('B', selector), true)
})

test('only one available download starts, saves, finishes and always revokes', async () => {
  const pending = deferred()
  let downloads = 0
  const { controller, operations, revoked, saved } = harness({ api: { novelDownloads: {
    options: async () => OPTIONS,
    download: async () => { downloads += 1; return pending.promise },
  } } })
  await controller.loadOptions('p')
  const first = controller.download('p', selector)
  assert.equal(await controller.download('p', selector), false)
  pending.resolve({ blob: new Blob(['book']), contentDisposition: "attachment; filename*=UTF-8''%E4%B9%A6.txt" })
  assert.equal(await first, true)
  assert.equal(downloads, 1)
  assert.deepEqual(operations, [
    { label: '正在准备下载', detail: '', blocking: true }, ['finish', 'op-1'],
  ])
  assert.deepEqual(saved, [['blob:1', '书.txt']])
  assert.deepEqual(revoked, ['blob:1'])
  assert.equal(controller.busy.value, false)
})

test('create and save failures are safe, finish and revoke correctly, and hostile names fall back', async () => {
  const createFailure = harness({
    createObjectURL: () => { throw new Error('browser detail') },
  })
  await createFailure.controller.loadOptions('p')
  await assert.rejects(() => createFailure.controller.download('p', selector))
  assert.equal(createFailure.controller.error.value, '下载失败，请重试。')
  assert.deepEqual(createFailure.operations.at(-1), ['finish', 'op-1'])
  assert.deepEqual(createFailure.revoked, [])

  const saveFailure = harness({
    saveBlob: () => { throw new Error('save detail') },
    api: { novelDownloads: {
      options: async () => OPTIONS,
      download: async () => ({ blob: new Blob(['book']), contentDisposition: 'attachment; filename="../../x.exe"' }),
    } },
  })
  await saveFailure.controller.loadOptions('p')
  await assert.rejects(() => saveFailure.controller.download('p', { scope: 'book', format: 'markdown' }))
  assert.equal(saveFailure.controller.error.value, '下载失败，请重试。')
  assert.deepEqual(saveFailure.revoked, ['blob:1'])
})

test('a revoke failure cannot leave the operation or busy state behind', async () => {
  const item = harness({
    revokeObjectURL: () => { throw new Error('revoke failure') },
  })
  await item.controller.loadOptions('p')
  await assert.rejects(() => item.controller.download('p', selector), /revoke failure/)
  assert.deepEqual(item.operations.at(-1), ['finish', 'op-1'])
  assert.equal(item.controller.busy.value, false)
})

test('a save failure remains primary when revoke also fails and real-store cleanup permits retry', async () => {
  const saveFailure = new Error('primary save failure')
  const revokeFailure = new Error('secondary revoke failure')
  let downloads = 0
  let saves = 0
  const revoked = []
  setActivePinia(createPinia())
  const operationStore = createOperationStore(`download-cross-cleanup-${Date.now()}`)()
  const item = harness({
    operationStore,
    saveBlob: () => {
      saves += 1
      if (saves === 1) throw saveFailure
    },
    revokeObjectURL: url => {
      revoked.push(url)
      if (revoked.length === 1) throw revokeFailure
    },
    api: { novelDownloads: {
      options: async () => OPTIONS,
      download: async () => {
        downloads += 1
        return { blob: new Blob(['book']), contentDisposition: 'attachment; filename="book.txt"' }
      },
    } },
  })
  await item.controller.loadOptions('p')

  await assert.rejects(
    () => item.controller.download('p', selector),
    failure => failure === saveFailure,
  )
  assert.deepEqual(revoked, ['blob:1'])
  assert.equal(item.controller.busy.value, false)
  assert.equal(operationStore.blocking, false)

  assert.equal(await item.controller.download('p', selector), true)
  assert.equal(downloads, 2)
  assert.deepEqual(revoked, ['blob:1', 'blob:1'])
  assert.equal(operationStore.blocking, false)
})

test('a thrown null save failure remains primary when revoke also fails', async () => {
  const revokeFailure = new Error('secondary revoke failure')
  const item = harness({
    saveBlob: () => { throw null },
    revokeObjectURL: () => { throw revokeFailure },
  })
  await item.controller.loadOptions('p')

  await assert.rejects(
    () => item.controller.download('p', selector),
    failure => failure === null,
  )
  assert.deepEqual(item.operations.at(-1), ['finish', 'op-1'])
  assert.equal(item.controller.error.value, '下载失败，请重试。')
  assert.equal(item.controller.busy.value, false)
})

test('a transient real-store finish failure clears the blocker and permits retry', async () => {
  let downloads = 0
  setActivePinia(createPinia())
  const operationStore = createOperationStore(`download-cleanup-${Date.now()}`)()
  const realFinish = operationStore.finish.bind(operationStore)
  let finishes = 0
  operationStore.finish = operationId => {
    finishes += 1
    if (finishes === 1) throw new Error('private store detail')
    return realFinish(operationId)
  }
  const item = harness({
    operationStore,
    api: { novelDownloads: {
      options: async () => OPTIONS,
      download: async () => {
        downloads += 1
        return { blob: new Blob(['book']), contentDisposition: 'attachment; filename="book.txt"' }
      },
    } },
  })
  await item.controller.loadOptions('p')
  await assert.rejects(() => item.controller.download('p', selector), /private store detail/)
  assert.equal(item.controller.busy.value, false)
  assert.equal(item.controller.error.value, '下载失败，请重试。')
  assert.equal(operationStore.blocking, false)
  assert.equal(finishes, 2)
  assert.equal(await item.controller.download('p', selector), true)
  assert.equal(downloads, 2)
})

test('a thrown undefined finish failure surfaces without a primary failure', async () => {
  let finishes = 0
  const item = harness({
    operationStore: {
      start: () => 'op-1',
      finish: () => {
        finishes += 1
        if (finishes === 1) throw undefined
      },
    },
  })
  await item.controller.loadOptions('p')

  await assert.rejects(
    () => item.controller.download('p', selector),
    failure => failure === undefined,
  )
  assert.equal(finishes, 2)
  assert.equal(item.controller.error.value, '下载失败，请重试。')
  assert.equal(item.controller.busy.value, false)
})

test('finish cleanup failure never replaces an API or revoke failure', async () => {
  const primaryApiFailure = new Error('primary api failure')
  const primaryRevokeFailure = new Error('primary revoke failure')
  const finishFailure = new Error('finish cleanup failure')
  const finishOnce = () => {
    let calls = 0
    return {
      start: () => 'op-1',
      finish: () => {
        calls += 1
        if (calls === 1) throw finishFailure
      },
    }
  }

  const apiItem = harness({
    operationStore: finishOnce(),
    api: { novelDownloads: {
      options: async () => OPTIONS,
      download: async () => { throw primaryApiFailure },
    } },
  })
  await apiItem.controller.loadOptions('p')
  await assert.rejects(() => apiItem.controller.download('p', selector), primaryApiFailure)

  const revokeItem = harness({
    operationStore: finishOnce(),
    revokeObjectURL: () => { throw primaryRevokeFailure },
  })
  await revokeItem.controller.loadOptions('p')
  await assert.rejects(() => revokeItem.controller.download('p', selector), primaryRevokeFailure)
})

test('disposal aborts an internal request and fences its late result', async () => {
  const pending = deferred()
  let receivedSignal
  let aborted = 0
  const { controller, saved, revoked } = harness({
    abortControllerFactory: () => ({
      signal: { get aborted() { return aborted > 0 } },
      abort: () => { aborted += 1 },
    }),
    api: { novelDownloads: {
      options: async () => OPTIONS,
      download: async (_projectId, _selector, { signal }) => {
        receivedSignal = signal
        return pending.promise
      },
    } },
  })
  await controller.loadOptions('p')
  const running = controller.download('p', selector)
  controller.dispose()
  pending.resolve({ blob: new Blob(['book']), contentDisposition: 'attachment; filename="book.txt"' })
  assert.equal(await running, false)
  assert.equal(receivedSignal.aborted, true)
  assert.equal(aborted, 2)
  assert.deepEqual(saved, [])
  assert.deepEqual(revoked, [])
})

test('disposing an option load fences its late result', async () => {
  const pending = deferred()
  const { controller } = harness({ api: { novelDownloads: {
    options: async () => pending.promise,
    download: async () => { throw new Error('not used') },
  } } })
  const loading = controller.loadOptions('p')
  assert.equal(controller.loading.value, true)
  controller.dispose()
  assert.equal(controller.loading.value, false)
  pending.resolve(OPTIONS)
  assert.equal(await loading, false)
  assert.equal(controller.options.value, null)
})

test('disposing fences late option and download rejections without public errors', async () => {
  const optionPending = deferred()
  const optionItem = harness({ api: { novelDownloads: {
    options: async () => optionPending.promise,
    download: async () => { throw new Error('not used') },
  } } })
  const loading = optionItem.controller.loadOptions('p')
  optionItem.controller.dispose()
  optionPending.reject(new Error('late option failure'))
  assert.equal(await loading, false)
  assert.equal(optionItem.controller.error.value, '')

  const downloadPending = deferred()
  const downloadItem = harness({ api: { novelDownloads: {
    options: async () => OPTIONS,
    download: async () => downloadPending.promise,
  } } })
  await downloadItem.controller.loadOptions('p')
  const running = downloadItem.controller.download('p', selector)
  downloadItem.controller.dispose()
  downloadPending.reject(new Error('late download failure'))
  assert.equal(await running, false)
  assert.equal(downloadItem.controller.error.value, '')
})

test('dispose clears loading and busy even when abort throws', async () => {
  const pending = deferred()
  const item = harness({
    abortControllerFactory: () => ({
      signal: {},
      abort: () => { throw new Error('abort failure') },
    }),
    api: { novelDownloads: {
      options: async () => OPTIONS,
      download: async () => pending.promise,
    } },
  })
  await item.controller.loadOptions('p')
  const running = item.controller.download('p', selector)
  assert.throws(() => item.controller.dispose(), /abort failure/)
  assert.equal(item.controller.loading.value, false)
  assert.equal(item.controller.busy.value, false)
  pending.resolve({ blob: new Blob(['late']), contentDisposition: null })
  assert.equal(await running, false)
})

test('disposing an abort-aware request fences rejection and finishes its owned operation exactly once', async () => {
  const { controller, operations, saved, revoked } = harness({ api: { novelDownloads: {
    options: async () => OPTIONS,
    download: async (_projectId, _selector, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    }),
  } } })
  await controller.loadOptions('p')
  const running = controller.download('p', selector)
  controller.dispose()
  assert.equal(await running, false)
  assert.equal(operations.filter(item => Array.isArray(item) && item[0] === 'finish').length, 1)
  assert.deepEqual(saved, [])
  assert.deepEqual(revoked, [])
})

test('rejects unavailable download and uses safe filename fallbacks', async () => {
  const unavailable = harness({ api: { novelDownloads: {
    options: async () => ({ ...OPTIONS, available: false }),
    download: async () => { throw new Error('must not call') },
  } } })
  await unavailable.controller.loadOptions('p')
  assert.equal(await unavailable.controller.download('p', selector), false)

  const values = [
    ['attachment; filename="safe.txt"', 'safe.txt'],
    ["attachment; filename*=UTF-8''bad%ZZ.txt", 'novel.txt'],
    ["attachment; filename*=UTF-8''a%2Fb.txt", 'novel.txt'],
    ['attachment; filename=".."', 'novel.txt'],
    ['attachment; filename="evil.exe"', 'novel.txt'],
    ['attachment; filename="bad\u0001.md"', 'novel.txt'],
  ]
  for (const [contentDisposition, filename] of values) {
    const item = harness({ api: { novelDownloads: {
      options: async () => OPTIONS,
      download: async () => ({ blob: new Blob(['book']), contentDisposition }),
    } } })
    await item.controller.loadOptions('p')
    await item.controller.download('p', selector)
    assert.equal(item.saved[0][1], filename)
  }
})

test('blob contents are never used as a filename and malicious disposition falls back by format', async () => {
  const blob = new Blob(['evil.exe ../../not-a-filename'])
  Object.defineProperty(blob, 'text', {
    value: async () => { throw new Error('blob body must not be read as a filename') },
  })
  const item = harness({ api: { novelDownloads: {
    options: async () => OPTIONS,
    download: async () => ({ blob, contentDisposition: null }),
  } } })
  await item.controller.loadOptions('p')
  await item.controller.download('p', { scope: 'book', format: 'markdown' })
  assert.deepEqual(item.saved, [['blob:1', 'novel.md']])

  const hostile = harness({ api: { novelDownloads: {
    options: async () => OPTIONS,
    download: async () => ({ blob, contentDisposition: 'attachment; filename="../../evil.exe"' }),
  } } })
  await hostile.controller.loadOptions('p')
  await hostile.controller.download('p', { scope: 'book', format: 'markdown' })
  assert.deepEqual(hostile.saved, [['blob:1', 'novel.md']])

  const controlCharacter = harness({ api: { novelDownloads: {
    options: async () => OPTIONS,
    download: async () => ({ blob, contentDisposition: 'attachment; filename="bad\u0001.md"' }),
  } } })
  await controlCharacter.controller.loadOptions('p')
  await controlCharacter.controller.download('p', { scope: 'book', format: 'markdown' })
  assert.deepEqual(controlCharacter.saved, [['blob:1', 'novel.md']])
})

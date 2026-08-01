import assert from 'node:assert/strict'
import test from 'node:test'

import {
  createWorkingDraftAutosave,
} from '../../src/application/writer/workingDraftAutosave.js'

const OLD_HASH = 'a'.repeat(64)
const SAVED_HASH = 'b'.repeat(64)
const NEXT_HASH = 'c'.repeat(64)
const RESET_HASH = 'd'.repeat(64)

function authority(content, revision, contentHash) {
  return {
    workingDraft: {
      content,
      revision,
      contentHash,
    },
  }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function createClock() {
  let now = 0
  let nextId = 1
  const timers = new Map()

  function schedule(callback, delay) {
    const id = nextId
    nextId += 1
    timers.set(id, { callback, dueAt: now + delay })
    return id
  }

  function cancel(id) {
    timers.delete(id)
  }

  function advance(milliseconds) {
    now += milliseconds
    while (true) {
      const due = [...timers.entries()]
        .filter(([, timer]) => timer.dueAt <= now)
        .sort(([, left], [, right]) => left.dueAt - right.dueAt)[0]
      if (!due) return
      timers.delete(due[0])
      due[1].callback()
    }
  }

  return { schedule, cancel, advance }
}

function createState({ clock, persist, ...options }) {
  return createWorkingDraftAutosave({
    delayMs: 800,
    maxWaitMs: 5000,
    schedule: clock.schedule,
    cancel: clock.cancel,
    persist,
    ...options,
  })
}

test('debounces edits for 800ms and persists an immutable CAS snapshot', async () => {
  const clock = createClock()
  const pending = deferred()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => {
      snapshots.push(snapshot)
      return pending.promise
    },
  })
  state.reset(authority('旧稿', 1, OLD_HASH))
  state.edit('准备保存')

  clock.advance(799)
  assert.deepEqual(snapshots, [])
  clock.advance(1)
  assert.deepEqual(snapshots, [{
    editGeneration: 2,
    expectedRevision: 1,
    expectedContentHash: OLD_HASH,
    content: '准备保存',
  }])
  assert.equal(Object.isFrozen(snapshots[0]), true)
  assert.equal(state.status.value, 'saving')

  pending.resolve(authority('准备保存', 2, SAVED_HASH))
  await state.whenIdle()
  assert.equal(state.dirty.value, false)
  assert.equal(state.status.value, 'saved')
})

test('enforces a five-second maximum dirty window despite continued edits', async () => {
  const clock = createClock()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => {
      snapshots.push(snapshot)
      return authority(snapshot.content, 2, SAVED_HASH)
    },
  })
  state.reset(authority('旧稿', 1, OLD_HASH))
  state.edit('0')
  for (const content of ['1', '2', '3', '4', '5', '6', '7']) {
    clock.advance(700)
    state.edit(content)
  }

  clock.advance(100)
  await state.whenIdle()

  assert.equal(snapshots.length, 1)
  assert.equal(snapshots[0].content, '7')
})

test('keeps one save in flight and completion advances baseline without replacing newer typing', async () => {
  const clock = createClock()
  const pending = deferred()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => {
      snapshots.push(snapshot)
      return pending.promise
    },
  })
  state.reset(authority('旧稿', 1, OLD_HASH))
  state.edit('准备保存')
  clock.advance(800)
  state.edit('保存期间继续写')

  assert.equal(snapshots.length, 1)
  pending.resolve(authority('准备保存', 2, SAVED_HASH))
  await state.whenIdle()

  assert.equal(state.text.value, '保存期间继续写')
  assert.equal(state.persistedRevision.value, 2)
  assert.equal(state.persistedHash.value, SAVED_HASH)
  assert.equal(state.dirty.value, true)
})

test('starts a debounce-expired edit immediately after the prior in-flight save settles', async () => {
  const clock = createClock()
  const first = deferred()
  const second = deferred()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => {
      snapshots.push(snapshot)
      return snapshots.length === 1 ? first.promise : second.promise
    },
  })
  state.reset(authority('旧稿', 1, OLD_HASH))
  state.edit('保存 A')
  clock.advance(800)
  state.edit('保存 B')
  clock.advance(800)

  assert.equal(snapshots.length, 1)
  first.resolve(authority('保存 A', 2, SAVED_HASH))
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()

  assert.deepEqual(snapshots, [
    {
      editGeneration: 2,
      expectedRevision: 1,
      expectedContentHash: OLD_HASH,
      content: '保存 A',
    },
    {
      editGeneration: 3,
      expectedRevision: 2,
      expectedContentHash: SAVED_HASH,
      content: '保存 B',
    },
  ])
  second.resolve(authority('保存 B', 3, NEXT_HASH))
  await state.whenIdle()
  assert.equal(state.status.value, 'saved')
})

test('failure remains dirty until explicit retry succeeds', async () => {
  const clock = createClock()
  const attempts = []
  const state = createState({
    clock,
    persist: snapshot => {
      attempts.push(snapshot)
      if (attempts.length === 1) return Promise.reject(new Error('offline'))
      return authority(snapshot.content, 2, SAVED_HASH)
    },
  })
  state.reset(authority('旧稿', 1, OLD_HASH))
  state.edit('需要重试')
  clock.advance(800)
  await state.whenIdle()

  assert.equal(state.status.value, 'failed')
  assert.equal(state.dirty.value, true)
  clock.advance(5000)
  assert.equal(attempts.length, 1)
  await state.retry()

  assert.equal(attempts.length, 2)
  assert.equal(attempts[1].expectedRevision, 1)
  assert.equal(state.status.value, 'saved')
  assert.equal(state.dirty.value, false)
})

test('flush cancels scheduled work and persists visible text immediately', async () => {
  const clock = createClock()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => {
      snapshots.push(snapshot)
      return authority(snapshot.content, 2, SAVED_HASH)
    },
  })
  state.reset(authority('旧稿', 1, OLD_HASH))
  state.edit('立即暂存')

  await state.flush()
  clock.advance(5000)

  assert.equal(snapshots.length, 1)
  assert.equal(snapshots[0].content, '立即暂存')
  assert.equal(state.status.value, 'saved')
})

test('dispose cancels scheduled saves and ignores later edits', () => {
  const clock = createClock()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => snapshots.push(snapshot),
  })
  state.reset(authority('旧稿', 1, OLD_HASH))
  state.edit('不会保存')
  state.dispose()
  state.edit('仍然不会保存')
  clock.advance(5000)

  assert.equal(state.status.value, 'disposed')
  assert.equal(state.text.value, '不会保存')
  assert.deepEqual(snapshots, [])
})

test('does not save unchanged text', async () => {
  const clock = createClock()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => snapshots.push(snapshot),
  })
  state.reset(authority('不变正文', 1, OLD_HASH))
  state.edit('不变正文')
  clock.advance(5000)
  await state.flush()

  assert.equal(state.dirty.value, false)
  assert.deepEqual(snapshots, [])
})

test('conflict preserves local text and never retries against the advanced revision', async () => {
  const clock = createClock()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => {
      snapshots.push(snapshot)
      return Promise.reject({ code: 'ChapterSessionConflict' })
    },
  })
  state.reset(authority('旧稿', 1, OLD_HASH))
  state.edit('本地冲突正文')
  clock.advance(800)
  await state.whenIdle()
  clock.advance(5000)
  await state.retry()

  assert.equal(state.status.value, 'conflict')
  assert.equal(state.text.value, '本地冲突正文')
  assert.equal(state.persistedRevision.value, 1)
  assert.equal(snapshots.length, 1)
})

test('ignores an old successful response after reset installs a new authority epoch', async () => {
  const clock = createClock()
  const pending = deferred()
  const state = createState({
    clock,
    persist: () => pending.promise,
  })
  state.reset(authority('A 初始', 1, OLD_HASH))
  state.edit('A 待保存')
  clock.advance(800)
  state.reset(authority('B 权威正文', 9, RESET_HASH))

  assert.equal(state.status.value, 'saved')
  pending.resolve(authority('A 待保存', 2, SAVED_HASH))
  await state.whenIdle()

  assert.equal(state.text.value, 'B 权威正文')
  assert.equal(state.persistedRevision.value, 9)
  assert.equal(state.persistedHash.value, RESET_HASH)
  assert.equal(state.dirty.value, false)
  assert.equal(state.status.value, 'saved')
})

test('ignores an old rejected response after reset installs a new authority epoch', async () => {
  const clock = createClock()
  const pending = deferred()
  const state = createState({
    clock,
    persist: () => pending.promise,
  })
  state.reset(authority('A 初始', 1, OLD_HASH))
  state.edit('A 待保存')
  clock.advance(800)
  state.reset(authority('B 权威正文', 9, RESET_HASH))

  assert.equal(state.status.value, 'saved')
  pending.reject(new Error('old request failed'))
  await state.whenIdle()

  assert.equal(state.text.value, 'B 权威正文')
  assert.equal(state.persistedRevision.value, 9)
  assert.equal(state.persistedHash.value, RESET_HASH)
  assert.equal(state.dirty.value, false)
  assert.equal(state.status.value, 'saved')
})

test('starts a due new-epoch edit only after the old in-flight request releases', async () => {
  const clock = createClock()
  const first = deferred()
  const second = deferred()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => {
      snapshots.push(snapshot)
      return snapshots.length === 1 ? first.promise : second.promise
    },
  })
  state.reset(authority('A 初始', 1, OLD_HASH))
  state.edit('A 待保存')
  clock.advance(800)
  state.reset(authority('B 权威正文', 9, RESET_HASH))
  state.edit('B 本地编辑')

  assert.equal(state.status.value, 'pending')
  clock.advance(800)
  assert.equal(snapshots.length, 1)
  first.resolve(authority('A 待保存', 2, SAVED_HASH))
  await Promise.resolve()
  await Promise.resolve()
  await Promise.resolve()

  assert.deepEqual(snapshots[1], {
    editGeneration: 4,
    expectedRevision: 9,
    expectedContentHash: RESET_HASH,
    content: 'B 本地编辑',
  })
  second.resolve(authority('B 本地编辑', 10, NEXT_HASH))
  await state.whenIdle()
  assert.equal(state.status.value, 'saved')
})

test('exposes readonly public state so direct writes cannot bypass edit scheduling', async () => {
  const clock = createClock()
  const snapshots = []
  const state = createState({
    clock,
    persist: snapshot => {
      snapshots.push(snapshot)
      return authority(snapshot.content, 2, SAVED_HASH)
    },
  })
  state.reset(authority('权威正文', 1, OLD_HASH))
  const originalWarn = console.warn
  console.warn = () => {}
  try {
    state.text.value = '绕过 edit 的文本'
    state.status.value = 'failed'
    state.persistedRevision.value = 99
    state.persistedHash.value = NEXT_HASH
  } finally {
    console.warn = originalWarn
  }

  assert.equal(state.text.value, '权威正文')
  assert.equal(state.status.value, 'saved')
  assert.equal(state.persistedRevision.value, 1)
  assert.equal(state.persistedHash.value, OLD_HASH)
  assert.equal(state.dirty.value, false)
  clock.advance(5000)
  assert.deepEqual(snapshots, [])

  state.edit('只能经 edit 保存')
  clock.advance(800)
  await state.whenIdle()
  assert.deepEqual(snapshots, [{
    editGeneration: 2,
    expectedRevision: 1,
    expectedContentHash: OLD_HASH,
    content: '只能经 edit 保存',
  }])
})

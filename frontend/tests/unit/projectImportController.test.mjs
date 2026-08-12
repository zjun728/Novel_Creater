import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'

import { ApiError } from '../../src/api/db/api-error.js'
import { createProjectImportController, PROJECT_IMPORT_PHASES } from '../../src/application/project/projectImportController.js'
import { installOperationNavigationGuard } from '../../src/router/operationNavigationGuard.js'
import { createOperationStore } from '../../src/stores/operationStore.js'

const file = name => new File(['PK\u0003\u0004same exact bytes'], name, { type: 'application/zip' })
const summary = overrides => ({
  packageHash: 'a'.repeat(64), manifestHash: 'b'.repeat(64), packageVersion: 1,
  sourceTitle: '原项目', proposedTitle: '原项目（导入）', counts: { chapters: 3, assets: 2 },
  hasFinalizedChapters: true, providerHistoryCount: 4, ...overrides,
})
const identity = () => ({
  commandId: '11111111-1111-4111-8111-111111111111',
  idempotencyKey: 'import-key-00001',
})

function harness(overrides = {}) {
  const calls = []
  const operations = []
  const routes = []
  const api = overrides.api || {
    projectImports: {
      preflight: async selected => { calls.push(['preflight', selected]); return summary() },
      publish: async (selected, command) => {
        calls.push(['publish', selected, command])
        return { status: 'succeeded', phase: 'succeeded', targetProjectId: 'project-new' }
      },
      get: async commandId => { calls.push(['get', commandId]); return { status: 'running' } },
    },
  }
  const controller = createProjectImportController({
    api,
    router: { push: async path => routes.push(path) },
    operationStore: {
      start: value => { operations.push(['start', value]); return 'op-1' },
      update: (id, value) => operations.push(['update', id, value]),
      finish: id => operations.push(['finish', id]),
    },
    createIdentity: identity,
    wait: async () => {},
    ...overrides,
  })
  return { api, calls, operations, routes, controller }
}

test('selection owns File and identity, preflights without reading bytes, and exposes editable title', async () => {
  const selected = file('完整备份.zip')
  Object.defineProperty(selected, 'arrayBuffer', { value: () => { throw new Error('must not read') } })
  Object.defineProperty(selected, 'text', { value: () => { throw new Error('must not read') } })
  const item = harness()
  assert.equal(await item.controller.selectFile(selected), true)
  assert.equal(item.controller.file.value, selected)
  assert.equal(item.controller.filename.value, '完整备份.zip')
  assert.deepEqual(item.controller.summary.value, summary())
  assert.equal(item.controller.title.value, '原项目（导入）')
  item.controller.setTitle('作者的新名称')
  assert.equal(item.controller.title.value, '作者的新名称')
  assert.deepEqual(item.calls, [['preflight', selected]])
})

test('preflight failure retains the selector boundary and exposes no private detail', async () => {
  const selected = file('retry.zip')
  const item = harness({ api: { projectImports: {
    preflight: async () => { throw new Error('C:\\private\\archive.zip') },
    publish: async () => { throw new Error('not used') },
    get: async () => { throw new Error('not used') },
  } } })
  assert.equal(await item.controller.selectFile(selected), false)
  assert.equal(item.controller.file.value, selected)
  assert.equal(item.controller.summary.value, null)
  assert.equal(item.controller.error.value, '无法检查此备份，请重新选择或重试。')
  assert.doesNotMatch(item.controller.error.value, /private|archive\.zip/i)
})

test('one import uses the exact retained File and identifiers, publishes five phases, and navigates', async () => {
  const selected = file('backup.zip')
  const item = harness()
  await item.controller.selectFile(selected)
  item.controller.setTitle('新项目')
  const first = item.controller.importProject()
  assert.equal(await item.controller.importProject(), false)
  assert.equal(await first, true)

  const publish = item.calls.find(call => call[0] === 'publish')
  assert.equal(publish[1], selected)
  assert.deepEqual(publish[2], {
    ...identity(), expectedPackageHash: 'a'.repeat(64), newTitle: '新项目',
  })
  assert.deepEqual(item.operations.map(value => value[0] === 'start'
    ? value[1].label : value[0] === 'update' ? value[2].label : null).filter(Boolean), PROJECT_IMPORT_PHASES)
  assert.equal(item.operations[0][1].blocking, true)
  assert.deepEqual(item.operations.at(-1), ['finish', 'op-1'])
  assert.deepEqual(item.routes, ['/projects/project-new/overview'])
  assert.equal(item.controller.file.value, null)
})

test('unknown result gets command, polls running, and retryRequired reposts the same bytes and identity', async () => {
  const selected = file('backup.zip')
  const calls = []
  let publishes = 0
  const statuses = [
    { status: 'running', phase: 'staged', retryRequired: false },
    { status: 'running', phase: 'staged', retryRequired: true },
  ]
  const item = harness({ api: { projectImports: {
    preflight: async () => summary(),
    publish: async (sentFile, command) => {
      calls.push(['publish', sentFile, command])
      publishes += 1
      if (publishes === 1) throw new ApiError({ code: 'request_timeout', message: 'fixed' })
      return { status: 'succeeded', phase: 'succeeded', targetProjectId: 'restored' }
    },
    get: async commandId => { calls.push(['get', commandId]); return statuses.shift() },
  } } })
  await item.controller.selectFile(selected)
  assert.equal(await item.controller.importProject(), true)
  assert.deepEqual(calls.map(call => call[0]), ['publish', 'get', 'get', 'publish'])
  assert.equal(calls[0][1], selected)
  assert.equal(calls[3][1], selected)
  assert.deepEqual(calls[0][2], calls[3][2])
  assert.deepEqual(item.routes, ['/projects/restored/overview'])
})

test('failed command and known request failure expose only fixed errors and retain retry identity', async () => {
  const selected = file('backup.zip')
  const item = harness({ api: { projectImports: {
    preflight: async () => summary(),
    publish: async () => ({ status: 'failed', phase: 'failed', publicErrorCode: 'private-ish-code' }),
    get: async () => { throw new Error('not used') },
  } } })
  await item.controller.selectFile(selected)
  assert.equal(await item.controller.importProject(), false)
  assert.equal(item.controller.error.value, '项目导入失败，请重试。')
  assert.equal(item.controller.file.value, selected)
  assert.deepEqual(item.routes, [])
})

test('a retry after a known request failure keeps the exact command title and File', async () => {
  const selected = file('backup.zip')
  const sent = []
  const item = harness({ api: { projectImports: {
    preflight: async () => summary(),
    publish: async (sentFile, command) => {
      sent.push([sentFile, command])
      if (sent.length === 1) throw new ApiError({ status: 500, code: 'ProjectImportIntegrity' })
      return { status: 'succeeded', phase: 'succeeded', targetProjectId: 'retried' }
    },
    get: async () => { throw new Error('not used') },
  } } })
  await item.controller.selectFile(selected)
  item.controller.setTitle('固定标题')
  assert.equal(await item.controller.importProject(), false)
  assert.equal(item.controller.setTitle('不能改变'), false)
  assert.equal(item.controller.title.value, '固定标题')
  assert.equal(await item.controller.importProject(), true)
  assert.equal(sent[0][0], selected)
  assert.equal(sent[1][0], selected)
  assert.deepEqual(sent[0][1], sent[1][1])
})

test('navigation failure retains the successful command for exact replay and recovery', async () => {
  const selected = file('backup.zip')
  const commands = []
  const routes = []
  let navigationAttempts = 0
  const item = harness({
    api: { projectImports: {
      preflight: async () => summary(),
      publish: async (_file, command) => {
        commands.push(command)
        return { status: 'succeeded', phase: 'succeeded', targetProjectId: 'created-once' }
      },
      get: async () => { throw new Error('not used') },
    } },
    router: { push: async path => {
      navigationAttempts += 1
      if (navigationAttempts === 1) throw new Error('route failed')
      routes.push(path)
    } },
  })
  await item.controller.selectFile(selected)
  assert.equal(await item.controller.importProject(), false)
  assert.equal(item.controller.file.value, selected)
  assert.equal(await item.controller.importProject(), true)
  assert.deepEqual(commands[0], commands[1])
  assert.deepEqual(routes, ['/projects/created-once/overview'])
})

test('successful terminal finishes its blocker before a real guarded navigation', async () => {
  setActivePinia(createPinia())
  const backingStore = createOperationStore('project-import-navigation')()
  const events = []
  const operationStore = {
    start(value) { return backingStore.start(value) },
    update(id, value) { return backingStore.update(id, value) },
    finish(id) { events.push('finish'); return backingStore.finish(id) },
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/library', component: { template: '<div />' } },
      { path: '/projects/:id/overview', component: { template: '<div />' } },
    ],
  })
  await router.push('/library')
  installOperationNavigationGuard(router, () => backingStore)
  const controller = createProjectImportController({
    api: { projectImports: {
      preflight: async () => summary(),
      publish: async () => ({
        status: 'succeeded', phase: 'succeeded', targetProjectId: 'guarded-project',
      }),
      get: async () => { throw new Error('not used') },
    } },
    router: { push: async path => {
      events.push(`push:${backingStore.blocking}`)
      return router.push(path)
    } },
    operationStore,
    createIdentity: identity,
    wait: async () => {},
  })
  await controller.selectFile(file('backup.zip'))

  assert.equal(await controller.importProject(), true)
  assert.equal(router.currentRoute.value.path, '/projects/guarded-project/overview')
  assert.deepEqual(events, ['finish', 'push:false'])
  assert.equal(controller.file.value, null)
})

test('resolved Vue Router navigation failure retains File and command for exact replay', async () => {
  const commands = []
  let rejectNavigation = true
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/library', component: { template: '<div />' } },
      { path: '/projects/:id/overview', component: { template: '<div />' } },
    ],
  })
  await router.push('/library')
  router.beforeEach(to => (
    rejectNavigation && to.path.startsWith('/projects/') ? false : true
  ))
  const selected = file('backup.zip')
  const item = harness({
    api: { projectImports: {
      preflight: async () => summary(),
      publish: async (_file, command) => {
        commands.push(command)
        return { status: 'succeeded', phase: 'succeeded', targetProjectId: 'created-once' }
      },
      get: async () => { throw new Error('not used') },
    } },
    router,
  })
  await item.controller.selectFile(selected)

  assert.equal(await item.controller.importProject(), false)
  assert.equal(router.currentRoute.value.path, '/library')
  assert.equal(item.controller.file.value, selected)
  rejectNavigation = false
  assert.equal(await item.controller.importProject(), true)
  assert.deepEqual(commands[0], commands[1])
  assert.equal(router.currentRoute.value.path, '/projects/created-once/overview')
})

test('a transient unknown GET remains in recovery and retries GET without reposting', async () => {
  let gets = 0
  let publishes = 0
  const item = harness({ api: { projectImports: {
    preflight: async () => summary(),
    publish: async () => {
      publishes += 1
      throw new ApiError({ code: 'request_failed' })
    },
    get: async () => {
      gets += 1
      if (gets === 1) throw new ApiError({ code: 'request_timeout' })
      return { status: 'succeeded', phase: 'succeeded', targetProjectId: 'recovered' }
    },
  } } })
  await item.controller.selectFile(file('backup.zip'))
  assert.equal(await item.controller.importProject(), true)
  assert.equal(publishes, 1)
  assert.equal(gets, 2)
  assert.deepEqual(item.routes, ['/projects/recovered/overview'])
})

test('changing selection aborts old preflight; dispose aborts and generation-fences late results', async () => {
  let resolveFirst
  const signals = []
  const first = file('old.zip')
  const second = file('new.zip')
  const item = harness({ api: { projectImports: {
    preflight: (selected, { signal }) => {
      signals.push([selected, signal])
      if (selected === first) return new Promise(resolve => { resolveFirst = resolve })
      return Promise.resolve(summary({ proposedTitle: 'new' }))
    },
    publish: async () => ({ status: 'succeeded', targetProjectId: 'late' }),
    get: async () => ({ status: 'running' }),
  } } })
  const old = item.controller.selectFile(first)
  await Promise.resolve()
  assert.equal(await item.controller.selectFile(second), true)
  assert.equal(signals[0][1].aborted, true)
  resolveFirst(summary({ proposedTitle: 'old' }))
  assert.equal(await old, false)
  assert.equal(item.controller.title.value, 'new')

  const importing = item.controller.importProject()
  item.controller.dispose()
  assert.equal(await importing, false)
  assert.deepEqual(item.routes, [])
  assert.equal(item.controller.busy.value, false)
  assert.equal(Object.hasOwn(item.controller, 'cancel'), false)
})

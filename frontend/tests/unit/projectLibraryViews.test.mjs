import assert from 'node:assert/strict'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import vuePlugin from '@vitejs/plugin-vue'
import { createServer } from 'vite'

const naiveUiStubId = '\0project-library-naive-ui-stub'
const frontendRoot = fileURLToPath(new URL('../..', import.meta.url))
const naiveUiStubPlugin = {
  name: 'project-library-naive-ui-stub',
  enforce: 'pre',
  resolveId(id) {
    if (id === 'naive-ui') return naiveUiStubId
  },
  load(id) {
    if (id !== naiveUiStubId) return undefined
    return `
      import { defineComponent, h } from 'vue'
      const stub = name => defineComponent({
        name,
        inheritAttrs: false,
        setup(_, { attrs, slots }) {
          return () => h('div', attrs, slots.default?.())
        },
      })
      export const NAlert = stub('NAlert')
      export const NEmpty = stub('NEmpty')
      export const NSkeleton = stub('NSkeleton')
      export const useMessage = () => ({})
      export const useDialog = () => ({})
    `
  },
}

let vite
let libraryModule
let archivedModule

test.before(async () => {
  vite = await createServer({
    configFile: false,
    root: frontendRoot,
    server: { middlewareMode: true, hmr: false, ws: false },
    appType: 'custom',
    logLevel: 'error',
    plugins: [vuePlugin(), naiveUiStubPlugin],
    ssr: { noExternal: ['naive-ui'] },
    optimizeDeps: { noDiscovery: true },
  })
  ;[libraryModule, archivedModule] = await Promise.all([
    vite.ssrLoadModule('/src/views/ProjectLibraryView.vue'),
    vite.ssrLoadModule('/src/views/ArchivedProjectsView.vue'),
  ])
})

test.after(async () => {
  await vite?.close()
})

function project(overrides = {}) {
  return {
    id: 'project-1',
    title: '典镇山河',
    lifecycleRevision: 3,
    archivedAt: null,
    ...overrides,
  }
}

function messageRecorder() {
  const calls = []
  const message = {}
  for (const type of ['success', 'error', 'warning', 'info']) {
    message[type] = (content, options) => calls.push({ type, content, options })
  }
  return { calls, message }
}

test('active page creates and routes only after the server returns the new project', async () => {
  const created = project({ id: 'created-1', title: '新项目' })
  const calls = []
  const routes = []
  const { message } = messageRecorder()
  const controller = libraryModule.createProjectLibraryController({
    store: {
      activeProjects: [],
      createProject: async title => {
        calls.push(['create', title])
        return created
      },
    },
    router: { push: async path => routes.push(path) },
    message,
  })

  const request = controller.create({ title: '新项目' })
  assert.deepEqual(routes, [])
  await request

  assert.deepEqual(calls, [['create', '新项目']])
  assert.deepEqual(routes, ['/projects/created-1/overview'])
  assert.equal(controller.createDialogOpen.value, false)
})

test('a route failure after successful creation keeps the project created and reports page recovery', async () => {
  const created = project({ id: 'created-1', title: '新项目' })
  const store = {
    activeProjects: [],
    createProject: async () => {
      store.activeProjects.push(created)
      return created
    },
  }
  const controller = libraryModule.createProjectLibraryController({
    store,
    router: {
      push: async () => {
        throw new Error('暂时无法打开项目')
      },
    },
    message: messageRecorder().message,
  })

  await controller.create({ title: '新项目' })

  assert.deepEqual(store.activeProjects, [created])
  assert.equal(controller.createDialogOpen.value, false)
  assert.equal(controller.createError.value, '')
  assert.equal(controller.actionError.value, '暂时无法打开项目')
})

test('active page opens and resumes only through explicit route actions', async () => {
  const routes = []
  const controller = libraryModule.createProjectLibraryController({
    store: { activeProjects: [] },
    router: { push: async path => routes.push(path) },
    message: messageRecorder().message,
  })
  const current = project()

  assert.deepEqual(routes, [])
  await controller.open(current)
  await controller.resume(current, 4)
  assert.deepEqual(routes, [
    '/projects/project-1/overview',
    '/projects/project-1/write/chapters/4',
  ])
})

test('rename keeps the dialog open and server-backed list unchanged on failure', async () => {
  const original = project({ title: '原名' })
  const store = {
    activeProjects: [original],
    renameProject: async () => {
      throw new Error('重命名失败，请重试')
    },
  }
  const controller = libraryModule.createProjectLibraryController({
    store,
    router: { push: async () => {} },
    message: messageRecorder().message,
  })
  controller.beginRename(original)

  await controller.rename({ title: '新名' })

  assert.deepEqual(store.activeProjects, [original])
  assert.deepEqual(controller.renameTarget.value, original)
  assert.equal(controller.renameError.value, '重命名失败，请重试')
  assert.equal(controller.renamePending.value, false)
})

test('archive has no confirmation and successful toast undo restores returned revision', async () => {
  const original = project()
  const archived = project({ archivedAt: 123, lifecycleRevision: 4 })
  const calls = []
  const feedback = messageRecorder()
  const controller = libraryModule.createProjectLibraryController({
    store: {
      activeProjects: [original],
      archiveProject: async (id, revision) => {
        calls.push(['archive', id, revision])
        return archived
      },
      restoreProject: async (id, revision) => {
        calls.push(['restore', id, revision])
        return project({ lifecycleRevision: 5 })
      },
    },
    router: { push: async () => {} },
    message: feedback.message,
  })

  await controller.archive(original)
  assert.deepEqual(calls, [['archive', 'project-1', 3]])
  const archiveToast = feedback.calls.find(call => call.content === '项目已归档')
  assert.equal(archiveToast.options.actionLabel, '撤销')
  assert.equal(archiveToast.options.duration, 6000)

  await archiveToast.options.onAction()
  assert.deepEqual(calls, [
    ['archive', 'project-1', 3],
    ['restore', 'project-1', 4],
  ])
})

test('undo failure reports an error without optimistic list mutation', async () => {
  const original = project()
  const archived = project({ archivedAt: 123, lifecycleRevision: 4 })
  const archivedRows = [archived]
  const feedback = messageRecorder()
  const controller = libraryModule.createProjectLibraryController({
    store: {
      activeProjects: [],
      archivedProjects: archivedRows,
      archiveProject: async () => archived,
      restoreProject: async () => {
        throw new Error('项目已在别处更新')
      },
    },
    router: { push: async () => {} },
    message: feedback.message,
  })

  await controller.archive(original)
  const undo = feedback.calls.find(call => call.content === '项目已归档').options.onAction
  await undo()

  assert.deepEqual(archivedRows, [archived])
  assert.match(controller.actionError.value, /项目已在别处更新/)
  assert.ok(feedback.calls.some(call => call.type === 'error' && call.content === '撤销归档失败'))
})

test('archive failure stays recoverable and does not remove the project', async () => {
  const original = project()
  const rows = [original]
  const controller = libraryModule.createProjectLibraryController({
    store: {
      activeProjects: rows,
      archiveProject: async () => {
        throw new Error('归档暂时失败')
      },
    },
    router: { push: async () => {} },
    message: messageRecorder().message,
  })

  await controller.archive(original)
  assert.deepEqual(rows, [original])
  assert.equal(controller.actionError.value, '归档暂时失败')
})

test('archived page restores directly without confirmation', async () => {
  const archived = project({ archivedAt: 123 })
  const calls = []
  const controller = archivedModule.createArchivedProjectsController({
    store: {
      archivedProjects: [archived],
      restoreProject: async (id, revision) => calls.push(['restore', id, revision]),
    },
    message: messageRecorder().message,
    confirmation: {
      confirm: async () => {
        calls.push(['unexpected-confirm'])
        return false
      },
    },
  })

  await controller.restore(archived)
  assert.deepEqual(calls, [['restore', 'project-1', 3]])
})

test('permanent delete calls no API on cancel and runs once through danger confirmation', async () => {
  const archived = project({ archivedAt: 123 })
  const calls = []
  let confirmationOptions
  const store = {
    archivedProjects: [archived],
    permanentlyDeleteProject: async (id, revision) => {
      calls.push(['delete', id, revision])
    },
  }
  const controller = archivedModule.createArchivedProjectsController({
    store,
    message: messageRecorder().message,
    confirmation: {
      confirm: async options => {
        confirmationOptions = options
        return false
      },
    },
  })

  await controller.permanentlyDelete(archived)
  assert.deepEqual(calls, [])
  assert.equal(confirmationOptions.positiveText, '永久删除')
  assert.match(confirmationOptions.content, /无法恢复/)

  await confirmationOptions.onConfirm()
  assert.deepEqual(calls, [['delete', 'project-1', 3]])
})

test('both pages expose recoverable load errors and retry the same list', async () => {
  let attempts = 0
  const store = {
    activeProjects: [],
    loadActiveProjects: async () => {
      attempts += 1
      if (attempts === 1) throw new Error('项目库加载失败')
    },
  }
  const controller = libraryModule.createProjectLibraryController({
    store,
    router: { push: async () => {} },
    message: messageRecorder().message,
  })

  await controller.load()
  assert.equal(controller.loadError.value, '项目库加载失败')
  assert.equal(controller.loading.value, false)
  await controller.load()
  assert.equal(controller.loadError.value, '')
  assert.equal(attempts, 2)
})

import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import * as projectStoreModule from '../../src/stores/projectStore.js'

let storeSequence = 0

function project(id, {
  title = id,
  archivedAt = null,
  lifecycleRevision = 0,
} = {}) {
  return { id, title, archivedAt, lifecycleRevision }
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

function createStore(projectApi) {
  assert.equal(
    typeof projectStoreModule.createProjectStore,
    'function',
    'project store must expose an API-injectable definition factory',
  )
  setActivePinia(createPinia())
  storeSequence += 1
  return projectStoreModule.createProjectStore(
    projectApi,
    `project-lifecycle-test-${storeSequence}`,
  )()
}

function snapshot(store) {
  return JSON.parse(JSON.stringify({
    activeProjects: store.activeProjects,
    archivedProjects: store.archivedProjects,
    currentProject: store.currentProject,
  }))
}

test('loads separate lists and commits create and rename only after success', async () => {
  const active = project('active-1', { title: '旧名', lifecycleRevision: 2 })
  const archived = project('archived-1', { archivedAt: 123, lifecycleRevision: 3 })
  const pendingCreate = deferred()
  const pendingRename = deferred()
  const calls = []
  const store = createStore({
    listActive: async () => [active],
    listArchived: async () => [archived],
    create: input => {
      calls.push(['create', structuredClone(input)])
      return pendingCreate.promise
    },
    get: async () => active,
    rename: (projectId, input) => {
      calls.push(['rename', projectId, structuredClone(input)])
      return pendingRename.promise
    },
  })

  await store.loadActiveProjects()
  await store.loadArchivedProjects()
  assert.deepEqual(store.activeProjects, [active])
  assert.deepEqual(store.archivedProjects, [archived])

  const creating = store.createProject('新项目')
  assert.deepEqual(store.activeProjects, [active])
  const created = project('active-2', { title: '新项目' })
  pendingCreate.resolve(created)
  await creating
  assert.deepEqual(store.activeProjects, [created, active])

  const renaming = store.renameProject('active-1', '新名字')
  assert.equal(store.activeProjects[1].title, '旧名')
  const renamed = project('active-1', { title: '新名字', lifecycleRevision: 2 })
  pendingRename.resolve(renamed)
  await renaming
  assert.deepEqual(store.activeProjects, [created, renamed])
  assert.deepEqual(calls, [
    ['create', { title: '新项目' }],
    ['rename', 'active-1', { title: '新名字' }],
  ])
})

test('archive and restore move a project only after successful responses', async () => {
  const active = project('project-1', { lifecycleRevision: 4 })
  const pendingArchive = deferred()
  const pendingRestore = deferred()
  const store = createStore({
    listActive: async () => [active],
    listArchived: async () => [],
    get: async () => active,
    archive: (projectId, revision) => {
      assert.equal(projectId, 'project-1')
      assert.equal(revision, 4)
      return pendingArchive.promise
    },
    restore: (projectId, revision) => {
      assert.equal(projectId, 'project-1')
      assert.equal(revision, 5)
      return pendingRestore.promise
    },
  })

  await store.loadActiveProjects()
  await store.loadArchivedProjects()
  await store.loadProject('project-1')

  const archiving = store.archiveProject('project-1', 4)
  assert.deepEqual(store.activeProjects, [active])
  assert.deepEqual(store.archivedProjects, [])
  assert.deepEqual(store.currentProject, active)

  const archived = project('project-1', { archivedAt: 123, lifecycleRevision: 5 })
  pendingArchive.resolve(archived)
  await archiving
  assert.deepEqual(store.activeProjects, [])
  assert.deepEqual(store.archivedProjects, [archived])
  assert.deepEqual(store.currentProject, archived)

  const restoring = store.restoreProject('project-1', 5)
  assert.deepEqual(store.archivedProjects, [archived])
  const restored = project('project-1', { lifecycleRevision: 6 })
  pendingRestore.resolve(restored)
  await restoring
  assert.deepEqual(store.activeProjects, [restored])
  assert.deepEqual(store.archivedProjects, [])
  assert.deepEqual(store.currentProject, restored)
})

test('failed lifecycle requests preserve both lists and current project exactly', async () => {
  const active = project('active-1', { lifecycleRevision: 2 })
  const archived = project('archived-1', { archivedAt: 123, lifecycleRevision: 3 })
  const failure = new Error('request failed')
  const projectApi = {
    listActive: async () => [active],
    listArchived: async () => [archived],
    get: async () => active,
    create: async () => { throw failure },
    rename: async () => { throw failure },
    archive: async () => { throw failure },
    restore: async () => { throw failure },
    permanentlyDelete: async () => { throw failure },
  }
  const store = createStore(projectApi)
  await store.loadActiveProjects()
  await store.loadArchivedProjects()
  await store.loadProject('active-1')
  const before = snapshot(store)

  for (const operation of [
    () => store.createProject('失败的新项目'),
    () => store.renameProject('active-1', '失败的新名字'),
    () => store.archiveProject('active-1', 2),
    () => store.restoreProject('archived-1', 3),
    () => store.permanentlyDeleteProject('archived-1', 3),
  ]) {
    await assert.rejects(operation, /request failed/)
    assert.deepEqual(snapshot(store), before)
  }
})

test('an older project load cannot overwrite a newer route context', async () => {
  const oldResponse = deferred()
  const newProject = project('project-2')
  const store = createStore({
    get: projectId => (
      projectId === 'project-1' ? oldResponse.promise : Promise.resolve(newProject)
    ),
  })

  const oldLoad = store.loadProject('project-1')
  await store.loadProject('project-2')
  oldResponse.resolve(project('project-1'))
  await oldLoad

  assert.deepEqual(store.currentProject, newProject)
  assert.equal('invalidateOpenProject' in store, false)
})

test('a failed load for a new route cannot retain the previous route project', async () => {
  const established = project('project-1')
  const store = createStore({
    get: async projectId => {
      if (projectId === 'project-2') throw new Error('missing')
      return established
    },
  })

  await store.loadProject('project-1')
  await assert.rejects(() => store.loadProject('project-2'), /missing/)
  assert.equal(store.currentProject, null)
})

test('permanent delete removes only the archived copy after server success', async () => {
  const active = project('project-1', { lifecycleRevision: 5 })
  const archived = project('project-1', { archivedAt: 123, lifecycleRevision: 5 })
  const pendingDelete = deferred()
  const store = createStore({
    listActive: async () => [active],
    listArchived: async () => [archived],
    get: async () => archived,
    permanentlyDelete: (projectId, revision) => {
      assert.equal(projectId, 'project-1')
      assert.equal(revision, 5)
      return pendingDelete.promise
    },
  })

  await store.loadActiveProjects()
  await store.loadArchivedProjects()
  await store.loadProject('project-1')
  const deleting = store.permanentlyDeleteProject('project-1', 5)
  assert.deepEqual(store.archivedProjects, [archived])
  assert.deepEqual(store.currentProject, archived)
  pendingDelete.resolve(null)
  await deleting

  assert.deepEqual(store.activeProjects, [active])
  assert.deepEqual(store.archivedProjects, [])
  assert.equal(store.currentProject, null)
})

test('late list responses cannot erase a newer successful lifecycle write', async () => {
  const oldActiveList = deferred()
  const oldArchivedList = deferred()
  const created = project('project-2')
  const archived = project('project-1', { archivedAt: 123, lifecycleRevision: 2 })
  const store = createStore({
    listActive: () => oldActiveList.promise,
    listArchived: () => oldArchivedList.promise,
    create: async () => created,
    archive: async () => archived,
  })

  const activeLoad = store.loadActiveProjects()
  const archivedLoad = store.loadArchivedProjects()
  await store.createProject('project-2')
  await store.archiveProject('project-1', 1)
  oldActiveList.resolve([project('project-1', { lifecycleRevision: 1 })])
  oldArchivedList.resolve([])
  await Promise.all([activeLoad, archivedLoad])

  assert.deepEqual(store.activeProjects, [created])
  assert.deepEqual(store.archivedProjects, [archived])
})

test('late project reads cannot undo archive or resurrect a permanently deleted route project', async () => {
  const oldArchiveRead = deferred()
  const archived = project('archive-me', { archivedAt: 123, lifecycleRevision: 2 })
  const archiveStore = createStore({
    get: () => oldArchiveRead.promise,
    archive: async () => archived,
  })

  const archiveRead = archiveStore.loadProject('archive-me')
  await archiveStore.archiveProject('archive-me', 1)
  oldArchiveRead.resolve(project('archive-me', { lifecycleRevision: 1 }))
  await archiveRead
  assert.deepEqual(archiveStore.currentProject, archived)

  const oldDeleteRead = deferred()
  const deleteStore = createStore({
    get: () => oldDeleteRead.promise,
    permanentlyDelete: async () => null,
  })
  const deleteRead = deleteStore.loadProject('delete-me')
  await deleteStore.permanentlyDeleteProject('delete-me', 4)
  oldDeleteRead.resolve(project('delete-me', { archivedAt: 123, lifecycleRevision: 4 }))
  await deleteRead
  assert.equal(deleteStore.currentProject, null)
})

const ROUTE_ISOLATION_MUTATIONS = Object.freeze([
  {
    name: 'rename',
    install(projectApi, succeeds, changed) {
      projectApi.rename = async () => {
        if (!succeeds) throw new Error('rename failed')
        return changed
      }
    },
    run(store) {
      return store.renameProject('project-a', 'renamed-a')
    },
    changed: project('project-a', { title: 'renamed-a', lifecycleRevision: 4 }),
  },
  {
    name: 'archive',
    install(projectApi, succeeds, changed) {
      projectApi.archive = async () => {
        if (!succeeds) throw new Error('archive failed')
        return changed
      }
    },
    run(store) {
      return store.archiveProject('project-a', 3)
    },
    changed: project('project-a', { archivedAt: 123, lifecycleRevision: 4 }),
  },
  {
    name: 'restore',
    install(projectApi, succeeds, changed) {
      projectApi.restore = async () => {
        if (!succeeds) throw new Error('restore failed')
        return changed
      }
    },
    run(store) {
      return store.restoreProject('project-a', 3)
    },
    changed: project('project-a', { lifecycleRevision: 4 }),
  },
  {
    name: 'permanent delete',
    install(projectApi, succeeds) {
      projectApi.permanentlyDelete = async () => {
        if (!succeeds) throw new Error('permanent delete failed')
      }
    },
    run(store) {
      return store.permanentlyDeleteProject('project-a', 3)
    },
    changed: null,
  },
])

test('lifecycle mutations cannot change currentProject for a different pending route', async t => {
  for (const mutation of ROUTE_ISOLATION_MUTATIONS) {
    for (const mutationSucceeds of [true, false]) {
      for (const routeSucceeds of [true, false]) {
        await t.test(
          `${mutation.name}; mutation ${mutationSucceeds ? 'success' : 'failure'}; route ${routeSucceeds ? 'success' : 'failure'}`,
          async () => {
            const projectA = project('project-a', { title: 'original-a', lifecycleRevision: 3 })
            const projectB = project('project-b')
            const pendingB = deferred()
            let firstRead = true
            const projectApi = {
              get: projectId => {
                if (projectId === 'project-a' && firstRead) {
                  firstRead = false
                  return Promise.resolve(projectA)
                }
                assert.equal(projectId, 'project-b')
                return pendingB.promise
              },
            }
            mutation.install(projectApi, mutationSucceeds, mutation.changed)
            const store = createStore(projectApi)
            await store.loadProject('project-a')
            const routeB = store.loadProject('project-b')
            assert.equal(
              store.currentProject,
              null,
              'starting a different route load must clear the prior route project',
            )

            if (mutationSucceeds) {
              await mutation.run(store)
            } else {
              await assert.rejects(mutation.run(store), /failed/)
            }
            assert.deepEqual(
              store.currentProject,
              null,
              'a non-route mutation must not replace currentProject',
            )

            if (routeSucceeds) {
              pendingB.resolve(projectB)
              await routeB
              assert.deepEqual(store.currentProject, projectB)
            } else {
              pendingB.reject(new Error('project-b load failed'))
              await assert.rejects(routeB, /project-b load failed/)
              assert.equal(
                store.currentProject,
                null,
                'a failed target route must not resurrect the previous project',
              )
            }
          },
        )
      }
    }
  }
})

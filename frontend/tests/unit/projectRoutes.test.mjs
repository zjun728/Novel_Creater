import assert from 'node:assert/strict'
import test from 'node:test'

import { effectScope, nextTick, reactive } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'

async function loadRouteModule() {
  try {
    return await import('../../src/router/projectRoutes.js')
  } catch (error) {
    assert.fail(`canonical project route module is missing: ${error.message}`)
  }
}

async function loadRouteProjectModule() {
  try {
    return await import('../../src/composables/useRouteProject.js')
  } catch (error) {
    assert.fail(`route-owned project context is missing: ${error.message}`)
  }
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

async function settle() {
  await nextTick()
  await new Promise(resolve => setImmediate(resolve))
  await nextTick()
}

test('canonical path builders encode project IDs and require positive chapter numbers', async () => {
  const {
    applicationSettingsPath,
    experienceLibraryPath,
    chapterWriterPath,
    projectContractPath,
    projectBiblePath,
    projectModelSettingsPath,
    projectOverviewPath,
    projectSeedsPath,
    styleLibraryPath,
  } = await loadRouteModule()

  assert.equal(styleLibraryPath(), '/assets/styles')
  assert.equal(experienceLibraryPath(), '/assets/experience')
  assert.equal(projectOverviewPath('a/b'), '/projects/a%2Fb/overview')
  assert.equal(projectSeedsPath('a/b'), '/projects/a%2Fb/seeds')
  assert.equal(projectContractPath('a/b'), '/projects/a%2Fb/contract')
  assert.equal(projectBiblePath('a/b'), '/projects/a%2Fb/bible')
  assert.equal(
    projectModelSettingsPath('a/b'),
    '/projects/a%2Fb/settings/models',
  )
  assert.equal(applicationSettingsPath(), '/settings/application')
  assert.equal(chapterWriterPath('p 1', 3), '/projects/p%201/write/chapters/3')
  for (const invalid of [0, -1, 1.5, '3.5', '', null]) {
    assert.throws(() => chapterWriterPath('project-1', invalid), /positive chapter number/i)
  }
})

test('formal route registry names only canonical destinations and catches retired paths', async () => {
  const { projectRoutes } = await loadRouteModule()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: projectRoutes,
  })

  const root = router.resolve('/')
  assert.equal(root.matched[0].redirect, '/projects')
  assert.equal(router.resolve('/projects').name, 'ProjectLibrary')
  assert.equal(router.resolve('/projects/archived').name, 'ArchivedProjects')
  assert.equal(router.resolve('/settings/providers').name, 'ProviderSettings')
  assert.equal(router.resolve('/settings/application').name, 'ApplicationSettings')
  assert.equal(router.resolve('/assets/styles').name, 'StyleLibrary')
  assert.equal(router.resolve('/assets/experience').name, 'ExperienceLibrary')
  assert.equal(router.resolve('/projects/project-1/overview').name, 'ProjectOverview')
  assert.equal(router.resolve('/projects/project-1/seeds').name, 'ProjectSeeds')
  assert.equal(
    router.resolve('/projects/project-1/contract').name,
    'ProjectContract',
  )
  assert.equal(router.resolve('/projects/project-1/bible').name, 'ProjectBible')
  assert.equal(
    router.resolve('/projects/project-1/settings/models').name,
    'ProjectModelSettings',
  )
  assert.equal(
    router.resolve('/projects/project-1/write/chapters/9').name,
    'ChapterWriter',
  )

  for (const path of [
    '/projects/project-1/write/chapters/0',
    '/projects/project-1/write/chapters/nope',
    ['', 'project', 'old-id'].join('/'),
    '/writer/old-id/1',
    '/settings',
    '/arbitrary/path',
  ]) {
    const resolved = router.resolve(path)
    assert.equal(resolved.meta.notFound, true, `${path} must select NotFound`)
  }
})

test('creative asset routes survive direct navigation and browser back/forward', async () => {
  const { projectRoutes } = await loadRouteModule()
  const router = createRouter({
    history: createMemoryHistory(),
    routes: projectRoutes.map(route => (
      ['StyleLibrary', 'ExperienceLibrary'].includes(route.name)
        ? { ...route, component: { render: () => null } }
        : route
    )),
  })

  await router.push('/assets/styles')
  await router.isReady()
  assert.equal(router.currentRoute.value.name, 'StyleLibrary')

  await router.push('/assets/experience')
  assert.equal(router.currentRoute.value.name, 'ExperienceLibrary')

  router.back()
  await settle()
  assert.equal(router.currentRoute.value.name, 'StyleLibrary')

  router.forward()
  await settle()
  assert.equal(router.currentRoute.value.name, 'ExperienceLibrary')
})

test('route context hydrates on refresh and classifies active archived missing and error states', async () => {
  const { useRouteProject } = await loadRouteProjectModule()
  const calls = []
  const route = reactive({ params: { projectId: 'active-1' } })
  const store = {
    async loadProject(projectId) {
      calls.push(projectId)
      if (projectId === 'active-1') {
        return { id: projectId, title: '典镇山河', archivedAt: null }
      }
      if (projectId === 'archived-1') {
        return { id: projectId, title: '旧稿', archivedAt: 123 }
      }
      if (projectId === 'missing-1') {
        throw Object.assign(new Error('missing'), { status: 404, code: 'project_not_found' })
      }
      throw new Error('offline')
    },
  }
  const scope = effectScope()
  const context = scope.run(() => useRouteProject({ route, store }))

  assert.equal(context.state.value, 'loading')
  await settle()
  assert.deepEqual(calls, ['active-1'])
  assert.equal(context.state.value, 'active')
  assert.equal(context.project.value.id, 'active-1')

  route.params.projectId = 'archived-1'
  await settle()
  assert.equal(context.state.value, 'archived')
  assert.equal(context.project.value.id, 'archived-1')

  route.params.projectId = 'missing-1'
  await settle()
  assert.equal(context.state.value, 'missing')
  assert.equal(context.project.value, null)

  route.params.projectId = 'offline-1'
  await settle()
  assert.equal(context.state.value, 'error')
  assert.match(context.error.value.message, /offline/)
  scope.stop()
})

test('late context hydration cannot replace the state for a newer route', async () => {
  const { useRouteProject } = await loadRouteProjectModule()
  const oldResponse = deferred()
  const route = reactive({ params: { projectId: 'old-project' } })
  const store = {
    loadProject(projectId) {
      if (projectId === 'old-project') return oldResponse.promise
      return Promise.resolve({ id: projectId, title: '新项目', archivedAt: null })
    },
  }
  const scope = effectScope()
  const context = scope.run(() => useRouteProject({ route, store }))
  await nextTick()
  route.params.projectId = 'new-project'
  await settle()
  oldResponse.resolve({ id: 'old-project', title: '旧项目', archivedAt: null })
  await settle()

  assert.equal(context.state.value, 'active')
  assert.equal(context.project.value.id, 'new-project')
  scope.stop()
})

test('a rejected request for an older route is ignored after a newer route succeeds', async () => {
  const { useRouteProject } = await loadRouteProjectModule()
  const oldResponse = deferred()
  const route = reactive({ params: { projectId: 'old-project' } })
  const store = {
    loadProject(projectId) {
      if (projectId === 'old-project') return oldResponse.promise
      return Promise.resolve({ id: projectId, title: '新项目', archivedAt: null })
    },
  }
  const scope = effectScope()
  const context = scope.run(() => useRouteProject({ route, store }))
  await nextTick()
  route.params.projectId = 'new-project'
  await settle()
  oldResponse.reject(new Error('stale offline response'))
  await settle()

  assert.equal(context.state.value, 'active')
  assert.equal(context.project.value.id, 'new-project')
  scope.stop()
})

import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const readSource = relativePath => readFile(
  new URL(`../../src/${relativePath}`, import.meta.url),
  'utf8',
)

test('the active router delegates only to the canonical project route registry', async () => {
  const router = await readSource('router/index.js')
  const retiredViewPattern = new RegExp(
    ['Home', 'Project', 'Settings'].map(name => `${name}View`).join('|'),
  )

  assert.match(router, /projectRoutes/)
  assert.doesNotMatch(router, retiredViewPattern)
  assert.doesNotMatch(router, /path:\s*['"]\/project\/|path:\s*['"]\/writer\/|path:\s*['"]\/settings['"]/)
})

test('project overview renders explicit route hydration states', async () => {
  const [overview, archived, missing, context] = await Promise.all([
    readSource('views/ProjectOverviewView.vue'),
    readSource('views/ArchivedProjectStatusView.vue'),
    readSource('views/NotFoundView.vue'),
    readSource('composables/useRouteProject.js'),
  ])

  assert.match(overview, /useRouteProject/)
  assert.match(overview, /ArchivedProjectStatusView/)
  assert.match(overview, /NotFoundView/)
  for (const state of ['loading', 'active', 'archived', 'missing', 'error']) {
    assert.match(overview, new RegExp(`['"]${state}['"]`))
  }
  assert.match(archived, /恢复项目/)
  assert.match(archived, /返回项目库/)
  assert.match(archived, /expectedLifecycleRevision|lifecycleRevision/)
  assert.match(missing, /返回项目库/)
  assert.match(context, /route\.params\.projectId/)
  assert.doesNotMatch(context, /onBeforeUnmount|currentProject\s*=\s*null|invalidateOpenProject/)
})

test('project lifecycle state has no retired list delete or unmount invalidation surface', async () => {
  const [client, store] = await Promise.all([
    readSource('api/db/client.js'),
    readSource('stores/projectStore.js'),
  ])

  for (const method of [
    'listActive', 'listArchived', 'create', 'get', 'rename',
    'archive', 'restore', 'permanentlyDelete',
  ]) {
    assert.match(client, new RegExp(`${method}:`))
  }
  assert.doesNotMatch(client, /PROJECT_FIELDS|projects:\s*\{[^}]*\bdelete:/s)
  for (const state of ['activeProjects', 'archivedProjects', 'currentProject']) {
    assert.match(store, new RegExp(`const ${state} = ref\\(`))
  }
  assert.doesNotMatch(store, /invalidateOpenProject|function loadProjects|function openProject|function deleteProject/)
})

test('provider and project model settings have separate reachable surfaces', async () => {
  const [view, binding] = await Promise.all([
    readSource('views/ProviderSettingsView.vue'),
    readSource('components/project/settings/TaskModelBinding.vue'),
  ])

  assert.match(view, /ProviderSettings/)
  assert.match(binding, /projectId/)
  assert.match(binding, /useModelBindingStore/)
  assert.doesNotMatch(binding, /activeProjects|loadActiveProjects/)
})

test('the chapter workspace returns through the canonical project overview builder', async () => {
  const workspace = await readSource('views/ChapterWriterView.vue')

  assert.match(workspace, /projectOverviewPath/)
  assert.doesNotMatch(workspace, /router\.push\(`\/project\//)
})

test('project library routes mount the completed lifecycle interaction slice', async () => {
  const [library, archived] = await Promise.all([
    readSource('views/ProjectLibraryView.vue'),
    readSource('views/ArchivedProjectsView.vue'),
  ])

  assert.match(library, /ProjectCard/)
  assert.match(library, /ProjectNameDialog/)
  assert.match(library, /createProjectLibraryController/)
  assert.match(archived, /ProjectCard/)
  assert.match(archived, /createArchivedProjectsController/)
})

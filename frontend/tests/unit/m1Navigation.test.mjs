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

test('project overview renders explicit route and read-only archive states', async () => {
  const [overview, header, missing, context] = await Promise.all([
    readSource('views/ProjectOverviewView.vue'),
    readSource('components/projects/ProjectPageHeader.vue'),
    readSource('views/NotFoundView.vue'),
    readSource('composables/useRouteProject.js'),
  ])

  assert.match(overview, /useRouteProject/)
  assert.match(overview, /loadOverview/)
  assert.match(overview, /overview\.project\.lifecycle === 'archived'/)
  assert.match(overview, /NotFoundView/)
  for (const state of ['loading', 'archived', 'missing', 'error', 'stale']) {
    assert.match(overview, new RegExp(`['"]${state}['"]`))
  }
  assert.match(header, /已归档 · 只读/)
  assert.match(overview, /正在读取当前项目概览/)
  assert.match(overview, /项目概览暂时无法加载/)
  assert.match(overview, /项目不存在或已被删除/)
  assert.doesNotMatch(overview, /ArchivedProjectStatusView|ProjectBackupPanel/)
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

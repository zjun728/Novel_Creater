import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../..', import.meta.url))
const read = path => readFile(`${root}/${path}`, 'utf8')

test('blank project creation exposes complete long-form metadata', async () => {
  const source = await read('src/components/projects/ProjectCreateDialog.vue')
  for (const field of ['title', 'genre', 'description', 'targetWords', 'targetChapters']) {
    assert.match(source, new RegExp(`v-model(?:\\.number)?="form\\.${field}"`))
  }
  assert.match(source, /PROJECT_METADATA_DEFAULTS\.targetWords/)
  assert.match(source, /PROJECT_METADATA_DEFAULTS\.targetChapters/)
  assert.match(source, /默认 240 万字/)
  assert.match(source, /创建并打开/)
})

test('project settings exposes the five fields, CAS save, and archived read-only mode', async () => {
  const source = await read('src/views/ProjectSettingsView.vue')
  for (const field of ['title', 'genre', 'description', 'targetWords', 'targetChapters']) {
    assert.match(source, new RegExp(`form\\.${field}`))
  }
  assert.match(source, /expectedLifecycleRevision/)
  assert.match(source, /updateProjectSettings/)
  assert.match(source, /routeProject\.state\.value === 'archived'/)
  assert.match(source, /已归档项目资料只能查看/)
  assert.match(source, /onBeforeRouteUpdate/)
  assert.match(source, /beforeunload/)
  assert.match(source, /reload\(\{ force: true \}\)/)
})

test('revision-sensitive views refresh project authority after contract confirmation', async () => {
  const [wizard, exportView] = await Promise.all([
    read('src/components/project/CreationContractWizard.vue'),
    read('src/views/ProjectExportView.vue'),
  ])
  assert.match(wizard, /projectStore\.loadProject\(props\.projectId\)/)
  assert.match(exportView, /onMounted/)
  assert.match(exportView, /reload\(\{ force: true \}\)/)
})

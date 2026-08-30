import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { projectExportPath, projectRoutes } from '../../src/router/projectRoutes.js'

test('project export route is canonical, encoded, and mounts the dedicated page', () => {
  assert.equal(projectExportPath('project / 一'), '/projects/project%20%2F%20%E4%B8%80/settings/export')
  const route = projectRoutes.find(item => item.name === 'ProjectExport')
  assert.equal(route.path, '/projects/:projectId/settings/export')
  assert.equal(route.props, true)
})

test('export page composes existing delivery and backup capabilities without duplicating business logic', async () => {
  const source = await readFile(
    new URL('../../src/views/ProjectExportView.vue', import.meta.url),
    'utf8',
  )
  assert.match(source, /import NovelDownloadPanel/)
  assert.match(source, /import ProjectBackupPanel/)
  assert.match(source, /<novel-download-panel/)
  assert.match(source, /<project-backup-panel/)
  assert.match(source, /:project-id="routeProject\.project\.value\.id"/)
  assert.match(source, /:lifecycle-revision="routeProject\.project\.value\.lifecycleRevision"/)
  assert.doesNotMatch(source, /api\.|createNovelDownloadController|createProjectBackupController/)
})

test('export page exposes its asynchronous route failure as an alert', async () => {
  const source = await readFile(
    new URL('../../src/views/ProjectExportView.vue', import.meta.url),
    'utf8',
  )
  assert.match(
    source,
    /v-else-if="routeProject\.state\.value === 'error'"[\s\S]*?<n-result[\s\S]*?role="alert"/,
  )
})

import assert from 'node:assert/strict'
import { access, readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'

import { nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'


const frontendRoot = path.resolve(import.meta.dirname, '../..')

async function settle() {
  await nextTick()
  await new Promise(resolve => setImmediate(resolve))
  await nextTick()
}


test('canonical corpus asset route survives direct navigation and browser history', async () => {
  const { corpusLibraryPath, projectRoutes } = await import(
    '../../src/router/projectRoutes.js'
  )
  const router = createRouter({
    history: createMemoryHistory(),
    routes: projectRoutes.map(route => (
      ['StyleLibrary', 'CorpusLibrary'].includes(route.name)
        ? { ...route, component: { render: () => null } }
        : route
    )),
  })

  assert.equal(corpusLibraryPath(), '/assets/corpus')
  await router.push('/assets/styles')
  await router.isReady()
  await router.push('/assets/corpus')
  assert.equal(router.currentRoute.value.name, 'CorpusLibrary')
  router.back()
  await settle()
  assert.equal(router.currentRoute.value.name, 'StyleLibrary')
  router.forward()
  await settle()
  assert.equal(router.currentRoute.value.name, 'CorpusLibrary')
})


test('corpus lifecycle view owns explicit import, bounded preview, version history, and one eligible danger dialog', async () => {
  const files = [
    'src/views/assets/CorpusLibraryView.vue',
    'src/components/assets/CorpusImportDialog.vue',
    'src/components/assets/CorpusLifecycleMenu.vue',
  ]
  await Promise.all(files.map(file => access(path.join(frontendRoot, file))))
  const [view, importDialog, lifecycle] = await Promise.all(
    files.map(file => readFile(path.join(frontendRoot, file), 'utf8')),
  )

  assert.match(view, /版本历史|version/i)
  assert.match(view, /previewChars|1200/)
  assert.match(view, /referenceCount/)
  assert.match(importDialog, /displayName/)
  assert.match(importDialog, /referenceTags/)
  assert.match(importDialog, /notes/)
  assert.match(importDialog, /createDistinctSource/)
  assert.match(lifecycle, /deleteEligible/)
  assert.match(lifecycle, /deleteReason/)
  assert.equal((lifecycle.match(/type=["']error["']/g) || []).length, 1)
  assert.doesNotMatch(
    `${view}\n${importDialog}\n${lifecycle}`,
    /\bfetch\s*\(|localStorage|sessionStorage|type=["']file["']/,
  )
})

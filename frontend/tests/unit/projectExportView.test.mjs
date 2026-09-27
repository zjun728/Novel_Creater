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


test('fresh project refresh precedes the first delivery-panel mount', async () => {
  const Vue = await import('@vue/runtime-core')
  const { compileScript, parse } = await import('@vue/compiler-sfc')
  const source = await readFile(new URL('../../src/views/ProjectExportView.vue', import.meta.url), 'utf8')
  const { descriptor } = parse(source, { filename: 'ProjectExportView.vue' })
  let script = compileScript(descriptor, { id: 'export-mount-order', inlineTemplate: true }).content
  script = script.replace(/import\s+\{([^}]+)\}\s+from\s+['"]vue['"];?/gu,
    (_match, names) => `const { ${names.replace(/\s+as\s+/gu, ': ')} } = Vue;`)
  script = script.replace(/import\s+\{([^}]+)\}\s+from\s+['"]naive-ui['"];?/gu,
    (_match, names) => `const { ${names} } = dependencies;`)
  script = script.replace(/import\s+(\w+)\s+from\s+['"][^'"]+['"];?/gu,
    (_match, name) => `const ${name} = dependencies.${name};`)
  script = script.replace(/import\s+\{ useRouteProject \}\s+from\s+['"][^'"]+['"];?/gu,
    'const { useRouteProject } = dependencies;')
  assert.doesNotMatch(script, /\bimport\s/u)
  script = script.replace('export default', 'return')

  const mounts = []
  const unmounts = []
  const panel = name => Vue.defineComponent({
    props: ['projectId', 'lifecycleRevision'],
    setup(props) {
      Vue.onMounted(() => mounts.push([name, props.projectId, props.lifecycleRevision]))
      Vue.onBeforeUnmount(() => unmounts.push(name))
      return () => Vue.h('div')
    },
  })
  const stub = Vue.defineComponent({ setup: (_props, { slots }) => () => Vue.h('div', slots.default?.()) })
  let completeRefresh
  const refresh = new Promise(resolve => { completeRefresh = resolve })
  const reloads = []
  const context = {
    state: Vue.ref('active'),
    project: Vue.shallowRef({ id: 'project-1', title: 'Cached title', lifecycleRevision: 1 }),
    async reload(options) {
      reloads.push(options)
      context.state.value = 'loading'
      context.project.value = null
      context.project.value = await refresh
      context.state.value = 'active'
    },
  }
  const dependencies = {
    NButton: stub, NResult: stub, NSkeleton: stub, NotFoundView: stub,
    ProjectPageHeader: stub, NovelDownloadPanel: panel('download'), ProjectBackupPanel: panel('backup'),
    useRouteProject: () => context,
  }
  const View = new Function('Vue', 'dependencies', script)(Vue, dependencies)
  const node = type => ({ type, children: [], parent: null })
  const remove = child => {
    if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1)
    child.parent = null
  }
  const renderer = Vue.createRenderer({
    createElement: node, createText: node, createComment: node,
    setText() {}, setElementText() {}, patchProp() {},
    parentNode: item => item.parent, nextSibling: () => null,
    insert(child, parent, anchor = null) {
      remove(child); child.parent = parent
      const index = anchor ? parent.children.indexOf(anchor) : -1
      if (index < 0) parent.children.push(child)
      else parent.children.splice(index, 0, child)
    },
    remove,
  })
  const app = renderer.createApp(View)
  try {
    app.mount(node('root'))
    await Vue.nextTick()
    assert.deepEqual(reloads, [{ force: true }])
    assert.deepEqual(mounts, [])
    assert.deepEqual(unmounts, [])
    completeRefresh({ id: 'project-1', title: 'Fresh title', lifecycleRevision: 2 })
    await refresh
    await Vue.nextTick()
    assert.deepEqual(mounts, [['download', 'project-1', undefined], ['backup', 'project-1', 2]])
    assert.deepEqual(unmounts, [])
  } finally { app.unmount() }
})
